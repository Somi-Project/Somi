from config.twittersettings import TWITTER_API_ENABLED


class TwitterApiClient:
    def __init__(self):
        self.enabled = bool(TWITTER_API_ENABLED)
