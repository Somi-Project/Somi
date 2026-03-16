from __future__ import annotations

import pytest

np = pytest.importorskip("numpy", reason="numpy unavailable in environment")
AudioOut = pytest.importorskip("speech.io.audio_out", reason="audio stack unavailable").AudioOut


def test_linear_resample_changes_length() -> None:
    pcm = np.sin(2 * np.pi * 440 * np.linspace(0, 1, 24000, endpoint=False)).astype(np.float32)
    out = AudioOut._resample_linear(pcm, 24000, 48000)
    assert out.dtype == np.float32
    assert out.shape[0] == 48000
