"""_cz_station_note_text() -- tells the player where to redeem CZ combat
bonds. Prefers the current system when its controlling faction already
matches the squadron faction (redeem here, no travel), falls back to the
closest known controlled station from past Docked visits, or an
unknown-yet message if none has been recorded."""
from edc.ui.panels.combat_panel import _cz_station_note_text


def test_current_system_controlled_by_squadron_faction():
    text = _cz_station_note_text("Elite United Worlds", "Elite United Worlds", " ", None)
    assert "Redeem bonds here" in text
    assert "closest known" not in text


def test_current_system_not_controlled_falls_back_to_closest_known_station():
    station = {
        "station_name": "Jameson Memorial", "system_name": "Shinrarta Dezhra",
        "distance_ly": 12.3, "last_visited": "2026-09-01T00:00:00Z",
    }
    text = _cz_station_note_text("Elite United Worlds", "Some Other Faction", " ", station)
    assert "Jameson Memorial" in text
    assert "12.3 ly" in text


def test_no_known_station_yet():
    text = _cz_station_note_text("Elite United Worlds", "Some Other Faction", " ", None)
    assert "no confirmed station known yet" in text


def test_outstanding_bonds_text_included_when_redeeming_locally():
    text = _cz_station_note_text("Elite United Worlds", "Elite United Worlds", " 20,000 Cr in unredeemed combat bonds — ", None)
    assert "20,000 Cr" in text
