import re
from typing import List

from speech.config import TTS_MAX_CHARS_PER_CHUNK


def chunk_text(text: str, max_chars: int = TTS_MAX_CHARS_PER_CHUNK) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    pieces = [p.strip() for p in re.split(r"(?<=[\.,\?\!\n])", text) if p.strip()]
    out: List[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current} {piece}".strip() if current else piece
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            out.append(current)
        while len(piece) > max_chars:
            out.append(piece[:max_chars].strip())
            piece = piece[max_chars:]
        current = piece.strip()
    if current:
        out.append(current)
    return out
