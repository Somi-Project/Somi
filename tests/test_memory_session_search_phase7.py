from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from runtime.history_compaction import build_compaction_summary
from search.session_search import SessionSearchService
from state import SessionEventStore


class MemorySessionSearchPhase7Tests(unittest.TestCase):
    def test_session_search_recalls_prior_decision_and_compaction_summary(self) -> None:
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        state_store = SessionEventStore(db_path=Path(root) / "state.sqlite3")
        searcher = SessionSearchService(
            state_store=state_store,
            artifacts_root=Path(root) / "artifacts",
            jobs_root=Path(root) / "jobs",
        )
        trace = state_store.start_turn(
            user_id="phase7-user",
            thread_id="planning",
            user_text="What did we decide about the Tokyo budget?",
            routing_prompt="tokyo budget recall",
        )
        state_store.finish_turn(
            trace=trace,
            assistant_text="We decided on a mid-range Tokyo budget of about $250 per day including hotel and trains.",
            status="completed",
            route="llm_only",
            model_name="phase7-test",
            routing_prompt="tokyo budget recall",
            latency_ms=42,
        )
        recall = searcher.answer_recall("Tokyo budget", user_id="phase7-user", thread_id="planning", limit=3, days=30)
        compacted = build_compaction_summary(
            messages=[
                {"role": "user", "content": "Remember the Tokyo budget decision."},
                {"role": "assistant", "content": "Budget target is about $250 per day with hotel and transit."},
            ],
            state_ledger={
                "goals": ["Plan Tokyo travel well"],
                "decisions": ["Budget target is 250/day"],
            },
        )
        self.assertIn("Tokyo budget", recall)
        self.assertIn("$250 per day", recall)
        self.assertIn("Ledger decisions", compacted)


if __name__ == "__main__":
    unittest.main()
