"""SessionActivityDialog._render_report() -- pure formatting logic taking
an already-fetched report dict, kept separate from refresh() (which does
the tick fetch + DB query) so it's testable without Qt/DB setup. Fake
self carrying only the widgets _render_report() touches, same pattern as
test_faction_expansion_live_push.py's _fake_expansion_dialog."""
from types import SimpleNamespace

from edc.ui.panels.session_activity_dialog import SessionActivityDialog


def _fake_dialog():
    rendered = []
    return SimpleNamespace(_set_body_text=lambda text: rendered.append(text)), rendered


def test_empty_report_shows_a_no_activity_message():
    fs, rendered = _fake_dialog()
    SessionActivityDialog._render_report(fs, {})
    assert "No activity" in rendered[0]


def test_report_lists_system_and_faction_with_mission_counts():
    fs, rendered = _fake_dialog()
    report = {
        "Ekono": {
            "Elite United Worlds": {
                "missions": {"count": 3, "weighted": 6, "primary_count": 2, "secondary_count": 1},
                "combat_bonds_total": 20000,
                "cz_kills": {"ground_l": 0, "ground_m": 0, "ground_h": 0, "space_l": 0, "space_m": 0, "space_h": 2},
                "trade_sold": {"commodity": 63085, "exploration": 0, "exobiology": 0},
            },
        },
    }
    SessionActivityDialog._render_report(fs, report)
    text = rendered[0]
    assert "Ekono" in text
    assert "Elite United Worlds" in text
    assert "3" in text  # mission count
    assert "20,000" in text  # combat bonds total, thousands-separated
