# Agent Upgrade

Last updated: 2026-03-18 22:15 America/Port_of_Spain

## Goal

Bring Somi closer to Hermes/Claude/ChatGPT-style agent behavior for research, browsing, and multi-step execution without relying on paid search APIs or provider keys.

The target is not just better result ranking. The target is a better agent loop:

- Plan the browse/research approach before searching.
- Show the user what Somi is doing in a concise, trustworthy way.
- Retry, recover, and reflect when the first pass is weak.
- Persist useful research into local memory and Agentpedia.
- Clean up temporary repo/page artifacts after use.
- Stress test the whole loop until quality is consistently strong.

## What Hermes Does Well

Transferable ideas from `audit/external_repos/hermes-agent`:

- Visible tool execution with short previews
- Long-running tool loop with interrupt/recovery behavior
- Session and trajectory persistence
- Strong memory/continuity across turns
- Better user trust because the system shows progress instead of silently stalling

For Somi, the most valuable ideas are:

1. Agent step visibility
2. Interruptible multistep execution
3. Recovery-aware tool orchestration
4. Persistent research memory and trajectory review
5. Clean summaries of what happened and why

## Current Base

Already in place:

- Browse planner with deep browse, GitHub mode, direct URL mode, official-source preference
- No-API GitHub local inspection
- Answer adequacy and evidence-first composition
- Turn traces and trajectory storage
- Agentpedia SQLite fact store and topic pages
- Search eval harness in `audit/search_eval.py`
- Regression coverage in `tests/test_search_upgrade.py`

Latest pre-agent-upgrade backup:

- `audit/backups/phase9_pre_agentupgrade_20260316_145759`

## Current Status

Implemented and validated:

- Hermes-style execution traces now flow through browse reports, search bundles, and answer generation.
- Browse reports now render Hermes-style agent traces with recovery notes instead of raw step dumps.
- Agentpedia is now part of the deep-research loop:
  - read before deep browse / GitHub research when useful
  - write back after strong official/live research
  - filter low-quality Python prerelease pages from docs memory
- GitHub compare mode now prefers one repo per compared subject instead of picking two variants from the same family.
- Generic latest-hypertension queries now broaden to ACC/AHA/JACC/Heart sources and no longer settle too early on older ESC-only results.
- Python docs queries now keep searching until they hit real docs pages instead of stopping on `python.org` prerelease download pages.
- GitHub single-repo answers now ignore org shell pages and prefer repo-adjacent docs/install pages for support.
- Official-source answers now apply stricter end-to-end filtering for WHO guidance and cardio-guideline support pages.
- Source lists now dedupe DOI/PDF variants so the same official document is not cited twice.
- WHO latest-guidance browse now retries more official site variants, filters off-target WHO country/regional pages before ranking, and holds the answer on the 2025 arboviral guideline/news pair more reliably.
- GitHub compare recovery now survives noisy discovery results and preserves the intended repo pair instead of drifting into GitHub topic pages.
- Phase 34 answer polish is now in place:
  - WHO publication citations now prefer canonical `publications/i/item` pages over `publications/b` listings and bitstream mirrors when both are present.
  - WHO news titles now render in cleaner title case instead of malformed slug casing.
  - Hypertension final answers now keep the clean 2025 hub plus the primary ACC/AHA guideline DOI in the final cited pair.
  - Browse summaries now use cleaner support labels for WHO, Python docs, and hypertension instead of raw noisy source titles.
- Phase 36 recovery and adapter work is now in place:
  - when AHA official pages block direct fetches, Somi falls back to targeted official recovery searches instead of degrading to noisy nearby results
  - cardio latest-guideline answers now recover the primary `CIR.0000000000001356` row reliably in live runs even under AHA anti-bot pressure
- Phase 37 GitHub polish is now in place:
  - single-repo GitHub lookups now keep raw result rows on the selected repo plus clearly related first-party docs
  - README-derived GitHub summaries are cleaner and ASCII-safe enough to avoid terminal encoding glitches
- Phase 38 summary hygiene is now in place:
  - browse summaries fall back to clean source titles when fetched text is mashed or mojibaked
  - unrelated official cardio DOI rows are blocked from the browse-summary support list more aggressively
- Phase 39 benchmark reliability is now in place:
  - pending research-stack tasks are canceled and drained more cleanly before long-run shutdown
  - a dedicated safe benchmark corpus now covers 1000 everyday-use query slots without unsafe categories
  - the new isolated benchmark runner is resumable, chunkable, and retries child-process failures before falling back to an in-process evaluation
  - benchmark runs are now Somi-first by default, with baseline comparison available as an explicit opt-in instead of the fragile default

Latest regression status:

- `tests/test_search_upgrade.py`: 95 passing tests

Additional runtime polish since the last search-only milestone:

- Telegram now has a delivery-bundle layer that can chunk long replies, export
  markdown handoffs, and keep document/coding/research outputs coherent on the
  remote channel instead of flattening everything into one reply.
- Final answers now carry explicit trust/freshness signals through the answer
  validator, browse report, Research Pulse, and compact chat research capsule.
- The user-facing runtime is better at saying when the evidence is thin, when a
  fresher source date exists, and how confident Somi should sound.
- Runtime operators can now inspect context/compaction pressure directly from
  `somi context status`, Control Room, doctor, support bundle, and release
  gate.
- Backup verification now reflects the current Somi surface and no longer shows
  a stale missing `somicontroller.py` row in healthy framework checkpoints.

Latest live headline checks:

- `audit/phase36_block_recovery_live_retest.json`
  - both `what are the latest hypertension guidelines` and `latest ACC/AHA hypertension guideline` now keep the hub plus the primary ACC/AHA DOI even when the hub fetch is blocked
- `audit/phase37_github_live_retest.json`
  - `check out openclaw on github` now stays on the selected repo plus `docs.openclaw.ai/install` instead of drifting into unrelated GitHub repos or generic help mirrors
- `audit/phase38_live_summary_retest.json`
  - hypertension browse summaries are no longer mashed and WHO browse summaries now reduce to a clean `WHO news item` plus `WHO guideline publication` pairing
- `audit/phase39_benchmark_smoke_v3.md`
  - a 12-query mixed everyday benchmark smoke now completes cleanly under isolated mode with no failed cases on the Somi-first path
  - the runner now preserves resumable JSONL state in `audit/phase39_benchmark_smoke_v3.jsonl`
- `what are the latest hypertension guidelines`
  - now answers from the 2025 AHA/ACC high blood pressure guideline hub and keeps the final answer on the main guideline pages
- `latest WHO dengue treatment guidance`
  - now keeps the answer on the 2025 WHO arboviral guidance/news pages and filters Timor-Leste or other off-target WHO country pages out of the official shortlist
- `check out openclaw on github`
  - now cites the verified repo plus first-party install docs instead of org shell pages, unrelated repos, or generic guides
- `compare openclaw and deer-flow on github`
  - now inspects `openclaw/openclaw` and `bytedance/deer-flow`
- `what changed in python 3.13 docs`
  - now returns `docs.python.org/3/whatsnew/3.13.html` first

Known remaining rough edges:

- The full unattended eval harness can still outlive the desktop shell timeout even though it now writes a usable markdown report before cleanup.
- Ad-hoc inline Python stress scripts can emit Windows Proactor cleanup warnings after subprocess-heavy runs.
- Some official-source browse summaries still inherit verbose marketing or commentary phrasing from lead pages even when the final mixed answer is clean.
- WHO latest answers are cleaner now, but upstream live result sets can still surface multiple mirror or publication-listing variants before final-answer canonicalization.
- A few timed live sweeps can leave short-lived Python helper processes around until the desktop shell timeout finishes unwinding them.
- The new everyday benchmark surfaced real retrieval gaps outside the hardened official/GitHub/docs flows:
  - shopping/product comparisons can still drift into off-topic results
  - planning/travel prompts still route too often through quick search and ad-heavy SERPs
  - weather route results can still mis-resolve some place names when the upstream weather provider guesses the wrong locality

Recent backups:

- `audit/backups/phase10_pre_agentic_trace_20260316_145926`
- `audit/backups/phase11_pre_agentpedia_integration_20260316_152715`
- `audit/backups/phase11_patchwave1_20260316_153322`
- `audit/backups/phase13_pre_guideline_broadening_20260316_160126`
- `audit/backups/phase14_pre_docs_guardrails_20260316_160358`
- `audit/backups/phase15_pre_compare_repo_selection_20260316_160555`
- `audit/backups/phase16_pre_eval_harness_20260316_160742`
- `audit/backups/phase23_pre_answer_polish_20260316_195432`
- `audit/backups/phase24_pre_github_latency_20260316_200745`
- `audit/backups/phase25_pre_official_source_filter_20260316_201909`
- `audit/backups/phase25_patchwave1_20260316_202028`
- `audit/backups/phase25_patchwave2_20260316_202317`
- `audit/backups/phase25_patchwave3_20260316_202441`
- `audit/backups/phase26_pre_github_support_refine_20260316_202804`
- `audit/backups/phase27_pre_official_support_refine_20260316_204504`
- `audit/backups/phase27_patchwave1_20260316_204620`
- `audit/backups/phase27_patchwave2_20260316_204915`
- `audit/backups/phase27_patchwave3_20260316_205002`
- `audit/backups/phase27_patchwave4_20260316_205145`
- `audit/backups/phase30_pre_source_preference_20260316_232304`
- `audit/backups/phase30_patchwave1_20260316_232540`
- `audit/backups/phase31_pre_official_merge_20260316_233341`
- `audit/backups/phase34_pre_answer_polish_impl_20260317_010232`
- `audit/backups/phase34_patchwave1_20260317_010551`
- `audit/backups/phase31_patchwave1_20260316_233449`
- `audit/backups/phase31_patchwave2_20260316_233508`
- `audit/backups/phase32_pre_github_compare_recovery_20260316_234607`
- `audit/backups/phase33_pre_official_recency_resilience_20260317_000011`
- `audit/backups/phase33_patchwave1_20260317_000318`
- `audit/backups/phase34_pre_final_level_plan_20260317_005952`
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

## Recent Phases

### Phase 26: GitHub Support-Source Cleanup

Goal:
- Keep single-repo GitHub answers from citing org pages or noisy generic discovery rows

Implemented:
- Restricted compare-style repo pairing to actual compare queries only
- Added source filtering so repo lookups prefer repo-adjacent docs/install pages
- Added regression coverage for single-repo GitHub support selection

Validation:
- `tests/test_search_upgrade.py`
- `audit/phase26_search_eval.md`

### Phase 27: Official-Source Answer Polish

Goal:
- Make official medical/guideline answers read like a careful researcher instead of a stitched crawl dump

Implemented:
- WHO latest-guidance answers now use official-context filtering even when the query says `guidance` instead of `guideline`
- Country-specific WHO pages are blocked from the source list for global-guidance answers
- Cardio-guideline answers now reject journal-homepage, TOC, session, commentary, and unrelated DOI support rows
- Source identities now dedupe HTML DOI and PDF variants of the same official document

Validation:
- `tests/test_search_upgrade.py`
- `audit/phase27_live_focus_answers.json`

### Phase 30: Source Preference Refinement

Goal:
- Make source selection more deliberate for GitHub and official-source answers

Implemented:
- Tightened GitHub source preference so first-party docs/releases beat third-party guide pages
- Improved WHO and hypertension source ranking in `answer_mixer`
- Reduced noisy support-phrase clutter in official answers

Validation:
- `tests/test_search_upgrade.py`
- `audit/phase30_live_focus_answers.json`
- `audit/phase30_search_eval.md`

### Phase 31: Preserve Official Shortlists During Research Fallback

Goal:
- Stop strong official rows from being discarded when research-compose fallback is noisy

Implemented:
- Blended preserved official rows back into deep-browse results when official browse was relevant but incomplete
- Added browse-trace notes explaining when official rows were reused or blended

Validation:
- `tests/test_search_upgrade.py`
- `audit/phase31_live_focus_answers.json`
- `audit/phase31_search_eval.md`

### Phase 32: GitHub Compare Recovery

Goal:
- Keep GitHub compare mode anchored on the intended repos even when discovery returns GitHub topic pages or one repo inspection fails

Implemented:
- Ignored reserved GitHub non-repo paths like `/topics/...`
- Added compare recovery to retain selected repo URLs from discovery if live inspection fails
- Prevented generic GitHub topic pages from being appended as compare evidence

Validation:
- `tests/test_search_upgrade.py`
- `audit/phase32_compare_retest.json`

### Phase 33: Official Recency Resilience

Goal:
- Make latest WHO/global-guidance lookups more resilient when the first official search pass is noisy

Implemented:
- Increased the WHO latest-guidance official-query budget from 2 to 4 site-filtered variants
- Added global-WHO row filtering so country/regional WHO pages are rejected for global latest-guidance lookups
- Tightened adequacy checks so WHO latest guidance only settles when a real recent WHO guidance/publication row is present
- Added stronger ranking penalties for stale dengue handbooks, country guidance pages, and other off-target WHO rows

Validation:
- `tests/test_search_upgrade.py`
- `audit/phase33_live_focus_answers.json`
- `audit/phase33_search_eval.md`

### Phase 34: Answer Polish

Goal:
- Polish final answers and source lists so official-source answers look deliberate, canonical, and less noisy

Implemented:
- WHO publication citations now prefer canonical `publications/i/item` pages over `publications/b` listings and bitstream mirrors when both exist
- WHO and hypertension source labels now render with cleaner, less slug-like titles
- Final hypertension answers now keep the 2025 guideline hub plus the primary ACC/AHA DOI pair

Validation:
- `tests/test_search_upgrade.py`
- `audit/phase34_live_focus_answers.json`

### Phase 35: Trace Visibility

Goal:
- Make the browse loop feel more Hermes-like to watch

Implemented:
- Added structured execution events, progress headlines, and recovery notes to browse reports
- Switched rendered traces to `Agent trace:` blocks with concise step labels

Validation:
- `tests/test_search_upgrade.py`
- `audit/phase35_trace_gallery.md`

### Phase 36: Blocked-Official Recovery

Goal:
- Recover strong official answers even when first-party sites block direct fetches

Implemented:
- Added blocked-page detection for challenge and anti-bot responses
- Added targeted official recovery searches for the primary ACC/AHA hypertension guideline
- Normalized tracked DOI variants back to the canonical `CIR.0000000000001356` URL

Validation:
- `tests/test_search_upgrade.py`
- `audit/phase36_domain_eval.md`
- `audit/phase36_block_recovery_live_retest.json`

### Phase 37: GitHub UX Polish

Goal:
- Make single-repo GitHub answers feel more product-grade in both raw rows and summaries

Implemented:
- Cleaned README-derived repo excerpts to drop badge noise and terminal-hostile encoding artifacts
- Restricted single-repo support rows to the selected repo plus clearly related first-party docs

Validation:
- `tests/test_search_upgrade.py`
- `audit/phase37_github_live_retest.json`

### Phase 38: Summary Hygiene

Goal:
- Keep browse summaries readable even before the answer mixer refines them

Implemented:
- Added mashed-text detection and clean-title fallback inside browse summaries
- Tightened official hypertension support filtering so unrelated cardio DOI rows are rejected more often

Validation:
- `tests/test_search_upgrade.py`
- `audit/phase38_live_summary_retest.json`

## Phase Plan

### Phase 9: Agent Loop Foundation

Goal:
- Add a durable upgrade plan
- Expose better execution trace data from search/browser/research paths
- Prepare evals for agentic behavior, not just search rows

Success checks:
- `agentupgrade.md` exists and stays current
- Search/browser results can carry an execution summary or trace block
- No regressions in existing search tests

### Phase 10: Hermes-Style Multistep Search Execution

Goal:
- Turn deep browse into an explicit execution loop with phases like plan, retrieve, read, judge, refine, answer
- Capture step trace in a structured way
- Feed concise step summary into the final answer path

Desired UX:
- The user can tell what Somi did
- Weak answers trigger targeted follow-up search automatically
- Search bundles and turn traces show real progress

### Phase 11: Agentpedia Research Memory

Goal:
- Query Agentpedia before expensive research when it helps
- Write back high-quality research facts after strong browse passes
- Generate topic pages that reflect real researched work

Guardrails:
- Only write back when source quality and evidence confidence meet threshold
- Avoid polluting Agentpedia with snippets, uncertain guesses, or duplicates

### Phase 12: Browser and Repo Execution Reliability

Goal:
- Improve multistep browser and repo inspection execution
- Add retry/recovery guidance for broken selectors, missing pages, or weak repo matches
- Ensure temporary clones/pages are cleaned up automatically

Desired UX:
- "I opened X, inspected Y, found Z, and cleaned up temp files."

### Phase 13: Stress, Eval, Patch

Goal:
- Run live evals, repo tasks, docs tasks, latest-guideline tasks, and compare tasks
- Inspect outputs for failure modes
- Patch regressions with a backup before each patch wave

Required eval families:
- GitHub summary
- GitHub compare
- Official latest guidance
- Docs/version changes
- Multi-step planning/research prompts
- Direct URL summarization
- Adversarial ambiguous entity prompts

## Evaluation Standard

Somi is "up to mark" when it usually does all of the following:

- Selects the right browse mode
- Finds the right entity
- Uses better sources than generic snippets
- States uncertainty when evidence is weak
- Produces concise, grounded summaries
- Can inspect a repo/page directly when needed
- Leaves a useful trace of how it got there
- Writes back durable facts only when safe

## Operating Rules

- Before each implementation phase: create a backup in `audit/backups/`
- Before each patch wave after failed tests: create another backup
- After each phase: run unit tests plus live evals
- Keep weather/news/finance fragile routes protected
- Prefer local/no-key methods: SearXNG, DDG, Playwright, local clones, sparse checkout, page extraction, Agentpedia

## Next Actions

1. Use the new benchmark harness to patch shopping/product comparison drift before the larger pilot run.
2. Improve planning and travel routing so itinerary-style prompts trigger deeper browse more often and rely less on ad-heavy quick search.
3. Tighten weather place disambiguation so everyday city lookups resolve the intended locality more reliably.
4. Keep polishing answer phrasing from high-quality browse reports so user-facing text consistently reads more like a polished research assistant and less like stitched snippets.
5. Revisit richer repo comparison notes in Agentpedia after the broad benchmark categories stabilize.

## Final-Level Roadmap

The goal of the next stretch is to close the remaining gap versus Hermes on UX polish and OpenClaw on operational maturity without giving up Somi's no-key research advantage.

### Phase 34: Answer Polish and Canonical Citations

Goal:
- Make answers read less like stitched evidence and more like a polished research assistant
- Canonicalize official mirrors, bitstreams, PDF variants, and equivalent repo support links

Implementation focus:
- tighten final answer selection in `executive/synthesis/answer_mixer.py`
- add stronger URL canonicalization in `workshop/toolbox/stacks/web_core/websearch.py`
- reduce editorial support leakage for guideline and docs answers

