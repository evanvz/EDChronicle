"""SINC bucket points (Complete BGS Guide 2024 p65: log2 per bucket), the
"which bucket still pays" hints, and the likely daily ceiling (6-8% of headroom,
from 121 clean EUW day-pairs, 2026-10-12)."""
import pytest

from edc.core.bgs_points import bucket_hints, bucket_points, ceiling, total_points


def test_bucket_points_match_sinc_formulas():
    p = bucket_points(inf=61, bounties=0, trade_profit=6_200_000, exploration=3_100_000)
    assert p["missions"] == pytest.approx(0.5 * 5.930737, abs=1e-3)      # 0.5 x log2(61)
    assert p["bounties"] == 0                                              # nothing redeemed
    assert p["trade"] == pytest.approx(0.5 * 5.954196, abs=1e-3)          # 0.5 x log2(6.2M / 100k)
    assert p["exploration"] == pytest.approx(0.5 * 1.632268, abs=1e-3)    # 0.5 x log2(3.1M / 1M)
    assert total_points(p) == pytest.approx(6.76, abs=0.01)
    assert bucket_points(inf=-3, bounties=300_000, trade_profit=50_000, exploration=0) == {
        "missions": 0, "bounties": 0, "trade": 0, "exploration": 0}      # below each threshold: nothing


def test_hints_name_empty_buckets_and_the_cost_of_the_next_step():
    hints = bucket_hints(inf=61, bounties=0, trade_profit=6_200_000, exploration=3_100_000)
    assert hints["empty"] == ["bounties"]
    assert hints["next"]["bounties"] == "first 900K → +1.33"
    assert hints["next"]["missions"] == "another 61 INF → +0.5"
    assert hints["next"]["trade"] == "another 6.2M → +0.5"


def test_ceiling_is_6_to_8_percent_of_headroom():
    lo, hi = ceiling(0.7488)
    assert (round(lo, 2), round(hi, 2)) == (1.51, 2.01)
    assert ceiling(None) is None


def _act(inf=0, bounties=0, trade=0, expl=0):
    return {"tier_score": inf, "bounties": bounties, "trade_profit": trade, "exploration": expl}


def test_point_chips_show_points_empty_buckets_and_ceiling():
    from edc.core.bgs_tasks import bgs_point_chips
    chips = bgs_point_chips(_act(61, 0, 6_200_000, 3_100_000), 0.7488)
    assert [c["text"] for c in chips] == ["SINC 6.8 pts · empty: bounties", "Likely max today +1.5–2.0"]
    assert "Bounties: 0.00 — next: first 900K → +1.33" in chips[0]["tooltip"]
    assert bgs_point_chips(_act(), None) == []                    # nothing done, influence unknown


def test_session_report_points_line_only_for_squad_faction(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import patch
    from PyQt6.QtWidgets import QApplication, QLabel
    from edc.ui.panels.session_activity_dialog import SessionActivityDialog
    from persistence.database import Database
    from persistence.repository import Repository
    from persistence.schema import SCHEMA_SQL
    app = QApplication.instance() or QApplication([])
    db = Database(tmp_path / "t.db"); db.executescript(SCHEMA_SQL); db.run_migrations()
    repo = Repository(db)

    def entry(inf):
        return {"missions": {"count": 3, "weighted": inf, "primary_count": 3, "secondary_count": 0, "by_type": {},
                             "reward_total": 0, "reward_by_type": {}},
                "combat_bonds_total": 0, "bounties_total": 0, "bounties_max_cashin": 0,
                "cz_kills": {"ground_l": 0, "ground_m": 0, "ground_h": 0, "space_l": 0, "space_m": 0, "space_h": 0},
                "trade_sold": {"commodity": 6_200_000, "exploration": 0, "exobiology": 0, "purchase": 0}}
    report = {"2026-10-11": {"Ekono": {"EUW": entry(61), "Other Faction": entry(10)}}}
    dlg = SessionActivityDialog(SimpleNamespace(_repo=repo, _faction_name="EUW", _latest_known_tick=None))
    with patch.object(repo, "get_session_activity_report", return_value=report), \
         patch.object(repo, "get_faction_history", return_value=[{"influence": 0.7488}]), \
         patch.object(repo, "get_system_addresses_for_names", return_value={"Ekono": 1}):
        dlg.refresh()
    texts = [l.text() for card in dlg._cards for l in card.findChildren(QLabel)]
    lines = [t for t in texts if "SINC" in t]
    assert len(lines) == 1 and "Likely max today +1.5–2.0" in lines[0]


def test_population_scales_bases_like_sincs_daily_amounts():
    small = bucket_points(inf=20, bounties=8_000_000, trade_profit=0, exploration=0, population=150_000)
    assert small == bucket_points(inf=20, bounties=8_000_000, trade_profit=0, exploration=0)   # small = unscaled
    large = bucket_points(inf=20, bounties=8_000_000, trade_profit=0, exploration=0, population=2_474_591_197)
    assert large["bounties"] == pytest.approx(small["bounties"] - 1.33 * 1.5849625, abs=1e-6)  # base x3 (30M/10M)
    assert large["missions"] == pytest.approx(small["missions"] - 0.5 * 1.7369656, abs=1e-6)   # base x10/3 (50/15 INF)
    assert bucket_hints(0, 0, 0, 0, population=10_000_000)["next"]["bounties"] == "first 1.8M → +1.33"   # medium x2
