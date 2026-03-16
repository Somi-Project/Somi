__all__ = ["TwitterHandler"]


def __getattr__(name):
    if name == "TwitterHandler":
        from workshop.integrations.twitter.engine import TwitterHandler
        return TwitterHandler
    raise AttributeError(name)