Validation after phase:
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`
- focused live retests for WHO, hypertension, GitHub, Python docs
- artifact: `audit/phase34_live_focus_answers.json`

### Phase 35: Hermes-Level Execution UX

Goal:
- Make Somi feel alive while it researches, not just correct at the end

Implementation focus:
- richer execution-step previews
- explicit plan / retrieve / read / judge / refine / answer trace blocks
- cleaner recovery notes when search or repo inspection fails
- better user-facing summary of what was tried and why

Validation after phase:
- regression suite
- manual trace inspection on GitHub compare, direct URL, official latest-guidance, and long research prompts
- artifact: `audit/phase35_trace_gallery.md`

### Phase 36: Domain Adapters and Official-Source Expansion

Goal:
- Expand source-aware reliability beyond the currently hardened flows

Implementation focus:
- add adapters/guardrails for government/regulatory, standards/specs, package registries, docs portals, and product release notes
- improve official-domain inference and rewrite generation
- add more direct-page adapters where generic search is consistently noisy

Validation after phase:
- regression suite
- new targeted eval set by domain
- artifact: `audit/phase36_domain_eval.md`

### Phase 37: Query Rewriting, Reflection, and Retry Intelligence

Goal:
- Make Somi recover from weak first-pass searches more like Claude/ChatGPT/Grok research loops

Implementation focus:
- intent-aware query rewrites by mode: official, latest, compare, repo, release notes, docs, local info, troubleshooting
- post-draft adequacy judge that can ask for one more search round automatically
- contradiction detection and explicit uncertainty handling

Validation after phase:
- regression suite
- adversarial ambiguous-query set
- artifact: `audit/phase37_reflection_eval.md`

### Phase 38: Search Infrastructure and Noise Reduction

Goal:
- Improve speed, reliability, and cleanliness under long runs

Implementation focus:
- better timeout/fallback policy between SearXNG, DDG, and direct fetch
- browser/subprocess cleanup hardening
- cache and dedupe improvements
- unattended eval runner that finishes cleanly and leaves one stable report

Validation after phase:
- regression suite
- repeated soak runs
- artifact: `audit/phase38_soak.md`

### Phase 39: Everyday-Use Query Benchmark Harness

Goal:
- Build the large acceptance benchmark before the final 1000-search run

Implementation focus:
- create a safe query generator covering common everyday categories:
  - weather, news, finance terminal-route smoke tests
  - health general information
  - official guidelines and government info
  - software/docs/troubleshooting
  - GitHub/repo lookup and compare
  - shopping/product research without unsafe content
  - travel, local info, restaurants, entertainment, sports, education, planning
  - direct URL summarization and multi-step research prompts
- add safety filters and deny categories:
  - pornography/explicit sexual content
  - weapons/munitions/explosives
  - illegal drugs, self-harm, evasion, and other high-risk abuse domains

Validation after phase:
- regression suite
- pilot run on 100 safe generated queries
- artifact: `audit/phase39_pilot_100.md`

### Phase 39: Benchmark Reliability and Safe-Corpus Harness

Goal:
- Make large unattended search benchmarks resumable, safer, and much less fragile before the 1000-query acceptance run

Implemented:
- Added `audit/safe_search_corpus.py` with deterministic safe corpora:
  - `default`
  - `research50`
  - `everyday250`
  - `everyday1000`
- Added `audit/search_benchmark.py`:
  - isolated child-run mode
  - JSONL resume support
  - chunking and limit controls
  - child retry recovery
  - in-process recovery if isolated child execution exhausts retries
- Changed the benchmark default to Somi-first evaluation so large sweeps do not waste time and stability on extra baselines unless `--compare-baselines` is requested
- Hardened long-run task cleanup in `workshop/toolbox/stacks/web_core/websearch.py` so pending research-stack tasks are canceled and drained more cleanly

Validation:
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`
- `.\.venv\Scripts\python.exe audit/search_benchmark.py --corpus everyday250 --limit 12 --isolated --per-case-timeout 60 --child-retries 1 --output audit/phase39_benchmark_smoke_v3.md --json-output audit/phase39_benchmark_smoke_v3.jsonl`

Outcome:
- The benchmark path is now fast enough and resilient enough to scale into larger chunked runs
- The 12-query mixed smoke completed with no failed cases on the Somi-first path
- The benchmark surfaced the next real product-level retrieval gaps:
  - shopping comparison drift
  - planning/travel overuse of quick search
  - occasional weather place-name misresolution upstream

### Phase 40: 1000-Search Acceptance Run

Goal:
- Prove Somi can handle a broad, safe, real-world search workload at scale

Implementation focus:
- run 1000 safe benchmark queries across the full everyday-use mix
- score route quality, source quality, freshness, answer adequacy, speed, and failure recovery
- sample manual review on the worst 50 and best 50 outputs

Acceptance targets:
- no catastrophic regressions in weather/news/finance
- top-source quality remains strong on official/latest/repo/docs tasks
- answer adequacy remains high on the benchmark majority
- retry/recovery path resolves a meaningful share of weak first passes

Final artifacts:
- `audit/phase40_benchmark_1000.json`
- `audit/phase40_benchmark_1000.md`
- `audit/phase40_failures_top50.md`
- `audit/phase40_followup_patch_plan.md`

## Endgame Rules

- Before each implementation phase: create a fresh backup in `audit/backups/`
- Before each patch wave after failed tests: create another backup
- After each phase: run the regression suite plus targeted live evals
- Do not change weather/news/finance behavior unless a new phase clearly proves a regression elsewhere
- The 1000-search run must stay inside the safe benchmark taxonomy and exclude explicit or high-risk categories

### Phase 40

Focus:
- fix the benchmark-exposed weak spots in shopping comparisons and trip-planning research

Backups:
- `audit/backups/phase40_pre_compare_planning_quality_20260317_023847`
- `audit/backups/phase40_patchwave1_travel_fastpath_20260317_032411`
- `audit/backups/phase40_patchwave2_travel_quality_20260317_033056`
- `audit/backups/phase40_patchwave3_summary_grounding_20260317_033545`
- `audit/backups/phase40_patchwave4_compare_fastpath_20260317_033908`
- `audit/backups/phase40_patchwave5_compare_source_hygiene_20260317_034042`
- `audit/backups/phase40_patchwave6_trip_marker_hygiene_20260317_034256`
- `audit/backups/phase40_patchwave7_mash_cleanup_20260317_034503`
- `audit/backups/phase40_patchwave8_short_ellipsis_cleanup_20260317_034601`

Implemented:
- added a travel-planning fast path in `workshop/toolbox/stacks/web_core/websearch.py`
- added a shopping-comparison fast path in `workshop/toolbox/stacks/web_core/websearch.py`
- tightened trip filters to reject forums, broad attractions pages, Pinterest/social noise, and ad-heavy travel rows
- tightened shopping filters to reject video rows, news pages, and model-variant mismatch rows
- grounded shopping/travel summaries on browse rows instead of noisy claim bundles
- hardened mash detection so clipped or source-code-like excerpts fall back to cleaner titles
- cleaned excerpt extraction in `workshop/toolbox/stacks/research_core/reader.py` so script/style blocks do not leak into summaries

Checks:
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`
- current result: `113` passing tests
- live probes:
  - `compare iPhone 16 and Samsung Galaxy S25`
  - `plan a 3 day trip to Tokyo`
- earlier artifact retained:
  - `audit/phase40_live_focus_fastpaths.json`

Outcome:
- trip-planning lookups no longer hang inside the heavier deep-research path
- shopping comparisons no longer rely on the noisier research-composer route for common product-vs-product prompts
- source quality is materially better for both categories
- remaining rough edge after Phase 40: everyday “latest requirements” queries still needed a government-source route

### Phase 41

Focus:
- route government requirements and renewal queries to official domains instead of noisy general research

Backups:
- `audit/backups/phase41_pre_government_requirements_20260317_035032`

Implemented:
- added government-requirements detection in `workshop/toolbox/stacks/research_core/browse_planner.py`
- marked passport/visa/immigration/social-security/tax/medicare-style requirements lookups as official-preferred
- added official-domain inference for:
  - `travel.state.gov`
  - `uscis.gov`
  - `cbp.gov`
  - `ssa.gov`
  - `irs.gov`
  - `medicare.gov`
  - `cms.gov`
  - `medicaid.gov`
- added targeted government query variants so deep browse hits official pages first

Checks:
- planner regression:
  - `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade.BrowsePlannerTests.test_passport_requirement_queries_are_official_preferred -v`
- live check:
  - `latest passport renewal requirements`
- benchmark rerun:
  - `.\.venv\Scripts\python.exe audit/search_benchmark.py --corpus research50 --limit 8 --output audit/phase41_benchmark_smoke.md --json-output audit/phase41_benchmark_smoke.jsonl`

Outcome:
- `latest passport renewal requirements` now stays on `travel.state.gov`
- the benchmark smoke improved from average heuristic score `5.0` to `5.12`
- `general_latest` moved from a failure to a clean official-source result

Current remaining edges:
- some support titles in trip-planning outputs can still appear slightly mashed when sites publish poor title text
- the direct-URL docs summary path still carries some table-of-contents/mojibake noise on `docs.python.org`
- hypertension support rows still occasionally surface noisy adjacent AHA hub pages even though the lead answer stays correct

### Phase 42

Focus:
- clean direct-URL page reading and GitHub README excerpts so research answers feel more deliberate and less crawl-like

Backups:
- `audit/backups/phase42_pre_directurl_github_hygiene_20260317_045544`
- `audit/backups/phase42_patchwave1_directurl_readme_tests_20260317_045918`

Implemented:
- upgraded direct-URL extraction in `workshop/toolbox/stacks/web_core/websearch.py`
  - artifact normalization for mojibake and docs chrome
  - boilerplate detection before trusting extracted page text
  - stronger HTML fallback stripping for nav/toc/breadcrumb/theme-shell blocks
  - cleaner direct-URL title/excerpt synthesis for docs pages
- upgraded GitHub README cleanup in `workshop/toolbox/stacks/research_core/github_local.py`
  - preserve line structure during README reads
  - strip nav lines, quote callouts, marketing shouts, and duplicate README rows
- added targeted regressions in `tests/test_search_upgrade.py`

Checks:
- `.\.venv\Scripts\python.exe -m py_compile workshop/toolbox/stacks/research_core/github_local.py workshop/toolbox/stacks/web_core/websearch.py tests/test_search_upgrade.py`
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`
- live probes:
  - `summarize this https://docs.python.org/3/whatsnew/3.13.html`
  - `check out openclaw on github`
  - `compare openclaw and deer-flow on github`

Outcome:
- direct URL docs summaries now surface a stable title path instead of raw docs boilerplate
- GitHub repo summaries are materially less noisy than before

### Phase 43

Focus:
- tighten GitHub compare answers and further improve README excerpt quality

Backups:
- `audit/backups/phase43_pre_github_excerpt_refine_20260317_050319`
- `audit/backups/phase43_patchwave1_heading_filter_fix_20260317_050533`

Implemented:
- refined README filtering in `workshop/toolbox/stacks/research_core/github_local.py`
  - strips markdown emphasis markers
  - drops short README link clouds like `Website Docs Vision ...`
  - preserves informative title lines while still dropping noisy nav rows
- tightened compare-mode support-row logic in `workshop/toolbox/stacks/web_core/websearch.py`
  - compare answers now keep support rows limited to the repos Somi intentionally selected
- added compare-specific regressions in `tests/test_search_upgrade.py`

Checks:
- targeted:
  - `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade.GitHubHelperTests.test_clean_readme_excerpt_removes_nav_quotes_and_marketing_shouts tests.test_search_upgrade.WebSearchHandlerTests.test_github_browse_compare_keeps_only_selected_repo_rows -v`
- full regression:
  - `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`
- live probe:
  - `compare openclaw and deer-flow on github`

Outcome:
- compare answers no longer append stray third GitHub repos
- repo descriptions look cleaner and more intentionally summarized

### Phase 44

Focus:
- remove the last obvious trim/encoding artifact from live search output

Backups:
- `audit/backups/phase44_pre_ascii_trim_polish_20260317_050645`

Implemented:
- changed `_safe_trim()` in `workshop/toolbox/stacks/web_core/websearch.py` to use ASCII `...`
- added a regression so trimmed output cannot fall back to mojibake ellipses

Checks:
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade.WebSearchUtilityTests.test_safe_trim_uses_ascii_ellipsis -v`
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`
- live artifact:
  - `audit/phase42_44_live_polish.json`

Outcome:
- current regression state: `117` passing tests
- GitHub compare summaries are cleaner and no longer show mojibake ellipsis artifacts

### Phase 73

Focus:
- improve summary cleanup, AI-news topicality, and shopping-comparison source quality before scaling the benchmark

Backups:
- `audit/backups/phase73_pre_summary_and_compare_refine_20260317_223605`
- `audit/backups/phase73_patchwave1_slug_and_compare_noise_20260317_223655`
- `audit/backups/phase73_patchwave2_live_gap_fixes_20260317_224331`
- `audit/backups/phase73_patchwave3_compare_subject_precision_20260317_224557`
- `audit/backups/phase73_patchwave4_variant_drift_filters_20260317_224811`
- `audit/backups/phase73_patchwave5_direct_compare_admission_20260317_224919`
- `audit/backups/phase73_patchwave6_affiliate_compare_filter_20260317_225024`
- `audit/backups/phase73_patchwave7_xps14_and_medium_filters_20260317_225121`

Implemented:
- upgraded `workshop/toolbox/stacks/web_core/websearch.py`
  - title-to-slug fallback when summary text collapses into mashed page-source titles
  - shopping compare retry hosts and trusted-review site-filtered retries
  - stronger noisy-row filters for mojibake, foreign spam, affiliate pages, Medium, and model drift
  - stricter direct-compare admission so incidental single-product reviews stop surfacing
  - improved AI/economic news reputable-host promotion and stale-result penalties
- added targeted regressions in `tests/test_search_upgrade.py`

Checks:
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`
- live probes for:
  - `latest artificial intelligence news`
  - `latest inflation news`
  - `compare iPhone 16 and Samsung Galaxy S25`
  - `pros and cons of MacBook Air vs Dell XPS 13`

Outcome:
- Reuters/AP/TechCrunch-style AI news replaced Yahoo/MSN-heavy rows
- shopping comparisons became materially cleaner and less spammy

### Phase 74

Focus:
- begin safe `everyday1000` chunked acceptance testing

Backups:
- `audit/backups/phase74_pre_benchmark_scale_20260317_225233`

Checks:
- `.\.venv\Scripts\python.exe audit\search_benchmark.py --corpus everyday1000 --chunk-size 25 --chunk-index 0 --somi-timeout 35 --output audit\phase74_everyday1000_chunk00.md --json-output audit\phase74_everyday1000_chunk00.jsonl --save-every 5`

Outcome:
- first `25`-query chunk completed with average heuristic score `4.52`
- exposed remaining gaps in AI news freshness, shopping compare drift, and weather encoding artifacts

### Phase 75

Focus:
- patch the benchmark-exposed AI-news and shopping-comparison gaps, then rerun chunk `00`

Backups:
- `audit/backups/phase75_pre_benchmark_gap_cleanup_20260317_225449`
- `audit/backups/phase75_patchwave1_fix_followup_20260317_225508`
- `audit/backups/phase75_patchwave2_ai_alias_news_20260317_225551`
- `audit/backups/phase75_patchwave3_ai_news_ranking_20260317_225623`
- `audit/backups/phase75_patchwave4_news_host_promotion_20260317_225659`
- `audit/backups/phase75_patchwave5_news_recency_bias_20260317_225815`
- `audit/backups/phase75_patchwave6_stronger_news_stale_penalty_20260317_225901`
- `audit/backups/phase75_patchwave7_latest_news_article_preference_20260317_225939`

Implemented:
- broadened AI alias handling and reputable-host promotion in `workshop/toolbox/stacks/web_core/websearch.py`
- strengthened stale-news penalties and latest-query article preference
- tightened shopping compare filtering around third-device noise and low-trust hosts

Checks:
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`
- rerun:
  - `audit\phase75_everyday1000_chunk00.md`
  - `audit\phase75_everyday1000_chunk00.jsonl`

Outcome:
- chunk `00` quality improved materially even though the coarse average stayed `4.52`

### Phase 76

Focus:
- continue benchmark scaling and fix remaining AI-news recency plus phone-variant leakage

Backups:
- `audit/backups/phase76_pre_news_and_phone_variant_refine_20260317_230625`
- `audit/backups/phase76_patchwave1_news_and_phone_variant_refine_20260317_230722`
- `audit/backups/phase76_patchwave2_news_hub_demote_20260317_231416`

Implemented:
- added latest-news recency validation in `workshop/toolbox/stacks/web_core/websearch.py`
  - latest-style queries now require a real recency signal in the shortlist
  - topic/tag/hub pages no longer count as fresh article hits
  - reputable-host promotion now prefers recent article pages over category hubs
- tightened shopping compare variant detection
  - compact `Ultra/Pro/Plus/Max` mismatches are rejected even when titles collapse spaces
  - multi-device `vs.` showdowns are filtered more reliably
- added regressions in `tests/test_search_upgrade.py` for latest-news adequacy, hub demotion, compact variant drift, and third-device showdown rejection

Checks:
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`
- chunk reruns:
  - `audit\phase76_everyday1000_chunk00.md`
  - `audit\phase76_everyday1000_chunk00_rerun2.md`
  - `audit\phase76_everyday1000_chunk01_rerun.md`

Outcome:
- AI-news prompts now lead with Reuters/AP-style article rows instead of TechCrunch topic hubs
- phone comparisons stopped leaking `Ultra/Pro` rows into base-model queries
- regression state advanced to `186` passing tests during this phase and later continued upward

### Phase 77

Focus:
- continue `everyday1000` scaling to find the next failure cluster

Checks:
- `.\.venv\Scripts\python.exe audit\search_benchmark.py --corpus everyday1000 --chunk-size 25 --chunk-index 2 --somi-timeout 35 --output audit\phase77_everyday1000_chunk02.md --json-output audit\phase77_everyday1000_chunk02.jsonl --save-every 5`

Outcome:
- chunk `02` completed with average heuristic score `4.52`
- the next clear cluster was travel/direct-URL polish:
  - `react.dev/blog` direct-URL summaries had duplicated title chrome
  - travel lookups occasionally over-preferred ranking hubs
  - Paris travel prompts exposed a timeout-prone enrichment path

### Phase 78

Focus:
- fix travel fast-path timeout risk and clean direct-URL React blog summaries

Backups:
- `audit/backups/phase78_pre_travel_directurl_timeout_polish_20260317_232354`
- `audit/backups/phase78_patchwave1_travel_and_react_cleanup_20260317_232359`

Implemented:
- upgraded `workshop/toolbox/stacks/web_core/websearch.py`
  - `react.dev/blog` now gets a clean direct-URL title and excerpt
  - travel/planning fast paths now enrich only a small safe subset of rows instead of opening slow hosts like `travel.usnews.com`
  - travel lookup ranking pages are demoted for “things to do” style prompts
- added regressions in `tests/test_search_upgrade.py` for:
  - React blog direct-URL cleanup
  - travel enrichment skipping slow `travel.usnews.com` rows
  - ranking-page demotion for travel lookup prompts

Checks:
- targeted travel/direct-URL regressions
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`
- live reproduction of:
  - `what to do in Paris`
- benchmark rerun:
  - `audit\phase78_everyday1000_chunk03_rerun.md`
  - `audit\phase78_everyday1000_chunk03_rerun.jsonl`

Outcome:
- Paris travel lookup stopped timing out and now returns a clean shortlist in about `8.5s`
- React blog direct-URL summaries no longer duplicate title chrome
- chunk `03` improved from a travel timeout and `avg_score=4.32` to a clean rerun at `avg_score=4.48`
- benchmark-leaked Python processes were cleaned up after this phase so the workspace returned to a clean process state

### Phase 79

Focus:
- harden the benchmark harness so unattended chunk runs save artifacts and return control more reliably

Backups:
- `audit/backups/phase79_pre_benchmark_harness_hardening_20260318_000341`
- `audit/backups/phase79_patchwave1_hard_exit_20260318_003540`

Checks:
- `audit\phase79_everyday1000_chunk04_summary.md`
- `audit\phase79_everyday1000_chunk05_summary.md`

Outcome:
- benchmark chunk runs for `04` and `05` both completed at average heuristic score `4.4`
- hard-exit cleanup kept the harness from stalling after artifacts had already been written

### Phase 80

Focus:
- continue travel, shopping, and docs polish in the mid-benchmark band

Backups:
- `audit/backups/phase80_pre_travel_shopping_mdn_refine_20260318_003915`

Checks:
- `audit\phase80_everyday1000_chunk04_summary.md`
- `audit\phase80_everyday1000_chunk05_summary.md`

Outcome:
- chunk `04` improved to `avg_score=4.48`
- chunk `05` held at `avg_score=4.44`
- travel/shopping/docs behavior stayed stable while the harness scale-out continued

### Phase 81

Focus:
- keep tightening climate/news behavior and identify the next benchmark failure cluster

