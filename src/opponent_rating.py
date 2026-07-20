"""动态对手分级 — 评分引擎 V1.0

ELO -> ST 实力分 -> AP 吸引力分 -> effective_tier (S/A/B/C)
双维度连续评分 + 离散档位映射 + 不对称阈值（下调易/上调难）
"""
from __future__ import annotations

import json, os
from collections import defaultdict
from pathlib import Path
import numpy as np, pandas as pd

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"
_ELO_PATH = _DATA_DIR / "elo_history.parquet"
_APPEAL_PATH = _DATA_DIR / "appeal_scores.parquet"
_ALL_UNIFIED = _DATA_DIR / "all_unified.parquet"

K_DEFAULT, K_EARLY, K_LATE, HOME_ADV = 20, 30, 15, 65.0

INITIAL_ELO_2023 = {
    "武汉三镇": 1550, "山东泰山": 1550, "浙江": 1525,
    "成都蓉城": 1525, "上海海港": 1525, "北京国安": 1525,
    "上海申花": 1500, "河南": 1500, "天津津门虎": 1500,
    "梅州客家": 1500, "长春亚泰": 1500,
    "大连人": 1475, "深圳队": 1475, "沧州雄狮": 1475,
}
ELO_NEW_PROMOTED, ELO_MEAN = 1425, 1500.0
K_DEFAULT, K_EARLY, K_LATE, HOME_ADV = 25, 35, 18, 65.0

PROMOTED_2023 = {"青岛海牛", "南通支云"}
PROMOTED_2024 = {"深圳新鹏城", "青岛西海岸", "云南玉昆", "大连英博海发"}
PROMOTED_2026 = {"辽宁铁人", "重庆铜梁龙"}
_ALL_PROMOTED = PROMOTED_2023 | PROMOTED_2024 | PROMOTED_2026

DERBY_BONUS = {"上海申花": 30, "山东泰山": 20, "天津津门虎": 20}
FROZEN_TIERS = {"上海申花": "S"}

TOPIC_SCORES = {"new_promoted": 5, "star_player": 10, "default": 0}

# ── 自动话题检测 ───────────────────────────────────────────────────────────
def _detect_topic(opponent, match_date, standings_by_round, matches):
    """基于 MCP 积分榜数据自动检测话题标签。"""
    from src.csl_context import _normalize_club_name
    t = _normalize_club_name(opponent)
    dt = pd.Timestamp(match_date)
    
    tags = []
    
    # 升班马首赛季（排名相关话题已由 PERF 覆盖）
    if t in PROMOTED_2026:
        return "new_promoted"
    
    return "default"

ALL_CSL_TEAMS_2026 = [
    "上海申花", "成都蓉城", "山东泰山", "天津津门虎",
    "上海海港", "深圳新鹏城", "浙江", "河南",
    "武汉三镇", "云南玉昆", "青岛西海岸",
    "青岛海牛", "大连英博海发", "辽宁铁人", "重庆铜梁龙",
]

_NORM_PARAMS = {"ELO": (1400.0, 1700.0), "PPG": (0.5, 2.0), "L5_PPG": (0.0, 2.5), "GD_per": (-1.5, 1.5)}


# ============================================================
# Task 1.1 - ELO
# ============================================================

def _elo_update(rating_a, rating_b, score_a, k=20, home_adv=65.0):
    expected_a = 1.0 / (1.0 + 10.0 ** ((rating_b - (rating_a + home_adv)) / 400.0))
    return (rating_a + k * (score_a - expected_a),
            rating_b + k * ((1.0 - score_a) - (1.0 - expected_a)))

def _get_k_factor(round_num, total_rounds=30):
    if round_num <= 5: return K_EARLY
    if round_num >= total_rounds - 4: return K_LATE
    return K_DEFAULT

def _parse_round(round_str):
    digits = "".join(filter(str.isdigit, str(round_str)))
    return int(digits) if digits else 0

def _get_initial_elo(team):
    from src.csl_context import _normalize_club_name
    t = _normalize_club_name(team)
    if t in INITIAL_ELO_2023: return float(INITIAL_ELO_2023[t])
    if t in _ALL_PROMOTED: return float(ELO_NEW_PROMOTED)
    return float(ELO_MEAN)

