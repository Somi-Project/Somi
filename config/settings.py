# config/settings.py
DEFAULT_MODEL = "qwen3:8b"
MEMORY_MODEL = "phi3:3.8b"

USE_MEMORY2 = True
MEMORY_STORE_DIR = "memory_store"
MEMORY2_MAX_FACT_LINES = 12
MEMORY2_MAX_SKILL_LINES = 6
MEMORY2_MAX_TOTAL_CHARS = 2200
MEMORY2_VOLATILE_TTL_HOURS = 48
MEMORY2_EVENT_LOG_ENABLED = True
MEMORY2_EXTRACTION_ENABLED = True

USE_MEMORY3 = True
MEMORY_DB_PATH = "memory_store/memory.db"
MEMORY_PINNED_MD_PATH = "memory_store/MEMORY.md"
MEMORY_MAX_TOTAL_CHARS = 2200
MEMORY_MAX_PINNED_LINES = 10
MEMORY_MAX_FACT_LINES = 10
MEMORY_MAX_SKILL_LINES = 6
MEMORY_LINE_MAX_CHARS = 160
MEMORY_VOLATILE_TTL_HOURS = 48
MEMORY_EXTRACTION_ENABLED = True
MEMORY_CONF_MIN = 0.65
MEMORY_SUMMARY_EVERY_N_TURNS = 8
EMBEDDING_MODEL = "nomic-embed-text"
EMBEDDING_DIM = 768
SQLITE_VEC_ENABLED = True
SQLITE_VEC_EXTENSION_PATH = ""
MEMORY_DEBUG = True
INSTRUCT_MODEL = "stable-code:3b"
DEFAULT_TEMP = 0.4
DISABLE_MEMORY_FOR_FINANCIAL = True
VISION_MODEL = "glm-ocr:latest"
DEFAULT_LOCATION = "Port of Spain, Trinidad and Tobago"
DEFAULT_NEWS_REGION = "Trinidad and Tobago"

RAG_WEBSITES = [
    "placeholder"
]

# System timezone
SYSTEM_TIMEZONE = "America/New_York"
TWITTER_USERNAME = "placeholder"
TWITTER_PASSWORD = "placeholder"
# Twitter API credentials
TWITTER_API = {
    "api_key": "placeholder",
    "api_secret": "placeholder",
    "access_token": "placeholder",
    "access_token_secret": "placeholder",
    "bearer_token": "placeholder",
    "client_id": "placeholder",
    "client_secret": "placeholder",
}
# Twitter Auto-post and auto-reply intervals in minutes
AUTO_POST_INTERVAL_MINUTES = 242
AUTO_POST_INTERVAL_LOWER_VARIATION = 20  # -20 minutes
AUTO_POST_INTERVAL_UPPER_VARIATION = 30  # +30 minutes
AUTO_REPLY_INTERVAL_MINUTES = 240
AUTO_REPLY_INTERVAL_LOWER_VARIATION = 20  # -20 minutes
AUTO_REPLY_INTERVAL_UPPER_VARIATION = 30  # +30 minutes

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
# These are conservative defaults for 12GB VRAM + 24GB RAM; can be raised on better hardware
SESSION_DIR = "sessions/"  # Directory for per-user JSON session files
SESSION_AUTO_SAVE_EVERY_N_TURNS = 1  # Save after every N responses (1 = always, safe but slight overhead)

MAX_CONTEXT_TOKENS = 8192  # Hard cap on total tokens sent to LLM (fits most 8B models on 12GB VRAM)
DEFAULT_MAX_NEW_TOKENS = 512  # Default generation length (balanced for speed)
RESPONSE_TOKEN_SOFT_LIMIT = 300  # Aim for shorter responses unless long_form triggered

HISTORY_KEEP_RAW_LAST_N = 6  # Keep last N messages raw (for short-term coherence)
HISTORY_COMPRESS_AFTER_N = 12  # Trigger compression when history exceeds this
HISTORY_SUMMARY_MODEL = MEMORY_MODEL  # Use small model for summaries (e.g., phi3:3.8b – fast, low VRAM)
COMPRESSION_AGGRESSIVENESS = 0.7  # 0.0-1.0: higher = shorter summaries (more token savings, but less detail)

