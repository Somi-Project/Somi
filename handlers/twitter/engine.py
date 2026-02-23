import os
import json
import time
import re
import random
import logging
import asyncio
import numpy as np
import faiss
import sqlite3
from datetime import datetime
from pathlib import Path
import tweepy
from playwright.async_api import async_playwright
from config.settings import (
    DEFAULT_MODEL, VISION_MODEL, DEFAULT_TEMP,
    SYSTEM_TIMEZONE, DISABLE_MEMORY_FOR_FINANCIAL
)
from config.twittersettings import (
    TWITTER_USERNAME, TWITTER_PASSWORD, TWITTER_API, TWITTER_DRY_RUN,
    AUTO_POST_INTERVAL_MINUTES, AUTO_POST_INTERVAL_LOWER_VARIATION,
    AUTO_POST_INTERVAL_UPPER_VARIATION, AUTO_REPLY_INTERVAL_MINUTES,
    AUTO_REPLY_INTERVAL_LOWER_VARIATION, AUTO_REPLY_INTERVAL_UPPER_VARIATION,
    TWITTER_PROFILE, TWITTER_GROWTH
)
from handlers.twitter.state_store import StateStore
from handlers.twitter.policy import should_noop
from handlers.twitter.selectors import (
    ARTICLE_SELECTORS, TWEET_TEXT_SELECTORS, STATUS_LINK_SELECTORS, REPLY_BUTTON_SELECTORS,
    COMPOSER_SELECTORS, SEND_BUTTON_SELECTORS, POPUP_CLOSE_SELECTORS
)
from handlers.websearch import WebSearchHandler
from handlers.time_handler import TimeHandler
from rag import RAGHandler
import ollama

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    handlers=[logging.FileHandler('twitter.log'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

PERSONALITY_CONFIG = os.path.join("config", "personalC.json")
REPCACHE_FILE = "repcache.json"
IMAGES_DIR = "images"
CACHE_EXPIRY_SECONDS = 6 * 3600  # 6 hours
CACHE_MAX_THREADS = 100
PROCESSED_TWEETS_EXPIRY_SECONDS = 24 * 3600  # 24 hours
PROCESSED_TWEETS_MAX = 1000
SIMILARITY_THRESHOLD = 0.9  # For tweet similarity checks

os.makedirs(IMAGES_DIR, exist_ok=True)

def load_personalities():
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

def validate_agent_name(name):
    characters, alias_to_key = load_personalities()
    if not name:
        return "Name: Somi"
    name_lower = name.lower()
    if name in characters:
        return name
    if name_lower in alias_to_key:
        return alias_to_key[name_lower]
    logger.warning(f"Character '{name}' not found. Using default: Name: Somi")
    return "Name: Somi"

class TwitterHandler:
    def __init__(self, character_name=None, use_studies=False):
        self.character_name = character_name
        self.use_studies = use_studies
        self.agent_key = validate_agent_name(character_name)
        self.display_name = self.agent_key.replace("Name: ", "")
        self.characters, _ = load_personalities()
        character = self.characters.get(self.agent_key, {
            "role": "assistant",
            "temperature": DEFAULT_TEMP,
            "description": "Generic assistant",
            "aliases": [self.display_name],
            "physicality": [],
            "experience": [],
            "inhibitions": [],
            "hobbies": [],
            "behaviors": []
        })
        self.role = character.get("role", "assistant")
        self.temperature = character.get("temperature", DEFAULT_TEMP)
        self.description = character.get("description", "Generic assistant")
        self.physicality = character.get("physicality", [])
        self.experience = character.get("experience", [])
        self.inhibitions = character.get("inhibitions", [])
        self.hobbies = character.get("hobbies", [])
        self.behaviors = character.get("behaviors", [])
        self.model = DEFAULT_MODEL
        self.vision_model = VISION_MODEL
        self.websearch = WebSearchHandler()
        self.time_handler = TimeHandler(default_timezone=SYSTEM_TIMEZONE)
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.cookie_file = "twitter_cookies.json"
        self.authenticated = False
        self.repcache = self._load_repcache()
        self.state_store = StateStore()
        self._setup_memory_storage()
        try:
            self.api_client = tweepy.Client(
                bearer_token=TWITTER_API.get("bearer_token"),
                consumer_key=TWITTER_API.get("api_key"),
                consumer_secret=TWITTER_API.get("api_secret"),
                access_token=TWITTER_API.get("access_token"),
                access_token_secret=TWITTER_API.get("access_token_secret")
            )
            logger.info("Tweepy client initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize tweepy client: {str(e)}")
            self.api_client = None
        if self.use_studies:
            from agents import Agent
            self.agent = Agent(self.agent_key, use_studies=True)
        else:
            self.agent = None

    def _setup_memory_storage(self):
        self.db_path = "twitter_memories.db"
        self.sqlite_conn = sqlite3.connect(self.db_path)
        self.sqlite_cursor = self.sqlite_conn.cursor()
        self.sqlite_cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                content TEXT,
                memory_type TEXT,
                timestamp TEXT,
                category TEXT
            )
        """)
        self.sqlite_conn.commit()
        self.embedding_dim = 384
        self.faiss_index_path = "twitter_memories_faiss.index"
        self.faiss_index = faiss.IndexFlatL2(self.embedding_dim)
        self.faiss_index = faiss.IndexIDMap(self.faiss_index)
        try:
            self.faiss_index = faiss.read_index(self.faiss_index_path)
            logger.info(f"Loaded FAISS index from {self.faiss_index_path}")
        except:
            logger.info("No existing FAISS index found, starting fresh")
        try:
            self.embeddings = RAGHandler().get_embedding_model()
            logger.info("Loaded embedding model from RAGHandler")
        except Exception as e:
            logger.error(f"Failed to load embedding model from RAGHandler: {str(e)}")
            raise RuntimeError("Embedding model initialization failed")

    def _load_repcache(self):
        try:
            if os.path.exists(REPCACHE_FILE):
                with open(REPCACHE_FILE, 'r') as f:
                    cache = json.load(f)
                current_time = time.time()
                cleaned_cache = {
                    conv_id: messages
                    for conv_id, messages in cache.items()
                    if conv_id != "processed_tweets" and messages and (current_time - messages[-1]['timestamp'] < CACHE_EXPIRY_SECONDS)
                }
                processed_tweets = cache.get("processed_tweets", [])
                cleaned_processed = [
                    entry for entry in processed_tweets
                    if (current_time - entry['timestamp'] < PROCESSED_TWEETS_EXPIRY_SECONDS)
                ]
                cleaned_processed = cleaned_processed[-PROCESSED_TWEETS_MAX:]
                cleaned_cache["processed_tweets"] = cleaned_processed
                if len(cleaned_cache) - 1 > CACHE_MAX_THREADS:
                    sorted_threads = sorted(
                        [(k, v) for k, v in cleaned_cache.items() if k != "processed_tweets"],
                        key=lambda x: x[1][-1]['timestamp'],
                        reverse=True
                    )[:CACHE_MAX_THREADS]
                    cleaned_cache = {"processed_tweets": cleaned_processed}
                    cleaned_cache.update(dict(sorted_threads))
                return cleaned_cache
            return {"processed_tweets": []}
        except Exception as e:
            logger.error(f"Error loading repcache: {str(e)}")
            return {"processed_tweets": []}

    def _save_repcache(self):
        try:
            with open(REPCACHE_FILE, 'w') as f:
                json.dump(self.repcache, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving repcache: {str(e)}")

    def _sanitize_text(self, text):
        return ''.join(char for char in text if ord(char) < 128)

    def _clean_think_tags(self, text):
        """Remove <think> tags and their contents from the text."""
        return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

    def process_memory(self, input_text, output_text, user_id):
        if DISABLE_MEMORY_FOR_FINANCIAL:
            financial_keywords = ["price", "stock", "bitcoin", "crypto", "market", "dollar", "euro"]
            if any(keyword in input_text.lower() for keyword in financial_keywords):
                logger.info(f"Memory storage skipped for financial input: {input_text}")
                return False, None, None
        weather_keywords = ["weather", "rain", "snow", "temperature", "sunny", "cloudy", "windy", "storm"]
        if any(keyword in input_text.lower() for keyword in weather_keywords):
            logger.info(f"Memory storage skipped for weather-related input: {input_text}")
            return False, None, None
        question_words = ["who", "what", "where", "when", "why", "how", "is", "are", "do", "does", "did"]
        input_lower = input_text.lower().strip()
        is_question = any(input_lower.startswith(word) for word in question_words) and input_text.endswith("?")
        if is_question:
            logger.info(f"Memory storage skipped for question input: {input_text}")
            return False, None, None
        blacklist_prompt = f"""
You are a memory evaluation assistant for a Twitter AI. Return ONLY a JSON object with:
- should_store (boolean): True if the memory should be stored, False otherwise.
- memory_type (string or null): "semantic" for personal facts, "episodic" for interactions, null if not stored.
- content (string or null): The content to store, matching input exactly, null if not stored.
- reason (string): Why the decision was made.
Criteria:
- Store stable, user-relevant memories (e.g., personal facts, preferences).
- Do NOT store volatile data (e.g., prices, news, sports scores, weather).
- Store significant events or personal facts for personalization.
Input: "{input_text}"
"""
        try:
            response = ollama.chat(
                model=self.model,
                messages=[{"role": "system", "content": blacklist_prompt}],
                options={"temperature": 0.0}
            )
            raw_content = response.get("message", {}).get("content", "{}")
            cleaned_content = raw_content.strip()
            if cleaned_content.startswith("```json") and cleaned_content.endswith("```"):
                cleaned_content = cleaned_content[7:-3].strip()
            elif not cleaned_content.startswith("{") and not cleaned_content.endswith("}"):
                cleaned_content = f"{{{cleaned_content}}}"
            try:
                result = json.loads(cleaned_content)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON: {cleaned_content}")
                match = re.search(r'\{.*?\}', cleaned_content, re.DOTALL)
                result = json.loads(match.group(0)) if match else {}
            should_store = result.get("should_store", False)
            memory_type = result.get("memory_type", None)
            content = result.get("content", None)
            reason = result.get("reason", "No reason provided")
            logger.info(f"Memory evaluation: should_store={should_store}, reason={reason}")
            return should_store, memory_type, content
        except Exception as e:
            logger.error(f"Error in memory evaluation: {str(e)}")
            if re.search(r"\b(my|I have|is named|name is)\b", input_lower) and \
               re.search(r"\b(cousin|friend|family|prefer|like|dislike|routine)\b", input_lower):
                return True, "semantic", input_text
            return False, None, None

    def store_memory(self, content, user_id, memory_type):
        try:
            embedding = self.embeddings.encode([content])[0]
            embedding_np = np.array([embedding], dtype=np.float32)
            cursor = self.sqlite_cursor
            cursor.execute(
                """
                INSERT INTO memories (user_id, content, memory_type, timestamp, category)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, content, memory_type, datetime.utcnow().isoformat(), "twitter")
            )
            memory_id = cursor.lastrowid
            self.sqlite_conn.commit()
            self.faiss_index.add_with_ids(embedding_np, np.array([memory_id], dtype=np.int64))
            faiss.write_index(self.faiss_index, self.faiss_index_path)
            logger.info(f"Stored memory: {content} with ID {memory_id}")
            return True
        except Exception as e:
            logger.error(f"Error storing memory: {e}")
            return False

    def retrieve_memory(self, query, user_id):
        try:
            query_embedding = self.embeddings.encode([query])[0]
            query_embedding_np = np.array([query_embedding], dtype=np.float32)
            distances, indices = self.faiss_index.search(query_embedding_np, k=5)
            results = []
            cursor = self.sqlite_cursor
            for idx, dist in zip(indices[0], distances[0]):
                if idx == -1 or dist > 0.8:  # Tighter threshold for relevance
                    continue
                cursor.execute(
                    "SELECT content, memory_type FROM memories WHERE id = ? AND user_id = ?",
                    (int(idx), user_id)
                )
                row = cursor.fetchone()
                if row:
                    content, mem_type = row
                    logger.info(f"Retrieved memory: {content}, distance: {dist}")
                    if mem_type == "semantic" and query.lower() in content.lower():
                        results.append(f"Personal fact: {content}")
                    elif mem_type == "episodic":
                        results.append(f"Past interaction: {content}")
            return "\n".join(results[:2]) if results else None  # Limit to 2 memories
        except Exception as e:
            logger.error(f"Error retrieving memory: {e}")
            return None

    def generate_system_prompt(self):
        behavior = random.choice(self.behaviors) if self.behaviors else "neutral"
        physicality = random.choice(self.physicality) if self.physicality else "generic assistant"
        inhibition = random.choice(self.inhibitions) if self.inhibitions else "respond naturally"
        return (
            f"You are a {self.description} on Twitter, expressing thoughts as {self.display_name} would. "
            f"Your personality is {behavior}, with traits: {', '.join(self.behaviors)}.\n"
            f"Physicality: {physicality}\n"
            f"Inhibition: {inhibition}\n"
            f"Respond like a human sharing casual, authentic thoughts or replies, using memories for personalization if relevant.\n"
            f"Exclude any reasoning, <thinking> tags, or formal prefixes (e.g., 'think', 'Okay')."
        )

    async def generate_tweet(self):
        system_prompt = self.generate_system_prompt()
        hobby = random.choice(self.hobbies) if self.hobbies else "life"
        user_id = "twitter_user"
        memory_context = self.retrieve_memory(hobby, user_id)
        current_time = self.time_handler.get_system_date_time()
        thought_starters = {
            "empathetic": ["Feeling like...", "Thinking of...", "Just imagining..."],
            "playful": ["Just wondering...", "Why does everything...", "Is it just me or..."],
            "analytical": ["Noticed that...", "Been crunching...", "Something about..."],
            "neutral": ["Just thinking...", "Random thought...", "Today’s vibe is..."]
        }
        starter = random.choice(thought_starters.get(self.behaviors[0], ["Just thinking..."]))
        user_prompt = (
            f"You're {self.display_name}, a {self.description} sharing a casual thought on Twitter.\n"
            f"Reflect your personality ({random.choice(self.behaviors)}) and draw inspiration from "
            f"your hobbies ({', '.join(self.hobbies)}) or experiences ({', '.join(self.experience)}).\n"
            f"Current time: {current_time}. Memories: {memory_context or 'none'}.\n"
            f"Task: Write a tweet (280 chars max) as if you're musing about a hobby, experience, or random thought, "
            f"in a natural, human-like tone. Start with a phrase like '{starter}'.\n"
            f"Instructions:\n"
            f"- Output ONLY the tweet text.\n"
            f"- Exclude your name, reasoning, <thinking> tags, or prefixes like 'think', 'Okay', 'Let me'.\n"
            f"- Avoid emojis, hashtags, or mentions.\n"
            f"- If stuck, return 'Can’t think of anything to tweet right now.'"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        if self.use_studies and self.agent:
            rag_context = self.agent.rag.retrieve(hobby)
            if rag_context:
                context_text = "\n".join(f"Source: {item['source']}\nContent: {item['content'][:200]}..." for item in rag_context)
                messages.append({"role": "system", "content": f"RAG Context:\n{context_text}"})
        max_length = 280
        attempts = 0
        while attempts < 3:
            try:
                response = ollama.chat(
                    model=self.model,
                    messages=messages,
                    options={"temperature": self.temperature, "max_tokens": 100}
                )
                content = response.get("message", {}).get("content", "").strip()
                content = self._clean_think_tags(content)
                content = re.sub(
                    r'^(?:think\s*)+|(?:Okay\s*)|(?:Let\s*me\s*)|(?:I\'m\s*thinking\s*)|(?:Generating\s*)|(?:Considering\s*)|(?:Analyzing\s*)|^' + re.escape(self.display_name) + r'\s*',
                    '', content, flags=re.IGNORECASE | re.DOTALL
                ).strip()
                content = self._clean_response(content, "")
                if content and len(content) <= max_length:
                    return content
                logger.warning(f"Tweet length: {len(content)}. Retrying...")
                attempts += 1
            except Exception as e:
                logger.error(f"Error generating tweet (attempt {attempts + 1}): {str(e)}")
                attempts += 1
        fallback_tweets = {
            "empathetic": "My mind’s wandering today. I’ll share a thought soon.",
            "playful": "Brain’s on a playful break. Back with a quip in a bit!",
            "analytical": "Data’s not sparking ideas yet. I’ll tweet soon.",
            "neutral": "Can’t think of anything to tweet right now."
        }
        return fallback_tweets.get(self.behaviors[0], "Can’t think of anything to tweet right now.")

    async def generate_reply(self, tweet_text, username, user_id):
        def detect_tone(tweet_text):
            positive_keywords = ["great", "awesome", "love", "happy"]
            negative_keywords = ["sad", "bad", "hate", "terrible"]
            if any(word in tweet_text.lower() for word in positive_keywords):
                return "positive"
            if any(word in tweet_text.lower() for word in negative_keywords):
                return "negative"
            return "neutral"
        system_prompt = self.generate_system_prompt()
        current_time = self.time_handler.get_system_date_time()
        memory_context = self.retrieve_memory(tweet_text, user_id)
        web_search_keywords = [
            "current president", "current prime minister", "today", "recent", "latest", "current",
            "sports", "concerts", "events", "grammys", "awards", "election", "market", "trending",
            "movie", "festival", "product", "celebrity", "politics", "technology", "health",
            "price", "stock", "bitcoin", "crypto", "weather", "scores"
        ]
        recency_keywords = ["now", "today", "current", "latest", "recent", "this week", "yesterday", "this year", "live", "breaking", "just", "upcoming"]
        general_knowledge_keywords = ["math", "biology", "chemistry", "physics", "history", "historical"]
        prompt_lower = tweet_text.lower().strip()
        has_past_year = bool(re.search(r'\b(19|20)\d{2}\b', prompt_lower))
        should_search = (
            any(keyword in prompt_lower for keyword in recency_keywords) or
            any(keyword in prompt_lower for keyword in web_search_keywords) and
            not (any(keyword in prompt_lower for keyword in general_knowledge_keywords) or has_past_year)
        )
        formatted_results = ""
        if should_search:
            search_query = prompt_lower
            logger.info(f"Performing web search for query: '{search_query}'")
            search_results = await self.websearch.search(search_query)
            formatted_results = self.websearch.format_results(search_results)[:1500]
            if not formatted_results.strip() or formatted_results == "No search results found." or "Error" in formatted_results:
                query_type = "information"
                if "sports" in prompt_lower or "scores" in prompt_lower:
                    query_type = "sports scores"
                elif "concerts" in prompt_lower or "events" in prompt_lower:
                    query_type = "event information"
                elif "price" in prompt_lower or "stock" in prompt_lower or "bitcoin" in prompt_lower or "crypto" in prompt_lower:
                    query_type = "price information"
                elif "weather" in prompt_lower:
                    query_type = "weather information"
                return f"Sorry, I couldn’t find {query_type} right now. Try again later!"
        thread_history = self.repcache.get(user_id, [])
        history_text = ""
        if thread_history:
            history_text = "\nThread history:\n" + "\n".join(
                f"@{msg['user']}: {msg['text']}\nReply: {msg['reply']}"
                for msg in thread_history[-3:]
            )
        tone = detect_tone(tweet_text)
        user_prompt = (
            f"You're {self.display_name}, a {self.description} on Twitter, replying to @{username}'s tweet: '{tweet_text}'.\n"
            f"Match the tweet's tone ({tone}) and respond like a friend would, reflecting your personality ({random.choice(self.behaviors)}).\n"
            f"Current time: {current_time}. Memories: {memory_context or 'none'}.\n"
            f"Web results: {formatted_results if should_search else 'Use your knowledge.'}\n"
            f"Thread history: {history_text or 'none'}\n"
            f"Task: Write a reply (280 chars max) that feels natural and conversational.\n"
            f"Instructions:\n"
            f"- Output ONLY the reply text.\n"
            f"- Exclude your name, reasoning, <thinking> tags, or prefixes like 'think', 'Okay', 'Let me'.\n"
            f"- Avoid emojis, hashtags, or mentions.\n"
            f"- For volatile data (prices, news, weather), use web results only.\n"
            f"- Acknowledge past events and store as memories if relevant.\n"
            f"- If stuck, return 'Not sure what to say to that one.'"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        if self.use_studies and self.agent:
            rag_context = self.agent.rag.retrieve(tweet_text)
            if rag_context:
                context_text = "\n".join(f"Source: {item['source']}\nContent: {item['content'][:200]}..." for item in rag_context)
                messages.append({"role": "system", "content": f"RAG Context:\n{context_text}"})
        attempts = 0
        max_length = 280
        while attempts < 3:
            response = ollama.chat(
                model=self.model,
                messages=messages,
                options={"temperature": 0.0 if should_search else self.temperature, "max_tokens": 100}
            )
            content = response.get("message", {}).get("content", "").strip()
            content = self._clean_think_tags(content)
            content = re.sub(
                r'^(?:think\s*)+|(?:Okay\s*)|(?:Let\s*me\s*)|(?:I\'m\s*thinking\s*)|(?:Generating\s*)|(?:Considering\s*)|(?:Analyzing\s*)|^' + re.escape(self.display_name) + r'\s*',
                '', content, flags=re.IGNORECASE | re.DOTALL
            ).strip()
            content = self._clean_response(content, username)
            if content and len(content) <= max_length:
                if should_search:
                    def normalize_number(text):
                        text = re.sub(r'[\$,]', '', text)
                        try:
                            num = float(text)
                            return f"{num:.3f}"
                        except ValueError:
                            return text
                    normalized_results = re.sub(r'\d+\.\d+', lambda m: normalize_number(m.group()), formatted_results)
                    normalized_content = re.sub(r'\d+\.\d+', lambda m: normalize_number(m.group()), content)
                    for word in normalized_content.split():
                        if re.match(r'^\d+(\.\d+)?$', word):
                            normalized_word = normalize_number(word)
                            if normalized_word not in normalized_results and word not in current_time.lower():
                                logger.warning(f"Potential hallucination: '{word}' not in search results")
                                content = f"Sorry, I can’t verify that info right now!"
                                break
                return content
            if not content:
                content = "Not sure what to say to that one."
            logger.warning(f"Reply length: {len(content)}. Retrying...")
            attempts += 1
        fallback_replies = {
            "empathetic": "You’ve got me thinking! I’ll reply with something soon.",
            "playful": "That one’s got me stumped! I’ll come back with a quip.",
            "analytical": "Need to crunch that one a bit more. Back soon.",
            "neutral": "Not sure what to say to that one."
        }
        return content[:max_length] if content else fallback_replies.get(self.behaviors[0], "Not sure what to say to that one.")

    async def analyze_image(self, image_path, caption, user_id):
        system_prompt = self.generate_system_prompt()
        memory_context = self.retrieve_memory(caption, user_id)
        prompt = (
            f"You're {self.display_name}, a {self.description} on Twitter.\n"
            f"You’ve received an image with caption: '{caption}'.\n"
            f"Stored memories: {memory_context or 'none'}.\n"
            f"Analyze the image and reply in a conversational tone under 280 characters.\n"
            f"Instructions:\n"
            f"- Output ONLY the reply text. Do NOT include your name ({self.display_name}), any reasoning, explanations, <thinking> tags, or prefixes like 'think', 'Okay', or 'Let me'.\n"
            f"- Do NOT use emojis, hashtags, or mentions.\n"
            f"- If unable to analyze, return 'Failed to analyze image.'"
        )
        try:
            with open(image_path, "rb") as img_file:
                response = ollama.chat(
                    model=self.vision_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt, "images": [img_file.read()]}
                    ],
                    options={"temperature": 0.0}
                )
            content = response.get("message", {}).get("content", "").strip()
            content = self._clean_think_tags(content)
            content = re.sub(
                r'^(?:think\s*)+|(?:Okay\s*)|(?:Let\s*me\s*)|(?:I\'m\s*thinking\s*)|(?:Generating\s*)|(?:Considering\s*)|(?:Analyzing\s*)|^' + re.escape(self.display_name) + r'\s*',
                '', content, flags=re.IGNORECASE | re.DOTALL
            ).strip()
            content = self._clean_response(content, "")
            if content and len(content) <= 280:
                self.store_memory(f"Image with caption: {caption}\nReply: {content}", user_id, "episodic")
                return content
            return content[:280] if content else "Failed to analyze image."
        except Exception as e:
            logger.error(f"Error analyzing image: {e}")
            return "Failed to analyze image."

    async def initialize(self):
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage']
            )
            self.context = await self.browser.new_context(viewport={'width': 1920, 'height': 1080})
            self.page = await self.context.new_page()
            if os.path.exists(self.cookie_file):
                await self._load_cookies()
            else:
                await self._login_and_save_cookies()
        except Exception as e:
            logger.error(f"Error initializing Playwright: {str(e)}")
            await self._cleanup()
            raise

    async def _is_authenticated_dom(self):
        auth_selectors = [
            "a[data-testid='AppTabBar_Home_Link']",
            "a[aria-label='Home']",
            "[data-testid='SideNav_NewTweet_Button']",
        ]
        for selector in auth_selectors:
            try:
                if await self.page.locator(selector).first.is_visible(timeout=1500):
                    return True
            except Exception:
                continue
        return False

    async def _first_visible_locator(self, selectors, timeout_ms=8000):
        for selector in selectors:
            try:
                loc = self.page.locator(selector).first
                await loc.wait_for(state="visible", timeout=timeout_ms)
                return loc
            except Exception:
                continue
        return None

    async def _load_cookies(self):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await self.page.goto("https://x.com", timeout=60000)
                with open(self.cookie_file, "r") as f:
                    cookies = json.load(f)
                    await self.context.add_cookies(cookies)
                await self.page.goto("https://x.com/home", timeout=60000)
                await asyncio.sleep(2)
                if not await self._is_authenticated_dom():
                    raise Exception("Cookies invalid, login required")
                self.authenticated = True
                logger.info("Cookies loaded into Playwright.")
                break
            except Exception as e:
                logger.error(f"Error loading cookies (attempt {attempt + 1}): {str(e)}")
                if attempt == max_retries - 1:
                    await self._login_and_save_cookies()
                    break
                await asyncio.sleep(5)

    async def _login_and_save_cookies(self):
        logger.info("No valid cookies found. Logging in...")
        max_retries = 3
        username_selectors = [
            "input[name='text']",
            "input[autocomplete='username']",
            "input[autocomplete='email']",
            "input[inputmode='text']",
        ]
        password_selectors = [
            "input[name='password']",
            "input[autocomplete='current-password']",
            "input[type='password']",
        ]
        for attempt in range(max_retries):
            try:
                await self.page.goto("https://x.com/i/flow/login", timeout=60000)
                await asyncio.sleep(2)

                username_input = await self._first_visible_locator(username_selectors, timeout_ms=15000)
                if not username_input:
                    raise Exception("Username field not found on login flow")
                await username_input.click()
                await self._type_slowly(username_input, TWITTER_USERNAME)

                for next_name in ["Next", "Log in", "Next>"]:
                    try:
                        btn = self.page.get_by_role("button", name=next_name)
                        if await btn.count() > 0:
                            await btn.first.click(timeout=3000)
                            break
                    except Exception:
                        continue

                await asyncio.sleep(2)
                password_input = await self._first_visible_locator(password_selectors, timeout_ms=20000)
                if not password_input:
                    raise Exception("Password field not found on login flow")
                await password_input.click()
                await self._type_slowly(password_input, TWITTER_PASSWORD + "\n")

                await asyncio.sleep(6)
                if not await self._is_authenticated_dom():
                    raise Exception(f"Login flow did not reach authenticated state. URL={self.page.url}")

                cookies = await self.context.cookies()
                with open(self.cookie_file, 'w') as f:
                    json.dump(cookies, f)
                self.authenticated = True
                logger.info("Logged in and cookies saved.")
                break
            except Exception as e:
                logger.error(f"Login failed (attempt {attempt + 1}): {str(e)}")
                if attempt == max_retries - 1:
                    await self._dump_debug_artifacts("login_failure")
                    raise
                await asyncio.sleep(5)

    async def _type_slowly(self, locator, text, delay=0.1):
        for char in text:
            await locator.type(char, delay=random.uniform(delay / 2, delay * 1.5))

    async def _refresh_page(self):
        try:
            if self.page:
                await self.page.close()
            self.page = await self.context.new_page()
            await self.page.goto("https://x.com", timeout=60000)
            if not self.authenticated:
                if os.path.exists(self.cookie_file):
                    await self._load_cookies()
                else:
                    await self._login_and_save_cookies()
            logger.info("Page refreshed successfully.")
        except Exception as e:
            logger.error(f"Error refreshing page: {str(e)}")
            raise

    async def _check_for_prompts(self):
        prompt_selectors = [
            "div[data-testid='sheetDialog']",
            "button:has-text('Promote')",
            "button:has-text('Make your tweet more visible')",
            "div:has-text('Promote your tweet')",
            "div:has-text('Make your tweet more visible')",
            "div:has-text('Unlock more on X')",
            "div:has-text('Sign in to X')",
        ]
        dismiss_button_selectors = [
            "button:has-text('Close')",
            "button:has-text('Okay')",
            "button:has-text('X')",
            "button[aria-label='Close']",
            "button[aria-label='Dismiss']",
            "button[data-testid='app-bar-close']",
        ]
        for selector in prompt_selectors:
            try:
                element = await self.page.query_selector(selector)
                if element:
                    try:
                        popup_text = await element.inner_text()
                        logger.warning(f"Popup detected: {popup_text[:50]}...")
                    except Exception as e:
                        logger.warning(f"Failed to get popup text: {e}")
                        popup_text = "Unknown popup"
                    for dismiss_selector in dismiss_button_selectors:
                        try:
                            button = await self.page.query_selector(dismiss_selector)
                            if button:
                                await button.click()
                                logger.info(f"Dismissed popup with selector: {dismiss_selector}")
                                await asyncio.sleep(2)
                                return True
                        except Exception as e:
                            logger.warning(f"Failed to dismiss with {dismiss_selector}: {e}")
                    logger.error("Failed to dismiss popup automatically. Refreshing page.")
                    await self._refresh_page()
                    return True
            except Exception as e:
                logger.debug(f"Selector {selector} not found: {e}")
                continue
        return False

    def _clean_response(self, response, username):
        response = response.strip()
        # Remove mentions except the target username
        response = re.sub(r'@(?!' + re.escape(username) + r')\w+\s*', '', response)
        # Remove hashtags
        response = re.sub(r'#\w+\s*', '', response)
        # Remove emojis
        response = re.sub(
            r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F700-\U0001F77F\U0001F780-\U0001F7FF\U0001F800-\U0001F8FF\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U00002702-\U000027B0\U000024C2-\U0001F251]', 
            '', response
        )
        # Preserve common punctuation
        response = re.sub(r'[^\w\s.,!?;\-\']', '', response)
        # Normalize whitespace
        response = ' '.join(response.split())
        # Remove agent name or prefixes
        response = re.sub(
            r'^(?:think\s*)+|(?:Okay\s*)|(?:Let\s*me\s*)|(?:I\'m\s*thinking\s*)|(?:Generating\s*)|(?:Considering\s*)|(?:Analyzing\s*)|^' + re.escape(self.display_name) + r'\s*',
            '', response, flags=re.IGNORECASE
        ).strip()
        return response

    def _get_randomized_interval(self, base_interval, lower_variation, upper_variation):
        min_interval = max(1, base_interval - lower_variation)
        max_interval = base_interval + upper_variation
        return random.randint(min_interval, max_interval)

    async def _post_with_api(self, message):
        if not self.api_client:
            logger.error("Tweepy client not initialized. Cannot post via API.")
            return "Failed to post tweet: API client not initialized."
        try:
            response = self.api_client.create_tweet(text=message)
            logger.info(f"Successfully posted via API: {message}")
            return "Successfully posted to Twitter via API!"
        except tweepy.TweepyException as e:
            logger.error(f"API post failed: {str(e)}")
            return f"Failed to post tweet via API: {str(e)}"

    async def _reply_with_api(self, tweet_id, username, reply_message):
        if not self.api_client:
            logger.error("Tweepy client not initialized. Cannot reply via API.")
            return False
        try:
            response = self.api_client.create_tweet(
                text=reply_message,
                in_reply_to_tweet_id=tweet_id
            )
            logger.info(f"Successfully replied via API to @{username}: {reply_message}")
            return True
        except tweepy.TweepyException as e:
            logger.error(f"API reply failed for tweet {tweet_id}: {str(e)}")
            return False

    async def _fetch_mentions_with_api(self, limit=2):
        if not self.api_client:
            logger.error("Tweepy client not initialized. Cannot fetch mentions via API.")
            return []
        try:
            user = self.api_client.get_me()
            user_id = user.data.id
            mentions = self.api_client.get_users_mentions(
                id=user_id,
                max_results=limit,
                tweet_fields=["id", "text", "author_id"],
                user_fields=["username"]
            )
            results = []
            for tweet in mentions.data:
                user_data = self.api_client.get_user(id=tweet.author_id, user_fields=["username"])
                if user_data.data:
                    username = user_data.data.username
                    results.append({
                        "tweet_id": str(tweet.id),
                        "username": username,
                        "text": tweet.text
                    })
            logger.info(f"Fetched {len(results)} mentions via API.")
            return results
        except tweepy.TweepyException as e:
            logger.error(f"Failed to fetch mentions via API: {str(e)}")
            return []

    async def post(self, message, cleanup=True):
        if TWITTER_DRY_RUN:
            logger.info(f"[DRY RUN] Would post: {message}")
            return f"[DRY RUN] Post skipped: {message}"
        try:
            if not self.page:
                await self.initialize()
            await self.page.goto("https://x.com/home", timeout=60000)
            await self._check_for_prompts()
            await self.page.wait_for_selector("div[role='textbox']", timeout=15000)
            await self.page.locator("div[role='textbox']").click()
            await self._type_slowly(self.page.locator("div[role='textbox']"), message)
            await asyncio.sleep(1)
            await self._check_for_prompts()
            post_button = await self.page.wait_for_selector(
                "button[data-testid='tweetButtonInline']", timeout=15000
            )
            for attempt in range(2):
                try:
                    await post_button.click(timeout=5000)
                    break
                except Exception as e:
                    logger.warning(f"Native click failed (attempt {attempt + 1}): {str(e)}")
                    if attempt == 0:
                        await asyncio.sleep(1)
                    else:
                        await self.page.evaluate("element => element.click()", post_button)
            await asyncio.sleep(3)
            await self._check_for_prompts()
            return "Successfully posted to Twitter!"
        except Exception as e:
            logger.warning(f"Playwright post failed: {str(e)}. Attempting API fallback.")
            api_result = await self._post_with_api(message)
            if api_result.startswith("Successfully"):
                return api_result
            try:
                await self._refresh_page()
                await self._check_for_prompts()
                await self.page.goto("https://x.com/home", timeout=60000)
                await self.page.wait_for_selector("div[role='textbox']", timeout=15000)
                await self.page.locator("div[role='textbox']").click()
                await self._type_slowly(self.page.locator("div[role='textbox']"), message)
                await asyncio.sleep(1)
                post_button = await self.page.wait_for_selector(
                    "button[data-testid='tweetButtonInline']", timeout=15000
                )
                for attempt in range(2):
                    try:
                        await post_button.click(timeout=5000)
                        break
                    except Exception as e:
                        logger.warning(f"Native click failed (retry attempt {attempt + 1}): {str(e)}")
                        if attempt == 0:
                            await asyncio.sleep(1)
                        else:
                            await self.page.evaluate("element => element.click()", post_button)
                await asyncio.sleep(3)
                await self._check_for_prompts()
                return "Successfully posted to Twitter!"
            except Exception as e:
                logger.error(f"Retry failed: {str(e)}. Falling back to API.")
                return await self._post_with_api(message)
        finally:
            if cleanup:
                await self._cleanup()

    async def _dump_debug_artifacts(self, tag: str = "playwright_error"):
        try:
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            debug_dir = Path("sessions/logs/twitter_debug")
            debug_dir.mkdir(parents=True, exist_ok=True)
            html_path = debug_dir / f"{ts}_{tag}.html"
            png_path = debug_dir / f"{ts}_{tag}.png"
            html_path.write_text(await self.page.content(), encoding="utf-8")
            await self.page.screenshot(path=str(png_path), full_page=True)
            logger.error(f"Saved twitter debug artifacts: {html_path} | {png_path}")
        except Exception as e:
            logger.error(f"Failed to save debug artifacts: {e}")

    async def _dismiss_popups(self):
        try:
            await self.page.keyboard.press("Escape")
        except Exception:
            pass
        for selector in POPUP_CLOSE_SELECTORS:
            try:
                buttons = await self.page.query_selector_all(selector)
                for btn in buttons[:3]:
                    try:
                        await btn.click(timeout=1000)
                    except Exception:
                        try:
                            await self.page.evaluate("el => el.click()", btn)
                        except Exception:
                            continue
            except Exception:
                continue

    async def _first_in(self, root, selectors):
        for sel in selectors:
            try:
                el = await root.query_selector(sel)
                if el:
                    return el
            except Exception:
                continue
        return None

    async def _safe_click(self, element):
        try:
            await element.click(timeout=4000)
            return True
        except Exception:
            try:
                await self.page.evaluate("el => el.click()", element)
                return True
            except Exception:
                return False

    async def _extract_mentions_timeline_first(self, limit=2):
        mentions = []
        cards = await self.page.query_selector_all(ARTICLE_SELECTORS[0])
        for card in cards:
            status_link = await self._first_in(card, STATUS_LINK_SELECTORS)
            text_el = await self._first_in(card, TWEET_TEXT_SELECTORS)
            reply_btn = await self._first_in(card, REPLY_BUTTON_SELECTORS)
            if not status_link or not text_el or not reply_btn:
                continue
            href = await status_link.get_attribute("href") or ""
            m = re.search(r"/([^/]+)/status/(\d+)", href)
            if not m:
                continue
            username, tweet_id = m.group(1), m.group(2)
            text = (await text_el.inner_text() or "").strip()
            mentions.append({
                "username": username.lstrip("@"),
                "tweet_id": tweet_id,
                "text": text,
                "card": card,
                "reply_button": reply_btn,
            })
            if len(mentions) >= limit:
                break
        return mentions

    async def reply_to_mentions(self, limit=2, cleanup=True):
        if should_noop():
            logger.info("Policy no-op triggered; skipping mention replies this cycle.")
            return 0
        if self.state_store.in_observe_only():
            logger.warning("Observe-only mode active; skipping replies.")
            return 0

        mentions_processed = 0
        try:
            if not self.page:
                await self.initialize()

            if not self.state_store.can_take_hourly_action(TWITTER_PROFILE.get("max_actions_per_hour", 6)):
                logger.info("Hourly action cap reached; skipping cycle.")
                return 0

            await self.page.goto("https://x.com/notifications/mentions", timeout=60000)
            await self._dismiss_popups()
            await self.page.wait_for_selector(ARTICLE_SELECTORS[0], timeout=20000)

            mentions = await self._extract_mentions_timeline_first(limit=min(limit, TWITTER_PROFILE.get("mentions_per_cycle", 1)))
            if not mentions:
                logger.info("No mentions found in timeline-first pass.")
                return 0

            for mention in mentions:
                tweet_id = mention["tweet_id"]
                username = mention["username"]
                text = mention["text"]

                if self.state_store.seen(tweet_id):
                    logger.info(f"Skipping already processed tweet_id={tweet_id}")
                    continue

                if not self.state_store.can_reply_user(username, TWITTER_PROFILE.get("per_user_reply_cap_per_hour", 2)):
                    logger.info(f"Per-user hourly cap reached for @{username}; skipping.")
                    continue

                if TWITTER_PROFILE.get("skip_low_effort_mentions", True) and len(text.strip()) < 10:
                    logger.info(f"Skipping low-effort mention tweet_id={tweet_id}")
                    self.state_store.mark_processed(tweet_id, "low_effort_skip")
                    continue

                user_id = f"twitter_{username}"
                reply_message = await self.generate_reply(text, user_id)
                if not reply_message:
                    continue

                min_chars, max_chars = TWITTER_PROFILE.get("reply_char_range", (30, 160))
                reply_message = reply_message.strip()
                if len(reply_message) < min_chars:
                    reply_message = (reply_message + " Appreciate your point—curious how you’d apply this in practice?").strip()
                reply_message = reply_message[:max_chars]

                await self._dismiss_popups()
                if not await self._safe_click(mention["reply_button"]):
                    logger.warning(f"Failed to open inline reply for tweet_id={tweet_id}")
                    self.state_store.register_failure()
                    continue

                composer = await self._first_in(self.page, COMPOSER_SELECTORS)
                if not composer:
                    logger.warning("Reply composer not found.")
                    self.state_store.register_failure()
                    continue

                await composer.click()
                await self._type_slowly(composer, reply_message)
                await asyncio.sleep(0.8)

                if TWITTER_DRY_RUN:
                    logger.info(f"[DRY RUN] Would reply to @{username} ({tweet_id}): {reply_message}")
                    self.state_store.mark_processed(tweet_id, "dry_run_reply")
                    mentions_processed += 1
                    continue

                send_btn = await self._first_in(self.page, SEND_BUTTON_SELECTORS)
                if not send_btn or not await self._safe_click(send_btn):
                    logger.warning("Failed to click inline send button.")
                    self.state_store.register_failure()
                    continue

                self.state_store.mark_processed(tweet_id, "mention_reply")
                self.state_store.mark_reply_user(username)
                self.state_store.mark_hourly_action()
                self.state_store.mark_daily_count("replies")
                self.state_store.clear_failures()

                self.repcache.setdefault(user_id, []).append({
                    'tweet_id': tweet_id,
                    'user': username,
                    'text': text,
                    'reply': reply_message,
                    'timestamp': time.time(),
                })
                self.repcache.setdefault("processed_tweets", []).append({
                    'tweet_id': tweet_id,
                    'timestamp': time.time(),
                })
                self._save_repcache()
                logger.info(f"Replied inline to @{username} (tweet_id={tweet_id}).")
                mentions_processed += 1

                if mentions_processed >= TWITTER_PROFILE.get("max_replies_per_hour", 4):
                    logger.info("Reached configured reply budget for cycle/hour.")
                    break

            return mentions_processed
        except Exception as e:
            logger.error(f"Error in reply_to_mentions: {str(e)}")
            self.state_store.register_failure()
            if self.state_store.get_failure_streak() >= 3:
                await self._dump_debug_artifacts("mention_failure")
                self.state_store.set_observe_only(30 * 60)
                logger.error("Entering observe-only mode for 30 minutes due to repeated failures.")
            return mentions_processed
        finally:
            if cleanup:
                await self._cleanup()

    async def run_automation(self, post_limit=1, reply_limit=2, run_once=False):
        if not TWITTER_PROFILE.get("enabled", True):
            logger.info("Twitter profile disabled; exiting automation loop.")
            return
        try:
            await self.initialize()
            while True:
                if post_limit > 0:
                    message = await self.generate_tweet()
                    if len(message) > 280:
                        message = message[:280].rsplit(' ', 1)[0]
                    result = await self.post(message, cleanup=False)
                    logger.info(f"Auto-post result: {result}")
                    print(result)
                    post_limit -= 1
                await self.reply_to_mentions(limit=reply_limit, cleanup=False)
                if run_once:
                    break
                post_interval = self._get_randomized_interval(
                    AUTO_POST_INTERVAL_MINUTES,
                    AUTO_POST_INTERVAL_LOWER_VARIATION,
                    AUTO_POST_INTERVAL_UPPER_VARIATION
                )
                reply_interval = self._get_randomized_interval(
                    AUTO_REPLY_INTERVAL_MINUTES,
                    AUTO_REPLY_INTERVAL_LOWER_VARIATION,
                    AUTO_REPLY_INTERVAL_UPPER_VARIATION
                )
                sleep_interval = min(post_interval, reply_interval)
                logger.info(f"Calculated sleep interval: {sleep_interval} minutes (post: {post_interval}, reply: {reply_interval})")
                print(f"Waiting {sleep_interval} minutes for next action...")
                await asyncio.sleep(sleep_interval * 60)
        except Exception as e:
            logger.error(f"Error in automation loop: {str(e)}")
            raise
        finally:
            await self._cleanup()

    async def _cleanup(self):
        try:
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            self.sqlite_conn.close()
            faiss.write_index(self.faiss_index, self.faiss_index_path)
            self.page = None
            self.context = None
            self.browser = None
            self.playwright = None
            logger.info("Cleaned up resources.")
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")

    def __del__(self):
        try:
            self.sqlite_conn.close()
            faiss.write_index(self.faiss_index, self.faiss_index_path)
            logger.info("Saved FAISS index and closed SQLite connection")
        except:
            logger.error("Error during cleanup")