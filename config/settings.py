# config/settings.py
DEFAULT_MODEL = "huihui_ai/qwen3-abliterated:1.7b"
MEMORY_MODEL = "codegemma:2b"
INSTRUCT_MODEL = "phi4-mini-reasoning:3.8b"
DEFAULT_TEMP = 0.9
DISABLE_MEMORY_FOR_FINANCIAL = True

# Twitter login
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
    "client_secret": "placeholder"
}
# Twitter Auto-post and auto-reply intervals in minutes
AUTO_POST_INTERVAL_MINUTES = 242
AUTO_POST_INTERVAL_LOWER_VARIATION = 20  # -20 minutes
AUTO_POST_INTERVAL_UPPER_VARIATION = 30  # +30 minutes
AUTO_REPLY_INTERVAL_MINUTES = 240
AUTO_REPLY_INTERVAL_LOWER_VARIATION = 20  # -20 minutes
AUTO_REPLY_INTERVAL_UPPER_VARIATION = 30  # +30 minutes

TELEGRAM_BOT_TOKEN = "placeholder"
TELEGRAM_BOT_USERNAME = "placeholdert"
TELEGRAM_AGENT_ALIASES = ["placeholder", "placeholder", "placeholder", "placeholder"]

VISION_MODEL = "qwen2.5vl:3b"

RAG_WEBSITES = [
    "placeholder"
]

# System timezone
SYSTEM_TIMEZONE = "America/New_York"
