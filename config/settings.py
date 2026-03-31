# config/settings.py
import os

from config.heartbeatsettings import *
from config.memorysettings import *
from config.modelsettings import MODEL_CAPABILITY_PROFILE, MODEL_CAPABILITY_PROFILES, get_active_model_profile_name, get_model_profile

# Model role map
ACTIVE_MODEL_CAPABILITY_PROFILE = get_active_model_profile_name()
_MODEL_PROFILE = get_model_profile()
GENERAL_MODEL = str(_MODEL_PROFILE.get("general_model") or "qwen3:8b")
INSTRUCT_MODEL = str(_MODEL_PROFILE.get("instruct_model") or "stable-code:3b")
CODING_MODEL = str(_MODEL_PROFILE.get("coding_model") or "stable-code:3b")
WEBSEARCH_MODEL = INSTRUCT_MODEL
CODING_AGENT_PROFILE = str(_MODEL_PROFILE.get("coding_agent_profile") or "coding_worker")
CODING_WORKSPACE_ROOT = "workshop/tools/workspace/coding_mode"
CODING_SESSIONS_ROOT = "sessions/coding"
CODING_SKILL_DRAFTS_ROOT = "skills_local"
CODING_DEFAULT_LANGUAGE = "python"
CODING_SUPPORTED_PROFILES = ("python", "javascript", "typescript", "web", "game")
CODING_SANDBOX_DEFAULT_BACKEND = "managed_venv"
CODING_SANDBOX_SNAPSHOT_ROOT = "sessions/coding/sandbox_snapshots"
CODING_SANDBOX_ROLLBACKS_ROOT = "sessions/coding/rollbacks"
CODING_SANDBOX_MAX_FILES = 2500
CODING_SANDBOX_MAX_TOTAL_BYTES = 24 * 1024 * 1024
CODING_SANDBOX_PREVIEW_CHAR_THRESHOLD = 2000
CODING_SANDBOX_MAX_SNAPSHOTS_PER_WORKSPACE = 8

# Runtime model behavior policies
DEFAULT_THINK_FALSE = True
MODELS_WITHOUT_THINK = [
    "stable-code:3b",
    "glm-ocr:latest",
]
MODEL_KEEP_ALIVE_SECONDS = {
    "default": 180,
    "general": 240,
    "instruct": 180,
    "websearch": 180,
    "vision": 120,
    "memory": 120,
    "scraper": 120,
}
MODEL_FAILOVER_ENABLED = True
MODEL_FAILOVER_MAX_ATTEMPTS = 3
MODEL_FAILOVER_COOLDOWN_SECONDS = 300
MODEL_FAILOVER_FAILS_BEFORE_COOLDOWN = 2
MODEL_FAILOVER_RETRYABLE_ERRORS = (
    "timeout",
    "timed out",
    "connection",
    "refused",
    "temporarily unavailable",
    "unavailable",
    "not found",
    "no such model",
    "model not found",
    "cuda",
    "out of memory",
)

# Domain-specific SearXNG fetch profiles
SEARXNG_DOMAIN_PROFILES = {
    "general": {
        "profile": "general",
        "category": "general",
        "max_results": 10,
        "max_pages": 2,
        "source_name": "searxng_general",
    },
    "science": {
        "profile": "science",
        "category": "science",
        "max_results": 10,
        "max_pages": 2,
        "source_name": "searxng_research",
    },
    "biomed": {
        "profile": "science_biomed",
        "category": "science",
        "max_results": 10,
        "max_pages": 2,
        "source_name": "searxng_biomed",
    },
    "engineering": {
        "profile": "science_engineering",
        "category": "science",
        "max_results": 10,
        "max_pages": 2,
        "source_name": "searxng_engineering",
    },
    "nutrition": {
        "profile": "science_nutrition",
        "category": "science",
        "max_results": 10,
        "max_pages": 2,
        "source_name": "searxng_nutrition",
    },
    "religion": {
        "profile": "science_religion",
        "category": "general",
        "max_results": 10,
        "max_pages": 2,
        "source_name": "searxng_religion",
    },
    "entertainment": {
        "profile": "science_entertainment",
        "category": "general",
        "max_results": 10,
        "max_pages": 2,
        "source_name": "searxng_entertainment",
    },
    "business_administrator": {
        "profile": "science_business_administrator",
        "category": "general",
        "max_results": 10,
        "max_pages": 2,
        "source_name": "searxng_business_administrator",
    },
    "journalism_communication": {
        "profile": "science_journalism_communication",
        "category": "news",
        "max_results": 10,
        "max_pages": 2,
        "source_name": "searxng_journalism_communication",
    },
    "news": {
        "profile": "news",
        "category": "news",
        "max_results": 15,
        "max_pages": 2,
        "source_name": "searxng_news",
    },
}

