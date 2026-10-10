"""edge-tts failing (Microsoft 403s, 2026-10-10) must fall back to Kokoro, then the
Windows voice, skip edge-tts until the retry window passes, then use edge-tts again."""
import asyncio
from unittest.mock import patch

import edc.audio.tts_engine as tts


class _FailingCommunicate:
    def __init__(self, *a, **kw):
        pass

    async def stream(self):
        raise RuntimeError("403")
        yield


class _WorkingCommunicate:
    def __init__(self, *a, **kw):
        pass

    async def stream(self):
        yield {"type": "audio", "data": b"mp3"}


def test_fallback_chain_then_recovery():
    loop = asyncio.new_event_loop()
    tts._edge_down_until = 0.0
    tts._kokoro_failed = False
    try:
        with patch("edge_tts.Communicate", _FailingCommunicate):
            wav, sr = tts._synth_wav(loop, "Fallback test.", "en-US-GuyNeural", "+0%")
        assert wav[:4] == b"RIFF" and sr == 24000  # Kokoro's rate
        assert tts._edge_down_until > 0

        # Inside the retry window edge-tts isn't called; Kokoro broken -> Windows voice.
        tts._kokoro_failed = True
        with patch("edge_tts.Communicate", side_effect=AssertionError("edge called")):
            wav, sr = tts._synth_wav(loop, "Still down.", "en-US-GuyNeural", "+0%")
        assert wav[:4] == b"RIFF" and sr == 16000  # Windows OneCore rate

        # Window over and edge-tts fixed: primary path is used again.
        tts._edge_down_until = 0.0
        with patch("edge_tts.Communicate", _WorkingCommunicate), \
             patch("edc.audio._alert_edge_proc._mp3_to_wav_bytes", return_value=(b"edge", 22050)):
            assert tts._synth_wav(loop, "Back.", "en-US-GuyNeural", "+0%") == (b"edge", 22050)
    finally:
        tts._edge_down_until = 0.0
        tts._kokoro_failed = False
        loop.close()


def test_every_edge_voice_maps_to_a_kokoro_voice():
    engine = tts.TTSEngine()
    used = set(tts._ALERT_VOICE_POOL) | {tts.TTSEngine._SQUADRON_VOICE}
    engine._comms_voice_pool = []
    with patch.object(tts, "QThread"), patch.object(tts, "TTSWorker"), patch.object(tts, "CommsWorker"):
        engine.start()
    used |= set(engine._comms_voice_pool)
    assert used <= set(tts._KOKORO_VOICE)

