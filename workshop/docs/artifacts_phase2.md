# Artifacts Phase 2 — Implementation + Audit

This phase introduces two NL-triggered artifact contracts:

- `meeting_summary` (v1)
- `decision_matrix` (v1)

## What was implemented

### 1) New contracts and pipeline builders

- `meeting_summary` builder: `handlers/contracts/pipelines/meeting_notes.py`
- `decision_matrix` builder: `handlers/contracts/pipelines/decision.py`

Both are registered in `handlers/contracts/pipelines/__init__.py` and routed by `handlers/contracts/orchestrator.py`.

### 2) Conservative intent detection

`handlers/contracts/intent.py` now supports these intents with hard gates:

- `meeting_summary` only triggers on explicit meeting/transcript signals, transcript-like structure, or multiple meeting sections.
- `decision_matrix` only triggers with decision-framework intent plus >=2 options.

### 3) Strict validation + markdown rendering

`handlers/contracts/schemas.py` adds strict + lenient validators and renderers for both new contracts.

### 4) Backward-compatible storage envelope

Artifacts are still stored in `sessions/artifacts/*.jsonl` and now include aliases:

- `contract_name` (alias of `artifact_type`)
- `contract_version` (alias-like from `schema_version`)
- `data` (alias of `content`)
- `input_fingerprint` (normalized user input hash)

Older readers using `artifact_type` and `content` continue to work.

### 5) Fact distillation policy

No new Agentpedia/fact writes were added for `meeting_summary` or `decision_matrix`.
Only existing Phase 1 types still distill facts.

---

## Contract schemas

## Contract: `meeting_summary`

### Trigger rules

Trigger when one of the following is true:

- explicit ask for meeting notes/minutes/transcript summary
- transcript-like formatting (timestamps/speaker labels + multiline)
- >=2 of these sections present: `Agenda:`, `Attendees:`, `Action items:`, `Decisions:`, `Next steps:`

Do not trigger on short/general prompts.

### Required strict fields

- `title: string`
- `date: string | null`
- `attendees: list[string]`
- `summary: list[string]` (max 12)
- `decisions: list[string]` (max 10)
- `action_items: list[{owner, task, due}]`
- `risks_blockers: list[string]` (max 8)
- `extra_sections: list[{title, content}]`

### Rendering

Markdown includes:

- title/date/attendees
- summary bullets
- decisions
- action-items table
- risks/blockers
- extra sections

## Contract: `decision_matrix`

### Trigger rules

Trigger only when:

- decision-framework language is present (`help me decide`, `decision matrix`, `weighted criteria`, etc.), and
- at least two options are detected.

Must not trigger for one-option requests.

### Required strict fields

- `question: string`
- `options: list[string]` (2–8)
- `criteria: list[{name, weight, rationale}]` (>=2)
- `scores: list[{option, criterion, score, justification}]`
- `totals: list[{option, weighted_total}]`
- `recommendation: string`
- `sensitivity_notes: list[string]` (optional)
- `extra_sections: list[{title, content}]`

### Validation semantics

- weights must sum to 1.0 (0.999–1.001 tolerance)
- score range must be 1–5
- full option×criterion matrix coverage required

### Rendering

Markdown includes:

- question
- options
- criteria/weight table
- score table
- totals + recommendation
- sensitivity notes + extra sections

---

## Audit (simulate → audit → patch)

### Findings from re-audit

1. **Trigger conservatism needed tightening**
   - `meeting_summary` matching was too broad around generic “action items” language.
   - `decision_matrix` framework matching was too permissive for generic “options/criteria” wording.

2. **Robustness issue in storage aliasing**
   - `contract_version` casting could throw if `schema_version` was malformed.

3. **Latency/quality balance in decision scoring**
   - matrix total computation was refactored to O(n) lookup-backed aggregation for options×criteria coverage.
   - explicit score extraction is lightweight regex-based and falls back to deterministic heuristics.

### Patches applied

- tightened intent regex/gates for meeting and decision intents
- hardened storage alias cast for contract version
- improved decision builder score extraction and total calculation path

### Current risk notes

- Heuristic scoring in decision matrices remains non-domain-specific unless user provides explicit scores.
- Meeting parsing is section/line based; highly unstructured notes may still need manual cleanup.

---

## Failure modes and fallback behavior

- If intent confidence is below threshold, no artifact is generated.
- If strict validation fails, artifact orchestration fails safe and normal assistant output is returned.
- New types do not write distilled facts to Agentpedia.
