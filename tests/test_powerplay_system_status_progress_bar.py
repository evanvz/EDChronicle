"""_progress_bar_text() renders Frontier's Control Points tug-of-war
(qty/threshold) as a text bar -- pure function, no Qt dependency."""
from edc.ui.panels.powerplay_system_status_panel import (
    _progress_bar_text, _prediction_color, _COLOR_FAVORABLE, _COLOR_UNFAVORABLE, _COLOR_NEUTRAL,
)


def test_zero_progress_renders_empty_bar():
    text = _progress_bar_text(0, 6088)
    assert text == "░░░░░░░░░░ 0%"


def test_full_progress_renders_full_bar():
    text = _progress_bar_text(6088, 6088)
    assert text == "██████████ 100%"


def test_over_threshold_clamps_to_100_percent():
    text = _progress_bar_text(9000, 6088)
    assert text == "██████████ 100%"


def test_half_progress_renders_half_bar():
    text = _progress_bar_text(3044, 6088)
    assert text == "█████░░░░░ 50%"


def test_missing_threshold_renders_dash():
    assert _progress_bar_text(30, None) == "—"


def test_missing_qty_renders_dash():
    assert _progress_bar_text(None, 6088) == "—"


def test_zero_threshold_renders_dash_not_divide_by_zero():
    assert _progress_bar_text(30, 0) == "—"


def test_fortify_is_favorable():
    assert _prediction_color("FORTIFY") == _COLOR_FAVORABLE


def test_expanded_and_negated_are_favorable():
    assert _prediction_color("EXPANDED") == _COLOR_FAVORABLE
    assert _prediction_color("NEGATED") == _COLOR_FAVORABLE


def test_undermine_and_fail_are_unfavorable():
    assert _prediction_color("UNDERMINE") == _COLOR_UNFAVORABLE
    assert _prediction_color("FAIL") == _COLOR_UNFAVORABLE


def test_pass_is_neutral():
    assert _prediction_color("PASS") == _COLOR_NEUTRAL


def test_unknown_prediction_defaults_to_neutral():
    assert _prediction_color("") == _COLOR_NEUTRAL
    assert _prediction_color("SOMETHING_NEW") == _COLOR_NEUTRAL


def test_prediction_color_is_case_insensitive():
    assert _prediction_color("fortify") == _COLOR_FAVORABLE
