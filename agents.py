# agents.py
# Somi Agent using PromptForge + JSONL snapshot memory + same-turn recall
# Compatible with rag.py and handlers/websearch.py without requiring new methods.

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from ollama import AsyncClient

from config.settings import (
    DEFAULT_MODEL,
    MEMORY_MODEL,
    DEFAULT_TEMP,
    VISION_MODEL,
    SYSTEM_TIMEZONE,
    DISABLE_MEMORY_FOR_FINANCIAL,
)

from rag import RAGHandler
from handlers.websearch import WebSearchHandler
from handlers.time_handler import TimeHandler
from handlers.wordgame import WordGameHandler

from memory import MemoryManager
from promptforge import PromptForge

os.makedirs(os.path.join("sessions", "logs"), exist_ok=True)
LOG_PATH = os.path.join("sessions", "logs", "bot.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8")],
)
logger = logging.getLogger(__name__)

logging.getLogger("http.client").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


class Agent:
    def __init__(self, name: str, use_studies: bool = False, use_flow: bool = False, user_id: str = "default_user"):
        self.personality_config = "config/personalC.json"
        self.default_agent_key = "Name: Somi"
        self.use_studies = use_studies
        self.use_flow = use_flow

        self.current_mode = "normal"
        self.story_iterations = 0
        self.conversation_cache: List[Dict[str, str]] = []

        self.user_id = str(user_id or "default_user")
        self.session_dir = os.path.join("sessions", self.user_id)
        os.makedirs(self.session_dir, exist_ok=True)
        self.story_file = os.path.join(self.session_dir, "story.json")
        self.game_file = os.path.join(self.session_dir, "game.json")

        self.ollama_client = AsyncClient()
        self.vision_client = AsyncClient()

        self._maintenance_task: Optional[asyncio.Task] = None
        self._mem_write_sem = asyncio.Semaphore(1)

        # Load personality config
        try:
            with open(self.personality_config, "r", encoding="utf-8") as f:
                self.characters = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"Failed to load personality config ({e}) — using default")
            self.characters = {
                self.default_agent_key: {
                    "role": "assistant",
                    "temperature": DEFAULT_TEMP,
                    "description": "Generic assistant",
                    "aliases": ["Somi"],
                    "physicality": [],
                    "experience": [],
                    "inhibinations": [],
                    "hobbies": [],
                    "behaviors": [],
                }
            }

        # Alias mapping
        self.alias_to_key: Dict[str, str] = {}
        for key, cfg in self.characters.items():
            aliases = cfg.get("aliases", []) + [key, key.replace("Name: ", "")]
            for a in aliases:
                self.alias_to_key[str(a).lower()] = key

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

        self.history: List[Dict[str, str]] = []
        self.rag = RAGHandler()
        self.websearch = WebSearchHandler()
        self.time_handler = TimeHandler(default_timezone=SYSTEM_TIMEZONE)
        self.wordgame = WordGameHandler(game_file=self.game_file)

        self.promptforge = PromptForge(workspace=".")

        embedding_model = self.rag.get_embedding_model()
        self.memory = MemoryManager(
            embedding_model=embedding_model,
            ollama_client=self.ollama_client,
            memory_model_name=self.memory_model,
            user_id=self.user_id,
            base_dir="sessions",
            disable_financial_memory=DISABLE_MEMORY_FOR_FINANCIAL,
        )

        self.turn_counter = 0
        self._load_mode_files()

    def _resolve_agent_key(self, name: str) -> str:
        if not name:
            return self.default_agent_key
        if name in self.characters:
            return name
        nl = name.lower()
        if nl in self.alias_to_key:
            return self.alias_to_key[nl]
        logger.warning(f"Agent '{name}' not found. Using default: {self.default_agent_key}")
        return self.default_agent_key

    def _load_mode_files(self) -> None:
        try:
            if os.path.exists(self.story_file):
                with open(self.story_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("summary"):
                    self.current_mode = "story"
                    self.story_iterations = int(data.get("iterations", 0))
        except Exception:
            self.current_mode = "normal"
            self.story_iterations = 0

        try:
            if os.path.exists(self.game_file):
                self.current_mode = "game"
                self.wordgame.load_game_state()
        except Exception:
            if self.current_mode == "game":
                self.current_mode = "normal"

    def _clean_think_tags(self, text: str) -> str:
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    def _strip_unwanted_json(self, text: str) -> str:
        if self.current_mode != "game":
            text = re.sub(r"```json\s*\{.*?\}\s*```", "", text, flags=re.DOTALL)
        return text.strip()

    def _compose_identity_block(self) -> str:
        behavior = random.choice(self.behaviors) if self.behaviors else "neutral"
        physicality = random.choice(self.physicality) if self.physicality else "generic assistant"
        inhibition = random.choice(self.inhibitions) if self.inhibitions else "respond naturally"

        return (
            f"You are {self.name}, a {self.description} AI assistant.\n"
            f"Role: {self.role}\n"
            f"Tone: {behavior}\n"
            f"Physicality: {physicality}\n"
            f"Constraints: {inhibition}\n\n"
            "Core instructions:\n"
            "- Use Memory Context to personalize responses using stable facts/preferences/instructions.\n"
            "- Never use memory for volatile info like prices, weather, breaking news.\n"
            "- If Web/Search Context is present, use it for up-to-date queries.\n"
            "- Be direct and practical.\n"
        )

    def _push_history(self, user_prompt: str, assistant_content: str) -> None:
        self.history.append({"role": "user", "content": user_prompt})
        self.history.append({"role": "assistant", "content": assistant_content})
        if len(self.history) > 60:
            self.history = self.history[-60:]

        if self.use_flow:
            self.conversation_cache.append({"role": "user", "content": user_prompt})
            self.conversation_cache.append({"role": "assistant", "content": assistant_content})
            if len(self.conversation_cache) > 10:
                self.conversation_cache = self.conversation_cache[-10:]

    def _should_websearch(self, prompt_lower: str) -> bool:
        explicit = any(k in prompt_lower for k in ["search", "look up", "google", "find online", "check online"])
        recency = any(k in prompt_lower for k in ["latest", "today", "now", "current", "this week", "breaking", "live"])
        volatile = any(k in prompt_lower for k in [
            "price", "weather", "forecast", "scores", "market", "stock", "bitcoin", "crypto", "forex",
            "exchange rate", "convert", "conversion", "how much", "how many", "to ", "worth"
        ])
        has_year = bool(re.search(r"\b(19|20)\d{2}\b", prompt_lower))
        return bool((explicit or recency or volatile) and not has_year)

    def _build_rag_block(self, prompt: str, k: int = 2) -> str:
        if not self.use_studies:
            return ""
        try:
            hits = self.rag.retrieve(prompt, k=k)
            if not hits:
                return ""
            parts = []
            for h in hits[:k]:
                src = str(h.get("source", ""))[:120]
                content = str(h.get("content", ""))[:500]
                if content.strip():
                    parts.append(f"- Source: {src}\n  Content: {content}")
            if not parts:
                return ""
            return "## RAG Context (use only if relevant)\n" + "\n".join(parts)
        except Exception as e:
            logger.debug(f"RAG retrieval failed (non-fatal): {e}")
            return ""

    async def _maintenance_tick(self) -> None:
        try:
            async with asyncio.timeout(4.0):
                await self.memory.curate_daily_digest()
                await self.memory.prune_old_memories()
        except Exception:
            pass

    async def _persist_memory_serial(self, mem_content: str, user_id: str, mem_type: str, source: str) -> None:
        try:
            async with self._mem_write_sem:
                await self.memory.store_memory(mem_content, user_id, mem_type, source=source)
        except Exception:
            pass

    def _token_budget(self, prompt: str, system_prompt: str, base_max: int) -> int:
        total_chars = len(prompt) + len(system_prompt)
        if total_chars > 14000:
            return max(120, int(base_max * 0.35))
        if total_chars > 9000:
            return max(160, int(base_max * 0.55))
        if total_chars > 6000:
            return max(180, int(base_max * 0.70))
        return base_max

    def _extract_urls_from_results(self, results: List[Dict[str, Any]], limit: int = 4) -> List[str]:
        urls = []
        for r in results or []:
            if not isinstance(r, dict):
                continue
            u = (r.get("url") or "").strip()
            if u and u.startswith("http"):
                urls.append(u)
            if len(urls) >= limit:
                break
        return urls

    def _is_volatile_results(self, results: List[Dict[str, Any]]) -> Tuple[bool, str]:
        volatile = False
        cat = "general"
        for r in results or []:
            if not isinstance(r, dict):
                continue
            if r.get("category"):
                cat = str(r.get("category"))
            if bool(r.get("volatile", False)):
                volatile = True
        return volatile, cat

    def _numeric_guard(self, content: str, search_context: str) -> str:
        """
        Replace numeric tokens not present in search_context with [see source].
        Uses word-boundary regex replacement to avoid partial replacements.
        """
        try:
            if not content or not search_context:
                return content

            ctx = search_context.lower()
            ctx_norm = ctx.replace(",", "").replace(" ", "")

            numbers = re.findall(r"\b\d{1,3}(?:,\d{3})*(?:\.\d+)?%?\b", content)
            if not numbers:
                return content

            out = content
            for n in set(numbers):
                n_norm = n.lower().replace(",", "").replace(" ", "")
                if n_norm not in ctx_norm:
                    out = re.sub(rf"\b{re.escape(n)}\b", "[see source]", out)
            return out
        except Exception:
            return content

    async def generate_response(
        self,
        prompt: str,
        user_id: str = "default_user",
        dementia_friendly: bool = False,
        long_form: bool = False,
    ) -> str:
        start_total = time.time()
        self.turn_counter += 1

        prompt = (prompt or "").strip()
        if not prompt:
            return "Hey, give me something to work with!"

        prompt_lower = prompt.lower()

        if self.turn_counter % 25 == 0:
            if self._maintenance_task is None or self._maintenance_task.done():
                self._maintenance_task = asyncio.create_task(self._maintenance_tick())

        # Mode toggles
        if self.current_mode == "normal":
            if prompt_lower == "tell me a story":
                self.current_mode = "story"
                self.story_iterations = 0
            elif any(x in prompt_lower for x in ["lets play hangman", "let's play hangman", "play hangman", "start hangman"]):
                if self.wordgame.start_game("hangman"):
                    self.current_mode = "game"
                else:
                    return "Oops, something went wrong starting Hangman. Try again!"

        cmd = prompt_lower.strip()
        if cmd in ("stop", "end", "quit"):
            if self.current_mode == "game":
                self.wordgame.clear_game_state()
                self.current_mode = "normal"
                return "Game ended. What's next?"
            if self.current_mode == "story":
                self.current_mode = "normal"
                self.story_iterations = 0
                try:
                    if os.path.exists(self.story_file):
                        os.remove(self.story_file)
                except Exception:
                    pass
                return "Story ended. What's next?"

        # Game path
        if self.current_mode == "game":
            game_response, game_ended = self.wordgame.process_game_input(prompt)
            if game_response:
                self._push_history(prompt, game_response)
                if game_ended:
                    self.current_mode = "normal"
                return game_response

        # ── Early conversion handoff (prevents LLM from guessing old rates) ──
        conversion_keywords = ["convert", "to ", "how much", "how many", "worth", "equals", "rate of", "exchange"]
        if any(k in prompt_lower for k in conversion_keywords):
            try:
                conv_result = await self.websearch.converter.convert(prompt)
                if conv_result and "Error" not in conv_result and len(conv_result.strip()) > 5:
                    self._push_history(prompt, conv_result)
                    return conv_result + "\n(Source: real-time finance data)"
            except Exception as e:
                logger.debug(f"Early conversion failed: {e}")
                # fall through — LLM can still try

        detail_keywords = ["explain", "detail", "in-depth", "detailed", "elaborate", "expand", "clarify", "iterate"]
        long_form = long_form or any(k in prompt_lower for k in detail_keywords) or self.current_mode == "story"
        base_max_tokens = 650 if long_form or self.current_mode == "story" else 260

        should_search = self._should_websearch(prompt_lower)

        search_context = "Not required for this query. Use internal knowledge."
        memory_context = "No relevant memories found"
        results: List[Dict[str, Any]] = []
        volatile_search = False
        volatile_category = "general"

        if should_search:
            try:
                results = await self.websearch.search(prompt_lower)
                volatile_search, volatile_category = self._is_volatile_results(results)
                formatted = self.websearch.format_results(results)
                if formatted and "Error" not in formatted:
                    search_context = formatted[:2200]
                else:
                    search_context = "Web search returned no results."
            except Exception as e:
                logger.info(f"Web search failed (non-fatal): {e}")
                search_context = "Web search unavailable."
        else:
            mem = await self.memory.retrieve_relevant_memories(prompt, self.user_id, min_score=0.20)
            if mem:
                memory_context = mem

        rag_block = self._build_rag_block(prompt, k=2)
        current_time = self.time_handler.get_system_date_time()
        identity_block = self._compose_identity_block()

        mode_context = "Normal mode."
        if self.current_mode == "story":
            mode_context = "Story mode active. Continue the story coherently. End with 'Want more?'"

        extra_blocks = []
        if rag_block:
            extra_blocks.append(rag_block)

        if should_search:
            sources = self._extract_urls_from_results(results, limit=4)
            sources_text = "\n".join([f"- {u}" for u in sources]) if sources else "(No URLs available in results.)"

            evidence_rules = (
                "## Evidence Rules (STRICT)\n"
                "You MUST follow these rules when Web/Search Context is present:\n"
                "1) Use ONLY facts found in Web/Search Context. Do NOT guess or fill in missing details.\n"
                "2) If something is not in the results, say you cannot verify it from the search results.\n"
                "3) For volatile data (prices, rates, weather, breaking news): do NOT invent numbers. If you cite a number, it must appear verbatim in the results.\n"
                "4) Include source URL(s) for the claims you make.\n"
                f"Category hint: {volatile_category}\n"
                "Sources available:\n"
                f"{sources_text}\n"
            )
            extra_blocks.append(evidence_rules)

        system_prompt = self.promptforge.build_system_prompt(
            identity_block=identity_block,
            current_time=current_time,
            memory_context=memory_context,
            search_context=search_context,
            mode_context=mode_context,
            extra_blocks=extra_blocks if extra_blocks else None,
        )

        # Gentle failsafe reminder — short and natural
        system_prompt += "\n\nFor currency or crypto conversions (like \"100 AUD to TTD\" or \"0.5 BTC to ETH\"): please use the finance/conversion tools or search for current rates — old numbers from training are usually wrong."

        max_tokens = self._token_budget(prompt, system_prompt, base_max_tokens)
        history_msgs = self.history[-10:] if self.history else []

        messages = self.promptforge.build_messages(
            system_prompt=system_prompt,
            history=history_msgs,
            user_prompt=prompt,
        )

        content = ""
        try:
            async with asyncio.timeout(120):
                resp = await self.ollama_client.chat(
                    model=self.model,
                    messages=messages,
                    options={
                        "temperature": 0.0 if should_search else float(self.temperature),
                        "max_tokens": int(max_tokens),
                        "keep_alive": 300,
                    },
                )
            content = resp.get("message", {}).get("content", "") or ""
        except Exception:
            content = "Sorry — generation failed. Try again."

        content = self._clean_think_tags(content)
        content = self._strip_unwanted_json(content)

        if should_search and volatile_search:
            content = self._numeric_guard(content, search_context)

            if "http" not in content.lower():
                urls = self._extract_urls_from_results(results, limit=4)
                if urls:
                    content = content.rstrip() + "\n\nSources:\n" + "\n".join([f"- {u}" for u in urls])

        if self.current_mode == "story":
            if not content.endswith("Want more?"):
                content = content.rstrip() + " Want more?"
            self.story_iterations += 1
            if self.story_iterations >= 10:
                self.current_mode = "normal"
                self.story_iterations = 0
                content = content.rstrip() + " And so, the story comes to an end."

        if dementia_friendly:
            if len(content) > 420:
                content = content[:390] + "... (kept short and clear)"
            content = content.replace("however", "but").replace("therefore", "so")

        # Memory write-back hard-block on websearch turns
        if not should_search:
            try:
                should_store, mem_type, mem_content = await self.memory.should_store_memory(prompt, content, self.user_id)
                if should_store and mem_type and mem_content:
                    self.memory.stage_memory(user_id=self.user_id, memory_type=mem_type, content=mem_content, source="conversation")
                    asyncio.create_task(self._persist_memory_serial(mem_content, self.user_id, mem_type, source="conversation"))
            except Exception:
                pass

        self._push_history(prompt, content)
        logger.info(f"[{self.user_id}] Total response time: {time.time() - start_total:.2f}s")
        return content

    async def analyze_image(self, image_path: str, caption: str = "", user_id: str = "default_user") -> str:
        system_prompt = self._compose_identity_block()
        memory_context = await self.memory.retrieve_relevant_memories(caption or "image", self.user_id, min_score=0.20) or "No relevant memories found"

        prompt = (
            f"You received an image with caption: '{caption or 'Describe this image'}'.\n"
            f"Relevant memory:\n{memory_context}\n\n"
            "Describe what you see clearly. If uncertain, say so."
        )

        try:
            with open(image_path, "rb") as img:
                image_data = img.read()

            async with asyncio.timeout(180):
                resp = await self.vision_client.chat(
                    model=self.vision_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt, "images": [image_data]},
                    ],
                    options={"temperature": float(self.temperature), "keep_alive": 300},
                )
            content = resp.get("message", {}).get("content", "") or ""
            content = self._clean_think_tags(content)
            content = self._strip_unwanted_json(content)

            note = f"Image noted: {caption}".strip()
            self.memory.stage_memory(user_id=self.user_id, memory_type="episodic", content=note, source="vision")
            asyncio.create_task(self._persist_memory_serial(note, self.user_id, "episodic", source="vision"))
            return content or "I couldn't extract anything useful from that image."
        except Exception as e:
            return f"Sorry — image analysis failed ({type(e).__name__})."

    def clear_short_term_history(self) -> None:
        self.history = []

    def __del__(self):
        try:
            if self.current_mode == "game":
                self.wordgame.clear_game_state()
        except Exception:
            pass