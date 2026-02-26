"""Search/routing-focused settings kept separate from config/settings.py to reduce bloat."""

# Debug formatting behavior for WebSearchHandler.format_results.
WEBSEARCH_DEBUG_RESULTS = False

# Hard cap for formatted web context passed into prompts.
WEBSEARCH_MAX_FORMAT_CHARS = 9000