# For proactive reminders (placeholders for reminders.py)
PROACTIVE_REMINDER_INTERVAL_MIN = 60  # Minutes between checks (set high to avoid overhead)

# Hardware scaling flags (unlock on better setups)
ALLOW_16K_CONTEXT = False  # False on 12GB VRAM to avoid OOM; True for 24GB+
AUTO_COMPRESS_ON_LOW_MEMORY = True  # Automatically compress if nearing limits
UNRESTRICTED_MODE = False  # If True, bypass any future soft limits (maintains unrestricted nature)



# Heartbeat runtime defaults (calm monitor-only mode)
HEARTBEAT_ENABLED = True
HEARTBEAT_MODE = "MONITOR"  # OFF | MONITOR | ASSIST
HEARTBEAT_TICK_SECONDS = 10
HB_UI_HEARTBEAT_UPDATE_SECONDS = 2
HB_ALIVE_BREADCRUMB_MINUTES = 30

HB_MAX_EVENTS_BUFFER = 200
HB_MAX_UI_EVENTS_PER_DRAIN = 25
HB_EVENT_DEDUPE_COOLDOWN_SECONDS = 300

HEARTBEAT_QUIET_HOURS = ("22:00", "05:00")
HB_LOG_PATH = "sessions/logs/heartbeat.log"

# Heartbeat 1B: Daily greeting task
HB_FEATURE_DAILY_GREETING = True
HEARTBEAT_DAILY_GREETING_TIME = "05:00"
HB_GREETING_INCLUDE_QUOTE = True
HB_GREETING_INCLUDE_WEATHER = True
HB_GREETING_INCLUDE_NEWS_URGENT = False
HB_GREETING_MAX_WORDS = 80
HB_GREETING_CHANNEL = "activity"

# Heartbeat 1C: Weather warnings
HB_FEATURE_WEATHER_WARN = True
HB_WEATHER_CHECK_MINUTES = 45
HB_WEATHER_WARN_DEDUPE_HOURS = 8
HB_WEATHER_FRESHNESS_MINUTES = 180
HB_WEATHER_THRESHOLDS = {
    "precip_prob": 0.70,
    "rain_mm": 10,
    "wind_kph": 45,
    "heat_c": 35,
    "cold_c": 5,
    "storm_keywords": ["storm", "thunderstorm", "hurricane", "tropical storm", "flood", "hail", "severe"],
}
HB_WEATHER_FAIL_SILENT = True

# Heartbeat 1C: Delight slot
HB_FEATURE_DELIGHT = True
HB_DELIGHT_FREQUENCY = "3_per_week"  # daily | 3_per_week | weekly
HB_DELIGHT_QUIET_HOURS_RESPECT = True
HB_DELIGHT_COOLDOWN_HOURS = 24
HB_DELIGHT_AVOID_AFTER_GREETING_MINUTES = 60
HB_DELIGHT_MAX_WORDS = 50
HB_DELIGHT_SOURCES = ["local_jokes", "local_facts", "agentpedia_fact", "interest_snippet"]

# Explicitly disable autonomous news in heartbeat
HB_FEATURE_NEWS_URGENT = False
HB_NEWS_DISABLED = True

# Heartbeat 2A: Agentpedia growth
HB_FEATURE_AGENTPEDIA_GROWTH = True
HB_AGENTPEDIA_GROWTH_FREQUENCY = "weekly"  # weekly | 3_per_week | daily
HB_AGENTPEDIA_GROWTH_FREQUENCY_MODE = "explicit"  # explicit | role_default
HB_AGENTPEDIA_FACTS_PER_RUN = 2
HB_AGENTPEDIA_ANNOUNCE_UPDATES = False
HB_AGENTPEDIA_MIN_CONFIDENCE_TO_COMMIT = 0.70
HB_AGENTPEDIA_FAIL_SILENT = True

CAREER_ROLE = None
USER_INTERESTS = []
HB_FEATURE_CAREER_ROLE = True

HB_FEATURE_REMINDERS = True
HB_FEATURE_GOAL_NUDGES = True
HB_GOAL_NUDGE_INTERVAL_MINUTES = 240
