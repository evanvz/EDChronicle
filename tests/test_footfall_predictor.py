from edc.core.footfall_predictor import predict_footfall, LIKELY_UNCLAIMED, UNCERTAIN


def test_never_indexed_by_spansh_leans_unclaimed():
    score, label = predict_footfall(None, None)
    assert score > 50


def test_pre_odyssey_last_update_and_unmapped_is_likely_unclaimed():
    score, label = predict_footfall("2019-01-01T00:00:00Z", False)
    assert label == LIKELY_UNCLAIMED
    assert score == 100


def test_recently_updated_and_mapped_is_the_worst_case_score():
    # Baseline 50, -10 (recently updated) -15 (was_mapped) = 25 -- the
    # lowest score this heuristic can produce, since Spansh's snapshot
    # alone never proves a footfall happened, only that someone visited.
    score, label = predict_footfall("2026-08-01T00:00:00Z", True)
    assert score == 25
    assert label == UNCERTAIN


def test_score_always_clamped_0_100():
    score, _ = predict_footfall("2019-01-01T00:00:00Z", False)
    assert 0 <= score <= 100
    score, _ = predict_footfall("2026-08-01T00:00:00Z", True)
    assert 0 <= score <= 100


def test_unknown_was_mapped_applies_no_adjustment():
    with_none, _ = predict_footfall("2026-01-01T00:00:00Z", None)
    baseline = 50 - 10  # recent update penalty only
    assert with_none == baseline
