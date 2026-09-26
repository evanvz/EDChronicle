"""Repository._signed_tier_value() -- Frontier's own "+" to "+++++" tier
length, signed by its Trend ("UpGood"/"DownGood"/"UpBad"/"DownBad").
"Good" means the tier count should add to the faction's score, "Bad"
means it should subtract -- confirmed live 2026-09-26: a combat-mission
secondary effect on a rival faction carried Trend:"DownBad" (their
influence actually went down) but was being counted as a flat positive
with no sign at all before this fix."""
from persistence.repository import _signed_tier_value


def test_upgood_is_positive():
    assert _signed_tier_value("++", "UpGood") == 2


def test_downgood_is_positive():
    assert _signed_tier_value("+++", "DownGood") == 3


def test_upbad_is_negative():
    assert _signed_tier_value("+", "UpBad") == -1


def test_downbad_is_negative():
    assert _signed_tier_value("++++", "DownBad") == -4


def test_missing_trend_defaults_to_positive():
    """No way to recover the real sign for rows recorded before this
    column existed -- always treated as positive, the only behavior that
    ever existed before this fix."""
    assert _signed_tier_value("+++", None) == 3


def test_missing_influence_tier_is_zero_regardless_of_trend():
    assert _signed_tier_value(None, "DownBad") == 0
    assert _signed_tier_value(None, "UpGood") == 0