# Backward-compatible aliases used across older modules
DEFAULT_MODEL = GENERAL_MODEL
VISION_MODEL = str(_MODEL_PROFILE.get("vision_model") or "qwen3.5:9b")
DEFAULT_TEMP = float(_MODEL_PROFILE.get("default_temp") or 0.4)
SEARXNG_BASE_URL = "http://localhost:8080"
DEFAULT_LOCATION = "Port of Spain, Trinidad and Tobago"
DEFAULT_NEWS_REGION = "Trinidad and Tobago"

# Playwright scraping fallback for thin/empty search results
SCRAPER_FALLBACK_ENABLED = True
SCRAPER_FALLBACK_MIN_RESULTS = 2
SCRAPER_USE_PLAYWRIGHT = True
SCRAPER_MODEL = str(_MODEL_PROFILE.get("scraper_model") or "qwen3.5:0.8b")
SCRAPER_LLM_RERANK = True
SCRAPER_MAX_RESULT_LINKS = 8
SCRAPER_MAX_PAGE_OPENS = 3
SCRAPER_PAGE_TIMEOUT_MS = 12000
SCRAPER_TEMP_DIR = "sessions/scrape_tmp"

# Optional Dockerized Scrapling service (host:container = 9959:8000)
SCRAPLING_SERVICE_ENABLED = False
SCRAPLING_SERVICE_BASE_URL = "http://localhost:9959"
SCRAPLING_SERVICE_PATH = "/fetch"
SCRAPLING_SERVICE_TIMEOUT_SECONDS = 4.0

# Research route: optional crawlies retrieval engine
RESEARCH_CRAWLIES_ENABLED = True
RESEARCH_CRAWLIES_TIMEOUT_SECONDS = 20.0
RESEARCH_CRAWLIES_MAX_PAGES = 2
RESEARCH_CRAWLIES_MAX_CANDIDATES = 12
RESEARCH_CRAWLIES_MAX_OPEN_LINKS = 3
RESEARCH_CRAWLIES_MIN_QUALITY_STOP = 35.0
RESEARCH_CRAWLIES_USE_SCRAPLING = True
RESEARCH_CRAWLIES_USE_PLAYWRIGHT = True
RESEARCH_CRAWLIES_USE_LLM_RERANK = False
RESEARCH_CRAWLIES_SAVE_ARTIFACTS = True

# Finance historical route: crawlies fallback/augmentation
FINANCE_HISTORICAL_CRAWLIES_ENABLED = True
FINANCE_HISTORICAL_CRAWLIES_TIMEOUT_SECONDS = 14.0
FINANCE_HISTORICAL_CRAWLIES_MAX_PAGES = 2
FINANCE_HISTORICAL_CRAWLIES_MAX_CANDIDATES = 12
FINANCE_HISTORICAL_CRAWLIES_MAX_OPEN_LINKS = 3
FINANCE_HISTORICAL_CRAWLIES_MIN_QUALITY_STOP = 35.0
FINANCE_HISTORICAL_CRAWLIES_USE_SCRAPLING = True
FINANCE_HISTORICAL_CRAWLIES_USE_PLAYWRIGHT = True
FINANCE_HISTORICAL_CRAWLIES_USE_LLM_RERANK = False
FINANCE_HISTORICAL_CRAWLIES_SAVE_ARTIFACTS = True
FINANCE_HISTORICAL_CRAWLIES_CATEGORY = "general"
RAG_WEBSITES = [
    "placeholder"
]

