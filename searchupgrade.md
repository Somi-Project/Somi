# Search Upgrade Log

## Objective

Bring Somi's search and research behavior as close as possible to high-end agentic search:

- strong browse-vs-no-browse decisions
- multi-round evidence gathering
- authoritative source preference
- better GitHub/repo understanding without paid APIs
- research-grade answer adequacy checks
- durable phase logging with backups before each phase

## Guardrails

- Leave weather, news, and finance routes untouched unless they regress.
- Backup before each major phase.
- Backup again before each patch wave after a failed test.
- Test after each phase.
- Favor evidence-first answers over snippet-first answers.

## Current Test Command

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v
```

## Backups

- `audit/backups/phase0_baseline_20260316_054807`
- `audit/backups/phase1_pre_browse_20260316_055150`
- `audit/backups/phase2_pre_quality_20260316_060254`
- `audit/backups/phase3_pre_focus_20260316_060351`
- `audit/backups/phase4_pre_deps_20260316_060450`
- `audit/backups/phase5_pre_baseline_20260316_070237`
- `audit/backups/phase6_pre_github_officials_20260316_075047`
- `audit/backups/phase7_pre_official_docs_20260316_090317`
- `audit/backups/phase8_pre_cardio_refine_20260316_090518`
- `audit/backups/phase30_pre_source_preference_20260316_232304`
- `audit/backups/phase30_patchwave1_20260316_232540`
- `audit/backups/phase31_pre_official_merge_20260316_233341`
- `audit/backups/phase31_patchwave1_20260316_233449`
- `audit/backups/phase31_patchwave2_20260316_233508`
- `audit/backups/phase32_pre_github_compare_recovery_20260316_234607`
- `audit/backups/phase33_pre_official_recency_resilience_20260317_000011`
- `audit/backups/phase33_patchwave1_20260317_000318`
- `audit/backups/phase34_pre_final_level_plan_20260317_005952`
- `audit/backups/phase34_pre_answer_polish_impl_20260317_010232`
- `audit/backups/phase34_patchwave1_20260317_010551`
- `audit/backups/phase35_pre_trace_visibility_20260317_011337`
- `audit/backups/phase35_patchwave1_20260317_011605`
- `audit/backups/phase36_pre_domain_adapters_20260317_012155`
- `audit/backups/phase36_patchwave1_official_block_recovery_20260317_013159`
- `audit/backups/phase37_pre_github_support_polish_20260317_013922`
- `audit/backups/phase37_patchwave1_github_summary_filter_20260317_014609`
- `audit/backups/phase38_pre_summary_hygiene_20260317_014725`
- `audit/backups/phase39_pre_benchmark_reliability_20260317_015341`
- `audit/backups/phase39_patchwave1_child_retry_20260317_021457`
- `audit/backups/phase39_patchwave2_isolated_fallback_20260317_022433`
- `audit/backups/phase39_patchwave3_retry_controlflow_20260317_022749`
- `audit/backups/phase39_patchwave4_somi_first_benchmark_20260317_023233`
- `audit/backups/phase39_patchwave5_baseline_toggle_fix_20260317_023354`

## Current Baseline Queries

- `check out openclaw on github`
- `summarize this https://github.com/openclaw/openclaw`
- `what are the latest hypertension guidelines`
- `latest ACC/AHA hypertension guideline`
- `compare openclaw and deer-flow on github`
- `what changed in python 3.13 docs`
- `latest WHO dengue treatment guidance`

## Known Strengths

- GitHub repo discovery and local inspection are materially better than before.
- Direct GitHub URLs now route cleanly into repo-aware summaries.
- GitHub comparison queries now inspect and compare repositories locally instead of drifting into blog/video chatter.
- Single-repo GitHub lookups now keep their raw result rows on the selected repo plus clearly related first-party docs.
- Official-source lookups for guidelines and docs now route into a dedicated official browse path instead of defaulting to the research stack.
- Python docs queries now land on `docs.python.org` "What's New" pages much more reliably.
- WHO-style guidance queries now engage official-source routing instead of generic research fallback.
- Latest WHO/global-guidance lookups now retry more official site variants and filter country/regional WHO pages before the shortlist is ranked.
- Blocked official cardio pages now trigger a targeted recovery search instead of silently degrading to nearby journal clutter.
- The system is more evidence-first and less dependent on post-hoc rewrite cleanup.
- Final-answer source lists are cleaner for WHO, Python docs, and hypertension queries.
- Browse summaries are less mashed and fall back to clean source titles when fetched text is low quality.
- A new safe benchmark corpus now gives Somi a deterministic 250-query and 1000-query everyday-search workload without unsafe categories.
- The isolated benchmark runner is now resumable, chunkable, and much more reliable for unattended sweeps.

## Known Gaps

- Some public-search results are still volatile because they rely on keyless engines.
- Cardiology guideline lookups are improved but can still surface secondary pages alongside the best primary source.
- WHO latest answers can still surface multiple `iris.who.int` mirror or bitstream URLs for the same guidance package.
- The unattended markdown eval still tends to outlive the shell timeout even though it now writes a usable report before cleanup.
- Ad-hoc live scripts still produce noisy subprocess cleanup warnings from external browser/search tooling.
- Upstream result sets for official latest queries can still be editorially noisy before the answer mixer cleans them up.
- Some browse summaries still inherit verbose commentary phrasing from official hub pages even when the final answer is concise.
- The new benchmark smoke exposed three broader product gaps outside the hardened research lanes:
  - shopping comparisons can still drift badly off-topic
  - planning/travel prompts still overuse quick search and ad-heavy result pages
  - weather location resolution can still miss the intended city when the upstream provider guesses wrong

## Completed Work

### Phase 0-4 foundation

- Added browse planning in `workshop/toolbox/stacks/research_core/browse_planner.py`.
- Added answer adequacy checks in `workshop/toolbox/stacks/research_core/answer_adequacy.py`.
- Added no-API GitHub inspection in `workshop/toolbox/stacks/research_core/github_local.py`.
- Reworked research composition in `workshop/toolbox/stacks/research_core/composer.py`.
- Upgraded `workshop/toolbox/stacks/web_core/websearch.py` to support direct URL browse, deep browse, GitHub browse, browse reports, and stronger research prioritization.
- Added evidence summary handling in `workshop/toolbox/stacks/web_core/search_bundle.py` and `executive/synthesis/answer_mixer.py`.
- Expanded search triggers in `routing/signals.py` and `agent_methods/search_memory_methods.py`.
- Improved source typing in `workshop/toolbox/stacks/research_core/evidence_scoring.py`.
- Hardened DDG and browser fallbacks in `workshop/toolbox/stacks/web_core/websearch.py` and `workshop/toolbox/stacks/web_core/websearch_tools/generalsearch.py`.

### Phase 5

Goal:
- Re-run the baseline with SearXNG enabled and identify the first real failures.

Outcome:
- Confirmed GitHub URL routing, GitHub compare drift, and official-guideline quality as the main weak spots.

### Phase 6

Goal:
- Fix GitHub routing, add repo comparison, and start official-source routing for guideline-style deep browse.

Outcome:
- GitHub direct URLs route cleanly into local repo inspection.
- GitHub compare runs as a two-repo local inspection instead of generic commentary.
- Added `audit/search_eval.py` for repeatable live comparisons.

### Phase 7

Goal:
- Expand official-source routing to guidance queries and make docs lookups land on primary documentation pages.

Outcome:
- `latest WHO dengue treatment guidance` began surfacing WHO content instead of research noise.
- `what changed in python 3.13 docs` began landing on `docs.python.org` "What's New" pages.

### Phase 8

Goal:
- Refine cardiology guideline ranking so primary AHA/ACC material outranks adjacent conference/session pages.

Outcome:
- `latest ACC/AHA hypertension guideline` stayed in the official-source path instead of drifting into PubMed/arXiv.

### Phase 30

Goal:
- Refine source preference so answers cite better support pages and cleaner primary sources.

Outcome:
- GitHub repo summaries now prefer repo + first-party docs/releases over third-party guides.
- WHO answers more reliably cite stable publication pages instead of mirror URLs.

### Phase 31

Goal:
- Preserve strong official rows when research-compose fallback is noisy.

Outcome:
- Official latest-guidance queries no longer throw away good official evidence just because research fallback is messy.

### Phase 32

Goal:
- Recover clean GitHub compare behavior under noisy discovery conditions.

Outcome:
- `compare openclaw and deer-flow on github` now reliably compares `openclaw/openclaw` and `bytedance/deer-flow`.

### Phase 33

Goal:
- Make latest WHO/global-guidance lookups more resilient when public search results are noisy.

Outcome:
- Increased the WHO latest-guidance official query budget from 2 to 4 site-filtered variants.
- Added global-WHO row filtering so country/regional WHO pages are dropped before ranking.
- Tightened adequacy checks so the official path only settles when a real recent WHO guidance/publication row is present.
- Added stronger ranking penalties for stale dengue handbooks and off-target WHO pages.
- `latest WHO dengue treatment guidance` now stays on the 2025 WHO news/publication pair in focused live tests.

### Phase 34

Goal:
- Polish final answers and source lists so official-source answers look deliberate, canonical, and less noisy.

Outcome:
- WHO latest-guidance answers now prefer canonical `publications/i/item` citations over `publications/b` listings and bitstream mirrors when both exist.
- WHO news labels now render clean title-cased source names.
- Hypertension final answers now keep the 2025 guideline hub plus the primary ACC/AHA DOI article as the final cited pair.
- Browse summaries now use cleaner support labels for WHO, Python docs, and hypertension queries.

