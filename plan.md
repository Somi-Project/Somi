# Researcher Layer Vision Plan (Phased, Low-Risk)

## 0) Vision Alignment (yes — fully understood)

You want a **careful, auditable researcher** that:

- uses **SearXNG as primary discovery**,
- enriches results with structured APIs (arXiv, PubMed, Semantic Scholar, ClinicalTrials, etc.),
- extracts **atomic claims**, corroborates claims, flags conflicts, performs computations when needed,
- emits a structured, auditable artifact (**EvidenceBundle**),
- and integrates into the current flow with **minimal risk/minimal changes**.

You also want Agentpedia to be the long-term memory substrate (agent-friendly Wikipedia), with textbook ingestion that is cacheable/idempotent and can be promoted into Agentpedia.

---

## 1) Current-State Deep Dive (from repo)

### 1.1 Where research tasks are triggered today

Research is triggered in two layers:

1. **Router intent layer** (`handlers/routing.py`)
   - Detects research markers (PMID/DOI/NCT/arXiv, study/trial/meta-analysis/guideline/etc.).
   - Emits `intent="science"` and routes to websearch path.

2. **Websearch handler layer** (`handlers/websearch.py`)
   - Uses `_is_research_query(...)` hard/soft signals.
   - If research-like, runs `_research_stack(...)`.

### 1.2 How research executes today

`_research_stack(...)` currently does:

- **Agentpedia path** first-class candidate:
  - `Agentpedia.search(...)` = local stores first (verified/textbook/researched), then optional router fallback.
- **SearXNG path** as parallel candidate:
  - `search_searxng(..., category="science", source_name="searxng_research")`.
- Deterministic winner picking between candidates, then fallback to DDG web if needed.

### 1.3 How storage/fetch works today

There are two memory tracks:

1. **Science stores** (`handlers/research/science_stores.py`)
   - `VerifiedScienceStore` (high-confidence facts)
   - `ResearchedScienceStore` (web-enriched facts with snippets/tags/domain)
   - `TextbookFactsStore` (book registry + textbook chunks, optional FTS)

2. **Agentpedia KB** (`handlers/research/agentpedia_kb.py`)
   - SQLite fact table + topic pages rendered to markdown in `agentpedia/pages/*.md`.
   - Has dedupe keys, confidence, citations, and topic-page generation.

`Agentpedia` orchestrator (`handlers/research/agentpedia.py`) bridges these and supports:

- local-first retrieval,
- router fallback,
- optional write-back to researched store,
- Agentpedia KB add/search/list/grow APIs.

### 1.4 Textbook ingestion today

- Existing ingestion command: `python -m handlers.research.science_ingest`.
- It scans `data/textbooks/*.pdf`, hashes files, skips already-ingested books, extracts/chunks, and stores into `TextbookFactsStore`.

### 1.5 Gaps vs desired vision

- No first-class **EvidenceBundle** contract across the full pipeline.
- Claim extraction/corroboration/conflict resolution exists only partially and not as explicit staged researcher workflow.
- Textbook UX path is `data/textbooks`; you want a clearer root-level `research/textbooks/` workspace with `.md` sidecars for fast lookup and idempotent ingestion.
- Agentpedia format exists, but retrieval/write policies can be made more agent-friendly and explicit (provenance, confidence, contradiction handling, domain weighting).
- SearXNG profiles exist globally, but not yet formalized as **domain research profiles** with per-domain engines/safety/timerange defaults.

---

## 2) Guiding Principles for implementation

1. **Keep current APIs stable** (do not break `websearch.py` consumers).
2. **Add, don’t rewrite**: introduce new modules/contracts behind feature flags.
3. **Deterministic and auditable by default**: every claim should show provenance and confidence basis.
4. **Idempotent ingestion**: no duplicate textbook processing.
5. **Progressive activation**: shadow mode -> dual-run -> primary mode.

---

## 3) Proposed Target Architecture (incremental)

### 3.1 New core artifact: `EvidenceBundle`

Create a typed artifact (dataclass / pydantic) with sections:

- `query`, `intent`, `domain`, `created_at`, `bundle_id`
- `discovery_results[]` (SearXNG + direct API findings)
- `claims[]` (atomic claims)
  - each claim: `claim_id`, `text`, `claim_type`, `units`, `computation`, `confidence`, `status`
- `evidence_links[]`
  - maps claim -> sources (URL/DOI/PMID/NCT/arXiv), snippet, extraction notes
- `corroboration`
  - support_count, contradict_count, source_diversity, recency
- `conflicts[]`
  - opposing claims + rationale
- `verdict`
  - concise “best current answer” with uncertainty notes
- `agentpedia_actions[]`
  - what was persisted / skipped and why

### 3.2 Research pipeline stages

1. **Discover** (SearXNG primary)
2. **Enrich** (domain APIs by identifier/content)
3. **Distill** (atomic claim extraction)
4. **Corroborate** (cross-source matching)
5. **Conflict detect** (explicit contradiction graph)
6. **Compute** (units/rates/risk deltas as needed)
7. **Assemble EvidenceBundle**
8. **Persist policy** (researched store + optional Agentpedia promotion)

### 3.3 Agentpedia as source-of-truth memory

- Agentpedia remains durable memory.
- Add stronger retrieval ranking:
  - confidence + freshness + source quality + user relevance.
- Add explicit contradiction status:
  - `active`, `contested`, `deprecated`, `superseded`.
- Keep human-friendly pages, but back them by machine-friendly normalized records.

---

## 4) Phased Execution Plan

## Phase 1 — Contracts + Observability (no behavior change)

**Goal:** introduce scaffolding safely.

