"""_economy_display() -- clean_token() turns "$economy_HighTech;" into
"HighTech" (no space), which wouldn't match _HIGH_VALUE's "High Tech"
spelling used for highlighting in the candidate dialog. This is the one
fixup needed on top of clean_token() for Frontier's economy tokens."""
from edc.ui.panels.colonisation_panel import _economy_display


def test_high_tech_gets_spaced():
    assert _economy_display("$economy_HighTech;") == "High Tech"


def test_ordinary_economy_passes_through_clean_token():
    assert _economy_display("$economy_Agri;") == "Agri"
    assert _economy_display("$economy_Extraction;") == "Extraction"
