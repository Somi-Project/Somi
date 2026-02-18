"""Configuration defaults for the modular speech subsystem."""

SAMPLE_RATE = 16000
EXPECTED_STT_SR = 16000
FRAME_MS = 20
SILENCE_MS = 500
MAX_UTTERANCE_S = 12
PREROLL_MS = 200
AUDIO_GAIN = 1.0

VAD_RMS_THRESHOLD = 0.015  # Tunable based on room noise
BARGEIN_RMS_THRESHOLD = 0.03  # Tunable for speaker leakage and mic sensitivity
BARGEIN_CONSEC_FRAMES = 6  # Tunable for barge-in strictness
ECHO_POLICY = "tier0"

BACKCHANNEL_AFTER_MS = 800
BACKCHANNEL_WAV = "speech/assets/ack.wav"

STT_PREFER_FAST = True
WHISPER_MODEL_NAME = "base"

TTS_BACKEND = "pocket"
TTS_SAMPLE_RATE = 24000
TTS_ALLOW_FALLBACK_TONE = False
TTS_MAX_CHARS_PER_CHUNK = 220

AGENT_NAME_DEFAULT = "Name: Somi"
USER_ID_DEFAULT = "default_user"
USE_STUDIES_DEFAULT = False
AGENT_TIMEOUT_S = 45

PLAYBACK_SLEEP_SLICE_MS = 40

LOG_PATH = "sessions/logs/speech.log"
METRICS_DIR = "sessions/speech_runs"
