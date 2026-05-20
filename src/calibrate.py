"""用 2025 真实数据校准 context 因子权重（对数线性回归）。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.classify import A_TIER_OPPONENTS, DERBY_RIVALS, build_base_multiplier_lookup
from src.data_feeds import (
    compute_home_form_2025,
    fetch_csl_standings,
    fetch_guoan_2025_all,
    fetch_guoan_2025_home,
    get_opponent_rank_2025,
    get_opponent_standing,
    lost_to_bottom_recently,
    recent_form_before_match,
)
from src.ingest import load_all


def _demand_rows_for_home_match(demand: pd.DataFrame, date: pd.Timestamp, opp: str) -> pd.DataFrame:
    """按 ingest 的 match_id 口径匹配单场需求行。"""
    ds = pd.Timestamp(date).strftime("%Y-%m-%d")
    key = f"{ds} {str(opp).strip()}"
    m = demand[demand["match_id"].astype(str) == key]
    if not m.empty:
        return m
    pref = demand[demand["match_id"].astype(str).str.startswith(ds, na=False)]
    if pref.empty:
        return pref
    needle = str(opp).strip()[:4]
    hit = pref[pref["match_id"].astype(str).str.contains(needle, regex=False, na=False)]
    return hit if not hit.empty else pref


def calibrate_context_weights(data_dir: str = "data/raw") -> dict:
    """用 2025 主场样本回归 ``ln(context_observed)``，得到情境乘子权重。

    context_observed = (实际散票合计 / 同级场均) / base_lookup[对手]
    """
    defaults: dict = {
        "weekend": 1.05,
        "top3_opponent": 1.08,
        "bottom3_opponent": 0.95,
        "home_form_bonus": 0.1,
        "second_half_penalty": 1.0,
        "derby_bonus": 1.35,
        "r_squared": 0.0,
    }

    home_matches = fetch_guoan_2025_home()
    try:
        demand = load_all(data_dir)
        base_lookup = build_base_multiplier_lookup(f"{data_dir}/2025散票数据.xlsx")
    except Exception:
        return defaults.copy()

    per_match = demand.groupby(["match_id", "match_tier"], as_index=False)["quantity"].sum()
    a_avg = float(per_match.loc[per_match["match_tier"] == "A", "quantity"].mean())
    b_avg = float(per_match.loc[per_match["match_tier"] == "B", "quantity"].mean())
    if not np.isfinite(a_avg) or a_avg <= 0:
        a_avg = 1.0
    if not np.isfinite(b_avg) or b_avg <= 0:
        b_avg = 1.0

    rows: list[dict] = []
    for _, match in home_matches.iterrows():
        if pd.isna(match.get("date")):
            continue
        opp = str(match["opponent"]).strip()
        date = pd.Timestamp(match["date"])
        round_num = int(match["round_num"])

        seat_match = _demand_rows_for_home_match(demand, date, opp)
        if seat_match.empty:
            continue
        actual = float(seat_match["quantity"].sum())
        if actual <= 0:
            continue

        tier = "A" if opp in A_TIER_OPPONENTS else "B"
        tier_avg = a_avg if tier == "A" else b_avg
        observed_mult = actual / tier_avg if tier_avg > 0 else 1.0

        base = float(base_lookup.get(opp, 1.0))
        if base <= 0:
            base = 1.0
        context_observed = observed_mult / base

        is_weekend = 1 if date.weekday() >= 5 else 0
        opponent_rank = get_opponent_rank_2025(opp)
        home_form_before = compute_home_form_2025(up_to_round=round_num)
        season_half = 0 if round_num <= 15 else 1
        is_derby = 1 if opp in {"上海申花", "天津津门虎", "山东泰山"} else 0

        rows.append(
            {
                "opponent": opp,
                "round": round_num,
                "actual": actual,
                "observed_mult": observed_mult,
                "base": base,
                "context_observed": context_observed,
                "is_weekend": is_weekend,
                "opp_rank": opponent_rank,
                "is_top3": 1 if opponent_rank <= 3 else 0,
                "is_bottom3": 1 if opponent_rank >= 14 else 0,
                "home_form": home_form_before,
                "season_half": season_half,
                "is_derby": is_derby,
            }
        )

    df = pd.DataFrame(rows)
    if len(df) < 6:
        out = defaults.copy()
        out["r_squared"] = 0.0
        return out

    y = np.log(df["context_observed"].clip(lower=0.1).astype(float).values)
    X = df[
        ["is_weekend", "is_top3", "is_bottom3", "home_form", "season_half", "is_derby"]
    ].astype(float).values
    X_with_const = np.column_stack([np.ones(len(X)), X])
    w, *_ = np.linalg.lstsq(X_with_const, y, rcond=None)
    y_hat = X_with_const @ w
    ss_res = float(np.sum((y - y_hat) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 1e-12 else 0.0

    weights: dict = {
        "weekend": round(float(np.exp(w[1])), 3),
        "top3_opponent": round(float(np.exp(w[2])), 3),
        "bottom3_opponent": round(float(np.exp(w[3])), 3),
        "home_form_bonus": float(w[4]),
        "second_half_penalty": round(float(np.exp(w[5])), 3),
        "derby_bonus": round(float(np.exp(w[6])), 3),
        "r_squared": r2,
    }
    return weights


def _v2_default_model() -> dict:
    """样本过少时的保守系数（与 v2 文档同量级，含比赛日/双赛周项）。"""
    return {
        "intercept": 10.0,
        "form_coef": 1.5,
        "lost_bottom_coef": -0.5,
        "rank_coef": -0.03,
        "derby_coef": 0.2,
        "dow_coef": 0.02,
        "days_since_coef": 0.01,
        "double_coef": -0.15,
        "r_squared": 0.0,
        "n_samples": 0,
    }


def compute_recent_form_5_all_before(
    schedule_df: pd.DataFrame | None,
    before: pd.Timestamp,
) -> float:
    """本场之前（按日期）最近 5 场全主客胜率；无赛果的行不参与。"""
    if schedule_df is None or getattr(schedule_df, "empty", True):
        return 0.5
    df = schedule_df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    if "result" not in df.columns:
        return 0.5
    r = df["result"].astype(str).str.strip().str.upper()
    done = df[r.isin(["W", "D", "L"])]
    sub = done[done["date"] < before].sort_values("date").tail(5)
    if sub.empty:
        return 0.5
    wins = (sub["result"].astype(str).str.strip().str.upper() == "W").sum()
    return float(wins / len(sub))


def compute_lost_to_bottom_recent_before(
    schedule_df: pd.DataFrame | None,
    before: pd.Timestamp,
    rank_fn,
) -> bool:
    """近 3 场（按日期、本场之前）是否曾输给「排名 ≥12」的球队。"""
    if schedule_df is None or schedule_df.empty:
        return False
    df = schedule_df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    if "result" not in df.columns:
        return False
    r = df["result"].astype(str).str.strip().str.upper()
    done = df[r.isin(["W", "D", "L"])]
    prev3 = done[done["date"] < before].sort_values("date").tail(3)
    for _, pm in prev3.iterrows():
        if str(pm["result"]).strip().upper() != "L":
            continue
        pr = int(rank_fn(str(pm["opponent"]).strip()))
        if pr >= 12:
            return True
    return False


def gather_attendance_v2_inputs_for_fixture(
    schedule_df: pd.DataFrame | None,
    match_date: pd.Timestamp,
    opponent: str,
    standings_df: pd.DataFrame | None = None,
) -> dict:
    """组装 ``predict_attendance_v2`` 所需情境（2026 赛程 + 积分榜）。"""
    opp = str(opponent).strip()
    md = pd.Timestamp(match_date)

    if standings_df is not None and not standings_df.empty:
        opp_rank = int(get_opponent_standing(opp, standings_df))
    else:
        opp_rank = int(get_opponent_rank_2025(opp))
    opp_rank = max(1, min(16, opp_rank))

    def _rank(o: str) -> int:
        if standings_df is not None and not standings_df.empty:
            return max(1, min(16, int(get_opponent_standing(o, standings_df))))
        return max(1, min(16, int(get_opponent_rank_2025(o))))

    recent_5 = compute_recent_form_5_all_before(schedule_df, md)
    lost_bottom = compute_lost_to_bottom_recent_before(schedule_df, md, _rank)
    is_derby = opp in DERBY_RIVALS
    day_of_week = int(md.weekday())

    days_since = 14
    is_double = False
    if schedule_df is not None and not schedule_df.empty:
        sch = schedule_df.copy()
        sch["date"] = pd.to_datetime(sch["date"], errors="coerce")
        sch = sch.dropna(subset=["date"])
        v = sch["venue"].astype(str)
        home_rows = sch[v.str.contains("主", na=False) | v.str.upper().isin(["H", "HOME"])]
        if "result" in home_rows.columns:
            rr = home_rows["result"].astype(str).str.strip()
            completed_home = home_rows[rr.ne("") & rr.str.upper().isin(["W", "D", "L"])]
        else:
            completed_home = home_rows.iloc[0:0]
        if not completed_home.empty:
            last_home_date = pd.Timestamp(completed_home.sort_values("date")["date"].iloc[-1])
            days_since = max(0, int((md.normalize() - last_home_date.normalize()).days))

        is_self = (sch["date"].dt.normalize() == md.normalize()) & (
            sch["opponent"].astype(str).str.strip() == opp
        )
        nearby = sch[~is_self]
        if not nearby.empty:
            nd = pd.to_datetime(nearby["date"], errors="coerce").dropna()
            if not nd.empty:
                diffs = abs((nd - md).dt.days)
                is_double = bool((diffs <= 4).sum() > 1)

    return {
        "recent_form_5": recent_5,
        "lost_to_bottom_recent": lost_bottom,
        "opponent_rank": opp_rank,
        "is_derby": is_derby,
        "day_of_week": day_of_week,
        "days_since_last_home": days_since,
        "is_double_matchweek": is_double,
    }


def build_attendance_model_v2(data_dir: str = "data/raw") -> dict:
    """滚动战绩 + 比赛日/双赛周 对 ln(散票销量) 的 OLS。

    特征: recent_form, lost_to_bottom, opp_rank, derby,
    day_of_week, days_since_last_home, is_double
    """
    defaults = _v2_default_model()
    try:
        demand = load_all(data_dir)
    except Exception:
        return defaults.copy()

    home_matches = fetch_guoan_2025_home()
    all_matches = fetch_guoan_2025_all(include_acl=True)
    if all_matches.empty or home_matches.empty:
        return defaults.copy()

    all_matches = all_matches.copy()
    all_matches["date"] = pd.to_datetime(all_matches["date"], errors="coerce")

    rows: list[dict] = []
    for _, match in home_matches.iterrows():
        if pd.isna(match.get("date")):
            continue
        opp = str(match["opponent"]).strip()
        rnd = int(match["round_num"])
        venue = str(match["venue"]).strip().upper()
        if venue != "H":
            continue
        date_ts = pd.Timestamp(match["date"])
        seat_match = _demand_rows_for_home_match(demand, date_ts, opp)
        if seat_match.empty:
            continue
        actual = float(seat_match["quantity"].sum())
        if actual <= 0:
            continue

        recent_form = recent_form_before_match(date_ts, n=5)
        lost_to_bottom = 1 if lost_to_bottom_recently(date_ts) else 0

        opp_rank = int(get_opponent_rank_2025(opp))
        is_derby = 1 if opp in DERBY_RIVALS else 0
        match_date = date_ts
        day_of_week = int(match_date.weekday())

        home_before = all_matches[
            (all_matches["venue"].astype(str).str.strip().str.upper() == "H")
            & (all_matches["competition"] == "CSL")
            & (all_matches["date"] < date_ts)
        ].sort_values("date")
        if not home_before.empty and pd.notna(home_before.iloc[-1]["date"]):
            last_home_date = pd.Timestamp(home_before.iloc[-1]["date"])
            days_since_last = max(0, int((match_date.normalize() - last_home_date.normalize()).days))
        else:
            days_since_last = 14

        date_line = date_ts.normalize()
        is_self = (
            (pd.to_datetime(all_matches["date"], errors="coerce").dt.normalize() == date_line)
            & (all_matches["opponent"].astype(str).str.strip() == opp)
            & (all_matches["venue"].astype(str).str.upper() == "H")
            & (all_matches["competition"] == "CSL")
        )
        nearby = all_matches[~is_self]
        if not nearby.empty:
            nd = pd.to_datetime(nearby["date"], errors="coerce")
            days_diff = abs((nd - match_date).dt.days)
            is_double = int(bool((days_diff <= 4).any()))
        else:
            is_double = 0

        rows.append(
            {
                "opponent": opp,
                "round": rnd,
                "actual": actual,
                "recent_form": recent_form,
                "lost_to_bottom": lost_to_bottom,
                "opp_rank": opp_rank,
                "derby": is_derby,
                "day_of_week": day_of_week,
                "days_since_last": float(days_since_last),
                "is_double": float(is_double),
            }
        )

    df = pd.DataFrame(rows)
    if len(df) < 5:
        out = defaults.copy()
        out["n_samples"] = len(df)
        return out

    y = np.log(df["actual"].astype(float).values)
    X = df[
        [
            "recent_form",
            "lost_to_bottom",
            "opp_rank",
            "derby",
            "day_of_week",
            "days_since_last",
            "is_double",
        ]
    ].astype(float).values
    X_with_c = np.column_stack([np.ones(len(X)), X])
    w, *_ = np.linalg.lstsq(X_with_c, y, rcond=None)
    y_hat = X_with_c @ w
    ss_res = float(np.sum((y - y_hat) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 1e-12 else 0.0

    return {
        "intercept": float(w[0]),
        "form_coef": float(w[1]),
        "lost_bottom_coef": float(w[2]),
        "rank_coef": float(w[3]),
        "derby_coef": float(w[4]),
        "dow_coef": float(w[5]),
        "days_since_coef": float(w[6]),
        "double_coef": float(w[7]),
        "r_squared": r2,
        "n_samples": len(df),
    }


def predict_attendance_v2(
    recent_form_5: float,
    lost_to_bottom_recent: bool,
    opponent_rank: int,
    is_derby: bool = False,
    day_of_week: int = 5,
    days_since_last_home: int = 7,
    is_double_matchweek: bool = False,
    model: dict | None = None,
    max_capacity: int = 27500,
) -> float:
    """滚动战绩 v2：预测散票量级上座（与训练 ``actual`` 同口径，默认封顶总散票池）。"""
    if model is None:
        model = build_attendance_model_v2()
    log_att = float(model.get("intercept", 10.0))
    log_att += float(model.get("form_coef", 0)) * float(recent_form_5)
    log_att += float(model.get("lost_bottom_coef", 0)) * (1.0 if lost_to_bottom_recent else 0.0)
    log_att += float(model.get("rank_coef", 0)) * float(opponent_rank)
    log_att += float(model.get("derby_coef", 0)) * (1.0 if is_derby else 0.0)
    log_att += float(model.get("dow_coef", 0)) * float(day_of_week)
    log_att += float(model.get("days_since_coef", 0)) * float(days_since_last_home)
    log_att += float(model.get("double_coef", 0)) * (1.0 if is_double_matchweek else 0.0)
    return min(float(np.exp(log_att)), float(max_capacity))


def attendance_v2_features_for_2025_home_round(
    all_matches: pd.DataFrame,
    rnd: int,
    match_date: pd.Timestamp,
    opponent: str,
) -> dict:
    """回测单场：由 2025 全量赛程（含亚冠、按日期）构造 v2 特征。"""
    am = all_matches.copy()
    am["date"] = pd.to_datetime(am["date"], errors="coerce")
    md = pd.Timestamp(match_date)
    date_line = md.normalize()

    recent_form = recent_form_before_match(md, n=5)
    lost_bottom = lost_to_bottom_recently(md)

    opp_rank = int(get_opponent_rank_2025(str(opponent).strip()))
    is_derby = str(opponent).strip() in DERBY_RIVALS
    day_of_week = int(md.weekday())
    home_before = am[
        (am["venue"].astype(str).str.strip().str.upper() == "H")
        & (am["competition"] == "CSL")
        & (am["date"] < md)
    ].sort_values("date")
    if not home_before.empty and pd.notna(home_before.iloc[-1]["date"]):
        last_home_date = pd.Timestamp(home_before.iloc[-1]["date"])
        days_since = max(0, int((md.normalize() - last_home_date.normalize()).days))
    else:
        days_since = 14
    opp = str(opponent).strip()
    is_self = (
        (pd.to_datetime(am["date"], errors="coerce").dt.normalize() == date_line)
        & (am["opponent"].astype(str).str.strip() == opp)
        & (am["venue"].astype(str).str.upper() == "H")
        & (am["competition"] == "CSL")
    )
    nearby = am[~is_self]
    if not nearby.empty:
        nd = pd.to_datetime(nearby["date"], errors="coerce")
        days_diff = abs((nd - md).dt.days)
        is_double = bool((days_diff <= 4).any())
    else:
        is_double = False
    return {
        "recent_form_5": recent_form,
        "lost_to_bottom_recent": lost_bottom,
        "opponent_rank": max(1, min(16, opp_rank)),
        "is_derby": is_derby,
        "day_of_week": day_of_week,
        "days_since_last_home": days_since,
        "is_double_matchweek": is_double,
    }


if __name__ == "__main__":
    w = calibrate_context_weights()
    print("校准权重:")
    for k, v in w.items():
        print(f"  {k}: {v}")
    m2 = build_attendance_model_v2()
    print("上座 v2:")
    print(f"  R²={m2.get('r_squared', 0):.3f} (n={m2.get('n_samples', 0)})")


# ═══════════════════════════════════════════════════════════
# V3 扩展模型：用户复购特征 + 座位热力预测
# ═══════════════════════════════════════════════════════════

def _load_unified_data() -> pd.DataFrame:
    """加载统一格式数据（data/processed/all_unified.parquet）。"""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "all_unified.parquet")
    if os.path.exists(path):
        return pd.read_parquet(path)
    return pd.DataFrame()


def _load_user_stats() -> pd.DataFrame:
    """加载用户画像数据。"""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "user_stats.parquet")
    if os.path.exists(path):
        return pd.read_parquet(path)
    return pd.DataFrame()


def _get_opp_rank_2025_replay(opponent: str, match_date) -> int:
    """获取比赛日对手真实排名。

    2025赛季: 从重放积分榜查找；缺失则回退终榜。
    2026赛季: 从 CSL Dashboard 实时拉取。
    """
    import os
    opp = str(opponent).strip()
    md = pd.Timestamp(match_date)
    
    # 2026赛季: 使用实时积分榜（从CSL全量赛果计算）
    if md.year >= 2026:
        st26_path = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "standings_2026_by_round.parquet")
        if os.path.exists(st26_path):
            st26 = pd.read_parquet(st26_path)
            # Find latest standings on or before match date
            st26["date_dt"] = pd.to_datetime(st26["date"], errors="coerce")
            rounds_before = st26[st26["date_dt"] <= md]["round"].unique()
            if len(rounds_before) > 0:
                target_round = max(rounds_before)
                row = st26[(st26["round"] == target_round) & (st26["team"].str.contains(opp[:4], na=False))]
                if not row.empty:
                    return int(row["rank"].iloc[0])
        # Fallback: live API
        try:
            from src.data_feeds import fetch_csl_standings, get_opponent_standing
            st = fetch_csl_standings()
            if not st.empty:
                rank = get_opponent_standing(opp, st)
                if 1 <= rank <= 16:
                    return int(rank)
        except Exception:
            pass
    
    # 2025赛季: 从重放积分榜查找
    st_path = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "standings_2025_by_round.parquet")
    if os.path.exists(st_path):
        st = pd.read_parquet(st_path)
        st["date_dt"] = pd.to_datetime(st["date"], errors="coerce")
        rounds_before = st[st["date_dt"] <= md]["round"].unique()
        if len(rounds_before) > 0:
            target_round = max(rounds_before)
            row = st[(st["round"] == target_round) & (st["team"].str.contains(opp[:4], na=False))]
            if not row.empty:
                return int(row["rank"].iloc[0])
    
    # 回退终榜
    from src.data_feeds import get_opponent_rank_2025
    return int(get_opponent_rank_2025(opp))


def estimate_repeat_ratio(
    opponent: str,
    match_tier: str = "B",
    is_derby: bool = False,
    is_weekend: bool = True,
) -> float:
    """赛前预估复购率。

    基于历史数据: A级/德比吸引更多一次性观众 → repeat_ratio 更低。
    历史均值 ~0.52, A级 ~0.48, 德比 ~0.45, B级工作日 ~0.56.
    """
    base = 0.52
    if match_tier == "A":
        base -= 0.04
    if is_derby:
        base -= 0.07
    if not is_weekend:
        base += 0.04
    return max(0.35, min(0.65, base))


def build_attendance_model_v3() -> dict:
    """V3 上座模型：V2 7特征 + repeat_ratio (预测安全)。

    使用统一数据 (all_unified.parquet) 的 CSL 主场样本。
    若数据不可用，回退到 V2。
    """
    defaults = {
        "intercept": 10.0,
        "form_coef": 1.5,
        "lost_bottom_coef": -0.5,
        "rank_coef": -0.03,
        "derby_coef": 0.2,
        "dow_coef": 0.02,
        "days_since_coef": 0.01,
        "double_coef": -0.15,
        "repeat_ratio_coef": -5.0,
        "r_squared": 0.0,
        "n_samples": 0,
        "version": "v3",
    }

    all_data = _load_unified_data()
    user_stats = _load_user_stats()
    if all_data.empty:
        return defaults.copy()

    # CSL home only
    csl = all_data[
        (all_data["competition"] == "CSL") 
        & (all_data["is_home"] == True) 
        & (all_data["is_bundle"] == False)
        & (all_data.get("is_partial", False) == False)  # 排除预售中/部分数据
    ].copy()
    csl["match_date_dt"] = pd.to_datetime(csl["match_date"])
    match_ids = sorted(csl["match_id"].unique())

    if len(match_ids) < 5:
        return defaults.copy()

    rows = []
    for mid in match_ids:
        m = csl[csl["match_id"] == mid]
        md = m["match_date_dt"].iloc[0]
        opp = str(m["opponent"].iloc[0])

        recent_form = recent_form_before_match(md, n=5)
        lost_bot = 1 if lost_to_bottom_recently(md) else 0
        opp_rank = _get_opp_rank_2025_replay(opp, md)
        is_derby = 1 if opp in DERBY_RIVALS else 0
        day_of_week = int(md.weekday())

        csl_home = csl[csl["match_date_dt"] < md]
        if not csl_home.empty:
            days_since = max(0, int((md.normalize() - csl_home["match_date_dt"].max().normalize()).days))
        else:
            days_since = 14

        other = csl[csl["match_id"] != mid]
        if not other.empty:
            diffs = abs((other["match_date_dt"] - md).dt.days)
            is_double = int((diffs <= 4).any())
        else:
            is_double = 0

        # Repeat ratio from user stats
        if not user_stats.empty:
            mu = m["大麦用户id"].unique()
            ms = user_stats[user_stats["大麦用户id"].isin(mu)]
            repeat_ratio = (ms["total_matches"] > 1).sum() / len(ms) if len(ms) > 0 else 0.5
        else:
            repeat_ratio = 0.5

        total = float(m["数量"].sum())

        rows.append({
            "total": total,
            "recent_form": recent_form,
            "lost_to_bottom": lost_bot,
            "opp_rank": opp_rank,
            "derby": is_derby,
            "day_of_week": day_of_week,
            "days_since_last": float(days_since),
            "is_double": float(is_double),
            "repeat_ratio": repeat_ratio,
        })

    df = pd.DataFrame(rows)
    if len(df) < 5:
        return defaults.copy()

    y = np.log(df["total"].values)
    X = df[[
        "recent_form", "lost_to_bottom", "opp_rank", "derby",
        "day_of_week", "days_since_last", "is_double", "repeat_ratio",
    ]].astype(float).values

    X_c = np.column_stack([np.ones(len(X)), X])
    w, *_ = np.linalg.lstsq(X_c, y, rcond=None)
    y_hat = X_c @ w
    ss_res = float(np.sum((y - y_hat) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 1e-12 else 0.0

    return {
        "intercept": float(w[0]),
        "form_coef": float(w[1]),
        "lost_bottom_coef": float(w[2]),
        "rank_coef": float(w[3]),
        "derby_coef": float(w[4]),
        "dow_coef": float(w[5]),
        "days_since_coef": float(w[6]),
        "double_coef": float(w[7]),
        "repeat_ratio_coef": float(w[8]),
        "r_squared": r2,
        "n_samples": len(df),
        "version": "v3",
    }


def predict_attendance_v3(
    recent_form_5: float,
    lost_to_bottom_recent: bool,
    opponent_rank: int,
    is_derby: bool = False,
    day_of_week: int = 5,
    days_since_last_home: int = 7,
    is_double_matchweek: bool = False,
    repeat_ratio: float | None = None,
    opponent: str = "",
    match_tier: str = "B",
    model: dict | None = None,
    max_capacity: int = 27500,
) -> float:
    """V3 预测：V2 特征 + 预估复购率。"""
    if model is None:
        model = build_attendance_model_v3()

    if repeat_ratio is None:
        repeat_ratio = estimate_repeat_ratio(
            opponent=opponent, match_tier=match_tier,
            is_derby=is_derby, is_weekend=(day_of_week >= 5),
        )

    log_att = float(model.get("intercept", 10.0))
    log_att += float(model.get("form_coef", 0)) * float(recent_form_5)
    log_att += float(model.get("lost_bottom_coef", 0)) * (1.0 if lost_to_bottom_recent else 0.0)
    log_att += float(model.get("rank_coef", 0)) * float(opponent_rank)
    log_att += float(model.get("derby_coef", 0)) * (1.0 if is_derby else 0.0)
    log_att += float(model.get("dow_coef", 0)) * float(day_of_week)
    log_att += float(model.get("days_since_coef", 0)) * float(days_since_last_home)
    log_att += float(model.get("double_coef", 0)) * (1.0 if is_double_matchweek else 0.0)
    log_att += float(model.get("repeat_ratio_coef", 0)) * float(repeat_ratio)
    return min(float(np.exp(log_att)), float(max_capacity))


def get_section_heatmap() -> pd.DataFrame:
    """座位热力：各区段场均售票 + 均价 + 前后排偏好。

    Returns DataFrame: section, floor, per_match, avg_price, front_row_pct
    """
    all_data = _load_unified_data()
    if all_data.empty:
        return pd.DataFrame()

    csl = all_data[(all_data["competition"] == "CSL") & (all_data["is_bundle"] == False) & (all_data.get("is_partial", False) == False)].copy()
    n_matches = csl["match_id"].nunique()

    csl_valid = csl[csl["row_num"] > 0].copy()

    heatmap = csl.groupby(["section", "floor"]).agg(
        total_seats=("数量", "sum"),
        avg_price=("实际支付价格", "mean"),
        unique_users=("大麦用户id", "nunique"),
    ).reset_index()

    heatmap["per_match"] = heatmap["total_seats"] / n_matches

    # Front row preference
    front = csl_valid[csl_valid["row_num"] <= 10].groupby("section")["数量"].sum()
    total_rows = csl_valid.groupby("section")["数量"].sum()
    front_pct = (front / total_rows.replace(0, np.nan)).fillna(0)

    heatmap["front_row_pct"] = heatmap["section"].map(front_pct).fillna(0)
    heatmap = heatmap.sort_values("per_match", ascending=False)

    return heatmap


# ═══════════════════════════════════════════════════════════
# V4 上座模型：2025-only 六特征 + 2025+2026 增量 live
# ═══════════════════════════════════════════════════════════

def _v4_default_model() -> dict:
    return {
        "intercept": 10.0,
        "form_coef": 1.5,
        "lost_bottom_coef": -0.5,
        "rank_coef": -0.03,
        "derby_coef": 0.2,
        "weekend_coef": 0.05,
        "double_coef": -0.15,
        "r_squared": 0.0,
        "n_samples": 0,
        "version": "v4",
    }


def _csl_home_complete_matches(all_data: pd.DataFrame) -> pd.DataFrame:
    """CSL 主场、非套票、非预售中的场次级汇总。"""
    if all_data.empty:
        return pd.DataFrame()
    partial_col = all_data["is_partial"] if "is_partial" in all_data.columns else False
    csl = all_data[
        (all_data["competition"] == "CSL")
        & (all_data["is_home"] == True)
        & (all_data["is_bundle"] == False)
        & (partial_col == False)
    ].copy()
    if csl.empty:
        return pd.DataFrame()
    csl["match_date_dt"] = pd.to_datetime(csl["match_date"], errors="coerce")
    agg = (
        csl.groupby("match_id", as_index=False)
        .agg(
            match_date=("match_date_dt", "first"),
            opponent=("opponent", "first"),
            total_tickets=("数量", "sum"),
        )
        .dropna(subset=["match_date"])
    )
    return agg


def _is_double_matchweek(all_data: pd.DataFrame, match_id: str, match_date: pd.Timestamp) -> int:
    other = all_data[all_data["match_id"] != match_id]
    if other.empty:
        return 0
    if "match_date_dt" not in other.columns:
        other = other.copy()
        other["match_date_dt"] = pd.to_datetime(other["match_date"], errors="coerce")
    diffs = abs((other["match_date_dt"] - match_date).dt.days)
    return int((diffs <= 4).any())


def _build_v4_training_rows(
    matches: pd.DataFrame,
    all_data: pd.DataFrame,
    *,
    rank_fn,
) -> list[dict]:
    rows: list[dict] = []
    for _, row in matches.iterrows():
        md = pd.Timestamp(row["match_date"])
        opp = str(row["opponent"]).strip()
        mid = str(row["match_id"])
        total = float(row["total_tickets"])
        if total <= 0:
            continue

        recent_form = recent_form_before_match(md, n=5)
        lost_bottom = 1 if lost_to_bottom_recently(md) else 0
        opp_rank = int(rank_fn(opp, md))
        is_derby = 1 if opp in DERBY_RIVALS else 0
        is_weekend = 1 if md.weekday() >= 5 else 0
        is_double = _is_double_matchweek(all_data, mid, md)

        rows.append(
            {
                "total": total,
                "recent_form": recent_form,
                "lost_to_bottom": lost_bottom,
                "opp_rank": opp_rank,
                "derby": is_derby,
                "is_weekend": is_weekend,
                "is_double": float(is_double),
            }
        )
    return rows


def _fit_v4_ols(rows: list[dict], defaults: dict) -> dict:
    df = pd.DataFrame(rows)
    if len(df) < 5:
        out = defaults.copy()
        out["n_samples"] = len(df)
        return out

    y = np.log(df["total"].astype(float).values)
    X = df[
        ["recent_form", "lost_to_bottom", "opp_rank", "derby", "is_weekend", "is_double"]
    ].astype(float).values
    X_c = np.column_stack([np.ones(len(X)), X])
    w, *_ = np.linalg.lstsq(X_c, y, rcond=None)
    y_hat = X_c @ w
    ss_res = float(np.sum((y - y_hat) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 1e-12 else 0.0

    return {
        "intercept": float(w[0]),
        "form_coef": float(w[1]),
        "lost_bottom_coef": float(w[2]),
        "rank_coef": float(w[3]),
        "derby_coef": float(w[4]),
        "weekend_coef": float(w[5]),
        "double_coef": float(w[6]),
        "r_squared": r2,
        "n_samples": len(df),
        "version": "v4",
    }


def build_attendance_model_v4() -> dict:
    """2025-only：ln(散票) ~ 近态/输保级/排名/德比/周末/双赛周。"""
    defaults = _v4_default_model()
    all_data = _load_unified_data()
    if all_data.empty:
        return defaults.copy()

    matches = _csl_home_complete_matches(all_data)
    matches = matches[matches["match_date"].astype(str).str.contains("2025", na=False)]
    if matches.empty:
        return defaults.copy()

    all_data = all_data.copy()
    all_data["match_date_dt"] = pd.to_datetime(all_data["match_date"], errors="coerce")

    def rank_fn(opp: str, _md: pd.Timestamp) -> int:
        return int(get_opponent_rank_2025(opp))

    rows = _build_v4_training_rows(matches, all_data, rank_fn=rank_fn)
    return _fit_v4_ols(rows, defaults)


def build_attendance_model_live() -> dict:
    """2025 全量 + 2026 已完赛；2026 场次用实时积分榜排名。"""
    defaults = _v4_default_model()
    defaults["version"] = "live"
    all_data = _load_unified_data()
    if all_data.empty:
        return defaults.copy()

    matches = _csl_home_complete_matches(all_data)
    m2025 = matches[matches["match_date"].astype(str).str.contains("2025", na=False)]
    m2026 = matches[matches["match_date"].astype(str).str.contains("2026", na=False)]
    matches = pd.concat([m2025, m2026], ignore_index=True)
    if matches.empty:
        return defaults.copy()

    all_data = all_data.copy()
    all_data["match_date_dt"] = pd.to_datetime(all_data["match_date"], errors="coerce")

    standings = fetch_csl_standings()

    def rank_fn(opp: str, md: pd.Timestamp) -> int:
        if md.year >= 2026 and standings is not None and not standings.empty:
            return max(1, min(16, int(get_opponent_standing(opp, standings))))
        return int(get_opponent_rank_2025(opp))

    rows = _build_v4_training_rows(matches, all_data, rank_fn=rank_fn)
    out = _fit_v4_ols(rows, defaults)
    out["version"] = "live"
    return out


def predict_attendance_v4(
    recent_form_5: float,
    lost_to_bottom_recent: bool,
    opponent_rank: int,
    is_derby: bool = False,
    is_weekend: bool = True,
    is_double_matchweek: bool = False,
    model: dict | None = None,
    max_capacity: int = 27500,
) -> float:
    """V4 六特征预测散票上座。"""
    if model is None:
        model = build_attendance_model_v4()
    log_att = float(model.get("intercept", 10.0))
    log_att += float(model.get("form_coef", 0)) * float(recent_form_5)
    log_att += float(model.get("lost_bottom_coef", 0)) * (1.0 if lost_to_bottom_recent else 0.0)
    log_att += float(model.get("rank_coef", 0)) * float(opponent_rank)
    log_att += float(model.get("derby_coef", 0)) * (1.0 if is_derby else 0.0)
    log_att += float(model.get("weekend_coef", 0)) * (1.0 if is_weekend else 0.0)
    log_att += float(model.get("double_coef", 0)) * (1.0 if is_double_matchweek else 0.0)
    return min(float(np.exp(log_att)), float(max_capacity))


def gather_attendance_v4_inputs_for_fixture(
    schedule_df: pd.DataFrame | None,
    match_date: pd.Timestamp,
    opponent: str,
    standings_df: pd.DataFrame | None = None,
    is_weekend: bool | None = None,
) -> dict:
    """组装 ``predict_attendance_v4`` 所需情境。"""
    opp = str(opponent).strip()
    md = pd.Timestamp(match_date)
    v2 = gather_attendance_v2_inputs_for_fixture(schedule_df, md, opp, standings_df)
    if is_weekend is None:
        is_weekend = md.weekday() >= 5
    return {
        "recent_form_5": float(v2["recent_form_5"]),
        "lost_to_bottom_recent": bool(v2["lost_to_bottom_recent"]),
        "opponent_rank": int(v2["opponent_rank"]),
        "is_derby": bool(v2["is_derby"]) or opp in DERBY_RIVALS,
        "is_weekend": bool(is_weekend),
        "is_double_matchweek": bool(v2["is_double_matchweek"]),
    }


def compute_match_importance(standings_df: pd.DataFrame) -> dict[str, float | int | str]:
    """距亚冠区(前三)与距降级区(后三)的分数差。"""
    out: dict[str, float | int | str] = {
        "guoan_rank": 0,
        "guoan_points": 0,
        "gap_to_acl": None,
        "gap_to_relegation": None,
        "acl_line_points": None,
        "relegation_line_points": None,
        "label": "数据不足",
    }
    if standings_df is None or standings_df.empty:
        return out
    st = standings_df.sort_values("rank").reset_index(drop=True)
    guoan = st[st["team"].astype(str).str.contains("国安", na=False)]
    if guoan.empty:
        return out
    gr = guoan.iloc[0]
    rk = int(gr["rank"])
    pts = float(gr["points"])
    out["guoan_rank"] = rk
    out["guoan_points"] = pts

    if len(st) >= 3:
        acl_pts = float(st.iloc[2]["points"])
        out["acl_line_points"] = acl_pts
        out["gap_to_acl"] = round(acl_pts - pts, 1)

    if len(st) >= 16:
        rel_pts = float(st.iloc[15]["points"])
    elif len(st) >= 3:
        rel_pts = float(st.iloc[-1]["points"])
    else:
        rel_pts = None
    if rel_pts is not None:
        out["relegation_line_points"] = rel_pts
        out["gap_to_relegation"] = round(pts - rel_pts, 1)

    gap_acl = out["gap_to_acl"]
    gap_rel = out["gap_to_relegation"]
    if gap_acl is not None and gap_acl <= 3:
        out["label"] = "亚冠争夺"
    elif gap_rel is not None and gap_rel <= 3:
        out["label"] = "保级关键"
    elif gap_acl is not None and gap_acl <= 6:
        out["label"] = "争亚冠"
    else:
        out["label"] = "常规争位"
    return out
