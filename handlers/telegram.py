# handlers/telegram.py — UNIVERSAL + UX UPGRADED (Feb 2026)
#
# Key upgrades:
# - per-user Agent instances (correct memory isolation)
# - per-user message queue (prevents parallel overload)
# - instant ACK + edit message when done (feels responsive)
# - safe edit fallback: if edit fails, send a normal reply (prevents worker crashes)
# - /simple /detailed /postictal /normal /clear toggles
# - /memory /pin /forget transparency/control
# - /cancel cancels active generation + clears queue
# - watchdog timeouts at Telegram layer
# - sanitizer for Telegram-safe output
# - runtime files under sessions/<user_id>/... to keep root clean
#
# OCR paths remain untouched (per your instruction).

import asyncio
import json
import logging
import re
import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Dict, List
from collections import defaultdict, deque

import pandas as pd
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from agents import Agent
from config.settings import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_BOT_USERNAME,
    TELEGRAM_AGENT_ALIASES,
    OCR_TRIGGERS,
    REGISTRY_TRIGGERS
)

from config.extraction_schema import (
    EXTRACTION_FIELDS,
    POST_PROCESSING,
    OUTPUT_COLUMNS
)

# Safe OCR import
OCR_REGISTRY_READY = False
process_registry_photo = None
_call_qwen = None
try:
    from handlers.ocr_registry import process_registry_photo, _call_qwen
    OCR_REGISTRY_READY = True
    logging.getLogger(__name__).info("Universal form OCR module loaded")
except Exception as e:
    logging.getLogger(__name__).warning(f"OCR not available: {e}")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")


def sanitize_text(s: str, limit: int = 4000) -> str:
    s = (s or "").strip()
    s = CONTROL_CHAR_RE.sub("", s)
    s = re.sub(r"\n{4,}", "\n\n", s)
    s = re.sub(r"[ \t]{3,}", "  ", s)
    if len(s) > limit:
        s = s[:limit - 10].rstrip() + "…"
    return s or "…"