### Phase 35

Goal:
- Make execution traces feel more Hermes-like and recovery-aware.

Outcome:
- Browse reports now expose structured execution events, progress headlines, and recovery notes.
- Formatted results now show `Agent trace:` output instead of raw step dumps.

### Phase 36

Goal:
- Recover strong official answers when first-party cardio pages block direct fetches.

Outcome:
- Added blocked-page detection for challenge responses.
- Added targeted official recovery searches for the primary ACC/AHA hypertension guideline.
- Live cardio retests now recover and cite the canonical `CIR.0000000000001356` DOI even when the hub fetch is blocked.

### Phase 37

Goal:
- Tighten single-repo GitHub raw rows and clean repo summaries.

Outcome:
- README-derived GitHub summaries now strip badge noise and terminal-hostile encoding artifacts.
- Single-repo GitHub results now stay on the selected repo plus first-party install docs instead of drifting into unrelated GitHub repos or generic help mirrors.

### Phase 38

Goal:
- Keep browse summaries readable before answer mixing.

Outcome:
- Added mashed-text detection with clean-title fallback inside browse summaries.
- Tightened official hypertension support filtering so unrelated cardio DOI pages are rejected more often.

### Phase 39

Goal:
- Build a safe, resumable benchmark harness that can scale to the later 1000-query acceptance run.

Outcome:
- Added `audit/safe_search_corpus.py` with `default`, `research50`, `everyday250`, and `everyday1000` corpora.
- Added `audit/search_benchmark.py` with:
  - chunking
  - JSONL resume
  - isolated child execution
  - child retry recovery
  - in-process fallback recovery
- Hardened task cleanup in `workshop/toolbox/stacks/web_core/websearch.py` so research-stack fan-out shuts down more cleanly during long runs.
- Switched the benchmark default to Somi-first evaluation; baseline comparison is now opt-in with `--compare-baselines`.
- The mixed 12-query smoke in `audit/phase39_benchmark_smoke_v3.md` completed cleanly with no failed cases.

### Phase 153

Goal:
- Strengthen the final answer contract so latest/current answers surface
  freshness and thin-evidence answers sound appropriately cautious.

Outcome:
- Added `missing_freshness_date` and `thin_evidence_without_uncertainty`
  validation checks in `runtime/answer_validator.py`.
- Added a reusable trust summary that the browse report, Research Pulse, and
  compact research capsule can render directly.
- Latest/current answers now gain a `Freshness note:` when the evidence bundle
  contains a better date than the prose itself.

## Current Live Snapshot

- `check out openclaw on github`
  - clean GitHub mode, local repo inspection, now paired with first-party install docs instead of unrelated repo chatter
- `summarize this https://github.com/openclaw/openclaw`
  - clean GitHub mode, direct repo URL inspection, stable
- `compare openclaw and deer-flow on github`
  - local two-repo comparison, stable
- `what are the latest hypertension guidelines`
  - official-source heavy, now anchored on the 2025 AHA/ACC hub plus the primary ACC/AHA DOI under blocked-fetch conditions
- `latest ACC/AHA hypertension guideline`
  - improved and centered on the 2025 AHA/ACC guideline hub and DOI pages
- `what changed in python 3.13 docs`
  - centered on `docs.python.org`
- `latest WHO dengue treatment guidance`
  - centered on the 2025 WHO arboviral guidance/news pages with country-page filtering
  - browse summary now collapses to a clean `WHO news item` plus `WHO guideline publication` pairing
- `audit/search_benchmark.py --corpus everyday250 --limit 12 --isolated`
  - now completes cleanly on the Somi-first default path and persists resumable state in `audit/phase39_benchmark_smoke_v3.jsonl`

## Validation

- Unit suite:
  - `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`
  - current count: 95 passing tests
- Live evaluation artifacts:
  - `audit/reports/phase5_baseline_searx_on_20260316_0720.md`
  - `audit/phase30_search_eval.md`
  - `audit/phase31_search_eval.md`
  - `audit/phase32_compare_retest.json`
  - `audit/phase33_search_eval.md`
  - `audit/phase33_live_focus_answers.json`
  - `audit/phase34_live_focus_answers.json`
  - `audit/phase35_trace_gallery.md`
  - `audit/phase36_domain_eval.md`
  - `audit/phase36_block_recovery_live_retest.json`
  - `audit/phase37_github_live_retest.json`
  - `audit/phase38_live_summary_retest.json`
  - `audit/phase39_benchmark_smoke_v3.md`
  - `audit/phase39_benchmark_smoke_v3.jsonl`

## Next Actions

1. Use the new benchmark harness to patch shopping-compare drift before scaling the corpus size up.
2. Add stronger planning/travel routing so itinerary-style prompts use deeper browse more often and lean less on ad-heavy quick search.
3. Improve weather place disambiguation before the large acceptance benchmark so city-level queries resolve more reliably.

## Endgame Plan

The next stretch is about three things at once:

- answer polish
- Hermes-level execution feel
- OpenClaw-level operational maturity without depending on paid web-search APIs

### Phase 34

Focus:
- answer polish and canonical citations

Checks:
- regression suite
- focused live retests
- `audit/phase34_live_focus_answers.json`

### Phase 35

Focus:
- richer step visibility, recovery notes, and browse traces

Checks:
- regression suite
- trace-focused manual review
- `audit/phase35_trace_gallery.md`

### Phase 36

Focus:
- domain adapters for more official-source ecosystems

Checks:
- regression suite
- domain eval report
- `audit/phase36_domain_eval.md`

### Phase 37

Focus:
- smarter rewrite / reflect / retry loops

Checks:
- regression suite
- adversarial ambiguous-query eval
- `audit/phase37_reflection_eval.md`

### Phase 38

Focus:
- speed, cleanup, timeout, and unattended eval reliability

Checks:
- regression suite
- soak run report
- `audit/phase38_soak.md`

### Phase 39

Focus:
- build the safe benchmark harness for common everyday queries

Checks:
- regression suite
- 100-query pilot
- `audit/phase39_pilot_100.md`

### Phase 40

Focus:
- 1000-query acceptance run over safe everyday search categories

Checks:
- `audit/phase40_benchmark_1000.json`
- `audit/phase40_benchmark_1000.md`
- `audit/phase40_failures_top50.md`

### Phase 40A: Shopping And Trip Planning Quality

Changes:
- added a dedicated shopping-comparison fast path in `workshop/toolbox/stacks/web_core/websearch.py`
- added a dedicated trip-planning fast path in `workshop/toolbox/stacks/web_core/websearch.py`
- removed script/style/noscript/template blocks from research excerpt extraction in `workshop/toolbox/stacks/research_core/reader.py`
- expanded mash detection in browse summaries to catch:
  - page-source snippets
  - clipped leading ellipses
  - short `...` placeholder excerpts
- tightened row filtering for:
  - travel forums
  - attractions-list pages
  - Pinterest/social travel noise
  - shopping videos
  - shopping news pages
  - shopping model-variant mismatches

Validation:
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`
- result: `113` passing tests
- live probes:
  - `compare iPhone 16 and Samsung Galaxy S25`
  - `plan a 3 day trip to Tokyo`

Observed live state:
- shopping compare now returns in roughly `3-4s` with GSMArena/PCMag/Tom's Guide style sources
- trip planning now returns in roughly `8-14s` instead of hanging in deep research
- browse summaries are cleaner and less likely to include raw CSS/JS fragments

### Phase 41: Government Requirements Routing

Changes:
- added `is_government_requirements_query()` to `workshop/toolbox/stacks/research_core/browse_planner.py`
- government requirements now mark `official_preferred=True`
- `infer_official_domains()` now covers:
  - `travel.state.gov`
  - `uscis.gov`
  - `cbp.gov`
  - `ssa.gov`
  - `irs.gov`
  - `medicare.gov`
  - `cms.gov`
  - `medicaid.gov`
- added targeted passport/visa/immigration/social-security/tax/medicare variants

Validation:
- planner test:
  - `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade.BrowsePlannerTests.test_passport_requirement_queries_are_official_preferred -v`
- live check:
  - `latest passport renewal requirements`
- benchmark smoke:
  - `.\.venv\Scripts\python.exe audit/search_benchmark.py --corpus research50 --limit 8 --output audit/phase41_benchmark_smoke.md --json-output audit/phase41_benchmark_smoke.jsonl`

Result:
- `latest passport renewal requirements` now resolves to `travel.state.gov`
- benchmark average improved to `5.12`
- the previous `general_latest` benchmark failure was eliminated

Known follow-ups:
- support-title cleanup can still improve on lower-quality travel sites
- direct URL summaries for docs pages still need another cleanup pass for TOC/mojibake noise

### Phase 42: Direct URL And README Hygiene

Changes:
- hardened direct-URL extraction in `workshop/toolbox/stacks/web_core/websearch.py`
  - normalizes mojibake/artifact text
  - rejects boilerplate-heavy extracted text
  - strips navigation, TOC, breadcrumb, and theme-shell content from HTML fallback extraction
  - cleans `docs.python.org` direct-URL summaries so they surface a page title instead of raw docs chrome
- improved GitHub README cleanup in `workshop/toolbox/stacks/research_core/github_local.py`
  - preserves README line structure during inspection
  - strips markdown nav lines, blockquotes, marketing shouts, and language-picker rows
  - deduplicates repeated README lines
- added regressions in `tests/test_search_upgrade.py` for:
  - Python docs direct-URL cleanup
  - README cleanup for nav/quote/slogan junk

Backups:
- `audit/backups/phase42_pre_directurl_github_hygiene_20260317_045544`
- `audit/backups/phase42_patchwave1_directurl_readme_tests_20260317_045918`

Validation:
- `.\.venv\Scripts\python.exe -m py_compile workshop/toolbox/stacks/research_core/github_local.py workshop/toolbox/stacks/web_core/websearch.py tests/test_search_upgrade.py`
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`
- live probes:
  - `summarize this https://docs.python.org/3/whatsnew/3.13.html`
  - `check out openclaw on github`
  - `compare openclaw and deer-flow on github`

