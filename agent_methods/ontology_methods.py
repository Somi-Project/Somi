from __future__ import annotations

"""Extracted Agent methods from agents.py (ontology_methods.py)."""


def _refresh_operational_graph(self, active_user_id: str, thread_id: str, *, force: bool = False) -> None:
    ontology = getattr(self, "ontology", None)
    if ontology is None:
        return
    try:
        ontology.refresh_thread(user_id=str(active_user_id or self.user_id), thread_id=str(thread_id or "general"), force=bool(force))
    except Exception as e:
        logger.debug(f"Operational graph refresh skipped: {type(e).__name__}: {e}")
