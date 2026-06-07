"""
国安散票预测 — 规则引擎 V5.4（盛夏重启效应）

基值: 2023-2026 去情境化中位数 (53场)
  S=12600 A=10900 B=8200 C=5700
乘数: 53场网格搜索
  derby=1.25 derby_B=1.05 lost_bottom=0.65 heavy_home_loss=0.85
  away_winless=0.98 away_winless_losses=0.82 saturday=1.02
  season_opener=1.15 short_rest=0.78 midweek=0.92
  summer=1.15 (B/C级, 7-8月, 暑假运营活动)
  midseason_restart=1.10 (>=28天间隔, 6-7月, 非赛季首场)
年份因子: year_2023=1.45 (S级豁免)
惩罚底线: 0.35  EMA: 0.20

V5.4: +midseason_restart
  - 盛夏重启: B级6月长休场次均值1.22x (n=2: 海港1.07 + 亚泰1.37), 标定1.10保守
  - 去掉了对手级偏差(OPP_DEVIATION), 保持模型系统性
"""
from __future__ import annotations
import json, os
from pathlib import Path
import numpy as np, pandas as pd
from src.classify import classify_opponent_tier, DERBY_RIVALS

TIER_BASE: dict[str, float] = {"S": 12600, "A": 10900, "B": 8200, "C": 5700}
OPP_DEVIATION: dict[str, float] = {}

MULTIPLIERS = {
    "derby": 1.25, "derby_B": 1.05,
    "lost_bottom": 0.65, "heavy_home_loss": 0.85,
    "consecutive_home_losses": 0.82,
    "away_winless": 0.98, "away_winless_losses": 0.82,
    "saturday": 1.02,
    "season_opener": 1.17,
    "short_rest": 0.78, "midweek": 0.86,
    "summer": 1.13,
    "midseason_restart": 1.10,
}

YEAR_2023 = 1.45

PENALTY_FLOOR = 0.35
_CAL_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "calibration.json")
_ALPHA = 0.20

def _load_cal() -> dict:
    if not os.path.exists(_CAL_FILE):
        return {"tier": {"S": 1.0, "A": 1.0, "B": 1.0, "C": 1.0}, "history": []}
    with open(_CAL_FILE) as f: return json.load(f)

def _save_cal(cal: dict):
    os.makedirs(os.path.dirname(_CAL_FILE), exist_ok=True)
    with open(_CAL_FILE, "w") as f: json.dump(cal, f, indent=2, ensure_ascii=False)

def predict(opponent, derby=False, lost_bottom=False, heavy_home_loss=False,
            consecutive_home_losses=False,
            away_winless=False, saturday=False, season_opener=False,
            short_rest=False, midweek=False, summer=False,
            away_winless_losses=False, midseason_restart=False,
            match_year=None, **__) -> float:
    tier = classify_opponent_tier(opponent)
    base = TIER_BASE.get(tier, 8100)
    for key, val in OPP_DEVIATION.items():
        if key in opponent or opponent in key: base *= val; break
    mult = 1.0
    if match_year == "2023" and tier != "S":
        mult *= YEAR_2023
    if derby and tier != "S":
        mult *= MULTIPLIERS["derby_B"] if tier == "A" else MULTIPLIERS["derby"]
    if lost_bottom: mult *= 0.78 if tier in ("S","A") else MULTIPLIERS["lost_bottom"]
    elif consecutive_home_losses: mult *= MULTIPLIERS["consecutive_home_losses"]
    elif heavy_home_loss: mult *= MULTIPLIERS["heavy_home_loss"]
    if away_winless_losses:
        mult *= MULTIPLIERS["away_winless_losses"]
    elif away_winless:
        mult *= MULTIPLIERS["away_winless"]
    if saturday: mult *= MULTIPLIERS["saturday"]
    if season_opener: mult *= MULTIPLIERS["season_opener"]
    if midseason_restart and not season_opener: mult *= MULTIPLIERS["midseason_restart"]
    if midweek and not lost_bottom: mult *= MULTIPLIERS["midweek"]
    if short_rest and not lost_bottom and not heavy_home_loss: mult *= MULTIPLIERS["short_rest"]
    if summer and tier in ("B","C"): mult *= MULTIPLIERS["summer"]
    if mult < PENALTY_FLOOR: mult = PENALTY_FLOOR
    return min(base * mult, 20000.0)

def predict_calibrated(opponent, **kwargs):
    raw = predict(opponent, **kwargs)
    return raw * _load_cal()["tier"].get(classify_opponent_tier(opponent), 1.0)

def update(match_id, opponent, actual, **ctx):
    cal = _load_cal()
    # 去重：同一match_id不重复更新
    if any(h.get("match_id") == match_id for h in cal.get("history", [])):
        return
    raw = predict(opponent, **ctx)
    tier = classify_opponent_tier(opponent)
    ratio = actual / raw if raw > 0 else 1.0
    old = cal["tier"].get(tier, 1.0)
    new = round(_ALPHA * ratio + (1 - _ALPHA) * old, 4)
    new = max(0.3, min(2.0, new))
    cal["tier"][tier] = new
    cal["history"].append({"match_id": match_id, "tier": tier, "raw_pred": round(raw,0),
        "actual": round(actual,0), "ratio": round(ratio,4)})
    _save_cal(cal)

def get_calibration(): return _load_cal()
def get_history(): return pd.DataFrame(_load_cal().get("history", []))
def init_from_data(): pass
