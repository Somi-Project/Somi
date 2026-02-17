"""
Textbook ingestion v2.2 (one-time)
- Scan a folder of PDFs, hash each file, skip if already ingested
- Extract text by page with pdfplumber
- Chunk into compact "study notes" chunks
- Store into TextbookFactsStore + registry (book_id)

Run:
  python -m handlers.research.science_ingest

Folder default:
  data/textbooks
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import List, Tuple

from .science_stores import TextbookFactsStore, _norm_space

DEFAULT_TEXTBOOKS_DIR = Path("data") / "textbooks"


def _sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _chunk_text(text: str, max_len: int = 900) -> List[str]:
    """
    Chunk into paragraph-ish segments, favoring fact-like sentences.
    Conservative filter to avoid storing pure narrative/noise.
    """
    t = _norm_space(text)
    if not t:
        return []

    # drop very noisy tokens
    t = re.sub(r"\b(page\s+\d+|chapter\s+\d+)\b", " ", t, flags=re.I)
    t = re.sub(r"\s{2,}", " ", t).strip()

    parts = re.split(r"(?<=[\.\!\?])\s+", t)
    chunks: List[str] = []
    buf = ""
    for s in parts:
        s = s.strip()
        if not s:
            continue

        keep = any(k in s.lower() for k in [
            "is defined", "characterized", "treatment", "diagnosis", "risk",
            "contraind", "dose", "mg", "iv", "oral", "management", "complication"
        ])
        keep = keep or bool(re.search(r"\b\d+(\.\d+)?\b", s))
        if not keep:
            continue

        if len(buf) + len(s) + 1 <= max_len:
            buf = (buf + " " + s).strip()
        else:
            if len(buf) >= 120:
                chunks.append(buf)
            buf = s

    if len(buf) >= 120:
        chunks.append(buf)

    # final dedupe
    seen = set()
    out: List[str] = []
    for c in chunks:
        key = c[:160].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def ingest_folder(folder: Path = DEFAULT_TEXTBOOKS_DIR) -> Tuple[int, int]:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)

    store = TextbookFactsStore()

    pdfs = sorted([p for p in folder.rglob("*.pdf") if p.is_file()])
    books_added = 0
    chunks_added = 0

    if not pdfs:
        return (0, 0)

    import pdfplumber

    for pdf_path in pdfs:
        try:
            file_hash = _sha256_file(pdf_path)
        except Exception:
            continue

        if store.book_exists(file_hash):
            continue

        title = pdf_path.stem
        book_id = file_hash[:12]

        store.register_book(
            book_id=book_id,
            title=title,
            file_path=str(pdf_path),
            file_hash=file_hash,
        )
        books_added += 1

        with pdfplumber.open(str(pdf_path)) as pdf:
            for i, page in enumerate(pdf.pages):
                try:
                    txt = page.extract_text() or ""
                except Exception:
                    txt = ""
                if not txt or len(txt.strip()) < 120:
                    continue

                chunks = _chunk_text(txt, max_len=900)
                if not chunks:
                    continue

                chunks_added += store.add_chunks(
                    book_id=book_id,
                    title=title,
                    page=i + 1,
                    chunks=chunks,
                    tags="textbook",
                )

    return books_added, chunks_added


if __name__ == "__main__":
    b, c = ingest_folder(DEFAULT_TEXTBOOKS_DIR)
    print(f"[science_ingest] books_added={b}, chunks_added={c}")
