"""Unit tests for sales_velocity.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from src.sales_velocity import (
    predict_final_from_d4, check_velocity_alert,
    compute_velocity_correction, apply_velocity_correction,
)


class TestD4Prediction:
    def test_basic(self):
        result = predict_final_from_d4(6000, 0.60)
        assert result == 10000

    def test_zero(self):
        result = predict_final_from_d4(0, 0.60)
        assert result == 0


class TestVelocityAlert:
    def test_wuhan_case(self):
        # 显式传 0.60：断言的是该口径下的判定逻辑本身（标定值另测）
        alert = check_velocity_alert(9200, 3959, d4_ratio=0.60)
        assert alert["alert"] is True
        assert alert["direction"] == "overestimate"
        assert abs(alert["deviation_pct"] - 39.4) < 1.0

    def test_no_alert(self):
        alert = check_velocity_alert(10000, 6000, d4_ratio=0.60)
        assert alert["alert"] is False

    def test_default_d4_is_calibrated(self):
        """默认 D4 标定值 = 4 场实测中位 0.69（2026-10-20 重标）。"""
        from src.sales_velocity import D4_RATIO_DEFAULT, D1_TO_MATCHDAY_RATIO
        assert abs(D4_RATIO_DEFAULT - 0.69) < 1e-9
        assert abs(D1_TO_MATCHDAY_RATIO - 0.949) < 1e-9
        # 青岛西海岸 10/18 实测 D4=4,275 → 反推终值应贴近实际 5,751
        est = predict_final_from_d4(4275)
        assert abs(est - 5751) / 5751 < 0.10


class TestVelocityCurve:
    def test_monotonic(self):
        from src.sales_velocity import VELOCITY_CURVE
        vals = [VELOCITY_CURVE[k] for k in sorted(VELOCITY_CURVE)]
        assert vals == sorted(vals)
        assert vals[-1] == 1.0

    def test_expected_cum_ratio(self):
        from src.sales_velocity import expected_cum_ratio
        assert expected_cum_ratio(0) == 0.0
        assert abs(expected_cum_ratio(4) - 0.689) < 1e-9
        assert expected_cum_ratio(99) == 1.0
        assert expected_cum_ratio(4, ratio=0.6) == 0.6


class TestCorrection:
    def test_no_deviation(self):
        # 显式传 0.85 保持原断言语义；默认值已是 0.949（标定值另测）
        corr = compute_velocity_correction(10000, 8500, d7_ratio=0.85)
        assert abs(corr - 1.0) < 0.01

    def test_low_sales(self):
        corr = compute_velocity_correction(10000, 6800, d7_ratio=0.85)
        assert corr < 0.95

    def test_default_ratio_semantics(self):
        """默认比率为「赛前一天 ≈ 94.9%」：实际达 9,490 时无修正。"""
        corr = compute_velocity_correction(10000, 9490)
        assert abs(corr - 1.0) < 0.01

    def test_clip(self):
        corr = compute_velocity_correction(10000, 100)
        assert corr >= 0.80

    def test_apply(self):
        result = apply_velocity_correction(10000, 0.90)
        assert result == 9000