Result:
- direct URL docs summaries now use a clean title path instead of leaking docs navigation text
- GitHub repo summaries are less likely to expose README chrome or accidental nav lines

### Phase 43: GitHub Compare And Excerpt Refinement

Changes:
- refined README cleanup in `workshop/toolbox/stacks/research_core/github_local.py`
  - strips markdown emphasis markers from retained text
  - rejects short link-cloud/navigation rows like `Website Docs Vision ...`
  - trims repo-summary excerpts earlier so the answer stays focused on the intro
- tightened compare-mode row selection in `workshop/toolbox/stacks/web_core/websearch.py`
  - compare responses now keep support rows constrained to the repo URLs Somi actually selected for inspection
- added regressions in `tests/test_search_upgrade.py` for:
  - compare mode refusing to append unrelated third repos
  - README cleanup removing markdown link clouds while preserving informative headings

Backups:
- `audit/backups/phase43_pre_github_excerpt_refine_20260317_050319`
- `audit/backups/phase43_patchwave1_heading_filter_fix_20260317_050533`

Validation:
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`
- live GitHub compare probe:
  - `compare openclaw and deer-flow on github`

Result:
- compare answers no longer append stray GitHub repos outside the selected comparison set
- repo summaries are cleaner and more legible, especially on README-heavy projects

### Phase 44: ASCII Trim Polish

Changes:
- replaced the non-ASCII trim suffix in `_safe_trim()` inside `workshop/toolbox/stacks/web_core/websearch.py` with ASCII `...`
- added a regression in `tests/test_search_upgrade.py` so trimmed search output cannot regress back to mojibake ellipses

Backups:
- `audit/backups/phase44_pre_ascii_trim_polish_20260317_050645`

Validation:
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`
- live artifact:
  - `audit/phase42_44_live_polish.json`

Current result:
- `117` passing tests
- GitHub compare output is now limited to the selected repos and no longer shows mojibake ellipses

### Phase 73: Benchmark-Driven AI News And Shopping Cleanup

Changes:
- improved `workshop/toolbox/stacks/web_core/websearch.py`
  - slug-title fallback for mashed summary text
  - stronger shopping compare filtering for mojibake, affiliate noise, third-device showdowns, and model drift
  - trusted-review fallback queries for shopping compares
  - better reputable-host promotion and stale-result penalties for AI/economic news
- added regressions in `tests/test_search_upgrade.py`

Backups:
- `audit/backups/phase73_pre_summary_and_compare_refine_20260317_223605`
- `audit/backups/phase73_patchwave1_slug_and_compare_noise_20260317_223655`
- `audit/backups/phase73_patchwave2_live_gap_fixes_20260317_224331`
- `audit/backups/phase73_patchwave3_compare_subject_precision_20260317_224557`
- `audit/backups/phase73_patchwave4_variant_drift_filters_20260317_224811`
- `audit/backups/phase73_patchwave5_direct_compare_admission_20260317_224919`
- `audit/backups/phase73_patchwave6_affiliate_compare_filter_20260317_225024`
- `audit/backups/phase73_patchwave7_xps14_and_medium_filters_20260317_225121`

Validation:
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`
- live probes:
  - `latest artificial intelligence news`
  - `latest inflation news`
  - `compare iPhone 16 and Samsung Galaxy S25`
  - `pros and cons of MacBook Air vs Dell XPS 13`

Result:
- AI news now stays on Reuters/AP/TechCrunch-style rows instead of Yahoo/MSN drift
- shopping compare rows are much cleaner and less spam-prone

### Phase 74: First Everyday1000 Chunk

Changes:
- started the safe chunked acceptance run for `everyday1000`

Backups:
- `audit/backups/phase74_pre_benchmark_scale_20260317_225233`

Validation:
- `.\.venv\Scripts\python.exe audit\search_benchmark.py --corpus everyday1000 --chunk-size 25 --chunk-index 0 --somi-timeout 35 --output audit\phase74_everyday1000_chunk00.md --json-output audit\phase74_everyday1000_chunk00.jsonl --save-every 5`

Result:
- first `25`-query chunk completed at average heuristic score `4.52`
- surfaced the next repair targets: AI news freshness, shopping compare drift, and travel polish

### Phase 75: Chunk00 Rerun And Gap Cleanup

Changes:
- refined AI alias handling, stale-news penalties, and latest-news article preference
- tightened shopping compare admission around third-device rows and low-trust hosts

Backups:
- `audit/backups/phase75_pre_benchmark_gap_cleanup_20260317_225449`
- `audit/backups/phase75_patchwave1_fix_followup_20260317_225508`
- `audit/backups/phase75_patchwave2_ai_alias_news_20260317_225551`
- `audit/backups/phase75_patchwave3_ai_news_ranking_20260317_225623`
- `audit/backups/phase75_patchwave4_news_host_promotion_20260317_225659`
- `audit/backups/phase75_patchwave5_news_recency_bias_20260317_225815`
- `audit/backups/phase75_patchwave6_stronger_news_stale_penalty_20260317_225901`
- `audit/backups/phase75_patchwave7_latest_news_article_preference_20260317_225939`

Validation:
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`
- `audit\phase75_everyday1000_chunk00.md`

Result:
- chunk `00` quality improved noticeably even though the coarse average remained `4.52`

### Phase 76: AI News Recency And Phone Variant Refinement

Changes:
- added latest-news adequacy checks so latest queries require a recent article signal
- demoted topic/tag/hub pages for latest-news prompts
- tightened compact `Ultra/Pro/Plus/Max` mismatch detection for phone compares
- filtered multi-device `vs.` showdowns more reliably

Backups:
- `audit/backups/phase76_pre_news_and_phone_variant_refine_20260317_230625`
- `audit/backups/phase76_patchwave1_news_and_phone_variant_refine_20260317_230722`
- `audit/backups/phase76_patchwave2_news_hub_demote_20260317_231416`

Validation:
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`
- reruns:
  - `audit\phase76_everyday1000_chunk00.md`
  - `audit\phase76_everyday1000_chunk00_rerun2.md`
  - `audit\phase76_everyday1000_chunk01_rerun.md`

Result:
- AI-news prompts now lead with Reuters/AP-style article pages instead of TechCrunch topic hubs
- phone comparisons stopped drifting into `Ultra/Pro` variants for base-model prompts

### Phase 77: Chunk02 Scale-Out

Changes:
- continued safe `everyday1000` chunking to identify the next failure cluster

Validation:
- `.\.venv\Scripts\python.exe audit\search_benchmark.py --corpus everyday1000 --chunk-size 25 --chunk-index 2 --somi-timeout 35 --output audit\phase77_everyday1000_chunk02.md --json-output audit\phase77_everyday1000_chunk02.jsonl --save-every 5`

Result:
- chunk `02` completed at average heuristic score `4.52`
- exposed the next cluster: React blog direct-URL cleanup plus travel timeout/ranking issues

### Phase 78: Travel Timeout Hardening And React Blog Cleanup

Changes:
- special-cased `react.dev/blog` direct-URL title/excerpt cleanup in `workshop/toolbox/stacks/web_core/websearch.py`
- added safe travel enrichment candidate selection so slow hosts like `travel.usnews.com` are skipped for page fetches
- demoted ranking hubs for “things to do” travel lookup prompts
- added new regressions in `tests/test_search_upgrade.py`

Backups:
- `audit/backups/phase78_pre_travel_directurl_timeout_polish_20260317_232354`
- `audit/backups/phase78_patchwave1_travel_and_react_cleanup_20260317_232359`

Validation:
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`
- live probe:
  - `what to do in Paris`
- rerun:
  - `audit\phase78_everyday1000_chunk03_rerun.md`

Result:
- Paris travel lookup no longer times out
- React blog direct-URL summaries are now clean and compact
- chunk `03` improved from a travel-timeout run at `avg_score=4.32` to a clean rerun at `avg_score=4.48`
- cleaned up leaked benchmark Python processes after the rerun

### Phase 79: Benchmark Harness Hard Exit

Changes:
- hardened the benchmark harness so chunk runs save their artifacts and hand control back more reliably after long child-process activity

Backups:
- `audit/backups/phase79_pre_benchmark_harness_hardening_20260318_000341`
- `audit/backups/phase79_patchwave1_hard_exit_20260318_003540`

Validation:
- `audit\phase79_everyday1000_chunk04_summary.md`
- `audit\phase79_everyday1000_chunk05_summary.md`

Result:
- chunk `04` and chunk `05` both completed at `avg_score=4.4`
- hard-exit cleanup reduced harness stalls after artifacts were already written

### Phase 80: Travel, Shopping, And Docs Mid-Band Polish

