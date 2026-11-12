"""_cz_station_note_text() -- tells the player where to redeem CZ combat
bonds: at a station the faction fought for controls (not necessarily the
squadron's). Prefers the current system when that faction controls it,
else names the closest known station that faction controls, else just
"this faction"."""
from edc.ui.panels.combat_panel import _cz_station_note_text

EUW = "Elite United Worlds"
SMMI = "Sorbago Mastopolos Mining Inc"
_STATION = {
    "station_name": "Rankin Terminal", "system_name": "Inupiates", "station_faction": SMMI,
    "distance_ly": 12.3, "last_visited": "2026-09-01T00:00:00Z",
}


def test_current_system_controlled_by_the_faction_fought_for():
    text = _cz_station_note_text([SMMI], SMMI, " ", None)
    assert "Redeem bonds here" in text and "the faction you fought for" in text


def test_closest_station_of_the_faction_fought_for_is_named():
    text = _cz_station_note_text([SMMI], "Some Other Faction", " ", _STATION)
    assert text.startswith("Redeem bonds at a station this faction controls to count towards the war —")
    assert "closest known: Rankin Terminal (Inupiates), 12.3 ly" in text


def test_station_of_another_faction_is_not_shown():
    text = _cz_station_note_text([EUW], "Some Other Faction", " ", _STATION)
    assert "Rankin Terminal" not in text


def test_other_faction_fought_for_names_this_faction_not_the_squadron():
    # 2026-11-11: fought for SMMI in Sorbago, the note told Evan to use a squadron-faction station
    text = _cz_station_note_text([SMMI], "Some Other Faction", " 121,494 Cr in unredeemed combat bonds — ", None)
    assert text == ("Redeem bonds at a station this faction controls to count towards the war —"
                    " 121,494 Cr in unredeemed combat bonds.")


def test_no_bonds_text_ends_cleanly():
    text = _cz_station_note_text([SMMI], "Some Other Faction", " ", None)
    assert text == "Redeem bonds at a station this faction controls to count towards the war."


def test_two_factions_fought_for():
    text = _cz_station_note_text([SMMI, EUW], "Some Other Faction", " ", None)
    assert "a station each faction controls" in text


def test_outstanding_bonds_text_included_when_redeeming_locally():
    text = _cz_station_note_text([EUW], EUW, " 20,000 Cr in unredeemed combat bonds — ", None)
    assert "20,000 Cr" in text
