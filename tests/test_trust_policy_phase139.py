from __future__ import annotations

import unittest

from runtime.answer_validator import build_answer_trust_summary, validate_and_repair_answer


class TrustPolicyPhase139Tests(unittest.TestCase):
    def test_high_stakes_low_evidence_adds_caution_prefix(self) -> None:
        repaired, issues = validate_and_repair_answer(
            content="The latest hypertension treatment is definitely this exact plan.",
            intent="general",
            should_search=True,
            query_text="latest hypertension treatment guidance",
            evidence_contract={"required_min_sources": 2, "found_sources": 0},
            citation_map=[],
        )
        codes = {str(row.get("code") or "") for row in issues}
        self.assertIn("high_stakes_low_evidence", codes)
        self.assertTrue(repaired.startswith("Caution: this topic can affect health, legal, or financial decisions"))

    def test_strong_evidence_does_not_add_high_stakes_caution(self) -> None:
        repaired, issues = validate_and_repair_answer(
            content="The official guidance was updated and the source is cited.\n\nSources:\n- https://example.com/guidance",
            intent="general",
            should_search=True,
            query_text="latest hypertension guidance",
            evidence_contract={"required_min_sources": 2, "found_sources": 3},
            citation_map=[{"url": "https://example.com/guidance"}],
        )
        codes = {str(row.get("code") or "") for row in issues}
        self.assertNotIn("high_stakes_low_evidence", codes)
        self.assertFalse(repaired.startswith("Caution:"))

    def test_latest_query_without_date_adds_freshness_note_from_citation_map(self) -> None:
        repaired, issues = validate_and_repair_answer(
            content="The latest Python release improves error messages.\n\nSources:\n- https://docs.python.org/3/whatsnew/3.13.html",
            intent="general",
            should_search=True,
            query_text="what changed in python 3.13 latest docs",
            evidence_contract={"required_min_sources": 1, "found_sources": 2},
            citation_map=[{"url": "https://docs.python.org/3/whatsnew/3.13.html", "published_at": "2026-03-18"}],
        )
        codes = {str(row.get("code") or "") for row in issues}
        self.assertIn("missing_freshness_date", codes)
        self.assertIn("Freshness note: the newest cited source I found is dated 2026-03-18", repaired)

    def test_trust_summary_reports_solid_with_single_medium_caution(self) -> None:
        summary = build_answer_trust_summary(
            issues=[{"code": "missing_freshness_date", "severity": "medium"}],
            should_search=True,
            query_text="latest guidance",
            evidence_contract={"found_sources": 2},
            citation_map=[{"url": "https://example.com/guidance", "published_at": "2026-03-18"}],
        )
        self.assertEqual(summary["level"], "solid")
        self.assertIn("Newest source date: 2026-03-18", summary["summary"])


if __name__ == "__main__":
    raise SystemExit(unittest.main())