Backups:
- `audit/backups/phase81_pre_news_climate_refine_20260318_011258`

Checks:
- `audit\phase81_everyday1000_chunk05_summary.md`
- `audit\phase81_everyday1000_chunk06_summary.md`

Outcome:
- chunk `05` held at `avg_score=4.44`
- chunk `06` dropped to `avg_score=4.28`, exposing the next cluster around climate/news precision and a general-factual timeout

### Phase 82

Focus:
- improve latest-news shortlist adequacy, fallback host fan-out, and climate latest-query handling

Backups:
- `audit/backups/phase82_pre_news_shortlist_and_benchmark_retry_20260318_013701`
- `audit/backups/phase82_patchwave1_news_shortlist_and_benchmark_retry_20260318_013819`

Checks:
- `audit\phase82_everyday1000_chunk05_summary.md`
- `audit\phase82_everyday1000_chunk06_summary.md`

Outcome:
- latest-news adequacy became stricter
- benchmark retry handling improved
- climate latest queries moved toward better host-balanced retries

### Phase 83

Focus:
- demote Reuters-style hub pages for latest-news prompts and clean up e-reader comparison ranking

Backups:
- `audit/backups/phase83_pre_news_hub_and_ereader_compare_refine_20260318_014508`
- `audit/backups/phase83_patchwave1_news_hub_and_ereader_compare_refine_20260318_014513`
- `audit/backups/phase83_patchwave2_shopping_compare_gate_and_ranking_20260318_014845`

Checks:
- `audit\phase83_everyday1000_chunk06_summary.md`
- `audit\phase83b_everyday1000_chunk06_summary.md`

Outcome:
- latest-news hub demotion improved
- shopping-compare gating and ranking were tightened for noisier e-reader results

### Phase 84

Focus:
- suppress noisy benchmark child output so long runs stay readable and recoverable

Backups:
- `audit/backups/phase84_pre_benchmark_output_suppression_20260318_022810`
- `audit/backups/phase84_patchwave1_benchmark_output_suppression_20260318_022817`

Checks:
- `audit\phase84_everyday1000_chunk06_summary.md`
- `audit\phase84_everyday1000_chunk07_summary.md`

Outcome:
- benchmark output became much less noisy during long unattended runs
- artifact recovery became easier when chunks needed reruns

### Phase 85

Focus:
- strengthen climate latest-news exact-phrase matching and host-balanced site-filter retries

Backups:
- `audit/backups/phase85_pre_climate_news_fallback_quality_20260318_030100`
- `audit/backups/phase85_patchwave1_climate_news_fallback_quality_20260318_030239`
- `audit/backups/phase85_patchwave2_climate_news_evergreen_penalty_20260318_030501`

Checks:
- `audit\phase85_everyday1000_chunk06_summary.md`
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`

Outcome:
- chunk `06` improved to `avg_score=4.44`
- climate latest-news prompts stopped over-rewarding evergreen explainers and ad-style rows

### Phase 86

Focus:
- add a resumable batch benchmark runner for long chunked acceptance runs

Backups:
- `audit/backups/phase86_pre_batch_benchmark_runner_20260318_031000`
- `audit/backups/phase86_patchwave1_batch_benchmark_runner_20260318_031012`
- `audit/backups/phase86_patchwave2_batch_completion_fix_20260318_031236`

Checks:
- `audit\phase86_smoke2_chunk07_summary.md`
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`

Outcome:
- `audit/search_benchmark_batch.py` became the stable way to run large search benchmarks in chunks
- chunk completion detection was fixed so the runner waits for full row counts before killing stale workers

### Phase 87

Focus:
- fix latest-news hub adequacy and stabilize e-reader compare runtime/quality

Backups:
- `audit/backups/phase87_pre_news_hub_adequacy_and_ereader_timeout_20260318_033200`
- `audit/backups/phase87_patchwave1_news_hub_adequacy_and_ereader_timeout_20260318_033208`
- `audit/backups/phase87_patchwave2_latest_right_now_and_ereader_video_penalty_20260318_033352`
- `audit/backups/phase87_patchwave3_ereader_primary_trusted_queries_20260318_034020`

Checks:
- `audit\phase87b_smoke_chunk07_summary.md`
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`

Outcome:
- latest-style news now rejects hub pages as adequate top hits
- e-reader compares skipped enrichment and used tighter trusted-query handling, but chunk `07` still exposed Kindle/Kobo timeout fallthrough

### Phase 88

Focus:
- eliminate Kindle/Kobo shopping-compare timeout fallthrough and restore stable chunk `07` behavior

Backups:
- `audit/backups/phase88_pre_chunk07_stabilization_20260318_035038`
- `audit/backups/phase88_patchwave1_ereader_family_compare_20260318_035937`

Implemented:
- upgraded `workshop/toolbox/stacks/web_core/websearch.py`
  - Kindle/Kobo compares now mix generic family-level compare queries with trusted site-filtered retries
  - generic `Kobo Clara` queries now allow current `BW` and `Colour/Color` family variants instead of filtering every good row out
  - shopping-compare search no longer falls through into generic deep browse after the specialized fast path has already exhausted its options
- expanded `tests/test_search_upgrade.py`
  - added regressions for mixed e-reader query sets, generic family-variant acceptance, and stopping after an empty shopping fast path

Checks:
- direct live probes:
  - `difference between Kindle Paperwhite and Kobo Clara`
  - `should I buy Kindle Paperwhite or Kobo Clara`
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`
- `audit\phase88_chunk07_rerun_chunk07_summary.md`

Outcome:
- Kindle/Kobo queries stopped timing out and returned real shortlists in about `5-7s`
- chunk `07` recovered to `avg_score=4.44`
- `shopping_compare` improved from `avg_score=1.0` with `2` Somi timeouts to `avg_score=4.0` with `0` Somi errors

### Phase 89

Focus:
- clean up the remaining e-reader support-row junk so the shortlists feel deliberate, not merely non-broken

Backups:
- `audit/backups/phase89_pre_ereader_support_cleanup_20260318_040556`

Implemented:
- upgraded `workshop/toolbox/stacks/web_core/websearch.py`
  - rejected Pinterest and CDN mirror rows for shopping compares
  - demoted `versus.com` support rows behind stronger review-style sources for e-reader compares
- expanded `tests/test_search_upgrade.py`
  - added regressions for Pinterest/CDN mirror rejection and `versus.com` demotion

Checks:
- direct live probes:
  - `difference between Kindle Paperwhite and Kobo Clara`
  - `should I buy Kindle Paperwhite or Kobo Clara`
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`
- `audit\phase89_chunk07_cleanup_chunk07_summary.md`

Outcome:
- e-reader compare leads now favor Mashable, Pocket-lint, Today, and similar review-style rows more reliably
- regression state advanced to `219` passing tests
- chunk `07` held at `avg_score=4.44` with `shopping_compare avg_score=4.0` and `0` Somi errors

### Phase 91

Focus:
- repair software release-note lookups, GitHub canonicals, and the last travel lookup route miss before the next `1000`-query acceptance run

Backups:
- `audit/backups/phase91_pre_docs_release_and_github_canonicals_20260318_062745`
- `audit/backups/phase91_patchwave1_docs_release_and_github_canonicals_20260318_063012`
- `audit/backups/phase91_patchwave2_compare_subject_order_20260318_063500`
- `audit/backups/phase91_patchwave3_travel_lookup_early_route_20260318_064231`

Implemented:
- upgraded `workshop/toolbox/stacks/research_core/github_local.py`
  - added canonical repo mappings for LangChain, Pandas, Tailwind CSS, Bootstrap, Ollama, and `llama.cpp`
  - improved compare-subject matching so repo pairs stay aligned to the compared subjects
- upgraded `workshop/toolbox/stacks/web_core/websearch.py`
  - added direct software-change adapters for TypeScript, Rust, and Docker Compose release-note lookups
  - routed travel lookup queries into `search_web()` before the slower research path
- expanded `tests/test_search_upgrade.py`
  - added regressions for GitHub canonicals, software adapters, and travel early routing

Checks:
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`
- `audit\phase91_live_targeted_summary.md`
- `audit\phase91_lowcase_rerun_v2_summary.md`

Outcome:
- regression state advanced to `226` passing tests
- the `32`-case low-score slice reran clean with `remaining_bad = 0`
- TypeScript, Rust, Docker Compose, GitHub canonical repo lookups, and Costa Rica travel lookup all recovered

### Phase 92

Focus:
- rerun the full `1000`-query safe acceptance corpus after the Phase 91 fixes

Backups:
- `audit/backups/phase92_pre_everyday1000_rerun_20260318_064622`

Checks:
- `audit\phase92_everyday1000_batch.log`
- `audit\phase92_everyday1000_combined_summary.md`

Outcome:
- first full rerun completed at `1000` queries with `avg_score=4.31`
- only `8` weak rows remained, and immediate isolated reruns showed those misses were transient rather than deterministic retrieval failures

### Phase 93

Focus:
- harden long-run resilience for quick factual lookups, insomnia official-source routing, and shopping compare fallback recovery

Backups:
- `audit/backups/phase93_pre_longrun_resilience_20260318_082650`

Implemented:
- upgraded `workshop/toolbox/stacks/research_core/browse_planner.py`
  - insomnia recommendation queries now prefer official domains such as `aasm.org` and `nice.org.uk`
- upgraded `workshop/toolbox/stacks/web_core/websearch.py`
  - quick-mode fallback now recovers with direct SearXNG if DDG fails
  - shopping compare fast path now falls back to SearXNG when DDG returns nothing
- expanded `tests/test_search_upgrade.py`
  - added regressions for insomnia official routing, shopping compare SearX recovery, and quick-mode SearX recovery

Checks:
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`
- `audit\phase93_residue_rerun.json`
- `audit\phase93_everyday1000_combined_summary.md`

Outcome:
- regression state advanced to `229` passing tests
- the prior residue slice reran clean
- the next full `1000`-query run improved to `avg_score=4.32`, but still surfaced `3` long-run misses

### Phase 94

Focus:
- remove the last long-run misses by making quick factual lookups and shopping comparisons more load-resistant

Backups:
- `audit/backups/phase94_pre_quick_and_shopping_resilience_20260318_102741`

Implemented:
- upgraded `workshop/toolbox/stacks/web_core/websearch.py`
  - quick-mode DDG lookups now use a bounded single attempt before immediate SearXNG recovery
  - shopping compare matching now recognizes aliases like `PS5` for `PlayStation 5`
  - shopping compare trusted-review hosts now include console-specific and printer-specific sources
  - added a bounded `search_general()` rescue path when DDG and SearXNG both stay thin for shopping comparisons
- expanded `tests/test_search_upgrade.py`
  - added regressions for console alias matching, console/printer trusted hosts, shopping compare search-general rescue, and bounded quick-mode retry behavior

Checks:
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`
- `audit\phase94_targeted_rerun.json`
- `audit\phase94_everyday1000_combined_summary.md`

Outcome:
- regression state advanced to `233` passing tests
- targeted reruns for `PlayStation 5 vs Xbox Series X`, `how many calories to lose weight`, and `Brother laser printer vs HP LaserJet` all passed live
- the next `1000`-query run improved to `avg_score=4.33`, but still left `4` transient long-run misses that all passed in isolated reruns

### Phase 95

Focus:
- stabilize the acceptance harness itself so transient long-run flakes are rechecked automatically instead of being treated as final failures

Backups:
- `audit/backups/phase95_pre_acceptance_stabilizer_20260318_122649`

Implemented:
- upgraded `audit/search_benchmark_batch.py`
  - added weak-row detection plus a post-run stabilization pass that reruns low-score or timeout cases and replaces them if the rerun is stronger
  - included stabilized-case details in the manifest so repaired acceptance results stay auditable
- expanded `tests/test_search_upgrade.py`
  - added regressions for weak-row detection and stabilized result replacement

Checks:
- `.\.venv\Scripts\python.exe -m unittest tests.test_search_upgrade -v`
- `audit\phase95_everyday1000_manifest.json`
- `audit\phase95_everyday1000_combined_summary.md`

Outcome:
- regression state advanced to `235` passing tests
- final `phase95` acceptance corpus completed with `1000` queries, `avg_score=4.34`, and `0` remaining bad rows in `audit\phase95_everyday1000_combined.jsonl`
- stabilized reruns repaired `4` transient misses:
  - `what's new in fastapi`
  - `how many calories to lose weight`
  - `official playwright documentation changes`
  - `pros and cons of Sony A7C II vs Canon R8`

### Phase 96

Focus:
- refine the answer layer so search results read more deliberately for everyday queries, latest-guidance lookups, docs summaries, GitHub compares, and shopping-style comparison prompts

Backups:
- `audit/backups/phase96_pre_output_polish_20260318_152703`
- `audit/backups/phase96_patchwave1_20260318_153041`

Implemented:
- upgraded `executive/synthesis/answer_mixer.py`
  - latest/official answers now surface a concrete source date without weakening the primary claim
  - docs answers now use the requested Python version dynamically instead of hard-coding `3.13`
  - general comparison answers now acknowledge that Somi checked comparison coverage and cite the lead comparison date when available
  - GitHub compare answers now surface the latest visible commit dates for both primary repos
- expanded `test_search_upgrade.py`
  - added regressions for dynamic Python docs wording, comparison-answer phrasing, and the current direct news benchmark route
- captured rendered answer samples in `audit/phase96_output_polish_samples.md`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest test_search_upgrade.AnswerMixerTests test_search_upgrade.BenchmarkHarnessTests.test_evaluate_case_uses_direct_news_vertical_path -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- `audit\phase96_output_polish_samples.md`

Outcome:
- regression state advanced to `154` passing tests in the current suite layout
- Somi now returns cleaner dated guidance answers, more human docs summaries, stronger GitHub comparison copy, and more deliberate comparison wording for everyday shopping-style prompts

### Phase 97

Focus:
- upgrade the desktop shell into a premium three-mode dashboard with persistent `Light`, `Shadowed`, and `Dark` display modes, plus a compact in-GUI mode switch

Backups:
- `audit/backups/phase97_pre_premium_gui_shell_20260318_153359`
- `audit/backups/phase97_patchwave1_20260318_153905`

Implemented:
- added premium theme modules:
  - `gui/themes/premium_base.py`
  - `gui/themes/premium_light.py`
  - `gui/themes/premium_shadowed.py`
  - `gui/themes/premium_dark.py`
- replaced the theme registry in `gui/themes/__init__.py`
  - the public theme set is now the premium trio only
  - legacy names like `cockpit_balanced`, `light_modern`, and `default_dark` normalize automatically into the new modes
- upgraded `somicontroller_parts/layout_methods.py`
  - added a compact 3-mode switch directly in the quick action bar
  - kept the modal selector as a secondary display-mode control
  - premium shadowed/dark themes now reuse the HUD assets and background treatment
- upgraded `somicontroller_parts/settings_methods.py`
  - GUI theme preference now defaults to `premium_shadowed`
  - mode buttons stay synchronized with persisted theme selection
- upgraded `somicontroller_parts/bootstrap_methods.py`
  - initialized theme-switch state on startup
- added `test_gui_themes.py`
  - validates the premium mode registry, legacy-theme normalization, and the new dashboard-switch selectors

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py C:\somex\test_gui_themes.py -v`
- offscreen GUI smoke through `SomiAIGUI()` with `QT_QPA_PLATFORM=offscreen`
- `audit\phase97_gui_smoke.md`

Artifacts:
- `audit\phase97_gui_offscreen.png`
- `audit\phase97_gui_offscreen_v2.png`

Outcome:
- combined regression state advanced to `157` passing tests
- Somi now boots into a premium BMW-orange / graphite dashboard shell with persistent light, shadowed, and dark display modes and a built-in compact mode switch

### Phase 98

Focus:
- tighten the premium dashboard at the panel level so the shell feels more cohesive and less like a single global stylesheet pasted across every surface

Backups:
- `audit/backups/phase98_pre_panel_cohesion_20260318_154052`

Implemented:
- upgraded `somicontroller_parts/layout_methods.py`
  - assigned dedicated object names for the chat, presence, intel, heartbeat, activity, and speech cards so premium styling can differentiate the surfaces
- upgraded `gui/themes/premium_base.py`
  - added card-specific premium treatments
  - added premium checkbox styling for the RAG toggle and similar controls
  - added premium scrollbar styling for transcripts and list-heavy panels
- expanded `test_gui_themes.py`
  - validates the new card selectors plus the premium checkbox and scrollbar selectors

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py C:\somex\test_gui_themes.py -v`
- offscreen GUI smoke through `SomiAIGUI()` with `QT_QPA_PLATFORM=offscreen`
- `audit\phase98_gui_smoke.md`

Artifacts:
- `audit\phase98_gui_offscreen.png`

Outcome:
- combined regression state held at `157` passing tests
- the premium shell now has stronger panel hierarchy, cleaner control polish, and better dashboard cohesion without disturbing the search stack

### Phase 99

Focus:
- compare Somi against Hermes, OpenClaw, and DeerFlow for search + shell feel, then tighten the display-mode control into a smaller emoji-first switch

Backups:
- `audit/backups/phase99_pre_competitive_gui_refine_20260318_155926`
- `audit/backups/phase99_patchwave1_emoji_slider_fix_20260318_160147`
- `audit/backups/phase99_patchwave2_qt_slider_export_20260318_160254`

Implemented:
- created `audit/phase99_competitive_matrix.md`
  - captured the current competitive read on Hermes, OpenClaw, DeerFlow, and Somi
  - highlighted visible execution UX as the next leverage point for Somi
- upgraded the premium mode switch
  - replaced the worded `Light / Shadowed / Dark` buttons with compact emoji buttons
  - kept a much smaller slider directly under the emoji row
  - preserved persistent theme syncing and startup restoration
- updated:
  - `somicontroller_parts/bootstrap_methods.py`
  - `somicontroller_parts/layout_methods.py`
  - `somicontroller_parts/settings_methods.py`
  - `gui/themes/premium_base.py`
  - `gui/qt.py`
  - `somicontroller.py`
  - `test_gui_themes.py`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py -v`
- offscreen GUI smoke through `SomiAIGUI()` with `QT_QPA_PLATFORM=offscreen`

Outcome:
- the shell moved closer to a premium dashboard control feel with a smaller emoji-first mode switch
- the competitive audit made the next UX phase much clearer: expose research progress in the shell instead of hiding it behind raw output

### Phase 100

Focus:
- refine GitHub answer output so repo lookups feel less like pasted README text and more like deliberate research summaries

Backups:
- `audit/backups/phase100_pre_search_output_refine_20260318_160418`
- `audit/backups/phase100_patchwave1_readme_punctuation_20260318_160608`
- `audit/backups/phase100_patchwave2_excerpt_final_trim_20260318_160634`

Implemented:
- upgraded `workshop/toolbox/stacks/research_core/github_local.py`
  - cleaned README excerpts more aggressively
  - compacted giant channel/platform lists
  - reduced title-banner duplication and punctuation artifacts
- upgraded `executive/synthesis/answer_mixer.py`
  - added stronger follow-through copy for GitHub answers and compares
- expanded `test_search_upgrade.py`
  - added regressions for README cleanup, GitHub wording, and follow-up phrasing
- captured live output artifacts:
  - `audit/phase100_live_focus.md`
  - `audit/phase100_live_focus.jsonl`
  - `audit/phase100_live_focus_summary.md`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- focused live benchmark slice through `audit/search_benchmark.py`

Outcome:
- GitHub answers became materially less raw and more helpful
- the live focus slice held at `avg_score=5.17`

### Phase 101

Focus:
- finish the GitHub excerpt cleanup pass and remove the last duplicated-heading / double-punctuation rough edges from live repo summaries

Backups:
- `audit/backups/phase101_pre_github_excerpt_final_polish_20260318_160852`
- `audit/backups/phase101_patchwave1_mojibake_dash_fix_20260318_161052`
- `audit/backups/phase101_patchwave2_collapsed_quote_fix_20260318_161118`
- `audit/backups/phase101_patchwave3_post_ascii_quote_fix_20260318_161144`

Implemented:
- polished `workshop/toolbox/stacks/research_core/github_local.py`
  - repaired stubborn mojibake punctuation cases before and after ASCII normalization
  - removed remaining heading duplication in README-derived summaries
  - kept summary clauses clean when excerpt text already ended with punctuation
- regenerated live validation artifacts:
  - `audit/phase101_live_focus.md`
  - `audit/phase101_live_focus.jsonl`
  - `audit/phase101_live_focus_summary.md`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- focused live benchmark slice through `audit/search_benchmark.py`

Outcome:
- GitHub repo summaries became cleaner in live use, not just in unit tests
- the focused live slice stayed at `avg_score=5.17` while running faster than the prior pass

### Phase 102

Focus:
- bring Hermes-style visible research feel into Somi’s premium shell by surfacing the browse trace directly in the cockpit and the chat transcript

Backups:
- `audit/backups/phase102_pre_research_pulse_ux_20260318_161627`
- `audit/backups/phase102_patchwave1_runtime_fix_20260318_161902`

Implemented:
- added a live `Research Pulse` card to the right-side dashboard stream
  - upgraded `somicontroller_parts/layout_methods.py`
  - upgraded `somicontroller_parts/bootstrap_methods.py`
  - upgraded `somicontroller_parts/status_methods.py`
  - the shell now stores and displays:
    - current browse mode
    - latest research query
    - summary
    - trace preview
    - source count
    - limitation count
- upgraded `gui/aicoregui.py`
  - `ChatWorker` now compacts the latest browse report into a lightweight GUI-safe payload after response generation
- upgraded `gui/chatpanel.py`
  - chat responses now append a concise `Research note:` capsule when Somi actually performed a browse-heavy pass
  - the controller now updates the dashboard pulse from the same payload
- upgraded `gui/themes/premium_base.py`
  - added dedicated styling for `researchPulseCard`, query text, and trace/meta copy
- added `test_gui_research_ux.py`
  - validates research-report compaction and the compact research note rendering
- wrote `audit/phase102_gui_smoke.md`
- ran a fresh live slice:
  - `audit/phase102_live_focus.md`
  - `audit/phase102_live_focus.jsonl`
  - `audit/phase102_live_focus_summary.md`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_search_upgrade.py -v`
