"""Tests for edc.audio.tts_phrases.pick() -- pure function, no Qt needed."""
import edc.audio.tts_phrases as tts_phrases
from edc.audio.tts_phrases import pick


def test_empty_templates_returns_empty_string():
    assert pick([]) == ""


def test_single_template_returns_it_every_time():
    templates = ["Only option."]
    for _ in range(10):
        assert pick(templates) == "Only option."


def test_placeholder_is_filled_from_kwargs():
    templates = ["Bounty {credits} credits from {faction}."]
    result = pick(templates, credits="1,000", faction="Aisling Duval")
    assert result == "Bounty 1,000 credits from Aisling Duval."


def test_missing_placeholder_is_stripped_cleanly():
    templates = ["Hello {name}, welcome."]
    result = pick(templates)
    assert result == "Hello , welcome."


def test_never_repeats_the_same_template_twice_in_a_row():
    templates = ["A", "B", "C", "D", "E"]
    tts_phrases._last_picked.clear()
    previous = pick(templates)
    for _ in range(50):
        current = pick(templates)
        assert current != previous
        previous = current


def test_pools_track_last_pick_independently():
    pool_a = ["A1", "A2"]
    pool_b = ["B1", "B2"]
    tts_phrases._last_picked.clear()
    a_result = pick(pool_a)
    b_result = pick(pool_b)
    # Picking from pool_b must not affect pool_a's own last-picked tracking.
    assert tts_phrases._last_picked[id(pool_a)] == a_result
    assert tts_phrases._last_picked[id(pool_b)] == b_result


def test_all_duplicate_templates_does_not_crash():
    templates = ["Same.", "Same.", "Same."]
    tts_phrases._last_picked.clear()
    for _ in range(5):
        assert pick(templates) == "Same."
