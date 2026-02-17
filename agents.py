# agents.py
# Mainframe

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
from handlers.websearch_tools.conversion import parse_conversion_request  # parser-gated conversion
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

        # Default / constructor user_id (call-level user_id can override at runtime)
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
                    "inhibitions": [],
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

        # History:
        # - self.history: default single-user history (CLI/GUI unchanged)
        # - self.history_by_user: optional per-user history for Telegram/WhatsApp/etc
        self.history: List[Dict[str, str]] = []
        self.history_by_user: Dict[str, List[Dict[str, str]]] = {}

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
            user_id=self.user_id,  # default; call-level user_id overrides when we call memory methods
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
            "- Never simulate timers or countdowns. If asked to set a reminder, confirm it was scheduled.\n"
        )

    # -------- History selection (safe, minimal) --------
    def _should_use_per_user_history(self, active_user_id: str) -> bool:
        """
        Keep CLI/GUI behavior unchanged:
        - If active_user_id matches the agent's default self.user_id, use self.history.
        - If active_user_id differs (Telegram/WhatsApp multi-chat), use per-user history.
        """
        au = str(active_user_id or "").strip()
        if not au:
            return False
        return au != str(self.user_id)

    def _get_history_list(self, active_user_id: str) -> List[Dict[str, str]]:
        if self._should_use_per_user_history(active_user_id):
            return self.history_by_user.setdefault(active_user_id, [])
        return self.history

    def _push_history_for(self, active_user_id: str, user_prompt: str, assistant_content: str) -> None:
        hist = self._get_history_list(active_user_id)
        hist.append({"role": "user", "content": user_prompt})
        hist.append({"role": "assistant", "content": assistant_content})
        if len(hist) > 60:
            del hist[:-60]

        if self.use_flow:
            self.conversation_cache.append({"role": "user", "content": user_prompt})
            self.conversation_cache.append({"role": "assistant", "content": assistant_content})
            if len(self.conversation_cache) > 10:
                self.conversation_cache = self.conversation_cache[-10:]

    # -------- Local intent routing (memory/goals/reminders) --------
    def _is_personal_memory_query(self, prompt: str) -> bool:
        pl = (prompt or "").strip().lower()
        if not pl:
            return False

        # Strong internal-state triggers: never websearch
        internal_triggers = (
            "what do you remember", "remember about me", "summarize everything you remember",
            "summarize what you remember", "summarize my", "everything you remember about me",
            "my name", "my preference", "my preferences",
            "my goals", "my goal", "my reminders", "goals and reminders",
            "due reminders", "any due reminders", "list my", "show my",
            "forget about", "remove my", "delete my",
        )
        if any(t in pl for t in internal_triggers):
            return True

        if re.search(r"\b(my)\s+(name|preferences?|goals?|reminders?)\b", pl):
            return True

        if ("remind me" in pl) and not any(k in pl for k in ("news", "weather", "price", "quote", "market")):
            return True

        return False

    async def _route_local_memory_intents(self, prompt: str, active_user_id: str) -> Optional[str]:
        """
        Handle obvious memory/goals/reminders intents deterministically.
        Returns a final user-facing string if handled, else None (continue normal pipeline).
        """
        pl = (prompt or "").strip()
        pll = pl.lower()
        if not pll:
            return None

        # 1) One-time reminders: "remind me to X in N seconds/minutes/hours/days"
        m = re.search(
            r"^remind me to\s+(.+?)\s+in\s+(\d+)\s+(seconds?|minutes?|hours?|days?)\s*$",
            pll,
        )
        if m:
            title = m.group(1).strip()
            n = int(m.group(2))
            unit = m.group(3).strip()

            # MemoryManager supports "in N unit" parsing; seconds require a memory.py patch (you said you'll do it).
            rid = await self.memory.add_reminder(active_user_id, title=title, when=f"in {n} {unit}", scope="task")
            if rid:
                return f"Got it — reminder set: '{title}' in {n} {unit}."
            return "I couldn't schedule that reminder time. Try: remind me to <task> in 2 minutes."

        # 2) Due reminders: "any due reminders" / "are there any due reminders right now"
        if ("due reminder" in pll) or ("due reminders" in pll):
            due = await self.memory.consume_due_reminders(active_user_id, limit=10)
            if not due:
                return "No due reminders right now."
            lines = ["**Due reminders:**"]
            for d in due:
                title = str(d.get("title", "Reminder"))
                due_ts = str(d.get("due_ts", "soon"))
                lines.append(f"- {title} (due {due_ts})")
            return "\n".join(lines)

        # 3) Save goal (and split off trailing reminder request)
        if pll.startswith("my goal is "):
            tail = pl[len("my goal is "):].strip()

            goal_text = tail
            reminder_tail = ""

            # Split on ". remind me ..." or " remind me ..."
            mm = re.search(r"^(.*?)(?:\.\s*remind me| remind me)\s+(.+)$", tail, flags=re.IGNORECASE)
            if mm:
                goal_text = (mm.group(1) or "").strip()
                reminder_tail = (mm.group(2) or "").strip()

            if goal_text:
                await self.memory.upsert_goal(active_user_id, title=goal_text, scope="task", progress=0.0, confidence=0.7)

            # If they asked for recurring reminders, be honest (recurring not implemented in MemoryManager yet)
            if reminder_tail:
                # common patterns humans use
                if any(k in reminder_tail.lower() for k in ("every ", "daily", "each day", "every day", "every afternoon", "every morning", "every night")):
                    return (
                        f"Goal saved: {goal_text}\n"
                        "Recurring reminders (e.g., every day at 3pm) aren’t wired up yet. "
                        "Right now I can do one-time reminders like: “remind me to drink water in 2 hours”."
                    )
                # If it's a one-time phrasing like "in 2 hours", let the normal reminder parser handle it
                # by returning None (continue pipeline) OR we can try to schedule directly:
                rm = re.search(r"\bin\s+(\d+)\s+(seconds?|minutes?|hours?|days?)\b", reminder_tail.lower())
                if rm:
                    n = int(rm.group(1))
                    unit = rm.group(2)
                    rid = await self.memory.add_reminder(active_user_id, title=goal_text, when=f"in {n} {unit}", scope="task")
                    if rid:
                        return f"Goal saved: {goal_text}\nAlso set a reminder in {n} {unit}."
                return f"Goal saved: {goal_text}"
            return f"Goal saved: {goal_text}" if goal_text else "I didn’t catch the goal. Try: My goal is <something>."

        # 4) Update goal progress: "update goal <title> to <progress%>"
        if pll.startswith("update goal ") and " to " in pll:
            tail = pl[len("update goal "):].strip()
            parts = tail.rsplit(" to ", 1)
            if len(parts) == 2 and parts[0].strip():
                pct_txt = parts[1].strip().rstrip("%")
                if pct_txt.replace(".", "", 1).isdigit():
                    prog = max(0.0, min(1.0, float(pct_txt) / 100.0))
                    await self.memory.upsert_goal(active_user_id, title=parts[0].strip(), scope="task", progress=prog, confidence=0.72)
                    return f"Updated goal '{parts[0].strip()}' to {int(prog * 100)}%."

        # 5) List goals and/or reminders (best-effort; reminders listing may not exist yet)
        if re.search(r"\b(list|show)\b.*\b(goals?|reminders?)\b", pll) or ("goals and reminders" in pll):
            lines: List[str] = []

            # Goals
            try:
                goals = await self.memory.list_active_goals(active_user_id, scope="task", limit=25)
            except Exception:
                goals = []
            lines.append("**Goals**:")
            if goals:
                for g in goals:
                    title = str(g.get("title", "(untitled)"))
                    progress = g.get("progress", 0.0)
                    try:
                        pct = int(float(progress) * 100)
                    except Exception:
                        pct = 0
                    lines.append(f"- {title} (progress {pct}%)")
            else:
                lines.append("- (none)")

            # Reminders (only if the method exists; otherwise be honest)
            lines.append("\n**Reminders**:")
            list_rem = getattr(self.memory, "list_active_reminders", None)
            if callable(list_rem):
                try:
                    rems = await list_rem(active_user_id, scope="task", limit=25)
                except Exception:
                    rems = []
                if rems:
                    for r in rems:
                        title = str(r.get("title", "(untitled)"))
                        due_ts = str(r.get("due_ts", "(unknown)"))
                        lines.append(f"- {title} (due {due_ts})")
                else:
                    lines.append("- (none)")
            else:
                lines.append("- (listing not available yet — I can only announce reminders when they become due)")

            return "\n".join(lines)

        # 6) Summarize what you remember about me (offline; no websearch)
        if ("remember about me" in pll) or ("what do you remember" in pll) or ("summarize everything you remember" in pll):
            # Pull profile + small conversation summary + goals
            profile = await self.memory.retrieve_relevant_memories("name preferences profile", active_user_id, min_score=0.0, scope="profile")
            conv = await self.memory.retrieve_relevant_memories("key facts", active_user_id, min_score=0.25, scope="conversation")
            goal_ctx = None
            try:
                goal_ctx = await self.memory.build_goal_context(active_user_id, scope="task", limit=10)
            except Exception:
                goal_ctx = None

            parts: List[str] = ["Here’s what I have stored about you:"]
            if profile:
                parts.append("\n**Profile**\n" + profile)
            if goal_ctx:
                parts.append("\n**Goals**\n" + goal_ctx)
            if conv:
                parts.append("\n**Recent memory**\n" + conv)

            if len(parts) == 1:
                return "I don’t have anything stored about you yet."
            return "\n".join(parts)

        # 7) Forget/remove/delete (best-effort: goals/reminders if delete methods exist; otherwise forget_phrase filter)
        if re.search(r"^(forget|remove|delete)\b", pll):
            # Extract target phrase
            mm = re.search(r"^(?:forget|remove|delete)\s+(?:about\s+)?(.+)$", pl, flags=re.IGNORECASE)
            target = (mm.group(1).strip() if mm else "").strip()
            if not target:
                return "Tell me what to forget/remove. Example: “forget about my water goal”."

            removed_any = False

            # Try goal deletion if available
            del_goal = getattr(self.memory, "delete_goal_by_title", None)
            if callable(del_goal):
                try:
                    ok = await del_goal(active_user_id, title=target, scope="task")
                    removed_any = removed_any or bool(ok)
                except Exception:
                    pass

            # Try reminder deletion if available
            del_rem = getattr(self.memory, "delete_reminder_by_title", None)
            if callable(del_rem):
                try:
                    n = await del_rem(active_user_id, title=target, scope="task")
                    removed_any = removed_any or (int(n) > 0)
                except Exception:
                    pass

            # Always add forget-phrase filter as fallback for recall (prevents resurfacing)
            try:
                ok2 = await self.memory.forget_phrase(active_user_id, phrase=target, scope="task")
                removed_any = removed_any or bool(ok2)
            except Exception:
                pass

            return "Done — I’ll stop using that." if removed_any else "I couldn’t find anything matching that to remove, but I’ll avoid bringing it up."

        return None

    def _should_websearch(self, prompt: str) -> bool:
        """
        Network decision gate (natural-language-first):
        - Default to LLM-only.
        - Search only when user intent requires freshness/volatility/citations or research.
        """
        pl = (prompt or "").strip().lower()
        if not pl:
            return False

        # Hard block: internal state / memory/goals/reminders must never websearch
        if self._is_personal_memory_query(pl):
            return False

        explicit = any(k in pl for k in (
            "search", "look up", "google", "find online", "check online",
            "source", "sources", "cite", "citation", "link", "verify", "confirm online",
        ))

        recency = any(k in pl for k in (
            "latest", "current", "today", "now", "right now", "this week", "updated", "newest",
            "breaking", "live", "recent",
        ))

        volatile = any(k in pl for k in (
            "price", "quote", "market", "stock", "shares",
            "bitcoin", "btc", "ethereum", "eth", "crypto", "coin",
            "exchange rate", "fx", "forex",
            "weather", "forecast", "temperature", "rain",
            "news", "headline", "current events",
        ))

        research_keywords = (
            "evidence", "paper", "papers", "study", "studies", "literature", "review",
            "systematic review", "meta-analysis", "metaanalysis",
            "rct", "randomized", "randomised", "trial", "clinical trial",
            "guideline", "practice guideline", "consensus", "position statement",
            "pmid", "pubmed", "doi", "arxiv", "openalex", "semantic scholar", "crossref",
            "clinicaltrials", "clinicaltrials.gov", "nct",
        )
        research = any(k in pl for k in research_keywords) or bool(
            re.search(r"\b(10\.\d{4,9}/\S+|pmid\s*\d{6,9}|nct\s*\d{8}|arxiv\s*:\s*\d{4}\.\d{4,5})\b", pl)
        )

        years = [int(y) for y in re.findall(r"\b(19\d{2}|20\d{2})\b", pl)]
        has_year = bool(years)
        near_present = any(y >= 2023 for y in years)

        historical_only = has_year and not (explicit or recency or volatile or research) and not near_present
        if historical_only:
            return False

        return bool(explicit or recency or volatile or research or (has_year and near_present))

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

    async def _persist_memory_serial(self, mem_content: str, user_id: str, mem_type: str, source: str, scope: str = "conversation") -> None:
        try:
            async with self._mem_write_sem:
                await self.memory.store_memory(mem_content, user_id, mem_type, source=source, scope=scope)
        except Exception:
            pass

    def _memory_scope_for_prompt(self, prompt: str, should_search: bool = False) -> str:
        pl = (prompt or "").lower()
        if self.current_mode == "story":
            return "task"
        if any(k in pl for k in ("remember", "always", "preference", "my favorite", "i prefer", "call me")):
            return "profile"
        if should_search:
            return "task"
        return "conversation"

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

        # Call-level user_id override (Telegram/WhatsApp multi-chat)
        active_user_id = str(user_id or self.user_id)
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
                self._push_history_for(active_user_id, prompt, game_response)
                if game_ended:
                    self.current_mode = "normal"
                return game_response

        # --- NEW: Local deterministic routing for memory/goals/reminders (prevents websearch + LLM hallucination) ---
        try:
            local = await self._route_local_memory_intents(prompt, active_user_id)
            if local:
                self._push_history_for(active_user_id, prompt, local)
                return local
        except Exception as e:
            logger.debug(f"Local intent routing failed (non-fatal): {e}")

        # Early conversion handoff (ONLY if parser confirms conversion)
        try:
            if parse_conversion_request(prompt) is not None:
                async with asyncio.timeout(20.0):
                    conv_result = await self.websearch.converter.convert(prompt)
                if conv_result and "Error" not in conv_result and len(conv_result.strip()) > 5:
                    self._push_history_for(active_user_id, prompt, conv_result)
                    return conv_result + "\n(Source: real-time finance data)"
        except Exception as e:
            logger.debug(f"Early conversion failed: {e}")
            # fall through — normal routing continues

        # Lightweight proactive memory commands (kept for backwards compatibility; local router handles most)
        try:
            m = re.search(r"^remind me to\s+(.+?)\s+in\s+(\d+)\s+(seconds?|minutes?|hours?|days?)$", prompt_lower)
            if m:
                title = m.group(1).strip()
                n = int(m.group(2))
                unit = m.group(3)
                rid = await self.memory.add_reminder(active_user_id, title=title, when=f"in {n} {unit}", scope="task")
                if rid:
                    return f"Got it — reminder set: '{title}' in {n} {unit}."
                return "I couldn't parse that reminder time. Try: remind me to <task> in 2 hours."
        except Exception:
            pass

        detail_keywords = ["explain", "detail", "in-depth", "detailed", "elaborate", "expand", "clarify", "iterate"]
        long_form = long_form or any(k in prompt_lower for k in detail_keywords) or self.current_mode == "story"
        base_max_tokens = 650 if long_form or self.current_mode == "story" else 260

        should_search = self._should_websearch(prompt)

        search_context = "Not required for this query. Use internal knowledge."
        memory_context = "No relevant memories found"
        results: List[Dict[str, Any]] = []
        volatile_search = False
        volatile_category = "general"

        if should_search:
            try:
                results = await self.websearch.search(prompt)
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
            mem_scope = self._memory_scope_for_prompt(prompt, should_search=False)
            mem = await self.memory.retrieve_relevant_memories(prompt, active_user_id, min_score=0.20, scope=mem_scope)
            due = await self.memory.consume_due_reminders(active_user_id, limit=3)
            due_block = ""
            if due:
                due_lines = [f"- {d.get('title','Reminder')} (due {d.get('due_ts','soon')})" for d in due[:3]]
                due_block = "\n".join(due_lines)
            if mem and due_block:
                memory_context = f"[Due reminders]\n{due_block}\n\n[Memory]\n{mem}"
            elif mem:
                memory_context = mem
            elif due_block:
                memory_context = f"[Due reminders]\n{due_block}"

        rag_block = self._build_rag_block(prompt, k=2)
        current_time = self.time_handler.get_system_date_time()
        identity_block = self._compose_identity_block()

        mode_context = "Normal mode."
        if self.current_mode == "story":
            mode_context = "Story mode active. Continue the story coherently. End with 'Want more?'"

        extra_blocks = []
        if rag_block:
            extra_blocks.append(rag_block)
        try:
            goal_ctx = await self.memory.build_goal_context(active_user_id, scope="task", limit=3)
            if goal_ctx:
                extra_blocks.append("## Active Goals\n" + goal_ctx)
        except Exception:
            pass

        if should_search:
            sources = self._extract_urls_from_results(results, limit=4)
            sources_text = "\n".join([f"- {u}" for u in sources]) if sources else "(No URLs available in results.)"

            evidence_rules = (
                "## Evidence Rules (STRICT)\n"
                "You MUST follow these rules when Web/Search Context is present:\n"
                "1) Use ONLY facts found in Web/Search Context. Do NOT guess or fill in missing details.\n"
                "2) If something is not in the results, say you cannot verify it from the search results.\n"
                "3) For volatile data (prices, rates, weather, breaking news, scientific citations/guidelines): do NOT invent numbers. If you cite a number, it must appear verbatim in the results.\n"
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

        system_prompt += (
            "\n\nFor currency or crypto conversions (like \"100 AUD to TTD\" or \"0.5 BTC to ETH\"): "
            "please use the finance/conversion tools or search for current rates — old numbers from training are usually wrong."
        )

        max_tokens = self._token_budget(prompt, system_prompt, base_max_tokens)

        hist = self._get_history_list(active_user_id)
        history_msgs = hist[-10:] if hist else []

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
                should_store, mem_type, mem_content = await self.memory.should_store_memory(prompt, content, active_user_id)
                mem_scope = self._memory_scope_for_prompt(prompt, should_search=should_search)
                if should_store and mem_type and mem_content:
                    self.memory.stage_memory(
                        user_id=active_user_id,
                        memory_type=mem_type,
                        content=mem_content,
                        source="conversation",
                        scope=mem_scope,
                    )
                    asyncio.create_task(
                        self._persist_memory_serial(mem_content, active_user_id, mem_type, source="conversation", scope=mem_scope)
                    )
            except Exception:
                pass

        self._push_history_for(active_user_id, prompt, content)
        logger.info(f"[{active_user_id}] Total response time: {time.time() - start_total:.2f}s")
        return content

    async def analyze_image(self, image_path: str, caption: str = "", user_id: str = "default_user") -> str:
        active_user_id = str(user_id or self.user_id)

        system_prompt = self._compose_identity_block()
        memory_context = (
            await self.memory.retrieve_relevant_memories(caption or "image", active_user_id, min_score=0.20, scope="vision")
            or "No relevant memories found"
        )

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
            self.memory.stage_memory(user_id=active_user_id, memory_type="episodic", content=note, source="vision", scope="vision")
            asyncio.create_task(self._persist_memory_serial(note, active_user_id, "episodic", source="vision", scope="vision"))
            return content or "I couldn't extract anything useful from that image."
        except Exception as e:
            return f"Sorry — image analysis failed ({type(e).__name__})."

    def clear_short_term_history(self) -> None:
        # Preserve existing CLI/GUI semantics: clears only default history
        self.history = []

    def __del__(self):
        try:
            if self.current_mode == "game":
                self.wordgame.clear_game_state()
        except Exception:
            pass