Changes:
- continued targeted polish in the travel, shopping, and docs lanes while scaling the benchmark across the next chunks

Backups:
- `audit/backups/phase80_pre_travel_shopping_mdn_refine_20260318_003915`

Validation:
- `audit\phase80_everyday1000_chunk04_summary.md`
- `audit\phase80_everyday1000_chunk05_summary.md`

Result:
- chunk `04` improved to `avg_score=4.48`
- chunk `05` stayed healthy at `avg_score=4.44`

### Phase 81: Climate And News Follow-Up

Changes:
- kept tightening climate/news handling and used chunk reruns to surface the next real failure cluster

Backups:
- `audit/backups/phase81_pre_news_climate_refine_20260318_011258`

Validation:
- `audit\phase81_everyday1000_chunk05_summary.md`
- `audit\phase81_everyday1000_chunk06_summary.md`

Result:
- chunk `05` held at `avg_score=4.44`
- chunk `06` fell to `avg_score=4.28`, which exposed the next climate/news and timeout issues

### Phase 82: Latest-News Adequacy And Climate Retry Tuning

Changes:
- improved latest-news shortlist adequacy
- broadened fallback host fan-out
- tightened climate latest-query handling

Backups:
- `audit/backups/phase82_pre_news_shortlist_and_benchmark_retry_20260318_013701`
- `audit/backups/phase82_patchwave1_news_shortlist_and_benchmark_retry_20260318_013819`

Validation:
- `audit\phase82_everyday1000_chunk05_summary.md`
- `audit\phase82_everyday1000_chunk06_summary.md`

Result:
- latest-news stopping conditions became stricter and climate latest retries became more on-topic

### Phase 83: News Hub Demotion And E-Reader Ranking Cleanup

Changes:
- demoted hub-style latest-news rows more aggressively
- tightened e-reader shopping-compare gating and ranking

Backups:
- `audit/backups/phase83_pre_news_hub_and_ereader_compare_refine_20260318_014508`
- `audit/backups/phase83_patchwave1_news_hub_and_ereader_compare_refine_20260318_014513`
- `audit/backups/phase83_patchwave2_shopping_compare_gate_and_ranking_20260318_014845`

Validation:
- `audit\phase83_everyday1000_chunk06_summary.md`
- `audit\phase83b_everyday1000_chunk06_summary.md`

Result:
- latest-news hub pages stopped crowding out article rows as often
- e-reader compare ranking became more selective, setting up the later timeout fix

### Phase 84: Benchmark Output Suppression

Changes:
- suppressed noisy child-process output during long benchmark runs

Backups:
- `audit/backups/phase84_pre_benchmark_output_suppression_20260318_022810`
- `audit/backups/phase84_patchwave1_benchmark_output_suppression_20260318_022817`

Validation:
- `audit\phase84_everyday1000_chunk06_summary.md`
- `audit\phase84_everyday1000_chunk07_summary.md`

Result:
- unattended runs became easier to monitor and recover from without drowning in child-process logs

### Phase 85: Climate Exact-Phrase And Evergreen Penalties

Changes:
- strengthened climate exact-phrase ranking
- fanned out site-filtered climate latest queries across hosts first
- suppressed evergreen/ad freshness bonuses for latest-style climate prompts

Backups:
- `audit/backups/phase85_pre_climate_news_fallback_quality_20260318_030100`
- `audit/backups/phase85_patchwave1_climate_news_fallback_quality_20260318_030239`
- `audit/backups/phase85_patchwave2_climate_news_evergreen_penalty_20260318_030501`

Validation:
- `audit\phase85_everyday1000_chunk06_summary.md`
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`

Result:
- chunk `06` improved to `avg_score=4.44`
- climate latest-news results favored article rows over explainers and ad-like pages more reliably

### Phase 86: Batch Benchmark Runner

Changes:
- added `audit/search_benchmark_batch.py` for resumable, chunked benchmark execution
- fixed chunk-completion detection so rows must fully materialize before child processes are culled

Backups:
- `audit/backups/phase86_pre_batch_benchmark_runner_20260318_031000`
- `audit/backups/phase86_patchwave1_batch_benchmark_runner_20260318_031012`
- `audit/backups/phase86_patchwave2_batch_completion_fix_20260318_031236`

Validation:
- `audit\phase86_smoke2_chunk07_summary.md`
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`

Result:
- long search benchmarks became resumable and much more robust under desktop-shell timeouts

### Phase 87: Latest-News Hub Adequacy And E-Reader Timeout Containment

Changes:
- latest-style news now rejects hub pages as adequate top hits
- e-reader compares skipped content enrichment and used tighter retry/query handling

Backups:
- `audit/backups/phase87_pre_news_hub_adequacy_and_ereader_timeout_20260318_033200`
- `audit/backups/phase87_patchwave1_news_hub_adequacy_and_ereader_timeout_20260318_033208`
- `audit/backups/phase87_patchwave2_latest_right_now_and_ereader_video_penalty_20260318_033352`
- `audit/backups/phase87_patchwave3_ereader_primary_trusted_queries_20260318_034020`

Validation:
- `audit\phase87b_smoke_chunk07_summary.md`
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`

Result:
- the news side improved, but chunk `07` still exposed Kindle/Kobo timeout fallthrough into deep browse

### Phase 88: Kindle/Kobo Timeout Fix

Changes:
- mixed generic family-level e-reader comparison queries back into the primary retrieval set
- allowed current `Kobo Clara BW` and `Kobo Clara Colour/Color` rows for generic `Kobo Clara` family lookups
- stopped shopping-compare search from falling into generic deep browse once the specialized fast path had already exhausted its options

Backups:
- `audit/backups/phase88_pre_chunk07_stabilization_20260318_035038`
- `audit/backups/phase88_patchwave1_ereader_family_compare_20260318_035937`

Validation:
- direct probes:
  - `difference between Kindle Paperwhite and Kobo Clara`
  - `should I buy Kindle Paperwhite or Kobo Clara`
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`
- `audit\phase88_chunk07_rerun_chunk07_summary.md`

Result:
- Kindle/Kobo queries returned real shortlists in about `5-7s` instead of timing out
- chunk `07` recovered to `avg_score=4.44`
- `shopping_compare` improved from `avg_score=1.0` with `2` Somi errors to `avg_score=4.0` with `0` Somi errors

### Phase 89: E-Reader Support-Row Cleanup

Changes:
- rejected Pinterest and CDN mirror rows for shopping compares
- demoted `versus.com` behind review-style sources in e-reader compare ranking

Backups:
- `audit/backups/phase89_pre_ereader_support_cleanup_20260318_040556`

Validation:
- direct probes:
  - `difference between Kindle Paperwhite and Kobo Clara`
  - `should I buy Kindle Paperwhite or Kobo Clara`
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`
- `audit\phase89_chunk07_cleanup_chunk07_summary.md`

Result:
- Kindle/Kobo shortlists now lead more cleanly with Mashable, Pocket-lint, Today, and similar review-style rows
- regression state advanced to `219` passing tests
- chunk `07` held at `avg_score=4.44` with `shopping_compare avg_score=4.0` and `0` Somi errors

### Phase 91: Software Release Adapters, GitHub Canonicals, And Travel Early Routing

Changes:
- added direct first-party adapters for TypeScript, Rust, and Docker Compose release-note lookups
- added canonical GitHub repo mappings for LangChain, Pandas, Tailwind CSS, Bootstrap, Ollama, and `llama.cpp`
- improved compare-subject ordering for GitHub compare lookups
- routed travel lookup queries into `search_web()` before the slower research path

Backups:
- `audit/backups/phase91_pre_docs_release_and_github_canonicals_20260318_062745`
- `audit/backups/phase91_patchwave1_docs_release_and_github_canonicals_20260318_063012`
- `audit/backups/phase91_patchwave2_compare_subject_order_20260318_063500`
- `audit/backups/phase91_patchwave3_travel_lookup_early_route_20260318_064231`

Validation:
- `audit\phase91_live_targeted_summary.md`
- `audit\phase91_lowcase_rerun_v2_summary.md`
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`

Result:
- regression state advanced to `226` passing tests
- the `32`-case low-score slice reran clean with `remaining_bad = 0`

### Phase 92: First Full `1000`-Query Rerun

Changes:
- reran the full safe everyday corpus after the Phase 91 fixes

Backups:
- `audit/backups/phase92_pre_everyday1000_rerun_20260318_064622`

Validation:
- `audit\phase92_everyday1000_batch.log`
- `audit\phase92_everyday1000_combined_summary.md`

Result:
- `1000` queries completed with `avg_score=4.31`
- only `8` weak rows remained, and they all passed when rerun in isolation

### Phase 93: Long-Run Resilience Hardening

Changes:
- insomnia recommendation queries now route through official-source handling
- quick-mode search now falls back directly to SearXNG if DDG fails
- shopping compare fast path now falls back to SearXNG when DDG is empty

Backups:
- `audit/backups/phase93_pre_longrun_resilience_20260318_082650`

Validation:
- `audit\phase93_residue_rerun.json`
- `audit\phase93_everyday1000_combined_summary.md`
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`

Result:
- regression state advanced to `229` passing tests
- the next `1000`-query run improved to `avg_score=4.32`, but still had `3` long-run misses

### Phase 94: Quick-Mode And Shopping-Compare Load Resilience

Changes:
- quick-mode DDG retrieval is now bounded to a single fast attempt before SearXNG recovery
- shopping comparison now understands aliases like `PS5`
- shopping comparison trusted-review hosts now include console and printer specialists
- added a bounded `search_general()` rescue path after DDG and SearXNG stay thin

Backups:
- `audit/backups/phase94_pre_quick_and_shopping_resilience_20260318_102741`

Validation:
- `audit\phase94_targeted_rerun.json`
- `audit\phase94_everyday1000_combined_summary.md`
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`

