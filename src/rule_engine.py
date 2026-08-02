"""
国安散票预测 — 规则引擎 V5.4（盛夏重启效应）

基值: 2023-2026 去情境化中位数 (53场)
  S=12600 A=10900 B=8200 C=5700
乘数: 53场网格搜索
  derby=1.25 derby_B=1.05 lost_bottom=0.65 heavy_home_loss=0.85
  away_winless=0.94 away_winless_losses=0.82(S/A=0.77) saturday=1.02
  season_opener=1.15 short_rest=0.78 midweek=0.92
  summer=1.15 (B/C级, 7-8月, 暑假运营活动)
  midseason_restart=1.10 (>=28天间隔, 6-7月, 非赛季首场)
年份因子: year_2023=1.45 (S级豁免)
惩罚底线: 0.35  EMA: 0.20

V5.5: 客场态势拆分 — 含平局×0.94 / 近2客全败 B-C×0.82 S-A×0.77（成都场标定）
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
    "poor_home_form": 0.82,
    "away_winless": 0.94, "away_winless_losses": 0.82,
    "saturday": 1.02,
    "season_opener": 1.17,
    "short_rest": 0.78, "midweek": 0.86,
    "summer": 1.13,
    "summer_C": 1.30,   # C级暑假（辽宁7/17验证 ratio=1.33；勿改回1.13）
    "late_season": 0.80,  # 10月后赛季末战意衰减（展示层与引擎共用，单一事实源）
    "midseason_restart": 1.10,
    "top3_form": 1.08,
}

YEAR_2023 = 1.45

PENALTY_FLOOR = 0.35
_CAL_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "calibration.json")
_ALPHA = 0.20
_EMA_MIN_SAMPLES = 3

def _tier_sample_count(tier: str) -> int:
    """统计 calibration history 中某级别的已赛样本数（全历史）。"""
    return sum(
        1 for h in _load_cal().get("history", [])
        if h.get("tier") == tier
    )

def get_effective_calibration(tier: str, enable_ema: bool = True) -> float:
    """EMA 校准因子。默认关闭；开启时样本 < 3 场强制 1.0。

    S 级永久禁用（2026-08-03 用户确认）：S 级仅申花 1 场样本，校准无统计意义，
    恒返回 1.0——勿改回（避免单场 ratio 过度影响 S 级基值 12600）。
    """
    if not enable_ema:
        return 1.0
    if tier == "S":
        return 1.0
    if _tier_sample_count(tier) < _EMA_MIN_SAMPLES:
        return 1.0
    return _load_cal()["tier"].get(tier, 1.0)

def _load_cal() -> dict:
    if not os.path.exists(_CAL_FILE):
        return {"tier": {"S": 1.0, "A": 1.0, "B": 1.0, "C": 1.0}, "history": []}
    with open(_CAL_FILE) as f: return json.load(f)

def _save_cal(cal: dict):
    os.makedirs(os.path.dirname(_CAL_FILE), exist_ok=True)
    with open(_CAL_FILE, "w") as f: json.dump(cal, f, indent=2, ensure_ascii=False)

def predict(opponent, derby=False, lost_bottom=False, heavy_home_loss=False,
            consecutive_home_losses=False, poor_home_form=False,
            away_winless=False, away_winless_losses=False,
            saturday=False, season_opener=False,
            short_rest=False, midweek=False, summer=False,
            midseason_restart=False, top3_form=False,
            late_season=False,
            opponent_tier_override=None,
            opponent_st=None,
            ap_pct=None,
            match_year=None, **__) -> float:
    if opponent_tier_override is not None and isinstance(opponent_tier_override, (int, float)):
        base = float(opponent_tier_override)
        tier = None  # continuous mode, no tier
    else:
        tier = opponent_tier_override or classify_opponent_tier(opponent)
        base = TIER_BASE.get(tier, 8100)
    # AP 分位浮动（2026-08-03 用户确认加入）：同一级别内按对手吸引力差异化
    # 基值 × (1 + 0.20×(ap_pct−0.5))，限幅 ±5%。ap_pct=None 时不浮动（保持原逻辑）
    if ap_pct is not None:
        _ap_coef = 1.0 + 0.20 * (max(0.0, min(1.0, ap_pct)) - 0.5)
        _ap_coef = max(0.95, min(1.05, _ap_coef))
        base *= _ap_coef
    # Determine if opponent is "strong" (for penalty rules)
    # Priority: ST score > Tier > default False
    if opponent_st is not None:
        is_strong = opponent_st >= 55
    elif tier is not None:
        is_strong = tier in ("S", "A")
    else:
        is_strong = False

    for key, val in OPP_DEVIATION.items():
        if key in opponent or opponent in key: base *= val; break
    mult = 1.0
    if match_year == "2023" and tier != "S":
        mult *= YEAR_2023
    if derby and tier != "S":
        mult *= MULTIPLIERS["derby_B"] if tier in ("A", None) else MULTIPLIERS["derby"]  # None=continuous default to derby
    if lost_bottom: mult *= 0.78 if is_strong else MULTIPLIERS["lost_bottom"]
    elif consecutive_home_losses: mult *= MULTIPLIERS["consecutive_home_losses"]
    elif poor_home_form: mult *= 0.77 if is_strong else MULTIPLIERS["poor_home_form"]
    elif heavy_home_loss: mult *= MULTIPLIERS["heavy_home_loss"]
    if away_winless_losses:
        mult *= 0.77 if is_strong else MULTIPLIERS["away_winless_losses"]
    elif away_winless:
        mult *= MULTIPLIERS["away_winless"]
    if saturday: mult *= MULTIPLIERS["saturday"]
    if season_opener: mult *= MULTIPLIERS["season_opener"]
    if midseason_restart and not season_opener: mult *= MULTIPLIERS["midseason_restart"]
    if midweek and not lost_bottom: mult *= MULTIPLIERS["midweek"]
    if short_rest and not lost_bottom and not heavy_home_loss: mult *= MULTIPLIERS["short_rest"]
    if summer and tier == "C": mult *= MULTIPLIERS["summer_C"]
    elif summer and tier == "B": mult *= MULTIPLIERS["summer"]
    elif summer and tier in ("S","A"): mult *= 1.08
    elif summer and tier is None: mult *= 1.08 if is_strong else MULTIPLIERS["summer"]  # continuous mode uses ST
    if late_season: mult *= MULTIPLIERS["late_season"]
    if top3_form and tier in ("B","C", None): mult *= MULTIPLIERS["top3_form"]
    if mult < PENALTY_FLOOR: mult = PENALTY_FLOOR
    return min(base * mult, 20000.0)

def predict_calibrated(opponent, enable_ema=False, **kwargs):
    """预测 + EMA 校准。2026-08-03 起默认关闭 EMA（用户确认）。

    理由：EMA 因子是历史残差拟合（0.96-0.98），动态分级后模型已变准，
    乘上它会双重修正、扩大预测噪音。近期(6-8月)验证：关 EMA MAE 380→254（−33%）。
    如需临时开启显式传 enable_ema=True。
    """
    raw = predict(opponent, **kwargs)
    tier = kwargs.get('opponent_tier_override') or classify_opponent_tier(opponent)
    return raw * get_effective_calibration(tier, enable_ema=enable_ema)

def update(match_id, opponent, actual, **ctx):
    cal = _load_cal()
    # 去重：同一match_id不重复更新
    if any(h.get("match_id") == match_id for h in cal.get("history", [])):
        return
    raw = predict(opponent, **ctx)
    # Use dynamic tier override if provided, otherwise fall back to static classification
    tier = ctx.get("opponent_tier_override") or classify_opponent_tier(opponent)
    # Ensure tier is a valid string key
    if not isinstance(tier, str) or tier not in ("S", "A", "B", "C"):
        tier = classify_opponent_tier(opponent)
    # S 级永久禁用 EMA（仅申花 1 场样本，校准无意义；2026-08-03 用户确认）
    if tier == "S":
        return
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