# System timezone
SYSTEM_TIMEZONE = "America/New_York"

# Finance vendor backend toggle: "yfinance" | "yahooquery"
FINANCE_YAHOO_BACKEND = "yfinance"

# Telegram permissions you can message @userinfobot on telegram for your user ID
TELEGRAM_BOT_OWNER_IDS = {
    "placeholder",
}
TELEGRAM_BOT_TOKEN = "placeholder"
TELEGRAM_BOT_USERNAME = "placeholder"
TELEGRAM_AGENT_ALIASES = [
    "Somi",
    "bot",
    "Agent",
    "retard",
    "degen",
]

#  OCR & REGISTRY TRIGGERS
OCR_TRIGGERS = [
    "ocr", "scan", "extract", "table", "read", "form", "document", "scan this", "read this"
]

REGISTRY_TRIGGERS = [
    "registry", "add to registry", "save patient", "add patient", "database", "db",
    "add to database", "save to registry", "save to db", "record", "add record",
    "patient", "epilepsy", "brain", "form", "save form"
]

# Session persistence, compression, and efficiency settings
SESSION_DIR = "sessions/"
SESSION_AUTO_SAVE_EVERY_N_TURNS = 1
MAX_CONTEXT_TOKENS = int(_MODEL_PROFILE.get("max_context_tokens") or 8192)


SESSION_MEDIA_DIR = "sessions/media"
COMFYUI_PORT = 8188

# Chat Flow / Routing architecture defaults
CONTEXT_PROFILE = str(_MODEL_PROFILE.get("chat_context_profile") or "8k")
HISTORY_MAX_MESSAGES = int(_MODEL_PROFILE.get("history_max_messages") or 10)
SUMMARY_ENABLED = True
SUMMARY_UPDATE_EVERY_N_TURNS = 8
SUMMARY_MAX_TOKENS = 220
SUMMARY_LAST_TURNS_TO_SUMMARIZE = 12
SUMMARY_USE_LLM = False
SUMMARY_MODEL = MEMORY_MODEL
ROUTING_DEBUG = True
ENABLE_SMART_FOLLOWUPS = True   # Set False to completely disable the new resolver logic

# Deterministic context budgets (approx-token budgets)
BUDGET_MEMORY_TOKENS = 420
BUDGET_SEARCH_TOKENS = 550
BUDGET_HISTORY_TOKENS = 900
BUDGET_OUTPUT_RESERVE_TOKENS = 320
CHAT_CONTEXT_PROFILE = str(_MODEL_PROFILE.get("chat_context_profile") or "8k")
CHAT_CONTEXT_PROFILES = {
    "4k": {"max_context_tokens": 4096, "history_turns": 4, "memory_chars": 900, "summary_chars": 350},
    "8k": {"max_context_tokens": 8192, "history_turns": 8, "memory_chars": 1600, "summary_chars": 500},
    "16k": {"max_context_tokens": 16384, "history_turns": 12, "memory_chars": 2600, "summary_chars": 800},
    "32k": {"max_context_tokens": 32768, "history_turns": 18, "memory_chars": 4200, "summary_chars": 1200},
}

DEFAULT_MAX_NEW_TOKENS = int(_MODEL_PROFILE.get("default_max_new_tokens") or 512)
RESPONSE_TOKEN_SOFT_LIMIT = int(_MODEL_PROFILE.get("response_token_soft_limit") or 300)

