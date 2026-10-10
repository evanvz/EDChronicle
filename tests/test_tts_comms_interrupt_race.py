"""Regression test for the comms-channel interrupt race: interrupt() firing
mid-synthesis (e.g. a StartJump cutting the departed system's chatter) must
not get silently wiped by _speak_one() clearing the flag right before
playback -- confirmed live, the previous system's announcement kept playing
after a jump."""
import asyncio
from unittest.mock import patch

from edc.audio.tts_engine import CommsWorker


def _worker():
    import queue
    w = CommsWorker(queue.PriorityQueue(), rate=210, volume=0.5)
    w._loop = asyncio.new_event_loop()
    return w


def test_interrupt_during_synthesis_skips_playback():
    worker = _worker()

    def _synth(*a, **kw):
        # Simulates interrupt() firing on the main thread while synthesis is
        # still running.
        worker._interrupt.set()
        return b"wav", 24000

    with patch("edc.audio.tts_engine._synth_wav", _synth),          patch("edc.audio._comms_edge_proc._dsp_and_play") as mock_play,          patch("edc.audio.audio_devices.resolve_playback_device_id", return_value=None):
        worker._speak_one("Test message.", "en-US-GuyNeural")

    mock_play.assert_not_called()


def test_no_interrupt_plays_normally():
    worker = _worker()

    with patch("edc.audio.tts_engine._synth_wav", return_value=(b"wav", 24000)),          patch("edc.audio._comms_edge_proc._dsp_and_play") as mock_play,          patch("edc.audio.audio_devices.resolve_playback_device_id", return_value=None):
        worker._speak_one("Test message.", "en-US-GuyNeural")

    mock_play.assert_called_once()
