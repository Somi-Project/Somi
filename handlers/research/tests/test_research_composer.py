import sys
import types

if "httpx" not in sys.modules:
    hx = types.ModuleType("httpx")

    class _Resp:
        status_code = 200
        headers = {"content-type": "text/html"}
        text = ""

    class _Client:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        async def get(self, *args, **kwargs):
            return _Resp()

    hx.AsyncClient = _Client
    sys.modules["httpx"] = hx

import asyncio

import handlers.research.composer as composer
from handlers.research.evidence_claims import ClaimCandidate
from handlers.research.evidence_reconcile import reconcile_claims
from handlers.research.evidence_schema import EvidenceItem


class _FakeRouter:
    def __init__(self, *args, **kwargs):
        pass

    async def search(self, question: str):
        return [
            {
                "title": "Guideline says treatment reduces risk by 20%",
                "url": "https://who.int/guideline/a",
                "description": "Official guideline update.",
                "source": "pubmed",
                "domain": "biomed",
                "published": "2025-01-01",
                "id_type": "pmid",
                "id": "123456",
            }
        ]


async def _fake_searx(*args, **kwargs):
    return [
        {
            "title": "Study reports treatment reduces risk by 20%",
            "url": "https://example.org/study",
            "description": "Randomized trial with 20% risk reduction.",
            "source": "searxng_research",
            "domain": "science",
            "published": "2025-01-02",
        }
    ]


async def _fake_deep_read(items, **kwargs):
    for i in items:
        i.content_excerpt = (
            "The trial demonstrates treatment reduces risk by 20% in adults. "
            "Guidelines recommend use for high-risk groups."
        )
    return items


def test_evidence_bundle_shape(monkeypatch):
    monkeypatch.setattr(composer, "ResearchRouter", _FakeRouter)
    monkeypatch.setattr(composer, "search_searxng", _fake_searx)
    monkeypatch.setattr(composer, "deep_read_items", _fake_deep_read)

    bundle = asyncio.run(composer.research_compose("latest guideline on treatment efficacy"))
    assert hasattr(bundle, "items")
    assert hasattr(bundle, "claims")
    assert hasattr(bundle, "conflicts")
    assert isinstance(bundle.items, list)


def test_corroboration_needs_multiple_sources_for_high():
    item = EvidenceItem(
        id="i1",
        title="single",
        url="https://example.com",
        source_type="academic",
        published_date="2024-01-01",
        retrieved_at="2026-01-01T00:00:00Z",
    )
    candidates = [ClaimCandidate(text="Drug reduces risk by 20%", item_id="i1")]
    claims, _ = reconcile_claims(candidates, items_by_id={"i1": item}, risk_mode="high")
    assert claims
    assert claims[0].confidence != "high"


def test_conflict_detection_numeric_opposition():
    item1 = EvidenceItem(id="a", title="a", url="https://a.org", source_type="academic", published_date=None, retrieved_at="x")
    item2 = EvidenceItem(id="b", title="b", url="https://b.org", source_type="academic", published_date=None, retrieved_at="x")
    cands = [
        ClaimCandidate(text="Treatment increases survival by 30% in adults.", item_id="a", numbers={"values": [{"value": 30.0, "unit": "%"}]}),
        ClaimCandidate(text="Treatment decreases survival by 10% in adults.", item_id="b", numbers={"values": [{"value": 10.0, "unit": "%"}]}),
    ]
    _, conflicts = reconcile_claims(cands, items_by_id={"a": item1, "b": item2}, risk_mode="normal")
    assert conflicts


def test_no_hallucination_when_empty(monkeypatch):
    class _EmptyRouter:
        def __init__(self, *args, **kwargs):
            pass

        async def search(self, question: str):
            return []

    async def _empty_searx(*args, **kwargs):
        return []

    monkeypatch.setattr(composer, "ResearchRouter", _EmptyRouter)
    monkeypatch.setattr(composer, "search_searxng", _empty_searx)

    bundle = asyncio.run(composer.research_compose("compare evidence for x"))
    assert "Insufficient evidence" in bundle.answer
