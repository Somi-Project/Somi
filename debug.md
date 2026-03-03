# Debug Notes (Final Pass)

## Audit + Patch Cycle Completed
I re-ran an audit/simulate/patch loop focused on routing correctness, follow-up resolution robustness, finance historical fallback behavior, and news fallback quality.

## Changes made in this pass
1. **Follow-up ambiguity policy hardened**
   - `FollowUpResolver` now clarifies not only near-ties, but also **low-confidence follow-up-like prompts** (e.g., “that one”, “tell me more”).
   - If follow-up phrasing is detected and confidence is weak, it returns a ranked clarify list instead of silently falling through.

2. **Historical finance symbol inference fallback hardened**
   - Historical symbol inference no longer defaults to BTC when no symbol is detected.
   - If symbol inference is incomplete, historical path now falls back to `search_general(...)` using the original query + date context, preserving SearXNG-first behavior.

3. **News fallback quality heuristic improved (low-latency)**
   - Added cheap lexical relevance scoring for top SearX news results.
   - DDG fallback now triggers not only on low count but also **low relevance**, and weak SearX batches are de-prioritized in final ordering.
   - This adds negligible latency and improves result quality consistency.


5. **SearXNG query integrity enforced**
   - News SearXNG calls now use the original user query string (`q_hyg`) rather than LLM-refined DDG query text.
   - This ensures queries like "what's the price of bitcoin" are sent to SearXNG unchanged.

4. **Suggested hardening steps executed (from prior debug notes)**
   - Added route-decision snapshot logging in `agents.py` to `sessions/logs/routing_decisions.log` (ts/user/prompt/route/reason/intent/last_tool_type).
   - Added explicit tests for follow-up phrasing variants (`result #2`, `link 2`, “that one” clarify behavior), contextual news follow-up route, and finance fallback when symbol is unresolved.

## Validation status
- `pytest -q tests/test_simulation_routing_flows.py handlers/websearch_tools/tests/test_followup_and_fallbacks.py` => pass
- `python -m py_compile` on modified modules/tests => pass
- Simulated flows:
  - general chat => `llm_only`
  - news query + natural-language follow-up => deterministic URL resolution
  - weather query => weather route
  - crypto price query => crypto route
  - crypto historical follow-up => historical response path or controlled fallback

## Current grey-zone notes
1. **Heuristic routing remains lexical**: edge-case phrasing can still challenge deterministic rules; route logs now exist for telemetry tuning.
2. **News relevance scoring is intentionally lightweight**: it improves quality without high latency, but is not semantic ranking.
3. **Tool context remains in-memory TTL**: accepted by requirement; no restart persistence by design.


## Ready-to-merge check
- Functional simulation set (i-v) passes.
- Focused test suite passes (17 tests).
- No blocking defects found in this final pass.
- Recommendation: **Ready to merge**.


## Additional final check
- **Explicit library-matched finance query normalization**: verified and patched so natural language financial queries are normalized before library calls.
  - Example: "what's the price of bitcoin now" -> Binance lookup input `bitcoin` (resolves to `BTCUSDT` in `bcrypto`).
  - Example: "what's the price of gold" -> commodity ticker resolution to `GC=F` for yfinance/yahooquery path.
