"""Per-system ticks from the system's own readings: influence or states only
change at a tick, so differing readings prove the system ticked between them
(tick.edcd.io listed no tick for 2026-10-18 while Ekono still moved)."""
from edc.core.system_ticks import infer_system_ticks, merge_ticks

EXP = '[{"State": "Expansion"}]'


def _r(at, inf, source="eddn", active="[]", pending="[]", faction="EUW"):
    return (at, faction, inf, active, pending, source)


def test_change_between_readings_is_a_system_tick():
    rows = [_r("2026-10-18T23:10:36Z", 0.7812), _r("2026-10-18T23:10:36Z", 0.05, faction="Other"),
            _r("2026-10-19T11:46:38Z", 0.7832), _r("2026-10-19T11:46:38Z", 0.048, faction="Other"),
            _r("2026-10-19T15:00:00Z", 0.7832)]                                         # confirms it
    assert infer_system_ticks(rows) == [{"after": "2026-10-18T23:10:36Z", "by": "2026-10-19T11:46:38Z",
                                         "confirmed": True}]


def test_state_change_alone_counts_and_rounding_does_not():
    rows = [_r("2026-10-14T20:00:00Z", 0.5936, pending=EXP), _r("2026-10-15T20:00:00Z", 0.59362, active=EXP,
                                                                source="journal")]
    assert infer_system_ticks(rows)[0]["confirmed"]                                     # pending -> active, own journal
    assert infer_system_ticks([_r("2026-10-14T20:00:00Z", 0.5936), _r("2026-10-15T20:00:00Z", 0.59362)]) == []


def test_unconfirmed_stale_upload_is_not_used():
    """An EDDN reading with old values after new ones (EDCAS warns of these) isn't
    confirmed until a later reading agrees."""
    rows = [_r("2026-10-18T10:00:00Z", 0.60), _r("2026-10-18T20:00:00Z", 0.55), _r("2026-10-19T08:00:00Z", 0.60)]
    assert [t["confirmed"] for t in infer_system_ticks(rows)] == [False, False]


def test_merge_adds_only_ticks_no_global_tick_explains():
    sys_ticks = [{"after": "2026-10-17T10:00:00Z", "by": "2026-10-17T20:00:00Z", "confirmed": True},   # global 16:25 explains
                 {"after": "2026-10-18T23:10:36Z", "by": "2026-10-19T11:46:38Z", "confirmed": True},   # missed by tick.edcd.io
                 {"after": "2026-10-19T12:00:00Z", "by": "2026-10-19T13:00:00Z", "confirmed": False}]
    ticks, added = merge_ticks(["2026-10-17T16:25:36Z"], sys_ticks)
    assert ticks == ["2026-10-17T16:25:36Z", "2026-10-19T11:46:38Z"] and list(added) == ["2026-10-19T11:46:38Z"]
