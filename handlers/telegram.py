# handlers/telegram.py — FINAL + /series + PHONE NUMBER FIXED + PERFECT EXCEL (Dec 2025)

import asyncio
import json
import logging
import re
import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Dict, List
from collections import defaultdict

import pandas as pd
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from agents import Agent
from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_BOT_USERNAME, TELEGRAM_AGENT_ALIASES

# Safe OCR import
OCR_REGISTRY_READY = False
process_registry_photo = None
_call_qwen = None
try:
    from handlers.ocr_registry import process_registry_photo, _call_qwen
    OCR_REGISTRY_READY = True
    logging.getLogger(__name__).info("Qwen-VL OCR module loaded")
except Exception as e:
    logging.getLogger(__name__).warning(f"OCR not available: {e}")

# Paths
PERSONALITY_CONFIG = "config/personalC.json"
CACHE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "telegram_cache.json")
IMAGES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "images")
os.makedirs(IMAGES_DIR, exist_ok=True)

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def load_personalities():
    try:
        with open(PERSONALITY_CONFIG, "r", encoding="utf-8") as f:
            characters = json.load(f)
        alias_to_key = {}
        for key, config in characters.items():
            aliases = config.get("aliases", []) + [key, key.replace("Name: ", "")]
            for alias in aliases:
                alias_to_key[alias.lower()] = key
        return characters, alias_to_key
    except FileNotFoundError:
        logger.error(f"{PERSONALITY_CONFIG} not found.")
        return {}, {}

