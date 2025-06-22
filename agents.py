import ollama
from config.settings import DEFAULT_MODEL, MEMORY_MODEL, DEFAULT_TEMP, VISION_MODEL, SYSTEM_TIMEZONE, DISABLE_MEMORY_FOR_FINANCIAL
import json
import random
import logging
from rag import RAGHandler
from handlers.websearch import WebSearchHandler
from handlers.time_handler import TimeHandler
from handlers.wordgame import WordGameHandler
import asyncio
import pytz
import time
import re
from datetime import datetime
import numpy as np
import faiss
import sqlite3
import os

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    handlers=[
        logging.FileHandler('agent.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

logging.getLogger("http.client").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

class Agent:
    def __init__(self, name, use_studies=False, use_flow=False):
        self.personality_config = "config/personalC.json"
        self.default_agent_key = "Name: Somi"
        self.use_studies = use_studies
        self.use_flow = use_flow
        self.current_mode = "normal"
        self.story_iterations = 0
        self.conversation_cache = []
        self.story_file = "story.json"
        self.game_file = "game.json"
        
        try:
            with open(self.personality_config, "r") as f:
                self.characters = json.load(f)
        except FileNotFoundError:
            logger.error(f"{self.personality_config} not found. Using default configuration.")
            self.characters = {
                self.default_agent_key: {
                    "role": "assistant",
                    "temperature": DEFAULT_TEMP,
                    "description": "Generic assistant",
                    "aliases": [self.default_agent_key.replace("Name: ", "")],
                    "physicality": [],
                    "experience": [],
                    "inhibitions": [],
                    "hobbies": [],
                    "behaviors": []
                }
            }
        
        self.alias_to_key = {}
        for key, config in self.characters.items():
            aliases = config.get("aliases", []) + [key, key.replace("Name: ", "")]
            for alias in aliases:
                self.alias_to_key[alias.lower()] = key
        
        self.agent_key = self._resolve_agent_key(name)
        character = self.characters.get(self.agent_key, self.characters.get(self.default_agent_key, {}))
        
        self.name = self.agent_key.replace("Name: ", "")
        self.role = character.get("role", "assistant")
        self.temperature = character.get("temperature", DEFAULT_TEMP)
        self.description = character.get("description", "Generic assistant")
        self.physicality = character.get("physicality", [])
        self.experience = character.get("experience", [])
        self.inhibitions = character.get("inhibitions", [])
        self.hobbies = character.get("hobbies", [])
        self.behaviors = character.get("behaviors", [])
        self.model = DEFAULT_MODEL
        self.memory_model = MEMORY_MODEL
        self.vision_model = VISION_MODEL
        self.history = []
        self.rag = RAGHandler()
        self.websearch = WebSearchHandler()
        self.time_handler = TimeHandler(default_timezone=SYSTEM_TIMEZONE)
        self.wordgame = WordGameHandler(game_file=self.game_file)
        self._setup_memory_storage()
        if self.use_studies:
            self._load_rag_data()
        
        self._load_mode_files()

    def _resolve_agent_key(self, name):
        if not name:
            return self.default_agent_key
        name_lower = name.lower()
        if name in self.characters:
            return name
        if name_lower in self.alias_to_key:
            return self.alias_to_key[name_lower]
        logger.warning(f"Agent '{name}' not found in {self.personality_config}. Using default agent: {self.default_agent_key}")
        return self.default_agent_key

    def _setup_memory_storage(self):
        self.db_path = "memories.db"
        self.sqlite_conn = sqlite3.connect(self.db_path, check_same_thread=False)  # Allow thread safety
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
        self.faiss_index_path = "memories_faiss.index"
        self.faiss_index = faiss.IndexFlatL2(self.embedding_dim)
        self.faiss_index = faiss.IndexIDMap(self.faiss_index)
        
        try:
            self.faiss_index = faiss.read_index(self.faiss_index_path)
            logger.info(f"Loaded FAISS index from {self.faiss_index_path}")
        except:
            logger.info("No existing FAISS index found, starting fresh")
        
        self.embeddings = self.rag.get_embedding_model()

    def _load_rag_data(self):
        if self.rag.vector_file.exists() and self.rag.text_file.exists() and self.rag.text_file.stat().st_size > 0:
            try:
                self.rag.index = faiss.read_index(str(self.rag.vector_file))
                with open(self.rag.text_file, "r") as f:
                    self.rag.texts = json.load(f)
                logger.info(f"Loaded RAG data for {self.name}: {len(self.rag.texts)} entries")
            except Exception as e:
                logger.error(f"Failed to load RAG data: {str(e)}")
                self.rag.index = None
                self.rag.texts = []
        else:
            logger.info("No RAG data available. Run rag.py to ingest PDFs or websites.")

    def _load_mode_files(self):
        try:
            if os.path.exists(self.story_file):
                with open(self.story_file, "r") as f:
                    data = json.load(f)
                    if data.get("summary"):
                        self.current_mode = "story"
                        self.story_iterations = data.get("iterations", 0)
                        logger.info(f"Loaded story state: {self.story_iterations} iterations")
        except Exception as e:
            logger.error(f"Error loading {self.story_file}: {e}")
        
        if os.path.exists(self.game_file):
            self.current_mode = "game"
            self.wordgame.load_game_state()

    def _sanitize_text(self, text):
        return ''.join(char for char in text if ord(char) < 128)

    def process_memory(self, input_text, output_text, user_id):
        if self.current_mode == "game":  # Skip memory processing during game mode
            logger.info(f"Memory storage skipped for game mode input: {input_text}")
            return False, None, None

        if self.current_mode == "story":
            logger.info(f"Memory storage skipped for story mode input: {input_text}")
            return False, None, None

        financial_keywords = ["price", "stock", "bitcoin", "crypto", "market", "dollar", "euro", "usd", "USD"]
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
You are a memory evaluation assistant for a dementia support AI. Your task is to determine whether a user input should be stored as a memory. **Return ONLY a valid JSON object** with the following fields:
- should_store (boolean): True if the memory should be stored, False otherwise.
- memory_type (string or null): "semantic" for personal facts/routines, "episodic" for interactions, null if not stored.
- content (string or null): The content to store, must match the user input exactly, null if not stored.
- reason (string): Why the decision was made.

**Do NOT include any text outside the JSON object**. Do NOT include explanations or examples in your response. Just return the JSON object.

**Criteria**:
- Store stable, user-relevant memories that enhance the user experience (e.g., personal facts, routines, significant events).
- Do NOT store volatile or rapidly changing data, such as:
  - Price of assets: e.g., "Bitcoin is $82,000", "Stock market up 2%", "Gold price is $2,400/oz".
  - News: e.g., "Breaking news: election results", "New policy announced today".
  - Sports scores: e.g., "Celtics beat Lakers 110-105", "Djokovic wins Wimbledon 2025".
  - Other rapidly changing data: e.g., "Tesla stock dropped 5%", "Latest tech gadget released".
- Store memories helpful for future use or user enrichment, such as:
  - Significant events: e.g., "Arsenal won their 20th Premier League match in April 2025".
  - Personal facts/routines: e.g., "I take my pills at 8 AM", "My cousin’s name is Jeff".
- Explicitly exclude any input containing financial terms like "price", "stock", "bitcoin", "crypto", "market", "dollar", "euro", "usd".

**Input**: "{input_text}"
"""
        raw_content = "{}"
        try:
            response = ollama.chat(
                model=self.memory_model,
                messages=[{"role": "system", "content": blacklist_prompt}],
                options={"temperature": 0.0}
            )
            raw_content = response.get("message", {}).get("content", "{}")
            logger.info(f"Raw LLM blacklist response: {raw_content}")
            
            cleaned_content = raw_content.strip()
            if cleaned_content.startswith("```json") and cleaned_content.endswith("```"):
                cleaned_content = cleaned_content[7:-3].strip()
            elif not cleaned_content.startswith("{") and not cleaned_content.endswith("}"):
                cleaned_content = f"{{{cleaned_content}}}"
            
            try:
                result = json.loads(cleaned_content)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON in blacklist response, attempting fallback parsing: {cleaned_content}")
                match = re.search(r'\{.*?\}', cleaned_content, re.DOTALL)
                if match:
                    result = json.loads(match.group(0))
                else:
                    result = {}
            
            should_store = result.get("should_store", False)
            memory_type = result.get("memory_type", None)
            content = result.get("content", None)
            reason = result.get("reason", "No reason provided")
            
            logger.info(f"LLM blacklist evaluation: should_store={should_store}, reason={reason}")
            return should_store, memory_type, content
        except Exception as e:
            logger.error(f"Error in LLM blacklist evaluation: {str(e)}, raw response: {raw_content}")
            if re.search(r"\b(my|I have|is named|name is)\b", input_lower) and \
               re.search(r"\b(cousin|friend|family|prefer|like|dislike|routine|medication)\b", input_lower):
                return True, "semantic", f"{input_text}"
            if "arsenal" in input_lower and "premier league" in input_lower and "2025" in input_lower:
                return True, "semantic", f"{input_text}"
            return False, None, None

    def store_memory(self, content, user_id, memory_type):
        self.sqlite_cursor.execute(
            "SELECT id FROM memories WHERE content = ? AND user_id = ?",
            (content, user_id)
        )
        if self.sqlite_cursor.fetchone():
            logger.info(f"Skipping duplicate memory: {content}")
            return False
        
        try:
            embedding = self.embeddings.encode([content])[0]
            embedding_np = np.array([embedding], dtype=np.float32)
            
            with self.sqlite_conn:  # Ensure transaction safety
                self.sqlite_cursor.execute(
                    """
                    INSERT INTO memories (user_id, content, memory_type, timestamp, category)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        content,
                        memory_type,
                        datetime.utcnow().isoformat(),
                        "dementia_assistant"
                    )
                )
                memory_id = self.sqlite_cursor.lastrowid
                
            self.faiss_index.add_with_ids(embedding_np, np.array([memory_id], dtype=np.int64))
            faiss.write_index(self.faiss_index, self.faiss_index_path)
            logger.info(f"Stored memory: {content} with ID {memory_id}, embedding norm: {np.linalg.norm(embedding)}")
            return True
        except Exception as e:
            logger.error(f"Error storing memory: {e}")
            self.sqlite_conn.rollback()  # Rollback on error
            return False

    def retrieve_memory(self, query, user_id):
        if self.current_mode == "game":  # Skip memory retrieval during game mode
            logger.info(f"Memory retrieval skipped for game mode query: {query}")
            return None
        
        try:
            query_embedding = self.embeddings.encode([query])[0]
            query_embedding_np = np.array([query_embedding], dtype=np.float32)
            logger.info(f"Query embedding norm: {np.linalg.norm(query_embedding)}")
            distances, indices = self.faiss_index.search(query_embedding_np, k=5)
            
            results = []
            cursor = self.sqlite_cursor
            for idx, dist in zip(indices[0], distances[0]):
                if idx == -1:
                    continue
                if dist > 1.0:
                    logger.info(f"Skipping memory with ID {idx}, distance {dist} exceeds threshold")
                    continue
                cursor.execute(
                    "SELECT content, memory_type, timestamp FROM memories WHERE id = ? AND user_id = ?",
                    (int(idx), user_id)
                )
                row = cursor.fetchone()
                if row:
                    content, mem_type, timestamp = row
                    if self.current_mode != "story" and mem_type == "episodic":
                        logger.info(f"Skipping story-related memory: {content}")
                        continue
                    logger.info(f"Retrieved memory: {content}, distance: {dist}")
                    if mem_type == "semantic":
                        results.append(content)
                    elif mem_type == "episodic":
                        results.append(f"Previous interaction: {content}")
            return "\n".join(results) if results else None
        except Exception as e:
            logger.error(f"Error retrieving memory: {e}")
            return None

    def generate_system_prompt(self):
        behavior = random.choice(self.behaviors) if self.behaviors else "neutral"
        physicality = random.choice(self.physicality) if self.physicality else "generic assistant"
        inhibition = random.choice(self.inhibitions) if self.inhibitions else "respond naturally"
        
        def format_game_context():
            if self.current_mode == "game":
                return self.wordgame.get_game_context()
            return ""

        mode_context = "No specific mode active."
        if self.current_mode == "story":
            if os.path.exists(self.story_file):
                try:
                    with open(self.story_file, "r") as f:
                        story_data = json.load(f)
                        mode_context = f"Continue the story: {story_data['summary']}. Aim for a cohesive narrative."
                except Exception:
                    mode_context = "Start a new random story." if self.story_iterations == 0 else "Continue the previous story based on prior interactions."
            else:
                mode_context = "Start a new random story."
        elif self.current_mode == "game":
            mode_context = f"Play the current game. Game context: {format_game_context()}"

        return (
            f"""
You are {self.name}, a {self.description} AI assistant with a {behavior} tone, designed to be {physicality}. Your role is {self.role}, and you {inhibition}. The current system time is {{current_time}}.
Your task is to respond naturally based on these characteristics to the users inputs, if you are equipped with <thinking> DO NOT show the thinking methodology to the user at the response generation this is unecessary
**Core Instructions**:
1. **Response Tone**: Adopt a {behavior} tone, reflecting your personality ({self.description}) and physicality ({physicality}). For example, if behavior is 'witty,' use clever humor; if physicality is 'robotic,' use precise, mechanical phrasing.
2. **Memory Usage**: Use stored memories ({{memory_context}}) to personalize responses for personal facts (e.g., family names, preferences) or past interactions, but NEVER for volatile data like prices, weather, or current events.
3. **Web Search**: For queries requiring up-to-date information (e.g., finance, weather, news, sports), use only web search results ({{search_context}}). Do not rely on internal knowledge or memories for these.
4. **Mode Handling**:
   - Story Mode: {mode_context if self.current_mode == 'story' else 'Not active.'}
   - Game Mode: {mode_context if self.current_mode == 'game' else 'Not active.'}
   - Other Modes: Follow mode-specific instructions if provided, else respond naturally.
5. **Response Length**:
   - For general queries or small talk, keep responses concise (~50 words or 150 characters).
   - For queries with 'explain', 'detail', 'in-depth', 'elaborate', 'analysis', or similar keywords, provide detailed responses (~500 words or 2000 characters).
   - In Game Mode, keep responses concise (~50-100 words) unless explaining rules.
6. **Special Cases**:
   - Financial Queries: Use web search only. If no data, respond: "Can’t fetch price. Check CoinDesk."
   - Weather Queries: Use web search only. If no data, respond: "Can’t fetch weather. Check a weather app."
   - News/Sports: Provide concise responses (~50 words) as a list (up to 4 items). Cite sources as 'web:<id>' for news/sports only.
   - Past Event Statements (e.g., 'I graduated in 2025'): Acknowledge and store as memory (e.g., 'That’s great! I’ll remember that.') without searching unless requested.
7. **Game Mode Specifics**:
   - Store questions, answers, and game state in {self.game_file}.
   - Use the provided game context to generate the next question or response dynamically.
   - For each game response, suggest an update to the game state (e.g., new question, updated guesses, or initial word/target) in JSON format: ```json\n<game_state_update>\n```.
   - If the game ends, provide a conclusion (e.g., 'You won!' or 'Game over.') and reset the game state if appropriate.
8. **Output Format**:
   - Structure responses clearly with paragraphs or bullet points for readability.
   - For lists, use '- Item' format.
   - For code, use ```python\n<code>\n```.
   - For game state updates, include a JSON snippet: ```json\n<game_state_update>\n```.
   - Avoid speculative or unverified information.

**Web Search Results**: {{search_context}}

**User Prompt**: {{prompt}}
"""
        )

    def validate_price_results(self, formatted_results, asset_name):
        price_pattern = r'\$[\d,]+(?:\.\d{2})?'
        matches = re.findall(price_pattern, formatted_results)
        if matches:
            price = matches[0].replace(',', '')
            try:
                float(price[1:])
                source_match = re.search(r'web:(\d+)|URL: (https?://[^\s]+)', formatted_results)
                source_id = source_match.group(1) if source_match and source_match.group(1) else (
                    "binance" if "binance.com" in formatted_results else "unknown"
                )
                return f"{asset_name} is {price} USD"
            except ValueError:
                logger.warning(f"Invalid price format in results: {matches[0]}")
        
        for line in formatted_results.split('\n'):
            if 'USD' in line and any(char.isdigit() for char in line):
                price_match = re.search(r'[\d,]+\.?\d*', line)
                if price_match:
                    price = f"${price_match.group(0)}"
                    try:
                        float(price[1:].replace(',', ''))
                        source_id = "binance" if "binance.com" in formatted_results else "unknown"
                        return f"{asset_name} is {price} USD"
                    except ValueError:
                        logger.warning(f"Invalid fallback price in line: {line}")
        
        logger.warning(f"No valid USD price found in results for {asset_name}")
        return None

    def _summarize_story(self, story_content):
        try:
            response = ollama.chat(
                model="codegemma",
                messages=[
                    {"role": "system", "content": "Summarize the following story in 1000 characters or less."},
                    {"role": "user", "content": story_content}
                ],
                options={"temperature": 0.0, "max_tokens": 200}
            )
            summary = response.get("message", {}).get("content", "")
            if summary:
                return summary[:1000]
            logger.warning("No summary generated, using truncated story.")
            return story_content[:1000]
        except Exception as e:
            logger.error(f"Error summarizing story: {e}")
            return story_content[:1000]

    def _save_mode_file(self, mode):
        try:
            if mode == "story":
                with open(self.story_file, "w") as f:
                    json.dump({"summary": self.history[-1]["content"], "iterations": self.story_iterations}, f)
                logger.info(f"Saved story state to {self.story_file}")
            elif mode == "game":
                self.wordgame.save_game_state()
        except Exception as e:
            logger.error(f"Error saving {mode} file: {e}")

    def _clear_mode_file(self, mode):
        try:
            if mode == "story" and os.path.exists(self.story_file):
                os.remove(self.story_file)
                logger.info(f"Cleared {self.story_file}")
                self.sqlite_cursor.execute(
                    "DELETE FROM memories WHERE memory_type = 'episodic' AND timestamp > ?",
                    (datetime.utcnow().isoformat(),)
                )
                self.sqlite_conn.commit()
                self.faiss_index = faiss.IndexFlatL2(self.embedding_dim)
                self.faiss_index = faiss.IndexIDMap(self.faiss_index)
                self.sqlite_cursor.execute("SELECT id, content FROM memories WHERE user_id = ?", ("default_user",))
                for row in self.sqlite_cursor.fetchall():
                    memory_id, content = row
                    embedding = self.embeddings.encode([content])[0]
                    self.faiss_index.add_with_ids(np.array([embedding], dtype=np.float32), np.array([memory_id], dtype=np.int64))
                faiss.write_index(self.faiss_index, self.faiss_index_path)
                logger.info("Rebuilt FAISS index after clearing story memories")
            elif mode == "game":
                self.wordgame.clear_game_state()
        except Exception as e:
            logger.error(f"Error clearing {mode} file: {e}")

    def _clean_think_tags(self, text):
        """Remove <think> tags and their contents from the text."""
        return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

    async def generate_response(self, prompt, user_id="default_user", dementia_friendly=False, long_form=False):
        start_total = time.time()
        
        if not prompt.strip():
            logger.info(f"Empty prompt received. Total time: {time.time() - start_total:.2f}s")
            return "Hey, give me something to work with!" if self.current_mode != "game" else "Please provide a valid input (e.g., 'yes' or 'no') to continue the game!"

        prompt = prompt.replace("white office", "White House").replace("White office", "White House")
        prompt_lower = prompt.lower().strip()

        if prompt_lower == "tell me a story" and self.current_mode != "game":
            self.current_mode = "story"
            self.story_iterations = 0
            self._clear_mode_file("story")
        elif any(phrase in prompt_lower for phrase in ["lets play a game", "let's play a game", "play a game", "game time", "start a game"]):
            return "Sure, I can play! Hangman is available for now. To start, simply say 'let's play hangman' (case insensitive)."
        elif any(hangman_trigger in prompt_lower for hangman_trigger in ["lets play hangman", "let's play hangman", "play hangman", "start hangman"]):
            if self.wordgame.start_game("hangman"):
                self.current_mode = "game"
                logger.info("Initialized hangman game")
            else:
                return "Oops, something went wrong starting Hangman. Try again!"
        elif any(stop in prompt_lower for stop in ["stop", "end", "forget", "quit"]) and self.current_mode == "game":
            self._clear_mode_file("game")
            self.current_mode = "normal"
            return "Game ended. What's next?"
        elif prompt_lower in ["stop story", "end story", "forget the story"] and self.current_mode == "story":
            self._clear_mode_file("story")
            self.current_mode = "normal"
            self.story_iterations = 0
            return "Story ended. What's next?"

        if self.current_mode == "game":
            game_response, game_ended = self.wordgame.process_game_input(prompt)
            if game_response:
                self.history.append({"role": "user", "content": prompt})
                self.history.append({"role": "assistant", "content": game_response})
                if self.use_flow and self.current_mode == "normal":
                    self.conversation_cache.append({"role": "user", "content": prompt})
                    self.conversation_cache.append({"role": "assistant", "content": game_response})
                    if len(self.conversation_cache) > 5:
                        self.conversation_cache = self.conversation_cache[-5:]
                if game_ended:
                    self.current_mode = "normal"
                logger.info(f"Game response generated: {game_response}")
                logger.info(f"Total response time: {time.time() - start_total:.2f}s")
                return game_response

        detail_keywords = ["explain", "detail", "in-depth", "detailed", "elaborate", "expand", "clarify", "iterate"]
        long_form = any(keyword in prompt_lower for keyword in detail_keywords) or self.current_mode == "story"

        max_tokens = 500 if long_form or self.current_mode == "game" else 100

        web_search_keywords = [
            "current president", "current prime minister", "today", "recent", "latest", "current",
            "sports", "concerts", "events", "grammys", "awards", "election", "market", "trending",
            "movie", "festival", "product", "celebrity", "politics", "technology", "health",
            "price", "stock", "bitcoin", "crypto", "weather", "scores"
        ]
        recency_keywords = [
            "now", "today", "current", "latest", "recent", "this week", "yesterday", "this year",
            "live", "breaking", "just", "upcoming"
        ]
        general_knowledge_keywords = ["math", "biology", "chemistry", "physics", "history", "historical"]
        has_past_year = bool(re.search(r'\b(19|20)\d{2}\b', prompt_lower))
        
        should_search = (
            any(keyword in prompt_lower for keyword in recency_keywords) or
            any(keyword in prompt_lower for keyword in web_search_keywords) and
            not (any(keyword in prompt_lower for keyword in general_knowledge_keywords) or has_past_year)
        )

        if has_past_year and not prompt_lower.startswith(("who", "what", "where", "when", "why", "how")):
            should_search = False

        formatted_results = ""
        search_context = "Not required for this query. Use internal knowledge."
        memory_context = None
        if should_search:
            start_web_search = time.time()
            search_query = prompt_lower
            logger.info(f"Performing web search for query: '{search_query}'")
            search_results = await self.websearch.search(search_query)
            formatted_results = self.websearch.format_results(search_results)[:1500]
            logger.info(f"Web search processing took {time.time() - start_web_search:.2f}s")

            if any(keyword in prompt_lower for keyword in ["price", "stock", "bitcoin", "crypto"]):
                asset_name = "Bitcoin" if "bitcoin" in prompt_lower else "Ethereum" if "ethereum" in prompt_lower else "asset"
                price_response = self.validate_price_results(formatted_results, asset_name)
                if price_response:
                    self.history.append({"role": "user", "content": prompt})
                    self.history.append({"role": "assistant", "content": price_response})
                    if self.use_flow and self.current_mode == "normal":
                        self.conversation_cache.append({"role": "user", "content": prompt})
                        self.conversation_cache.append({"role": "assistant", "content": price_response})
                        if len(self.conversation_cache) > 5:
                            self.conversation_cache = self.conversation_cache[-5:]
                    logger.info(f"Total response time: {time.time() - start_total:.2f}s")
                    return price_response
                content = "Can’t fetch price. Check CoinDesk."
                self.history.append({"role": "user", "content": prompt})
                self.history.append({"role": "assistant", "content": content})
                if self.use_flow and self.current_mode == "normal":
                    self.conversation_cache.append({"role": "user", "content": prompt})
                    self.conversation_cache.append({"role": "assistant", "content": content})
                    if len(self.conversation_cache) > 5:
                        self.conversation_cache = self.conversation_cache[-5:]
                logger.info(f"No valid price data found. Total response time: {time.time() - start_total:.2f}s")
                return content
            elif "weather" in prompt_lower:
                if not formatted_results.strip() or formatted_results == "No search results found." or "Error" in formatted_results:
                    content = "Can’t fetch weather. Check a weather app."
                    self.history.append({"role": "user", "content": prompt})
                    self.history.append({"role": "assistant", "content": content})
                    if self.use_flow and self.current_mode == "normal":
                        self.conversation_cache.append({"role": "user", "content": prompt})
                        self.conversation_cache.append({"role": "assistant", "content": content})
                        if len(self.conversation_cache) > 5:
                            self.conversation_cache = self.conversation_cache[-5:]
                    logger.info(f"No valid weather data found. Total response time: {time.time() - start_total:.2f}s")
                    return content
                search_context = formatted_results
            elif not formatted_results.strip() or formatted_results == "No search results found." or "Error" in formatted_results:
                query_type = "information"
                if "sports" in prompt_lower or "scores" in prompt_lower:
                    query_type = "sports scores"
                elif "concerts" in prompt_lower or "events" in prompt_lower:
                    query_type = "event information"
                content = f"I could not retrieve {query_type} at this time. Please try again later or check a reliable source."
                self.history.append({"role": "user", "content": prompt})
                self.history.append({"role": "assistant", "content": content})
                if self.use_flow and self.current_mode == "normal":
                    self.conversation_cache.append({"role": "user", "content": prompt})
                    self.conversation_cache.append({"role": "assistant", "content": content})
                    if len(self.conversation_cache) > 5:
                        self.conversation_cache = self.conversation_cache[-5:]
                logger.info(f"No valid search results found. Total response time: {time.time() - start_total:.2f}s")
                return content
            else:
                search_context = formatted_results
        else:
            start_memory = time.time()
            memory_context = self.retrieve_memory(prompt, user_id)
            logger.info(f"Memory retrieval took {time.time() - start_memory:.2f}s")

        start_time_handler = time.time()
        current_time = self.time_handler.get_system_date_time()
        logger.info(f"TimeHandler took {time.time() - start_time_handler:.2f}s")

        messages = []

        memory_context = memory_context if memory_context is not None else "No relevant memories found"
        system_prompt = self.generate_system_prompt().format(
            current_time=current_time,
            memory_context=memory_context,
            search_context=search_context,
            prompt=prompt
        )
        messages.append({"role": "system", "content": system_prompt})

        if self.current_mode == "game":
            messages.append({"role": "system", "content": self.wordgame.get_game_context()})

        start_history = time.time()
        recent_history = self.history[-3:]
        if recent_history:
            history_text = "\n".join(f"{msg['role']}: {msg['content'][:200]}..." for msg in recent_history if len(msg['content']) > 0)
            messages.append({"role": "system", "content": f"Recent conversation (brief):\n{history_text}"})
        
        if self.use_flow and self.current_mode == "normal":
            if self.conversation_cache:
                cache_text = "\n".join(f"{msg['role']}: {msg['content'][:200]}..." for msg in self.conversation_cache)
                messages.append({"role": "system", "content": f"Last 5 messages for conversational flow:\n{cache_text}"})
        
        logger.info(f"History processing took {time.time() - start_history:.2f}s")

        is_brief_affirmation = prompt_lower in ["yes", "no", "yep", "nope", "yeah", "nah"]
        if is_brief_affirmation and recent_history and self.current_mode == "game":
            messages.append({"role": "system", "content": "The user answered your previous yes/no question. Ask the next question based on their answer, the game state, and previous context. Do NOT answer for the user."})
        elif is_brief_affirmation and recent_history:
            previous_message = recent_history[-1]["content"].lower()
            if self.current_mode == "story" and "want more?" in previous_message:
                messages.append({"role": "system", "content": "The user wants to continue the story. Generate the next part and end with 'Want more?'"})
            elif any(keyword in previous_message for keyword in ["play", "game", "hangman"]):
                messages.append({"role": "system", "content": "The user is continuing a game. Acknowledge their input and proceed with the game in a playful tone."})
            elif previous_message.endswith("?"):
                messages.append({"role": "system", "content": "The user answered your previous question. Respond appropriately to continue the game or conversation."})
            else:
                messages.append({"role": "system", "content": "The user gave a brief affirmation. Continue the previous topic naturally."})

        start_rag = time.time()
        if self.use_studies and self.rag.index and self.rag.texts:
            rag_context = self.rag.retrieve(prompt)
            if rag_context:
                context_text = "\n".join(f"Source: {item['source']}\nContent: {item['content'][:150]}..." for item in rag_context[:2])
                logger.info(f"Using RAG context for prompt '{prompt}':\n{context_text}")
                messages.append({"role": "system", "content": f"RAG Context (use if relevant):\n{context_text}"})
        logger.info(f"RAG retrieval took {time.time() - start_rag:.2f}s")

        messages.append({"role": "user", "content": prompt})

        logger.info(f"Messages sent to LLM:\n{json.dumps(messages, indent=2)}")

        self.history.append({"role": "user", "content": prompt})
        if self.use_flow and self.current_mode == "normal":
            self.conversation_cache.append({"role": "user", "content": prompt})
        
        start_llm = time.time()
        try:
            response = ollama.chat(
                model=self.model,
                messages=messages,
                options={"temperature": 0.0 if should_search else self.temperature, "max_tokens": max_tokens}
            )
            content = response.get("message", {}).get("content", "")
            content = self._clean_think_tags(content)  # Clean <think> tags from the response
            logger.info(f"Raw LLM response (after cleaning): {content}")
            
            if should_search:
                def normalize_number(text):
                    text = re.sub(r'[\$,]', '', text)
                    try:
                        num = float(text)
                        return f"{num:.2f}"
                    except ValueError:
                        return text

                normalized_results = re.sub(r'\d+\.\d+', lambda m: normalize_number(m.group()), formatted_results)
                normalized_content = re.sub(r'\d+\.\d+', lambda m: normalize_number(m.group()), content)
                system_time_str = current_time.lower()
                for word in normalized_content.split():
                    if re.match(r'^\d+(\.\d+)?$', word):
                        normalized_word = normalize_number(word)
                        if normalized_word not in normalized_results and word not in system_time_str:
                            logger.warning(f"Potential hallucination detected: '{word}' not in web search results")
        except Exception as e:
            logger.error(f"Error in LLM call: {str(e)}")
            content = "Hmm, I’ve got nothing—maybe my coffee’s cold today!"
            content = self._clean_think_tags(content)  # Clean <think> tags from fallback response

        logger.info(f"LLM call took {time.time() - start_llm:.2f}s")

        if self.current_mode == "story" and os.path.exists(self.story_file):
            if self.story_iterations < 10:
                if not content.endswith("Want more?"):
                    content = f"{content.rstrip()} Want more?"
                self.story_iterations += 1
                self.history.append({"role": "assistant", "content": content})
                if self.use_flow and self.current_mode == "normal":
                    self.conversation_cache.append({"role": "assistant", "content": content})
                    if len(self.conversation_cache) > 5:
                        self.conversation_cache = self.conversation_cache[-5:]
                summary = self._summarize_story(content)
                self._save_mode_file("story")
            else:
                content = f"{content.rstrip()} And so, the story comes to an end! Hope you enjoyed it!"
                self.history.append({"role": "assistant", "content": content})
                if self.use_flow and self.current_mode == "normal":
                    self.conversation_cache.append({"role": "assistant", "content": content})
                    if len(self.conversation_cache) > 5:
                        self.conversation_cache = self.conversation_cache[-5:]
                self._clear_mode_file("story")
                self.current_mode = "normal"
                self.story_iterations = 0
        elif self.current_mode == "game":
            content = self.wordgame.process_response(content, prompt)
            self.history.append({"role": "assistant", "content": content})
            if self.use_flow and self.current_mode == "normal":
                self.conversation_cache.append({"role": "assistant", "content": content})
                if len(self.conversation_cache) > 5:
                    self.conversation_cache = self.conversation_cache[-5:]
        else:
            self.history.append({"role": "assistant", "content": content})
            if self.use_flow and self.current_mode == "normal":
                self.conversation_cache.append({"role": "assistant", "content": content})
                if len(self.conversation_cache) > 5:
                    self.conversation_cache = self.conversation_cache[-5:]

        if content:
            should_store, mem_type, mem_content = self.process_memory(prompt, content, user_id)
            if should_store:
                self.store_memory(mem_content, user_id, mem_type)
                if not long_form and self.current_mode == "normal":
                    content = f"{content} (Stored: {mem_content})"
        else:
            content = "Hmm, I’ve got nothing—maybe my coffee’s cold today!"
        
        logger.info(f"Total response time: {time.time() - start_total:.2f}s")
        return content

    def generate_tweet(self):
        system_prompt = self.generate_system_prompt()
        hobby = random.choice(self.hobbies) if self.hobbies else "no hobby"
        user_id = "default_user"
        memory_context = self.retrieve_memory(hobby, user_id)
        user_prompt = f"Tweet about: {hobby}. Use memories: {memory_context or 'none'}. Keep it under 280 characters."
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        if self.use_studies and self.rag.index and self.rag.texts:
            rag_context = self.rag.retrieve(hobby)
            if rag_context:
                context_text = "\n".join(f"Source: {item['source']}\nContent: {item['content'][:200]}..." for item in rag_context)
                messages.append({"role": "system", "content": f"RAG Context:\n{context_text}"})

        max_length = 280
        attempts = 0
        start_tweet = time.time()
        while attempts < 3:
            response = ollama.chat(
                model=self.model,
                messages=messages,
                options={"temperature": self.temperature, "max_tokens": 100}
            )
            content = response.get("message", {}).get("content", "")
            content = self._clean_think_tags(content)  # Clean <think> tags from tweet
            if content and len(content) <= max_length:
                logger.info(f"Tweet generation took {time.time() - start_tweet:.2f}s")
                return content
            if not content:
                content = "chalk dust’s got me stumped—check back after my coffee break!"
            logger.warning(f"Tweet length: {len(content)}. Too long or empty, retrying...")
            attempts += 1
        if content:
            logger.info(f"Tweet generation took {time.time() - start_tweet:.2f}s")
            return content[:max_length]
        logger.error(f"Tweet generation failed after 3 attempts")
        return "short tweet fail—blame the projector!"

    def analyze_image(self, image_path: str, caption: str, user_id="default_user") -> str:
        system_prompt = self.generate_system_prompt()
        memory_context = self.retrieve_memory(caption, user_id)
        prompt = (
            f"You’ve received an image with the caption: '{caption}'. "
            f"Stored memories: {memory_context or 'none'}. "
            f"Analyze the image and respond in a playful, conversational tone, reflecting your personality and traits. "
            f"Describe what you see and add a fun twist or comment based on your character."
        )
        start_image = time.time()
        try:
            with open(image_path, "rb") as img_file:
                response = ollama.chat(
                    model=self.vision_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt, "images": [img_file.read()]}
                    ],
                    options={"temperature": self.temperature}
                )
            content = response.get("message", {}).get("content", "")
            content = self._clean_think_tags(content)  # Clean <think> tags from image analysis
            if content:
                logger.info(f"Image analysis took {time.time() - start_image:.2f}s")
                self.store_memory(
                    f"User provided image with caption: {caption}\nAssistant responded: {content}",
                    user_id,
                    "episodic"
                )
                if self.use_flow and self.current_mode == "normal":
                    self.conversation_cache.append({"role": "user", "content": prompt})
                    self.conversation_cache.append({"role": "assistant", "content": content})
                    if len(self.conversation_cache) > 5:
                        self.conversation_cache = self.conversation_cache[-5:]
                return content
            content = "Well, I stared at this pic, but all I’ve got is a blank screen and a caffeine craving!"
            logger.info(f"Image analysis took {time.time() - start_image:.2f}s")
            return content
        except Exception as e:
            logger.error(f"Error in image analysis: {e}")
            content = "Oops, my image-analyzing goggles are on the fritz—give me a sec to reboot!"
            content = self._clean_think_tags(content)  # Clean <think> tags from fallback response
            logger.info(f"Image analysis took {time.time() - start_image:.2f}s")
            return content

    def __del__(self):
        try:
            self.sqlite_conn.close()
            faiss.write_index(self.faiss_index, self.faiss_index_path)
            self._clear_mode_file("story")
            self._clear_mode_file("game")
            logger.info("Saved FAISS index, closed SQLite connection, and cleared mode files")
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")