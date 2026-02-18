# speech/

Modular speech pipeline:

Mic -> VAD turn detection -> STT final transcript -> `Agent.generate_response()` -> Pocket TTS -> Speaker.

## Guarantees
- Speech layer never performs tool routing/memory/reminder parsing/websearch.
- Agent calls only happen on finalized STT utterances.
- Monotonic `turn_id` stale-guard isolation is used across async boundaries.
- Tier0 echo suppression: STT is disabled while assistant is speaking.
- Barge-in cancels in-flight turns and calls `sd.stop()` immediately.

## Run
```bash
python -m speech.tools.run_speech --agent-name "Name: Somi"
```

## Tools
- `python -m speech.tools.test_tts`
- `python -m speech.tools.test_latency`
- `python -m speech.tools.test_bargein`
- `python -m speech.tools.test_echo`

- `python -m speech.tools.test_simulation`
- `python -m speech.tools.test_orchestrator_sim`