async def safe_edit_or_send(ack_msg, update: Update, text: str) -> None:
    """
    Telegram edits can fail for many reasons (message deleted, not modified, permissions, etc.)
    This prevents the worker from crashing by falling back to reply_text.
    """
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

        # ✅ per-user agents and settings
        self.agents: Dict[str, Agent] = {}
        self.user_settings: Dict[str, Dict[str, bool]] = defaultdict(lambda: {
            "simple": False,
            "detailed": False,
            "postictal": False,
        })

        # ✅ per-user queue + active task
        self.user_queues: Dict[str, deque] = defaultdict(deque)
        self.user_tasks: Dict[str, asyncio.Task] = {}
        self.user_cancel_flags: Dict[str, bool] = defaultdict(bool)
        self.queue_cap_per_user = 20

        # Series mode
        self.series_sessions = defaultdict(list)      # user_id → list of dicts
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

        self.application.add_handler(CommandHandler("memory", self.memory_command))
        self.application.add_handler(CommandHandler("pin", self.pin_command))
        self.application.add_handler(CommandHandler("forget", self.forget_command))

        # Series OCR mode
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

    def _get_agent(self, uid: str) -> Agent:
        if uid in self.agents:
            return self.agents[uid]
        agent = Agent(self.agent_key, use_studies=self.use_studies, user_id=uid)
        self.agents[uid] = agent
        return agent

    async def validate_bot_username(self):
        bot = await self.application.bot.get_me()
        actual = f"@{bot.username}"
        if actual != self.bot_username:
            logger.warning(f"Correcting username: {self.bot_username} → {actual}")
            self.bot_username = actual
        self.bot_id = bot.id

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
        self.user_queues[uid].clear()
        await update.message.reply_text("Cancelled current task and cleared queued messages.")

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
        await update.message.reply_text("Okay — I’ll avoid using that memory going forward." if ok else "Couldn't apply forget.")

    # -----------------------
    # Series mode
    # -----------------------

    async def start_series(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        self.active_series_users.add(user_id)
        self.series_sessions[user_id] = []
        await update.message.reply_text(
            "Series mode activated!\n\n"
            "Send photos one by one with your trigger word in caption.\n"
            "When finished → /endseries → get one Excel with all records."
        )

    async def end_series(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                    caption=f"Full series • {len(df)} records • {len(df.columns)} fields"
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

    async def _enqueue_user_job(self, update: Update, text: str):
        uid = self._uid(update)
        text = (text or "").strip()
        if not text:
            return

        # ✅ queue cap to prevent runaway backlog/hangs
        if len(self.user_queues[uid]) >= self.queue_cap_per_user:
            self.user_queues[uid].clear()
            await update.message.reply_text(
                "Too many queued messages — queue cleared. Send 1 prompt at a time, or use /cancel."
            )
            return

        self.user_queues[uid].append((update, text))

        # worker already running → just acknowledge
        if uid in self.user_tasks and not self.user_tasks[uid].done():
            await update.message.reply_text("Got it — queued. I’ll reply in order.")
            return

        self.user_cancel_flags[uid] = False
        t = asyncio.create_task(self._user_worker(uid))
        self.user_tasks[uid] = t

    async def _user_worker(self, uid: str):
        while self.user_queues[uid]:
            if self.user_cancel_flags[uid]:
                self.user_queues[uid].clear()
                return

            update, text = self.user_queues[uid].popleft()
            agent = self._get_agent(uid)
            settings = self.user_settings[uid]

            dementia_friendly = bool(settings.get("simple") or settings.get("postictal"))
            long_form = bool(settings.get("detailed"))

            ack = await update.message.reply_text("Got it — thinking…")

            try:
                resp = await asyncio.wait_for(
                    agent.generate_response(
                        text,
                        user_id=uid,
                        dementia_friendly=dementia_friendly,
                        long_form=long_form,
                    ),
                    timeout=150,
                )
                await safe_edit_or_send(ack, update, resp)

            except asyncio.CancelledError:
                await safe_edit_or_send(ack, update, "Cancelled.")
                return

            except asyncio.TimeoutError:
                await safe_edit_or_send(
                    ack,
                    update,
                    "Timed out. Try again with a shorter prompt, or use /simple mode."
                )

            except Exception as e:
                await safe_edit_or_send(
                    ack,
                    update,
                    f"Error: {type(e).__name__}. Try again."
                )

    # -----------------------
    # Photos
    # -----------------------

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = self._uid(update)
        user_id_int = update.effective_user.id

        photo_file = await update.message.photo[-1].get_file()
        img_dir = self._images_dir(uid)
        photo_path = os.path.join(img_dir, f"photo_{update.message.message_id}_{user_id_int}.jpg")
        await photo_file.download_to_drive(photo_path)
        logger.info(f"[{uid}] Saved photo: {photo_path}")

        caption = (update.message.caption or "").lower()
        triggers = [x.lower() for x in (OCR_TRIGGERS or []) + (REGISTRY_TRIGGERS or [])]
        is_ocr_request = any(t in caption for t in triggers)

        # SERIES MODE OCR (unchanged)
        if user_id_int in self.active_series_users and is_ocr_request and OCR_REGISTRY_READY:
            await update.message.reply_text("Adding page to series…")
            raw_text = await asyncio.to_thread(_call_qwen, photo_path)

            entries = []
            pattern = re.compile(r"ENTRY\s*\d+\s*\n(.*?)(?=ENTRY\s*\d+|\Z)", re.DOTALL | re.IGNORECASE)
            for block_match in pattern.finditer(raw_text):
                block = block_match.group(1)
                entry = {}
                for line in block.split("\n"):
                    if ":" not in line:
                        continue
                    key, val = line.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    if val in ("—", "–", "-"):
                        val = ""

                    if key in EXTRACTION_FIELDS:
                        cleaner = POST_PROCESSING.get(key, lambda x: x)
                        entry[key] = cleaner(val)

                if entry:
                    entries.append(entry)

            if entries:
                self.series_sessions[user_id_int].extend(entries)
                await update.message.reply_text(
                    f"Added {len(entries)} record(s)\n"
                    f"Total so far: {len(self.series_sessions[user_id_int])}"
                )
            else:
                await update.message.reply_text("No records found on this page.")

            try:
                os.remove(photo_path)
            except Exception:
                pass
            return

        # SINGLE IMAGE OCR (unchanged)
        if is_ocr_request and OCR_REGISTRY_READY:
            await update.message.reply_text("Analyzing form…")
            await process_registry_photo(photo_path, update, context)
            return

        # NORMAL VISION FALLBACK (ack + watchdog + safe edit)
        agent = self._get_agent(uid)
        ack = await update.message.reply_text("Got it — analyzing image…")
        try:
            resp = await asyncio.wait_for(
                agent.analyze_image(photo_path, update.message.caption or "Describe this image.", user_id=uid),
                timeout=210,
            )
            await safe_edit_or_send(ack, update, resp)
        except asyncio.TimeoutError:
            await safe_edit_or_send(ack, update, "Image analysis timed out. Try a clearer photo or smaller request.")
        except Exception as e:
            logger.error(f"[{uid}] Vision failed: {e}")
            await safe_edit_or_send(ack, update, "Could not analyze image.")
        finally:
            try:
                os.remove(photo_path)
            except Exception:
                pass

    # -----------------------
    # Start/Stop
    # -----------------------

    async def start(self):
        logger.info("Bot starting…")
        await self.application.initialize()
        await self.validate_bot_username()
        await self.application.start()
        await self.application.updater.start_polling()
        logger.info("Bot running — UX upgraded.")

    async def stop(self):
        try:
            for uid, t in list(self.user_tasks.items()):
                if t and not t.done():
                    t.cancel()
        except Exception:
            pass
        await self.application.updater.stop()
        await self.application.stop()
        await self.application.shutdown()
