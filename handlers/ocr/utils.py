from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable, List


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def image_hashes(paths: Iterable[str]) -> List[str]:
    return [sha256_file(p) for p in paths]


def safe_basename(path: str) -> str:
    return Path(path).stem.replace(" ", "_")
