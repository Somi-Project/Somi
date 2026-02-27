# config/settings.py
from config.heartbeatsettings import *
from config.memorysettings import *

# Model role map
GENERAL_MODEL = "qwen3:8b"
INSTRUCT_MODEL = "stable-code:3b"
CODING_MODEL = "stable-code:3b"
WEBSEARCH_MODEL = INSTRUCT_MODEL

# Backward-compatible aliases used across older modules
DEFAULT_MODEL = GENERAL_MODEL
VISION_MODEL = "glm-ocr:latest"
DEFAULT_TEMP = 0.4
SEARXNG_BASE_URL = "http://localhost:8080"
DEFAULT_LOCATION = "Port of Spain, Trinidad and Tobago"
DEFAULT_NEWS_REGION = "Trinidad and Tobago"

RAG_WEBSITES = [
    "placeholder"
]

# System timezone
SYSTEM_TIMEZONE = "America/New_York"

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

# New OpenClaw-inspired settings for persistence, compression, and efficiency
SESSION_DIR = "sessions/"
SESSION_AUTO_SAVE_EVERY_N_TURNS = 1
MAX_CONTEXT_TOKENS = 8192


SESSION_MEDIA_DIR = "sessions/media"
COMFYUI_PORT = 8188

# Chat Flow / Routing architecture defaults
CONTEXT_PROFILE = "8k"
HISTORY_MAX_MESSAGES = 10
SUMMARY_ENABLED = True
SUMMARY_UPDATE_EVERY_N_TURNS = 8
SUMMARY_MAX_TOKENS = 220
SUMMARY_LAST_TURNS_TO_SUMMARIZE = 12
SUMMARY_USE_LLM = False
SUMMARY_MODEL = MEMORY_MODEL
ROUTING_DEBUG = True

# Deterministic context budgets (approx-token budgets)
BUDGET_MEMORY_TOKENS = 420
BUDGET_SEARCH_TOKENS = 550
BUDGET_HISTORY_TOKENS = 900
BUDGET_OUTPUT_RESERVE_TOKENS = 320
CHAT_CONTEXT_PROFILE = "8k"
CHAT_CONTEXT_PROFILES = {
    "4k": {"max_context_tokens": 4096, "history_turns": 4, "memory_chars": 900, "summary_chars": 350},
    "8k": {"max_context_tokens": 8192, "history_turns": 8, "memory_chars": 1600, "summary_chars": 500},
    "16k": {"max_context_tokens": 16384, "history_turns": 12, "memory_chars": 2600, "summary_chars": 800},
    "32k": {"max_context_tokens": 32768, "history_turns": 18, "memory_chars": 4200, "summary_chars": 1200},
}

DEFAULT_MAX_NEW_TOKENS = 512
RESPONSE_TOKEN_SOFT_LIMIT = 300

HISTORY_KEEP_RAW_LAST_N = 6
HISTORY_COMPRESS_AFTER_N = 12
COMPRESSION_AGGRESSIVENESS = 0.7

# For proactive reminders (placeholders for reminders.py)
PROACTIVE_REMINDER_INTERVAL_MIN = 60

# Hardware scaling flags
ALLOW_16K_CONTEXT = False
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
PROMPT_BUDGET_EVIDENCE = 1200
PROMPT_BUDGET_HISTORY = 2200
PROMPT_BUDGET_USER_RESERVE = 450

# OCR triggers
GENERAL_OCR_TRIGGERS = ["ocr", "extract text", "scan", "read this", "transcribe", "digitize"]
STRUCTURED_OCR_TRIGGERS = []

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
TTS_ENGINE = "piper"
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
