"""ExobiologyPanel._short_body_name() -- Canonn's getSystemPoi API returns
body names without the system prefix ("3 d"), but Frontier's own journal
BodyName is always "<system> <suffix>" ("HIP 105879 3 d"). Confirmed live
2026-09-22 against a real system (HIP 105879) with real Canonn codex data
present: the un-stripped comparison silently matched nothing at all, so
the "Canonn already knows what's likely here" hint never fired despite
both sides having the right data."""
import sys
from PyQt6.QtWidgets import QApplication

from edc.ui.panels.exobiology_panel import ExobiologyPanel

# A QApplication is required to construct any QWidget subclass, even via
# __new__ -- Qt asserts on this at first widget-adjacent call.
_app = QApplication.instance() or QApplication(sys.argv)


def _panel():
    return ExobiologyPanel.__new__(ExobiologyPanel)


def test_strips_known_system_prefix():
    assert _panel()._short_body_name("HIP 105879 3 d", "HIP 105879") == "3 d"
    assert _panel()._short_body_name("HIP 105879 3 h", "HIP 105879") == "3 h"


def test_leaves_name_unchanged_when_prefix_absent():
    assert _panel()._short_body_name("Unknown Body", None) == "Unknown Body"
    assert _panel()._short_body_name("3 d", "HIP 105879") == "3 d"


def test_star_itself_has_no_suffix_to_strip():
    assert _panel()._short_body_name("Sol", "Sol") == "Sol"


def test_case_insensitive_prefix_match():
    assert _panel()._short_body_name("hip 105879 3 d", "HIP 105879") == "3 d"


def test_real_canonn_response_shape_matches_after_stripping():
    """Real payload captured live from Canonn's getSystemPoi for HIP
    105879 (2026-09-22) -- body keys are short form, confirming the fix
    against actual API output, not just a synthetic example."""
    panel = _panel()
    canonn_species_by_body = {
        "3 d": ["Bacterium Alcyoneum - Lime", "Stratum Laminamus - Emerald"],
        "3 h": ["Bacterium Aurasus - Lime", "Stratum Paleas - Emerald"],
    }
    key = panel._short_body_name("HIP 105879 3 d", "HIP 105879").lower()
    assert canonn_species_by_body.get(key) == ["Bacterium Alcyoneum - Lime", "Stratum Laminamus - Emerald"]
