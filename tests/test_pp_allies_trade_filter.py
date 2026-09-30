"""Trade finders' "Exclude enemy PowerPlay systems" keeps allied (ZYADA) systems."""
from types import SimpleNamespace

from edc.core.bgs_tasks import allied_powers
from edc.ui.panels.trade_route_panel import _drop_enemy_pp


def test_allied_systems_are_kept_rivals_dropped():
    owners = {"Ally Sys": "Denton Patreus", "Rival Sys": "Zachary Hudson", "Own Sys": "Aisling Duval"}
    edsm = SimpleNamespace(get_controller_by_name=lambda name: {"power": owners[name]})
    stations = {i: {"system_name": n} for i, n in enumerate(owners)}
    kept = _drop_enemy_pp(stations, "Aisling Duval", edsm, allied_powers("Aisling Duval"))
    assert sorted(s["system_name"] for s in kept.values()) == ["Ally Sys", "Own Sys"]
    # without allies (old behaviour) the ally counts as enemy
    assert len(_drop_enemy_pp(stations, "Aisling Duval", edsm)) == 1
