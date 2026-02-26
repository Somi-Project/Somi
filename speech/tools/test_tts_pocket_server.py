import time

from speech.io.audio_out import AudioOut
from speech.metrics.log import logger
from speech.tts.tts_pocket_server import PocketTTSServerTTS


def main():
    tts = PocketTTSServerTTS()
    audio_out = AudioOut()
    pcm, sr = tts.synthesize("hello")
    logger.info("Pocket server TTS test pcm=%s sr=%s", getattr(pcm, "shape", None), sr)
    audio_out.play(pcm, sr)
    time.sleep(1.5)


if __name__ == "__main__":
    main()