class CacheManager:
    def __init__(self):
        self.cache: List[Dict] = self._load_cache()

    def _load_cache(self) -> List[Dict]:
        try:
            if not os.path.exists(CACHE_FILE):
                return []
            with open(CACHE_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading cache: {e}")
            return []

    def save_cache(self):
        try:
            with open(CACHE_FILE, 'w') as f:
                json.dump(self.cache, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving cache: {e}")

    def add_to_cache(self, message: str, timestamp: datetime):
        self.cache.append({"message": message, "timestamp": timestamp.isoformat()})
        self.save_cache()

    def clear_cache(self):
        self.cache = []
        self.save_cache()

    def get_recent_data(self, hours: int = 24) -> List[Dict]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        return [e for e in self.cache if datetime.fromisoformat(e["timestamp"]) >= cutoff]

class TelegramHandler:
    def __init__(self, character_name: str, use_studies=False):
        self.token = TELEGRAM_BOT_TOKEN
        if not self.token or self.token == "your_telegram_bot_token":
            raise ValueError("TELEGRAM_BOT_TOKEN must be set")

        self.characters, self.alias_to_key = load_personalities()
        self.agent_key = self._resolve_agent_key(character_name)
        self.agent = Agent(self.agent_key, use_studies=use_studies)
        self.display_name = self.agent_key.replace("Name: ", "")

        self.bot_username = TELEGRAM_BOT_USERNAME
        self.bot_id = None
        self.cache_manager = CacheManager()
        self.application = Application.builder().token(self.token).build()

        # Series mode
        self.series_sessions = defaultdict(list)   # user_id → list of patient dicts
        self.active_series_users = set()

        # Handlers
        self.application.add_handler(MessageHandler(filters.REPLY & filters.TEXT & ~filters.COMMAND, self.handle_reply))
        self.application.add_handler(CommandHandler("clearcache", self.clear_cache_command))
        self.application.add_handler(CommandHandler("hotcoins", self.hot_coins_command))
        self.application.add_handler(CommandHandler("series", self.start_series))
        self.application.add_handler(CommandHandler("endseries", self.end_series))
        self.application.add_handler(MessageHandler(filters.Mention(self.bot_username), self.handle_mention))

        if TELEGRAM_AGENT_ALIASES:
            pattern = re.compile(r'\b(' + '|'.join(map(re.escape, TELEGRAM_AGENT_ALIASES)) + r')\b', re.IGNORECASE)
            self.application.add_handler(MessageHandler(filters.Regex(pattern) & filters.TEXT & ~filters.COMMAND, self.handle_alias_mention))

        self.application.add_handler(MessageHandler(filters.PHOTO, self.handle_photo))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_all_messages))

    def _resolve_agent_key(self, name):
        if not name:
            return "Name: Somi"
        name_lower = name.lower()
        if name in self.characters:
            return name
        if name_lower in self.alias_to_key:
            return self.alias_to_key[name_lower]
        return "Name: Somi"

    async def validate_bot_username(self):
        bot = await self.application.bot.get_me()
        actual = f"@{bot.username}"
        if actual != self.bot_username:
            logger.warning(f"Correcting username: {self.bot_username} → {actual}")
            self.bot_username = actual
        self.bot_id = bot.id

    async def clear_cache_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.cache_manager.clear_cache()
        await update.message.reply_text("Cache cleared!")

    async def hot_coins_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        data = self.cache_manager.get_recent_data(24)
        if not data:
            await update.message.reply_text("No messages in last 24h.")
            return
        coins = self._analyze_hot_coins(data)
        if not coins:
            await update.message.reply_text("No hot coins.")
            return
        await update.message.reply_text("Hot coins (24h):\n" + "\n".join(f"{c}: {n}" for c, n in coins.items()))

    async def start_series(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        self.active_series_users.add(user_id)
        self.series_sessions[user_id] = []
        await update.message.reply_text(
            "Series mode ON!\n\n"
            "Send photos one by one with 'extract' (or your trigger) in caption.\n"
            "When done → /endseries → get one perfect Excel with ALL patients."
        )

    async def end_series(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in self.active_series_users:
            await update.message.reply_text("You weren't in series mode.")
            return

        patients = self.series_sessions.get(user_id, [])
        if not patients:
            await update.message.reply_text("No patients collected.")
        else:
            await self._send_combined_excel(patients, update)
            await update.message.reply_text(f"Done! Sent Excel with {len(patients)} patients.")

        self.active_series_users.discard(user_id)
        self.series_sessions.pop(user_id, None)

    async def _send_combined_excel(self, patients: list, update: Update):
        if not patients:
            return
        df = pd.DataFrame(patients)
        cols = ["Name", "Date of Birth", "Phone Number", "ID", "Age at Diagnosis",
                "Seizure Type", "CT", "MRI", "EEG", "Previous Surgeries",
                "Current Meds", "Complications"]
        df = df.reindex(columns=cols, fill_value="")

        filename = f"Series_Registry_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
        path = os.path.join(tempfile.gettempdir(), filename)

        try:
            df.to_excel(path, index=False, engine='openpyxl')
            with open(path, 'rb') as f:
                await update.message.reply_document(
                    document=f,
                    filename=filename,
                    caption=f"Full series • {len(df)} patients • Phone + Meds + Clean ID"
                )
            logger.info(f"[Series] Sent {len(df)} patients")
        except Exception as e:
            logger.error(f"[Series] Excel failed: {e}")
            await update.message.reply_text("Excel creation failed.")
        finally:
            try: os.remove(path)
            except: pass

    async def handle_all_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self._is_relevant_message(update.message.text):
            self.cache_manager.add_to_cache(update.message.text, update.message.date)

    async def handle_mention(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self._is_relevant_message(update.message.text):
            self.cache_manager.add_to_cache(update.message.text, update.message.date)
        clean = re.sub(re.escape(self.bot_username), '', update.message.text, flags=re.IGNORECASE).strip()
        resp = await self.agent.generate_response(clean)
        await update.message.reply_text((resp or "Hmm...")[:4000])

    async def handle_alias_mention(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self._is_relevant_message(update.message.text):
            self.cache_manager.add_to_cache(update.message.text, update.message.date)
        clean = update.message.text
        for a in TELEGRAM_AGENT_ALIASES:
            clean = re.sub(rf'\b{re.escape(a)}\b', '', clean, flags=re.IGNORECASE).strip()
        resp = await self.agent.generate_response(clean)
        await update.message.reply_text((resp or "Hmm...")[:4000])

    async def handle_reply(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.reply_to_message and update.message.reply_to_message.from_user.id == self.bot_id:
            if self._is_relevant_message(update.message.text):
                self.cache_manager.add_to_cache(update.message.text, update.message.date)
            resp = await self.agent.generate_response(update.message.text.strip())
            await update.message.reply_text((resp or "Hmm...")[:4000])

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        photo_file = await update.message.photo[-1].get_file()
        photo_path = os.path.join(IMAGES_DIR, f"photo_{update.message.message_id}_{user_id}.jpg")
        await photo_file.download_to_drive(photo_path)
        logger.info(f"Saved photo: {photo_path}")

        caption = (update.message.caption or "").lower()

        from config.settings import OCR_TRIGGERS, REGISTRY_TRIGGERS
        triggers = [x.lower() for x in (OCR_TRIGGERS or []) + (REGISTRY_TRIGGERS or [])]
        is_ocr_request = any(t in caption for t in triggers)

        # ==================== SERIES MODE ====================
        if user_id in self.active_series_users and is_ocr_request and OCR_REGISTRY_READY and _call_qwen:
            await update.message.reply_text("Adding page to series…")
            raw_text = _call_qwen(photo_path)

            patients = []
            for block in re.finditer(r'PATIENT \d+\n(.*?)(?=\n\nPATIENT \d+|\Z)', raw_text, re.DOTALL):
                p = {}
                for line in block.group(1).split('\n'):
                    if ':' not in line: continue
                    key, val = line.split(':', 1)
                    key = key.strip()
                    val = val.strip().replace('—', '').strip()

                    if key == "Name": p["Name"] = val
                    elif key == "Date of Birth": p["Date of Birth"] = val
                    elif key == "Phone Number": p["Phone Number"] = val
                    elif key == "ID":
                        clean_id = re.sub(r'[Nn]$', '', val).strip()
                        p["ID"] = clean_id or val
                    elif key == "Age at Diagnosis": p["Age at Diagnosis"] = val
                    elif key == "Seizure Type": p["Seizure Type"] = val
                    elif key == "CT": p["CT"] = val
                    elif key == "MRI": p["MRI"] = val
                    elif key == "EEG": p["EEG"] = val
                    elif key == "Previous Surgeries":
                        p["Previous Surgeries"] = val.replace(',', ' | ')
                    elif key == "Current Meds":
                        p["Current Meds"] = val.replace(', ', ' | ')
                    elif key == "Complications": p["Complications"] = val
                if p:
                    patients.append(p)

            if patients:
                self.series_sessions[user_id].extend(patients)
                await update.message.reply_text(
                    f"Added {len(patients)} patient(s)\n"
                    f"Total in series: {len(self.series_sessions[user_id])}"
                )
            else:
                await update.message.reply_text("No patients found on this page.")

            os.remove(photo_path)
            return

        # ==================== SINGLE IMAGE OCR ====================
        if is_ocr_request and OCR_REGISTRY_READY:
            await update.message.reply_text("Processing registry page…")
            await process_registry_photo(photo_path, update, context)
            return

        # ==================== NORMAL VISION ====================
        try:
            resp = self.agent.analyze_image(photo_path, update.message.caption or "Describe this image.")
            await update.message.reply_text(resp[:4000])
        except Exception as e:
            logger.error(f"Vision failed: {e}")
            await update.message.reply_text("Could not analyze image.")
        finally:
            try: os.remove(photo_path)
            except: pass

    def _is_relevant_message(self, message: str) -> bool:
        patterns = [r'\$[a-zA-Z]{2,5}\b', r'\b(bot|improve|enhance|suggest)\b',
                    r'\b(event|war|market|crash|news)\b', r'\b(trade|buy|sell|price|volume)\b']
        return any(re.search(p, message, re.IGNORECASE) for p in patterns)

    def _analyze_hot_coins(self, data: List[Dict]) -> Dict[str, int]:
        mentions = {}
        for entry in data:
            for coin in re.findall(r'\$[a-zA-Z]{2,5}\b', entry["message"], re.IGNORECASE):
                mentions[coin.lower()] = mentions.get(coin.lower(), 0) + 1
        return dict(sorted(mentions.items(), key=lambda x: x[1], reverse=True)[:5])

    async def start(self):
        logger.info("Bot starting…")
        await self.application.initialize()
        await self.validate_bot_username()
        await self.application.start()
        await self.application.updater.start_polling()
        logger.info("Bot running — /series ready!")

    async def stop(self):
        await self.application.updater.stop()
        await self.application.stop()
        await self.application.shutdown()
