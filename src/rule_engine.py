"""
国安散票预测 — 规则引擎 V4（4级KMeans聚类 + 数据修正）

基值: KMeans K=4 聚类均值（2024-2025跨年, 仅2026在队）
  S=15000(申花,时间加权) A=10600(成都/山东/武汉/云南/天津) B=8600 C=4900
乘数: 4级网格搜索最优
  derby=1.25 derby_B=1.15 lost_bottom=0.65 heavy_home_loss=0.85
  away_winless=0.88 saturday=1.10 late_season=0.60
  season_opener=1.15 short_rest=0.78 midweek=0.80
惩罚底线: 0.35
EMA alpha: 0.20
OPP_DEVIATION: 无（聚类已内化差异）

更新: 天津从S降A(MAE 754→687)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from src.classify import classify_opponent_tier, DERBY_RIVALS

# ── 规则参数 ──
# 基值: KMeans K=4 聚类均值（跨年, 仅2026在队）
# S=15000: 申花三年趋势10383→13977→16827，加权近期(×1/2/3)=14544，上调至15000捕获上行通道
TIER_BASE: dict[str, float] = {"S": 15000, "A": 10600, "B": 8600, "C": 4900}

# ── 对手偏离因子 ──
# V4: 无偏差——4级聚类已内化差异, 不需要队级修正
OPP_DEVIATION: dict[str, float] = {}

# 乘数: 4级网格搜索最优（2026六场）
MULTIPLIERS = {
    "derby": 1.25,
    "derby_B": 1.15,
    "lost_bottom": 0.65,
    "heavy_home_loss": 0.85,
    "away_winless": 0.88,
    "saturday": 1.10,
    "late_season": 0.60,
    "season_opener": 1.15,
    "short_rest": 0.78,
    "midweek": 0.80,
    "unbeaten_3": 1.08,       # 近3场不败 → 球迷乐观溢价（完整30轮验证+13%,N=9vs6）
}

# 惩罚底线: 负向乘数叠加不跌破此值
PENALTY_FLOOR = 0.35

# ── 校准 ──
_CAL_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "calibration.json")
_ALPHA = 0.20


def _load_cal() -> dict:
    if not os.path.exists(_CAL_FILE):
        return {"tier": {"S": 1.0, "A": 1.0, "B": 1.0, "C": 1.0}, "history": []}
    with open(_CAL_FILE) as f:
        return json.load(f)


def _save_cal(cal: dict):
    os.makedirs(os.path.dirname(_CAL_FILE), exist_ok=True)
    with open(_CAL_FILE, "w") as f:
        json.dump(cal, f, indent=2, ensure_ascii=False)


def predict(opponent: str,
            derby: bool = False,
            lost_bottom: bool = False,
            heavy_home_loss: bool = False,
            away_winless: bool = False,
            saturday: bool = False,
            late_season: bool = False,
            season_opener: bool = False,
            short_rest: bool = False,
            midweek: bool = False,
            unbeaten_3: bool = False,
            ) -> float:
    """规则引擎 V4 预测单场上座（未校准）。

    S级derby不叠加——京津/京沪德比效应已内嵌在T1基值中。
    lost_bottom对T1/A级用0.78（复仇效应），T3/C级用0.65（全罚）。
    """
    tier = classify_opponent_tier(opponent)
    base = TIER_BASE.get(tier, 8100)
    # 对手专属偏离度（V4: 无偏差）
    dev = 1.0
    for key, val in OPP_DEVIATION.items():
        if key in opponent or opponent in key:
            dev = val
            break
    base *= dev
    mult = 1.0

    if derby and tier != "S":
        if tier == "A":
            mult *= MULTIPLIERS["derby_B"]
        else:
            mult *= MULTIPLIERS["derby"]

    if lost_bottom:
        if tier in ("S", "A"):
            mult *= 0.78  # 输弱队后踢强队: 球迷更想看复仇, 惩罚减半
        else:
            mult *= MULTIPLIERS["lost_bottom"]
    elif heavy_home_loss:
        mult *= MULTIPLIERS["heavy_home_loss"]

    if away_winless:
        mult *= MULTIPLIERS["away_winless"]
    if saturday:
        mult *= MULTIPLIERS["saturday"]
    if late_season:
        mult *= MULTIPLIERS["late_season"]
    if season_opener:
        mult *= MULTIPLIERS["season_opener"]
    if midweek and not lost_bottom and not heavy_home_loss:
        mult *= MULTIPLIERS["midweek"]
    # short_rest 不与 lost_bottom/heavy 叠加——避免双重惩罚
    if short_rest and not lost_bottom and not heavy_home_loss:
        mult *= MULTIPLIERS["short_rest"]
    if unbeaten_3:
        mult *= MULTIPLIERS["unbeaten_3"]

    if mult < PENALTY_FLOOR:
        mult = PENALTY_FLOOR

    return min(base * mult, 20000.0)


def predict_calibrated(opponent: str, **kwargs) -> float:
    """规则引擎 + 分级校准 → 最终预测。"""
    raw = predict(opponent, **kwargs)
    tier = classify_opponent_tier(opponent)
    cal = _load_cal()
    factor = cal["tier"].get(tier, 1.0)
    return raw * factor


def update(match_id: str, opponent: str, actual: float, **match_context):
    """赛后更新分级校准因子。"""
    raw = predict(opponent, **match_context)
    tier = classify_opponent_tier(opponent)
    ratio = actual / raw if raw > 0 else 1.0

    cal = _load_cal()
    old = cal["tier"].get(tier, 1.0)
    new = round(_ALPHA * ratio + (1 - _ALPHA) * old, 4)
    new = max(0.3, min(2.0, new))
    cal["tier"][tier] = new

    cal["history"].append({
        "match_id": match_id, "tier": tier,
        "raw_pred": round(raw, 0), "actual": round(actual, 0),
        "ratio": round(ratio, 4),
        f"cal_{tier}_before": round(old, 4),
        f"cal_{tier}_after": new,
    })
    _save_cal(cal)


def get_calibration() -> dict:
    return _load_cal()


def get_history() -> pd.DataFrame:
    cal = _load_cal()
    return pd.DataFrame(cal.get("history", []))


def detect_context_2026(match_date) -> dict:
    """从线上CSL Dashboard JSON检测2026上下文。（deprecated: 用src/csl_context.py）"""
    from src.csl_context import load_csl_data, get_guoan_matches, detect_ctx
    matches, standings, _ = load_csl_data()
    guoan = get_guoan_matches(matches)
    return detect_ctx({"date": match_date, "is_home": True, "completed": True}, guoan, standings)


def init_from_data():
    """从历史数据初始化参数。（deprecated: V4用聚类基值）"""
    pass
