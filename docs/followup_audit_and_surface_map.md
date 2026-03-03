# Follow-up + Historical + News Fallback Audit

## Phase 0 — Audit Report

| Feature | Status | Evidence | Gap |
|---|---|---|---|
| Per-turn orchestrator | Exists | `Agent.generate_response` in `agents.py` and route selection via `decide_route` in `handlers/routing.py`. | No deterministic tool follow-up resolver before routing. |
| Follow-up resolver for tool results | Missing | No invocation of any `last_results`/tool-context resolver in orchestrator. | Follow-up prompts (e.g., "expand second one") were not deterministically mapped to prior result URLs. |
| Historical finance protocol | Missing/incomplete | `handlers/websearch_tools/finance.py` exposed current quote methods only (`search_crypto_yfinance`, `search_stocks_commodities`, `search_forex_yfinance`). | No historical time-constraint parser + no yfinance history route for follow-up queries like "in Oct 2021". |
| News provider fallback (SearXNG→DDG) | Incomplete | `handlers/websearch_tools/news.py` used DDG as primary provider only. | No SearXNG-first path, and no robust fallback on SearX failures or low-result cases. |

## Phase 1 — Follow-up Surface Map

| Tool Type | Follow-up intent classes | Deterministic resolution strategy |
|---|---|---|
| News/Web | ordinal (`second`, `link 3`), URL (`summarize https://...`), fuzzy headline fragment (`the one about ...`) | resolve URL directly, or map ordinal to cached ranked result, or fuzzy title/snippet match with ambiguity clarification list |
| Finance | time-constrained follow-up (`in 2021`, `Oct 2021`, `on 2021-12-31`, `between ...`) | detect time constraint and route to historical retrieval (`yfinance` history), then summarize range/high/low/close |
| Weather | detail/time refinements (`tomorrow`, `hourly`, `wind/rain`) | preserve context + re-query weather tool with refined constraint |
| Research | link-level extraction (`summarize first paper`, `open second link`) | same ordinal/URL resolver against previous search result context |
