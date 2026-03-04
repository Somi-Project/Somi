# Websearch Hardening — Simulation / Debug / Patch x3

## What was implemented

### 1) Runtime SearXNG capability matrix
- Added capability probing in `handlers/research/searxng.py` with cached runtime detection (`/config` best-effort):
  - categories
  - engines
  - support flags for `time_range`, `language`, `safesearch`
- Profiles are now represented with shared `SearchProfile` dataclass and adapted automatically to supported capabilities.

### 2) Broader-profile retry for historical finance
- `search_finance_historical(...)` now:
  1. runs primary `finance_historical` profile,
  2. filters/ranks,
  3. **early-exits** if quality threshold met,
  4. otherwise triggers fallback path with a broader `general` SearXNG retry,
  5. then DDG fallback if still insufficient.

### 3) Latency budgets + balanced early exit
- Added stage budgets (default ms):
  - primary: 3500
  - fallback: 3500
  - enrich/filter window: controlled in pipeline
- Added early exit when filtered results already meet `min_results` to reduce latency without harming quality.

### 4) Structured telemetry counters
- Added counters in both general and finance-historical layers:
  - `sanitized_query_count`
  - `filtered_results_count`
  - `fallback_triggered_count`
- Exposed getters/reset helpers for tests and diagnostics.

### 5) Shared profile + normalization utilities
- Added `handlers/websearch_tools/search_common.py`:
  - `SearchProfile` dataclass
  - `normalize_search_result(...)`
  - `dedupe_by_url(...)`
- Used across wrappers to standardize normalization.

### 6) Pluggable ranking strategies by domain
- Added domain ranker map in finance historical module:
  - `finance_historical`
  - `science`
  - `news`
- Introduced `rank_results_by_domain(...)` for extensible ranking behavior.

### 7) Contract tests
- Added invariants for:
  - route reason for URL summarize
  - route reason for historical finance queries
  - follow-up ordinal selection correctness

### 8) Periodic telemetry diagnostics logging
- Wired lightweight periodic diagnostics emitters in both general and finance-historical search modules.
- Every interval, counters are logged with deltas and simple spike flags (fallback/filter spikes) for production drift detection.


---

## Simulation / Debug / Patch Cycles (3)

### Cycle 1
**Simulated sequence:**
1. what was the price of gold in nov 2022
2. what was the price of oil in nov 2022
3. what was bitcoin price in nov 2019
4. latest world news
5. summarize the 2nd result

**Observed:**
- Routing path appropriate (websearch, finance contextual follow-up where expected).
- Follow-up binding stable for ordinal selection.
- Historical rewrite avoided raw ticker leakage.

**Patch applied:**
- Tightened runtime adaptation and profile fallback flow.

### Cycle 2
**Observed:**
- Filtering quality improved, but needed standardized normalization and contract coverage.

**Patch applied:**
- Added shared normalization/profile utility and expanded tests for telemetry + fallback behavior.

### Cycle 3
**Observed:**
- Stable across reruns.
- `raw_ticker_leaks=0` in stress checks.
- Selection binding remains deterministic (`index=2` for “2nd result”).

**Patch applied:**
- Finalized ranking strategy hooks and invariant tests.

---

## Opinion: framework improvements vs pillars

### 1) Free
Very strong. Zero-key posture is preserved and improved by adaptive capability probing.

### 2) Exceptional UX
Improved through cleaner historical fallback, better follow-up determinism, and reduced junk pollution.

### 3) Low latency
Balanced: stage budgets + early-exit reduce unnecessary fallback cost while preserving quality thresholds.

### 4) Flawless operations
Improved with explicit telemetry counters and contract-style invariants.

### 5) Modular / expandable
Improved by introducing shared `SearchProfile` + normalization utility and pluggable domain rankers.

---

## Next sensible step
- Wire telemetry into a lightweight periodic diagnostics log/dashboard for production drift detection (e.g., sudden fallback spikes or filtering spikes).


## Manual log diagnosis patch
- Observed planner issue: historical finance turn was routed to websearch but query-plan selected `LLM_ONLY`, so tool execution did not run.
- Observed ticker issue: `"whats the price of oil now"` could match stock `NOW` from stock dictionary before commodity resolution.

### Fixes applied
- Query planner now forces `SEARCH_ONLY` for finance historical (time-anchor) queries to ensure data-backed tool execution.
- In `FinanceHandler.search_stocks_commodities`, commodity matching now runs before stock matching and stock candidates ignore current-time filler tokens (`now/today/current/latest`) to prevent `NOW` false positives.


## Additional simulate/debug pass
- Ran `scripts/simulate_search_quality.py --rounds 1` and confirmed rewrite cleanup no longer duplicates month anchors (e.g., `nov 2022 November 2022`).
- Patched `rewrite_historical_query` with anchor-equivalence detection for month/year/date/range before appending anchors.


## Endpoint compatibility simulate/debug patch
- Added `_build_endpoint_candidates(...)` in `finance.py` to produce endpoint-compatible, asset-focused candidate strings before ticker dictionary matching.
- This ensures cleaned API-facing inputs for free endpoints (yfinance/yahooquery/binance wrappers) after extraction/polishing.
- Re-ran simulation (`--rounds 2`) and verified routing/results injection remained stable with `raw_ticker_leaks=0`.


## Fresh simulation/debug verification (post endpoint-compat patch)
- Executed `python scripts/simulate_search_quality.py --rounds 3`.
- Results were stable across all rounds:
  - finance-historical turns routed via `websearch` with expected reasons,
  - follow-up ordinal binding remained deterministic (`index=2`),
  - stress check remained `raw_ticker_leaks=0`.
- No additional regression observed in simulated route/injection flow.