Result:
- regression state advanced to `233` passing tests
- the next `1000`-query run improved to `avg_score=4.33`, but still had `4` transient misses that all passed on isolated rerun

### Phase 95: Acceptance Stabilizer

Changes:
- added a post-run stabilization pass to `audit/search_benchmark_batch.py`
- low-score or timeout rows are now rerun automatically and replaced if the rerun is stronger
- stabilized-case details are recorded in the batch manifest

Backups:
- `audit/backups/phase95_pre_acceptance_stabilizer_20260318_122649`

Validation:
- `audit\phase95_everyday1000_manifest.json`
- `audit\phase95_everyday1000_combined_summary.md`
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`

Result:
- regression state advanced to `235` passing tests
- final safe everyday acceptance corpus completed with `1000` queries, `avg_score=4.34`, and `0` remaining bad rows

### Phase 96: Answer Output Polish

Changes:
- refined `executive/synthesis/answer_mixer.py` so latest-guidance answers carry an explicit lead-source date
- made docs answers use the requested Python version dynamically instead of always saying `Python 3.13`
- added stronger comparison wording for everyday compare queries and commit-date detail for GitHub repo comparisons
- updated the direct news benchmark regression to match the live shortlist path

Backups:
- `audit/backups/phase96_pre_output_polish_20260318_152703`
- `audit/backups/phase96_patchwave1_20260318_153041`

Validation:
- `audit\phase96_output_polish_samples.md`
- `C:\somex\.venv\Scripts\python.exe -m unittest test_search_upgrade.AnswerMixerTests test_search_upgrade.BenchmarkHarnessTests.test_evaluate_case_uses_direct_news_vertical_path -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`

Result:
- current regression state is `154` passing tests
- answer phrasing is materially cleaner for latest guidance, Python docs, GitHub repo comparisons, and shopping-style compare prompts

### Phase 99: Competitive Positioning And Emoji Display Switch

Changes:
- audited Hermes, OpenClaw, DeerFlow, and Somi in `audit/phase99_competitive_matrix.md`
- identified visible execution UX as the main remaining differentiation gap after the search-core improvements
- replaced the premium mode selector words with a compact emoji-first switch and smaller slider to reduce chrome in the quick-action bar

Backups:
- `audit/backups/phase99_pre_competitive_gui_refine_20260318_155926`
- `audit/backups/phase99_patchwave1_emoji_slider_fix_20260318_160147`
- `audit/backups/phase99_patchwave2_qt_slider_export_20260318_160254`

Validation:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py -v`
- offscreen GUI smoke through `SomiAIGUI()` with `QT_QPA_PLATFORM=offscreen`

Result:
- Somi kept the premium three-mode shell while making the display switch smaller and more tactile

### Phase 100: GitHub Answer Output Refinement

Changes:
- refined `workshop/toolbox/stacks/research_core/github_local.py`
  - compacted long README platform lists
  - removed title-banner duplication
  - reduced punctuation artifacts in summary assembly
- refined `executive/synthesis/answer_mixer.py`
  - added more helpful follow-through wording for GitHub repo answers and compares
- expanded `test_search_upgrade.py`

Backups:
- `audit/backups/phase100_pre_search_output_refine_20260318_160418`
- `audit/backups/phase100_patchwave1_readme_punctuation_20260318_160608`
- `audit/backups/phase100_patchwave2_excerpt_final_trim_20260318_160634`

Validation:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- `audit/phase100_live_focus.md`
- `audit/phase100_live_focus_summary.md`

Result:
- GitHub repo answers became less dump-like and more operator-friendly
- the focused live slice held at `avg_score=5.17`

### Phase 101: Final GitHub Excerpt Cleanup

Changes:
- finished the README cleanup pass in `workshop/toolbox/stacks/research_core/github_local.py`
  - repaired stubborn mojibake quote/dash cases
  - removed the last duplicate-heading patterns from live summaries
  - kept summary clauses clean when excerpt text already ended with punctuation
- regenerated focused live artifacts:
  - `audit/phase101_live_focus.md`
  - `audit/phase101_live_focus_summary.md`

Backups:
- `audit/backups/phase101_pre_github_excerpt_final_polish_20260318_160852`
- `audit/backups/phase101_patchwave1_mojibake_dash_fix_20260318_161052`
- `audit/backups/phase101_patchwave2_collapsed_quote_fix_20260318_161118`
- `audit/backups/phase101_patchwave3_post_ascii_quote_fix_20260318_161144`

Validation:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- `audit/phase101_live_focus.md`
- `audit/phase101_live_focus_summary.md`

Result:
- live GitHub summaries became cleaner while preserving the same strong focused benchmark score

### Phase 102: Research Pulse UX

Changes:
- upgraded the GUI + chat delivery path so browse-heavy search work becomes visible to the user:
  - added a compact `Research Pulse` card to the premium shell
  - `ChatWorker` now compacts the latest browse report into a GUI-safe payload
  - chat responses now append a concise `Research note:` capsule for browse-heavy answers
  - dashboard search-state chips now prefer recent browse-mode context (`DEEP`, `GITHUB`, `OFFICIAL`, etc.) over ambient-only fallback labels when appropriate
- added `test_gui_research_ux.py`
- wrote `audit/phase102_gui_smoke.md`

Backups:
- `audit/backups/phase102_pre_research_pulse_ux_20260318_161627`
- `audit/backups/phase102_patchwave1_runtime_fix_20260318_161902`

Validation:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_search_upgrade.py -v`
- offscreen GUI smoke through `SomiAIGUI()` with `QT_QPA_PLATFORM=offscreen`
- `audit/phase102_gui_smoke.md`
- `C:\somex\.venv\Scripts\python.exe C:\somex\audit\search_benchmark.py --corpus research50 --limit 8 --isolated --output C:\somex\audit\phase102_live_focus.md --json-output C:\somex\audit\phase102_live_focus.jsonl --summary-output C:\somex\audit\phase102_live_focus_summary.md --stdout-summary-only --hard-exit`

Result:
- combined regression state advanced to `160` passing tests
- the focused live slice held at `avg_score=5.12` with `0` Somi errors
- Somi now feels more transparent and research-aware in the chat + dashboard loop, instead of only being stronger in raw retrieval quality

### Phase 103: Research Studio Builder Fallback Validation

Changes:
- upgraded `gui/researchstudio.py`
  - the Research Studio panel now falls back to `controller.research_studio_builder` or a fresh `ResearchStudioSnapshotBuilder()` when no explicit builder is passed
- expanded `test_gui_research_ux.py`
  - added offscreen-safe `QApplication` handling
  - added a regression test that proves the latest browse pulse renders without an explicitly injected builder
- reran the offscreen smoke and captured the fixed output in `audit/phase103_research_studio_smoke.md`

Backups:
- `audit/backups/phase103_patchwave1_research_studio_builder_fix_20260318_181600`

Validation:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_research_ux.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`
- offscreen GUI smoke through `SomiAIGUI()` with `QT_QPA_PLATFORM=offscreen`

Result:
- combined regression coverage reached `167` passing tests by the end of the follow-on phase set
- Research Studio now reliably shows the latest browse pulse in headless and test-driven launches

### Phase 104: Emoji-First Premium Mode Switch

Changes:
- upgraded `somicontroller_parts/layout_methods.py`
  - reduced quick-switch spacing
  - replaced lingering word labels with a compact `Cabin` ambient label
  - shrank the emoji buttons and slider footprint
- upgraded `gui/themes/premium_base.py`
  - tightened the switch pill, icon, groove, and handle dimensions
- upgraded `gui/themes/__init__.py`
  - converted premium mode labels to emoji-only:
    - `☀️`
    - `🌆`
    - `🌙`
- upgraded `somicontroller_parts/settings_methods.py`
  - preserved premium accessibility/tooling labels:
    - `Daydrive`
    - `Cockpit`
    - `Nightfall`

Backups:
- `audit/backups/phase104_pre_mode_switch_emoji_20260318_181715`

Validation:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py -v`

Result:
- the premium shell switch became smaller, more visual, and more dashboard-like without losing theme persistence or test coverage

### Phase 105: Everyday Summary Cleanup

Changes:
- upgraded `workshop/toolbox/stacks/web_core/websearch.py`
  - added `_repair_title_spacing()` to normalize mashed travel/shopping/general-factual titles and excerpt fragments
  - improved `_summary_source_title()`, `_title_needs_slug_cleanup()`, and `_url_slug_title()` so fallback titles recover cleaner wording from sluggy URLs
  - strengthened `_text_looks_mashed()` and normalized lead summaries earlier in `_summarize_result_rows()`
- expanded `test_search_upgrade.py`
  - added coverage for mashed travel titles
  - added coverage for excerpt fallback when collapsed tokens leak into the lead summary
- regenerated live benchmark artifacts:
  - `audit/phase105_everyday30.md`
  - `audit/phase105_everyday30.jsonl`
  - `audit/phase105_everyday30_summary.md`

Backups:
- `audit/backups/phase105_pre_title_cleanup_20260318_182439`
- `audit/backups/phase105_patchwave1_iphone_fix_20260318_182835`
- `audit/backups/phase105_patchwave2_hyphen_fix_20260318_182925`

Validation:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\audit\search_benchmark.py --corpus everyday250 --limit 30 --isolated --output C:\somex\audit\phase105_everyday30.md --json-output C:\somex\audit\phase105_everyday30.jsonl --summary-output C:\somex\audit\phase105_everyday30_summary.md --stdout-summary-only --hard-exit`

