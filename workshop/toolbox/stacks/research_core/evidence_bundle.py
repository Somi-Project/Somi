from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha1
from typing import Any, Dict, List


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bundle_id(query: str, domain: str) -> str:
    seed = f"{(query or '').strip().lower()}|{(domain or '').strip().lower()}|{_iso_now()}"
    return sha1(seed.encode("utf-8", errors="ignore")).hexdigest()[:16]


@dataclass
class EvidenceLink:
    claim_id: str
    source_url: str
    source_title: str = ""
    source_id_type: str = "url"
    source_id: str = ""
    snippet: str = ""


@dataclass
class AtomicClaim:
    claim_id: str
    text: str
    claim_type: str = "descriptive"
    confidence: float = 0.0
    status: str = "candidate"
    units: str = ""
    computation: str = ""


@dataclass
class CorroborationStats:
    support_count: int = 0
    contradict_count: int = 0
    source_diversity: int = 0
    recency_hint: str = ""


@dataclass
class EvidenceBundle:
    query: str
    intent: str = "science"
    domain: str = "general"
    created_at: str = field(default_factory=_iso_now)
    bundle_id: str = ""
    discovery_results: List[Dict[str, Any]] = field(default_factory=list)
    claims: List[AtomicClaim] = field(default_factory=list)
    evidence_links: List[EvidenceLink] = field(default_factory=list)
    corroboration: CorroborationStats = field(default_factory=CorroborationStats)
    conflicts: List[Dict[str, Any]] = field(default_factory=list)
    verdict: str = ""
    agentpedia_actions: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.bundle_id:
            self.bundle_id = _bundle_id(self.query, self.domain)

    def validate(self) -> List[str]:
        errors: List[str] = []
        if not (self.query or "").strip():
            errors.append("query is required")
        if not isinstance(self.discovery_results, list):
            errors.append("discovery_results must be a list")
        for c in self.claims:
            if not (c.text or "").strip():
                errors.append("claim text cannot be empty")
        return errors

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)



def bundle_from_results(
    query: str,
    results: List[Dict[str, Any]],
    *,
    intent: str = "science",
    domain: str = "general",
) -> EvidenceBundle:
    """
    Lightweight shadow-mode bundle builder from existing result contract.
    Non-invasive: no behavior changes for callers.
    """
    b = EvidenceBundle(query=query, intent=intent, domain=domain)
    b.discovery_results = list(results or [])

    for idx, r in enumerate(results or [], start=1):
        if not isinstance(r, dict):
            continue
        title = str(r.get("title") or "").strip()
        desc = str(r.get("description") or "").strip()
        text = title or desc
        if not text:
            continue

        cid = f"c{idx}"
        conf = 0.45
        src = str(r.get("source") or "").lower()
        if src in ("pubmed", "europepmc", "clinicaltrials"):
            conf = 0.70
        elif src in ("verified", "textbook", "researched"):
            conf = 0.75

        b.claims.append(AtomicClaim(claim_id=cid, text=text[:220], confidence=conf, status="candidate"))
        url = str(r.get("url") or "").strip()
        b.evidence_links.append(EvidenceLink(
            claim_id=cid,
            source_url=url,
            source_title=title[:180],
            source_id_type=str(r.get("id_type") or "url"),
            source_id=str(r.get("id") or "")[:120],
            snippet=desc[:240],
        ))

    b.corroboration = CorroborationStats(
        support_count=len(b.claims),
        contradict_count=0,
        source_diversity=len({str((r or {}).get("source") or "") for r in (results or [])}),
    )
    b.verdict = "Shadow evidence bundle generated from current research stack results."
    return b