HISTORY_KEEP_RAW_LAST_N = 6
HISTORY_COMPRESS_AFTER_N = 12
COMPRESSION_AGGRESSIVENESS = 0.7
# Transcript hygiene + compaction controls
TRANSCRIPT_HYGIENE_ENABLED = True
TRANSCRIPT_MAX_MESSAGES = 160
TRANSCRIPT_MAX_MESSAGE_CHARS = 6000
HISTORY_AUTO_COMPACTION_ENABLED = True
HISTORY_AUTO_COMPACT_TRIGGER_MESSAGES = 28
HISTORY_AUTO_COMPACT_KEEP_RECENT_MESSAGES = 12
HISTORY_COMPACTION_MAX_ITEMS = 8
HISTORY_COMPACTION_SUMMARY_MAX_CHARS = 1200
HISTORY_AUTO_COMPACT_TRIGGER_TOKENS = 0   # 0 => derive from MAX_CONTEXT_TOKENS (~55%)
HISTORY_AUTO_COMPACT_TARGET_TOKENS = 0    # 0 => derive from MAX_CONTEXT_TOKENS (~35%)
HISTORY_AUTO_COMPACT_MIN_KEEP_MESSAGES = 6

# For proactive reminders (placeholders for reminders.py)
PROACTIVE_REMINDER_INTERVAL_MIN = 60


# Proactivity controls
PROACTIVITY_ENABLED = True
PROACTIVITY_ALLOW_AUTOMATIC_MESSAGES = True
PROACTIVITY_MAX_MESSAGES_PER_DAY = 3
PROACTIVITY_MAX_NOTIFICATIONS_PER_DAY = 1
PROACTIVITY_DAILY_INTERRUPT_BUDGET = 100

# Hardware scaling flags
ALLOW_16K_CONTEXT = bool(int(MAX_CONTEXT_TOKENS) >= 16384)
AUTO_COMPRESS_ON_LOW_MEMORY = True
UNRESTRICTED_MODE = False

PROMPT_ARCH_VERSION = "enterprise-v1.1"
PROMPT_ENTERPRISE_ENABLED = True
PROMPT_BLOCK_BUDGETS_ENABLED = True
PROMPT_FIREWALL_ENABLED = True
PROMPT_MODE_GATE_ENABLED = True
PROMPT_ACTION_PROTOCOL_ENABLED = False
PROMPT_SNAPSHOT_LOG_ENABLED = True
PROMPT_FORCE_LEGACY = False

# Budgets (deterministic heuristic)
PROMPT_BUDGET_KERNEL = 700
PROMPT_BUDGET_POLICIES = 320
PROMPT_BUDGET_PERSONA = 700
PROMPT_BUDGET_TOOLS = 450
PROMPT_BUDGET_TIME = 80
PROMPT_BUDGET_ROUTING = 140
PROMPT_BUDGET_MEMORY_PROFILE = 500
PROMPT_BUDGET_MEMORY_WORKING = 700
PROMPT_BUDGET_EVIDENCE = int(_MODEL_PROFILE.get("prompt_budget_evidence") or 1200)
PROMPT_BUDGET_HISTORY = int(_MODEL_PROFILE.get("prompt_budget_history") or 2200)
PROMPT_BUDGET_USER_RESERVE = int(_MODEL_PROFILE.get("prompt_budget_user_reserve") or 450)

# OCR triggers
GENERAL_OCR_TRIGGERS = ["ocr", "extract text", "scan", "read this", "transcribe", "digitize"]
STRUCTURED_OCR_TRIGGERS = []
IMAGE_ANALYSIS_TRIGGERS = [
    "analyze this",
    "analyse this",
    "analyze image",
    "analyse image",
    "describe this image",
    "describe this",
    "what is in this image",
    "what's in this image",
    "what do you see",
    "caption this",
]
OCR_AUTO_CLEAR_IMAGE = True
VISION_ANALYSIS_MODEL = VISION_MODEL
VISION_ANALYSIS_FALLBACK_MODELS = []
VISION_ANALYSIS_SECOND_PROMPT = True

