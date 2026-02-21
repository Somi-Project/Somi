from __future__ import annotations

import logging
from typing import List, Protocol

logger = logging.getLogger(__name__)


class VectorIndex(Protocol):
    def search(self, query_vec: List[float], limit: int = 20) -> List[str]:
        ...


class NullVectorIndex:
    def search(self, query_vec: List[float], limit: int = 20) -> List[str]:
        return []


class ZvecVectorIndex:
    def __init__(self, store):
        self.store = store

    def search(self, query_vec: List[float], limit: int = 20) -> List[str]:
        try:
            return self.store.vec_search(query_vec, limit=limit)
        except Exception as e:
            logger.warning("zvec search failed; returning empty: %s", e)
            return []
