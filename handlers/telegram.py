# handlers/telegram.py
import asyncio
import json
import logging
import re
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from agents import Agent
from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_BOT_USERNAME, TELEGRAM_AGENT_ALIASES

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PERSONALITY_CONFIG = "config/personalC.json"
CACHE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "telegram_cache.json")
IMAGES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "images")

os.makedirs(IMAGES_DIR, exist_ok=True)

def load_personalities():
    """Load personalities from personalC.json."""
    try:
        with open(PERSONALITY_CONFIG, "r") as f:
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
        
        # Load personalities and resolve agent key
        self.characters, self.alias_to_key = load_personalities()
        self.agent_key = self._resolve_agent_key(character_name)
        self.agent = Agent(self.agent_key, use_studies=use_studies)
        self.display_name = self.agent_key.replace("Name: ", "")
        
        self.bot_username = TELEGRAM_BOT_USERNAME
        self.bot_id = None  # Will be set in start()
        self.cache_manager = CacheManager()
        self.application = Application.builder().token(self.token).build()

        # Register handlers
        self.application.add_handler(MessageHandler(filters.REPLY & filters.TEXT & ~filters.COMMAND, self.handle_reply))
        self.application.add_handler(CommandHandler("clearcache", self.clear_cache_command))
        self.application.add_handler(CommandHandler("hotcoins", self.hot_coins_command))
        self.application.add_handler(MessageHandler(filters.Mention(self.bot_username), self.handle_mention))
        
        # Use TELEGRAM_AGENT_ALIASES for alias pattern
        if TELEGRAM_AGENT_ALIASES:
            alias_pattern = re.compile(r'\b(' + '|'.join(map(re.escape, TELEGRAM_AGENT_ALIASES)) + r')\b', re.IGNORECASE)
            self.application.add_handler(MessageHandler(filters.Regex(alias_pattern) & filters.TEXT & ~filters.COMMAND, self.handle_alias_mention))
        
        self.application.add_handler(MessageHandler(filters.PHOTO, self.handle_photo))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_all_messages))

    def _resolve_agent_key(self, name):
        """Resolve the agent key from name or alias."""
        if not name:
            return "Name: Somi"  # Default key
        name_lower = name.lower()
        if name in self.characters:
            return name
        if name_lower in self.alias_to_key:
            return self.alias_to_key[name_lower]
        logger.warning(f"Agent '{name}' not found. Using default: Name: Somi")
        return "Name: Somi"

    async def validate_bot_username(self):
        """Validate that TELEGRAM_BOT_USERNAME matches the bot's actual username."""
        bot = await self.application.bot.get_me()
        actual_username = f"@{bot.username}"
        if actual_username != self.bot_username:
            logger.warning(f"TELEGRAM_BOT_USERNAME ({self.bot_username}) does not match bot's actual username ({actual_username}). Auto-correcting.")
            self.bot_username = actual_username
        self.bot_id = bot.id

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

        cleaned_message = re.sub(re.escape(self.bot_username), '', message, flags=re.IGNORECASE).strip()
        logger.debug(f"Cleaned message for prompt: {cleaned_message}")

        try:
            response = await self.agent.generate_response(cleaned_message)
            if not response:
                response = f"Hmm, {self.display_name}'s not sure what to say—let’s try something else!"
            response = response.strip('"\'')
            if len(response) > 4096:
                response = response[:4093] + "..."
            await update.message.reply_text(response)
            logger.info(f"Replied to mention: {message} with {response}")
        except Exception as e:
            logger.error(f"Error generating response for mention '{message}': {e}")
            await update.message.reply_text(f"Oops, {self.display_name} had a glitch! Let me try again later.")

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

        try:
            response = await self.agent.generate_response(cleaned_message)
            if not response:
                response = f"Hmm, {self.display_name}'s not sure what to say—let’s try something else!"
            response = response.strip('"\'')
            if len(response) > 4096:
                response = response[:4093] + "..."
            await update.message.reply_text(response)
            logger.info(f"Replied to alias mention: {message} with {response}")
        except Exception as e:
            logger.error(f"Error generating response for alias mention '{message}': {e}")
            await update.message.reply_text(f"Oops, {self.display_name} had a glitch! Let me try again later.")

    async def handle_reply(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.message.text
        timestamp = update.message.date
        logger.info(f"Received reply to bot: {message} at {timestamp}")

        if self._is_relevant_message(message):
            self.cache_manager.add_to_cache(message, timestamp)

        if update.message.reply_to_message and update.message.reply_to_message.from_user.id == self.bot_id:
            logger.debug(f"Confirmed reply to bot (ID: {self.bot_id})")
            cleaned_message = message.strip()
            logger.debug(f"Cleaned reply message for prompt: {cleaned_message}")

            try:
                response = await self.agent.generate_response(cleaned_message)
                if not response:
                    response = f"Hmm, {self.display_name}'s not sure what to say—let’s try something else!"
                response = response.strip('"\'')
                if len(response) > 4096:
                    response = response[:4093] + "..."
                await update.message.reply_text(response)
                logger.info(f"Replied to bot reply: {message} with {response}")
            except Exception as e:
                logger.error(f"Error generating response for reply '{message}': {e}")
                await update.message.reply_text(f"Oops, {self.display_name} had a glitch! Let me try again later.")

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        photo_file = await update.message.photo[-1].get_file()
        photo_path = os.path.join(IMAGES_DIR, f"telegram_photo_{update.message.message_id}.jpg")
        await photo_file.download_to_drive(photo_path)
        logger.info(f"Saved photo to: {photo_path}")

        try:
            caption = update.message.caption or "No caption provided"
            response = self.agent.analyze_image(photo_path, caption)
            if len(response) > 4096:
                response = response[:4093] + "..."
            await update.message.reply_text(response)
            logger.info(f"Replied to photo with: {response}")
        except Exception as e:
            logger.error(f"Error analyzing photo: {e}")
            await update.message.reply_text(f"Whoops, {self.display_name} couldn’t analyze that pic—my circuits must be fried!")

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
        await self.validate_bot_username()
        await self.application.start()
        await self.application.updater.start_polling()
        logger.info("Bot is running.")

    async def stop(self):
        logger.info("Stopping Telegram bot...")
        await self.application.updater.stop()
        await self.application.stop()
        await self.application.shutdown()