# OCR pipeline options
OCR_CACHE_ENABLED = True
OCR_CACHE_TTL_DAYS = 30
OCR_CACHE_MAX_ITEMS = 2000
OCR_SECOND_PASS = True
OCR_MAX_PASSES = 2
OCR_TEMPERATURE = 0.0
OCR_TIMEOUT_SEC = 120
OCR_NUM_PREDICT = 1024
OCR_MAX_CONCURRENCY = 2
OCR_PREPROCESS_POLICY = "auto"
OCR_MIN_COVERAGE = 0.70
OCR_MAX_UNK_RATIO = 0.05
OCR_FAST_MODEL = None


# Speech/TTS runtime defaults
SPEECH_SAMPLE_RATE = 16000
SPEECH_FRAME_MS = 20
SPEECH_STT_PROVIDER = "whisper_local"
SPEECH_STT_MODEL = "tiny.en"
SPEECH_TTS_PROVIDER = "pyttsx3"
SPEECH_TTS_VOICE_HINT = ""
SPEECH_TTS_RATE = 190
SPEECH_TTS_VOLUME = 1.0
SPEECH_TTS_ALLOW_NETWORK_FALLBACK = False
SPEECH_POCKET_SERVER_URL = "http://127.0.0.1:8001/v1/audio/speech"
TTS_ENGINE = SPEECH_TTS_PROVIDER
PIPER_MODEL_PATH = "models/voices/en_US-lessac-medium.onnx"
PIPER_CONFIG_PATH = "models/voices/en_US-lessac-medium.onnx.json"
TTS_STREAM_CHUNK_MS = 30
AUDIO_OUTPUT_BLOCKSIZE = 1024
BARGE_IN_RMS_THRESHOLD = 0.03
BARGE_IN_FRAMES = 3
VAD_RMS_THRESHOLD = 0.008
VAD_SPEECH_HANGOVER_MS = 400
VAD_MIN_UTTERANCE_MS = 180


# Artifact orchestration (Phase 1)
ENABLE_NL_ARTIFACTS = True
ARTIFACT_INTENT_THRESHOLD = 0.75
MIN_SOURCES_FOR_RESEARCH_BRIEF = 3
DOC_FACTS_REQUIRE_PAGE_REFS = True
ONE_ARTIFACT_PER_TURN = True

ARTIFACT_DEGRADE_NOTICE = False
ARTIFACT_PLAN_REVISION_MAX_AGE_MINUTES = 180

# Phase 7 Life Modeling Layer
MONTAGUE_ENABLED = True
MONTAGUE_MAX_ACTIVE_PROJECTS = 20
MONTAGUE_FAST_WINDOW_DAYS = 30
MONTAGUE_PATTERN_WINDOWS = [7, 30, 90]
MONTAGUE_HEARTBEAT_TOP_IMPACTS = 3
MONTAGUE_HEARTBEAT_TOP_PATTERNS = 1
MONTAGUE_HEARTBEAT_TOP_CAL_CONFLICTS = 1
MONTAGUE_CALENDAR_HORIZON_DAYS = 7
MONTAGUE_INPUT_COMPAT_MODE = "lenient"
MONTAGUE_ENRICHMENT_MODE = "lite"  # off|lite|full
MONTAGUE_CLUSTER_ASSIGN_THRESHOLD = 0.42
MONTAGUE_CLUSTER_SWITCH_MARGIN = 0.12
MONTAGUE_CLUSTER_SWITCH_COOLDOWN_HOURS = 72
MONTAGUE_MIN_ITEMS_PER_PROJECT = 2
MONTAGUE_MAX_EVIDENCE_PER_LINK = 5
MONTAGUE_CLUSTER_WEIGHTS = {"tag": 0.55, "co": 0.30, "recency": 0.15}
MONTAGUE_RECENCY_DECAY_DAYS = 21
MONTAGUE_CALENDAR_PROVIDER = "null"  # null|json
MONTAGUE_CALENDAR_JSON_PATH = "sessions/calendar/events.json"
MONTAGUE_CALENDAR_CACHE_PATH = "executive/index/calendar_cache.json"
MONTAGUE_ENRICHMENT_VALIDATE_FACT_LOCK = True
MONTAGUE_MAX_ROWS_PER_FILE = 50
MONTAGUE_GOOGLE_CALENDAR_ACCESS_TOKEN = ""
MONTAGUE_GOOGLE_CALENDAR_ID = "primary"
MONTAGUE_MSGRAPH_ACCESS_TOKEN = ""
MONTAGUE_GOAL_LINK_QUEUE_PATH = "executive/index/goal_link_queue.json"

