from dataclasses import dataclass


@dataclass
class PlaywrightSession:
    mode: str
    cookie_file: str
