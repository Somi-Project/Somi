import re


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()
