"""rule_engine 向后兼容 — 线上旧版缺少 get_effective_calibration 时仍可启动。"""
from __future__ import annotations

from src.rule_engine import MULTIPLIERS, PENALTY_FLOOR, TIER_BASE, predict, predict_calibrated

try:
    from src.rule_engine import get_effective_calibration
except ImportError:
    def get_effective_calibration(tier: str, enable_ema: bool = False) -> float:
        if not enable_ema:
            return 1.0
        from src.rule_engine import get_calibration
        return get_calibration()["tier"].get(tier, 1.0)


def predict_calibrated_safe(opponent, enable_ema=False, **kwargs):
    """兼容旧 rule_engine.predict_calibrated（无 enable_ema 参数）。"""
    try:
        return predict_calibrated(opponent, enable_ema=enable_ema, **kwargs)
    except TypeError:
        raw = predict(opponent, **kwargs)
        from src.classify import classify_opponent_tier
        tier = classify_opponent_tier(opponent)
        return raw * get_effective_calibration(tier, enable_ema=enable_ema)
