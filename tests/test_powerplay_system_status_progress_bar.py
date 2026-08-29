"""_progress_bar_text() renders Frontier's Control Points tug-of-war
(qty/threshold) as a text bar -- pure function, no Qt dependency."""
from edc.ui.panels.powerplay_system_status_panel import _progress_bar_text


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
