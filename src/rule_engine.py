"""
国安散票预测 — 规则引擎 V3（跨赛季泛化）

基值: 每赛季从上一季数据重算（当前: 2025基值）
乘数: 2024→2025跨赛季网格搜索最优
  derby=1.25, lost_bottom=0.55, heavy_home_loss=0.70,
  away_winless=0.78, saturday=1.12, late_season=0.60, big_win_prev=0.82
惩罚底线: 0.35
EMA α: 0.20
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from src.classify import classify_opponent_tier, DERBY_RIVALS

# ── 规则参数 ──
# 基值: 2025赛季中位数（每年从上一季重算）
TIER_BASE: dict[str, float] = {"S": 12200, "A": 10900, "B": 9500, "C1": 9000, "C2": 6500}

# 乘数: 跨赛季网格搜索最优（2024→2025公平测试）
MULTIPLIERS = {
    "derby": 1.25,            # 默认德比（B/C级全量）
    "derby_B": 1.12,          # B级德比降档
    "lost_bottom": 0.55,
    "heavy_home_loss": 0.70,
    "away_winless": 0.78,
    "saturday": 1.12,
    "late_season": 0.60,
    "season_opener": 1.12,    # 赛季首个主场
    "short_rest": 0.82,       # 距上一主场≤5天
    "midweek": 0.85,          # 周二三四工作日
}

# 惩罚底线: 负向乘数叠加不跌破此值
PENALTY_FLOOR = 0.35

# ── 校准 ──
_CAL_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "calibration.json")
_ALPHA = 0.20


def _load_cal() -> dict:
    if not os.path.exists(_CAL_FILE):
        return {"tier": {"S": 1.0, "A": 1.0, "B": 1.0, "C1": 1.0, "C2": 1.0}, "history": []}
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
            ) -> float:
    """规则引擎 V3 预测单场上座（未校准）。

    big_win_prev → 覆盖 lost_bottom（乐观压倒旧伤）。
    B级derby → ×1.15（京津德比降档）。
    """
    tier = classify_opponent_tier(opponent)
    base = TIER_BASE.get(tier, 9000)
    mult = 1.0

    if derby and tier != "S":
        if tier == "B":
            mult *= MULTIPLIERS["derby_B"]
        else:
            mult *= MULTIPLIERS["derby"]

    if lost_bottom:
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
    return new


def get_calibration() -> dict:
    return _load_cal()["tier"]


def get_history() -> pd.DataFrame:
    return pd.DataFrame(_load_cal().get("history", []))


def detect_context_2026(match_date) -> dict:
    """从CSL Dashboard检测2026比赛情境。"""
    import urllib.request

    md = pd.Timestamp(match_date)
    result = {
        "lost_bottom": False, "heavy_home_loss": False,
        "away_winless": False, "returning_home": False,
        "derby": False, "saturday": md.weekday() == 5,
        "late_season": md.month >= 10, "big_win_prev": False,
    }

    try:
        url = "https://xxxniconico.github.io/csl-dashboard-2026/dashboard_embed.json"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        guoan_matches = []
        for lg in data.get("raw_data", {}).get("leagues", []):
            for m in lg.get("matches", []):
                h = m.get("home_club", ""); a = m.get("away_club", "")
                if "国安" not in h and "国安" not in a: continue
                score = m.get("score", {})
                if not isinstance(score, dict) or score.get("home") is None: continue
                dt = str(m.get("date", ""))[:10]
                is_home = "国安" in h
                hg = int(score["home"]); ag = int(score["away"])
                guoan_matches.append({
                    "date": dt, "is_home": is_home,
                    "opponent": a if is_home else h,
                    "gf": hg if is_home else ag, "ga": ag if is_home else hg,
                })

        df_g = pd.DataFrame(guoan_matches).sort_values("date")
        df_g["md"] = pd.to_datetime(df_g["date"])
        df_g["result"] = df_g.apply(
            lambda r: "W" if r["gf"] > r["ga"] else "D" if r["gf"] == r["ga"] else "L", axis=1)

        prev = df_g[df_g["md"] < md]; prev3 = prev.tail(3)

        st_path = os.path.join(os.path.dirname(__file__), "..", "data", "processed",
                               "standings_2026_by_round.parquet")
        st26 = pd.read_parquet(st_path) if os.path.exists(st_path) else None
        if st26 is not None:
            st26["md"] = pd.to_datetime(st26["date"])

        for _, r in prev3.iterrows():
            if r["result"] != "L": continue
            opp_rank = 8
            if st26 is not None:
                before = st26[st26["md"] <= pd.Timestamp(r["date"])]
                if not before.empty:
                    target = before["round"].max()
                    row = st26[(st26["round"] == target) &
                               (st26["team"].str.contains(str(r["opponent"])[:4], na=False))]
                    if not row.empty: opp_rank = int(row["rank"].iloc[0])
            if opp_rank >= 12: result["lost_bottom"] = True
            if r["is_home"] and (r["ga"] - r["gf"]) >= 2: result["heavy_home_loss"] = True

        away3 = prev3[prev3["is_home"] == False]
        if len(away3) >= 2 and (away3["result"] == "W").sum() == 0:
            result["away_winless"] = True
        if len(prev3) > 0 and not prev3.iloc[-1]["is_home"]:
            result["returning_home"] = True

        # big_win_prev: 上场净胜3+
        if len(prev) > 0 and prev.iloc[-1]["result"] == "W":
            last = prev.iloc[-1]
            if (last["gf"] - last["ga"]) >= 3:
                result["big_win_prev"] = True

    except Exception:
        pass

    return result


def init_from_data():
    """用已有2026数据初始化校准。"""
    parquet = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "all_unified.parquet")
    if not os.path.exists(parquet): return

    all_data = pd.read_parquet(parquet)
    c26 = all_data[
        (all_data["competition"] == "CSL") & (all_data["is_home"])
        & (~all_data["is_bundle"]) & (~all_data["is_partial"])
        & (all_data["match_date"].str.startswith("2026"))
    ]
    _save_cal({"tier": {"S": 1.0, "A": 1.0, "B": 1.0, "C": 1.0}, "history": []})

    for mid in sorted(c26["match_id"].unique()):
        m = c26[c26["match_id"] == mid]
        md = pd.Timestamp(m["match_date"].iloc[0])
        opp = str(m["opponent"].iloc[0])
        actual = int(m["数量"].sum())
        ctx = detect_context_2026(md)
        ctx["derby"] = opp in DERBY_RIVALS
        update(mid, opp, actual, **ctx)
