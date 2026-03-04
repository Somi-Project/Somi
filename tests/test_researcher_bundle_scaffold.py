from handlers.research.evidence_bundle import bundle_from_results


def test_bundle_from_results_builds_claims_and_links():
    results = [
        {"title": "Trial shows improved outcome", "description": "PMID-backed summary", "url": "https://example.com/a", "source": "pubmed"},
        {"title": "Guideline update", "description": "society recommendation", "url": "https://example.com/b", "source": "searxng_research"},
    ]

    bundle = bundle_from_results("stroke management", results, domain="biomed")
    d = bundle.as_dict()

    assert d["query"] == "stroke management"
    assert len(d["claims"]) == 2
    assert len(d["evidence_links"]) == 2
    assert d["corroboration"]["support_count"] == 2
    assert bundle.validate() == []
