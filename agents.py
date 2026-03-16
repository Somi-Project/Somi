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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from runtime.ollama_compat import create_async_client
from runtime.ollama_options import build_ollama_chat_options
from config.settings import (
    GENERAL_MODEL,
    CODING_MODEL,
    MEMORY_MODEL,
    INSTRUCT_MODEL,
    DEFAULT_TEMP,
    VISION_MODEL,
    SYSTEM_TIMEZONE,
    USE_MEMORY3,
    CONTEXT_PROFILE,
    CHAT_CONTEXT_PROFILE,
    CHAT_CONTEXT_PROFILES,
    HISTORY_MAX_MESSAGES,
    ROUTING_DEBUG,
    BUDGET_MEMORY_TOKENS,
    BUDGET_SEARCH_TOKENS,
    BUDGET_HISTORY_TOKENS,
    BUDGET_OUTPUT_RESERVE_TOKENS,
    PROMPT_ENTERPRISE_ENABLED,
    PROMPT_FORCE_LEGACY,
    SESSION_MEDIA_DIR,
    ENABLE_NL_ARTIFACTS,
    ARTIFACT_INTENT_THRESHOLD,
    MIN_SOURCES_FOR_RESEARCH_BRIEF,
    DOC_FACTS_REQUIRE_PAGE_REFS,
    ONE_ARTIFACT_PER_TURN,
    ARTIFACT_DEGRADE_NOTICE,
    ARTIFACT_PLAN_REVISION_MAX_AGE_MINUTES,
    STRATEGIC_HUMAN_SUMMARY_ENABLED,
    ENABLE_SMART_FOLLOWUPS,
    TRANSCRIPT_HYGIENE_ENABLED,
    TRANSCRIPT_MAX_MESSAGES,
    TRANSCRIPT_MAX_MESSAGE_CHARS,
    HISTORY_AUTO_COMPACTION_ENABLED,
    HISTORY_AUTO_COMPACT_TRIGGER_MESSAGES,
    HISTORY_AUTO_COMPACT_KEEP_RECENT_MESSAGES,
    HISTORY_COMPACTION_MAX_ITEMS,
    HISTORY_COMPACTION_SUMMARY_MAX_CHARS,
    HISTORY_AUTO_COMPACT_TRIGGER_TOKENS,
    HISTORY_AUTO_COMPACT_TARGET_TOKENS,
    HISTORY_AUTO_COMPACT_MIN_KEEP_MESSAGES,
    MAX_CONTEXT_TOKENS,
    WEBSEARCH_MODEL,
    MODEL_FAILOVER_ENABLED,
    MODEL_FAILOVER_MAX_ATTEMPTS,
    MODEL_FAILOVER_COOLDOWN_SECONDS,
    MODEL_FAILOVER_FAILS_BEFORE_COOLDOWN,
    MODEL_FAILOVER_RETRYABLE_ERRORS,
    ACTIVE_MODEL_CAPABILITY_PROFILE,
    TOOL_LOOP_DETECTION_ENABLED,
    TOOL_LOOP_HISTORY_SIZE,
    TOOL_LOOP_WARNING_THRESHOLD,
    TOOL_LOOP_CRITICAL_THRESHOLD,
    TOOL_LOOP_GLOBAL_CIRCUIT_BREAKER_THRESHOLD,
    TOOL_LOOP_DETECT_GENERIC_REPEAT,
    TOOL_LOOP_DETECT_NO_PROGRESS,
    TOOL_LOOP_DETECT_PING_PONG,
)
from workshop.toolbox.stacks.research_core.rag_handler import RAGHandler
try:
    from workshop.toolbox.stacks.web_core.websearch import WebSearchHandler
except Exception:  # pragma: no cover
    WebSearchHandler = None  # type: ignore
from workshop.toolbox.stacks.web_core.websearch_tools.conversion import parse_conversion_request  # parser-gated conversion
from workshop.toolbox.agent_core.routing import decide_route
from routing.planner import build_query_plan
from workshop.toolbox.stacks.web_core.search_bundle import render_search_bundle
try:
    from synthesis.answer_mixer import mix_answer
