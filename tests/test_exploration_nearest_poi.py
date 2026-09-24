"""ExplorationPanel._refresh_nearest_poi() -- renders the nearest EDAstro
POI card, or hides it when there's nothing to show (no cache, no
coordinates, or no POI found). Real QApplication/widget, matching this
app's own panel-smoke-test convention where a fake self isn't practical
for a QWidget method."""
import sys
import types

from PyQt6.QtWidgets import QApplication

from edc.ui.panels.exploration_panel import ExplorationPanel

_app = QApplication.instance() or QApplication(sys.argv)


class _FakeCache:
    def __init__(self, result):
        self._result = result

    def has_data(self):
        return True

    def get_nearest(self, x, y, z, min_rating=None):
        return self._result


def _state(x=1.0, y=2.0, z=3.0):
    return types.SimpleNamespace(system_x=x, system_y=y, system_z=z)


def test_hides_the_card_when_no_cache_given():
    panel = ExplorationPanel()
    panel._refresh_nearest_poi(_state(), None)
    assert panel._poi_frame.isVisible() is False


def test_hides_the_card_when_coordinates_are_missing():
    panel = ExplorationPanel()
    state = types.SimpleNamespace(system_x=None, system_y=None, system_z=None)
    panel._refresh_nearest_poi(state, _FakeCache({"name": "X", "coordinates": [0, 0, 0]}))
    assert panel._poi_frame.isVisible() is False


def test_hides_the_card_when_no_poi_found():
    panel = ExplorationPanel()
    panel._refresh_nearest_poi(_state(), _FakeCache(None))
    assert panel._poi_frame.isVisible() is False


def test_renders_name_type_rating_and_distance():
    panel = ExplorationPanel()
    poi = {"name": "Amundsen's Star", "type": "Notable Stellar Phenomena", "rating": 7.8,
           "distance_ly": 12.345, "galMapUrl": "https://www.edsm.net/en/system/id/1/name/Amundsen"}
    panel._refresh_nearest_poi(_state(), _FakeCache(poi))
    html = panel.nearest_poi_box.text()
    assert "Amundsen&#x27;s Star" in html or "Amundsen's Star" in html
    assert "Notable Stellar Phenomena" in html
    assert "7.8" in html
    assert "12.3" in html
    assert "edsm.net" in html


def test_html_special_characters_in_name_and_summary_are_escaped():
    panel = ExplorationPanel()
    poi = {"name": "<script>", "type": "X", "summary": "A & B", "distance_ly": 1.0}
    panel._refresh_nearest_poi(_state(), _FakeCache(poi))
    html = panel.nearest_poi_box.text()
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "A &amp; B" in html
