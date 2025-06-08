import psycopg2
from typing import List, Dict
import logging
import json
import requests
import numpy as np
from sentence_transformers import SentenceTransformer
from psycopg2 import pool
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MemoryHandler:
    BLACKLIST = [
        "price", "stock", "crypto", "weather", "news", "sports", "score",
        "concert", "event", "award", "grammy", "election", "market", "trending"
    ]

    def __init__(self, db_params: Dict[str, str], agent_name: str):
        self.db_params = db_params
        self.agent_name = agent_name
        self.conn_pool = None
        self.embedding_model = None
        self.llm_url = "http://127.0.0.1:11434/api/chat"
        try:
            self._initialize_resources()
        except Exception as e:
            logger.error(f"MemoryHandler initialization failed: {str(e)}")
            raise

    def _initialize_resources(self):
        try:
            self.conn_pool = psycopg2.pool.SimpleConnectionPool(minconn=1, maxconn=5, **self.db_params)
            logger.info("Initialized PostgreSQL connection pool")
        except Exception as e:
            logger.error(f"Failed to initialize connection pool: {str(e)}")
            raise

        try:
            self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("Loaded SentenceTransformer model")
        except Exception as e:
            logger.error(f"Failed to load SentenceTransformer: {str(e)}")
            raise

        self._ensure_tables()

    def _get_connection(self):
        try:
            conn = self.conn_pool.getconn()
            return conn
        except Exception as e:
            logger.error(f"Failed to get connection: {str(e)}")
            raise

    def _release_connection(self, conn):
        try:
            self.conn_pool.putconn(conn)
        except Exception as e:
            logger.error(f"Failed to release connection: {str(e)}")
            raise

    def _ensure_tables(self):
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS memories (
                        id SERIAL PRIMARY KEY,
                        agent_name VARCHAR(50) NOT NULL,
                        context VARCHAR(100) NOT NULL,
                        value TEXT NOT NULL,
                        user_input TEXT NOT NULL,
                        relevance_score FLOAT DEFAULT 10.0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        CONSTRAINT memories_unique UNIQUE (agent_name, context, value, user_input)
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS chat_history (
                        id SERIAL PRIMARY KEY,
                        agent_name VARCHAR(50) NOT NULL,
                        session_id VARCHAR(36) NOT NULL,
                        message_type VARCHAR(20) NOT NULL,
                        content TEXT NOT NULL,
                        embedding VECTOR(384),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                conn.commit()
                logger.info("Ensured memories and chat_history tables exist")
        except Exception as e:
            logger.error(f"Failed to ensure tables: {str(e)}")
            conn.rollback()
            raise
        finally:
            self._release_connection(conn)

    def _call_llm(self, messages: List[Dict[str, str]]) -> str:
        try:
            response = requests.post(
                self.llm_url,
                json={
                    "model": "llama3.2-vision:11b",
                    "messages": messages,
                    "stream": False
                }
            )
            response.raise_for_status()
            return response.json()["message"]["content"]
        except Exception as e:
            logger.error(f"LLM call failed: {str(e)}")
            return ""

    def update_relevance_decay(self):
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE memories
                    SET relevance_score = GREATEST(relevance_score - (EXTRACT(EPOCH FROM (NOW() - created_at)) / 86400) * 0.1, 0)
                    WHERE agent_name = %s;
                """, (self.agent_name,))
                conn.commit()
                logger.info(f"Updated relevance decay for {self.agent_name} in memories table")
        except Exception as e:
            logger.error(f"Failed to update relevance decay: {str(e)}")
            conn.rollback()
        finally:
            self._release_connection(conn)

    def store_memory(self, context: str, value: str, user_input: str, session_id: str):
        if not isinstance(context, str) or not isinstance(value, str) or not isinstance(user_input, str):
            logger.error(f"Invalid memory types: context={type(context)}, value={type(value)}, user_input={type(user_input)}")
            return
        if any(keyword in context.lower() or keyword in value.lower() or keyword in user_input.lower() for keyword in self.BLACKLIST):
            logger.info(f"Skipping memory storage: context='{context}', value='{value}', user_input='{user_input}'")
            return

        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO memories (agent_name, context, value, user_input, relevance_score)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT ON CONSTRAINT memories_unique
                    DO UPDATE SET updated_at = CURRENT_TIMESTAMP, relevance_score = 10.0;
                """, (self.agent_name, context, value, user_input, 10.0))
                conn.commit()
                logger.info(f"Stored memory in memories: context='{context}', value='{value}', user_input='{user_input}'")
        except Exception as e:
            logger.error(f"Failed to store memory in memories: {str(e)}")
            conn.rollback()
            raise
        finally:
            self._release_connection(conn)

        message_text = f"User's {context.replace('user_', '').replace('_', ' ')}: {value}"
        embedding = self.embedding_model.encode([message_text])[0].tolist()
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO chat_history (agent_name, session_id, message_type, content, embedding)
                    VALUES (%s, %s, %s, %s, %s::vector);
                """, (self.agent_name, session_id, "human", message_text, embedding))
                conn.commit()
                logger.info(f"Stored memory in chat_history: context='{context}', value='{value}'")
        except Exception as e:
            logger.error(f"Failed to store in chat_history: {str(e)}")
            conn.rollback()
            raise
        finally:
            self._release_connection(conn)

    def store_message(self, message_type: str, content: str, session_id: str):
        if not isinstance(content, str):
            logger.error(f"Invalid message content type: {type(content)}")
            return
        embedding = self.embedding_model.encode([content])[0].tolist()
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO chat_history (agent_name, session_id, message_type, content, embedding)
                    VALUES (%s, %s, %s, %s, %s::vector);
                """, (self.agent_name, session_id, message_type, content, embedding))
                conn.commit()
                logger.info(f"Stored {message_type} message in chat_history: {content[:50]}...")
        except Exception as e:
            logger.error(f"Failed to store message in chat_history: {str(e)}")
            conn.rollback()
            raise
        finally:
            self._release_connection(conn)

    def extract_memories(self, input_text: str) -> List[Dict[str, str]]:
        if any(keyword in input_text.lower() for keyword in self.BLACKLIST):
            logger.info(f"Skipping memory extraction: input='{input_text}'")
            return []

        prompt = f"""
You are a memory extraction assistant. Your task is to determine if the following user input explicitly states a personal fact about a relationship that should be stored as a memory. The input must clearly indicate a relationship (e.g., "my cousin is Jeff", "Jeff is my cousin"). If it does, extract the context and value in the format specified below. Do NOT store any information containing blacklisted keywords: {', '.join(self.BLACKLIST)}.

Input: "{input_text}"

If the input explicitly states a personal fact about a relationship, return a JSON object like:
{{
  "context": "user_cousin",
  "value": "Jeff"
}}

Possible contexts are: user_cousin, user_favorite_food, user_pet, user_sibling, user_friend.

If the input does not explicitly state a relationship or contains blacklisted keywords, return:
{{
  "context": "",
  "value": ""
}}

Examples:
- "my cousin is Jeff" → {{"context": "user_cousin", "value": "Jeff"}}
- "who is Jeff" → {{"context": "", "value": ""}}
- "Jeff is my other cousin" → {{"context": "user_cousin", "value": "Jeff"}}
- "I like to hang out with Jeff" → {{"context": "", "value": ""}}

Respond ONLY with the JSON object.
"""

        messages = [{"role": "user", "content": prompt}]
        response = self._call_llm(messages)
        try:
            result = json.loads(response)
            if result["context"] and result["value"]:
                memories = [{"context": result["context"], "value": result["value"]}]
                logger.info(f"Extracted memories: {memories}")
                return memories
            else:
                logger.info(f"No memories extracted from input: '{input_text}'")
                return []
        except Exception as e:
            logger.error(f"Failed to parse LLM response for memory extraction: {str(e)}")
            return []

    def identify_context(self, query: str) -> str:
        if any(keyword in query.lower() for keyword in self.BLACKLIST):
            logger.info(f"Skipping context identification: query='{query}'")
            return ""

        prompt = f"""
You are a context identification assistant. Your task is to determine if the following user query is asking about a stored personal fact related to a specific relationship. If it is, identify the context in the format specified below. Do NOT process queries containing blacklisted keywords: {', '.join(self.BLACKLIST)}.

Query: "{query}"

If the query is explicitly asking about a personal fact related to a relationship (e.g., "what's my cousin's name", "who are my cousins"), return a JSON object like:
{{
  "context": "user_cousin"
}}

Possible contexts are: user_cousin, user_favorite_food, user_pet, user_sibling, user_friend.

If the query is not asking about a personal fact related to a relationship or contains blacklisted keywords, return:
{{
  "context": ""
}}

Examples:
- "what's my cousin's name" → {{"context": "user_cousin"}}
- "who are my cousins" → {{"context": "user_cousin"}}
- "what's my friend's name" → {{"context": "user_friend"}}
- "who is Jeff" → {{"context": ""}}
- "who is Jeff to me" → {{"context": ""}}

Respond ONLY with the JSON object.
"""

        messages = [{"role": "user", "content": prompt}]
        response = self._call_llm(messages)
        try:
            result = json.loads(response)
            context = result["context"]
            if context:
                logger.info(f"Identified context: '{context}' for query '{query}'")
            else:
                logger.info(f"No context identified for query '{query}'")
            return context
        except Exception as e:
            logger.error(f"Failed to parse LLM response for context identification: {str(e)}")
            return ""

    def retrieve_memories(self, query: str, session_id: str, k: int = 3, relevance_threshold: float = 1.0) -> List[Dict[str, str]]:
        if any(keyword in query.lower() for keyword in self.BLACKLIST):
            logger.info(f"Skipping memory retrieval: query='{query}'")
            return []

        self.update_relevance_decay()

        context = self.identify_context(query)
        if context:
            conn = self._get_connection()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT context, value, user_input, relevance_score
                        FROM memories
                        WHERE agent_name = %s AND context = %s AND relevance_score >= %s
                        ORDER BY relevance_score DESC, updated_at DESC;
                    """, (self.agent_name, context, relevance_threshold))
                    results = cursor.fetchall()
                    if results:
                        memories = [{"context": result[0], "value": result[1], "user_input": result[2], "relevance_score": result[3], "created_at": None, "updated_at": None} for result in results]
                        logger.info(f"Retrieved memory from memories table: {memories}")
                        return memories
            except Exception as e:
                logger.error(f"Failed to retrieve from memories table: {str(e)}")
                raise
            finally:
                self._release_connection(conn)

        # Vector search fallback
        query_embedding = self.embedding_model.encode([query])[0].tolist()
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT content, 
                           REGEXP_REPLACE(SUBSTRING(content FROM 'User''s ([^:]+):'), 'User''s | ', '', 'g') AS context_raw,
                           'user_' || REGEXP_REPLACE(SUBSTRING(content FROM 'User''s ([^:]+):'), 'User''s | ', '_', 'g') AS context
                    FROM chat_history
                    WHERE agent_name = %s AND session_id = %s AND content LIKE 'User''s %: %'
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s;
                """, (self.agent_name, session_id, query_embedding, k))
                results = cursor.fetchall()
                memories = []
                # Check if results are not empty to avoid tuple unpacking errors
                if not results:
                    logger.info(f"No memories found in chat_history for query '{query}' via vector search")
                    return memories
                for result in results:
                    # Ensure the result has the expected number of columns
                    if len(result) != 3:
                        logger.warning(f"Unexpected result format in chat_history: {result}")
                        continue
                    content, context_raw, extracted_context = result
                    if extracted_context == context and ": " in content:
                        _, value = content.split(": ", 1)
                        memories.append({
                            "context": extracted_context,
                            "value": value,
                            "user_input": content,
                            "relevance_score": None,
                            "created_at": None,
                            "updated_at": None
                        })
                logger.info(f"Retrieved {len(memories)} memories for query '{query}' via vector search")
                return memories
        except Exception as e:
            logger.error(f"Failed to retrieve from chat_history: {str(e)}")
            raise
        finally:
            self._release_connection(conn)

    def close(self):
        try:
            if self.conn_pool:
                self.conn_pool.closeall()
                logger.info("Closed connection pool")
        except Exception as e:
            logger.error(f"Failed to close connection pool: {str(e)}")