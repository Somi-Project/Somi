# Chat Flow Regression Report

- timestamp: 2026-03-08 16:47:50
- total_turns: 10
- total_elapsed_ms: 72
- overall_ok: true
- history_messages_checked: 7
- selected_url: https://news.example/npu

## Checks
- turn_count_10: pass
- no_failures: pass
- followup_rewrite_open_2: pass
- selected_url_persisted: pass
- history_compaction_triggered: pass

## Turn Samples
- 1. Give me the latest AI chip news. -> (52 ms) Simulated response: Give me the latest AI chip news.
- 2. open 2 -> (2 ms) Simulated response: open 2
- 3. what were the key claims in that story? -> (2 ms) Simulated response: what were the key claims in that story?
- 4. compare that with result 1 -> (2 ms) Simulated response: compare that with result 1
- 5. summarize this URL https://example.com/analysis -> (2 ms) Simulated response: summarize this URL https://example.com/analysis
- 6. switch topic: what is a good python study plan? -> (1 ms) Simulated response: switch topic: what is a good python study plan?
- 7. make that into 3 steps -> (1 ms) Simulated response: make that into 3 steps
- 8. add one warning about burnout -> (2 ms) Simulated response: add one warning about burnout
- 9. quick recap of our chat so far -> (2 ms) Simulated response: quick recap of our chat so far
- 10. what should i ask next? -> (1 ms) Simulated response: what should i ask next?

## Tool Query Trace
- Give me the latest AI chip news.
- summarize this URL: https://news.example/npu
- summarize this URL: https://news.example/npu
- summarize this URL: https://news.example/npu
- summarize this URL: https://example.com/analysis
