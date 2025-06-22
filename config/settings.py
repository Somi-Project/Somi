# config/settings.py
DEFAULT_MODEL = "huihui_ai/qwen3-abliterated:1.7b"
MEMORY_MODEL = "codegemm:2b"
INSTRUCT_MODEL = "phi4-mini-reasoning:3.8b"
DEFAULT_TEMP = 0.9
DISABLE_MEMORY_FOR_FINANCIAL = True

TWITTER_USERNAME = "Somi_Ai_Friend"
TWITTER_PASSWORD = "Bones.12"
# Twitter API credentials
TWITTER_API = {
    "api_key": "nwIkrAc784c8k3dbKVVdQ43NY",
    "api_secret": "khJfgfse2jwaFQprQuqFR59O22WTbfgqnJJ2n4nW1Dyd2bs3zL",
    "access_token": "1927304408624140289-c0CEf7v5HVMYvqcumMGEY2UVfufugX",
    "access_token_secret": "fNGXefH78Gq1PS1vLZddx1ZQUvBzfaNXSXQD5955tHaeB",
    "bearer_token": "AAAAAAAAAAAAAAAAAAAAAHu62gEAAAAA5nt8DHuKpdseOiL9oMvz9HBMylw%3DcfO9vFNlerjYSO3UD7fE7fBFqHuPXtvoJhNwfIwtaj05kx8YaH",
    "client_id": "eHAzRHV0U3NxWXJ6c3FDTTh2WG06MTpjaQ",
    "client_secret": "T-wT1Nvrmi2N97BdFAdpwVmGzLOET1IIOs7RyxneHOmhxEW0-4"
}
# Twitter Auto-post and auto-reply intervals in minutes
AUTO_POST_INTERVAL_MINUTES = 242
AUTO_POST_INTERVAL_LOWER_VARIATION = 20  # -20 minutes
AUTO_POST_INTERVAL_UPPER_VARIATION = 30  # +30 minutes
AUTO_REPLY_INTERVAL_MINUTES = 240
AUTO_REPLY_INTERVAL_LOWER_VARIATION = 20  # -20 minutes
AUTO_REPLY_INTERVAL_UPPER_VARIATION = 30  # +30 minutes

TELEGRAM_BOT_TOKEN = "7745481120:AAH9xQOXP6OQJ5I_dHz_I653XXMhqx8lqXw"
TELEGRAM_BOT_USERNAME = "@SomiAnalyticsBot"
TELEGRAM_AGENT_ALIASES = ["Somi", "Somi bot", "Somi Agent", "Somi A.i.", "retard", "degenia"]

VISION_MODEL = "qwen2.5vl:3b"

RAG_WEBSITES = [
    "https://pmc.ncbi.nlm.nih.gov/articles/PMC7018407/"
]

# System timezone
SYSTEM_TIMEZONE = "America/New_York"