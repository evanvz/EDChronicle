"""Session BGS activity as BGS-Tally-style Discord text (default formatter layout:
one ```ansi block per system, one line per faction, non-zero items only), for the
user to paste. Nothing is posted anywhere."""
from edc.core.discord_report import bgs_tally_text, human_format

E = "\x1b["


def _entry(**kw):
    e = {
        "missions": {"count": 0, "weighted": 0, "primary_count": 0, "secondary_count": 0,
                     "by_type": {}, "reward_total": 0, "reward_by_type": {}},
        "combat_bonds_total": 0, "bounties_total": 0, "bounties_max_cashin": 0,
        "cz_kills": {"ground_l": 0, "ground_m": 0, "ground_h": 0, "space_l": 0, "space_m": 0, "space_h": 0},
        "trade_sold": {"commodity": 0, "exploration": 0, "exobiology": 0, "purchase": 0},
    }
    for k, v in kw.items():
        if k == "inf":
            e["missions"]["weighted"] = v
        elif k in e["trade_sold"]:
            e["trade_sold"][k] = v
        elif k in e["cz_kills"]:
            e["cz_kills"][k] = v
        else:
            e[k] = v
    return e


def test_human_format_matches_bgs_tally():
    assert [human_format(n) for n in (0, 999, 1300, 1_250_000, 999_999, 12_345_678, -2500)] == \
        ["0", "999", "1.3K", "1.25M", "1M", "12.3M", "-2.5K"]


def test_faction_line_layout_and_colours():
    report = {"2026-10-11": {"Ekono": {
        "Elite Underground Workers": _entry(inf=12, bounties_total=1_250_000, combat_bonds_total=340_000,
                                            purchase=2_000_000, commodity=450_000, exploration=1_300,
                                            space_l=2, space_m=1, ground_h=1),
        "Quiet Faction": _entry(),                     # no activity: left out
    }}}
    text = bgs_tally_text(report)
    assert text == (
        "```ansi\n"
        f"{E}37;1mEkono{E}0m\n"
        f"{E}33;1mElite Underground Workers{E}0m "
        f"{E}34mINF{E}0m {E}32m+12{E}0m "
        f"{E}31mBVs{E}0m {E}32m1.25M{E}0m "
        f"{E}31mCBs{E}0m {E}32m340K{E}0m "
        f"{E}36mTrdBuy{E}0m {E}32m2M{E}0m "
        f"{E}36mTrdProfit{E}0m {E}32m450K{E}0m "
        f"{E}37mExpl{E}0m {E}32m1.3K{E}0m "
        f"{E}31mSpaceCZs{E}0m L x {E}32m2{E}0m M x {E}32m1{E}0m  "
        f"{E}31mGroundCZs{E}0m H x {E}32m1{E}0m  \n"
        "```")


def test_days_in_the_tick_window_are_summed_and_apostrophes_dropped():
    report = {
        "2026-10-10": {"Arimavante": {"Cameron's Combat Services": _entry(inf=3, bounties_total=1000)}},
        "2026-10-11": {"Arimavante": {"Cameron's Combat Services": _entry(inf=-1, bounties_total=500)}},
    }
    text = bgs_tally_text(report)
    assert "Camerons Combat Services" in text and "'" not in text   # BGS-Tally strips apostrophes
    assert f"{E}32m+2{E}0m" in text and f"{E}32m1.5K{E}0m" in text


def test_negative_inf_and_empty_report():
    text = bgs_tally_text({"d": {"S": {"F": _entry(inf=-4)}}})
    assert f"{E}32m-4{E}0m" in text
    assert bgs_tally_text({}) == ""


def test_one_system_only_with_all_its_days():
    report = {
        "2026-10-10": {"Ekono": {"EUW": _entry(inf=2)}, "Sol": {"Fed": _entry(inf=9)}},
        "2026-10-11": {"Ekono": {"EUW": _entry(inf=3)}},
    }
    text = bgs_tally_text(report, "Ekono")
    assert "Ekono" in text and "Sol" not in text and f"{E}32m+5{E}0m" in text
    assert bgs_tally_text(report, "Nowhere") == ""


def test_each_system_card_copies_its_own_system(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import patch
    from PyQt6.QtWidgets import QApplication, QPushButton
    from edc.ui.panels.session_activity_dialog import SessionActivityDialog
    from persistence.database import Database
    from persistence.repository import Repository
    from persistence.schema import SCHEMA_SQL
    app = QApplication.instance() or QApplication([])
    db = Database(tmp_path / "t.db"); db.executescript(SCHEMA_SQL); db.run_migrations()
    repo = Repository(db)
    report = {"2026-10-11": {"Ekono": {"EUW": _entry(inf=4)}, "Sol": {"Fed": _entry(bounties_total=2000)}}}
    dlg = SessionActivityDialog(SimpleNamespace(_repo=repo, _faction_name="EUW", _latest_known_tick=None))
    with patch.object(repo, "get_session_activity_report", return_value=report):
        dlg.refresh()
    buttons = [b for card in dlg._cards for b in card.findChildren(QPushButton)]
    assert [b.text() for b in buttons] == ["📋 Copy for Discord"] * 2
    buttons[1].click()                          # second card = Sol (cards are sorted by system)
    copied = QApplication.clipboard().text()
    assert copied == bgs_tally_text(report, "Sol") and "Ekono" not in copied


def test_merits_line_for_report_systems_only():
    report = {"2026-10-26": {"Ys": {}, "Ekono": {"EUW": _entry(inf=2)}}}
    merits = {"2026-10-26": {"Ys": {"Aisling Duval": 4100}, "Sol": {"Aisling Duval": 999}},
              "2026-10-25": {"Ys": {"Aisling Duval": 100}}}
    text = bgs_tally_text(report, merits=merits)
    assert f"{E}33;1mAisling Duval{E}0m {E}36mMerits{E}0m {E}32m4.2K{E}0m" in text
    assert "Sol" not in text and "EUW" in text
    assert bgs_tally_text(report, "Ys") == ""     # no merits passed: nothing for a merits-only system


def test_merits_only_system_shows_when_your_power_controls_it(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import patch
    from PyQt6.QtWidgets import QApplication
    from edc.ui.panels.session_activity_dialog import SessionActivityDialog
    from persistence.database import Database
    from persistence.repository import Repository
    from persistence.schema import SCHEMA_SQL
    app = QApplication.instance() or QApplication([])
    db = Database(tmp_path / "t.db"); db.executescript(SCHEMA_SQL); db.run_migrations()
    repo = Repository(db)
    for addr, name, ctrl in ((1, "Ys", "Aisling Duval"), (2, "Tucanae", None)):
        db.execute("INSERT INTO systems (system_address, system_name, pp_controlling_power, pp_data_timestamp) "
                   "VALUES (?, ?, ?, '2026-10-26T10:00:00Z')", (addr, name, ctrl))
    merits = {"2026-10-26": {"Ys": {"Aisling Duval": 4100}, "Tucanae": {"Aisling Duval": 900}}}
    dlg = SessionActivityDialog(SimpleNamespace(_repo=repo, _faction_name="EUW", _latest_known_tick=None))
    with patch.object(repo, "get_session_activity_report", return_value={}), \
         patch.object(repo, "get_session_merits", return_value=merits):
        dlg.refresh()
    assert list(dlg._report["2026-10-26"]) == ["Ys"]     # acquisition-only Tucanae stays out
    dlg._copy_for_discord("Ys")
    assert "Merits" in QApplication.clipboard().text()