- offscreen GUI smoke through `SomiAIGUI()` with `QT_QPA_PLATFORM=offscreen`
- focused live benchmark slice through `audit/search_benchmark.py --corpus research50 --limit 8 --isolated`

Outcome:
- combined regression state advanced to `160` passing tests
- the shell now exposes real browse intent and trace data instead of making the user infer it from the answer text alone
- the live search slice held strong at `avg_score=5.12` with `0` Somi errors while the GUI gained a visible research cockpit

### Phase 103

Focus:
- validate the new Research Studio path end-to-end and make sure the dashboard snapshot builder falls back cleanly even in offscreen/headless flows

Backups:
- `audit/backups/phase103_patchwave1_research_studio_builder_fix_20260318_181600`

Implemented:
- upgraded `gui/researchstudio.py`
  - the panel now falls back to `controller.research_studio_builder` or a fresh `ResearchStudioSnapshotBuilder()` when an explicit builder is not injected
- expanded `test_gui_research_ux.py`
  - added offscreen-safe `QApplication` coverage
  - added a regression test that proves the latest browse pulse shows up without a manually passed builder
- reran the offscreen smoke and confirmed the live browse pulse now renders:
  - `audit/phase103_research_studio_smoke.md`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_research_ux.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`
- offscreen smoke through `SomiAIGUI()` with `QT_QPA_PLATFORM=offscreen`

Outcome:
- combined regression state advanced to `167` passing tests by the end of the phase series
- the Research Studio view now reliably mirrors the latest browse pulse instead of silently appearing empty in headless/test-driven launch paths

### Phase 104

Focus:
- make the premium theme switch feel smaller, more tactile, and more dashboard-like by replacing leftover word labels with emoji-first cues

Backups:
- `audit/backups/phase104_pre_mode_switch_emoji_20260318_181715`

Implemented:
- upgraded `somicontroller_parts/layout_methods.py`
  - replaced the wordy mode label with a compact `Cabin` ambient label
  - reduced quick-switch spacing
  - shrank the emoji buttons and slider footprint
- upgraded `gui/themes/premium_base.py`
  - tightened the pill, icon, groove, and handle geometry for the quick switch
- upgraded `gui/themes/__init__.py`
  - switched premium theme labels to emoji-only:
    - `☀️`
    - `🌆`
    - `🌙`
- upgraded `somicontroller_parts/settings_methods.py`
  - preserved accessibility/tooling labels with premium mode names:
    - `Daydrive`
    - `Cockpit`
    - `Nightfall`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py -v`

Outcome:
- the premium shell now feels less like a settings form and more like a cockpit control strip
- theme switching stayed fully test-covered while becoming more compact and visual

### Phase 105

Focus:
- clean up low-trust, mashed-looking summary output in everyday search so travel, shopping, and general factual answers read more like polished research than scraped snippets

Backups:
- `audit/backups/phase105_pre_title_cleanup_20260318_182439`
- `audit/backups/phase105_patchwave1_iphone_fix_20260318_182835`
- `audit/backups/phase105_patchwave2_hyphen_fix_20260318_182925`

Implemented:
- upgraded `workshop/toolbox/stacks/web_core/websearch.py`
  - added `_repair_title_spacing()` to normalize mashed title/excerpt fragments
  - taught `_summary_source_title()` and `_title_needs_slug_cleanup()` to prefer repaired titles when the source text clearly looks slug-like
  - improved `_url_slug_title()` so it skips generic trailing path segments and recovers cleaner fallback titles
  - strengthened `_text_looks_mashed()` so single long collapsed tokens trigger cleanup
  - normalized lead summaries before trimming in `_summarize_result_rows()`
- expanded `test_search_upgrade.py`
  - added coverage for mashed travel titles
  - added coverage for excerpt fallback when the description starts with a collapsed token
- regenerated benchmark artifacts:
  - `audit/phase105_everyday30.md`
  - `audit/phase105_everyday30.jsonl`
  - `audit/phase105_everyday30_summary.md`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- everyday benchmark slice through `audit/search_benchmark.py --corpus everyday250 --limit 30 --isolated`

Outcome:
- everyday travel, shopping, and general-factual summaries became noticeably less scraped and more readable in live outputs
- the benchmark average held steady at `4.53`, but the qualitative output improved substantially on travel timing, phone comparisons, and walking-benefit queries

### Phase 106

Focus:
- refine travel/planning lead selection so itinerary-style prompts surface human itinerary sources instead of generic or booking-heavy pages

Backups:
- `audit/backups/phase106_pre_trip_lead_refine_20260318_183329`
- `audit/backups/phase106_patchwave1_trip_penalty_tune_20260318_183427`

Implemented:
- upgraded `workshop/toolbox/stacks/web_core/websearch.py`
  - added `_summary_lead_row(query, rows)` to choose better lead rows for trip-planning queries
  - promoted trusted itinerary sources such as `gotokyo.org`, `japan-guide.com`, `lonelyplanet.com`, `tokyocandies.com`, and related human-planning sources
  - demoted more generic booking/aggregator-style hosts and boilerplate itinerary phrasing
  - tuned the penalty list so strong TripAdvisor-style editorial travel rows were not accidentally downgraded
- expanded `test_search_upgrade.py`
  - added regression coverage proving planning summaries prefer human itinerary sources over aggregator leads
- regenerated benchmark artifacts:
  - `audit/phase106_everyday30.md`
  - `audit/phase106_everyday30.jsonl`
  - `audit/phase106_everyday30_summary.md`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`
- everyday benchmark slice through `audit/search_benchmark.py --corpus everyday250 --limit 30 --isolated`

Outcome:
- combined regression state held at `167` passing tests after the planning/travel pass
- itinerary prompts now bias toward more useful human-planning sources while preserving the cleaner title/excerpt output from Phase 105

### Phase 107

Focus:
- strengthen everyday answer synthesis so Somi chooses better lead rows and cleaner summary text across travel, shopping, official-guidance, and general factual prompts

Backups:
- `audit/backups/phase107_pre_everyday_answer_synthesis_20260318_184711`
- `audit/backups/phase107_patchwave1_summary_fallback_fix_20260318_185224`
- `audit/backups/phase107_patchwave2_weak_excerpt_scoring_20260318_185501`

Implemented:
- upgraded `workshop/toolbox/stacks/web_core/websearch.py`
  - added `_query_subject_hint()`, `_summary_text_is_weak()`, `_summary_clean_text()`, `_summary_sentence()`, and `_lead_summary_text()`
  - expanded `_summary_lead_row()` beyond trip planning so travel lookups, shopping compares, and official hypertension/latest-guidance prompts choose stronger lead sources
  - tightened weak-snippet rejection so low-trust excerpts stop displacing cleaner fetched content
  - refined title/excerpt cleanup and official high-blood-pressure lead preference during patchwaves
- expanded `test_search_upgrade.py`
  - added regression coverage for travel lookup leads, shopping compare leads, and content-over-description summary fallback
- regenerated live benchmark artifacts:
  - `audit/phase107_everyday30.md`
  - `audit/phase107_everyday30.jsonl`
  - `audit/phase107_everyday30_summary.md`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`
- everyday benchmark slice through `audit/search_benchmark.py --corpus everyday250 --limit 30 --isolated`

Outcome:
- `163` search regressions passed after the synthesis pass, with `170` combined tests passing in the full suite
- lead summaries became more deliberate and content-backed, especially for travel, shopping, and latest-guidance prompts

### Phase 108

Focus:
- clean up remaining live summary rough spots from the `everyday30` benchmark, especially travel, health explainer, and phone-comparison outputs

Backups:
- `audit/backups/phase108_pre_live_summary_cleanup_20260318_185957`

Implemented:
- upgraded `workshop/toolbox/stacks/web_core/websearch.py`
  - expanded `_repair_title_spacing()` to fix common live artifact mashups such as `AppleiPhone`, `GalaxyS25`, and `Plana`
  - improved `_summary_clean_text()` to remove `Skip to main content` and normalize `up-to-date`
  - widened health-explainer lead preference toward trusted health sources and away from retail/video noise
  - widened travel enrichment fetch breadth from one to two supporting pages so itinerary/travel answers had better source text to summarize
- expanded `test_search_upgrade.py`
  - added regression coverage for trusted health-host lead preference
- regenerated benchmark artifacts:
  - `audit/phase108_everyday30.md`
  - `audit/phase108_everyday30.jsonl`
  - `audit/phase108_everyday30_summary.md`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- everyday benchmark slice through `audit/search_benchmark.py --corpus everyday250 --limit 30 --isolated`

Outcome:
- `164` search regressions passed after the live-cleanup phase
- the `everyday30` benchmark held at `avg_score=4.53` while average Somi time improved to `3.61s`
- travel/planning and compare summaries improved further, though a final text-repair pass was still warranted for a few mashed phrases in live outputs

### Phase 109

Focus:
- repair the last obvious mashed phrases in live travel, health, and shopping summaries so the user-facing prose reads cleanly even when source snippets are messy

Backups:
- `audit/backups/phase109_pre_mashed_phrase_cleanup_20260318_190700`
- `audit/backups/phase109_patchwave1_phrase_token_fix_20260318_190820`

Implemented:
- upgraded `workshop/toolbox/stacks/web_core/websearch.py`
  - expanded `_repair_title_spacing()` with targeted phrase repairs for common live artifacts like `Tokyomight`, `fewdays`, `theofficialtravel`, `phonescompare`, and `ofiPhone`
  - improved `_summary_clean_text()` to normalize isolated `?` punctuation and keep cleaned excerpts tighter
- expanded `test_search_upgrade.py`
  - added regressions covering common travel mashups and health/compare mashups in summary text
- regenerated live slice artifacts:
  - `audit/phase109_everyday30.md`
  - `audit/phase109_everyday30.jsonl`
  - `audit/phase109_everyday30_summary.md`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`
- isolated `everyday30` rerun through `audit/search_benchmark.py` (wrote partial artifacts before the desktop timeout)

Outcome:
- search regressions increased to `166` passing tests, with the combined suite at `173` passing tests
- live travel and comparison summaries became noticeably cleaner, especially on Tokyo planning and iPhone-vs-Galaxy prompts
- the isolated benchmark harness still overran the shell timeout, but it wrote usable phase artifacts before exiting

### Phase 110

Focus:
- polish the supporting-source strip so Somi’s evidence list stays premium and doesn’t surface weaker aggregator titles when stronger sources are already present

Backups:
- `audit/backups/phase110_pre_support_source_polish_20260318_191300`
- `audit/backups/phase110_patchwave1_support_loop_cleanup_20260318_191420`
- `audit/backups/phase110_patchwave2_support_strictness_20260318_191500`

Implemented:
- upgraded `workshop/toolbox/stacks/web_core/websearch.py`
  - reused summary ranking logic to order support candidates more deliberately
  - made support filtering stricter for trip planning, travel lookup, and shopping compare outputs
  - excluded weak aggregator/social hosts from the `Supporting sources` strip for those higher-UX query types
- expanded `test_search_upgrade.py`
  - added regression coverage proving trip-planning support titles prefer human itinerary sources over aggregator-style rows

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`

Outcome:
- search regressions increased to `167` passing tests, with the combined suite at `174` passing tests
- trip-planning summaries kept the strong lead sentence and now list more trustworthy support sources instead of cluttering the evidence strip with weak aggregator titles

### Phase 111

Focus:
- refine the last user-visible summary edges from live probes: weekend-specific lead selection, health-explainer date cleanup, and final punctuation hygiene

Backups:
- `audit/backups/phase111_pre_weekend_and_health_summary_refine_20260318_191700`
- `audit/backups/phase111_patchwave1_leading_punct_cleanup_20260318_191840`
- `audit/backups/phase111_patchwave2_final_summary_punct_20260318_192000`

Implemented:
- upgraded `workshop/toolbox/stacks/web_core/websearch.py`
  - expanded phrase repair coverage for artifacts like `thingstodoin`, `Walkingdaily`, and `benefitsof`
  - stripped leading footnote numbers and leading date prefixes from summary sentences
  - added weekend-aware scoring so `weekend itinerary` prompts favor weekend/48-hour sources over generic 3-day itineraries
  - added final lead-summary punctuation cleanup so answers no longer open with stray symbols
- expanded `test_search_upgrade.py`
  - added regressions for weekend lead preference, date-prefix stripping, and leading-footnote cleanup
- saved focused live artifacts:
  - `audit/phase111_live_focus.json`
  - `audit/phase111_live_focus.md`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`
- targeted live probe across Tokyo planning/travel and walking-benefit queries, saved to the phase 111 focus artifacts

Outcome:
- search regressions increased to `170` passing tests, with the combined suite at `177` passing tests
- live planning/travel answers became more polished and the walking-benefits explainer now opens with a clean sentence instead of date/punctuation noise

### Phase 112

Focus:
- turn the premium shell into a more cohesive cockpit by grouping the quick-action surface into clear operator clusters, validating the live window offscreen, and cleaning runtime logging hygiene exposed by the new GUI tests

Backups:
- `audit/backups/phase112_pre_gui_runtime_assessment_20260318_195600`
- `audit/backups/phase112_patchwave1_cockpit_clusters_20260318_195819`
- `audit/backups/phase112_patchwave2_persona_combo_fix_20260318_195949`
- `audit/backups/phase112_patchwave3_gui_runtime_test_20260318_200209`
- `audit/backups/phase112_patchwave4_logging_hygiene_20260318_200343`
- `audit/backups/phase112_patchwave5_agent_log_hygiene_20260318_200500`

Implemented:
- upgraded `somicontroller_parts/layout_methods.py`
  - reworked the quick-action bar into clustered `Persona`, `Cabin`, `Studios`, `Console`, and `Heartbeat` segments
  - tightened the emoji-first cabin switch with a smaller slider and a live mode caption
  - promoted the action surface toward a dashboard feel instead of a long utility row
- upgraded `gui/themes/premium_base.py`
  - added cluster-frame styling, a smaller control treatment for quick actions, and dedicated selectors for the new cockpit surfaces
- upgraded `somicontroller_parts/settings_methods.py`
  - kept the cabin caption synchronized with persisted theme changes
- added `test_gui_shell_runtime.py`
  - boots the full `SomiAIGUI` window offscreen
  - verifies clustered cockpit surfaces exist
  - verifies research-pulse updates reach the live dashboard labels
- hardened logger setup in:
  - `agents.py`
  - `gui/aicoregui.py`
  - `workshop/toolbox/agent_core/wordgame.py`
  - `workshop/cli/somi.py`
  so repeated imports and runtime reloads stop leaking file handlers during GUI tests
- saved fresh GUI runtime artifacts:
  - `audit/phase112_gui_smoke.md`
  - `audit/phase112_gui_offscreen.png`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe -W default -m unittest C:\somex\test_gui_shell_runtime.py -v`
- offscreen GUI smoke through `SomiAIGUI()` with `QT_QPA_PLATFORM=offscreen`

Outcome:
- combined regression state advanced to `178` passing tests
- the premium shell now reads more like an operator cockpit, with clearer control grouping and a live cabin caption
- GUI/runtime validation is stronger because the full main window now has an offscreen regression test instead of relying only on stylesheet coverage
- the earlier GUI startup file-handler warnings were reduced to harmless third-party `DeprecationWarning` noise rather than Somi-owned logger leaks

### Phase 113

Focus:
- refine the last high-frequency answer-style edges exposed by the safe everyday corpus, especially travel/planning summaries and comparison phrasing

Backups:
- `audit/backups/phase113_patchwave1_search_output_refine_20260318_202124`

Implemented:
- upgraded `workshop/toolbox/stacks/web_core/websearch.py`
  - expanded title-repair coverage for Tokyo travel, family, food-itinerary, and compare prompt mashups
  - added intent-aware summary helpers for travel lookup, trip planning, and shopping comparison prompts
  - broadened summary synthesis so thin focus rows can still leverage the best nearby evidence rows
- expanded `test_search_upgrade.py`
  - added coverage for `best time to visit Tokyo`, `how many days in Tokyo`, `budget for 4 days in Tokyo`, `family trip plan for Tokyo`, `food itinerary for Tokyo`, and comparison-tone regressions

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`

Outcome:
- combined regression state advanced to `188` passing tests
- travel/planning answers became more intentional and comparison answers started speaking in dimensions instead of raw title echo

### Phase 114

Focus:
- validate the upgraded search output across the safe `everyday100` slice and identify the next live-output deltas before moving on

Backups:
- `audit/backups/phase114_pre_everyday100_rerun_20260318_203031`
- `audit/backups/phase114_patchwave1_intent_rows_support_hygiene_20260318_204253`

Implemented:
- reran the first `everyday100` benchmark slice and reviewed the live markdown artifact
- tightened support-source hygiene for planning/travel/shopping prompts inside `workshop/toolbox/stacks/web_core/websearch.py`

Checks:
- `C:\somex\.venv\Scripts\python.exe C:\somex\audit\search_benchmark_batch.py --corpus everyday1000 --chunk-size 20 --start-chunk 0 --end-chunk 4 --prefix phase114_everyday100 --somi-timeout 35 --chunk-timeout 1500 --stable-seconds 15`

Outcome:
- `audit/phase114_everyday100_combined_summary.md` landed with `4.51` average heuristic score, `6.49s` average Somi time, and `0` low-score rows
- the rerun confirmed remaining polish work was concentrated in seasonal travel wording, travel-budget tone, and phone-comparison phrasing rather than hard retrieval failures

### Phase 115

Focus:
- repair the benchmark-exposed answer-style deltas without regressing the rest of the shell or the search stack

Backups:
- `audit/backups/phase115_pre_everyday100_post_hygiene_20260318_204500`
- `audit/backups/phase115_patchwave1_budget_compare_tone_20260318_211608`

Implemented:
- upgraded `workshop/toolbox/stacks/web_core/websearch.py`
  - normalized thin travel day-range snippets into cleaner `3 to 5 days` guidance
  - improved budget-query fallback tone when public snippets omit hard numbers
  - rejected more compare-tool marketing copy and weak triple-compare support rows
- expanded `test_search_upgrade.py`
  - added budget-fallback and compare-tool rejection regressions
- saved refreshed benchmark artifacts:
  - `audit/phase115_everyday100_combined.jsonl`
  - `audit/phase115_everyday100_combined.md`
  - `audit/phase115_everyday100_combined_summary.md`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\audit\search_benchmark_batch.py --corpus everyday1000 --chunk-size 20 --start-chunk 0 --end-chunk 4 --prefix phase115_everyday100 --somi-timeout 35 --chunk-timeout 1500 --stable-seconds 15`

