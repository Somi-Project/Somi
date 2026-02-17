from __future__ import annotations

from typing import List, Set

from .store import SQLiteMemoryStore


class GraphExpander:
    def __init__(self, store: SQLiteMemoryStore):
        self.store = store

    def expand(self, user_id: str, scope: str, seed_node_ids: List[str], hops: int = 1, edge_budget: int = 200) -> List[str]:
        hops = max(0, min(int(hops), 2))
        frontier: Set[str] = set(seed_node_ids)
        visited: Set[str] = set(seed_node_ids)

        for _ in range(hops):
            if not frontier:
                break
            nxt = set(self.store.neighbors(user_id, scope, list(frontier), max_edges=edge_budget))
            nxt -= visited
            visited |= nxt
            frontier = nxt
        return list(visited)
