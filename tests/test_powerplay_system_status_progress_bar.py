"""_progress_bar_text() renders Frontier's Control Points tug-of-war
(qty/threshold) as a text bar -- pure function, no Qt dependency."""
from edc.ui.panels.powerplay_system_status_panel import (
    _progress_bar_text, _prediction_color, _COLOR_FAVORABLE, _COLOR_UNFAVORABLE, _COLOR_NEUTRAL,
    _is_decay_risk,
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


def test_decay_risk_above_25_percent_reinforcement():
    assert _is_decay_risk("control", True, 0.30) is True


def test_no_decay_risk_at_or_below_25_percent():
    assert _is_decay_risk("control", True, 0.25) is False
    assert _is_decay_risk("control", True, 0.10) is False


def test_no_decay_risk_for_undermining_direction():
    # High progress on the *against* bar means someone else is undermining
    # this system, not that it's decaying -- only the reinforcement/fortify
    # direction is subject to the 25%+ decay rule.
    assert _is_decay_risk("control", False, 0.90) is False


def test_no_decay_risk_for_uncontrolled_state():
    assert _is_decay_risk("contested", True, 0.90) is False


def test_no_decay_risk_when_fraction_unknown():
    assert _is_decay_risk("control", True, None) is False
