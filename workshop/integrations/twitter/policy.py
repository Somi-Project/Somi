import random
from config.twittersettings import TWITTER_PROFILE


def should_noop() -> bool:
    return random.random() < float(TWITTER_PROFILE.get("noop_probability", 0.0))
