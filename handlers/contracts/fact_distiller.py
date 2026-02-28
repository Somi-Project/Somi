from __future__ import annotations

import time
from typing import Any, Dict, List

from handlers.research.science_stores import ResearchedScienceStore


class FactDistiller:
    def __init__(self):
        self.researched = ResearchedScienceStore()

    def distill_and_write(self, artifact: Dict[str, Any], *, require_doc_page_refs: bool = True) -> int:
        at = str(artifact.get("artifact_type") or "")
        if at == "research_brief":
            return self._write_research_facts(artifact)
        if at == "doc_extract":
            return self._write_doc_facts(artifact, require_doc_page_refs=require_doc_page_refs)
        return 0

    def _write_research_facts(self, artifact: Dict[str, Any]) -> int:
        content = dict(artifact.get("content") or {})
        findings = list(content.get("key_findings") or [])
        cits = list(artifact.get("citations") or [])
        if not findings or not cits:
            return 0

        facts: List[Dict[str, Any]] = []
        for idx, f in enumerate(findings[:6]):
            cit = cits[idx] if idx < len(cits) else {}
            src = str(cit.get("url") or "").strip()
            # facts-only contract: each distilled claim must have a citation URL
            if not src:
                continue
            facts.append(
                {
                    "topic": str(artifact.get("inputs", {}).get("user_query") or "research")[0:120],
                    "fact": str(f),
                    "source": src,
                    "confidence": "high",
                    "domain": "general",
                    "tags": f"artifact:research_brief;ts:{int(time.time())}",
                    "evidence_snippet": str(cit.get("title") or "")[:240],
                }
            )
        return self.researched.add_facts(facts, domain="general") if facts else 0

    def _write_doc_facts(self, artifact: Dict[str, Any], *, require_doc_page_refs: bool) -> int:
        content = dict(artifact.get("content") or {})
        table_extract = list(content.get("table_extract") or [])
        page_refs = list(content.get("page_refs") or [])
        if not table_extract:
            return 0
        if require_doc_page_refs and not page_refs:
            return 0

        facts: List[Dict[str, Any]] = []
        for idx, row in enumerate(table_extract[:8]):
            row_ref = ""
            if isinstance(row, dict):
                row_ref = str(row.get("page_ref") or row.get("ref") or row.get("page") or "").strip()
            if not row_ref and idx < len(page_refs):
                row_ref = str(page_refs[idx] or "").strip()
            if not row_ref and page_refs:
                row_ref = str(page_refs[0] or "").strip()
            if require_doc_page_refs and not row_ref:
                continue
            source_ref = row_ref or "doc_ref"
            facts.append(
                {
                    "topic": str(artifact.get("inputs", {}).get("user_query") or "document")[0:120],
                    "fact": str(row),
                    "source": str(source_ref),
                    "confidence": "medium",
                    "domain": "document",
                    "tags": f"artifact:doc_extract;ts:{int(time.time())}",
                    "evidence_snippet": str(source_ref),
                }
            )
        return self.researched.add_facts(facts, domain="document") if facts else 0