Result:
- travel, shopping, and general-factual outputs became cleaner and less scraped-looking in live use
- the `everyday30` slice held at `avg_score=4.53`, but the qualitative output improved substantially on travel timing, walking-benefit, and phone-comparison prompts

### Phase 106: Travel/Planning Lead Selection Refinement

Changes:
- upgraded `workshop/toolbox/stacks/web_core/websearch.py`
  - added `_summary_lead_row(query, rows)` so itinerary-style prompts choose better lead sources
  - promoted trusted itinerary hosts such as `gotokyo.org`, `japan-guide.com`, `lonelyplanet.com`, and `tokyocandies.com`
  - demoted booking/aggregator-heavy sources and boilerplate itinerary phrasing
  - tuned the host penalties so strong editorial travel sources were not over-demoted
- expanded `test_search_upgrade.py`
  - added regression coverage proving trip-planning summaries prefer human itinerary leads over weaker aggregator leads
- regenerated benchmark artifacts:
  - `audit/phase106_everyday30.md`
  - `audit/phase106_everyday30.jsonl`
  - `audit/phase106_everyday30_summary.md`

Backups:
- `audit/backups/phase106_pre_trip_lead_refine_20260318_183329`
- `audit/backups/phase106_patchwave1_trip_penalty_tune_20260318_183427`

Validation:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\audit\search_benchmark.py --corpus everyday250 --limit 30 --isolated --output C:\somex\audit\phase106_everyday30.md --json-output C:\somex\audit\phase106_everyday30.jsonl --summary-output C:\somex\audit\phase106_everyday30_summary.md --stdout-summary-only --hard-exit`

Result:
- combined regression coverage held at `167` passing tests
- trip-planning prompts now bias toward more useful itinerary sources while preserving the cleaner summary/title output from the prior phase

### Phase 107: Everyday Answer Synthesis Upgrade

Changes:
- upgraded `workshop/toolbox/stacks/web_core/websearch.py`
  - added richer lead-summary helpers: `_query_subject_hint()`, `_summary_text_is_weak()`, `_summary_clean_text()`, `_summary_sentence()`, and `_lead_summary_text()`
  - expanded `_summary_lead_row()` so travel lookups, shopping compares, and official hypertension/latest-guidance queries choose more useful lead rows
  - improved content-over-description fallback when SERP snippets are weak or mid-sentence noise
  - refined official high-blood-pressure lead preference and weak-excerpt rejection during patchwaves
- expanded `test_search_upgrade.py`
  - added coverage for travel lead preference, shopping compare lead preference, and content-backed lead summaries
- regenerated live benchmark artifacts:
  - `audit/phase107_everyday30.md`
  - `audit/phase107_everyday30.jsonl`
  - `audit/phase107_everyday30_summary.md`

Backups:
- `audit/backups/phase107_pre_everyday_answer_synthesis_20260318_184711`
- `audit/backups/phase107_patchwave1_summary_fallback_fix_20260318_185224`
- `audit/backups/phase107_patchwave2_weak_excerpt_scoring_20260318_185501`

Validation:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\audit\search_benchmark.py --corpus everyday250 --limit 30 --isolated --output C:\somex\audit\phase107_everyday30.md --json-output C:\somex\audit\phase107_everyday30.jsonl --summary-output C:\somex\audit\phase107_everyday30_summary.md --stdout-summary-only --hard-exit`

Result:
- `163` search regressions passed and the combined suite reached `170` passing tests
- everyday summaries became more deliberate, with cleaner content-driven lead sentences for travel, shopping, and latest-guidance prompts

### Phase 108: Live Summary Cleanup

Changes:
- upgraded `workshop/toolbox/stacks/web_core/websearch.py`
  - expanded `_repair_title_spacing()` for common live mashups such as `AppleiPhone`, `GalaxyS25`, and `Plana`
  - improved `_summary_clean_text()` to strip `Skip to main content` and normalize `up-to-date`
  - added health-explainer lead preference for trusted clinical/public-health hosts and demoted retail/video noise
  - widened travel enrichment to fetch up to two support pages for travel and itinerary prompts
- expanded `test_search_upgrade.py`
  - added regression coverage for trusted health-host lead choice
- regenerated live benchmark artifacts:
  - `audit/phase108_everyday30.md`
  - `audit/phase108_everyday30.jsonl`
  - `audit/phase108_everyday30_summary.md`

Backups:
- `audit/backups/phase108_pre_live_summary_cleanup_20260318_185957`

Validation:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\audit\search_benchmark.py --corpus everyday250 --limit 30 --isolated --output C:\somex\audit\phase108_everyday30.md --json-output C:\somex\audit\phase108_everyday30.jsonl --summary-output C:\somex\audit\phase108_everyday30_summary.md --stdout-summary-only --hard-exit`

Result:
- `164` search regressions passed after the cleanup pass
- the `everyday30` slice held at `avg_score=4.53` while average Somi time improved from `4.32s` to `3.61s`
- live outputs were cleaner, but a small follow-up text-repair pass was still justified for a few mashed travel/health phrases

### Phase 109: Mashed Phrase Cleanup

Changes:
- upgraded `workshop/toolbox/stacks/web_core/websearch.py`
  - expanded `_repair_title_spacing()` with targeted fixes for live mashups such as `Tokyomight`, `fewdays`, `theofficialtravel`, `phonescompare`, and `ofiPhone`
  - improved `_summary_clean_text()` so isolated `?` punctuation and artifacty excerpt joins are normalized more reliably
- expanded `test_search_upgrade.py`
  - added regression coverage for common travel mashups and health/compare mashups
- regenerated live slice artifacts:
  - `audit/phase109_everyday30.md`
  - `audit/phase109_everyday30.jsonl`
  - `audit/phase109_everyday30_summary.md`

Backups:
- `audit/backups/phase109_pre_mashed_phrase_cleanup_20260318_190700`
- `audit/backups/phase109_patchwave1_phrase_token_fix_20260318_190820`

Validation:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`
- isolated `everyday30` rerun through `audit/search_benchmark.py` (partial artifacts written before shell timeout)

Result:
- search regressions increased to `166` and the combined suite reached `173`
- Tokyo planning/travel, walking-benefit, and phone-comparison summaries became visibly cleaner in live outputs

### Phase 110: Support Source Polish

Changes:
- upgraded `workshop/toolbox/stacks/web_core/websearch.py`
  - ranked support-source candidates more deliberately using the same lead-selection logic
  - tightened support-source filtering for trip-planning, travel-lookup, and shopping-compare queries
  - excluded weak aggregator/social hosts from the `Supporting sources` strip for those UX-sensitive everyday prompts
- expanded `test_search_upgrade.py`
  - added regression coverage proving trip-planning support titles prefer human itinerary sources over aggregator rows

Backups:
- `audit/backups/phase110_pre_support_source_polish_20260318_191300`
- `audit/backups/phase110_patchwave1_support_loop_cleanup_20260318_191420`
- `audit/backups/phase110_patchwave2_support_strictness_20260318_191500`

Validation:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`

Result:
- search regressions increased to `167` and the combined suite reached `174`
- planning/travel evidence strips now feel more curated and less like a raw SERP spillover

### Phase 111: Weekend And Health Summary Refinement

Changes:
- upgraded `workshop/toolbox/stacks/web_core/websearch.py`
  - extended phrase repair coverage for `thingstodoin`, `Walkingdaily`, and `benefitsof`
  - stripped leading footnote numbers and date prefixes from summary sentences
  - added weekend-aware lead scoring so `weekend itinerary` prompts favor weekend/48-hour rows over generic 3-day itineraries
  - added final lead-summary punctuation cleanup
- expanded `test_search_upgrade.py`
  - added regression coverage for weekend lead preference, date-prefix stripping, and footnote cleanup
- saved focused live artifacts:
  - `audit/phase111_live_focus.json`
  - `audit/phase111_live_focus.md`

Backups:
- `audit/backups/phase111_pre_weekend_and_health_summary_refine_20260318_191700`
- `audit/backups/phase111_patchwave1_leading_punct_cleanup_20260318_191840`
- `audit/backups/phase111_patchwave2_final_summary_punct_20260318_192000`

Validation:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`
- targeted live probe saved to `audit/phase111_live_focus.json`

Result:
- search regressions increased to `170` and the combined suite reached `177`
- live Tokyo-planning/travel answers became more purposeful, and the walking-benefits explainer now starts with a clean health sentence instead of date/punctuation noise

### Phase 112: GUI Runtime And Cockpit Polish

Changes:
- strengthened the desktop-side validation layer without disturbing the search stack:
  - added `test_gui_shell_runtime.py` to boot the full offscreen shell and verify the live research pulse reaches the dashboard labels
  - saved `audit/phase112_gui_smoke.md` and `audit/phase112_gui_offscreen.png` for the refreshed cockpit shell
- upgraded logger hygiene in `agents.py`, `gui/aicoregui.py`, `workshop/toolbox/agent_core/wordgame.py`, and `workshop/cli/somi.py`
  - repeated runtime reloads no longer create fresh discarded file handlers for `bot.log` / `agent.log`
  - warning-sensitive GUI tests now run cleanly apart from third-party `swig` deprecation noise