# Artifact store sharding (optional, for high-volume sessions)
ARTIFACT_STORE_SHARD_BY_DATE = False
ARTIFACT_STORE_SHARD_DIRNAME = "shards"
ARTIFACT_STORE_MIRROR_PRIMARY_WHEN_SHARDED = False
MONTAGUE_BOOTSTRAP_RELAXATION_ENABLED = True
MONTAGUE_BOOTSTRAP_RELAXATION_ITEM_THRESHOLD = 6
MONTAGUE_BOOTSTRAP_RELAXED_MIN_ITEMS_PER_PROJECT = 1
MONTAGUE_JSONL_TAIL_READ_BYTES = 262144
MONTAGUE_TELEMETRY_PATH = "executive/index/montague_context_telemetry.json"

# Strategic cognition UX/safety
STRATEGIC_EXECUTION_BYPASS_PHRASES = ["do it", "apply", "run", "execute", "proceed now"]
STRATEGIC_HUMAN_SUMMARY_ENABLED = False

# Tavily research enrichment (additive alongside SearXNG)
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
TAVILY_RESEARCH_ENABLED = os.environ.get("TAVILY_RESEARCH_ENABLED", "").lower() in ("1", "true", "yes")

# Researcher Layer rollout flags (safe defaults)
RESEARCHER_LAYER_ENABLED = False
RESEARCHER_BUNDLE_SHADOW_MODE = True
AGENTPEDIA_PROMOTE_FROM_BUNDLE = False
RESEARCH_COMPOSER_ENABLED = True
RESEARCH_COMPOSER_DEEPREAD = True






# Tool loop detection guardrails
TOOL_LOOP_DETECTION_ENABLED = True
TOOL_LOOP_HISTORY_SIZE = 30
TOOL_LOOP_WARNING_THRESHOLD = 10
TOOL_LOOP_CRITICAL_THRESHOLD = 20
TOOL_LOOP_GLOBAL_CIRCUIT_BREAKER_THRESHOLD = 30
TOOL_LOOP_DETECT_GENERIC_REPEAT = True
TOOL_LOOP_DETECT_NO_PROGRESS = True
TOOL_LOOP_DETECT_PING_PONG = True

# Internal tool runtime guarantees
TOOL_RUNTIME_DEFAULT_TIMEOUT_SECONDS = 18
TOOL_RUNTIME_READ_ONLY_MAX_ATTEMPTS = 2
TOOL_RUNTIME_MUTATING_MAX_ATTEMPTS = 1
TOOL_RUNTIME_RETRY_BACKOFF_SECONDS = 0.25
TOOL_RUNTIME_IDEMPOTENCY_TTL_SECONDS = 120
TOOL_RUNTIME_RETRYABLE_ERRORS = (
    "timeout",
    "timed out",
    "temporarily unavailable",
    "connection reset",
    "connection aborted",
    "connection refused",
    "rate limit",
)

# Audit hardening (optional HMAC signing)
AUDIT_HMAC_SECRET = ""







