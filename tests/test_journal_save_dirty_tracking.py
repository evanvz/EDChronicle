"""MainWindow._save_ring_data() / _save_body_data() / _save_resolved_bodies()
/ _save_codex_entries() -- each re-loops the FULL session-accumulated
collection (state.rings/bodies/resolved_body_ids/exo) on every relevant
journal event, not just what changed -- an O(n^2) pattern across a scan
burst (each repo.save_* call auto-commits via Database.execute()). Each
now skips a record whose signature hasn't changed since the last time it
was saved, mirroring _save_colonisation_depot's dedup-guard shape (see
tests/test_colonisation_depot_dedup.py)."""
from contextlib import nullcontext
from types import SimpleNamespace

from edc.ui.main_window import MainWindow


def _fake_repo(**save_methods):
    return SimpleNamespace(db=SimpleNamespace(deferred_commit=lambda: nullcontext()), **save_methods)


# ---- _save_ring_data ----

def _ring_rec(system_address=123, parent_body="Body A", ring_class="Metal Rich",
              distance_ls=10.0, scanned=True, hotspots=None):
    return {
        "system_address": system_address, "parent_body": parent_body, "ring_class": ring_class,
        "distance_ls": distance_ls, "scanned": scanned, "hotspots": hotspots,
    }


def test_ring_first_save_writes():
    saved = []
    fake_self = SimpleNamespace(
        state=SimpleNamespace(system_address=123, rings={"Body A A Ring": _ring_rec()}),
        repo=_fake_repo(save_ring=lambda **kw: saved.append(kw)),
        _ring_last_seen={},
    )
    MainWindow._save_ring_data(fake_self)
    assert len(saved) == 1


def test_ring_unchanged_repeat_is_skipped():
    saved = []
    fake_self = SimpleNamespace(
        state=SimpleNamespace(system_address=123, rings={"Body A A Ring": _ring_rec()}),
        repo=_fake_repo(save_ring=lambda **kw: saved.append(kw)),
        _ring_last_seen={},
    )
    MainWindow._save_ring_data(fake_self)
    MainWindow._save_ring_data(fake_self)
    assert len(saved) == 1


def test_ring_change_triggers_new_save():
    saved = []
    fake_self = SimpleNamespace(
        state=SimpleNamespace(system_address=123, rings={"Body A A Ring": _ring_rec(scanned=False)}),
        repo=_fake_repo(save_ring=lambda **kw: saved.append(kw)),
        _ring_last_seen={},
    )
    MainWindow._save_ring_data(fake_self)
    fake_self.state.rings["Body A A Ring"] = _ring_rec(scanned=True)
    MainWindow._save_ring_data(fake_self)
    assert len(saved) == 2


# ---- _save_body_data ----

def _body_rec(planet_class="Icy body", was_mapped=False):
    return {"BodyID": 1, "PlanetClass": planet_class, "WasMapped": was_mapped}


def test_body_first_save_writes():
    saved = []
    fake_self = SimpleNamespace(
        state=SimpleNamespace(system_address=123, bodies={"Body A": _body_rec()}),
        repo=_fake_repo(save_body=lambda **kw: saved.append(kw)),
        _body_last_seen={},
    )
    MainWindow._save_body_data(fake_self)
    assert len(saved) == 1


def test_body_unchanged_repeat_is_skipped():
    saved = []
    fake_self = SimpleNamespace(
        state=SimpleNamespace(system_address=123, bodies={"Body A": _body_rec()}),
        repo=_fake_repo(save_body=lambda **kw: saved.append(kw)),
        _body_last_seen={},
    )
    MainWindow._save_body_data(fake_self)
    MainWindow._save_body_data(fake_self)
    assert len(saved) == 1


def test_body_change_triggers_new_save_and_does_not_resave_others():
    saved = []
    fake_self = SimpleNamespace(
        state=SimpleNamespace(system_address=123, bodies={
            "Body A": _body_rec(),
            "Body B": {"BodyID": 2, "PlanetClass": "Rocky body", "WasMapped": False},
        }),
        repo=_fake_repo(save_body=lambda **kw: saved.append(kw)),
        _body_last_seen={},
    )
    MainWindow._save_body_data(fake_self)
    assert len(saved) == 2
    fake_self.state.bodies["Body A"] = _body_rec(was_mapped=True)
    MainWindow._save_body_data(fake_self)
    # Only Body A (the changed one) re-saved -- Body B untouched this pass.
    assert len(saved) == 3
    assert saved[-1]["body_name"] == "Body A"


# ---- _save_resolved_bodies ----

def test_resolved_body_first_save_writes():
    saved = []
    fake_self = SimpleNamespace(
        state=SimpleNamespace(system_address=123, resolved_body_ids={1}),
        repo=_fake_repo(save_resolved_body=lambda addr, bid: saved.append((addr, bid))),
        _resolved_body_saved=set(),
    )
    MainWindow._save_resolved_bodies(fake_self)
    assert saved == [(123, 1)]


def test_resolved_body_repeat_call_does_not_resave():
    saved = []
    fake_self = SimpleNamespace(
        state=SimpleNamespace(system_address=123, resolved_body_ids={1}),
        repo=_fake_repo(save_resolved_body=lambda addr, bid: saved.append((addr, bid))),
        _resolved_body_saved=set(),
    )
    MainWindow._save_resolved_bodies(fake_self)
    fake_self.state.resolved_body_ids = {1, 2}  # body #2 newly resolved
    MainWindow._save_resolved_bodies(fake_self)
    assert saved == [(123, 1), (123, 2)]


# ---- _save_codex_entries ----

def _codex_rec(base_value=5000, is_phenomena=False):
    return {
        "LastScanType": "CODEX", "BodyID": 1, "Genus": "$Codex_Ent_Bacterial_Genus_Name;",
        "Species": "Species A", "Variant": "Green", "CodexEntryID": 42,
        "BaseValue": base_value, "IsPhenomena": is_phenomena,
    }


def test_codex_first_save_writes():
    saved = []
    fake_self = SimpleNamespace(
        state=SimpleNamespace(system_address=123, exo={"k": _codex_rec()}),
        repo=_fake_repo(save_codex_entry=lambda **kw: saved.append(kw)),
        _codex_entry_last_seen={},
    )
    MainWindow._save_codex_entries(fake_self)
    assert len(saved) == 1


def test_codex_unchanged_repeat_is_skipped():
    saved = []
    fake_self = SimpleNamespace(
        state=SimpleNamespace(system_address=123, exo={"k": _codex_rec()}),
        repo=_fake_repo(save_codex_entry=lambda **kw: saved.append(kw)),
        _codex_entry_last_seen={},
    )
    MainWindow._save_codex_entries(fake_self)
    MainWindow._save_codex_entries(fake_self)
    assert len(saved) == 1


def test_codex_value_change_triggers_new_save():
    saved = []
    fake_self = SimpleNamespace(
        state=SimpleNamespace(system_address=123, exo={"k": _codex_rec(base_value=5000)}),
        repo=_fake_repo(save_codex_entry=lambda **kw: saved.append(kw)),
        _codex_entry_last_seen={},
    )
    MainWindow._save_codex_entries(fake_self)
    fake_self.state.exo["k"] = _codex_rec(base_value=6000)
    MainWindow._save_codex_entries(fake_self)
    assert len(saved) == 2
