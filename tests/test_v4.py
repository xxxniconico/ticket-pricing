from src.classify import classify_opponent_tier
from src.pricing_matrix import get_multiplier, load_section_tier_map
from src.calibrate import build_attendance_model_v4, build_attendance_model_live, predict_attendance_v4


def test_pricing_matrix_s_t1():
    assert get_multiplier("T1", "S") == 1.05


def test_section_tier_map_loads():
    m = load_section_tier_map()
    assert isinstance(m, dict)
    assert len(m) >= 80


def test_build_attendance_model_v4_samples():
    model = build_attendance_model_v4()
    assert model.get("version") == "v4"
    assert model.get("n_samples", 0) >= 15


def test_live_model_more_samples_than_v4():
    v4 = build_attendance_model_v4()
    live = build_attendance_model_live()
    assert live.get("n_samples", 0) >= v4.get("n_samples", 0)


def test_predict_attendance_v4_cap():
    pred = predict_attendance_v4(
        recent_form_5=0.5,
        lost_to_bottom_recent=False,
        opponent_rank=3,
        is_derby=True,
        is_weekend=True,
        is_double_matchweek=False,
        max_capacity=27500,
    )
    assert 0 < pred <= 27500


def test_classify_shenhua_s():
    assert classify_opponent_tier("上海申花") == "S"
