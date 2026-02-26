from __future__ import annotations

import hashlib
from collections import OrderedDict
from typing import List

try:
    from ollama import AsyncClient
except Exception:  # pragma: no cover
    AsyncClient = None  # type: ignore

from config.memorysettings import EMBEDDING_MODEL


class EmbeddingUnavailable(RuntimeError):
    pass


class OllamaEmbedder:
    def __init__(self, client=None, model: str = EMBEDDING_MODEL, dim: int = 768, cache_size: int = 1024):
        self.client = client or (AsyncClient() if AsyncClient is not None else None)
        self.model = model
        self.dim = int(dim)
        self.cache: OrderedDict[str, List[float]] = OrderedDict()
        self.cache_size = int(cache_size)

    def _cache_get(self, key: str):
        v = self.cache.get(key)
        if v is None:
            return None
        self.cache.move_to_end(key)
        return v

    def _cache_set(self, key: str, val: List[float]):
        self.cache[key] = val
        self.cache.move_to_end(key)
        while len(self.cache) > self.cache_size:
            self.cache.popitem(last=False)

    async def embed(self, text: str) -> List[float]:
        s = (text or "")[:2000]
        h = hashlib.sha256(s.encode("utf-8", errors="ignore")).hexdigest()
        got = self._cache_get(h)
        if got is not None:
            return got
        if self.client is None:
            raise EmbeddingUnavailable("ollama client unavailable")
        try:
            resp = await self.client.embeddings(model=self.model, prompt=s)
            emb = resp.get("embedding") or resp.get("embeddings")
            if isinstance(emb, list) and emb and isinstance(emb[0], (float, int)):
                vec = [float(x) for x in emb[: self.dim]]
            elif isinstance(emb, list) and emb and isinstance(emb[0], list):
                vec = [float(x) for x in emb[0][: self.dim]]
            else:
                raise EmbeddingUnavailable("bad embedding payload")
            if len(vec) < self.dim:
                vec += [0.0] * (self.dim - len(vec))
            self._cache_set(h, vec)
            return vec
        except Exception as e:
            raise EmbeddingUnavailable(str(e))
