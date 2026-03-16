# speech

Modular speech pipeline:
Mic -> VAD -> STT -> agent response -> TTS -> speaker.

## Quick Start
- `python -m speech.tools.doctor`
- `python -m speech.tools.test_tts_local --play`
- `python -m speech.tools.test_stt_local --roundtrip`
- `python -m speech.tools.run_speech --doctor`

## Defaults
- TTS: local `pyttsx3`
- STT: local `faster-whisper` / Whisper
- Device selection: `sounddevice`
- Network TTS is optional

## Subsystems
- `brain/`: orchestration bridge.
- `detect/`: VAD, echo, barge-in.
- `io/`: input/output device handling.
- `stt/`: speech-to-text engines.
- `tts/`: text-to-speech engines.
- `tools/`: runners and diagnostics.
