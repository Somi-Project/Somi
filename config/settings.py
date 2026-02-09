# config/settings.py
DEFAULT_MODEL = "qwen3:8b"
MEMORY_MODEL = "phi3:3.8b"
INSTRUCT_MODEL = "stable-code:3b"
DEFAULT_TEMP = 0.4
DISABLE_MEMORY_FOR_FINANCIAL = True
VISION_MODEL = "glm-ocr:latest"
# System timezone
SYSTEM_TIMEZONE = "America/Port_of_Spain"
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

