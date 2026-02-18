import re
from typing import List

from speech.config import TTS_MAX_CHARS_PER_CHUNK

_SENT_BOUNDARY_RE = re.compile(r"[.!?\n]")
_DECIMAL_RE = re.compile(r"\d\.\d")
_URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
_ABBREVIATIONS = {
    "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.", "vs.", "etc.",
    "e.g.", "i.e.", "u.s.", "u.k.", "a.m.", "p.m.", "no.",
}


class StreamingChunker:
    def __init__(self, max_chars: int = TTS_MAX_CHARS_PER_CHUNK):
        self.max_chars = max_chars
        self._buffer = ""

    def feed(self, fragment: str) -> List[str]:
        if not fragment:
            return []
        self._buffer += fragment
        return self._drain(force=False)

    def flush(self) -> List[str]:
        return self._drain(force=True)

    def _drain(self, force: bool) -> List[str]:
        out: List[str] = []
        while True:
            split_at = self._find_split_index()
            if split_at is None:
                if force and self._buffer.strip():
                    out.extend(self._hard_wrap(self._buffer.strip()))
                    self._buffer = ""
                elif len(self._buffer) >= self.max_chars:
                    cut = self._buffer.rfind(" ", 0, self.max_chars)
                    if cut <= 0:
                        cut = self.max_chars
                    out.append(self._buffer[:cut].strip())
                    self._buffer = self._buffer[cut:].lstrip()
                break

            chunk = self._buffer[:split_at].strip()
            self._buffer = self._buffer[split_at:].lstrip()
            if chunk:
                out.extend(self._hard_wrap(chunk))
        return out

    def _find_split_index(self) -> int | None:
        if not self._buffer:
            return None

        candidate: int | None = None
        for match in _SENT_BOUNDARY_RE.finditer(self._buffer):
            idx = match.end()
            snippet = self._buffer[max(0, idx - 8):idx].lower()
            if any(snippet.endswith(abbr) for abbr in _ABBREVIATIONS):
                continue
            around = self._buffer[max(0, idx - 2): min(len(self._buffer), idx + 2)]
            if _DECIMAL_RE.search(around):
                continue
            if _URL_RE.search(self._buffer[max(0, idx - 16): min(len(self._buffer), idx + 16)]):
                continue
            candidate = idx
            if idx >= self.max_chars * 0.6:
                break

        if candidate is not None and candidate <= len(self._buffer):
            return candidate
        if len(self._buffer) > self.max_chars:
            cut = self._buffer.rfind(" ", 0, self.max_chars)
            return self.max_chars if cut <= 0 else cut
        return None

    def _hard_wrap(self, text: str) -> List[str]:
        if len(text) <= self.max_chars:
            return [text]
        chunks: List[str] = []
        remaining = text
        while len(remaining) > self.max_chars:
            cut = remaining.rfind(" ", 0, self.max_chars)
            if cut <= 0:
                cut = self.max_chars
            chunks.append(remaining[:cut].strip())
            remaining = remaining[cut:].lstrip()
        if remaining:
            chunks.append(remaining)
        return chunks


def chunk_text(text: str, max_chars: int = TTS_MAX_CHARS_PER_CHUNK) -> List[str]:
    chunker = StreamingChunker(max_chars=max_chars)
    chunks = chunker.feed((text or "").strip())
    chunks.extend(chunker.flush())
    return [c for c in chunks if c]
