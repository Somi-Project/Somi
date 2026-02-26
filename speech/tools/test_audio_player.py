from __future__ import annotations

import pytest

np = pytest.importorskip("numpy", reason="numpy unavailable")
playback = pytest.importorskip("handlers.audio.playback", reason="audio stack unavailable")


def test_resample_linear_length() -> None:
    pcm = np.sin(2 * np.pi * 220 * np.linspace(0, 1, 22050, endpoint=False)).astype(np.float32)
    out = playback.AudioPlayer._resample_linear(pcm, 22050, 44100)
    assert out.shape[0] == 44100
    assert out.dtype == np.float32
