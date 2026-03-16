"""Configuration defaults for the modular speech subsystem."""

from config.settings import AUDIO_OUTPUT_BLOCKSIZE
from speech.runtime_settings import load_speech_runtime_settings

_SETTINGS = load_speech_runtime_settings()

SAMPLE_RATE = int(_SETTINGS.sample_rate)
EXPECTED_STT_SR = int(_SETTINGS.sample_rate)
FRAME_MS = int(_SETTINGS.frame_ms)
MAX_UTTERANCE_S = 12
PREROLL_MS = 120
AUDIO_GAIN = 1.0

VAD_RMS_THRESHOLD = float(_SETTINGS.vad_rms_threshold)
VAD_SPEECH_HANGOVER_MS = int(_SETTINGS.vad_speech_hangover_ms)
VAD_MIN_UTTERANCE_MS = int(_SETTINGS.vad_min_utterance_ms)
SILENCE_MS = VAD_SPEECH_HANGOVER_MS
BARGEIN_RMS_THRESHOLD = float(_SETTINGS.barge_in_rms_threshold)
BARGEIN_CONSEC_FRAMES = int(_SETTINGS.barge_in_frames)
ECHO_POLICY = "tier0"

BACKCHANNEL_AFTER_MS = 800
BACKCHANNEL_WAV = "speech/assets/ack.wav"

STT_PREFER_FAST = True
WHISPER_MODEL_NAME = str(_SETTINGS.stt_model)

TTS_BACKEND = str(_SETTINGS.tts_provider)
TTS_SAMPLE_RATE = 24000
TTS_ALLOW_FALLBACK_TONE = True
TTS_MAX_CHARS_PER_CHUNK = 220
POCKET_TTS_SERVER_URL = str(_SETTINGS.pocket_server_url)
POCKET_TTS_VOICE = "nova"
POCKET_TTS_RESPONSE_FORMAT = "wav"
POCKET_TTS_SPEED = 1.0
POCKET_TTS_TIMEOUT_S = 30
PIPER_MODEL_PATH = str(_SETTINGS.piper_model_path)
PIPER_CONFIG_PATH = str(_SETTINGS.piper_config_path)

AGENT_NAME_DEFAULT = "Name: Somi"
USER_ID_DEFAULT = "default_user"
USE_STUDIES_DEFAULT = False
AGENT_TIMEOUT_S = 45

PLAYBACK_SLEEP_SLICE_MS = 20

LOG_PATH = "sessions/logs/speech.log"
METRICS_DIR = "sessions/speech_runs"