def compute_elo_history(matches):
    from src.csl_context import _normalize_club_name
    sorted_matches = sorted(matches, key=lambda x: x["date"])
    current_elo, rows = {}, []
    for m in sorted_matches:
        home = _normalize_club_name(m["home"])
        away = _normalize_club_name(m["away"])
        rnd = _parse_round(m.get("round", "第1轮"))
        completed = m.get("completed", False)
        if home not in current_elo: current_elo[home] = _get_initial_elo(home)
        if away not in current_elo: current_elo[away] = _get_initial_elo(away)
        elo_h_before, elo_a_before = current_elo[home], current_elo[away]
        if completed and m.get("hg") is not None and m.get("ag") is not None:
            if m["hg"] > m["ag"]: score_a, rh, ra = 1.0, "W", "L"
            elif m["hg"] == m["ag"]: score_a, rh, ra = 0.5, "D", "D"
            else: score_a, rh, ra = 0.0, "L", "W"
            k = _get_k_factor(rnd)
            new_h, new_a = _elo_update(elo_h_before, elo_a_before, score_a, k=k)
            current_elo[home], current_elo[away] = new_h, new_a
            rows.append({"date": m["date"], "round": m["round"], "team": home,
                "elo_before": elo_h_before, "elo_after": new_h, "opponent": away,
                "result": rh, "k": k})
            rows.append({"date": m["date"], "round": m["round"], "team": away,
                "elo_before": elo_a_before, "elo_after": new_a, "opponent": home,
                "result": ra, "k": k})
    df = pd.DataFrame(rows)
    if not df.empty: df["date"] = pd.to_datetime(df["date"])
    return df

def get_elo_at(team, date_str, elo_history):
    from src.csl_context import _normalize_club_name
    t = _normalize_club_name(team)
    dt = pd.Timestamp(date_str)
    subset = elo_history[(elo_history["team"] == t) & (elo_history["date"] <= dt)]
    if subset.empty: return _get_initial_elo(t)
    return float(subset.sort_values("date").iloc[-1]["elo_after"])


# ============================================================
# Task 1.2 - ST
# ============================================================

def _normalize_to_0_100(value, min_val, max_val):
    if max_val <= min_val: return 50.0
    return max(0.0, min(100.0, (value - min_val) / (max_val - min_val) * 100.0))

def _compute_ppg(team, date_str, matches):
    from src.csl_context import _normalize_club_name
    t = _normalize_club_name(team)
    dt = pd.Timestamp(date_str)
    year = dt.year
    played, points = 0, 0.0
    for m in matches:
        if not m.get("completed") or m["hg"] is None or m["ag"] is None: continue
        md = pd.Timestamp(m["date"])
        if md.year != year or md > dt: continue
        home = _normalize_club_name(m["home"])
        away = _normalize_club_name(m["away"])
        if home == t:
            played += 1
            if m["hg"] > m["ag"]: points += 3
            elif m["hg"] == m["ag"]: points += 1
        elif away == t:
            played += 1
            if m["ag"] > m["hg"]: points += 3
            elif m["ag"] == m["hg"]: points += 1
    return points / played if played > 0 else 0.0

def _compute_l5_ppg(team, date_str, matches):
    from src.csl_context import _normalize_club_name
    t = _normalize_club_name(team)
    dt = pd.Timestamp(date_str)
    team_matches = []
    for m in matches:
        if not m.get("completed") or m["hg"] is None or m["ag"] is None: continue
        md = pd.Timestamp(m["date"])
        if md > dt: continue
        home = _normalize_club_name(m["home"])
        away = _normalize_club_name(m["away"])
        if home == t or away == t: team_matches.append(m)
    recent = sorted(team_matches, key=lambda x: x["date"])[-5:]
    if not recent: return 0.0
    points = 0.0
    for m in recent:
        home = _normalize_club_name(m["home"])
        if home == t:
            if m["hg"] > m["ag"]: points += 3
            elif m["hg"] == m["ag"]: points += 1
        else:
            if m["ag"] > m["hg"]: points += 3
            elif m["ag"] == m["hg"]: points += 1
    return points / 5