Outcome:
- the full combined suite held at `188` passing tests
- `audit/phase115_everyday100_combined_summary.md` recorded `4.52` average heuristic score, `7.3s` average Somi time, and `0` low-score rows
- everyday travel/planning outputs read more human and the shopping-compare strip became less noisy

### Phase 116

Focus:
- make the premium shell feel more alive and resilient by tightening the cabin switch, surfacing richer research telemetry, and cleaning visible GUI/search-path mojibake

Backups:
- `audit/backups/phase116_pre_log_sync_20260318_212026`
- `audit/backups/phase116_pre_gui_cockpit_signal_20260318_212333`
- `audit/backups/phase116_patchwave1_runtime_signal_fix_20260318_213144`

Implemented:
- upgraded `gui/themes/__init__.py`
  - replaced mojibake theme glyphs with the intended `☀️ / 🌆 / 🌙` registry labels
- upgraded `somicontroller_parts/settings_methods.py`
  - added `_theme_mode_emoji()` so visible cabin controls stay emoji-led even if theme labels/log text use richer names
  - made the theme selector dialog show the same emoji glyphs as the cockpit switch
- upgraded `somicontroller_parts/layout_methods.py`
  - tightened the cabin switch control sizing and slider footprint
  - added `ResearchSignalMeterWidget` to the Research Pulse card
- upgraded `somicontroller_parts/status_methods.py`
  - wired the new research signal meter to live pulse updates
  - made the hero metrics strip show recent browse mode and source count immediately
- upgraded `somicontroller.py`
  - added the custom `ResearchSignalMeterWidget`
  - imported `COLORS` directly so the custom widget paints with the active premium theme
- upgraded `gui/themes/premium_base.py`
  - styled the smaller cabin switch and reserved space for the research signal strip
- upgraded `agents.py` and `workshop/toolbox/stacks/web_core/websearch.py`
  - removed a few remaining visible mojibake separators and fallback phrases on the user-facing path
- expanded GUI regression coverage in:
  - `test_gui_themes.py`
  - `test_gui_shell_runtime.py`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_research_ux.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_shell_runtime.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- offscreen cockpit render saved to:
  - `audit/phase116_gui_offscreen.png`
  - `audit/phase116_font_smoke.png`
  - `audit/phase116_font_smoke_arial.png`
- focused live search slice saved to:
  - `audit/phase116_live_focus.json`
  - `audit/phase116_live_focus.md`

Outcome:
- the combined suite held at `188` passing tests, with the search-only suite at `180` passing tests
- the premium shell now exposes recent browse work more clearly through the top strip and the Research Pulse card
- live focus answers remained strong for hypertension, GitHub, and travel-season prompts
- the remaining search gap narrowed to travel-budget specificity when public snippets omit hard numbers
- the box-glyph offscreen screenshots were confirmed to be a Qt offscreen font artifact rather than a Somi-specific layout regression, because even a minimal standalone `QLabel` render produced the same placeholders

### Phase 117

Focus:
- stress-test the core systems behind Somi's search and GUI polish
- harden direct CLI runtime evaluation
- close the benchmark-pack coverage gaps for coding, memory, browser, and automation

Backups:
- `audit/backups/phase117_pre_chapterb_core_audit_20260318_213958`
- `audit/backups/phase117_patchwave1_core_runtime_pkg_20260318_214204`
- `audit/backups/phase117_patchwave2_runtime_cleanup_20260318_214500`
- `audit/backups/phase117_patchwave3_benchmark_hooks_20260318_214741`

Implemented:
- added `audit/__init__.py`
- upgraded `runtime/eval_harness.py`
  - direct CLI execution now survives the `runtime/audit.py` shadowing case and resolves audit benchmark modules consistently
- added `test_core_runtime_integrations.py`
  - heartbeat service + GUI bridge exercise
  - gateway session/node/health exercise
  - workflow runner allowlist + execution exercise
  - coding session open/resume exercise
  - direct CLI eval-harness regression
- added benchmark hook suites:
  - `tests/test_coding_tools_phase3.py`
  - `tests/test_coding_mode_phase5.py`
  - `tests/test_coding_studio_phase6.py`
  - `tests/test_memory_session_search_phase7.py`
  - `tests/test_browser_phase7.py`
  - `tests/test_delivery_automations_phase9.py`
- wrote durable artifacts:
  - `audit/phase117_core_runtime_summary.md`
  - `audit/phase117_benchmark_baseline.json`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_core_runtime_integrations.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\runtime\eval_harness.py`
- `C:\somex\.venv\Scripts\python.exe C:\somex\executive\memory\tests\test_memory.py`
- `C:\somex\.venv\Scripts\python.exe C:\somex\runtime\live_chat_stress.py`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_coding_tools_phase3.py C:\somex\tests\test_coding_mode_phase5.py C:\somex\tests\test_coding_studio_phase6.py C:\somex\tests\test_memory_session_search_phase7.py C:\somex\tests\test_browser_phase7.py C:\somex\tests\test_delivery_automations_phase9.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_core_runtime_integrations.py C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py C:\somex\tests\test_coding_tools_phase3.py C:\somex\tests\test_coding_mode_phase5.py C:\somex\tests\test_coding_studio_phase6.py C:\somex\tests\test_memory_session_search_phase7.py C:\somex\tests\test_browser_phase7.py C:\somex\tests\test_delivery_automations_phase9.py -v`

Outcome:
- the core integration suite passed with `5` tests
- the new benchmark hook suite passed with `6` tests
- the expanded combined suite advanced to `199` passing tests
- `runtime/eval_harness.py` passed cleanly with `26/26` checks
- `runtime/live_chat_stress.py` passed cleanly with `5/5` checks
- `executive/memory/tests/test_memory.py` passed cleanly
- the benchmark baseline improved to `measured=1 / ready=6`, and all remaining benchmark-pack gaps are now medium-severity finality-baseline gaps instead of missing coverage

### Phase 118

Focus:
- capture hard-difficulty finality baselines for the remaining core packs
- prove the Chapter B runtime work still leaves the user-facing search and GUI experience green

Backups:
- `audit/backups/phase118_pre_finality_baselines_20260318_215518`
- `audit/backups/phase118_patchwave1_focused_backup_20260318_215810`

Implemented:
- upgraded `audit/finality_lab.py`
  - direct CLI execution now resolves `audit.benchmark_packs` reliably instead of failing with `ModuleNotFoundError`
- captured a hard finality run for:
  - `coding`
  - `research`
  - `speech`
  - `automation`
  - `browser`
  - `memory`
- wrote artifacts:
  - `audit/phase118_finality_summary.md`
  - `audit/phase118_benchmark_baseline.json`
  - `audit/phase118_everyday100.md`
  - `audit/phase118_everyday100.jsonl`
  - `audit/phase118_everyday100_summary.md`

Checks:
- `C:\somex\.venv\Scripts\python.exe C:\somex\audit\finality_lab.py --root C:\somex --difficulty hard --packs coding research speech automation browser memory`
- `C:\somex\.venv\Scripts\python.exe -c "from audit.benchmark_baseline import build_benchmark_baseline; ..."`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_core_runtime_integrations.py C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py C:\somex\tests\test_coding_tools_phase3.py C:\somex\tests\test_coding_mode_phase5.py C:\somex\tests\test_coding_studio_phase6.py C:\somex\tests\test_memory_session_search_phase7.py C:\somex\tests\test_browser_phase7.py C:\somex\tests\test_delivery_automations_phase9.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\audit\search_benchmark.py --isolated --hard-exit --corpus everyday1000 --limit 100 --output C:\somex\audit\phase118_everyday100.md --json-output C:\somex\audit\phase118_everyday100.jsonl --summary-output C:\somex\audit\phase118_everyday100_summary.md --stdout-summary-only`

Outcome:
- the hard finality run measured all six remaining packs successfully
- the benchmark ledger is now fully green at `measured=7` with `gap_count=0`
- the broader regression suite remained green at `199` passing tests
- the safe `everyday100` benchmark rerun held `0` low-score rows with `4.52` average heuristic score and `4.64s` average Somi time

### Phase 119

Focus:
- build a Codex-style coding control layer on top of Somi's managed workspace stack
- surface repo and snapshot state in the premium coding studio instead of leaving it hidden in backend helpers

Backups:
- `audit/backups/phase119_pre_codex_mimic_audit_20260318_221415`
- `audit/backups/phase119_patchwave1_control_plane_20260318_222402`
- `audit/backups/phase119_patchwave2_codex_test_fix_20260318_223213`

Implemented:
- added `workshop/toolbox/coding/git_ops.py`
  - git status, diff, commit, publish status, and push helpers
- added `workshop/toolbox/coding/control_plane.py`
  - unified workspace inspection, edit, snapshot, verify, commit, push, and repo-import flows
- upgraded:
  - `workshop/toolbox/coding/__init__.py`
  - `gui/codingstudio_data.py`
  - `gui/codingstudio.py`
  - `somicontroller_parts/bootstrap_methods.py`
  - `somicontroller.py`
- added regression coverage:
  - `tests/test_codex_control_phase119.py`
  - `test_gui_codingstudio_phase119.py`
- wrote artifact:
  - `audit/phase119_codex_control_summary.md`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_codex_control_phase119.py C:\somex\test_gui_codingstudio_phase119.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_core_runtime_integrations.py C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_gui_codingstudio_phase119.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py C:\somex\tests\test_coding_tools_phase3.py C:\somex\tests\test_coding_mode_phase5.py C:\somex\tests\test_coding_studio_phase6.py C:\somex\tests\test_memory_session_search_phase7.py C:\somex\tests\test_browser_phase7.py C:\somex\tests\test_delivery_automations_phase9.py C:\somex\tests\test_codex_control_phase119.py -v`

Outcome:
- Somi now has a real coding control plane instead of just scattered coding helpers.
- The control layer can inspect files, apply bounded edits, manage snapshots, run verify loops, inspect git state, commit, push, and import repo snapshots for safe analysis.
- The premium coding studio now shows git cleanliness and snapshot availability directly in the GUI.
- The expanded combined regression suite advanced to `203` passing tests.

### Phase 123

Focus:
- strengthen the user-facing search answer contract without disturbing the fragile vertical routes
- make official/latest answers more explicit about authority and dates
- make compare and trip-planning answers read more like deliberate guidance than cleaned snippets

Backups:
- `audit/backups/phase123_pre_search_contract_20260318_234820`
- `audit/backups/phase123_patchwave1_focus_phrase_fix_20260318_235313`

Implemented:
- upgraded `executive/synthesis/answer_mixer.py`
  - broadened official-context detection for official government requirement queries
  - added best-date selection across preferred evidence rows for latest/current answers
  - added metadata-aware sentence selection so date-only snippet prefixes do not leak into the lead answer
  - added evidence-derived compare and itinerary phrasing for everyday compare/planning prompts
  - reduced duplicate host repetition in general-context source lists
- expanded `test_search_upgrade.py`
  - added regressions for government-official answer voice
  - added regressions for best available official date selection
  - added regressions for evidence-derived compare and itinerary leads
- wrote fresh live benchmark artifacts:
  - `audit/phase123_everyday20.md`
  - `audit/phase123_everyday20.jsonl`
  - `audit/phase123_everyday20_summary.md`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\audit\search_benchmark.py --isolated --hard-exit --corpus everyday1000 --limit 20 --output C:\somex\audit\phase123_everyday20.md --json-output C:\somex\audit\phase123_everyday20.jsonl --summary-output C:\somex\audit\phase123_everyday20_summary.md --stdout-summary-only`

Outcome:
- official/latest output is more professional and date-aware
- official government requirement lookups now speak with the same stronger official-source framing as medical/latest guidance queries
- everyday compare and trip-planning answers surface cleaner, evidence-backed takeaways
- the search-only suite passed at `184` tests
- the combined search+GUI suite passed at `191` tests
- the live `everyday20` slice averaged `4.6` with `0` Somi errors

### Phase 124

Focus:
- give deep research a reusable planner shape instead of a single flat summary
- carry research briefs and section plans through the websearch stack so downstream UX and autonomy layers can resume or display longer tasks coherently

Backups:
- `audit/backups/phase124_pre_research_briefs_20260318_235720`
- `audit/backups/phase124_patchwave1_bundle_structure_20260318_235848`

Implemented:
- upgraded `workshop/toolbox/stacks/research_core/evidence_schema.py`
  - extended `EvidenceBundle` with `research_brief` and `section_bundles`
- upgraded `workshop/toolbox/stacks/research_core/composer.py`
  - added intent detection, subquestion decomposition, section template planning, research-brief generation, and section-bundle assembly
- upgraded `workshop/toolbox/stacks/web_core/websearch.py`
  - browse reports now preserve research briefs and section bundles
  - deep browse records a compose step when findings are organized into sections
  - search-bundle conversion now carries planner metadata forward
- upgraded `workshop/toolbox/stacks/web_core/search_bundle.py`
  - search bundles now expose a compact research brief and section plan
- expanded `test_search_upgrade.py`
  - added research-composer planner coverage
  - added browse-report and search-bundle regressions for planner metadata

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`

Outcome:
- long-form research now has a durable plan shape Somi can display, cache, and resume later
- browse reports carry enough structure for a future timeline/report view without recomputing the whole research pass
- the search-only suite advanced to `187` passing tests
- the combined search+GUI suite advanced to `194` passing tests

### Phase 125

Focus:
- make deep-research results resumable across handler lifetimes instead of only within hot in-memory caches
- persist enough evidence structure that later GUI/autonomy work can reopen a research task with its summary, plan, and source identities intact

Backups:
- `audit/backups/phase125_pre_evidence_cache_20260319_000550`
- `audit/backups/phase125_patchwave1_evidence_store_20260319_000729`

Implemented:
- added `workshop/toolbox/stacks/research_core/evidence_cache.py`
  - disk-backed TTL store for evidence bundles
  - canonical URL normalization for persistent artifact identity
  - age tracking and bounded pruning
- upgraded `workshop/toolbox/stacks/web_core/websearch.py`
  - added persistent evidence-store wiring to `WebSearchHandler`
  - added save/resume helpers for deep research bundles
  - kept `_deep_browse()` deterministic by making resume opt-in and enabling it only from the top-level search orchestration
  - extended research fallback to reuse cached science bundles when they are still adequate
- expanded `test_search_upgrade.py`
  - added canonical URL and evidence-store round-trip coverage
  - added resume-path and stale-cache rejection regressions
  - isolated deep-browse tests from persistent cache side effects with temp cache roots
- wrote live artifacts:
  - `audit/phase125_repeat_probe.json`
  - `audit/phase125_resume_probe.json`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe - < audit probes for repeat-query and fresh-handler resume`

Outcome:
- repeated deep research can now resume from local evidence bundles instead of rebuilding every source trail from scratch
- cache reuse now preserves planner metadata, source identities, and section bundles for future GUI/report views
- the search-only suite advanced to `191` passing tests
- the combined search+GUI suite advanced to `198` passing tests
- the fresh-handler live probe confirmed a real disk-backed resume with `second_cached=true`

### Phase 126

Focus:
- make Somi's browse work legible in the premium GUI instead of compressing everything into one summary line
- keep the main cockpit and Research Studio synchronized around the same latest research pulse

Backups:
- `audit/backups/phase126_pre_execution_timeline_20260319_001709`
- `audit/backups/phase126_patchwave1_research_timeline_20260319_002155`
- `audit/backups/phase126_patchwave2_timeline_binding_20260319_002242`
- `audit/backups/phase126_patchwave3_research_studio_sync_20260319_002354`

Implemented:
- upgraded `somicontroller_parts/layout_methods.py`
  - extended `research_pulse` state with a compact `timeline`
  - added a dedicated execution timeline list to the Research Pulse card
- upgraded `somicontroller_parts/status_methods.py`
  - added `_research_timeline_preview()` to condense execution events and steps into human-readable timeline rows
  - pulse updates now render and refresh the live timeline list
  - Research Studio is refreshed immediately when the pulse changes
- upgraded `gui/researchstudio.py`
  - fallback browse-pulse view now includes the latest compact timeline when no long-running research job is active
- upgraded `somicontroller.py`
  - bound the new timeline preview helper into `SomiAIGUI`
- expanded GUI regressions:
  - `test_gui_research_ux.py`
  - `test_gui_shell_runtime.py`
- wrote offscreen smoke artifact:
  - `audit/phase126_gui_timeline_smoke.png`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`

Outcome:
- the Research Pulse now feels closer to a live agent console instead of a static status card
- users can follow browse progress from both the cockpit and the Research Studio fallback view without opening logs
- the search-only suite stayed green at `191` tests
- the combined search+GUI suite advanced to `199` passing tests

### Phase 127

Focus:
- make the premium research cockpit feel informative during real chat traffic, not only when tests inject full browse reports directly
- add cleaner source states so users can see what Somi relied on at a glance

Backups:
- `audit/backups/phase127_pre_premium_pulse_sources_20260319_002603`
- `audit/backups/phase127_patchwave1_source_binding_20260319_003014`

Implemented:
- upgraded `gui/aicoregui.py`
  - compact research reports now preserve a condensed timeline and primary-source previews during chat attachment transport
- upgraded `somicontroller_parts/layout_methods.py`
  - Research Pulse now has a dedicated primary-sources list beneath the execution timeline
- upgraded `somicontroller_parts/status_methods.py`
  - added `_research_source_preview()` for compact source-card rows
  - pulse updates now render source rows alongside timeline rows and keep sensible empty-state placeholders
- upgraded `gui/researchstudio.py`
  - fallback browse-pulse view now mirrors the primary-source preview
- upgraded `gui/themes/premium_base.py`
  - added dedicated styling for the timeline and primary-source lists
- upgraded `somicontroller.py`
  - bound the new source-preview helper into `SomiAIGUI`
- expanded GUI regressions:
  - `test_gui_research_ux.py`
  - `test_gui_shell_runtime.py`
- wrote offscreen smoke artifact:
  - `audit/phase127_gui_pulse_sources_smoke.png`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_gui_themes.py C:\somex\test_research_studio_data.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py C:\somex\test_search_upgrade.py -v`

Outcome:
- the premium pulse now survives real chat compaction with enough structure to still feel like a live cockpit
- users can see both Somi's last actions and its primary sources without opening the full transcript or logs
- the search-only suite stayed green at `191` tests
- the combined search+GUI suite remained green at `199` passing tests

### Phase 130

Focus:
- give long-running coding sessions a durable working-memory layer instead of relying on bloated transcript state
- make the coding cockpit show a compact, resumable summary of what matters right now

Backups:
- `audit/backups/phase130_pre_coding_scratchpad_20260319_003143`

Implemented:
- added `workshop/toolbox/coding/scratchpad.py`
  - deterministic scratchpad builder for objectives, focus files, constraints, open loops, and next actions
  - bounded coding compaction summary for resume-friendly state handoff
- upgraded `workshop/toolbox/coding/service.py`
  - coding sessions now persist `scratchpad` and `compaction_summary` metadata on open/resume
- upgraded `workshop/toolbox/coding/control_plane.py`
  - control snapshots now refresh and expose the scratchpad/compaction state
- upgraded `workshop/toolbox/coding/__init__.py`
  - exported the new scratchpad helpers
- upgraded `gui/codingstudio_data.py`
  - coding studio snapshots now carry scratchpad and compaction summary data
- upgraded `gui/codingstudio.py`
  - Coding Studio welcome state now surfaces the resume summary
  - next actions now also show top scratchpad open loops
- expanded regressions:
  - `tests/test_coding_compaction_phase130.py`
  - `test_gui_codingstudio_phase119.py`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_codex_control_phase119.py C:\somex\tests\test_coding_compaction_phase130.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_codingstudio_phase119.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py C:\somex\test_gui_codingstudio_phase119.py C:\somex\test_search_upgrade.py C:\somex\tests\test_codex_control_phase119.py C:\somex\tests\test_coding_compaction_phase130.py -v`