- Add `handlers/research/evidence_bundle.py` (schema + validators).
- Add lightweight telemetry events for each research stage (discover/enrich/distill/etc.).
- Add feature flags in config:
  - `RESEARCHER_LAYER_ENABLED`
  - `RESEARCHER_BUNDLE_SHADOW_MODE`
  - `AGENTPEDIA_PROMOTE_FROM_BUNDLE`

**Risk:** very low.
**Rollback:** disable flags.

---

## Phase 2 — Domain SearXNG profiles + discovery normalization

**Goal:** improve primary discovery quality without changing user-facing behavior.

- Extend `handlers/research/searxng.py` profiles to domain-specific variants, e.g.:
  - `science_biomed`, `science_engineering`, `science_nutrition`, `science_religion`, `science_entertainment`, etc.
- Map `ResearchRouter` domain choice -> profile selection.
- Add per-profile engine allowlists and fallbacks.

**Risk:** low.
**Rollback:** fallback to existing `science` profile.

---

## Phase 3 — Enrichment connectors and claim distillation

**Goal:** add true researcher behavior.

- Add `handlers/research/enrichment.py` adapters:
  - PubMed, arXiv, Semantic Scholar, ClinicalTrials (start with currently used identifiers first).
- Add `handlers/research/claim_distiller.py`:
  - convert snippets/abstracts into atomic claims,
  - attach citations and extraction confidence.
- Keep output compatible with current `pack_result` by wrapping bundle summaries into old result shape.

**Risk:** medium.
**Rollback:** disable enrichment/distillation flags and keep existing router output.

---

## Phase 4 — Corroboration, conflict detection, and compute layer

**Goal:** evidence reasoning + contradictions.

- Add `handlers/research/corroborator.py` for claim-to-claim support graph.
- Add conflict scoring:
  - same topic, incompatible numerics or contradictory directional statements.
- Add compute utilities (unit normalization, percentage/risk deltas) with explicit computation trace in bundle.

**Risk:** medium.
**Rollback:** keep bundle fields optional and non-blocking.

---

## Phase 5 — Textbook workspace rework (`research/textbooks`) + idempotent sidecar markdown

**Goal:** enable “read a book” workflow you described.

- Create root folder:
  - `research/textbooks/` (raw files users drop in)
  - `research/textbooks/ingested/` (generated sidecar markdown)
- Ingestion behavior:
  - if `TextbookName.pdf` ingested, produce `research/textbooks/ingested/TextbookName.md`.
  - skip re-ingestion if hash unchanged and sidecar exists.
  - if changed hash, reprocess + refresh sidecar/version marker.
- Keep writing chunks to `TextbookFactsStore` for retrieval speed.
- Add command options:
  - ingest one,
  - ingest all,
  - `--absorb-all-to-agentpedia` for full textbook absorption when user explicitly asks.

**Risk:** low-medium.
**Rollback:** keep old `data/textbooks` reader as backward-compatible fallback.

---

## Phase 6 — Agentpedia persistence policy reconfiguration (agent-friendly)

**Goal:** optimize storage/fetch for long-term user-directed growth.

- Add policy layer (`handlers/research/agentpedia_policy.py`):
  - store only claims above confidence threshold,
  - prioritize user-interest domains,
  - decay stale low-value facts,
  - avoid duplicate near-equivalent claims.
- Add retrieval tuning:
  - weighted ranking by relevance + confidence + freshness + source trust.
- Add controlled promotion from bundle -> Agentpedia with reason codes.

**Risk:** medium.
**Rollback:** fallback to existing `Agentpedia.add_facts/search` behavior.

---

## Phase 7 — Integration, tests, and cutover

**Goal:** make researcher layer primary with confidence.

- Update `_research_stack` to optionally call new `ResearcherLayer.run(query)`.
- Shadow mode comparison:
  - old stack result vs bundle verdict quality signals.
- Add test suites:
  - contract tests (EvidenceBundle schema),
  - deterministic routing tests,
  - textbook idempotency tests,
  - Agentpedia promotion/conflict tests,
  - end-to-end research regression tests.

**Risk:** medium.
**Rollback:** one-flag revert to legacy stack.

---

## 5) Trigger matrix (what should happen when)

- **Research task triggered** when:
  - router intent is `science`,
  - query has research markers/identifiers,
  - or user explicitly asks to research/verify with sources.

- **Web search triggered** when:
  - local Agentpedia/textbook/researched coverage is insufficient,
  - or explicit request requires current/live information.

- **Textbook search triggered** when:
  - query semantically aligns to textbook-indexed topics,
  - and local textbook chunks exceed retrieval threshold.

- **Store to Agentpedia triggered** when:
  - user asks to save/absorb,
  - or auto-policy allows high-confidence bundle claims.

- **Absorb whole textbook triggered** only by explicit user instruction.

---

## 6) Concrete first implementation slice (recommended next PR)

To keep risk minimal, first build this narrow vertical slice:

1. Add `plan` scaffolding + config flags.
2. Add `EvidenceBundle` schema with no behavior change.
3. Add domain SearXNG profiles and router mapping.
4. Add `research/textbooks/` + sidecar markdown generation (idempotent).
5. Wire minimal bundle generation in shadow mode from existing results.

This gives immediate architecture progress while preserving existing UX.

---

## 7) Acceptance criteria for the full vision

- Every research response can emit an auditable `EvidenceBundle`.
- SearXNG is primary discovery path; enrichment APIs improve depth.
- Claims are atomic and linked to at least one citation.
- Contradictions are visible, not silently merged.
- Textbooks ingest once, produce searchable markdown sidecars, and skip duplicate work.
- Agentpedia grows in user-directed domains with clear persistence policy.
- Legacy flow remains available behind a feature flag for safe rollback.
