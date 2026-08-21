"""Tests for the randomized radio signal-quality DSP in
edc/audio/_comms_edge_proc.py -- pure numpy functions, no audio
hardware/subprocess/network needed."""
import numpy as np
import pytest

from edc.audio._comms_edge_proc import (
    _SIGNAL_QUALITY_PRESETS, _pick_signal_quality, _apply_dropouts,
)


def test_all_presets_have_required_keys():
    for preset in _SIGNAL_QUALITY_PRESETS:
        assert set(preset.keys()) == {"name", "weight", "drive", "noise", "dropout_chance"}
        assert preset["weight"] > 0
        assert preset["drive"] > 0
        assert preset["noise"] >= 0
        assert 0.0 <= preset["dropout_chance"] <= 1.0


def test_pick_signal_quality_always_returns_a_known_preset():
    for _ in range(50):
        picked = _pick_signal_quality()
        assert picked in _SIGNAL_QUALITY_PRESETS


def test_pick_signal_quality_produces_variety_over_many_draws():
    # Weighted random, but with 50 draws across 4 presets we should see
    # more than just one preset picked every time (regression against a
    # bug that always returns the first/highest-weight entry).
    names = {_pick_signal_quality()["name"] for _ in range(200)}
    assert len(names) > 1


def test_zero_chance_never_applies_dropout():
    sr = 22050
    data = np.ones(sr, dtype="float32")
    for _ in range(20):
        result = _apply_dropouts(data, sr, chance=0.0)
        assert np.array_equal(result, data)


def test_certain_chance_applies_a_dropout():
    sr = 22050
    data = np.ones(sr, dtype="float32")
    result = _apply_dropouts(data, sr, chance=1.0)
    # Some portion of the signal must be attenuated below the original 1.0
    # amplitude -- a dropout occurred somewhere in the waveform.
    assert np.min(result) < 0.5


def test_dropout_does_not_mutate_input_array():
    sr = 22050
    data = np.ones(sr, dtype="float32")
    original = data.copy()
    _apply_dropouts(data, sr, chance=1.0)
    assert np.array_equal(data, original)


def test_short_audio_is_returned_unchanged_even_at_certain_chance():
    sr = 22050
    data = np.ones(int(sr * 0.1), dtype="float32")  # well under the 0.3s floor
    result = _apply_dropouts(data, sr, chance=1.0)
    assert np.array_equal(result, data)


def test_dropout_never_fully_silences_the_window():
    # A weak signal fades, it doesn't cut to instant dead air -- the
    # attenuated floor should be a faint residual, not zero.
    sr = 22050
    data = np.ones(sr, dtype="float32")
    result = _apply_dropouts(data, sr, chance=1.0)
    nonzero_min = np.min(result[result < 0.99])
    assert nonzero_min > 0.0
