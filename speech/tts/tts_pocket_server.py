from __future__ import annotations

import io
import json
import wave
from urllib import error, request

import numpy as np

from speech.config import (
    POCKET_TTS_RESPONSE_FORMAT,
    POCKET_TTS_SERVER_URL,
    POCKET_TTS_SPEED,
    POCKET_TTS_TIMEOUT_S,
    POCKET_TTS_VOICE,
    TTS_ALLOW_FALLBACK_TONE,
    TTS_SAMPLE_RATE,
)
from speech.metrics.log import logger


class PocketTTSServerTTS:
    def synthesize(self, text: str):
        text = (text or "").strip()
        if not text:
            return np.zeros(1, dtype=np.float32), TTS_SAMPLE_RATE

        payload = {
            "input": text,
            "voice": POCKET_TTS_VOICE,
            "response_format": POCKET_TTS_RESPONSE_FORMAT,
            "speed": POCKET_TTS_SPEED,
            "stream": False,
        }

        try:
            wav_bytes = self._request_tts(payload)
            pcm, sr = self._decode_wav(wav_bytes)
            return pcm, sr
        except Exception as exc:
            logger.error("PocketTTSServerTTS synth failed err=%r", exc)
            if not TTS_ALLOW_FALLBACK_TONE:
                raise RuntimeError("PocketTTSServerTTS unavailable and fallback tone disabled") from exc
            return self._fallback_tone(text)

    def _request_tts(self, payload: dict) -> bytes:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            POCKET_TTS_SERVER_URL,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=POCKET_TTS_TIMEOUT_S) as resp:
                return resp.read()
        except error.URLError as exc:
            raise RuntimeError(f"HTTP request failed to {POCKET_TTS_SERVER_URL}") from exc

    def _decode_wav(self, wav_bytes: bytes):
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            nchannels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            sr = wf.getframerate()
            nframes = wf.getnframes()
            raw = wf.readframes(nframes)

        if nchannels not in (1, 2):
            raise RuntimeError(f"Unsupported channel count: {nchannels}")

        if sampwidth == 2:
            pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        elif sampwidth == 1:
            pcm = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
        else:
            raise RuntimeError(f"Unsupported sample width: {sampwidth}")

        if nchannels == 2:
            pcm = pcm.reshape(-1, 2).mean(axis=1)

        pcm = np.clip(pcm, -1.0, 1.0).astype(np.float32, copy=False)
        if pcm.size == 0:
            return np.zeros(1, dtype=np.float32), int(sr)
        return pcm, int(sr)

    def _fallback_tone(self, text: str):
        sr = TTS_SAMPLE_RATE
        duration = max(0.2, min(2.5, 0.03 * len(text)))
        t = np.linspace(0, duration, int(sr * duration), False)
        tone = 0.05 * np.sin(2 * np.pi * 440 * t)
        return tone.astype(np.float32), sr
