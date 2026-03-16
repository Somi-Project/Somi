# config/audiosettings.py
import re

# Wake word configuration
WAKE_WORDS = [
    "hey assistant",
    "hello assistant",
    "ok assistant",
    "wake up",
    "hi"
]
WAKE_WORD_PATTERNS = [re.compile(rf'\b{re.escape(word)}\b', re.IGNORECASE) for word in WAKE_WORDS]

# Cessation words for interrupting playback
CESSATION_WORDS = [
    "stop",
    "okay that's enough"
]
CESSATION_WORD_PATTERNS = [re.compile(rf'\b{re.escape(word)}\b', re.IGNORECASE) for word in CESSATION_WORDS]

# Wake word session timeout (seconds)
WAKE_SESSION_TIMEOUT = 300.0

# Audio processing settings
SAMPLE_RATE = 16000
CHANNELS = 1
SEGMENT_DURATION = 3.0
SILENCE_THRESHOLD = 0.05
MIN_AUDIO_LENGTH = 1.0
AUDIO_GAIN = 5.0
CHUNK_DURATION = 0.1
MAX_TRANSCRIPTION_LENGTH = 100

# Audio file saving setting
SAVE_AUDIO_FILES = False  # True to save audio files permanently, False to delete after playback

# Model settings
WHISPER_MODEL = "base.en"
OLLAMA_MODEL = "gemma3:4b"
TTS_MODEL = "tts_models/en/ljspeech/vits"
OLLAMA_ENDPOINT = "http://localhost:11434/api/generate"

# File paths
TEMP_AUDIO = "temp_speech.wav"
LAST_AUDIO = "last_speech.wav"
DEBUG_AUDIO = "debug_audio.wav"
OUTPUT_DIR = "audio_outputs"  # Directory for Coqui output files

# Cleanup settings
FILE_RETENTION_SECONDS = 360  # Delete files older than time in seconds
CLEANUP_INTERVAL = 300  # Run cleanup every 5 minutes

# InChime sound settings for wake word confirmation ( "Ding...ding...ding!")
INCHIME_FREQUENCIES = [1000, 1500, 2000]  # Hz, higher-pitched for bright, melodic "Ding"
INCHIME_DURATION = 0.9                    # Seconds, longer to accommodate three distinct tones
INCHIME_AMPLITUDE = 0.2                   # Gentle amplitude for pleasant sound
INCHIME_TONE_DURATION = 0.2               # Seconds, duration of each "Ding"
INCHIME_PAUSE = 0.15                      # Seconds, pause between tones

# OutChime sound settings for session end ("Dong...dong")
OUTCHIME_FREQUENCIES = [200, 300]         # Hz, lower-pitched for deep, resonant "Dong"
OUTCHIME_DURATION = 0.6                   # Seconds, shorter for two tones
OUTCHIME_AMPLITUDE = 0.15                 # Subtle amplitude for calming effect
OUTCHIME_TONE_DURATION = 0.2              # Seconds, duration of each "Dong"
OUTCHIME_PAUSE = 0.2                      # Seconds, pause between tones

# Greeting message for startup
GREETING_MESSAGE = "Hi! My name is Somi and I'm here to help you - please say a trigger word to start chatting"