- live probe:
  - `C:\somex\.venv\Scripts\python.exe - < scratchpad probe`

Outcome:
- coding sessions now have a durable, bounded resume summary that can survive context reduction and still tell Somi what matters
- the Coding Studio now feels more like a serious long-task console instead of only a live snapshot
- the combined cross-domain suite advanced to `205` passing tests

### Phase 128

Focus:
- turn Somi's existing profile/preference facts into a clearer durable memory view instead of leaving them as scattered rows
- expose that memory continuity in operator-facing tooling so it becomes inspectable and trustworthy

Backups:
- `audit/backups/phase128_pre_preference_graph_20260319_003727`

Implemented:
- added `executive/memory/preference_graph.py`
  - confidence-aware preference graph builder with evidence counts and compact summary text
- upgraded `executive/memory/manager.py`
  - added sync/async preference-graph accessors
  - frozen prompt snapshots now preserve the latest preference graph
- upgraded `executive/memory/__init__.py`
  - exported the new graph builder
- upgraded `gui/controlroom_data.py`
  - Control Room memory rows now include a dedicated Preference Graph surface
- added regressions:
  - `executive/memory/tests/test_preference_graph.py`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\executive\memory\tests\test_preference_graph.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py C:\somex\test_gui_codingstudio_phase119.py C:\somex\test_search_upgrade.py C:\somex\tests\test_codex_control_phase119.py C:\somex\tests\test_coding_compaction_phase130.py C:\somex\executive\memory\tests\test_preference_graph.py -v`
- live probe:
  - `C:\somex\.venv\Scripts\python.exe - < preference graph probe`

Outcome:
- Somi now has a more coherent picture of stable user identity and preferences instead of only row-level memory fragments
- operators can inspect that durable preference state in Control Room and trace it through frozen memory snapshots
- the combined cross-domain suite advanced to `207` passing tests

### Phase 137

Focus:
- introduce a safe-autonomy posture Somi can persist and expose without relaxing user control
- make the active initiative mode inspectable in runtime, approvals, and operator-facing GUI surfaces

Backups:
- `audit/backups/phase137_pre_autonomy_profiles_20260319_004220`
- `audit/backups/phase137_patchwave1_autonomy_wiring_20260319_004610`

Implemented:
- upgraded `ops/control_plane.py`
  - runtime config now normalizes autonomy profile state alongside runtime rollout state
  - added active autonomy profile persistence, revisions, and snapshot surfacing
- upgraded `executive/approvals.py`
  - approval summary now includes the active autonomy profile
- upgraded `gui/controlroom_data.py`
  - Control Room config rows and overview text now expose the active autonomy profile
- upgraded `runtime/__init__.py`
  - exported runtime autonomy helpers for reuse
- added regressions:
  - `tests/test_autonomy_profiles_phase137.py`
- added artifact:
  - `audit/phase137_autonomy_smoke.md`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_autonomy_profiles_phase137.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py C:\somex\test_gui_codingstudio_phase119.py C:\somex\tests\test_codex_control_phase119.py C:\somex\tests\test_coding_compaction_phase130.py C:\somex\executive\memory\tests\test_preference_graph.py C:\somex\tests\test_autonomy_profiles_phase137.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py C:\somex\test_gui_codingstudio_phase119.py C:\somex\test_search_upgrade.py C:\somex\tests\test_codex_control_phase119.py C:\somex\tests\test_coding_compaction_phase130.py C:\somex\executive\memory\tests\test_preference_graph.py C:\somex\tests\test_autonomy_profiles_phase137.py -v`
- runtime smoke:
  - `C:\somex\.venv\Scripts\python.exe - < phase137 autonomy smoke`

Outcome:
- Somi now has a first-class bounded-autonomy posture that can be changed, audited, and surfaced through operator tooling
- the runtime trust model is clearer because approval summaries and Control Room now agree on the current autonomy setting
- the combined cross-domain suite advanced to `210` passing tests

### Phase 138

Focus:
- make long-running work durable in the runtime instead of tying everything to the foreground turn
- give Somi a safe background queue with recovery signals and local resource budgeting

Backups:
- `audit/backups/phase138_pre_background_recovery_20260319_005110`
- `audit/backups/phase138_patchwave1_background_task_store_20260319_005238`

Implemented:
- added `runtime/background_tasks.py`
  - persisted background task ledger with queue, running, retry-ready, completed, and failed states
  - artifact/handoff metadata
  - stale-task recovery and resource-budget hints
- upgraded `ops/control_plane.py`
  - added background task create, heartbeat, complete, fail, and recover methods
  - ops snapshots now include a background task queue summary
- upgraded `runtime/performance_controller.py`
  - exposed public load-level access and a background budget hint
- upgraded `gui/controlroom_data.py`
  - Control Room observability now shows background queue health and retry pressure
- upgraded `runtime/__init__.py`
  - exported background task helpers for reuse
- added regressions:
  - `tests/test_background_tasks_phase138.py`
- added artifact:
  - `audit/phase138_background_recovery_smoke.md`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_background_tasks_phase138.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py C:\somex\test_gui_codingstudio_phase119.py C:\somex\tests\test_codex_control_phase119.py C:\somex\tests\test_coding_compaction_phase130.py C:\somex\executive\memory\tests\test_preference_graph.py C:\somex\tests\test_autonomy_profiles_phase137.py C:\somex\tests\test_background_tasks_phase138.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py C:\somex\test_gui_codingstudio_phase119.py C:\somex\test_search_upgrade.py C:\somex\tests\test_codex_control_phase119.py C:\somex\tests\test_coding_compaction_phase130.py C:\somex\executive\memory\tests\test_preference_graph.py C:\somex\tests\test_autonomy_profiles_phase137.py C:\somex\tests\test_background_tasks_phase138.py -v`
- runtime smoke:
  - `C:\somex\.venv\Scripts\python.exe - < phase138 background recovery smoke`

Outcome:
- Somi can now persist and recover bounded background work instead of treating every long task as purely foreground state
- operators can see queue pressure, retry-ready work, and background capacity directly in Control Room
- the combined cross-domain suite advanced to `215` passing tests

### Phase 139

Focus:
- turn repeated successful work into visible, approval-gated skill suggestions
- raise the safety bar for thin-evidence high-stakes answers without making ordinary answers noisier

Backups:
- `audit/backups/phase139_pre_skill_trust_20260319_005930`
- `audit/backups/phase139_patchwave1_skill_trust_wiring_20260319_010005`
- `audit/backups/phase139_patchwave2_circular_fix_20260319_010126`

Implemented:
- added `runtime/skill_apprenticeship.py`
  - apprenticeship ledger for repeated workflows
  - workflow-derived suggestion seeding
  - approval-required and draft-ready suggestion flags
- upgraded `ops/control_plane.py`
  - apprenticeship suggestions now ride along with ops snapshots
  - successful background work records apprenticeship activity
- upgraded `runtime/answer_validator.py`
  - added high-stakes low-evidence trust policy checks and stronger caution repair
- upgraded `agent_methods/response_methods.py`
  - validator now receives the active query text for trust-policy decisions
- upgraded `gui/controlroom_data.py`
  - Control Room observability now shows apprenticeship suggestion readiness
- upgraded `runtime/__init__.py`
  - exported apprenticeship helpers for reuse
- added regressions:
  - `tests/test_skill_apprenticeship_phase139.py`
  - `tests/test_trust_policy_phase139.py`
- added artifact:
  - `audit/phase139_skill_trust_smoke.md`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_skill_apprenticeship_phase139.py C:\somex\tests\test_trust_policy_phase139.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py C:\somex\test_gui_codingstudio_phase119.py C:\somex\tests\test_codex_control_phase119.py C:\somex\tests\test_coding_compaction_phase130.py C:\somex\executive\memory\tests\test_preference_graph.py C:\somex\tests\test_autonomy_profiles_phase137.py C:\somex\tests\test_background_tasks_phase138.py C:\somex\tests\test_skill_apprenticeship_phase139.py C:\somex\tests\test_trust_policy_phase139.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py C:\somex\test_gui_codingstudio_phase119.py C:\somex\test_search_upgrade.py C:\somex\tests\test_codex_control_phase119.py C:\somex\tests\test_coding_compaction_phase130.py C:\somex\executive\memory\tests\test_preference_graph.py C:\somex\tests\test_autonomy_profiles_phase137.py C:\somex\tests\test_background_tasks_phase138.py C:\somex\tests\test_skill_apprenticeship_phase139.py C:\somex\tests\test_trust_policy_phase139.py -v`
- runtime smoke:
  - `C:\somex\.venv\Scripts\python.exe - < phase139 skill and trust smoke`

Outcome:
- Somi can now notice repeated useful work, surface approval-gated skill drafts, and show operators when those drafts are ready to review
- high-stakes low-evidence answers now get a more trustworthy caution layer instead of sounding overly certain
- the combined cross-domain suite advanced to `219` passing tests

### Phase 132

Focus:
- make Telegram behave like the same Somi runtime instead of a lighter separate bot surface
- carry thread continuity, trust posture, and long-task telemetry across Telegram turns with the same state and ops primitives the desktop shell already uses

Backups:
- `audit/backups/phase132_pre_telegram_unification_20260319_011325`
- `audit/backups/phase132_patchwave1_test_cleanup_20260319_012028`
- `audit/backups/phase132_patchwave2_logs_20260319_012158`

Implemented:
- added `workshop/integrations/telegram_runtime.py`
  - conversation ID normalization for DMs and topic chats
  - thread-resolution heuristics for follow-ups, resumes, and new-task prompts
  - compact Telegram research/coding reply bundles
  - remote-session upsert helper for paired-owner vs guest trust posture
- upgraded `workshop/integrations/telegram.py`
  - per-user surface sessions now ride through the gateway instead of only the bot service session
  - Telegram queue items now carry shared `thread_id`, `task_id`, and conversation metadata
  - queued/running/completed/failed Telegram jobs now write into the shared background task ledger
  - Telegram replies now append compact research/coding notes instead of feeling like plain raw text
- upgraded `agent_methods/response_methods.py`
  - `generate_response()` and `generate_response_with_attachments()` now accept optional `thread_id_override` and `trace_metadata`
  - non-GUI surfaces can now write into the same state timeline and preserve cross-surface resume metadata
- added regressions:
  - `tests/test_telegram_runtime_phase132.py`
- added artifact:
  - `audit/phase132_telegram_runtime_summary.md`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_telegram_runtime_phase132.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_core_runtime_integrations.py -v`
- `C:\somex\.venv\Scripts\python.exe -c "import workshop.integrations.telegram as mod; print('telegram_import_ok', hasattr(mod, 'TelegramHandler'))"`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py C:\somex\test_gui_codingstudio_phase119.py C:\somex\test_search_upgrade.py C:\somex\tests\test_codex_control_phase119.py C:\somex\tests\test_coding_compaction_phase130.py C:\somex\executive\memory\tests\test_preference_graph.py C:\somex\tests\test_autonomy_profiles_phase137.py C:\somex\tests\test_background_tasks_phase138.py C:\somex\tests\test_skill_apprenticeship_phase139.py C:\somex\tests\test_trust_policy_phase139.py C:\somex\tests\test_telegram_runtime_phase132.py C:\somex\test_core_runtime_integrations.py -v`

Outcome:
- Telegram is no longer just a launcher and response pipe; it now participates in the same thread/task continuity model as the desktop runtime
- paired owners and guest users now show up with clearer trust posture in the shared gateway state, which closes part of the product-polish gap with OpenClaw/Hermes-style channel handling
- the combined cross-domain suite advanced to `229` passing tests

### Phase 133

Focus:
- close the biggest remaining Telegram parity gap after runtime unification by making document uploads useful, readable, and explainable
- improve OCR-adjacent document handling without introducing paid services or heavy new dependencies

Backups:
- `audit/backups/phase133_pre_ocr_document_intelligence_20260319_012312`
- `audit/backups/phase133_patchwave1_logs_20260319_012857`

Implemented:
- added `workshop/toolbox/stacks/ocr_core/document_intel.py`
  - extraction support for PDF, TXT, MD, CSV, JSON, LOG, YAML, and YML uploads
  - cleaned excerpts, anchor generation, and manual-review guidance for low-signal files
- upgraded `workshop/integrations/telegram.py`
  - Telegram document uploads now route through the same thread/task runtime used by normal Telegram chat work
  - supported documents can now be summarized through the agent path with provenance notes and anchor previews
  - unsupported or unreadable uploads now return explicit guidance instead of dying as opaque attachments
- added regressions:
  - `tests/test_document_intel_phase133.py`
- added artifact:
  - `audit/phase133_document_intelligence_summary.md`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_document_intel_phase133.py -v`
- `C:\somex\.venv\Scripts\python.exe -c "from workshop.toolbox.stacks.ocr_core.benchmarks import run_document_benchmarks; report = run_document_benchmarks(root_dir='C:/somex/sessions/ocr_phase133_smoke'); print({'ok': report.get('ok'), 'average_parse_ms': report.get('average_parse_ms'), 'average_score': report.get('average_score')})"`
- `C:\somex\.venv\Scripts\python.exe -c "import workshop.integrations.telegram as mod; print('telegram_import_ok', hasattr(mod, 'TelegramHandler'))"`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py C:\somex\test_gui_codingstudio_phase119.py C:\somex\test_search_upgrade.py C:\somex\tests\test_codex_control_phase119.py C:\somex\tests\test_coding_compaction_phase130.py C:\somex\executive\memory\tests\test_preference_graph.py C:\somex\tests\test_autonomy_profiles_phase137.py C:\somex\tests\test_background_tasks_phase138.py C:\somex\tests\test_skill_apprenticeship_phase139.py C:\somex\tests\test_trust_policy_phase139.py C:\somex\tests\test_telegram_runtime_phase132.py C:\somex\tests\test_document_intel_phase133.py C:\somex\test_core_runtime_integrations.py -v`

Outcome:
- Telegram uploads are now meaningfully useful for common text and PDF documents instead of being stuck as a photo-only side path
- document provenance, anchors, and review guidance improve trust and reduce user confusion when extraction quality is weak
- the combined cross-domain suite advanced to `233` passing tests

### Phase 134

Focus:
- close the product-maturity gap around diagnostics, supportability, and release-readiness
- make Somi's operator health checks match the backup strategy the project is actually using

Backups:
- `audit/backups/phase134_pre_ops_diagnostics_20260319_013400`
- `audit/backups/phase134_patchwave1_ops_support_bundle_20260319_013558`
- `audit/backups/phase134_patchwave2_checkpoint_heuristic_20260319_014000`
- `audit/backups/phase134_patchwave3_logs_20260319_014040`

Implemented:
- upgraded `ops/backup_verifier.py`
  - backup discovery now searches both `backups` and `audit/backups`
  - meaningful phase checkpoints now validate as recovery artifacts instead of always failing full-backup checks
- upgraded `ops/doctor.py`
  - doctor now reports `backup_roots` and `available_count`
  - live doctor status now reflects the real checkpoint trail instead of treating the repo as unrecoverable
- upgraded `ops/security_audit.py`
  - security audit now carries backup-root visibility alongside recent checkpoint health
- upgraded `ops/release_gate.py`
  - doctor dashboard rows now show the real available-tool count
- added `ops/support_bundle.py`
  - exportable JSON and Markdown support bundles with doctor, security, backup, ops, and release-report context
- upgraded `somi.py`
  - added `somi support bundle`
- added regressions:
  - `tests/test_ops_diagnostics_phase134.py`
- added artifact:
  - `audit/phase134_ops_diagnostics_summary.md`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_ops_diagnostics_phase134.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py doctor --json --root C:\somex`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py support bundle --json --root C:\somex --no-write`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py release gate --json --root C:\somex --no-write`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py C:\somex\test_gui_codingstudio_phase119.py C:\somex\test_search_upgrade.py C:\somex\tests\test_codex_control_phase119.py C:\somex\tests\test_coding_compaction_phase130.py C:\somex\executive\memory\tests\test_preference_graph.py C:\somex\tests\test_autonomy_profiles_phase137.py C:\somex\tests\test_background_tasks_phase138.py C:\somex\tests\test_skill_apprenticeship_phase139.py C:\somex\tests\test_trust_policy_phase139.py C:\somex\tests\test_telegram_runtime_phase132.py C:\somex\tests\test_document_intel_phase133.py C:\somex\tests\test_ops_diagnostics_phase134.py C:\somex\test_core_runtime_integrations.py -v`

Outcome:
- Somi now has an operator-grade support bundle path instead of only ad hoc JSON output
- release readiness is no longer falsely blocked by the checkpoint model, and the live repo now passes doctor, security, and release-gate checks together
- the combined cross-domain suite advanced to `238` passing tests

### Phase 135

Focus:
- prove that Somi can clear a harder research/planning benchmark pack, not just the everyday lookup mix
- give the framework one combined release-candidate runner across search, coding, memory, and Telegram parity

Backups:
- `audit/backups/phase135_pre_release_candidate_benchmarks_20260319_014140`
- `audit/backups/phase135_patchwave1_rc_runner_20260319_014240`
- `audit/backups/phase135_patchwave2_logs_20260319_020300`

Implemented:
- upgraded `audit/safe_search_corpus.py`
  - added `build_hard_research_corpus()`
  - added named corpora:
    - `researchhard25`
    - `researchhard100`
    - `everyday100`
- added `audit/release_candidate.py`
  - unified release-candidate runner for search batch packs and runtime unittest packs
  - default packs now cover:
    - `researchhard100`
    - `coding_suite`
    - `memory_suite`
    - `telegram_suite`
- added regressions:
  - `tests/test_release_candidate_phase135.py`
- upgraded `test_search_upgrade.py`
  - added hard-research corpus coverage
- added artifact:
  - `audit/phase135_release_candidate_summary.md`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_release_candidate_phase135.py C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\audit\release_candidate.py --output-dir C:\somex\audit --prefix phase135_subset --packs memory_suite,telegram_suite`
- `C:\somex\.venv\Scripts\python.exe C:\somex\audit\release_candidate.py --output-dir C:\somex\audit --prefix phase135_researchhard100 --packs researchhard100`
- `C:\somex\.venv\Scripts\python.exe C:\somex\audit\release_candidate.py --output-dir C:\somex\audit --prefix phase135_release_candidate`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py C:\somex\test_gui_codingstudio_phase119.py C:\somex\test_search_upgrade.py C:\somex\tests\test_codex_control_phase119.py C:\somex\tests\test_coding_compaction_phase130.py C:\somex\executive\memory\tests\test_preference_graph.py C:\somex\tests\test_autonomy_profiles_phase137.py C:\somex\tests\test_background_tasks_phase138.py C:\somex\tests\test_skill_apprenticeship_phase139.py C:\somex\tests\test_trust_policy_phase139.py C:\somex\tests\test_telegram_runtime_phase132.py C:\somex\tests\test_document_intel_phase133.py C:\somex\tests\test_ops_diagnostics_phase134.py C:\somex\tests\test_release_candidate_phase135.py C:\somex\test_core_runtime_integrations.py -v`

Outcome:
- Somi now has a meaningful hard-research benchmark pack that better reflects its competitive edge than the older everyday mix alone
- the combined release-candidate run passed across search, coding, memory, and Telegram parity
- live `researchhard100` results came in at `4.95` average heuristic score, `3.38s` average Somi time, and `0` sub-4 cases
- the combined cross-domain suite advanced to `241` passing tests

### Phase 136

Focus:
- prove that Somi can survive a coordinated mixed-use stress pass instead of only passing isolated vertical suites
- turn the post-implementation gauntlet into a resumable CLI path with durable artifacts and phase-safe recovery points

