import pytest

from src.classify import (
    classify_match,
    classify_match_hybrid,
    classify_match_v4,
    classify_opponent_tier,
    get_demand_multiplier,
)


def test_classify_opponent_tier_s():
    assert classify_opponent_tier("上海申花") == "S"


def test_classify_opponent_tier_c():
    assert classify_opponent_tier("青岛海牛") == "C"


def test_classify_match_v4_shenhua():
    tier, _ = classify_match_v4("上海申花")
    assert tier == "S"


def test_classify_match_backward_compat():
    tier, _ = classify_match("上海申花")
    assert tier == "A"
    tier_b, _ = classify_match("青岛海牛")
    assert tier_b == "B"


def test_derby_multiplier():
    _, mult = classify_match("上海申花")
    assert mult >= 1.3


def test_weak_opponent():
    _, mult = classify_match("青岛海牛", opponent_standing=15)
    assert mult < 1.0


def test_classify_match_hybrid_base_times_context():
    t, m = classify_match_hybrid(
        "青岛海牛",
        base_lookup={"青岛海牛": 0.55},
        opponent_standing=14,
        is_weekend=False,
        season_stage="mid",
        home_form=0.5,
    )
    assert t == "B"
    # round to 3dp (matches get_demand_multiplier rounding)
    assert m == pytest.approx(0.55 * 0.95, abs=0.001)


def test_get_demand_multiplier_new_opponent_by_standing():
    m = get_demand_multiplier(
        "新军2027",
        opponent_standing=2,
        base_lookup=None,
        is_weekend=True,
    )
    assert m == pytest.approx(1.25 * 1.05 * 1.08, abs=0.001)

    m2 = get_demand_multiplier(
        "新军2027",
        opponent_standing=8,
        base_lookup=None,
        is_weekend=True,
    )
    assert m2 == pytest.approx(1.0 * 1.05, abs=0.001)

    m3 = get_demand_multiplier(
        "青岛海牛",
        opponent_standing=15,
        base_lookup={"青岛海牛": 0.55},
        is_weekend=True,
    )
    assert m3 == pytest.approx(0.55 * 1.05 * 0.95, abs=0.001)
