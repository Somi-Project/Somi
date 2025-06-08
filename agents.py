# agents.py
import ollama
from config.settings import DEFAULT_MODEL, MEMORY_MODEL, DEFAULT_TEMP, VISION_MODEL, SYSTEM_TIMEZONE, DISABLE_MEMORY_FOR_FINANCIAL
import json
import random
import logging
from rag import RAGHandler
from handlers.websearch import WebSearchHandler
from handlers.time_handler import TimeHandler
import asyncio
import pytz
import time
import re
from datetime import datetime
import numpy as np
import faiss
import sqlite3

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
    def __init__(self, name, use_studies=False):
        self.personality_config = "config/personalC.json"
        self.default_agent_key = "Name: Somi"  # Fallback key if name resolution fails
        self.use_studies = use_studies  # Store use_studies
        
        # Load agents from personalC.json
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
        
        # Map aliases to agent keys
        self.alias_to_key = {}
        for key, config in self.characters.items():
            aliases = config.get("aliases", []) + [key, key.replace("Name: ", "")]
            for alias in aliases:
                self.alias_to_key[alias.lower()] = key
        
        # Resolve agent key from name or alias
        self.agent_key = self._resolve_agent_key(name)
        character = self.characters.get(self.agent_key, self.characters.get(self.default_agent_key, {}))
        
        # Extract display name (e.g., "Somi" from "Name: Somi")
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
        self._setup_memory_storage()
        if self.use_studies:
            self._load_rag_data()

    def _resolve_agent_key(self, name):
        """Resolve the agent key from name or alias."""
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

    def _sanitize_text(self, text):
        return ''.join(char for char in text if ord(char) < 128)

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
You are a memory evaluation assistant for a dementia support AI. Your task is to determine whether a user input should be stored as a memory. **Return ONLY a valid JSON object** with the following fields:
- should_store (boolean): True if the memory should be stored, False otherwise.
- memory_type (string or null): "semantic" for personal facts/routines, "episodic" for interactions, null if not stored.
- content (string or null): The content to store, must match the user input exactly, null if not stored.
- reason (string): Why the decision was made.