def _compute_gd_per(team, date_str, matches):
    from src.csl_context import _normalize_club_name
    t = _normalize_club_name(team)
    dt = pd.Timestamp(date_str)
    played, gd_total = 0, 0
    for m in matches:
        if not m.get("completed") or m["hg"] is None or m["ag"] is None: continue
        md = pd.Timestamp(m["date"])
        if md > dt: continue
        home = _normalize_club_name(m["home"])
        away = _normalize_club_name(m["away"])
        if home == t:
            played += 1; gd_total += m["hg"] - m["ag"]
        elif away == t:
            played += 1; gd_total += m["ag"] - m["hg"]
    return gd_total / played if played > 0 else 0.0

def compute_strength(team, date_str, elo_history, standings_by_round, matches):
    from src.csl_context import _normalize_club_name
    t = _normalize_club_name(team)
    elo = get_elo_at(t, date_str, elo_history)
    ppg = _compute_ppg(t, date_str, matches)
    if ppg == 0.0:
        # 升班马: 用 ELO 算 ST, 不硬赋 (fix P2-1)
        return max(0.0, min(100.0, 50.0 + 0.3 * (elo - ELO_MEAN) / 10.0))
    l5_ppg = _compute_l5_ppg(t, date_str, matches)
    gd_per = _compute_gd_per(t, date_str, matches)
    st_raw = (0.40 * _normalize_to_0_100(elo, *_NORM_PARAMS["ELO"])
            + 0.30 * _normalize_to_0_100(ppg, *_NORM_PARAMS["PPG"])
            + 0.20 * _normalize_to_0_100(l5_ppg, *_NORM_PARAMS["L5_PPG"])
            + 0.10 * _normalize_to_0_100(gd_per, *_NORM_PARAMS["GD_per"]))
    return max(0.0, min(100.0, st_raw))


# ============================================================
# Task 1.3 - AP
# ============================================================

def _load_guoan_home_attendance():
    if not _ALL_UNIFIED.exists():
        return pd.DataFrame(columns=["match_date", "opponent", "attendance", "match_tier"])
    df = pd.read_parquet(_ALL_UNIFIED)
    df["数量"] = pd.to_numeric(df["数量"])
    df["实际支付价格"] = pd.to_numeric(df["实际支付价格"])
    df["is_home"] = df["is_home"] == "True"
    # 对齐看板口径：CSL only, 排除 partial/bundle, 用 数量列求和
    csl = df[(df["competition"] == "CSL") & (df["is_partial"] == "False") & (df["is_bundle"] == "False")]
    home = csl[csl["is_home"] == True].copy()
    home["match_date"] = pd.to_datetime(home["match_date"])
    from src.csl_context import _normalize_club_name
    home["opponent"] = home["opponent"].apply(lambda x: _normalize_club_name(str(x)))
    return home.groupby(["match_date", "opponent", "match_tier"])["数量"].sum().reset_index(name="attendance")

def _attendance_percentile(opponent, guoan_home_history):
    from src.csl_context import _normalize_club_name
    t = _normalize_club_name(opponent)
    if guoan_home_history.empty: return 15.0  # 全空: 偏低
    opp_data = guoan_home_history[guoan_home_history["opponent"] == t]
    if opp_data.empty:
        # 升班马/无历史: 给最低档, 由 brand prior 接管
        if t in _ALL_PROMOTED: return 5.0  # 升班马保守默认（P1-2: 15→5）（不依赖排名）
        return 15.0  # 其他老队无数据: 偏低
    # 样本衰减: <4场向整体均值收缩 (fix P2-2)
    n = len(opp_data)
    decay = min(1.0, n / 4.0)  # 1场=0.25, 4场=1.0
    avg_att = float(opp_data["attendance"].mean())
    overall_mean = float(guoan_home_history["attendance"].mean())
    avg_att = decay * avg_att + (1 - decay) * overall_mean
    all_avg = guoan_home_history.groupby("opponent")["attendance"].mean()
    rank = (all_avg < avg_att).sum()
    total = len(all_avg)
    if total <= 1: return 50.0
    return max(0.0, min(100.0, (rank / (total - 1)) * 100.0))

