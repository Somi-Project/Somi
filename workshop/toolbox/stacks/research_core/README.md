# research_core

Somi's evidence-first research engine.

This package is where browsing becomes a structured research loop instead of a
single search-result dump.

## Start Here

- `browse_planner.py`
  - decides quick browse vs deep browse vs special research modes
- `router.py`
  - routes research work into the right domain/profile
- `reader.py`
  - deep-read and extraction logic for opened pages
- `composer.py`
  - evidence-driven research composition
- `answer_adequacy.py`
  - checks whether the gathered evidence really answers the question
- `github_local.py`
  - no-API GitHub discovery, clone, and local inspection helpers
- `agentpedia.py`
  - local research memory integration

## Evidence Modules

- `evidence_schema.py`
  - bundle/item schemas
- `evidence_claims.py`
  - claim extraction helpers
- `evidence_reconcile.py`
  - contradiction and overlap handling
- `evidence_scoring.py`
  - source/evidence ranking
- `evidence_cache.py`
  - cached evidence reuse

## Domain/Provider Helpers

- `domains/`
  - domain profiles for biomed, engineering, nutrition, and others
- `searxng.py`
  - SearXNG integration
- `scrape_fallback.py`
  - fallback scrape behavior when cleaner retrieval paths fail

## Typical Contributor Questions

- "Why did Somi keep searching?"
  - start in `answer_adequacy.py`
- "Why did it choose this browse mode?"
  - start in `browse_planner.py`
- "Why did it summarize this repo this way?"
  - start in `github_local.py`, then `composer.py`
- "Where did this evidence bundle come from?"
  - start in `reader.py`, `evidence_schema.py`, and `composer.py`

## Related Layers

- [`workshop/toolbox/stacks/web_core/README.md`](/C:/somex/workshop/toolbox/stacks/web_core/README.md)
- [`workshop/toolbox/research_supermode/README.md`](/C:/somex/workshop/toolbox/research_supermode/README.md)
- [`executive/synthesis/README.md`](/C:/somex/executive/synthesis/README.md)