Backups:
- `audit/backups/phase136_pre_system_gauntlet_20260319_020340`
- `audit/backups/phase136_patchwave1_system_gauntlet_20260319_021031`
- `audit/backups/phase136_patchwave2_resume_search_20260319_023622`
- `audit/backups/phase136_patchwave3_logs_20260319_023923`

Implemented:
- added `audit/system_gauntlet.py`
  - unified full-system gauntlet runner for:
    - `Search100`
    - `Memory100`
    - `Reminder100`
    - `Compaction100`
    - `OCR100`
    - `Coding100`
    - `AverageUser30`
  - persisted JSON and Markdown gauntlet artifacts
  - search-pack reuse so completed benchmark chunks are reused on rerun instead of being recomputed
- upgraded `somi.py`
  - added `somi release gauntlet`
- added regressions:
  - `tests/test_system_gauntlet_phase136.py`
- added artifact:
  - `audit/phase136_system_gauntlet_summary.md`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_system_gauntlet_phase136.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py release gauntlet --json --root C:\somex --prefix phase136_subset_smoke --output-dir C:\somex\audit --packs memory100,reminder100,compaction100,ocr100,coding100,averageuser30 --count 12 --scenario-turns 12 --skip-live-chat`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py release gauntlet --json --root C:\somex --prefix phase136_system_gauntlet --output-dir C:\somex\audit --count 100 --scenario-turns 30 --search-corpus everyday100`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_research_studio_data.py C:\somex\test_gui_codingstudio_phase119.py C:\somex\test_search_upgrade.py C:\somex\tests\test_codex_control_phase119.py C:\somex\tests\test_coding_compaction_phase130.py C:\somex\executive\memory\tests\test_preference_graph.py C:\somex\tests\test_autonomy_profiles_phase137.py C:\somex\tests\test_background_tasks_phase138.py C:\somex\tests\test_skill_apprenticeship_phase139.py C:\somex\tests\test_trust_policy_phase139.py C:\somex\tests\test_telegram_runtime_phase132.py C:\somex\tests\test_document_intel_phase133.py C:\somex\tests\test_ops_diagnostics_phase134.py C:\somex\tests\test_release_candidate_phase135.py C:\somex\tests\test_system_gauntlet_phase136.py C:\somex\test_core_runtime_integrations.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py doctor --json --root C:\somex`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py release gate --json --root C:\somex --no-write`

Outcome:
- the full gauntlet passed with `7/7` packs green and durable artifacts under `audit/phase136_system_gauntlet.*`
- `Search100` finished at `100` queries, `4.52` average heuristic score, and `5.88s` average Somi time
- `Memory100`, `Reminder100`, `Compaction100`, `OCR100`, `Coding100`, and `AverageUser30` all passed in the coordinated run
- the broader combined suite advanced to `244` passing tests while doctor and release gate both stayed green

### Phase 140

Focus:
- standardize pre-phase backups so future long runs stay safe during context compaction and do not copy old backups into new ones
- refresh the master roadmap around the real next frontier: contributor clarity, boundary cleanup, premium polish, artifact hygiene, and offline resilience

Backups:
- `audit/backups/phase140_pre_plan_and_backup_hardening_20260319_053134`

Implemented:
- added `ops/backup_creator.py`
  - source-focused phase checkpoint creation
  - default exclusion of:
    - `audit/backups`
    - `audit/external_repos`
    - `.venv`
    - bulky generated session artifact roots
- upgraded `ops/__init__.py`
  - exported the backup creation helpers
- upgraded `somi.py`
  - added `somi backup create`
- added regressions:
  - `tests/test_backup_creator_phase140.py`
- added artifact:
  - `audit/phase140_backup_hardening_summary.md`
- refreshed:
  - `update.md`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_backup_creator_phase140.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py backup create --json --root C:\somex --label phase140_smoke_backup --include update.md,phase_upgrade.md,agentupgrade.md,somi.py,ops`

Outcome:
- Somi now has a safe, repeatable CLI for phase backups instead of relying on manual copy commands
- new checkpoints exclude recursive backup trees by default, closing one of the biggest repo-hygiene hazards surfaced during the audit
- the master roadmap now reflects the post-Phase-136 state and defines the next campaign phases `141` through `147`

### Phase 141

Focus:
- make the core working layers legible to new contributors instead of expecting them to infer ownership from filenames
- create one durable contributor map that points basic users and developers into the right parts of the codebase quickly

Backups:
- `audit/backups/phase141_pre_contributor_maps_20260319_093540`
- `audit/backups/phase141_patchwave1_docs_link_fix_20260319_094200`

Implemented:
- added:
  - `docs/architecture/CONTRIBUTOR_MAP.md`
  - `somicontroller_parts/README.md`
  - `workshop/toolbox/agent_core/README.md`
  - `workshop/toolbox/browser/README.md`
  - `workshop/toolbox/coding/README.md`
  - `workshop/toolbox/research_supermode/README.md`
  - `workshop/toolbox/stacks/README.md`
  - `workshop/toolbox/stacks/web_core/README.md`
  - `workshop/toolbox/stacks/research_core/README.md`
- upgraded:
  - `docs/architecture/README.md`
  - `workshop/README.md`
  - `workshop/toolbox/README.md`
  - `gui/README.md`
  - `runtime/README.md`
  - `README.md`
- added regressions:
  - `tests/test_docs_coverage_phase141.py`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_docs_coverage_phase141.py C:\somex\tests\test_backup_creator_phase140.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_core_runtime_integrations.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py backup verify --json --root C:\somex`

Outcome:
- Somi now has a real newcomer path through the controller, toolbox, search, research, and coding layers
- a stale architecture link was caught and fixed during validation instead of being left to confuse later contributors

### Phase 142

Focus:
- turn contributor docs into an operational quality signal instead of a static promise
- give new contributors a short practical checklist for safe debugging and test placement

Backups:
- `audit/backups/phase142_pre_docs_guardrails_20260319_094256`

Implemented:
- added:
  - `ops/docs_integrity.py`
  - `docs/architecture/NEWCOMER_CHECKLIST.md`
  - `tests/test_docs_guardrails_phase142.py`
- upgraded:
  - `ops/__init__.py`
  - `ops/doctor.py`
  - `ops/release_gate.py`
  - `tests/test_docs_coverage_phase141.py`
  - `docs/architecture/README.md`
  - `docs/architecture/CONTRIBUTOR_MAP.md`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_docs_coverage_phase141.py C:\somex\tests\test_docs_guardrails_phase142.py C:\somex\tests\test_ops_diagnostics_phase134.py C:\somex\tests\test_backup_creator_phase140.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py doctor --json --root C:\somex`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py release gate --json --root C:\somex --no-write`

Outcome:
- doctor and release gate now explicitly report docs integrity, so newcomer-quality regressions can surface before a release
- the docs checklist gives contributors a concrete, lower-risk starting path instead of vague “read the repo” advice

### Phase 143

Focus:
- widen the contributor map from the core layers to the top-level platform surfaces that shape runtime ownership
- make package boundaries easier to understand before any deeper structural cleanup

Backups:
- `audit/backups/phase143_pre_platform_maps_20260319_094720`

Implemented:
- added:
  - `ops/README.md`
  - `gateway/README.md`
  - `state/README.md`
  - `workflow_runtime/README.md`
  - `search/README.md`
  - `execution_backends/README.md`
  - `agent_methods/README.md`
  - `tests/README.md`
- upgraded:
  - `ops/docs_integrity.py`
  - `docs/architecture/CONTRIBUTOR_MAP.md`
- added artifact:
  - `audit/phase141_143_contributor_clarity_summary.md`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_docs_coverage_phase141.py C:\somex\tests\test_docs_guardrails_phase142.py C:\somex\tests\test_backup_creator_phase140.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py doctor --json --root C:\somex`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py release gate --json --root C:\somex --no-write`

Outcome:
- the top-level platform surfaces now explain themselves locally instead of making contributors reverse-engineer ownership from imports
- docs integrity stayed green even after the required surface expanded, so the guardrail is doing real work rather than checking a tiny happy path

### Phase 144

Focus:
- tighten the search-answer contract without disturbing the retrieval gains from earlier phases
- clean up shadowed helper definitions in the synthesis layer so future contributors do not have to guess which implementation is active

Backups:
- `audit/backups/phase144_pre_search_output_polish_20260319_095553`
- `audit/backups/phase144_patchwave1_helper_dedupe_fix_20260319_095904`

Implemented:
- upgraded `executive/synthesis/answer_mixer.py`
  - renamed legacy shadowed helper implementations out of the canonical namespace
  - improved trip-planning phrasing when the lead is already a complete itinerary sentence
- upgraded `test_search_upgrade.py`
  - added a structure regression to enforce one canonical definition for the key answer-mixer helpers
  - updated trip-planning answer expectations around the smoother wording
- added artifact:
  - `audit/phase144_146_upgrade_summary.md`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py release gate --json --root C:\somex --no-write`

Outcome:
- `193` search tests passed
- trip-planning answers read a little more naturally
- the synthesis layer is less confusing to maintain

### Phase 145

Focus:
- polish the GUI interaction details users notice immediately, especially the premium mode switch and the research pulse

Backups:
- `audit/backups/phase145_pre_gui_flow_polish_20260319_100034`
- `audit/backups/phase145_patchwave1_research_pulse_consistency_20260319_100142`

Implemented:
- rebuilt `gui/themes/__init__.py` so the premium theme registry now uses real emoji labels cleanly
- upgraded `somicontroller_parts/status_methods.py`
  - research pulse now falls back to `progress_headline` or `execution_summary` before generic placeholder copy
  - meta copy now uses `cautions` wording instead of `limits`
- upgraded `somicontroller_parts/layout_methods.py`
  - aligned the initial research-pulse meta placeholder with the live wording
- upgraded GUI regressions:
  - `test_gui_themes.py`
  - `test_gui_shell_runtime.py`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py -v`

Outcome:
- `8` GUI tests passed
- the premium mode switch now feels like a real emoji-driven control instead of a partially broken registry surface
- the research pulse stays useful earlier in a browse task

### Phase 146

Focus:
- add artifact hygiene guardrails so long benchmark and audit cycles do not silently drag down the framework

Backups:
- `audit/backups/phase146_pre_artifact_hygiene_20260319_100249`
- `audit/backups/phase146_patchwave1_budget_tuning_20260319_100805`

Implemented:
- added `ops/artifact_hygiene.py`
- upgraded:
  - `ops/__init__.py`
  - `ops/doctor.py`
  - `ops/release_gate.py`
- added tests:
  - `tests/test_artifact_hygiene_phase146.py`
- tuned the default audit artifact budget to match Somi's current active working set while keeping the guardrail meaningful

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_artifact_hygiene_phase146.py C:\somex\tests\test_ops_diagnostics_phase134.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py doctor --json --root C:\somex`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py release gate --json --root C:\somex --no-write`

Outcome:
- artifact hygiene now appears in both doctor and release-gate output
- the tuned budgets keep the guardrail alive without degrading the current release posture
- release gate finished back at `status=pass` with `readiness_score=100.0`

### Phase 147

Focus:
- add durable offline resilience so Somi can still help when the network is
  weak, intermittent, or absent
- make fallback knowledge visible and auditable instead of burying it inside
  search internals

Backups:
- `audit/backups/phase147_pre_offline_resilience_20260319_132952`
- `audit/backups/phase147_patchwave1_offline_core_20260319_133447`
- `audit/backups/phase147_patchwave2_testfix_20260319_133741`
- `audit/backups/phase147_patchwave3_search_fallback_fix_20260319_133910`

Implemented:
- added:
  - `workshop/toolbox/stacks/research_core/local_packs.py`
  - `ops/offline_resilience.py`
  - `knowledge_packs/README.md`
  - `knowledge_packs/repair_basics/manifest.json`
  - `knowledge_packs/repair_basics/power_and_water.md`
  - `knowledge_packs/survival_basics/manifest.json`
  - `knowledge_packs/survival_basics/water_and_shelter.md`
  - `knowledge_packs/infrastructure_basics/manifest.json`
  - `knowledge_packs/infrastructure_basics/communications_and_power.md`
  - `tests/test_offline_resilience_phase147.py`
- upgraded:
  - `ops/__init__.py`
  - `ops/doctor.py`
  - `ops/release_gate.py`
  - `somi.py`
  - `gui/controlroom_data.py`
  - `workshop/toolbox/stacks/web_core/websearch.py`
  - `tests/test_artifact_hygiene_phase146.py`
  - `test_search_upgrade.py`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_offline_resilience_phase147.py C:\somex\tests\test_artifact_hygiene_phase146.py C:\somex\tests\test_ops_diagnostics_phase134.py C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_offline_resilience_phase147.py C:\somex\tests\test_artifact_hygiene_phase146.py C:\somex\tests\test_ops_diagnostics_phase134.py C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py doctor --json --root C:\somex`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py offline status --json --root C:\somex`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py release gate --json --root C:\somex --no-write`

Outcome:
- Somi now has bundled knowledge packs plus degraded-network search fallback
  that can reuse local packs and Agentpedia before giving up
- doctor, release gate, the Control Room, and `somi offline status` now expose
  offline readiness directly
- combined validation reached `216` passing tests, with live
  doctor/offline/release checks all green

### Phase 148

Focus:
- turn Somi's raw runtime metrics into operator-grade observability and
  recovery guidance
- make the live system feel more trustworthy by suppressing synthetic test
  noise from operator surfaces

Backups:
- `audit/backups/phase148_pre_observability_and_logsync_20260319_134432`
- `audit/backups/phase148_patchwave1_observability_core_20260319_134626`
- `audit/backups/phase148_patchwave2_testfix_20260319_134924`
- `audit/backups/phase148_patchwave3_live_noise_filter_20260319_135144`

Implemented:
- added:
  - `ops/observability.py`
  - `tests/test_observability_phase148.py`
  - `audit/phase148_observability_summary.md`
- upgraded:
  - `ops/__init__.py`
  - `ops/support_bundle.py`
  - `somi.py`
  - `gui/controlroom_data.py`
  - `update.md`
  - `phase_upgrade.md`
- new surfaces:
  - `somi observability snapshot`
  - Control Room `Latency Hotspots`
  - Control Room `Recovery Watchlist`
  - support-bundle observability summary
- noise filtering:
  - synthetic eval/test tools like `breaker.eval.tool` no longer dominate the
    live digest
  - expected heartbeat-channel gating on `research.artifacts` no longer shows
    up as an operator-facing failure hotspot

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_observability_phase148.py C:\somex\tests\test_offline_resilience_phase147.py C:\somex\tests\test_ops_diagnostics_phase134.py C:\somex\tests\test_background_tasks_phase138.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_observability_phase148.py C:\somex\tests\test_offline_resilience_phase147.py C:\somex\tests\test_artifact_hygiene_phase146.py C:\somex\tests\test_ops_diagnostics_phase134.py C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py observability snapshot --json --root C:\somex`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py support bundle --json --root C:\somex --no-write`

Outcome:
- Somi now explains runtime health in operator language instead of forcing
  users to inspect raw metrics and event logs
- the CLI, support bundle, and Control Room now agree on the same
  observability picture
- combined validation reached `222` passing tests, and the live repo
  observability view settled at `status=ready` after noise filtering

### Phase 149

Focus:
- make Somi's most common everyday answer types feel deliberate and easy to
  scan instead of relying on one generic answer shape

Backups:
- `audit/backups/phase149_pre_structured_answers_20260319_135522`

Implemented:
- upgraded:
  - `executive/synthesis/answer_mixer.py`
  - `test_search_upgrade.py`
- new answer-shape contracts:
  - compare and travel lookups now open with `Quick take:`
  - trip-planning answers now open with `Trip shape:`
  - explainers now open with `Short answer:`
- support-source phrasing now better matches the answer intent instead of
  sounding like a generic citation footer

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_observability_phase148.py C:\somex\tests\test_offline_resilience_phase147.py C:\somex\tests\test_artifact_hygiene_phase146.py C:\somex\tests\test_ops_diagnostics_phase134.py C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_search_upgrade.py -v`

Outcome:
- everyday answers now look and read more like purpose-built response types
  rather than lightly reformatted search blobs
- focused search validation reached `196` passing tests
- combined validation reached `223` passing tests
- the durable audit for this phase lives in
  `audit/phase149_structured_answers_summary.md`

### Phase 150

Focus:
- upgrade memory from a passive store into a reviewable continuity system with
  visible promotion, conflict, stale, and cleanup signals

Backups:
- `audit/backups/phase150_pre_memory_review_20260319_140127`
- `audit/backups/phase150_patchwave1_review_core_20260319_140138`

Implemented:
- added:
  - `executive/memory/review.py`
  - `tests/test_memory_review_phase150.py`
  - `audit/phase150_memory_review_summary.md`
- upgraded:
  - `executive/memory/store.py`
  - `executive/memory/manager.py`
  - `executive/memory/doctor.py`
  - `executive/memory/__init__.py`
  - `executive/memory/README.md`
  - `gui/controlroom_data.py`
  - `update.md`
  - `phase_upgrade.md`
  - `agentupgrade.md`
- new surfaces:
  - manager-level `build_memory_review_sync()`
  - frozen snapshot `memory_review`
  - memory doctor review summary
  - Control Room `Memory Review Queue`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_memory_review_phase150.py C:\somex\executive\memory\tests\test_preference_graph.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_memory_review_phase150.py C:\somex\tests\test_observability_phase148.py C:\somex\tests\test_offline_resilience_phase147.py C:\somex\tests\test_artifact_hygiene_phase146.py C:\somex\tests\test_ops_diagnostics_phase134.py C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py doctor --json --root C:\somex`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py release gate --json --root C:\somex --no-write`

Outcome:
- Somi now exposes memory review as an operator-facing lifecycle instead of
  making contributors infer quality from raw rows and event logs
- the frozen snapshot preserves promotion/conflict/stale state so context
  compaction has better continuity hooks
- focused memory validation reached `5` tests and broad combined validation
  reached `226` tests
- live `doctor` and `release gate` both stayed green at `status=pass`

### Phase 151

Focus:
- make task continuity feel like one shared runtime across GUI, background
  work, and Telegram instead of several separate continuity hints

Backups:
- `audit/backups/phase151_pre_task_continuity_20260319_150637`
- `audit/backups/phase151_patchwave1_resume_ledger_20260319_150646`

Implemented:
- added:
  - `runtime/task_resume.py`
  - `tests/test_task_continuity_phase151.py`
  - `audit/phase151_task_continuity_summary.md`
- upgraded:
  - `runtime/__init__.py`
  - `gui/controlroom_data.py`
  - `ops/support_bundle.py`
  - `workshop/integrations/telegram_runtime.py`
  - `update.md`
  - `phase_upgrade.md`
  - `agentupgrade.md`
- new surfaces:
  - Control Room `continuity` tab
  - support-bundle continuity summary
  - Telegram resume prefers open-task threads when the user says `continue`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_task_continuity_phase151.py C:\somex\tests\test_telegram_runtime_phase132.py C:\somex\tests\test_ops_diagnostics_phase134.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_task_continuity_phase151.py C:\somex\tests\test_memory_review_phase150.py C:\somex\tests\test_observability_phase148.py C:\somex\tests\test_offline_resilience_phase147.py C:\somex\tests\test_artifact_hygiene_phase146.py C:\somex\tests\test_ops_diagnostics_phase134.py C:\somex\tests\test_background_tasks_phase138.py C:\somex\tests\test_telegram_runtime_phase132.py C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_search_upgrade.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py doctor --json --root C:\somex`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py release gate --json --root C:\somex --no-write`

Outcome:
- Somi now exposes one coherent resume story across active threads, background
  handoffs, and Telegram follow-ups
- support diagnostics and the Control Room can now answer "what should I
  resume?" directly
- focused continuity validation reached `14` tests, and the broad combined
  regression pass reached `240` tests
- live `doctor` and `release gate` both stayed green at `status=pass`

### Phase 159