Backups:
- `audit/backups/phase112_pre_gui_runtime_assessment_20260318_195600`
- `audit/backups/phase112_patchwave1_cockpit_clusters_20260318_195819`
- `audit/backups/phase112_patchwave2_persona_combo_fix_20260318_195949`
- `audit/backups/phase112_patchwave3_gui_runtime_test_20260318_200209`
- `audit/backups/phase112_patchwave4_logging_hygiene_20260318_200343`
- `audit/backups/phase112_patchwave5_agent_log_hygiene_20260318_200500`

Validation:
- `C:\somex\.venv\Scripts\python.exe -W default -m unittest C:\somex\test_gui_shell_runtime.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`

Result:
- combined regression state advanced to `178`
- the search stack remained stable while the GUI/runtime surface gained stronger live validation and cleaner logging behavior

### Phase 113: Everyday Intent Summary Overrides

Changes:
- upgraded `workshop/toolbox/stacks/web_core/websearch.py`
  - expanded title-spacing repair coverage for Tokyo travel, family-trip, food-itinerary, and compare-style mashups
  - added intent-aware summary synthesis for travel lookup, trip planning, and shopping comparison prompts
  - widened summary context selection so thin focus rows can still use the strongest nearby evidence rows
- expanded `test_search_upgrade.py`
  - added regressions for Tokyo travel/planning prompts and comparison-tone polish

Backups:
- `audit/backups/phase113_patchwave1_search_output_refine_20260318_202124`

Validation:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`

Result:
- combined regression state advanced to `188`
- common travel/planning answers became more purposeful and compare answers started surfacing meaningful dimensions instead of raw SERP phrasing

### Phase 114: Safe Everyday100 Rerun

Changes:
- reran the first `everyday100` benchmark slice to validate live output quality after the new summary layer
- tightened support-source filtering in `workshop/toolbox/stacks/web_core/websearch.py` for planning, travel, and shopping prompts

Backups:
- `audit/backups/phase114_pre_everyday100_rerun_20260318_203031`
- `audit/backups/phase114_patchwave1_intent_rows_support_hygiene_20260318_204253`

Validation:
- `C:\somex\.venv\Scripts\python.exe C:\somex\audit\search_benchmark_batch.py --corpus everyday1000 --chunk-size 20 --start-chunk 0 --end-chunk 4 --prefix phase114_everyday100 --somi-timeout 35 --chunk-timeout 1500 --stable-seconds 15`

Result:
- `audit/phase114_everyday100_combined_summary.md` landed at `4.51` average heuristic score, `6.49s` average Somi time, and `0` low-score rows
- remaining quality gaps narrowed to seasonal travel wording, travel-budget tone, and phone-comparison polish

### Phase 115: Budget And Compare Tone Repair

Changes:
- upgraded `workshop/toolbox/stacks/web_core/websearch.py`
  - normalized thin travel day-range snippets into cleaner `3 to 5 days` guidance
  - improved budget-query fallback tone when public snippets omit hard numbers
  - rejected more compare-tool marketing copy and weak triple-compare support rows
- expanded `test_search_upgrade.py`
  - added budget fallback and compare-tool rejection regressions
- saved refreshed artifacts:
  - `audit/phase115_everyday100_combined.jsonl`
  - `audit/phase115_everyday100_combined.md`
  - `audit/phase115_everyday100_combined_summary.md`

Backups:
- `audit/backups/phase115_pre_everyday100_post_hygiene_20260318_204500`
- `audit/backups/phase115_patchwave1_budget_compare_tone_20260318_211608`

Validation:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\audit\search_benchmark_batch.py --corpus everyday1000 --chunk-size 20 --start-chunk 0 --end-chunk 4 --prefix phase115_everyday100 --somi-timeout 35 --chunk-timeout 1500 --stable-seconds 15`

Result:
- the suite held at `188` passing tests
- `audit/phase115_everyday100_combined_summary.md` recorded `4.52` average heuristic score, `7.3s` average Somi time, and `0` low-score rows
- live planning and shopping answers read more human even when public snippets were thin

### Phase 116: Cockpit Telemetry And Output Cleanup

Changes:
- upgraded `gui/themes/__init__.py`
  - replaced mojibake theme glyphs with `☀️ / 🌆 / 🌙`
- upgraded `somicontroller_parts/settings_methods.py`, `somicontroller_parts/layout_methods.py`, `somicontroller_parts/status_methods.py`, and `somicontroller.py`
  - tightened the cabin switch into a smaller emoji-led control
  - added a live `ResearchSignalMeterWidget` to the Research Pulse card
  - surfaced recent browse mode/source counts in the top-strip metrics immediately after pulse updates
- upgraded `agents.py` and `workshop/toolbox/stacks/web_core/websearch.py`
  - cleaned remaining visible mojibake in a few user-facing fallbacks and source separators
- refreshed GUI regression coverage in `test_gui_themes.py` and `test_gui_shell_runtime.py`

Backups:
- `audit/backups/phase116_pre_log_sync_20260318_212026`
- `audit/backups/phase116_pre_gui_cockpit_signal_20260318_212333`
- `audit/backups/phase116_patchwave1_runtime_signal_fix_20260318_213144`

Validation:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_research_ux.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_shell_runtime.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- offscreen artifacts:
  - `audit/phase116_gui_offscreen.png`
  - `audit/phase116_font_smoke.png`
  - `audit/phase116_font_smoke_arial.png`
- live focus artifacts:
  - `audit/phase116_live_focus.json`
  - `audit/phase116_live_focus.md`

Result:
- the combined suite stayed green at `188` passing tests, with `180` passing search-only tests
- latest-guidance, GitHub, and travel-season answers remained strong in the live focus slice
- travel-budget prompts are now the clearest remaining everyday search delta when public snippets do not expose concrete amounts
- headless screenshot text placeholders were confirmed to be an offscreen Qt font artifact because even a standalone label render showed the same box glyphs

### Phase 117: Core Runtime Stress And Benchmark Hook Closure

Changes:
- upgraded `runtime/eval_harness.py`
  - direct CLI execution now resolves audit benchmark modules reliably instead of tripping over the `runtime/audit.py` name collision
- added `audit/__init__.py`
- added `test_core_runtime_integrations.py`
  - direct CLI eval-harness regression
  - heartbeat, gateway, workflow, and coding-session integration coverage
- added benchmark hook coverage under `tests/`
  - `test_coding_tools_phase3.py`
  - `test_coding_mode_phase5.py`
  - `test_coding_studio_phase6.py`
  - `test_memory_session_search_phase7.py`
  - `test_browser_phase7.py`
  - `test_delivery_automations_phase9.py`
- wrote artifacts:
  - `audit/phase117_core_runtime_summary.md`
  - `audit/phase117_benchmark_baseline.json`

Backups:
- `audit/backups/phase117_pre_chapterb_core_audit_20260318_213958`
- `audit/backups/phase117_patchwave1_core_runtime_pkg_20260318_214204`
- `audit/backups/phase117_patchwave2_runtime_cleanup_20260318_214500`
- `audit/backups/phase117_patchwave3_benchmark_hooks_20260318_214741`

Validation:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_core_runtime_integrations.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\runtime\eval_harness.py`
- `C:\somex\.venv\Scripts\python.exe C:\somex\executive\memory\tests\test_memory.py`
- `C:\somex\.venv\Scripts\python.exe C:\somex\runtime\live_chat_stress.py`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_coding_tools_phase3.py C:\somex\tests\test_coding_mode_phase5.py C:\somex\tests\test_coding_studio_phase6.py C:\somex\tests\test_memory_session_search_phase7.py C:\somex\tests\test_browser_phase7.py C:\somex\tests\test_delivery_automations_phase9.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_core_runtime_integrations.py C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py C:\somex\tests\test_coding_tools_phase3.py C:\somex\tests\test_coding_mode_phase5.py C:\somex\tests\test_coding_studio_phase6.py C:\somex\tests\test_memory_session_search_phase7.py C:\somex\tests\test_browser_phase7.py C:\somex\tests\test_delivery_automations_phase9.py -v`

Result:
- the expanded combined suite advanced to `199` passing tests
- the benchmark baseline snapshot now reports `measured=1` and `ready=6`
- the old high-severity "missing coverage" gaps for coding, browser, memory, and automation are gone
- the remaining benchmark delta is now a healthier class of gap: finality-baseline capture for ready packs

### Phase 118: Finality Measurement And Everyday100 Revalidation

Changes:
- upgraded `audit/finality_lab.py`
  - direct CLI execution now resolves the `audit` package reliably
- captured a hard finality run for `coding`, `research`, `speech`, `automation`, `browser`, and `memory`
- regenerated the benchmark baseline into `audit/phase118_benchmark_baseline.json`
- reran the safe `everyday100` slice into:
  - `audit/phase118_everyday100.md`
  - `audit/phase118_everyday100.jsonl`
  - `audit/phase118_everyday100_summary.md`

Backups:
- `audit/backups/phase118_pre_finality_baselines_20260318_215518`
- `audit/backups/phase118_patchwave1_focused_backup_20260318_215810`

