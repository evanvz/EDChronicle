"""_cz_station_note_text() -- tells the player where to redeem CZ combat
bonds: at a station the faction fought for controls (not necessarily the
squadron's). Prefers the current system when that faction controls it,
falls back to the closest known squadron-faction station only when the
squadron faction is the one fought for, else names "this faction"."""
from edc.ui.panels.combat_panel import _cz_station_note_text

EUW = "Elite United Worlds"
SMMI = "Sorbago Mastopolos Mining Inc"
_STATION = {
    "station_name": "Jameson Memorial", "system_name": "Shinrarta Dezhra",
    "distance_ly": 12.3, "last_visited": "2026-09-01T00:00:00Z",
}


def test_current_system_controlled_by_the_faction_fought_for():
    text = _cz_station_note_text([SMMI], SMMI, " ", None, EUW)
    assert "Redeem bonds here" in text and "the faction you fought for" in text


def test_squadron_faction_fought_for_falls_back_to_closest_known_station():
    text = _cz_station_note_text([EUW], "Some Other Faction", " ", _STATION, EUW)
    assert "Jameson Memorial" in text
    assert "12.3 ly" in text


def test_other_faction_fought_for_names_this_faction_not_the_squadron():
    # 2026-11-11: fought for SMMI in Sorbago, the note told Evan to use a squadron-faction station
    text = _cz_station_note_text([SMMI], "Some Other Faction", " 121,494 Cr in unredeemed combat bonds — ",
                                 _STATION, EUW)
    assert text == ("Redeem bonds at a station this faction controls to count towards the war —"
                    " 121,494 Cr in unredeemed combat bonds.")


def test_no_bonds_text_ends_cleanly():
    text = _cz_station_note_text([SMMI], "Some Other Faction", " ", None, EUW)
    assert text == "Redeem bonds at a station this faction controls to count towards the war."


def test_two_factions_fought_for():
    text = _cz_station_note_text([SMMI, EUW], "Some Other Faction", " ", None, None)
    assert "a station each faction controls" in text


def test_outstanding_bonds_text_included_when_redeeming_locally():
    text = _cz_station_note_text([EUW], EUW, " 20,000 Cr in unredeemed combat bonds — ", None, EUW)
    assert "20,000 Cr" in text