def _cur_year_att_ratio(opponent, match_date, guoan_home_history):
    """跨年趋势：最近N次工体交锋上座率 vs 更早N次的均值。

    不卡年份——中超每队一年只来工体一次，卡年份永远凑不够3场。
    n=0 → None（升班马）; n=1 → 1.0（无法判断趋势）;
    n≥2 → recent/older 比值钳制在 [0.5,1.5]。
    """
    from src.csl_context import _normalize_club_name
    t = _normalize_club_name(opponent)
    dt = pd.Timestamp(match_date)
    opp_data = guoan_home_history[
        (guoan_home_history["opponent"] == t) &
        (guoan_home_history["match_date"] < dt)
    ].sort_values("match_date")
    n = len(opp_data)
    if n == 0:
        return None  # 升班马，无任何工体交锋数据
    if n == 1:
        return None  # 只有1场，无法判断趋势，不加分（同升班马）
    # 最近 min(2, n//2) 场 vs 整体历史均值（避免对半切放大极端值）
    recent_n = min(2, max(1, n // 2))
    recent = opp_data.tail(recent_n)
    recent_avg = float(recent["attendance"].mean())
    overall_avg = float(opp_data["attendance"].mean())
    if overall_avg <= 0:
        return 1.0
    return max(0.5, min(1.5, recent_avg / overall_avg))

def _has_cur_data(opponent, match_date, guoan_home_history):
    """检查是否有工体交锋数据（≥1场，不卡年份）。"""
    from src.csl_context import _normalize_club_name
    t = _normalize_club_name(opponent)
    md = pd.Timestamp(match_date)
    if guoan_home_history.empty:
        return False
    opp_data = guoan_home_history[
        (guoan_home_history["opponent"] == t) &
        (guoan_home_history["match_date"] < md)
    ]
    return len(opp_data) >= 1


def _get_perf(opponent, match_date, standings_by_round, matches):
    """排名分位：基于积分榜排名的号召力分（0-100）。
    
    不依赖历史票房数据——升班马和老牌队平等对待。
    rank=1 → 100, rank=16 → 0。
    """
    from src.csl_context import _normalize_club_name
    t = _normalize_club_name(opponent)
    dt = pd.Timestamp(match_date)
    yr = str(dt.year)
    
    # 从 matches 计算积分（含扣分——反映官方积分榜，球迷看的就这个）
    ded = {}
    try:
        from src.csl_context import load_csl_data
        _, _, ded_data = load_csl_data()
        ded = ded_data.get("deductions_by_club", {})
    except Exception:
        pass
    
    team_pts = {}
    for m in matches:
        if not m.get("completed") or m["hg"] is None: continue
        md = m["date"]
        if md > match_date: continue
        if not md.startswith(yr): continue
        for side, gf, ga in [(m["home"], m["hg"], m["ag"]), (m["away"], m["ag"], m["hg"])]:
            t2 = _normalize_club_name(side)
            if t2 not in team_pts: team_pts[t2] = 0
            if gf > ga: team_pts[t2] += 3
            elif gf == ga: team_pts[t2] += 1
    
    for team_name in team_pts:
        team_pts[team_name] -= ded.get(team_name, 0)
    
    ranked = sorted(team_pts.items(), key=lambda x: -x[1])
    total = len(ranked)
    if total <= 1:
        return 50.0
    
    for i, (team_name, _) in enumerate(ranked):
        if team_name == t:
            rank = i + 1
            return max(0.0, min(100.0, (total - rank) / (total - 1) * 100.0))
    
    return 50.0  # 没找到排名，默认中等

def compute_appeal(opponent, match_date,
                   guoan_home_history=None, cur_year_attendance=None,
                   hist_avg_attendance=None, last_h2h=None, topic_tag=None,
                   standings_by_round=None, matches=None):
    from src.csl_context import _normalize_club_name
    t = _normalize_club_name(opponent)
    if guoan_home_history is None or guoan_home_history.empty:
        guoan_home_history = _load_guoan_home_attendance()
    hist_pct = _attendance_percentile(t, guoan_home_history)
    derby_raw = DERBY_BONUS.get(t, 0.0)
    cur_ratio = _cur_year_att_ratio(t, match_date, guoan_home_history)
    if cur_ratio is not None:
        cur_scaled = (cur_ratio - 0.5) / 1.0 * 100.0  # 0.5→0, 1.0→50, 1.5→100
    else:
        cur_scaled = 0.0  # 升班马无数据，不加分
    # 排名分位（不依赖历史，升班马和老牌队平等）
    perf = _get_perf(t, match_date, standings_by_round or {}, matches or [])
    # Auto-detect topic if not explicitly provided
    if topic_tag is None:
        topic_tag = _detect_topic(t, match_date, standings_by_round or {}, matches or [])
    topic_raw = TOPIC_SCORES.get(topic_tag or "default", 0.0)
    # 有历史数据: HIST主导,PERF微调；无历史: PERF主导
    n_hist = len(guoan_home_history[guoan_home_history["opponent"] == t])
    if n_hist >= 1:
        w_hist, w_perf = 0.35, 0.10  # 真实票房说了算
    else:
        w_hist, w_perf = 0.15, 0.25  # 没历史，排名多信一点
    ap_raw = (w_hist * hist_pct + w_perf * perf + 0.15 * derby_raw
            + 0.10 * cur_scaled + 0.10 * topic_raw)
    return max(0.0, min(100.0, ap_raw))


# ── 连续 base 预测 ──────────────────────────────────────────────────────
def compute_continuous_base(st, ap, tier=None):
    """基于连续 ST/AP 在离散 TIER_BASE 锚点间平滑微调。

    以动态 tier 为锚点，ST 在档位内 ±5% 微调，AP ±3% 修正。
    """
    # 确定锚点
    TIER_ANCHORS = {"S": (12600.0, 85.0), "A": (10900.0, 70.0), "B": (8200.0, 50.0), "C": (5700.0, 25.0)}
    tier = tier or "B"
    anchor, center_st = TIER_ANCHORS.get(tier, (8200.0, 50.0))
    
    # ST 微调: 偏离中心 ±10% → ±5% base
    if center_st > 0:
        st_adj = 1.0 + (st - center_st) / center_st * 0.05
        st_adj = max(0.95, min(1.05, st_adj))
    else:
        st_adj = 1.0
    
    # AP 微调: AP=50→1.0, AP=0→0.97, AP=100→1.03
    ap_adj = 1.0 + (ap - 50.0) / 50.0 * 0.03
    
    return round(anchor * st_adj * ap_adj, 0)

# ── 国安自身状态乘数 ───────────────────────────────────────────────────
def compute_guoan_form_multiplier(match_date, elo_history=None, standings_by_round=None, matches=None):
    """基于国安自身排名计算全局预测修正乘数。
    
    国安争冠 → 所有比赛热度上升
    国安保级 → 德比生死战热度上升, 普通比赛下降
    
    Returns: float 乘数 (0.90-1.10)
    
    NOTE: 当前仅监控国安ST走势, 暂不影响预测 (始终返回1.0)。
    等积累足够历史数据后再启用。
    """
    return 1.0  # 监控模式: 不影响预测
    
    # --- 以下为待启用逻辑 ---

# ── 国安自身监控 ───────────────────────────────────────────────────────
def get_guoan_scorecard(match_date, elo_history=None, standings_by_round=None, matches=None):
    """监控国安自身评级（不影响预测, 仅记录走势）。"""
    from src.csl_context import _normalize_club_name
    t = _normalize_club_name("北京国安")
    
    if elo_history is None or elo_history.empty:
        elo_history = load_elo_history()
    if matches is None:
        from src.csl_context import load_csl_data
        matches, standings_by_round, _ = load_csl_data()
    
    st = compute_strength(t, match_date, elo_history, standings_by_round or {}, matches)
    elo_v = get_elo_at(t, match_date, elo_history)
    ppg = _compute_ppg(t, match_date, matches)
    l5 = _compute_l5_ppg(t, match_date, matches)
    gd = _compute_gd_per(t, match_date, matches)
    
    if st >= 80: tier = "S"
    elif st >= 55: tier = "A"
    elif st >= 35: tier = "B"
    else: tier = "C"
    
    return {"team": "北京国安", "date": match_date, "ST": round(st,1),
            "ELO": round(elo_v,1), "PPG": round(ppg,2), "L5_PPG": round(l5,2),
            "GD_per": round(gd,2), "tier": tier}
    from src.csl_context import _normalize_club_name
    t = _normalize_club_name("北京国安")
    dt = pd.Timestamp(match_date)
    
    if elo_history is None or elo_history.empty:
        elo_history = load_elo_history()
    if matches is None:
        from src.csl_context import load_csl_data
        matches, standings_by_round, _ = load_csl_data()
    
    guoan_st = compute_strength(t, match_date, elo_history, standings_by_round or {}, matches)
    
    # 国安排名
    guoan_rank = None
    if standings_by_round:
        yr = str(dt.year)
        parsed = []
        for k in standings_by_round.keys():
            s = str(k)
            if "_" in s and s[:4].isdigit():
                parsed.append((int(s[:4]), int(s.split("_")[1]), k))
            elif "第" in s and "轮" in s:
                n = int(s.replace("第", "").replace("轮", ""))
                parsed.append((9999, n, k))
        parsed.sort(key=lambda x: (x[0], x[1]), reverse=True)
        for py, pn, pk in parsed:
            if py != 9999 and py != int(yr): continue
            if t in standings_by_round[pk]:
                guoan_rank = standings_by_round[pk][t]
                break
    
    if guoan_rank is None:
        return 1.0
    
    if guoan_rank <= 2:
        return 1.08   # 争冠: +8%
    elif guoan_rank <= 5:
        return 1.04   # 亚冠区: +4%
    elif guoan_rank <= 10:
        return 1.00   # 中游: 不变
    elif guoan_rank <= 13:
        return 0.95   # 下游: -5%
    else:
        return 0.92   # 保级区: -8% (恐慌)

# ============================================================
# Task 1.4 - Fusion
# ============================================================

def get_effective_tier(opponent, match_date,
                       elo_history=None, standings_by_round=None,
                       matches=None, guoan_home_history=None,
                       last_h2h=None, topic_tag=None, soft_boundary=True):
    from src.csl_context import _normalize_club_name
    t = _normalize_club_name(opponent)
    if t in FROZEN_TIERS:
        return FROZEN_TIERS[t]
    if elo_history is None or elo_history.empty:
        elo_history = load_elo_history()
    if matches is None:
        from src.csl_context import load_csl_data
        matches, standings_by_round, _ = load_csl_data()
    if guoan_home_history is None or guoan_home_history.empty:
        guoan_home_history = _load_guoan_home_attendance()
    st = compute_strength(t, match_date, elo_history, standings_by_round or {}, matches)
    ap = compute_appeal(t, match_date, guoan_home_history, topic_tag=topic_tag,
                       standings_by_round=standings_by_round, matches=matches)
    # 传统德比：历史票房数据量化20年热度
    hist_pct = _attendance_percentile(t, guoan_home_history)
    # S: exceptional ST + strong AP (申花 hard-locked)
    if st >= 80 and ap >= 70: return "S"
    # A: strong ST + decent AP, OR 德比级票房
    if (st >= 55 and ap >= 40) or hist_pct >= 90: return "A"
    # 老牌强队保护：历史票房中上 + 实力不弱 → A
    if hist_pct >= 55 and st >= 45: return "A"
    # B floor: 高票房球队 (≥80%) 不下探
    if hist_pct >= 80: return "B"
    # AP-protected B: high appeal teams keep B even if ST is weak
    if ap >= 35 and st >= 20: return "B"
    # C: weak ST or very low AP
    if st < 35 or ap < 25:
        tier = "C"
    else:
        tier = "B"
    # Soft boundary: 边界球队有机会升档
    if soft_boundary:
        alt = _check_soft_boundary(st, ap, tier)
        if alt is not None:
            return alt
    return tier

def _check_soft_boundary(st, ap, current_tier):
    if current_tier == "C" and st >= 35 and ap >= 25: return "B"
    if current_tier == "B" and ((st >= 60 and ap >= 30) or (st >= 67 and ap >= 39)): return "A"
    if current_tier == "A" and st >= 77 and ap >= 67: return "S"
    return None

def get_opponent_scorecard(opponent, match_date,
                           elo_history=None, standings_by_round=None,
                           matches=None, guoan_home_history=None, topic_tag=None):
    from src.csl_context import _normalize_club_name
    t = _normalize_club_name(opponent)
    if elo_history is None or elo_history.empty: elo_history = load_elo_history()
    if matches is None:
        from src.csl_context import load_csl_data
        matches, standings_by_round, _ = load_csl_data()
    if guoan_home_history is None or guoan_home_history.empty:
        guoan_home_history = _load_guoan_home_attendance()
    elo = get_elo_at(t, match_date, elo_history)
    st = compute_strength(t, match_date, elo_history, standings_by_round or {}, matches)
    ap = compute_appeal(t, match_date, guoan_home_history, topic_tag=topic_tag,
                       standings_by_round=standings_by_round, matches=matches)
    tier = get_effective_tier(t, match_date, elo_history, standings_by_round or {},
                              matches, guoan_home_history, topic_tag=topic_tag)
    alt_tier = _check_soft_boundary(st, ap, tier)
    return {
        "opponent": t, "elo": round(elo, 1), "ST": round(st, 1), "AP": round(ap, 1),
        "tier": tier, "soft_boundary": alt_tier is not None, "alt_tier": alt_tier,
        "components": {
            "ELO": elo,
            "ST_sub": {"ELO_norm": _normalize_to_0_100(elo, *_NORM_PARAMS["ELO"]),
                       "PPG": _compute_ppg(t, match_date, matches),
                       "L5_PPG": _compute_l5_ppg(t, match_date, matches),
                       "GD_per": _compute_gd_per(t, match_date, matches)},
            "AP_sub": {"HIST_ATT_pct": _attendance_percentile(t, guoan_home_history),
                       "PERF": _get_perf(t, match_date, standings_by_round or {}, matches or []),
                       "DERBY_bonus": DERBY_BONUS.get(t, 0.0),
                       "CUR_YEAR_ratio": _cur_year_att_ratio(t, match_date, guoan_home_history),
                       "TOPIC": TOPIC_SCORES.get(_detect_topic(t, match_date, standings_by_round or {}, matches or []), 0.0)},
        }}


# ============================================================
# Cache I/O + Reseason
# ============================================================

def load_elo_history():
    if _ELO_PATH.exists():
        df = pd.read_parquet(_ELO_PATH)
        if "date" in df.columns: df["date"] = pd.to_datetime(df["date"])
        return df
    return pd.DataFrame()

def save_elo_history(df):
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(_ELO_PATH, index=False)

def save_appeal_scores(df):
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(_APPEAL_PATH, index=False)

def build_snapshot(date_str, elo_history=None, matches=None, standings_by_round=None):
    if elo_history is None or elo_history.empty: elo_history = load_elo_history()
    if matches is None:
        from src.csl_context import load_csl_data
        matches, standings_by_round, _ = load_csl_data()
    guoan_home_history = _load_guoan_home_attendance()
    cards = []
    for team in ALL_CSL_TEAMS_2026:
        card = get_opponent_scorecard(team, date_str, elo_history=elo_history,
            standings_by_round=standings_by_round or {}, matches=matches,
            guoan_home_history=guoan_home_history)
        cards.append(card)
    clean_date = date_str.replace("-", "")
    snapshot_path = _DATA_DIR / f"rating_snapshot_{clean_date}.json"
    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump({"as_of": date_str, "cards": cards}, f, ensure_ascii=False, indent=2)
    return cards

def get_all_tier_distribution(date_str, elo_history=None, matches=None, standings_by_round=None):
    cards = build_snapshot(date_str, elo_history, matches, standings_by_round)
    dist = {"S": 0, "A": 0, "B": 0, "C": 0}
    for c in cards: dist[c["tier"]] = dist.get(c["tier"], 0) + 1
    return dist

def reseason_recalibrate(new_season_year, elo_history=None, matches=None):
    from src.csl_context import _normalize_club_name
    prev_year = new_season_year - 1
    if elo_history is None or elo_history.empty: elo_history = load_elo_history()
    teams_elo = {}
    all_teams = set(elo_history["team"].unique()) if not elo_history.empty else set()
    for team in all_teams:
        t = _normalize_club_name(team)
        last_elo = get_elo_at(t, f"{prev_year}-12-31", elo_history)
        teams_elo[t] = round(last_elo + 0.5 * (ELO_MEAN - last_elo), 1)
    for t in _ALL_PROMOTED:
        if t not in teams_elo: teams_elo[t] = float(ELO_NEW_PROMOTED)
    prev_data = elo_history[elo_history["date"].dt.year == prev_year] if not elo_history.empty else pd.DataFrame()
    if not prev_data.empty:
        last_round = prev_data["date"].max()
        last_snap = prev_data[prev_data["date"] == last_round]
        if not last_snap.empty:
            max_idx = last_snap["elo_after"].idxmax()
            champ = _normalize_club_name(last_snap.loc[max_idx, "team"])
            if champ in teams_elo: teams_elo[champ] = max(teams_elo[champ], 1700.0)
    return teams_elo
