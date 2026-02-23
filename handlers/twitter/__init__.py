__all__ = ["TwitterHandler"]


def __getattr__(name):
    if name == "TwitterHandler":
        from .engine import TwitterHandler
        return TwitterHandler
    raise AttributeError(name)
