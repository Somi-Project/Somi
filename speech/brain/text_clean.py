import re


def clean_tts_text(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    return text