except Exception:  # pragma: no cover
    def mix_answer(_prompt: str, *, plan: Any = None, llm_draft: str = "", evidence: Any = None) -> str:
        return str(llm_draft or "")
from workshop.toolbox.agent_core.time_handler import TimeHandler
from workshop.toolbox.agent_core.tool_context import ToolContextStore
from workshop.toolbox.agent_core.followup_resolver import FollowUpResolver
from workshop.toolbox.agent_core.wordgame import WordGameHandler
from workshop.toolbox.agent_core import parse_delegation_command, render_delegation_help
from workshop.skills.dispatch import handle_skill_command
from workshop.skills.registry import build_registry_snapshot
from workshop.skills import StarterStudioService
from runtime.approval import ApprovalReceipt
from runtime.controller import handle_turn
from runtime.ticketing import ExecutionTicket
from executive.istari_runtime import IstariProtocol
from executive.life_modeling.artifact_store import ArtifactStore as MontagueArtifactStore
from executive.strategic import StrategicPlanner, select_subagent_profile
from executive.strategic.human_summary import render_human_summary
from workshop.toolbox.loader import ToolLoader
from executive.memory import Memory3Manager
from workshop.toolbox.stacks.contracts_core.intent import ArtifactIntentDetector
from workshop.toolbox.stacks.contracts_core.store import ArtifactStore
from workshop.toolbox.stacks.contracts_core.orchestrator import build_artifact_for_intent, validate_and_render
from workshop.toolbox.agent_core.continuity import (
    build_task_state_from_artifact,
    choose_thread_id_for_request,
    derive_thread_id,
    maybe_emit_continuity_artifact,
    normalize_tags,
    should_emit_task_state,
    suggest_tags,
    load_state_ledger,
    render_state_ledger_block,
    save_state_ledger,
    update_state_ledger,
)
from workshop.toolbox.stacks.contracts_core.fact_distiller import FactDistiller
from workshop.toolbox.stacks.contracts_core.policy import apply_research_degrade_notice, should_force_research_websearch
from workshop.toolbox.agent_core.heartbeat import (
    HeartbeatEngine,
    get_active_persona,
    load_assistant_profile,
    load_persona_catalog,
    save_assistant_profile,
)
from executive.promptforge import PromptForge
from runtime.history_compaction import COMPACTION_PREFIX, build_compaction_summary
from runtime.transcript_hygiene import sanitize_history_messages, sanitize_text
from runtime.answer_validator import validate_and_repair_answer
from runtime.performance_controller import PerformanceController
from runtime.plan_executor import (
    advance_plan_state,
    ensure_plan_state,
    load_plan_state,
    render_plan_block,
    save_plan_state,
)
from runtime.security_guard import sanitize_tool_args
from runtime.task_graph import (
    load_task_graph,
    render_task_graph_block,
    save_task_graph,
    update_task_graph,
)
from runtime.tool_orchestrator import (
    ToolCallSpec,
    ToolOrchestrationBudget,
    run_parallel_read_only,
    run_tool_chain,
)
from runtime.tool_loop_detection import (
    ToolLoopConfig,
    detect_tool_loop,
    record_tool_call,
    record_tool_call_outcome,
)
from ontology import SomiOntology
from ops import OpsControlPlane
from learning import SkillSuggestionEngine, TrajectoryStore
from search import SessionSearchService
from state import SessionEventStore
from subagents import SubagentExecutor, SubagentRegistry, SubagentStatusStore
from workshop.toolbox.coding import CodingSessionService
from workshop.toolbox.runtime import InternalToolRuntime
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
        self.ollama_client = create_async_client()
        self.vision_client = create_async_client()
        self._client_loop_id: Optional[int] = None
        self._maintenance_task: Optional[asyncio.Task] = None
        self._mem_write_sem = asyncio.Semaphore(1)
        self._last_due_injected_at: Dict[str, float] = {}
        self._due_inject_cooldown_seconds = 300.0
        self._forced_skill_keys_by_user: Dict[str, List[str]] = {}
        self._pending_tickets_by_user: Dict[str, Any] = {}
        self._pending_ticket_dir = os.path.join("sessions", "pending_tickets")
        os.makedirs(self._pending_ticket_dir, exist_ok=True)
        self._last_request_source = "chat"
        self._memory_queue_dir = os.path.join("sessions", "memory_queue")
        os.makedirs(self._memory_queue_dir, exist_ok=True)
        self.last_attachments_by_user: Dict[str, List[Dict[str, Any]]] = {}
        self._background_tasks: set[asyncio.Task] = set()
        # Load personality config
        try:
            with open(self.personality_config, "r", encoding="utf-8") as f:
                self.characters = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"Failed to load personality config ({e}) â€” using default")
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
        self.assistant_profile = load_assistant_profile()
        catalog = load_persona_catalog()
        active_key, active_persona = get_active_persona(str(self.assistant_profile.get("active_persona_key") or self.default_agent_key), catalog or self.characters)
        self.assistant_profile["active_persona_key"] = active_key
        self.heartbeat_engine = HeartbeatEngine()
        self.agent_key = self._resolve_agent_key(name)
        character = dict(self.characters.get(self.agent_key, self.characters.get(self.default_agent_key, {})))
        if active_persona:
            character.update(active_persona)
        self.name = self.agent_key.replace("Name: ", "")
        self.role = character.get("role", "assistant")
        self.temperature = character.get("temperature", DEFAULT_TEMP)
        self.description = character.get("description", "Generic assistant")
        self.physicality = character.get("physicality", [])
        self.experience = character.get("experience", [])
        self.inhibitions = character.get("inhibitions", [])
        self.hobbies = character.get("hobbies", [])
        self.behaviors = character.get("behaviors", [])
        self.model = GENERAL_MODEL
        self.coding_model = CODING_MODEL
        self.memory_model = MEMORY_MODEL
        self.vision_model = VISION_MODEL
        # History:
        # - self.history: default single-user history (CLI/GUI unchanged)
        # - self.history_by_user: optional per-user history for Telegram/WhatsApp/etc
        self.history: List[Dict[str, str]] = []
        self.history_by_user: Dict[str, List[Dict[str, str]]] = {}
        self.rag = RAGHandler()
        self.websearch = WebSearchHandler() if callable(WebSearchHandler) else None
        self.ops_control = OpsControlPlane()
        self.toolbox_runtime = InternalToolRuntime(ops_control=self.ops_control)
        self.state_store = SessionEventStore()
        self.session_search = SessionSearchService(state_store=self.state_store)
        self.trajectory_store = TrajectoryStore()
        self.skill_suggestion_engine = SkillSuggestionEngine()
        self.coding_sessions = CodingSessionService(coding_model=self.coding_model, agent_profile="coding_worker")
        self.start_here_service = StarterStudioService()
        self.subagent_registry = SubagentRegistry()
        self.subagent_status_store = SubagentStatusStore()
        self.subagent_executor = SubagentExecutor(
            registry=self.subagent_registry,
            runtime=self.toolbox_runtime,
            state_store=self.state_store,
            status_store=self.subagent_status_store,
        )
        self.time_handler = TimeHandler(default_timezone=SYSTEM_TIMEZONE)
        self.wordgame = WordGameHandler(game_file=self.game_file)
        self.tool_context_store = ToolContextStore(ttl_seconds=900)
        self.followup_resolver = FollowUpResolver()
        self.enable_smart_followups = ENABLE_SMART_FOLLOWUPS
        self.promptforge = PromptForge(workspace=".")
        self.artifact_store = ArtifactStore()
        self.artifact_detector = ArtifactIntentDetector(threshold=float(ARTIFACT_INTENT_THRESHOLD))
        self.fact_distiller = FactDistiller()
        self.istari_protocol = IstariProtocol()
        self.montague_context_store = MontagueArtifactStore()
        self.strategic_planner = StrategicPlanner()
        self.use_memory3 = bool(USE_MEMORY3)
        self.memory = Memory3Manager(
            ollama_client=self.ollama_client,
            session_id=self.user_id,
            time_handler=self.time_handler,
            user_id=self.user_id,
            session_search=self.session_search,
        )
        self.ontology = SomiOntology(
            state_store=self.state_store,
            memory_store=getattr(self.memory, "store", None),
        )
        self.turn_counter = 0
        self._perf_samples: list[dict[str, float | str | bool]] = []
        self.performance_controller = PerformanceController(
            profile_name=str(ACTIVE_MODEL_CAPABILITY_PROFILE or "medium"),
            window_size=24,
        )
        self._current_response_timeout_s = 150.0
        self._allow_parallel_tools = True
        self._tool_call_history_by_user: Dict[str, List[Dict[str, Any]]] = {}
        self._state_ledger_cache_by_user: Dict[str, Dict[str, Any]] = {}
        self._model_failures_by_name: Dict[str, int] = {}
        self._model_cooldowns_by_name: Dict[str, float] = {}
        self._capulet_context_cache: dict[str, Any] = {"fetched_at": 0.0, "payload": None}
        self.context_profile = str(CONTEXT_PROFILE or CHAT_CONTEXT_PROFILE or "8k").lower()
        self.context_profile_cfg = dict((CHAT_CONTEXT_PROFILES or {}).get(self.context_profile, {}))
        self._load_mode_files()
    def _refresh_profile_and_persona(self) -> tuple[dict, str, dict]:
        self.assistant_profile = load_assistant_profile()
        catalog = load_persona_catalog() or self.characters
        requested_key = str(self.assistant_profile.get("active_persona_key") or self.default_agent_key)
        active_key, persona = get_active_persona(requested_key, catalog)
        self.assistant_profile["active_persona_key"] = active_key
        if active_key != requested_key:
            try:
                save_assistant_profile(self.assistant_profile)
            except Exception:
                pass
        return self.assistant_profile, active_key, persona
    def _heartbeat_first_interaction_of_day(self, active_user_id: str, profile: dict) -> bool:
        today = datetime.now(timezone.utc).date().isoformat()
        return str(profile.get("last_brief_date") or "") != today
    def _log_route_snapshot(self, *, user_id: str, prompt: str, decision: Any, last_tool_type: str = "") -> None:
        try:
            path = os.path.join("sessions", "logs", "routing_decisions.log")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            row = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "user_id": str(user_id or "default_user"),
                "prompt": str(prompt or "")[:260],
                "route": str(getattr(decision, "route", "")),
                "reason": str(getattr(decision, "reason", "")),
                "intent": str((getattr(decision, "signals", {}) or {}).get("intent", "")),
                "last_tool_type": str(last_tool_type or ""),
            }
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _safe_temperature_value(self, value: Any, fallback: float) -> float:
        try:
            out = float(value)
        except Exception:
            out = float(fallback)
        if out < 0.0:
            return 0.0
        if out > 1.5:
            return 1.5
        return out
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
    def _extract_tradeoff_options(self, user_text: str) -> tuple[str, str]:
        text = str(user_text or "").strip()
        parts = re.split(r"\s+vs\.?\s+", text, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            return parts[0].strip(" ?.!,"), parts[1].strip(" ?.!,")
        parts = re.split(r"\s+or\s+", text, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            return parts[0].strip(" ?.!,"), parts[1].strip(" ?.!,")
        return "Option A", "Option B"
    def _get_latest_montague_context_context_pack(self, *, cache_ttl_seconds: float = 2.0) -> dict[str, Any]:
        now = time.time()
        cached = self._capulet_context_cache.get("payload")
        fetched_at = float(self._capulet_context_cache.get("fetched_at") or 0.0)
        if isinstance(cached, dict) and (now - fetched_at) <= max(0.0, float(cache_ttl_seconds)):
            return cached
        cp = self.montague_context_store.read_latest("context_pack_v1") or {
            "artifact_type": "context_pack_v1",
            "projects": [],
            "confirmed_goals": [],
            "top_impacts": [],
            "patterns": [],
            "calendar_conflicts": [],
            "relevant_artifact_ids": [],
        }
        self._capulet_context_cache = {"fetched_at": now, "payload": cp}
        return cp
    def _ensure_async_clients_for_current_loop(self) -> None:
        """
        Recreate async Ollama clients when called from a different event loop.
        This prevents `RuntimeError: Event loop is closed` when callers use
        repeated `asyncio.run(...)` invocations in tests/harnesses.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop_id = id(loop)
        if self._client_loop_id == loop_id:
            return
        self.ollama_client = create_async_client()
        self.vision_client = create_async_client()
        self._client_loop_id = loop_id
        # Keep memory manager + embedder aligned with the active async client.
        try:
            self.memory.client = self.ollama_client
            if getattr(self.memory, "embedder", None) is not None:
                self.memory.embedder.client = self.ollama_client
        except Exception:
            pass
    def _pending_ticket_path(self, user_id: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9._-]", "_", str(user_id or "default_user"))[:120]
        return os.path.join(self._pending_ticket_dir, f"{safe}.json")
    def _persist_pending_ticket(self, user_id: str, ticket: ExecutionTicket) -> None:
        try:
            path = self._pending_ticket_path(user_id)
            payload = {
                "user_id": str(user_id),
                "ticket": ticket.__dict__,
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception as e:
            logger.debug(f"Pending ticket persist failed: {e}")
    def _load_pending_ticket(self, user_id: str) -> Optional[ExecutionTicket]:
        path = self._pending_ticket_path(user_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.loads(f.read())
            ticket_raw = dict(raw.get("ticket") or {})
            return ExecutionTicket(**ticket_raw)
        except Exception as e:
            logger.debug(f"Pending ticket load failed: {e}")
            return None
    def _clear_pending_ticket(self, user_id: str) -> None:
        path = self._pending_ticket_path(user_id)
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
    def _schedule_background_task(self, coro: Any, *, label: str = "bg_task") -> None:
        try:
            task = asyncio.create_task(coro)
            self._background_tasks.add(task)
            def _done(t: asyncio.Task) -> None:
                self._background_tasks.discard(t)
                try:
                    t.result()
                except Exception as e:
                    logger.debug(f"Background task '{label}' failed: {type(e).__name__}: {e}")
            task.add_done_callback(_done)
        except Exception as e:
            logger.debug(f"Background task scheduling failed ({label}): {e}")
    def _memory_queue_path(self, user_id: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9._-]", "_", str(user_id or "default_user"))[:120]
        return os.path.join(self._memory_queue_dir, f"{safe}.jsonl")
    def _enqueue_memory_write(self, *, prompt: str, content: str, active_user_id: str, should_search: bool) -> None:
        path = self._memory_queue_path(active_user_id)
        row = {
            "prompt": str(prompt or "")[:4000],
            "content": str(content or "")[:8000],
            "active_user_id": str(active_user_id),
            "should_search": bool(should_search),
            "enqueued_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    def _read_memory_queue(self, active_user_id: str) -> List[Dict[str, Any]]:
        path = self._memory_queue_path(active_user_id)
        if not os.path.exists(path):
            return []
        out: List[Dict[str, Any]] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                if not isinstance(item, dict):
                    continue
                out.append(item)
        return out
    def _write_memory_queue(self, active_user_id: str, items: List[Dict[str, Any]]) -> None:
        path = self._memory_queue_path(active_user_id)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    async def _memory_ingest_nonblocking(self, *, active_user_id: str, limit: int = 4) -> None:
        try:
            async with self._mem_write_sem:
                queue = self._read_memory_queue(active_user_id)
                if not queue:
                    return
                keep: List[Dict[str, Any]] = []
                processed = 0
                for idx, item in enumerate(queue):
                    if processed >= max(1, int(limit)):
                        keep.append(item)
                        continue
                    try:
                        if bool(item.get("should_search", False)):
                            mem_write = await self.memory.ingest_turn(
                                str(item.get("prompt", "")),
                                assistant_text="",
                                tool_summaries=["websearch"],
                                session_id=active_user_id,
                            )
                        else:
                            mem_write = await self.memory.ingest_turn(
                                str(item.get("prompt", "")),
                                assistant_text=str(item.get("content", "")),
                                tool_summaries=None,
                                session_id=active_user_id,
                            )
                        notices = list((mem_write or {}).get("conflict_notices", []) or [])
                        if notices:
                            logger.info(f"[{active_user_id}] Memory update notice: {notices[0]}")
                        processed += 1
                    except Exception:
                        keep.append(item)
                        keep.extend(queue[idx + 1 :])
                        break
                self._write_memory_queue(active_user_id, keep)
        except Exception:
            pass
    def _extract_user_correction(self, prompt: str) -> Tuple[str, str]:
        p = (prompt or "").strip()
        if len(p) < 8:
            return "", ""
        # Keep this conservative to avoid false-positive reroutes on generic "no" replies.
        m = re.search(
            r"\b(?:not quite|that'?s not what i (?:asked|meant)|i (?:wanted|meant)|instead i (?:wanted|meant))\b[\s,:-]*(.*)$",
            p,
            flags=re.IGNORECASE,
        )
        if not m:
            return "", ""
        tail = (m.group(1) or "").strip(" .")
        if not tail:
            return "User signaled previous answer mismatch; prioritize clarification and corrected intent.", ""
        tail_norm = tail.lower()
        return f"User correction received: {tail_norm}", tail_norm
    def _is_explicit_coding_intent(self, prompt: str) -> bool:
        p = (prompt or "").strip().lower()
        if not p:
            return False
        strong_prefixes = (
            "code ", "write code", "implement ", "refactor ", "debug ",
            "fix bug", "add test", "create skill", "update skill",
            "patch ", "generate code", "review this code",
        )
        if p.startswith(strong_prefixes):
            return True
        explicit_action_markers = (
            "fix", "debug", "refactor", "implement", "write", "generate", "create", "update",
            "optimize", "add", "remove", "patch", "review",
        )
        technical_targets = (
            "code", "function", "class", "method", "stack trace", "traceback", "exception",
            "unit test", "skill.md", "pull request", "compile", "lint", "pytest", "api endpoint",
            "sql query", "script", "module", "file", "repository", "repo",
        )
        has_action = any(m in p for m in explicit_action_markers)
        has_target = any(m in p for m in technical_targets)
        # explicit code syntax cues
        has_code_cue = bool(
            re.search(r"```|\bdef\s+\w+\s*\(|\bclass\s+\w+\s*[:(]|\bimport\s+\w+", p)
            or re.search(r"\bselect\b.+\bfrom\b", p)
        )
        return (has_action and has_target) or has_code_cue
    def _is_plan_revision_followup(self, prompt: str) -> bool:
        p = (prompt or "").strip().lower()
        if len(p) < 10:
            return False
        revision_markers = (
            "update", "revise", "adjust", "change", "make it fit", "only have", "fit into",
            "rework", "modify", "shorten", "tighten",
        )
        plan_markers = ("plan", "that", "it", "schedule", "steps")
        return any(m in p for m in revision_markers) and any(m in p for m in plan_markers)
    def _extract_plan_revision_constraints(self, prompt: str) -> List[str]:
        p = (prompt or "").strip()
        if not p:
            return []
        out: List[str] = []
        lowered = p.lower()
        time_match = re.search(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|minutes?|mins?)\s*/?\s*(week|wk|day|month)", lowered)
        if time_match:
            qty, unit, period = time_match.group(1), time_match.group(2), time_match.group(3)
            out.append(f"Time budget: {qty} {unit} per {period}.")
        if "only have" in lowered:
            out.append("User has limited availability; prioritize essential steps.")
        cleaned = p.strip().rstrip(".?!")
        if cleaned:
            out.append(f"User adjustment request: {cleaned}")
        return out[:3]
    def _plan_revision_confidence(self, prompt: str) -> float:
        p = (prompt or "").strip().lower()
        if not p:
            return 0.0
        strong_markers = ("update", "revise", "adjust", "change", "rework", "modify", "make it fit")
        weak_markers = ("that", "it", "schedule", "steps", "hours/week", "hours per week", "only have")
        score = 0.0
        if any(m in p for m in strong_markers):
            score += 0.55
        if any(m in p for m in weak_markers):
            score += 0.25
        if "plan" in p:
            score += 0.2
        return min(score, 0.99)
    def _is_recent_artifact(self, artifact: Optional[Dict[str, Any]], *, max_age_minutes: int) -> bool:
        if not artifact:
            return False
        ts = str(artifact.get("timestamp") or artifact.get("created_at") or "").strip()
        if not ts:
            return False
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age_s = (datetime.now(timezone.utc) - dt).total_seconds()
            return age_s <= float(max_age_minutes) * 60.0
        except Exception:
            return False
    def _get_plan_for_revision(self, user_id: str, prompt: str) -> Optional[Dict[str, Any]]:
        conf = self._plan_revision_confidence(prompt)
        if conf < 0.75:
            return None
        candidate = self.artifact_store.get_last(user_id, "plan")
        max_age = int(ARTIFACT_PLAN_REVISION_MAX_AGE_MINUTES or 180)
        if not self._is_recent_artifact(candidate, max_age_minutes=max_age):
            return None
        return candidate
    def _should_force_research_websearch(self, route: str, artifact_intent: Optional[str]) -> bool:
        return bool(ENABLE_NL_ARTIFACTS and artifact_intent == "research_brief" and str(route or "") != "websearch")
    def _apply_research_degrade_notice(self, content: str, *, reason: str = "") -> str:
        if not bool(ARTIFACT_DEGRADE_NOTICE):
            return content
        reason_l = str(reason or "").lower()
        if "insufficient_sources" not in reason_l and "web search unavailable" not in reason_l:
            return content
        return (content or "").rstrip() + "\n\nI couldnâ€™t fetch enough sources right now, so I answered without citations."
    def _is_analysis_intent(self, prompt: str) -> bool:
        p = (prompt or "").strip().lower()
        if not p:
            return False
        markers = (
            "tradeoff", "trade-off", "compare", "comparison", "evaluate",
            "strategy", "architect", "architecture", "reasoning", "deep dive",
            "step by step", "step-by-step", "pros and cons", "plan",
        )
        if any(m in p for m in markers):
            return True
        return bool(re.search(r"\b(why|how does|explain in detail|analyze|analyse)\b", p))
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
    # -------- Local intent routing (memory/goals/reminders) --------
    def clear_short_term_history(self) -> None:
        # Preserve existing CLI/GUI semantics: clears only default history
        self.history = []
    def __del__(self):
        try:
            if self.current_mode == "game":
                self.wordgame.clear_game_state()
        except Exception:
            pass
import types as _agent_types
from agent_methods.history_methods import (
    _should_use_per_user_history,
    _get_history_list,
    _history_limits,
    _estimate_text_tokens_rough,
    _history_token_estimate,
    _resolve_history_compaction_thresholds,
    _state_ledger_for_user,
    _state_ledger_block,
    _history_for_prompt,
    _compact_history_if_needed,
    _push_history_for,
    _tool_loop_config,
    _tool_call_history,
    _run_tool_with_loop_guard,
)
from agent_methods.coding_methods import _handle_coding_command_or_intent
from agent_methods.starter_methods import _handle_starter_command_or_intent
from agent_methods.model_methods import (
    _select_generation_mode,
    _select_response_model,
    _model_role_for_generation_mode,
    _model_retryable_error_markers,
    _is_retryable_model_error,
    _record_model_success,
    _record_model_failure,
    _model_candidate_chain,
    _chat_with_model_failover,
)
from agent_methods.ontology_methods import _refresh_operational_graph
from agent_methods.response_methods import (
    generate_response,
    _set_last_attachments,
    get_last_attachments,
    generate_response_with_attachments,
    analyze_image,
    _start_turn_trace,
    _record_state_event,
    _finish_turn_trace,
)
from agent_methods.subagent_methods import (
    list_subagent_profiles,
    get_subagent_status,
    delegate_subagent,
    _format_subagent_snapshot,
    _handle_subagent_command,
)
from agent_methods.search_memory_methods import (
    _format_due_ts_local,
    _is_personal_memory_query,
    _should_inject_due_context,
    _mark_due_context_injected,
    _route_local_memory_intents,
    _should_websearch,
    _build_rag_block,
    _maintenance_tick,
    _persist_memory_serial,
    _memory_scope_for_prompt,
    _response_timeout_seconds,
    _vision_timeout_seconds,
    _token_budget,
    _extract_urls_from_results,
    _extract_urls_from_citation_map,
    _enforce_web_evidence_output,
    _is_volatile_results,
    _safe_build_image_spec,
    _is_chart_keyword_prompt,
    _numeric_guard,
    _is_finance_intent_hint,
    _looks_like_historical_price_followup,
    _looks_like_finance_followup,
    _render_direct_finance_answer,
    _render_direct_volatile_answer,
)
from agent_methods.text_methods import (
    _clean_think_tags,
    _strip_unwanted_json,
    _looks_like_tool_dump,
    _strip_search_meta_leakage,
    _strip_internal_prompt_leakage,
    _naturalize_search_output,
)

def _bind_agent_method(func):
    bound = _agent_types.FunctionType(
        func.__code__,
        globals(),
        name=func.__name__,
        argdefs=func.__defaults__,
        closure=func.__closure__,
    )
    bound.__kwdefaults__ = getattr(func, "__kwdefaults__", None)
    bound.__annotations__ = dict(getattr(func, "__annotations__", {}))
    bound.__doc__ = func.__doc__
    bound.__module__ = __name__
    return bound

_EXTRACTED_AGENT_METHODS = [
    _select_generation_mode,
    _select_response_model,
    _model_role_for_generation_mode,
    _model_retryable_error_markers,
    _is_retryable_model_error,
    _record_model_success,
    _record_model_failure,
    _model_candidate_chain,
    _chat_with_model_failover,
    _clean_think_tags,
    _strip_unwanted_json,
    _looks_like_tool_dump,
    _strip_search_meta_leakage,
    _strip_internal_prompt_leakage,
    _naturalize_search_output,
    _should_use_per_user_history,
    _get_history_list,
    _history_limits,
    _estimate_text_tokens_rough,
    _history_token_estimate,
    _resolve_history_compaction_thresholds,
    _state_ledger_for_user,
    _state_ledger_block,
    _history_for_prompt,
    _compact_history_if_needed,
    _push_history_for,
    _tool_loop_config,
    _tool_call_history,
    _run_tool_with_loop_guard,
    _handle_coding_command_or_intent,
    _handle_starter_command_or_intent,
    _format_due_ts_local,
    _is_personal_memory_query,
    _should_inject_due_context,
    _mark_due_context_injected,
    _route_local_memory_intents,
    _should_websearch,
    _build_rag_block,
    _maintenance_tick,
    _persist_memory_serial,
    _memory_scope_for_prompt,
    _response_timeout_seconds,
    _vision_timeout_seconds,
    _token_budget,
    _extract_urls_from_results,
    _extract_urls_from_citation_map,
    _enforce_web_evidence_output,
    _is_volatile_results,
    _safe_build_image_spec,
    _is_chart_keyword_prompt,
    _numeric_guard,
    _is_finance_intent_hint,
    _looks_like_historical_price_followup,
    _looks_like_finance_followup,
    _render_direct_finance_answer,
    _render_direct_volatile_answer,
    _refresh_operational_graph,
    generate_response,
    _set_last_attachments,
    get_last_attachments,
    generate_response_with_attachments,
    analyze_image,
    _start_turn_trace,
    _record_state_event,
    _finish_turn_trace,
    list_subagent_profiles,
    get_subagent_status,
    delegate_subagent,
    _handle_subagent_command,
]

for _agent_method in _EXTRACTED_AGENT_METHODS:
    _bound_method = _bind_agent_method(_agent_method)
    _bound_method.__qualname__ = f"Agent.{_agent_method.__name__}"
    setattr(Agent, _agent_method.__name__, _bound_method)

del _agent_method, _bound_method, _EXTRACTED_AGENT_METHODS, _bind_agent_method, _agent_types
