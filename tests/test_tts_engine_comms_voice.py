"""Tests for TTSEngine.speak_comms()'s voice-pool selection -- no Qt/thread
needed, TTSEngine.__init__ only sets plain attributes and a queue.PriorityQueue,
never starts anything until start() is called."""
from edc.audio.tts_engine import TTSEngine


def _make_engine(pool):
    engine = TTSEngine()
    engine._comms_enabled = True
    engine._comms_voice_pool = pool
    return engine


def _last_queued_voice(engine):
    item = engine._comms_queue.get_nowait()
    # (priority, counter, text, voice_id)
    return item[3]


def test_never_repeats_the_same_comms_voice_twice_in_a_row():
    pool = ["voiceA", "voiceB", "voiceC", "voiceD", "voiceE"]
    engine = _make_engine(pool)
    previous = None
    for _ in range(50):
        engine.speak_comms("Test message.")
        current = _last_queued_voice(engine)
        if previous is not None:
            assert current != previous
        previous = current


def test_single_voice_pool_returns_it_every_time():
    engine = _make_engine(["only-voice"])
    for _ in range(5):
        engine.speak_comms("Test message.")
        assert _last_queued_voice(engine) == "only-voice"


def test_empty_pool_queues_none_voice():
    engine = _make_engine([])
    engine.speak_comms("Test message.")
    assert _last_queued_voice(engine) is None


def test_disabled_comms_does_not_queue():
    engine = _make_engine(["voiceA", "voiceB"])
    engine._comms_enabled = False
    engine.speak_comms("Test message.")
    assert engine._comms_queue.empty()


def test_blank_text_does_not_queue():
    engine = _make_engine(["voiceA", "voiceB"])
    engine.speak_comms("   ")
    assert engine._comms_queue.empty()
