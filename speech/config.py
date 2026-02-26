"""Configuration defaults for the modular speech subsystem."""

from config.settings import (
    AUDIO_OUTPUT_BLOCKSIZE,
    BARGE_IN_FRAMES,
    BARGE_IN_RMS_THRESHOLD,
    PIPER_CONFIG_PATH,
    PIPER_MODEL_PATH,
    TTS_ENGINE,
    TTS_STREAM_CHUNK_MS,
    VAD_MIN_UTTERANCE_MS,
    VAD_RMS_THRESHOLD,
    VAD_SPEECH_HANGOVER_MS,
)

# Backward-compatibility aliases retained for older speech modules.
# Keep these names exported even when newer settings use BARGE_IN_* naming.
BARGEIN_RMS_THRESHOLD = BARGE_IN_RMS_THRESHOLD
BARGEIN_CONSEC_FRAMES = BARGE_IN_FRAMES
ECHO_POLICY = "tier0"
TTS_MAX_CHARS_PER_CHUNK = 220

SAMPLE_RATE = 16000
EXPECTED_STT_SR = 16000
FRAME_MS = 20
SILENCE_MS = VAD_SPEECH_HANGOVER_MS
MAX_UTTERANCE_S = 12
PREROLL_MS = 120
AUDIO_GAIN = 1.0

VAD_RMS_THRESHOLD = 0.008  # Tunable based on room noise

BACKCHANNEL_AFTER_MS = 800
BACKCHANNEL_WAV = "speech/assets/ack.wav"

STT_PREFER_FAST = True
WHISPER_MODEL_NAME = "base"

TTS_BACKEND = "pocket_server"
TTS_SAMPLE_RATE = 24000
TTS_ALLOW_FALLBACK_TONE = True
POCKET_TTS_SERVER_URL = "http://127.0.0.1:8001/v1/audio/speech"
POCKET_TTS_VOICE = "nova"
POCKET_TTS_RESPONSE_FORMAT = "wav"
POCKET_TTS_SPEED = 1.0
POCKET_TTS_TIMEOUT_S = 30

AGENT_NAME_DEFAULT = "Name: Somi"
USER_ID_DEFAULT = "default_user"
USE_STUDIES_DEFAULT = False
AGENT_TIMEOUT_S = 45

PLAYBACK_SLEEP_SLICE_MS = 20

LOG_PATH = "sessions/logs/speech.log"
METRICS_DIR = "sessions/speech_runs"