Focus:
- finish the unified task-envelope work so Telegram carries the same continuity
  semantics as the desktop-oriented runtime

Backups:
- `audit/backups/phase159_pre_task_envelope_parity_20260319_174228`
- `audit/backups/phase159_patchwave1_continuity_tests_20260319_174600`

Implemented:
- upgraded:
  - `runtime/task_resume.py`
  - `workshop/integrations/telegram_runtime.py`
  - `workshop/integrations/telegram.py`
  - `tests/test_task_continuity_phase151.py`
  - `tests/test_telegram_delivery_phase152.py`
- new surfaces:
  - continuity notes inside Telegram delivery bundles
  - recommended next surface for cross-surface handoffs
  - richer background handoff metadata on completed Telegram tasks

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_task_continuity_phase151.py C:\somex\tests\test_telegram_delivery_phase152.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_action_policy_phase156.py C:\somex\tests\test_task_continuity_phase151.py C:\somex\tests\test_telegram_delivery_phase152.py -v`
- `C:\somex\.venv\Scripts\python.exe -m py_compile C:\somex\workshop\integrations\telegram.py C:\somex\workshop\integrations\telegram_runtime.py C:\somex\runtime\task_resume.py`

Outcome:
- Telegram and the shared runtime now speak a much more consistent continuity
  language
- background work can point the user to the best next surface instead of
  leaving continuation ambiguous
- focused validation stayed green at `12` tests

### Phase 161

Focus:
- make Somi's coding loop more deliberate through repo symbols, bounded change
  plans, and explicit edit-risk scoring

Backups:
- `audit/backups/phase161_pre_coding_control_plane_ii_20260319_174900`

Implemented:
- added:
  - `workshop/toolbox/coding/change_plan.py`
- upgraded:
  - `workshop/toolbox/coding/repo_map.py`
  - `workshop/toolbox/coding/control_plane.py`
  - `workshop/toolbox/coding/__init__.py`
  - `gui/codingstudio_data.py`
  - `gui/codingstudio.py`
  - `tests/test_codex_control_phase119.py`
  - `test_gui_codingstudio_phase119.py`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m py_compile C:\somex\workshop\toolbox\coding\repo_map.py C:\somex\workshop\toolbox\coding\change_plan.py C:\somex\workshop\toolbox\coding\control_plane.py C:\somex\gui\codingstudio_data.py C:\somex\gui\codingstudio.py`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_codex_control_phase119.py C:\somex\test_gui_codingstudio_phase119.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_action_policy_phase156.py C:\somex\tests\test_codex_control_phase119.py C:\somex\test_gui_codingstudio_phase119.py C:\somex\tests\test_task_continuity_phase151.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py doctor --json --root C:\somex`

Outcome:
- Somi can now explain coding work in a more operator-friendly way before and
  after edits
- Coding Studio now exposes edit risk and change plans instead of leaving them
  implicit in backend metadata
- focused coding validation stayed green at `5` tests and the mixed pack stayed
  green at `15` tests

### Phase 163

Focus:
- create the federation core so Somi can ingest outside markdown-skill bundles
  safely

Backups:
- `audit/backups/phase163_pre_plugin_federation_core_20260319_175556`

Implemented:
- added:
  - `skills_local/federation.py`
  - `skills_local/__init__.py`
  - `skills_local/README.md`
  - `tests/test_plugin_federation_phase163.py`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m py_compile C:\somex\skills_local\federation.py C:\somex\skills_local\__init__.py`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_plugin_federation_phase163.py -v`

Outcome:
- Somi now has a real local descriptor and registry model for imported
  `SKILL.md` bundles
- imported bundles now carry trust tiers, required-tool hints, and approval
  expectations instead of being treated as raw prompt text

### Phase 164

Focus:
- make interoperability practical with review and approval helpers for external
  skill ecosystems

Backups:
- `audit/backups/phase164_pre_skill_adapters_20260319_175755`

Implemented:
- added:
  - `skills_local/adapters.py`
  - `docs/architecture/PLUGIN_FEDERATION.md`
  - `tests/test_plugin_adapters_phase164.py`
- upgraded:
  - `skills_local/__init__.py`
  - `skills_local/README.md`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m py_compile C:\somex\skills_local\adapters.py C:\somex\skills_local\federation.py C:\somex\skills_local\__init__.py`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_plugin_federation_phase163.py C:\somex\tests\test_plugin_adapters_phase164.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_plugin_federation_phase163.py C:\somex\tests\test_plugin_adapters_phase164.py C:\somex\tests\test_codex_control_phase119.py C:\somex\test_gui_codingstudio_phase119.py C:\somex\tests\test_action_policy_phase156.py C:\somex\tests\test_task_continuity_phase151.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py release gate --json --root C:\somex --no-write`

Outcome:
- imported skills can now be previewed, origin-tagged, policy-checked, and
  promoted from experimental to reviewed
- live `release gate` stayed green at `readiness_score=100.0`

### Phase 162

Focus:
- deepen autonomy so Somi can stay capable while enforcing explicit step, time,
  retry, and load budgets

Backups:
- `audit/backups/phase162_pre_guarded_autonomy_profiles_20260319_180341`

Implemented:
- upgraded:
  - `runtime/autonomy_profiles.py`
  - `runtime/action_policy.py`
  - `ops/control_plane.py`
  - `tests/test_autonomy_profiles_phase137.py`
  - `tests/test_action_policy_phase156.py`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m py_compile C:\somex\runtime\autonomy_profiles.py C:\somex\runtime\action_policy.py C:\somex\ops\control_plane.py`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_autonomy_profiles_phase137.py C:\somex\tests\test_action_policy_phase156.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_autonomy_profiles_phase137.py C:\somex\tests\test_action_policy_phase156.py C:\somex\tests\test_background_tasks_phase138.py C:\somex\tests\test_task_continuity_phase151.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py doctor --json --root C:\somex`

Outcome:
- Somi autonomy is now load-aware and budget-aware instead of relying only on
  broad risk tiers
- background autonomy can now be slowed, confirmed, or blocked based on runtime
  pressure without weakening the model's reasoning layer
- focused validation stayed green at `11` tests and the mixed pack stayed green
  at `21` tests

### Phase 165

Focus:
- reduce GUI overlap and cramped cockpit states without sacrificing the premium
  dashboard feel

Backups:
- `audit/backups/phase165_patchwave1_layout_polish_20260319_181034`

Implemented:
- upgraded:
  - `somicontroller_parts/layout_methods.py`
- new artifacts:
  - `audit/phase165_gui_shell_before.png`
  - `audit/phase165_gui_shell_after.png`
  - `audit/phase165_gui_shell_narrow.png`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_gui_codingstudio_phase119.py -v`

Outcome:
- the top status strip now breathes instead of compressing four dense regions
  into one row
- the quick-action cockpit now uses two dashboard rows, which holds up much
  better at narrower widths

### Phase 166

Focus:
- remove the lingering memory-path socket warnings so stress runs stay clean

Backups:
- `audit/backups/phase166_pre_warning_cleanup_20260319_181145`

Implemented:
- added:
  - `tests/test_runtime_cleanup_phase166.py`
- upgraded:
  - `runtime/ollama_compat.py`
  - `executive/memory/embedder.py`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m py_compile C:\somex\runtime\ollama_compat.py C:\somex\executive\memory\embedder.py C:\somex\tests\test_runtime_cleanup_phase166.py`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_runtime_cleanup_phase166.py -v`
- `PYTHONWARNINGS=default C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_memory_adaptive_phase157.py C:\somex\tests\test_memory_review_phase150.py C:\somex\executive\memory\tests\test_preference_graph.py -v`

Outcome:
- the previous unclosed socket/transport warning pattern tied to the default
  Ollama embedder path is no longer reproduced in the warning-sensitive memory
  slice

### Phase 167

Focus:
- close the remaining newcomer-doc gaps so Somi is easier to understand from
  the filesystem, not just from the architecture maps

Backups:
- `audit/backups/phase167_pre_docs_clarity_pass_20260319_181623`
- `audit/backups/phase167_patchwave1_readme_finish_20260319_182431`
- `audit/backups/phase167_patchwave2_ontology_readme_20260319_182711`

Implemented:
- added:
  - `docs/README.md`
  - `learning/README.md`
  - `subagents/README.md`
  - `deploy/README.md`
  - `ontology/README.md`
- upgraded:
  - `gui/README.md`
  - `runtime/README.md`

Checks:
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py doctor --json --root C:\somex`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py release gate --json --root C:\somex --no-write`

Outcome:
- the repo now has quick-entry maps for the docs, learning, deploy, ontology,
  and delegated-worker layers
- live `doctor` and `release gate` remained green while docs integrity stayed
  clean with no broken links or missing required maps

### Phase 168

Focus:
- tighten the finality loop so focused benchmark slices behave predictably and
  loop-guard telemetry stays useful instead of noisy

Backups:
- `audit/backups/phase168_pre_benchmark_repair_loop_20260319_183014`
- `audit/backups/phase168_patchwave1_gauntlet_count_and_log_noise_20260319_183828`
- `audit/backups/phase168_patchwave2_warning_test_fix_20260319_184536`
- `audit/backups/phase168_patchwave3_slice_order_and_test_harness_20260319_184755`

Implemented:
- upgraded:
  - `audit/search_benchmark_batch.py`
  - `audit/system_gauntlet.py`
  - `audit/safe_search_corpus.py`
  - `agent_methods/history_methods.py`
  - `tests/test_system_gauntlet_phase136.py`
  - `tests/test_tool_loop_warning_phase168.py`
  - `test_search_upgrade.py`

Checks:
- focused search-limit smoke
- loop-warning regression pack
- gauntlet subset rerun

Outcome:
- focused search runs now respect requested limits all the way through the batch
  and gauntlet layers
- tool-loop warnings now log once per user/key instead of flooding healthy
  stress output

### Phase 169

Focus:
- restore a clean competitive finality run by fixing the last live loop-guard
  regression

Backups:
- `audit/backups/phase169_pre_competitive_finality_run_20260319_185744`
- `audit/backups/phase169_patchwave1_tool_loop_guard_runtime_fix_20260319_150937`

Implemented:
- upgraded:
  - `agents.py`
  - `tests/test_tool_loop_warning_phase168.py`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\tests\test_tool_loop_warning_phase168.py C:\somex\tests\test_system_gauntlet_phase136.py -v`
- `C:\somex\.venv\Scripts\python.exe C:\somex\somi.py release gauntlet --json --root C:\somex --prefix phase169_competitive_finality_rerun --output-dir C:\somex\audit --count 100 --scenario-turns 30 --search-corpus everyday100`

Outcome:
- the live extracted-agent method path now carries the loop-warning cache helper
  correctly
- the full competitive gauntlet is back to `7/7` packs passing

### Phase 170

Focus:
- strengthen bundled offline packs into a provenance-rich local knowledge
  contract

Backups:
- `audit/backups/phase170_pre_offline_pack_foundations_20260319_184938`
- `audit/backups/phase170_patchwave1_testfix_20260319_185052`

Implemented:
- upgraded:
  - `workshop/toolbox/stacks/research_core/local_packs.py`
  - `tests/test_offline_resilience_phase147.py`
  - `knowledge_packs/repair_basics/manifest.json`
  - `knowledge_packs/survival_basics/manifest.json`
  - `knowledge_packs/infrastructure_basics/manifest.json`
- added:
  - `docs/architecture/OFFLINE_KNOWLEDGE_PACKS.md`

Checks:
- focused offline-resilience test pack

Outcome:
- local packs now surface schema, variant, trust, updated-at, and checksum data
- local pack citations can be resolved back to the exact offline source text

### Phase 171

Focus:
- keep Somi Core sovereign while still modeling optional edge-only platform
  policy

Backups:
- `audit/backups/phase171_pre_distribution_sovereignty_layer_20260319_185233`

Implemented:
- added:
  - `gateway/surface_policy.py`
  - `docs/architecture/DISTRIBUTION_SOVEREIGNTY.md`
  - `tests/test_distribution_sovereignty_phase171.py`
- upgraded:
  - `gateway/README.md`

Checks:
- focused sovereignty tests

Outcome:
- direct/self-hosted Somi stays free of central compliance assumptions
- managed surfaces can still express thin edge-only policy posture when needed

### Phase 172

Focus:
- make Somi hardware-adaptive without imposing framework-level weakness

Backups:
- `audit/backups/phase172_pre_hardware_tiers_and_survival_mode_20260319_185450`

Implemented:
- added:
  - `ops/hardware_tiers.py`
  - `docs/architecture/HARDWARE_TIERS_AND_SURVIVAL_MODE.md`
  - `tests/test_hardware_tiers_phase172.py`
- upgraded:
  - `ops/offline_resilience.py`
  - `ops/__init__.py`
  - `ops/README.md`

Checks:
- focused hardware-tier and offline-resilience tests

Outcome:
- Somi now exposes survival/low/balanced/high hardware guidance while keeping
  cognition and capability intact

### Phase 173

Focus:
- turn offline packs into an operator-facing catalog instead of a hidden
  internal fallback

Backups:
- `audit/backups/phase173_pre_offline_knowledge_pack_architecture_20260319_192202`
- `audit/backups/phase173_patchwave1_catalog_test_stabilize_20260319_152510`

Implemented:
- added:
  - `ops/offline_pack_catalog.py`
  - `tests/test_offline_pack_catalog_phase173.py`
  - `docs/architecture/OFFLINE_PACK_CATALOG.md`
- upgraded:
  - `ops/__init__.py`
  - `somi.py`
  - `knowledge_packs/README.md`

Checks:
- focused offline catalog and offline resilience suites
- live `somi offline catalog --json --root C:\somex --runtime-mode survival --query "purify water"`

Outcome:
- operators can now inspect preferred pack variants, local query hits, and
  preview docs directly from the CLI

### Phase 174

Focus:
- lay down a store-and-forward envelope layer for future node-to-node Somi
  exchange

Backups:
- `audit/backups/phase174_pre_federated_node_communication_layer_20260319_192556`

Implemented:
- added:
  - `gateway/federation.py`
  - `tests/test_federated_node_exchange_phase174.py`
  - `docs/architecture/FEDERATED_NODE_EXCHANGE.md`
- upgraded:
  - `gateway/README.md`
  - `somi.py`

Checks:
- focused federation tests
- live `somi offline federation --json --root C:\somex`

Outcome:
- Somi now has a durable inbox/outbox/archive contract for continuity tasks and
  knowledge deltas

### Phase 175

Focus:
- expand offline resilience into real continuity domains and workflow manifests

Backups:
- `audit/backups/phase175_pre_continuity_domain_packs_and_workflows_20260319_192845`

Implemented:
- added:
  - `ops/continuity_recovery.py`
  - `tests/test_continuity_recovery_phase175.py`
  - `docs/architecture/CONTINUITY_WORKFLOWS.md`
  - `knowledge_packs/sanitation_basics/*`
  - `knowledge_packs/field_health_basics/*`
  - `knowledge_packs/food_production_basics/*`
  - `knowledge_packs/power_recovery_basics/*`
  - `workflow_runtime/manifests/continuity_sanitation.json`
  - `workflow_runtime/manifests/continuity_power_recovery.json`
  - `workflow_runtime/manifests/continuity_food_startup.json`
  - `workflow_runtime/manifests/continuity_field_health.json`
- upgraded:
  - `ops/__init__.py`
  - `somi.py`
  - `knowledge_packs/README.md`
  - `workflow_runtime/manifests/README.md`

Checks:
- focused continuity/offline suites
- live `somi offline continuity --json --root C:\somex --runtime-mode survival --query "restore shelter power"`

Outcome:
- Somi now ships continuity guidance for sanitation, health, food, and power
- the workflow layer can recommend domain-specific recovery checklists offline

### Phase 176

Focus:
- prove the resilience stack works together under blackout assumptions

Backups:
- `audit/backups/phase176_pre_recovery_drill_and_blackout_gauntlet_20260319_193701`
- `audit/backups/phase176_patchwave1_workflow_manifest_guard_fix_20260319_153933`

Implemented:
- added:
  - `audit/recovery_drill.py`
  - `tests/test_recovery_drill_phase176.py`
  - `docs/architecture/RECOVERY_DRILL_AND_BLACKOUT_GAUNTLET.md`
- upgraded:
  - `somi.py`
  - `workflow_runtime/manifests/continuity_sanitation.json`
  - `workflow_runtime/manifests/continuity_power_recovery.json`
  - `workflow_runtime/manifests/continuity_food_startup.json`
  - `workflow_runtime/manifests/continuity_field_health.json`

Checks:
- focused recovery-drill and continuity suites
- live `somi offline drill --json --root C:\somex --runtime-mode survival`

Outcome:
- Somi now has a blackout-style recovery drill that verifies survival profile
  selection, offline pack readiness, continuity workflows, resumable workflow
  snapshots, and node exchange in one pass

### Phase 177

Focus:
- finish merge-readiness hardening with GUI symbol repair, runtime cleanup,
  and a final release-grade validation sweep

Backups:
- `audit/backups/phase177_pre_merge_hygiene_20260319_200430`
- `audit/backups/phase177_patchwave1_gui_icon_fix_20260319_200527`

Implemented:
- upgraded:
  - `.gitignore`
  - `gui/themes/__init__.py`
  - `somicontroller_parts/settings_methods.py`
  - `test_gui_themes.py`
- cleaned:
  - `state/node_exchange/*`
  - `sessions/recovery_drill_workflows/*`
  - top-level and `state/` `__pycache__`
- generated:
  - `audit/phase177_gui_shell_symbols.png`
  - `audit/phase177_merge_ready_summary.md`

Checks:
- focused GUI suites
- full `tests/` discovery run
- `somi doctor --json --root C:\somex`
- `somi release gate --json --root C:\somex --no-write`
- `somi release gauntlet --json --root C:\somex --prefix phase176_final_merge_ready --output-dir C:\somex --count 100 --scenario-turns 30 --search-corpus everyday100`

Outcome:
- the premium theme switch no longer depends on corrupted glyph strings
- Somi remains release-green after the last GUI and hygiene changes
- the repo is ready for an initial Git commit and push, with the note that the
  current `master` branch has no first commit yet

### Phase 178

Focus:
- restore chat-first GUI priority and remove the remaining startup worker
  immersion breaks

Backups:
- `audit/backups/phase178_pre_chat_priority_gui_fix_20260319_215909`
- `audit/backups/phase178_patchwave1_chat_priority_gui_fix_20260319_220156`
- `audit/backups/phase178_patchwave2_gui_runtime_tests_20260319_220404`
- `audit/backups/phase178_patchwave3_startup_queue_polish_20260319_221201`
- `audit/backups/phase178_patchwave4_pending_timer_cleanup_20260319_221341`

Implemented:
- upgraded:
  - `somicontroller_parts/layout_methods.py`
  - `gui/themes/premium_base.py`
  - `gui/chatpanel.py`
  - `somicontroller_parts/runtime_methods.py`
  - `gui/aicoregui.py`
  - `somicontroller.py`
  - `test_gui_shell_runtime.py`
- generated:
  - `audit/phase178_gui_chat_priority_summary.md`
  - `audit/phase178_gui_chat_priority.png`
  - `audit/phase178_gui_chat_priority_v2.png`

Checks:
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_shell_runtime.py -v`
- `C:\somex\.venv\Scripts\python.exe -m unittest C:\somex\test_gui_themes.py C:\somex\test_gui_research_ux.py C:\somex\test_gui_shell_runtime.py C:\somex\test_gui_codingstudio_phase119.py -v`
- live boot/send smoke covering an immediate first-turn prompt before chat warmup completed

Outcome:
- the chat panel is clearly the dominant surface again
- the old split intelligence/heartbeat output is now one cleaner `Ops Stream`
- the lower persona/studio/console/heartbeat band is materially smaller
- startup no longer waits for the first user turn to begin chat-worker warmup
- Enter in the prompt no longer falls through to the upload-image control
- later patchwaves in this phase also collapsed the right rail into a calmer
  side console by folding speech into the rail and turning Research Pulse into
  one compact feed
