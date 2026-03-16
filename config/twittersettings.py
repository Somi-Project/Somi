TWITTER_USERNAME = "placeholder"
TWITTER_PASSWORD = "placeholder"

TWITTER_API = {
    "api_key": "placeholder",
    "api_secret": "placeholder",
    "access_token": "placeholder",
    "access_token_secret": "placeholder",
    "bearer_token": "placeholder",
    "client_id": "placeholder",
    "client_secret": "placeholder",
}

TWITTER_API_ENABLED = False
TWITTER_API_PREFER = False
TWITTER_DRY_RUN = False

AUTO_POST_INTERVAL_MINUTES = 242
AUTO_POST_INTERVAL_LOWER_VARIATION = 20
AUTO_POST_INTERVAL_UPPER_VARIATION = 30

AUTO_REPLY_INTERVAL_MINUTES = 240
AUTO_REPLY_INTERVAL_LOWER_VARIATION = 20
AUTO_REPLY_INTERVAL_UPPER_VARIATION = 30

TWITTER_PROFILE = {
    "enabled": True,
    "niche": "general",
    "topics_include": ["AI", "technology", "automation"],
    "topics_avoid": ["politics", "religion", "war", "medical advice"],
    "max_actions_per_hour": 6,
    "max_replies_per_hour": 4,
    "max_original_posts_per_day": 3,
    "timeline_engage_max_per_day": 1,
    "trend_post_max_per_day": 1,
    "mentions_per_cycle": 1,
    "noop_probability": 0.35,
    "per_user_reply_cap_per_hour": 2,
    "reply_char_range": (30, 160),
    "tweet_char_range": (80, 220),
    "avoid_hashtags": True,
    "avoid_emojis": True,
    "avoid_mentions": True,
    "min_persona_fit": 0.55,
    "min_engagement_proxy": 50,
    "skip_low_effort_mentions": True,
}

TWITTER_GROWTH = {
    "enabled": True,
    "scan_explore": True,
    "scan_home_timeline": True,
    "scan_search_suggestions": True,
    "trend_scan_runs_per_day": 1,
    "trend_candidates_limit": 15,
    "posts_sample_per_trend": 12,
    "timeline_posts_to_sample": 50,
    "max_scrolls_per_scan": 6,
    "min_trend_score": 0.60,
    "min_post_quality": 0.55,
    "min_author_quality": 0.45,
    "prefer_reply_over_quote": True,
    "trend_target_per_day": 1,
    "engage_popular_post_per_day": 1,
    "metrics_enabled": True,
    "metrics_check_hours": [1, 6, 24],
}
