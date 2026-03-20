# workshop/integrations/telegram.py â€” UNIVERSAL TELEGRAM BOT (Feb 2026)
#
# What this file does (end-to-end flow)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 1) Startup
#    - Loads Telegram token + bot username from config/settings.py
#    - Loads personality config (config/personalC.json) and resolves the selected agent
#    - Initializes a Telegram Application (python-telegram-bot)
#    - Registers command handlers (/simple, /detailed, /series, etc.) and message handlers
#
# 2) Per-user isolation (memory + concurrency)
#    - Each Telegram user gets their own Agent instance: Agent(..., user_id=<telegram_user_id>)
#    - Each user has their own FIFO queue of pending prompts
#    - A per-user worker processes that queue sequentially (prevents one user from running parallel generations)
#
# 3) Responsiveness UX
#    - On each queued prompt, the bot immediately ACKs ("Got it â€” thinkingâ€¦")
#    - When the answer is ready, it edits the ACK message with the final reply
#    - If editing fails (message deleted, permissions, etc.), it falls back to sending a new reply
#    - /cancel cancels active generation and clears that userâ€™s pending queue
#
# 4) Text routing
#    - Mentions, replies to bot messages, and alias triggers are normalized into a clean user prompt
#    - Prompts are enqueued (not executed inline) to avoid blocking Telegramâ€™s event loop
#    - The worker calls agent.generate_response(...) under a global text semaphore
#
# 5) Photo routing
#    - Incoming photos are downloaded to sessions/<uid>/images/
#    - If caption includes OCR/registry triggers:
#         - Single-image OCR â†’ process_registry_photo(...)
#         - Series OCR mode (owner-only) â†’ accumulates extracted entries, then /endseries exports Excel
#      Else:
#         - Vision fallback â†’ agent.analyze_image(...)
#    - All OCR/vision work is executed under a global OCR semaphore
#    - The downloaded photo is always deleted in a finally block
#
# Security model (practical, abuse-resistant)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# A) Owner allowlist (TELEGRAM_BOT_OWNER_IDS)
#    - A set of Telegram user IDs considered â€œtrustedâ€
#    - Owners bypass most throttles and can use /series high-volume OCR
#    - Public users are gated to prevent compute abuse and â€œfree serviceâ€ exploitation
#
# B) Prompt bomb protection (public users)
#    - Hard cap on incoming text length (MAX_INCOMING_TEXT_CHARS)
#    - Per-user text rate limiter (token bucket) to reduce spam/overload
#    - Per-user queue cap: if a user builds too much backlog, queue is cleared
#
# C) Open-proxy / free crawler protection (public users)
#    - URL-heavy prompts are blocked (too many links)
#    - Link-only prompts are blocked (prevents â€œsummarize this URLâ€ proxying)
#    - This reduces abuse where attackers try to turn the bot into a web fetcher
#    - SearXNG remains bound to localhost (in searxng.py) so only the bot can use it
#
# D) OCR/vision abuse protection
#    - Per-user photo/OCR rate limiter (strict for public, loose for owners)
#    - File size cap for uploaded photos (public stricter than owners)
#    - Global OCR semaphore limits concurrent OCR/vision jobs across ALL users
#
# E) Global concurrency governors (stability under load)
#    - global_text_sem limits concurrent LLM generations
#    - global_ocr_sem limits concurrent OCR/vision operations (more expensive)
#    - This prevents multi-user spikes from crashing GPU/CPU/RAM
#
# Result: The bot stays responsive for normal users, remains powerful for owners/admins,
# and is harder to abuse as a free OCR farm or web proxy.


import asyncio
import json
import logging
import re
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from collections import defaultdict, deque

import pandas as pd
try:
    from telegram import Update
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
    TELEGRAM_SDK_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency surface
    Update = Any  # type: ignore[misc,assignment]
    Application = None  # type: ignore[assignment]
    CommandHandler = None  # type: ignore[assignment]
    MessageHandler = None  # type: ignore[assignment]
    filters = None  # type: ignore[assignment]

    class _ContextTypesFallback:
        DEFAULT_TYPE = Any

    ContextTypes = _ContextTypesFallback()  # type: ignore[assignment]
    TELEGRAM_SDK_AVAILABLE = False

from agents import Agent
from config.settings import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_BOT_USERNAME,
    TELEGRAM_AGENT_ALIASES,
    OCR_TRIGGERS,
    REGISTRY_TRIGGERS,
    TELEGRAM_BOT_OWNER_IDS,  # âœ… owner allowlist (iterable of ints)
)

from config.extraction_schema import (
    EXTRACTION_FIELDS,
    POST_PROCESSING,
    OUTPUT_COLUMNS
)
from gateway import GatewayService
from state import SessionEventStore
from workshop.toolbox.runtime import InternalToolRuntime
from workshop.integrations.telegram_runtime import (
    TelegramRuntimeBridge,
    build_telegram_delivery_bundle,
    build_telegram_progress_ack,
    build_telegram_reply_bundle,
    resolve_telegram_conversation_id,
)
from workshop.toolbox.stacks.ocr_core.document_intel import (
    SUPPORTED_DOCUMENT_SUFFIXES,
    build_document_note,
    extract_document_payload,
)

OCR_PIPELINE_READY = True

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")

# ----------------------------
# Security limits (tune here)
# ----------------------------
MAX_INCOMING_TEXT_CHARS = 4000           # prompt-bomb cap at Telegram entrypoint
MAX_URLS_NON_OWNER = 1                   # non-owners: URL-heavy prompts blocked
BLOCK_URL_ONLY_NON_OWNER = True          # blocks "summarize this link" style abuse for public
MAX_PHOTO_BYTES_NON_OWNER = 5_000_000    # 5MB; owners bypass
MAX_PHOTO_BYTES_OWNER = 20_000_000       # owners still capped to avoid insanity
MAX_DOCUMENT_BYTES_NON_OWNER = 8_000_000
MAX_DOCUMENT_BYTES_OWNER = 25_000_000

# URL detection for proxy-abuse gating
URL_RE = re.compile(r"(https?://\S+|www\.\S+)", re.IGNORECASE)

# ----------------------------
# Rate limiters (token buckets)
# ----------------------------
_TEXT_BUCKETS: Dict[str, tuple[float, float]] = {}   # uid -> (tokens, last_ts)
_PHOTO_BUCKETS: Dict[str, tuple[float, float]] = {}  # uid -> (tokens, last_ts)

def _allow_bucket(buckets: Dict[str, tuple[float, float]], uid: str, *, rate_per_sec: float, burst: float) -> bool:
    now = time.monotonic()
    tokens, last = buckets.get(uid, (burst, now))
    tokens = min(burst, tokens + (now - last) * rate_per_sec)
    if tokens < 1.0:
        buckets[uid] = (tokens, now)
        return False
    buckets[uid] = (tokens - 1.0, now)
    return True