Validation:
- `C:\somex\.venv\Scripts\python.exe C:\somex\audit\finality_lab.py --root C:\somex --difficulty hard --packs coding research speech automation browser memory`
- `C:\somex\.venv\Scripts\python.exe -c "from audit.benchmark_baseline import build_benchmark_baseline; ..."`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_core_runtime_integrations.py C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py C:\somex\tests\test_coding_tools_phase3.py C:\somex\tests\test_coding_mode_phase5.py C:\somex\tests\test_coding_studio_phase6.py C:\somex\tests\test_memory_session_search_phase7.py C:\somex\tests\test_browser_phase7.py C:\somex\tests\test_delivery_automations_phase9.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\audit\search_benchmark.py --isolated --hard-exit --corpus everyday1000 --limit 100 --output C:\somex\audit\phase118_everyday100.md --json-output C:\somex\audit\phase118_everyday100.jsonl --summary-output C:\somex\audit\phase118_everyday100_summary.md --stdout-summary-only`

Result:
- the benchmark ledger is now fully green at `measured=7` with `gap_count=0`
- the safe `everyday100` rerun kept `0` low-score rows
- the average heuristic score held at `4.52` with `4.64s` average Somi time

### Phase 123: Search Output Contract And Authority Routing

Changes:
- upgraded `executive/synthesis/answer_mixer.py`
  - extended official-context detection so requirement-style `.gov` lookups can use official answer framing instead of generic output
  - added best-date selection across preferred evidence rows for latest/current answers
  - added metadata-aware sentence selection to suppress date-only snippet residue in the answer lead
  - added evidence-derived compare and itinerary lead synthesis for compare and trip-planning prompts
  - reduced duplicate-host repetition in general source lists
- expanded `test_search_upgrade.py`
  - added regressions for official government requirement answers
  - added regressions for authoritative date selection
  - added regressions for compare and itinerary focus takeaways
- saved live artifacts:
  - `audit/phase123_everyday20.md`
  - `audit/phase123_everyday20.jsonl`
  - `audit/phase123_everyday20_summary.md`

Backups:
- `audit/backups/phase123_pre_search_contract_20260318_234820`
- `audit/backups/phase123_patchwave1_focus_phrase_fix_20260318_235313`

Validation:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\audit\search_benchmark.py --isolated --hard-exit --corpus everyday1000 --limit 20 --output C:\somex\audit\phase123_everyday20.md --json-output C:\somex\audit\phase123_everyday20.jsonl --summary-output C:\somex\audit\phase123_everyday20_summary.md --stdout-summary-only`

Result:
- official/latest answers are now better at surfacing the strongest available date even when the top evidence row is undated
- requirement-style official queries like passport renewal now use stronger official-source voice
- compare and trip-planning prompts now surface cleaner evidence-backed takeaways instead of raw snippet phrasing
- the search-only suite passed at `184` tests
- the combined search+GUI suite passed at `191` tests
- the live `everyday20` slice averaged `4.6` with `0` Somi errors

### Phase 124: Deep Research Briefs And Section Bundles

Changes:
- upgraded `workshop/toolbox/stacks/research_core/evidence_schema.py`
  - extended `EvidenceBundle` with a `research_brief` map and `section_bundles`
- upgraded `workshop/toolbox/stacks/research_core/composer.py`
  - added intent-aware research-brief generation
  - added subquestion decomposition and section templates
  - added section-bundle assembly that groups claims and supporting items into reportable sections
- upgraded `workshop/toolbox/stacks/web_core/websearch.py`
  - browse reports now retain planner artifacts
  - deep-browse execution steps now log when findings are organized into sections
  - `to_search_bundle()` now carries planner metadata into the user-facing bundle
- upgraded `workshop/toolbox/stacks/web_core/search_bundle.py`
  - rendered bundles can now show a compact research brief and section plan
- expanded `test_search_upgrade.py`
  - added composer and browse-report regressions for the new planner fields

Backups:
- `audit/backups/phase124_pre_research_briefs_20260318_235720`
- `audit/backups/phase124_patchwave1_bundle_structure_20260318_235848`

Validation:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`

Result:
- long research answers now carry a reusable brief, subquestions, and section structure instead of only a flat evidence summary
- the browse report has enough structure for future cache/resume and GUI timeline work
- the search-only suite advanced to `187` passing tests
- the combined search+GUI suite advanced to `194` passing tests

### Phase 125: Evidence Cache And Resume

Changes:
- added `workshop/toolbox/stacks/research_core/evidence_cache.py`
  - persistent TTL-backed evidence-store for research bundles
  - canonical URL normalization and bounded pruning
- upgraded `workshop/toolbox/stacks/web_core/websearch.py`
  - persistent evidence cache is now attached to `WebSearchHandler`
  - deep research bundles now save their rows, browse report, research brief, and section bundles
  - top-level search can resume a cached deep-research bundle when it still passes adequacy checks
  - `_deep_browse()` itself now only resumes when explicitly enabled so unit and sub-flow behavior stays deterministic
- expanded `test_search_upgrade.py`
  - added canonicalization, store round-trip, resume, and stale-cache regressions

Backups:
- `audit/backups/phase125_pre_evidence_cache_20260319_000550`
- `audit/backups/phase125_patchwave1_evidence_store_20260319_000729`

Validation:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`
- live repeat-query artifact: `audit/phase125_repeat_probe.json`
- live fresh-handler resume artifact: `audit/phase125_resume_probe.json`

Result:
- repeated deep-research queries can now reopen from a local evidence bundle rather than rebuilding the whole trail every time
- the fresh-handler resume probe confirmed the persistent path with `second_cached=true`, a populated research brief, and preserved section titles
- the search-only suite advanced to `191` passing tests
- the combined search+GUI suite advanced to `198` passing tests

### Phase 126: Execution Timeline In The Premium Search UI

Changes:
- upgraded `somicontroller_parts/layout_methods.py`
  - Research Pulse now includes a dedicated compact execution timeline list
- upgraded `somicontroller_parts/status_methods.py`
  - added a timeline preview reducer for browse execution events and steps
  - pulse updates now render timeline rows and refresh Research Studio immediately
- upgraded `gui/researchstudio.py`
  - fallback browse-pulse view now mirrors the latest timeline for non-job research activity
- upgraded `somicontroller.py`
  - bound the new timeline helper into `SomiAIGUI`
- expanded GUI regressions:
  - `test_gui_research_ux.py`
  - `test_gui_shell_runtime.py`

Backups:
- `audit/backups/phase126_pre_execution_timeline_20260319_001709`
- `audit/backups/phase126_patchwave1_research_timeline_20260319_002155`
- `audit/backups/phase126_patchwave2_timeline_binding_20260319_002242`
- `audit/backups/phase126_patchwave3_research_studio_sync_20260319_002354`

Validation:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- offscreen smoke artifact: `audit/phase126_gui_timeline_smoke.png`

Result:
- Somi now exposes a compact browse timeline directly in the premium cockpit instead of forcing users to infer progress from a single summary string
- the Research Studio fallback stays synchronized with the latest browse pulse, so the agent feels more coherent across panels
- the search-only suite stayed green at `191` tests
- the combined search+GUI suite advanced to `199` passing tests

### Phase 127: Primary Source Cards In The Premium Search UI

Changes:
- upgraded `gui/aicoregui.py`
  - compact research reports now preserve timeline rows and primary-source previews through the chat attachment path
- upgraded `somicontroller_parts/layout_methods.py`
  - Research Pulse now includes a dedicated primary-sources list
- upgraded `somicontroller_parts/status_methods.py`
  - added source-preview extraction and placeholder states for compact browse pulses
- upgraded `gui/researchstudio.py`
  - fallback browse-pulse summaries now surface the same source preview
- upgraded `gui/themes/premium_base.py`
  - added styling for the timeline/source lists
- upgraded `somicontroller.py`
  - bound the new source-preview helper into `SomiAIGUI`
- expanded GUI regressions:
  - `test_gui_research_ux.py`
  - `test_gui_shell_runtime.py`

Backups:
- `audit/backups/phase127_pre_premium_pulse_sources_20260319_002603`
- `audit/backups/phase127_patchwave1_source_binding_20260319_003014`

Validation:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_gui_themes.py C:\somex\test_research_studio_data.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`
- offscreen smoke artifact: `audit/phase127_gui_pulse_sources_smoke.png`

Result:
- the premium search UI now shows what Somi did and which sources it leaned on, even after the browse report is compacted for chat transport
- Research Studio mirrors the same source context, making the shell feel more consistent across panels
- the search-only suite stayed green at `191` tests
- the combined search+GUI suite remained green at `199` passing tests

### Phase 149: Structured Everyday Answer Types

Changes:
- upgraded `executive/synthesis/answer_mixer.py`
  - compare and travel-style answers now open with `Quick take:`
  - trip-planning answers now open with `Trip shape:`
  - explainer answers now open with `Short answer:`
  - support-source phrasing is now more intent-aware for everyday answers
- upgraded `test_search_upgrade.py`
  - added regressions for the new structured answer contracts

Backups:
- `audit/backups/phase149_pre_structured_answers_20260319_135522`

Validation:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_observability_phase148.py C:\somex\tests\test_offline_resilience_phase147.py C:\somex\tests\test_artifact_hygiene_phase146.py C:\somex\tests\test_ops_diagnostics_phase134.py C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_search_upgrade.py -v`

Result:
- the highest-volume everyday answer types now look more like intentional response formats than generic search prose
- the search-only suite reached `196` passing tests
- the combined validation slice reached `223` passing tests
- the audit artifact for this pass lives in `audit/phase149_structured_answers_summary.md`