**Do NOT include any text outside the JSON object.** Do NOT include explanations or examples in your response. Just return the JSON object.

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
        try:
            embedding = self.embeddings.encode([content])[0]
            embedding_np = np.array([embedding], dtype=np.float32)
            
            cursor = self.sqlite_cursor
            cursor.execute(
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
            memory_id = cursor.lastrowid
            self.sqlite_conn.commit()
            
            self.faiss_index.add_with_ids(embedding_np, np.array([memory_id], dtype=np.int64))
            faiss.write_index(self.faiss_index, self.faiss_index_path)
            logger.info(f"Stored memory: {content} with ID {memory_id}, embedding norm: {np.linalg.norm(embedding)}")
            return True
        except Exception as e:
            logger.error(f"Error storing memory: {e}")
            return False

    def retrieve_memory(self, query, user_id):
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
                    "SELECT content, memory_type FROM memories WHERE id = ? AND user_id = ?",
                    (int(idx), user_id)
                )
                row = cursor.fetchone()
                if row:
                    content, mem_type = row
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
        experience = random.choice(self.experience) if self.experience else "no past experience"
        inhibition = random.choice(self.inhibitions) if self.inhibitions else "respond naturally"
        return (
            f"You are {self.name}, a {behavior} {self.description}.\n"
            f"Physicality: {physicality}\n"
            f"Experience: {experience}\n"
            f"Inhibition: {inhibition}\n"
            f"Use stored memories to personalize responses when relevant."
        )

    async def generate_response(self, prompt, user_id="default_user", dementia_friendly=False):
        start_total = time.time()
        
        if not prompt.strip():
            logger.info(f"Empty prompt received. Total time: {time.time() - start_total:.2f}s")
            return "Hey, give me something to work with!"

        prompt = prompt.replace("white office", "White House").replace("White office", "White House")
        prompt_lower = prompt.lower().strip()

        memory_context = None
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
        if should_search:
            start_web_search = time.time()
            search_query = prompt_lower
            logger.info(f"Performing web search for query: '{search_query}'")
            search_results = await self.websearch.search(search_query)
            formatted_results = self.websearch.format_results(search_results)[:1500]
            logger.info(f"Web search processing took {time.time() - start_web_search:.2f}s")

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
                content = f"I could not retrieve the {query_type} at this time. Please try again later or check a reliable source."
                self.history.append({"role": "user", "content": prompt})
                self.history.append({"role": "assistant", "content": content})
                logger.info(f"Total response time: {time.time() - start_total:.2f}s")
                return content
        else:
            start_memory = time.time()
            memory_context = self.retrieve_memory(prompt, user_id)
            logger.info(f"Memory retrieval took {time.time() - start_memory:.2f}s")

        start_time_handler = time.time()
        current_time = self.time_handler.get_system_date_time()
        logger.info(f"TimeHandler took {time.time() - start_time_handler:.2f}s")

        messages = []

        system_prompt = f"""
You are a large language model being used inside of an AI agent framework.

You are now {self.name}, a {self.description} AI with a {random.choice(self.behaviors) if self.behaviors else 'neutral'} tone.
The current system time is: {current_time}.
You were trained at an earlier date therefore any enquiries needing up to date knowledge MUST undergo a web search as your trained data may be erroneous.

Your capabilities include:
- **Memory**: Use stored memories to personalize responses, especially for personal facts (e.g., family names, preferences) and past interactions. Memories: {memory_context or 'No relevant memories found'}. NEVER use memories for price, stock, crypto, weather, or news queries.
- **Time Queries**: Access the current date and time using the system clock (via pytz). The current system time is: {current_time}.
- **Web Search**: Access real-time data via a web search API for up-to-date information.
- **Internal Knowledge**: Use your training data for general knowledge, historical facts, mathematics, basic sciences, unless real-time data is needed.
- **Conversational Flexibility**: Engage in open-ended conversations, answer general knowledge questions, perform calculations, or explain concepts.

**Instructions**:
- For time/date queries, use the provided system time.
- For queries requiring up-to-date information (e.g., prices, news, sports, weather), rely ONLY on web search results.
- Use stored memories to enhance personalization and continuity, but NEVER for volatile data like prices, weather, or current events.
- If a memory is stored after this prompt, you MUST acknowledge it in your response (e.g., "I’ll remember that—your cousin’s name is Jeff.") and reflect the stored fact in your reply.
- If the prompt is a statement about a past event (e.g., contains a year like 2025 and isn’t a question), treat it as a fact to acknowledge and store, NOT a query to search. For example, "Arsenal won their 20th Premier League match in April 2025" should be responded to with: "That’s great—Arsenal won their 20th Premier League match in April 2025! I’ll store that for you. Anything else about the game?" Do NOT search for more information unless explicitly requested.
- Cite sources exactly as provided in the web search results.
- For news queries, format as a list of up to 4 headlines, each under 50 words.
- Keep responses under 500 words unless requested otherwise.
- If you have received websearch - if it is a financial query do not under any circumstances use memories or internal training and return the data as "Asset" is currently "Price" USD  e.g. Mew is currently $42.22 USD (this is just an example)

Your role is {self.role}. Respond in a {random.choice(self.behaviors) if self.behaviors else 'neutral'} tone, reflecting your personality: {self.description}.
Physicality: {random.choice(self.physicality) if self.physicality else 'generic assistant'}.
Inhibition: {random.choice(self.inhibitions) if self.inhibitions else 'respond naturally'}.

**Web Search Results**:
{formatted_results if should_search else 'Not required for this query. Use internal knowledge.'}

User Prompt: {prompt}
"""
        messages.append({"role": "system", "content": system_prompt})

        start_history = time.time()
        recent_history = self.history[-3:]
        if recent_history:
            history_text = "\n".join(f"{msg['role']}: {msg['content'][:200]}..." for msg in recent_history if len(msg['content']) > 0)
            messages.append({"role": "system", "content": f"Recent conversation (brief):\n{history_text}"})
        logger.info(f"History processing took {time.time() - start_history:.2f}s")

        is_brief_affirmation = prompt_lower in ["yes", "no", "yep", "nope", "yeah", "nah"]
        if is_brief_affirmation and recent_history:
            previous_message = recent_history[-1]["content"].lower()
            if any(keyword in previous_message for keyword in ["play", "game", "20 questions"]):
                messages.append({"role": "system", "content": "The user is continuing a game. Acknowledge their input and proceed with the game in a playful tone."})
            elif previous_message.endswith("?"):
                messages.append({"role": "system", "content": "The user answered your previous question. Respond appropriately to continue the conversation."})
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
        start_llm = time.time()
        try:
            response = ollama.chat(
                model=self.model,
                messages=messages,
                options={"temperature": 0.0 if should_search else self.temperature}
            )
            content = response.get("message", {}).get("content", "")
            logger.info(f"Raw LLM response: {content}")
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
                system_time_str = current_time.lower()
                for word in normalized_content.split():
                    if re.match(r'^\d+(\.\d+)?$', word):
                        normalized_word = normalize_number(word)
                        if normalized_word not in normalized_results and word not in system_time_str:
                            logger.warning(f"Potential hallucination detected: '{word}' not in web search results")
        except Exception as e:
            logger.error(f"Error in LLM call: {str(e)}")
            content = ""
        logger.info(f"LLM call took {time.time() - start_llm:.2f}s")

        if content:
            should_store, mem_type, mem_content = self.process_memory(prompt, content, user_id)
            if should_store:
                self.store_memory(mem_content, user_id, mem_type)
            self.history.append({"role": "assistant", "content": content})
        else:
            content = "Hmm, I’ve got nothing—maybe my coffee’s cold today!"
            self.history.append({"role": "assistant", "content": content})

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
            if content:
                logger.info(f"Image analysis took {time.time() - start_image:.2f}s")
                self.store_memory(
                    f"User provided image with caption: {caption}\nAssistant responded: {content}",
                    user_id,
                    "episodic"
                )
                return content
            content = "Well, I stared at this pic, but all I’ve got is a blank screen and a caffeine craving!"
            logger.info(f"Image analysis took {time.time() - start_image:.2f}s")
            return content
        except Exception as e:
            logger.error(f"Error in image analysis: {e}")
            content = "Oops, my image-analyzing goggles are on the fritz—give me a sec to reboot!"
            logger.info(f"Image analysis took {time.time() - start_image:.2f}s")
            return content

    def __del__(self):
        try:
            self.sqlite_conn.close()
            faiss.write_index(self.faiss_index, self.faiss_index_path)
            logger.info("Saved FAISS index and closed SQLite connection")
        except:
            logger.error("Error during cleanup")