import asyncio
import json
import logging
import re
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from agents import SomiAgent
from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_AGENT_ALIASES

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

CACHE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "telegram_cache.json")

class CacheManager:
    def __init__(self):
        self.cache: List[Dict] = self._load_cache()

    def _load_cache(self) -> List[Dict]:
        try:
            if not os.path.exists(CACHE_FILE):
                logger.info("No cache file found, starting with empty cache.")
                return []
            with open(CACHE_FILE, 'r') as f:
                cache = json.load(f)
                logger.info(f"Loaded cache with {len(cache)} entries.")
                return cache
        except Exception as e:
            logger.error(f"Error loading cache: {e}")
            return []

    def save_cache(self):
        try:
            with open(CACHE_FILE, 'w') as f:
                json.dump(self.cache, f, indent=2)
            logger.info("Cache saved to %s", CACHE_FILE)
        except Exception as e:
            logger.error(f"Error saving cache: {e}")

    def add_to_cache(self, message: str, timestamp: datetime):
        self.cache.append({"message": message, "timestamp": timestamp.isoformat()})
        self.save_cache()
        logger.info(f"Added message to cache: {message}")

    def clear_cache(self):
        self.cache = []
        self.save_cache()
        logger.info("Cache cleared.")

    def get_recent_data(self, hours: int = 24) -> List[Dict]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        recent = [entry for entry in self.cache if datetime.fromisoformat(entry["timestamp"]) >= cutoff]
        logger.info(f"Found {len(recent)} recent messages in the last {hours} hours.")
        return recent

class TelegramHandler:
    def __init__(self, character_name: str, use_studies=False):
        self.token = TELEGRAM_BOT_TOKEN
        if not self.token or self.token == "your_telegram_bot_token":
            raise ValueError("TELEGRAM_BOT_TOKEN must be set in config/settings.py")
        self.agent = SomiAgent(character_name, use_studies=use_studies)
        self.cache_manager = CacheManager()
        self.application = Application.builder().token(self.token).build()

        self.application.add_handler(CommandHandler("clearcache", self.clear_cache_command))
        self.application.add_handler(CommandHandler("hotcoins", self.hot_coins_command))
        self.application.add_handler(MessageHandler(filters.Mention("@SomiAnalyticsBot"), self.handle_mention))
        alias_pattern = re.compile('|'.join(map(re.escape, TELEGRAM_AGENT_ALIASES)), re.IGNORECASE)
        self.application.add_handler(MessageHandler(filters.Regex(alias_pattern) & filters.TEXT & ~filters.COMMAND, self.handle_alias_mention))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_all_messages))

    async def clear_cache_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.cache_manager.clear_cache()
        await update.message.reply_text("Cache cleared successfully!")
        logger.info("Cache cleared via command.")

    async def hot_coins_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        recent_data = self.cache_manager.get_recent_data(hours=24)
        if not recent_data:
            await update.message.reply_text("No relevant messages found in the last 24 hours.")
            logger.info("No recent data found for /hotcoins.")
            return

        hot_coins = self._analyze_hot_coins(recent_data)
        if not hot_coins:
            await update.message.reply_text("No hot coins or topics found in the last 24 hours.")
            logger.info("No hot coins/topics found in recent data.")
            return

        response = "Hot coins in the chat (last 24 hours):\n" + "\n".join(f"{item}: {count} mentions" for item, count in hot_coins.items())
        await update.message.reply_text(response)
        logger.info(f"Hot coins reported: {response}")

    async def handle_all_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.message.text
        timestamp = update.message.date
        logger.debug(f"Received message: {message} at {timestamp}")

        if self._is_relevant_message(message):
            self.cache_manager.add_to_cache(message, timestamp)

    async def handle_mention(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.message.text
        timestamp = update.message.date
        logger.info(f"Received mention: {message} at {timestamp}")

        if self._is_relevant_message(message):
            self.cache_manager.add_to_cache(message, timestamp)

        cleaned_message = re.sub(r'@SomiAnalyticsBot', '', message, flags=re.IGNORECASE).strip()
        logger.debug(f"Cleaned message for prompt: {cleaned_message}")

        prompt = (
            f"You’ve been mentioned in a Telegram chat. Respond to the following message in a playful, conversational tone, "
            f"reflecting your personality and traits, ensuring the response ends naturally with a complete thought or sentence. "
            f"Message: {cleaned_message}"
        )
        try:
            response = self.agent.generate_response(prompt)
            response = response.strip('"\'')
            if len(response) > 4096:  # Increased from 280 to 4096 (Telegram's max)
                response = response[:4093] + "..."
            await update.message.reply_text(response)
            logger.info(f"Replied to mention: {message} with {response}")
        except Exception as e:
            logger.error(f"Error generating response for mention '{message}': {e}")
            await update.message.reply_text("Oops, I had a glitch! Let me try again later.")

    async def handle_alias_mention(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.message.text
        timestamp = update.message.date
        logger.info(f"Received alias mention: {message} at {timestamp}")

        if self._is_relevant_message(message):
            self.cache_manager.add_to_cache(message, timestamp)

        cleaned_message = message
        for alias in TELEGRAM_AGENT_ALIASES:
            cleaned_message = re.sub(rf'\b{re.escape(alias)}\b', '', cleaned_message, flags=re.IGNORECASE)
        cleaned_message = cleaned_message.strip()
        logger.debug(f"Cleaned message for prompt: {cleaned_message}")

        prompt = (
            f"You’ve been mentioned in a Telegram chat by one of your aliases ({', '.join(TELEGRAM_AGENT_ALIASES)}). "
            f"Respond to the following message in a playful, conversational tone, "
            f"reflecting your personality and traits, ensuring the response ends naturally with a complete thought or sentence. "
            f"Message: {cleaned_message}"
        )
        try:
            response = self.agent.generate_response(prompt)
            response = response.strip('"\'')
            if len(response) > 4096:  # Increased from 280 to 4096
                response = response[:4093] + "..."
            await update.message.reply_text(response)
            logger.info(f"Replied to alias mention: {message} with {response}")
        except Exception as e:
            logger.error(f"Error generating response for alias mention '{message}': {e}")
            await update.message.reply_text("Oops, I had a glitch! Let me try again later.")

    def _is_relevant_message(self, message: str) -> bool:
        patterns = [
            r'\$[a-zA-Z]{2,5}\b',
            r'\b(bot|improve|enhance|suggest)\b',
            r'\b(event|war|market|crash|news)\b',
            r'\b(trade|buy|sell|price|volume)\b'
        ]
        is_relevant = any(re.search(pattern, message, re.IGNORECASE) for pattern in patterns)
        logger.debug(f"Message '{message}' is {'relevant' if is_relevant else 'not relevant'}")
        return is_relevant

    def _analyze_hot_coins(self, data: List[Dict]) -> Dict[str, int]:
        mentions: Dict[str, int] = {}
        for entry in data:
            message = entry["message"]
            coins = re.findall(r'\$[a-zA-Z]{2,5}\b', message, re.IGNORECASE)
            for coin in coins:
                coin_lower = coin.lower()
                mentions[coin_lower] = mentions.get(coin_lower, 0) + 1
        sorted_mentions = {k: v for k, v in sorted(mentions.items(), key=lambda x: x[1], reverse=True)[:5]}
        logger.info(f"Analyzed hot coins: {sorted_mentions}")
        return sorted_mentions

    async def start(self):
        logger.info("Starting Telegram bot...")
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        logger.info("Bot is running.")

    async def stop(self):
        logger.info("Stopping Telegram bot...")
        await self.application.updater.stop()
        await self.application.stop()
        await self.application.shutdown()