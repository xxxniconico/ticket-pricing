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
        alert = check_velocity_alert(9200, 3959)
        assert alert["alert"] is True
        assert alert["direction"] == "overestimate"
        assert abs(alert["deviation_pct"] - 39.4) < 1.0

    def test_no_alert(self):
        alert = check_velocity_alert(10000, 6000)
        assert alert["alert"] is False


class TestCorrection:
    def test_no_deviation(self):
        corr = compute_velocity_correction(10000, 8500)
        assert abs(corr - 1.0) < 0.01

    def test_low_sales(self):
        corr = compute_velocity_correction(10000, 6800)
        assert corr < 0.95

    def test_clip(self):
        corr = compute_velocity_correction(10000, 100)
        assert corr >= 0.80

    def test_apply(self):
        result = apply_velocity_correction(10000, 0.90)
        assert result == 9000
