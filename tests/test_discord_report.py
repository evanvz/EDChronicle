"""Session BGS activity as BGS-Tally-style Discord text (default formatter layout:
one ```ansi block per system, one line per faction, non-zero items only), for the
user to paste. Nothing is posted anywhere."""
from edc.core.discord_report import DISCORD_LIMIT, bgs_tally_text, human_format, split_for_discord

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


def test_split_for_discord_keeps_system_blocks_whole():
    blocks = "".join(f"```ansi\nSystem{i}\n{'x' * 600}\n```" for i in range(5))
    parts = split_for_discord(blocks)
    assert len(parts) > 1 and all(len(p) <= DISCORD_LIMIT for p in parts)
    assert "".join(parts) == blocks
    assert all(p.startswith("```ansi") and p.endswith("```") for p in parts)
    assert split_for_discord("") == []


def test_dialog_copy_button_cycles_parts(tmp_path):
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
    # enough systems with long faction names to need more than one Discord message
    big = {"2026-10-11": {f"System {i:02d}": {f"Faction {i} {'X' * 120} {j}": _entry(inf=j + 1, bounties_total=1000)
                                             for j in range(4)} for i in range(8)}}
    dlg = SessionActivityDialog(SimpleNamespace(_repo=repo, _faction_name="EUW", _latest_known_tick=None))
    with patch.object(repo, "get_session_activity_report", return_value=big):
        dlg.refresh()
    n = len(dlg._discord_parts)
    assert n > 1 and dlg._discord_btn.text() == f"📋 Copy for Discord (1/{n})"
    dlg._copy_for_discord()
    first = QApplication.clipboard().text()
    assert first == dlg._discord_parts[0] and len(first) <= DISCORD_LIMIT
    assert dlg._discord_btn.text() == f"📋 Copy for Discord (2/{n})"

    with patch.object(repo, "get_session_activity_report", return_value={}):
        dlg.refresh()
    assert not dlg._discord_btn.isEnabled()