def _allow_text(uid: str, is_owner: bool) -> bool:
    # Owners effectively unlimited at entrypoint.
    if is_owner:
        return True
    # ~0.6 msg/sec sustained, burst 3
    return _allow_bucket(_TEXT_BUCKETS, uid, rate_per_sec=0.6, burst=3.0)

def _allow_photo(uid: str, is_owner: bool) -> bool:
    if is_owner:
        # Owners: very loose gate (still prevents accidental runaway in group chats)
        return _allow_bucket(_PHOTO_BUCKETS, uid, rate_per_sec=1.0, burst=10.0)
    # Public: strict (about ~2/min sustained, burst 2)
    return _allow_bucket(_PHOTO_BUCKETS, uid, rate_per_sec=0.03, burst=2.0)

def sanitize_text(s: str, limit: int = 4000) -> str:
    s = (s or "").strip()
    s = CONTROL_CHAR_RE.sub("", s)
    s = re.sub(r"\n{4,}", "\n\n", s)
    s = re.sub(r"[ \t]{3,}", "  ", s)
    if len(s) > limit:
        s = s[:limit - 10].rstrip() + "â€¦"
    return s or "â€¦"

async def safe_edit_or_send(ack_msg, update: Update, text: str) -> None:
    text = sanitize_text(text, 4000)
    try:
        await ack_msg.edit_text(text)
        return
    except Exception:
        pass
    try:
        await update.message.reply_text(text)
    except Exception:
        pass


async def _send_telegram_file_bundle(update: Update, files: List[Dict[str, Any]]) -> int:
    sent = 0
    for item in list(files or []):
        path = str(item.get("path") or "").strip()
        if not path or not os.path.exists(path):
            continue
        caption_raw = str(item.get("caption") or item.get("title") or "").strip()
        caption = sanitize_text(caption_raw, 900) if caption_raw else ""
        file_name = os.path.basename(path)
        try:
            with open(path, "rb") as handle:
                await update.message.reply_document(
                    document=handle,
                    filename=file_name,
                    caption=caption or None,
                    parse_mode=None,
                )
            sent += 1
        except Exception as exc:
            logger.debug(f"Failed sending Telegram document attachment {file_name}: {exc}")
        finally:
            if bool(item.get("cleanup")):
                try:
                    os.remove(path)
                except Exception:
                    pass
    return sent


async def _send_telegram_visual_bundle(update: Update, attachments: List[Dict[str, Any]]) -> int:
    sent = 0
    for att in list(attachments or []):
        att_type = str(att.get("type") or "").strip().lower()
        path = str(att.get("path") or "").strip()
        if not path or not os.path.exists(path):
            continue
        try:
            if att_type == "image":
                with open(path, "rb") as handle:
                    await update.message.reply_photo(photo=handle, caption=(att.get("title") or ""))
                sent += 1
            elif att_type in {"document", "file", "text"}:
                sent += await _send_telegram_file_bundle(update, [att])
        except Exception as exc:
            logger.debug(f"Failed sending Telegram attachment {os.path.basename(path)}: {exc}")
        finally:
            if att_type == "image" and bool(att.get("cleanup")):
                try:
                    os.remove(path)
                except Exception:
                    pass
    return sent

def load_personalities(personality_config: str):
    try:
        with open(personality_config, "r", encoding="utf-8") as f:
            characters = json.load(f)
        alias_to_key = {}
        for key, config in characters.items():
            aliases = config.get("aliases", []) + [key, key.replace("Name: ", "")]
            for alias in aliases:
                alias_to_key[alias.lower()] = key
        return characters, alias_to_key
    except FileNotFoundError:
        logger.error(f"{personality_config} not found.")
        return {}, {}

