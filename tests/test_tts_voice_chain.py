"""Kokoro is the speech engine; if it's unavailable the Windows voice takes over."""
import asyncio
from unittest.mock import patch

import edc.audio.tts_engine as tts


def test_kokoro_then_windows_voice():
    loop = asyncio.new_event_loop()
    tts._kokoro_failed = False
    try:
        wav, sr = tts._synth_wav(loop, "Kokoro test.", "en-US-GuyNeural")
        assert wav[:4] == b"RIFF" and sr == 24000  # Kokoro's rate

        tts._kokoro_failed = True
        wav, sr = tts._synth_wav(loop, "Windows test.", "en-US-GuyNeural")
        assert wav[:4] == b"RIFF" and sr == 16000  # Windows OneCore rate
    finally:
        tts._kokoro_failed = False
        loop.close()


def test_every_voice_id_maps_to_a_kokoro_voice():
    engine = tts.TTSEngine()
    used = set(tts._ALERT_VOICE_POOL) | {tts.TTSEngine._SQUADRON_VOICE}
    engine._comms_voice_pool = []
    with patch.object(tts, "QThread"), patch.object(tts, "TTSWorker"), patch.object(tts, "CommsWorker"):
        engine.start()
    used |= set(engine._comms_voice_pool)
    assert used <= set(tts._KOKORO_VOICE)


def test_ship_computer_fx_keeps_peak_and_length():
    import numpy as np
    sr = 24000
    x = (0.5 * np.sin(2 * np.pi * 220 * np.arange(sr) / sr)).astype("float32")
    y = tts._ship_computer_fx(x, sr)
    assert len(y) == len(x) and y.dtype == np.float32
    assert abs(np.abs(y).max() - 0.5) < 1e-4
    assert not np.allclose(x, y)
    assert len(tts._ship_computer_fx(np.zeros(0, dtype="float32"), sr)) == 0