class CacheManager:
    def __init__(self, cache_file: str):
        self.cache_file = cache_file
        os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
        self.cache: List[Dict] = self._load_cache()

    def _load_cache(self) -> List[Dict]:
        try:
            if not os.path.exists(self.cache_file):
                return []
            with open(self.cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading cache: {e}")
            return []

    def save_cache(self):
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving cache: {e}")

    def add_to_cache(self, message: str, timestamp: datetime):
        self.cache.append({"message": message, "timestamp": timestamp.isoformat()})
        if len(self.cache) > 5000:
            self.cache = self.cache[-5000:]
        self.save_cache()

    def clear_cache(self):
        self.cache = []
        self.save_cache()

    def get_recent_data(self, hours: int = 24) -> List[Dict]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        out = []
        for e in self.cache:
            try:
                ts = datetime.fromisoformat(e["timestamp"])
                if ts >= cutoff:
                    out.append(e)
            except Exception:
                continue
        return out

class TelegramHandler:
    def __init__(self, character_name: str, use_studies: bool = False):
        if not TELEGRAM_SDK_AVAILABLE:
            raise RuntimeError("Telegram integration requires python-telegram-bot to be installed")
        self.token = TELEGRAM_BOT_TOKEN
        if not self.token or self.token == "your_telegram_bot_token":
            raise ValueError("TELEGRAM_BOT_TOKEN must be set")

        self.personality_config = "config/personalC.json"
        self.characters, self.alias_to_key = load_personalities(self.personality_config)
        self.agent_key = self._resolve_agent_key(character_name)
        self.display_name = self.agent_key.replace("Name: ", "")

        self.bot_username = TELEGRAM_BOT_USERNAME
        self.bot_id = None

        self.use_studies = use_studies
        self.application = Application.builder().token(self.token).build()
        self.ocr_runtime = InternalToolRuntime()
        self.gateway_service = GatewayService(root_dir="sessions/gateway")
        self.state_store = SessionEventStore()
        self.runtime_bridge = TelegramRuntimeBridge(
            gateway_service=self.gateway_service,
            state_store=self.state_store,
        )
        self.gateway_session = self.gateway_service.register_session(
            user_id="default_user",
            surface="telegram",
            client_id="telegram-bot",
            client_label="Telegram Bot",
            platform="python-telegram-bot",
            auth_mode="service",
            metadata={"persona": self.display_name},
        )

        # âœ… Owners
        try:
            self.owner_ids = {str(int(x)) for x in (TELEGRAM_BOT_OWNER_IDS or [])}
        except Exception:
            self.owner_ids = set()

        # âœ… per-user agents and settings
        self.agents: Dict[str, Agent] = {}
        self.user_settings: Dict[str, Dict[str, bool]] = defaultdict(lambda: {
            "simple": False,
            "detailed": False,
            "postictal": False,
        })

        # âœ… per-user queue + active task
        self.user_queues: Dict[str, deque] = defaultdict(deque)
        self.user_tasks: Dict[str, asyncio.Task] = {}
        self.user_cancel_flags: Dict[str, bool] = defaultdict(bool)
        self.user_active_threads: Dict[str, Dict[str, str]] = {}
        self.queue_cap_per_user = 20

        # âœ… Split global governors
        # Text generation can be a bit higher; OCR/vision should be conservative.
        self.global_text_sem = asyncio.Semaphore(8)
        self.global_ocr_sem = asyncio.Semaphore(2)

        # Series mode
        self.series_sessions = defaultdict(list)      # user_id â†’ list of dicts
        self.active_series_users = set()

        # Handlers
        self.application.add_handler(CommandHandler("clearcache", self.clearcache_command))
        self.application.add_handler(CommandHandler("hotcoins", self.hotcoins_command))

        # UX commands
        self.application.add_handler(CommandHandler("simple", self.simple_command))
        self.application.add_handler(CommandHandler("detailed", self.detailed_command))
        self.application.add_handler(CommandHandler("postictal", self.postictal_command))
        self.application.add_handler(CommandHandler("normal", self.normal_command))
        self.application.add_handler(CommandHandler("clear", self.clear_command))
        self.application.add_handler(CommandHandler("cancel", self.cancel_command))
        self.application.add_handler(CommandHandler("code", self.code_command))

        self.application.add_handler(CommandHandler("memory", self.memory_command))
        self.application.add_handler(CommandHandler("pin", self.pin_command))
        self.application.add_handler(CommandHandler("forget", self.forget_command))

        # Series OCR mode (OWNER ONLY)
        self.application.add_handler(CommandHandler("series", self.start_series))
        self.application.add_handler(CommandHandler("endseries", self.end_series))

        # Core message routes
        self.application.add_handler(MessageHandler(filters.REPLY & filters.TEXT & ~filters.COMMAND, self.handle_reply))
        self.application.add_handler(MessageHandler(filters.Mention(self.bot_username), self.handle_mention))

        if TELEGRAM_AGENT_ALIASES:
            pattern = re.compile(r"\b(" + "|".join(map(re.escape, TELEGRAM_AGENT_ALIASES)) + r")\b", re.IGNORECASE)
            self.application.add_handler(
                MessageHandler(filters.Regex(pattern) & filters.TEXT & ~filters.COMMAND, self.handle_alias_mention)
            )

        self.application.add_handler(MessageHandler(filters.PHOTO, self.handle_photo))
        self.application.add_handler(MessageHandler(filters.Document.ALL, self.handle_document))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_all_messages))

    def _resolve_agent_key(self, name: str) -> str:
        if not name:
            return "Name: Somi"
        if name in self.characters:
            return name
        nl = name.lower()
        if nl in self.alias_to_key:
            return self.alias_to_key[nl]
        return "Name: Somi"

    def _uid(self, update: Update) -> str:
        return str(update.effective_user.id)

    def _is_owner(self, uid: str) -> bool:
        return uid in self.owner_ids

    def _user_dir(self, uid: str) -> str:
        base = os.path.join("sessions", uid)
        os.makedirs(base, exist_ok=True)
        return base

    def _cache_manager(self, uid: str) -> CacheManager:
        cache_file = os.path.join(self._user_dir(uid), "cache", "telegram_cache.json")
        return CacheManager(cache_file)

    def _images_dir(self, uid: str) -> str:
        p = os.path.join(self._user_dir(uid), "images")
        os.makedirs(p, exist_ok=True)
        return p

    def _documents_dir(self, uid: str) -> str:
        p = os.path.join(self._user_dir(uid), "documents")
        os.makedirs(p, exist_ok=True)
        return p

    def _safe_filename(self, name: str, *, fallback: str = "document.bin") -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name or "").strip())
        return cleaned[:120] or fallback

    def _get_agent(self, uid: str) -> Agent:
        if uid in self.agents:
            return self.agents[uid]
        agent = Agent(self.agent_key, use_studies=self.use_studies, user_id=uid)
        self.agents[uid] = agent
        return agent

    def _conversation_id(self, update: Update) -> str:
        chat_id = getattr(getattr(update, "effective_chat", None), "id", "")
        thread_id = getattr(getattr(update, "message", None), "message_thread_id", "")
        return resolve_telegram_conversation_id(chat_id=chat_id, message_thread_id=thread_id)

    def _active_thread_state(self, uid: str) -> Dict[str, str]:
        return dict(self.user_active_threads.get(uid) or {})

    def _mark_thread_activity(self, *, uid: str, conversation_id: str, thread_id: str) -> None:
        self.user_active_threads[uid] = {
            "conversation_id": str(conversation_id or ""),
            "thread_id": str(thread_id or ""),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _ensure_user_surface_session(self, update: Update, *, uid: str, conversation_id: str, thread_id: str, queue_depth: int) -> dict:
        user = getattr(update, "effective_user", None)
        username = str(getattr(user, "username", "") or "").strip()
        first_name = str(getattr(user, "first_name", "") or "").strip()
        last_name = str(getattr(user, "last_name", "") or "").strip()
        display_name = " ".join([part for part in [first_name, last_name] if part]).strip() or username or f"Telegram {uid}"
        chat_type = str(getattr(getattr(update, "effective_chat", None), "type", "") or "telegram")
        return self.runtime_bridge.upsert_surface_session(
            user_id=uid,
            client_label=display_name,
            username=username,
            chat_type=chat_type,
            conversation_id=conversation_id,
            thread_id=thread_id,
            is_owner=self._is_owner(uid),
            queue_depth=queue_depth,
        )

    def _run_ocr_tool(self, *, uid: str, image_paths: List[str], caption: str, mode: str) -> dict:
        payload = {
            "action": "run",
            "mode": str(mode or "auto"),
            "image_paths": list(image_paths or []),
            "options": {"caption": str(caption or "")},
        }
        return self.ocr_runtime.run("ocr.extract", payload, {"source": "telegram", "approved": True, "user_id": uid})

    def _gateway_touch(self, *, activity: str, detail: str = "", status: str = "online", metadata: dict | None = None) -> None:
        try:
            self.gateway_service.touch_session(str((self.gateway_session or {}).get("session_id") or ""), status=status)
            self.gateway_service.update_presence(
                session_id=str((self.gateway_session or {}).get("session_id") or ""),
                status=status,
                activity=activity,
                detail=detail,
                metadata=dict(metadata or {}),
            )
        except Exception:
            pass

    def _gateway_event(
        self,
        *,
        uid: str = "",
        event_type: str,
        title: str,
        body: str = "",
        level: str = "info",
        metadata: dict | None = None,
    ) -> None:
        try:
            self.gateway_service.publish_event(
                event_type=event_type,
                surface="telegram",
                title=title,
                body=body,
                level=level,
                user_id=uid,
                session_id=str((self.gateway_session or {}).get("session_id") or ""),
                client_id=str((self.gateway_session or {}).get("client_id") or ""),
                metadata=dict(metadata or {}),
            )
        except Exception:
            pass


    async def validate_bot_username(self):
        bot = await self.application.bot.get_me()
        actual = f"@{bot.username}"
        if actual != self.bot_username:
            logger.warning(f"Correcting username: {self.bot_username} â†’ {actual}")
            self.bot_username = actual
        self.bot_id = bot.id
        self._gateway_touch(activity=f"persona:{self.display_name}", detail=self.bot_username, metadata={"bot_id": self.bot_id})
        try:
            self.gateway_service.record_health(
                service_id="telegram-bot",
                surface="telegram",
                status="online",
                summary=f"{self.bot_username} ready",
                metadata={"bot_id": self.bot_id},
            )
        except Exception:
            pass

    # -----------------------
    # Basic cache commands
    # -----------------------

    async def clearcache_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = self._uid(update)
        self._cache_manager(uid).clear_cache()
        await update.message.reply_text("Cache cleared.")

    async def hotcoins_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = self._uid(update)
        data = self._cache_manager(uid).get_recent_data(24)
        if not data:
            await update.message.reply_text("No messages in last 24h.")
            return
        coins = self._analyze_hot_coins(data)
        if not coins:
            await update.message.reply_text("No hot coins.")
            return
        await update.message.reply_text("Hot coins (24h):\n" + "\n".join(f"{c}: {n}" for c, n in coins.items()))

    # -----------------------
    # UX commands
    # -----------------------

    async def simple_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = self._uid(update)
        self.user_settings[uid]["simple"] = True
        self.user_settings[uid]["detailed"] = False
        await update.message.reply_text("Simple mode ON. (/normal to reset)")

    async def detailed_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = self._uid(update)
        self.user_settings[uid]["detailed"] = True
        self.user_settings[uid]["simple"] = False
        await update.message.reply_text("Detailed mode ON. (/normal to reset)")

    async def postictal_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = self._uid(update)
        self.user_settings[uid]["postictal"] = True
        await update.message.reply_text("Postictal mode ON (short, clear, calm). (/normal to reset)")

    async def normal_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = self._uid(update)
        self.user_settings[uid]["simple"] = False
        self.user_settings[uid]["detailed"] = False
        self.user_settings[uid]["postictal"] = False
        await update.message.reply_text("Back to normal mode.")

    async def clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = self._uid(update)
        agent = self._get_agent(uid)
        agent.clear_short_term_history()
        await update.message.reply_text("Cleared short-term conversation context.")

    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = self._uid(update)
        self.user_cancel_flags[uid] = True
        t = self.user_tasks.get(uid)
        if t and not t.done():
            t.cancel()
        queued = list(self.user_queues[uid])
        self.user_queues[uid].clear()
        for item in queued:
            if len(item) >= 4 and str(item[3] or "").strip():
                try:
                    self._get_agent(uid).ops_control.fail_background_task(
                        str(item[3]),
                        error="Cancelled from Telegram before execution.",
                        recoverable=False,
                        recommended_action="Send a fresh request when ready.",
                    )
                except Exception:
                    pass
        await update.message.reply_text("Cancelled current task and cleared queued messages.")

    async def code_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        objective = " ".join(list(getattr(context, "args", []) or [])).strip()
        prompt = f"/code {objective}".strip() if objective else "/code"
        await self._enqueue_user_job(update, prompt)

    async def memory_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = self._uid(update)
        agent = self._get_agent(uid)
        try:
            items = await agent.memory.list_recent_memories(uid, limit=15)
        except Exception:
            items = []
        if not items:
            await update.message.reply_text("No stored memories yet.")
            return

        lines = []
        for it in items[:15]:
            ts = (it.get("ts") or "")[:19].replace("T", " ")
            typ = it.get("type") or "facts"
            content = it.get("content") or ""
            lines.append(f"- [{typ}] {content}" + (f" ({ts} UTC)" if ts else ""))

        msg = "Recent memories:\n" + "\n".join(lines)
        await update.message.reply_text(sanitize_text(msg, 3900))

    async def pin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = self._uid(update)
        agent = self._get_agent(uid)
        text = (update.message.text or "").strip()
        arg = text.partition(" ")[2].strip()
        if not arg:
            await update.message.reply_text("Usage: /pin <instruction to remember>")
            return
        ok = await agent.memory.pin_instruction(uid, arg, source="telegram")
        await update.message.reply_text("Pinned." if ok else "Couldn't pin that.")

    async def forget_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = self._uid(update)
        agent = self._get_agent(uid)
        text = (update.message.text or "").strip()
        arg = text.partition(" ")[2].strip()
        if not arg:
            await update.message.reply_text("Usage: /forget <topic/phrase>")
            return
        ok = await agent.memory.forget_phrase(uid, arg, source="telegram")
        await update.message.reply_text("Okay â€” Iâ€™ll avoid using that memory going forward." if ok else "Couldn't apply forget.")

    # -----------------------
    # Series mode (OWNER ONLY)
    # -----------------------

    async def start_series(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = self._uid(update)
        if not self._is_owner(uid):
            await update.message.reply_text("Series mode is restricted.")
            return

        user_id = update.effective_user.id
        self.active_series_users.add(user_id)
        self.series_sessions[user_id] = []
        await update.message.reply_text(
            "Series mode activated!\n\n"
            "Send photos one by one with your trigger word in caption.\n"
            "When finished â†’ /endseries â†’ get one Excel with all records."
        )

    async def end_series(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = self._uid(update)
        if not self._is_owner(uid):
            await update.message.reply_text("Series mode is restricted.")
            return

        user_id = update.effective_user.id
        if user_id not in self.active_series_users:
            await update.message.reply_text("You weren't in series mode.")
            return

        entries = self.series_sessions.get(user_id, [])
        if not entries:
            await update.message.reply_text("No records collected.")
        else:
            await update.message.reply_text("Generating Excel for series...")
            await self._send_combined_excel(entries, update)
            await update.message.reply_text(f"Done. Sent Excel with {len(entries)} record(s).")

        self.active_series_users.discard(user_id)
        self.series_sessions.pop(user_id, None)

    async def _send_combined_excel(self, entries: list, update: Update):
        if not entries:
            return

        df = pd.DataFrame(entries)
        df = df.reindex(columns=OUTPUT_COLUMNS, fill_value="")

        filename = f"Series_Form_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
        path = os.path.join(tempfile.gettempdir(), filename)

        try:
            df.to_excel(path, index=False, engine="openpyxl")
            with open(path, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    filename=filename,
                    caption=f"Full series â€¢ {len(df)} records â€¢ {len(df.columns)} fields"
                )
            logger.info(f"[Series] Sent {len(df)} records")
        except Exception as e:
            logger.error(f"[Series] Excel failed: {e}")
            await update.message.reply_text("Could not create Excel file.")
        finally:
            try:
                os.remove(path)
            except Exception:
                pass

    # -----------------------
    # Core message handlers
    # -----------------------

    def _is_relevant_message(self, message: str) -> bool:
        patterns = [
            r"\$[a-zA-Z]{2,6}\b",
            r"\b(bot|improve|enhance|suggest)\b",
            r"\b(event|war|market|crash|news)\b",
            r"\b(trade|buy|sell|price|volume)\b"
        ]
        return any(re.search(p, message or "", re.IGNORECASE) for p in patterns)

    def _analyze_hot_coins(self, data: List[Dict]) -> Dict[str, int]:
        mentions = {}
        for entry in data:
            for coin in re.findall(r"\$[a-zA-Z]{2,6}\b", entry.get("message", ""), re.IGNORECASE):
                mentions[coin.lower()] = mentions.get(coin.lower(), 0) + 1
        return dict(sorted(mentions.items(), key=lambda x: x[1], reverse=True)[:5])

    async def handle_all_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = self._uid(update)
        text = update.message.text or ""
        if self._is_relevant_message(text):
            self._cache_manager(uid).add_to_cache(text, update.message.date)

    async def handle_mention(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = self._uid(update)
        text = update.message.text or ""
        if self._is_relevant_message(text):
            self._cache_manager(uid).add_to_cache(text, update.message.date)

        clean = re.sub(re.escape(self.bot_username), "", text, flags=re.IGNORECASE).strip()
        await self._enqueue_user_job(update, clean)

    async def handle_alias_mention(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = self._uid(update)
        text = update.message.text or ""
        if self._is_relevant_message(text):
            self._cache_manager(uid).add_to_cache(text, update.message.date)

        clean = text
        for a in TELEGRAM_AGENT_ALIASES:
            clean = re.sub(rf"\b{re.escape(a)}\b", "", clean, flags=re.IGNORECASE).strip()
        await self._enqueue_user_job(update, clean)

    async def handle_reply(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.reply_to_message and self.bot_id and update.message.reply_to_message.from_user.id == self.bot_id:
            uid = self._uid(update)
            text = update.message.text or ""
            if self._is_relevant_message(text):
                self._cache_manager(uid).add_to_cache(text, update.message.date)
            await self._enqueue_user_job(update, text.strip())

    # -----------------------
    # Queue + worker
    # -----------------------

    def _url_stats(self, text: str) -> tuple[int, bool]:
        urls = URL_RE.findall(text or "")
        url_count = len(urls)
        stripped = (text or "").strip()
        # "URL only" if the message is mostly a URL + tiny surrounding text
        url_only = False
        if url_count == 1:
            cleaned = URL_RE.sub("", stripped).strip()
            url_only = (len(cleaned) <= 20)
        return url_count, url_only

    async def _enqueue_user_job(self, update: Update, text: str):
        uid = self._uid(update)
        is_owner = self._is_owner(uid)
        conversation_id = self._conversation_id(update)

        text = (text or "").strip()
        if not text:
            return

        # 2) Prompt bomb protection (hard cap)
        if not is_owner and len(text) > MAX_INCOMING_TEXT_CHARS:
            await update.message.reply_text("Too long. Send a shorter prompt.")
            return

        # 3) Open proxy / crawler abuse protection (URL-heavy prompts)
        url_count, url_only = self._url_stats(text)
        if not is_owner:
            if url_count > MAX_URLS_NON_OWNER:
                await update.message.reply_text("Too many links in one message. Send at most 1 URL.")
                return
            if BLOCK_URL_ONLY_NON_OWNER and url_only:
                await update.message.reply_text(
                    "Link-only requests are restricted. Please ask a specific question without just dropping a URL."
                )
                return

        # per-user text rate limiting at entrypoint (owner bypass)
        if not _allow_text(uid, is_owner=is_owner):
            await update.message.reply_text("Slow down â€” you're sending too fast. Try again in a moment.")
            return

        # queue cap
        if len(self.user_queues[uid]) >= self.queue_cap_per_user:
            self.user_queues[uid].clear()
            await update.message.reply_text(
                "Too many queued messages â€” queue cleared. Send 1 prompt at a time, or use /cancel."
            )
            return

        active_state = self._active_thread_state(uid)
        thread_id = self.runtime_bridge.resolve_thread_id(
            user_id=uid,
            prompt=text,
            conversation_id=conversation_id,
            active_thread_id=str(active_state.get("thread_id") or ""),
            active_conversation_id=str(active_state.get("conversation_id") or ""),
            active_updated_at=str(active_state.get("updated_at") or ""),
        )
        reused_thread = bool(active_state.get("thread_id")) and thread_id == str(active_state.get("thread_id") or "")
        agent = self._get_agent(uid)
        task_row = agent.ops_control.create_background_task(
            user_id=uid,
            objective=text,
            task_type="telegram_chat",
            surface="telegram",
            thread_id=thread_id,
            meta={
                "conversation_id": conversation_id,
                "owner": is_owner,
            },
        )
        task_id = str(task_row.get("task_id") or "")
        session = self._ensure_user_surface_session(
            update,
            uid=uid,
            conversation_id=conversation_id,
            thread_id=thread_id,
            queue_depth=len(self.user_queues[uid]) + 1,
        )
        self.user_queues[uid].append((update, text, thread_id, task_id, conversation_id, str(session.get("session_id") or ""), reused_thread))
        self._mark_thread_activity(uid=uid, conversation_id=conversation_id, thread_id=thread_id)
        self._gateway_touch(
            activity=f"queued:{uid}",
            detail=f"depth={len(self.user_queues[uid])}",
            metadata={"thread_id": thread_id, "task_id": task_id},
        )
        self.gateway_service.record_prompt_ingress(
            surface="telegram",
            user_id=uid,
            text=text,
            session_id=str(session.get("session_id") or ""),
            client_id=str(session.get("client_id") or ""),
            thread_id=thread_id,
            metadata={
                "queue_depth": len(self.user_queues[uid]),
                "owner": is_owner,
                "conversation_id": conversation_id,
                "task_id": task_id,
            },
        )

        # worker already running â†’ acknowledge
        if uid in self.user_tasks and not self.user_tasks[uid].done():
            await update.message.reply_text(
                build_telegram_progress_ack(
                    queue_depth=len(self.user_queues[uid]),
                    reused_thread=reused_thread,
                    active_task=True,
                )
            )
            return

        self.user_cancel_flags[uid] = False
        t = asyncio.create_task(self._user_worker(uid))
        self.user_tasks[uid] = t

    async def _user_worker(self, uid: str):
        while self.user_queues[uid]:
            if self.user_cancel_flags[uid]:
                self.user_queues[uid].clear()
                return

            update, text, thread_id, task_id, conversation_id, session_id, reused_thread = self.user_queues[uid].popleft()
            agent = self._get_agent(uid)
            settings = self.user_settings[uid]

            dementia_friendly = bool(settings.get("simple") or settings.get("postictal"))
            long_form = bool(settings.get("detailed"))

            ack = await update.message.reply_text(
                build_telegram_progress_ack(
                    queue_depth=len(self.user_queues[uid]),
                    reused_thread=reused_thread,
                    active_task=False,
                )
            )
            self._gateway_touch(
                activity=f"responding:{uid}",
                detail=text[:120],
                metadata={"thread_id": thread_id, "task_id": task_id},
            )
            try:
                agent.ops_control.heartbeat_background_task(
                    task_id,
                    summary="Generating Telegram reply.",
                    meta={
                        "conversation_id": conversation_id,
                        "queue_depth": len(self.user_queues[uid]),
                    },
                )
            except Exception:
                pass
            try:
                self.gateway_service.update_presence(
                    session_id=session_id,
                    status="online",
                    activity="telegram_reply_running",
                    detail=f"{thread_id[:8]} :: {text[:72]}",
                    metadata={"task_id": task_id, "conversation_id": conversation_id},
                )
            except Exception:
                pass

            try:
                async with self.global_text_sem:
                    agent._last_request_source = "telegram"
                    resp, attachments = await asyncio.wait_for(
                        agent.generate_response_with_attachments(
                            text,
                            user_id=uid,
                            dementia_friendly=dementia_friendly,
                            long_form=long_form,
                            thread_id_override=thread_id,
                            trace_metadata={
                                "surface": "telegram",
                                "conversation_id": conversation_id,
                                "task_id": task_id,
                                "gateway_session_id": session_id,
                            },
                        ),
                        timeout=150,
                    )
                report = dict(getattr(getattr(agent, "websearch", None), "last_browse_report", {}) or {})
                route = self.runtime_bridge.latest_route(user_id=uid, thread_id=thread_id)
                continuity = self.runtime_bridge.build_thread_capsule(
                    user_id=uid,
                    thread_id=thread_id,
                    active_thread_id=thread_id,
                )
                reply_bundle = build_telegram_delivery_bundle(
                    content=resp,
                    route=route,
                    browse_report=report,
                    thread_id=thread_id,
                    task_id=task_id,
                    continuity_report=continuity,
                )
                await safe_edit_or_send(ack, update, reply_bundle.get("primary", resp))
                for item in list(reply_bundle.get("follow_ups") or []):
                    clean = str(item or "").strip()
                    if clean:
                        await update.message.reply_text(clean, parse_mode=None)
                sent_exports = await _send_telegram_file_bundle(update, list(reply_bundle.get("exports") or []))
                sent_visuals = await _send_telegram_visual_bundle(update, list(attachments or []))
                try:
                    agent.ops_control.complete_background_task(
                        task_id,
                        summary=str(reply_bundle.get("summary") or resp[:220]),
                        handoff={
                            "surface": "telegram",
                            "thread_id": thread_id,
                            "resume_hint": "Say continue to keep going on this thread.",
                            "route": route,
                            "recommended_surface": str(continuity.get("recommended_surface") or "telegram"),
                            "surface_names": list(continuity.get("surface_names") or []),
                            "open_task_count": int(continuity.get("open_task_count") or 0),
                            "sources_count": len(list(report.get("sources") or [])),
                            "export_count": sent_exports,
                            "attachment_count": sent_visuals,
                        },
                    )
                except Exception:
                    pass
                self._mark_thread_activity(uid=uid, conversation_id=conversation_id, thread_id=thread_id)
                self._gateway_event(
                    uid=uid,
                    event_type="telegram_response",
                    title=f"Response sent to {uid}",
                    body=resp,
                    metadata={
                        "attachment_count": sent_visuals,
                        "export_count": sent_exports,
                        "thread_id": thread_id,
                        "task_id": task_id,
                        "route": route,
                    },
                )
                try:
                    self.gateway_service.update_presence(
                        session_id=session_id,
                        status="online",
                        activity="telegram_reply_completed",
                        detail=f"{thread_id[:8]} :: {route or 'chat'}",
                        metadata={"task_id": task_id, "thread_id": thread_id},
                    )
                except Exception:
                    pass

            except asyncio.CancelledError:
                await safe_edit_or_send(ack, update, "Cancelled.")
                try:
                    agent.ops_control.fail_background_task(
                        task_id,
                        error="Telegram task was cancelled.",
                        recoverable=False,
                        recommended_action="Restart the request when ready.",
                    )
                except Exception:
                    pass
                self._gateway_event(uid=uid, event_type="telegram_cancelled", title=f"Task cancelled for {uid}", level="warn")
                return

            except asyncio.TimeoutError:
                await safe_edit_or_send(
                    ack,
                    update,
                    "Timed out. Try again with a shorter prompt, or use /simple mode."
                )
                try:
                    agent.ops_control.fail_background_task(
                        task_id,
                        error="Telegram reply timed out.",
                        recoverable=True,
                        recommended_action="Retry with a shorter or more focused request.",
                    )
                except Exception:
                    pass
                self._gateway_event(uid=uid, event_type="telegram_timeout", title=f"Timeout for {uid}", level="warn")

            except Exception as e:
                await safe_edit_or_send(
                    ack,
                    update,
                    f"Error: {type(e).__name__}. Try again."
                )
                try:
                    agent.ops_control.fail_background_task(
                        task_id,
                        error=f"{type(e).__name__}: {e}",
                        recoverable=True,
                        recommended_action="Retry the request or simplify the prompt.",
                    )
                except Exception:
                    pass
                self._gateway_event(
                    uid=uid,
                    event_type="telegram_error",
                    title=f"{type(e).__name__} while responding",
                    body=str(e),
                    level="error",
                )

    # -----------------------
    # Photos (OCR/Vision gated)
    # -----------------------

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = self._uid(update)
        is_owner = self._is_owner(uid)
        user_id_int = update.effective_user.id

        # Strict photo/OCR rate limit for public; loose for owners
        if not _allow_photo(uid, is_owner=is_owner):
            await update.message.reply_text("Too many photo/OCR requests. Try again in a minute.")
            return

        photo_file = await update.message.photo[-1].get_file()

        # File size gate
        try:
            fs = getattr(photo_file, "file_size", 0) or 0
            limit = MAX_PHOTO_BYTES_OWNER if is_owner else MAX_PHOTO_BYTES_NON_OWNER
            if fs and fs > limit:
                await update.message.reply_text("Image too large. Please send a smaller/compressed photo.")
                return
        except Exception:
            pass

        img_dir = self._images_dir(uid)
        photo_path = os.path.join(img_dir, f"photo_{update.message.message_id}_{user_id_int}.jpg")

        # download
        await photo_file.download_to_drive(photo_path)

        # If Telegram didn't give file_size, enforce after download too
        try:
            limit = MAX_PHOTO_BYTES_OWNER if is_owner else MAX_PHOTO_BYTES_NON_OWNER
            if os.path.getsize(photo_path) > limit:
                try:
                    os.remove(photo_path)
                except Exception:
                    pass
                await update.message.reply_text("Image too large. Please send a smaller/compressed photo.")
                return
        except Exception:
            pass

        logger.info(f"[{uid}] Saved photo: {photo_path}")
        self._gateway_touch(activity=f"image:{uid}", detail=os.path.basename(photo_path))

        caption = (update.message.caption or "").lower()
        triggers = [x.lower() for x in (OCR_TRIGGERS or []) + (REGISTRY_TRIGGERS or [])]
        is_ocr_request = any(t in caption for t in triggers)
        self._gateway_event(
            uid=uid,
            event_type="telegram_image",
            title=f"Image received from {uid}",
            body=caption or "image upload",
            metadata={"ocr_requested": is_ocr_request},
        )

        try:
            # SERIES MODE OCR (OWNER ONLY) â€” unchanged internals, just gated
            if user_id_int in self.active_series_users and is_ocr_request and OCR_PIPELINE_READY:
                if not is_owner:
                    await update.message.reply_text("Series OCR is restricted.")
                    return

                await update.message.reply_text("Adding page to seriesâ€¦")

                async with self.global_ocr_sem:
                    result = await asyncio.to_thread(
                        self._run_ocr_tool,
                        uid=uid,
                        image_paths=[photo_path],
                        caption=caption,
                        mode="structured",
                    )

                entries = list((result or {}).get("structured_records") or [])

                if entries:
                    self.series_sessions[user_id_int].extend(entries)
                    await update.message.reply_text(
                        f"Added {len(entries)} record(s)\n"
                        f"Total so far: {len(self.series_sessions[user_id_int])}"
                    )
                else:
                    await update.message.reply_text("No records found on this page.")
                return

            # SINGLE IMAGE OCR â€” public allowed but globally throttled
            if is_ocr_request and OCR_PIPELINE_READY:
                ack = await update.message.reply_text("Analyzing formâ€¦")
                async with self.global_ocr_sem:
                    result = await asyncio.to_thread(
                        self._run_ocr_tool,
                        uid=uid,
                        image_paths=[photo_path],
                        caption=caption,
                        mode="auto",
                    )
                body = str((result or {}).get("structured_text") or "") or str((result or {}).get("raw_text") or "")
                msg = body or "No text extracted."
                exports = dict((result or {}).get("exports") or {})
                if exports.get("excel_path"):
                    msg += f"\n\nExcel saved: {exports['excel_path']}"
                await update.message.reply_text(msg, parse_mode=None)
                try:
                    await ack.delete()
                except Exception:
                    pass
                return

            # NORMAL VISION FALLBACK â€” globally throttled
            agent = self._get_agent(uid)
            ack = await update.message.reply_text("Got it â€” analyzing imageâ€¦")
            try:
                async with self.global_ocr_sem:
                    resp = await asyncio.wait_for(
                        agent.analyze_image(
                            photo_path,
                            update.message.caption or "Describe this image.",
                            user_id=uid
                        ),
                        timeout=210,
                    )
                await safe_edit_or_send(ack, update, resp)
            except asyncio.TimeoutError:
                await safe_edit_or_send(ack, update, "Image analysis timed out. Try a clearer photo or smaller request.")
            except Exception as e:
                logger.error(f"[{uid}] Vision failed: {e}")
                await safe_edit_or_send(ack, update, "Could not analyze image.")
            return

        finally:
            try:
                os.remove(photo_path)
            except Exception:
                pass

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = self._uid(update)
        is_owner = self._is_owner(uid)
        document = getattr(getattr(update, "message", None), "document", None)
        if document is None:
            return

        if not _allow_photo(uid, is_owner=is_owner):
            await update.message.reply_text("Too many document requests. Try again in a minute.")
            return

        file_name = self._safe_filename(getattr(document, "file_name", "") or f"document_{getattr(document, 'file_id', 'upload')}")
        suffix = Path(file_name).suffix.lower()
        if suffix not in SUPPORTED_DOCUMENT_SUFFIXES:
            supported = ", ".join(sorted(SUPPORTED_DOCUMENT_SUFFIXES))
            await update.message.reply_text(f"I can currently read these document types here: {supported}")
            return

        file_size = int(getattr(document, "file_size", 0) or 0)
        limit = MAX_DOCUMENT_BYTES_OWNER if is_owner else MAX_DOCUMENT_BYTES_NON_OWNER
        if file_size and file_size > limit:
            await update.message.reply_text("Document too large. Send a smaller PDF or text-based file.")
            return

        conversation_id = self._conversation_id(update)
        caption = str(getattr(update.message, "caption", "") or "").strip()
        prompt = caption or f"Summarize this document and highlight the important points: {file_name}"
        active_state = self._active_thread_state(uid)
        thread_id = self.runtime_bridge.resolve_thread_id(
            user_id=uid,
            prompt=prompt,
            conversation_id=conversation_id,
            active_thread_id=str(active_state.get("thread_id") or ""),
            active_conversation_id=str(active_state.get("conversation_id") or ""),
            active_updated_at=str(active_state.get("updated_at") or ""),
        )
        agent = self._get_agent(uid)
        task_row = agent.ops_control.create_background_task(
            user_id=uid,
            objective=prompt,
            task_type="telegram_document",
            surface="telegram",
            thread_id=thread_id,
            meta={"conversation_id": conversation_id, "file_name": file_name, "owner": is_owner},
        )
        task_id = str(task_row.get("task_id") or "")
        session = self._ensure_user_surface_session(
            update,
            uid=uid,
            conversation_id=conversation_id,
            thread_id=thread_id,
            queue_depth=0,
        )
        self._mark_thread_activity(uid=uid, conversation_id=conversation_id, thread_id=thread_id)
        self._gateway_event(
            uid=uid,
            event_type="telegram_document",
            title=f"Document received from {uid}",
            body=file_name,
            metadata={"thread_id": thread_id, "task_id": task_id, "suffix": suffix},
        )

        doc_dir = self._documents_dir(uid)
        doc_path = os.path.join(doc_dir, f"{update.message.message_id}_{file_name}")
        ack = await update.message.reply_text("Reading document...")
        try:
            tg_file = await document.get_file()
            await tg_file.download_to_drive(doc_path)
            if os.path.getsize(doc_path) > limit:
                await safe_edit_or_send(ack, update, "Document too large. Send a smaller PDF or text-based file.")
                agent.ops_control.fail_background_task(
                    task_id,
                    error="Document exceeded size limit after download.",
                    recoverable=False,
                    recommended_action="Retry with a smaller file.",
                )
                return

            try:
                agent.ops_control.heartbeat_background_task(
                    task_id,
                    summary=f"Extracting text from {file_name}.",
                    meta={"thread_id": thread_id, "conversation_id": conversation_id},
                )
            except Exception:
                pass

            async with self.global_ocr_sem:
                payload = await asyncio.to_thread(
                    extract_document_payload,
                    doc_path,
                    max_chars=5000,
                    max_pdf_pages=6,
                )

            note = build_document_note(payload)
            if not bool(payload.get("ok")):
                message = note or "I couldn't extract readable text from that document yet."
                await safe_edit_or_send(ack, update, message)
                try:
                    agent.ops_control.fail_background_task(
                        task_id,
                        error=str(payload.get("error") or "document_extract_failed"),
                        recoverable=False,
                        recommended_action=str(payload.get("manual_review_message") or "Try a text-based export or send page screenshots."),
                    )
                except Exception:
                    pass
                return

            excerpt = str(payload.get("excerpt") or "").strip()
            doc_prompt = (
                f"{prompt}\n\n"
                f"{note}\n\n"
                "Document excerpt:\n"
                f"{excerpt}\n\n"
                "When helpful, reference the document anchors from the note."
            )
            async with self.global_text_sem:
                agent._last_request_source = "telegram"
                response, attachments = await asyncio.wait_for(
                    agent.generate_response_with_attachments(
                        doc_prompt,
                        user_id=uid,
                        thread_id_override=thread_id,
                        trace_metadata={
                            "surface": "telegram",
                            "conversation_id": conversation_id,
                            "task_id": task_id,
                            "gateway_session_id": str(session.get("session_id") or ""),
                            "document_name": file_name,
                            "document_kind": str(payload.get("document_kind") or ""),
                        },
                    ),
                    timeout=180,
                )

            route = self.runtime_bridge.latest_route(user_id=uid, thread_id=thread_id)
            continuity = self.runtime_bridge.build_thread_capsule(
                user_id=uid,
                thread_id=thread_id,
                active_thread_id=str(active_state.get("thread_id") or ""),
            )
            reply_bundle = build_telegram_delivery_bundle(
                content=response,
                route=route,
                browse_report=dict(getattr(getattr(agent, "websearch", None), "last_browse_report", {}) or {}),
                thread_id=thread_id,
                task_id=task_id,
                document_payload=payload,
                document_note=note,
                continuity_report=continuity,
            )
            await safe_edit_or_send(ack, update, str(reply_bundle.get("primary") or response))
            for item in list(reply_bundle.get("follow_ups") or []):
                clean = str(item or "").strip()
                if clean:
                    await update.message.reply_text(clean, parse_mode=None)
            sent_exports = await _send_telegram_file_bundle(update, list(reply_bundle.get("exports") or []))
            sent_visuals = await _send_telegram_visual_bundle(update, list(attachments or []))

            try:
                agent.ops_control.complete_background_task(
                    task_id,
                    summary=str(reply_bundle.get("summary") or response[:220]),
                    handoff={
                        "surface": "telegram",
                        "thread_id": thread_id,
                        "resume_hint": "Say continue to keep working with this document thread.",
                        "route": route,
                        "recommended_surface": str(continuity.get("recommended_surface") or "telegram"),
                        "surface_names": list(continuity.get("surface_names") or []),
                        "open_task_count": int(continuity.get("open_task_count") or 0),
                        "document_name": file_name,
                        "document_kind": str(payload.get("document_kind") or ""),
                        "document_anchor_count": len(list(payload.get("anchors") or [])),
                        "export_count": sent_exports,
                        "attachment_count": sent_visuals,
                    },
                )
            except Exception:
                pass

            try:
                self.gateway_service.update_presence(
                    session_id=str(session.get("session_id") or ""),
                    status="online",
                    activity="telegram_document_completed",
                    detail=f"{thread_id[:8]} :: {file_name}",
                    metadata={"task_id": task_id, "thread_id": thread_id, "export_count": sent_exports},
                )
            except Exception:
                pass

        except asyncio.TimeoutError:
            await safe_edit_or_send(ack, update, "Document processing timed out. Try a smaller file or a narrower question.")
            try:
                agent.ops_control.fail_background_task(
                    task_id,
                    error="Telegram document processing timed out.",
                    recoverable=True,
                    recommended_action="Retry with a smaller excerpt or a more focused prompt.",
                )
            except Exception:
                pass
        except Exception as exc:
            logger.error(f"[{uid}] Document handling failed: {exc}")
            await safe_edit_or_send(ack, update, f"Could not process that document: {type(exc).__name__}.")
            try:
                agent.ops_control.fail_background_task(
                    task_id,
                    error=f"{type(exc).__name__}: {exc}",
                    recoverable=True,
                    recommended_action="Retry with a supported text-based document or a smaller PDF.",
                )
            except Exception:
                pass
        finally:
            try:
                if os.path.exists(doc_path):
                    os.remove(doc_path)
            except Exception:
                pass

    # -----------------------
    # Start/Stop
    # -----------------------

    async def start(self):
        logger.info("Bot startingâ€¦")
        await self.application.initialize()
        await self.validate_bot_username()
        await self.application.start()
        await self.application.updater.start_polling()
        self._gateway_event(event_type="telegram_lifecycle", title="Telegram bot started")
        logger.info("Bot running â€” UX upgraded + security gating enabled.")

    async def stop(self):
        try:
            for uid, t in list(self.user_tasks.items()):
                if t and not t.done():
                    t.cancel()
        except Exception:
            pass
        self._gateway_touch(activity="stopping", status="offline")
        try:
            self.gateway_service.record_health(
                service_id="telegram-bot",
                surface="telegram",
                status="offline",
                summary="Telegram bot stopped",
            )
        except Exception:
            pass
        await self.application.updater.stop()
        await self.application.stop()
        await self.application.shutdown()



