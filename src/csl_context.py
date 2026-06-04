"""CSL 上下文检测 — 共享模块。看板和测试共用，避免手写上下文。"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

from src.classify import classify_opponent_tier, DERBY_RIVALS

# CSL 数据源：本地优先，云端回退
_CSL_PATH = "/mnt/c/Users/xxxsu/.openclaw/workspace/csl_project_v2/data/csl_final_production_ready.json"
_DEDUCTIONS_PATH = "/mnt/c/Users/xxxsu/.openclaw/workspace/csl_project_v2/config/csl_cfa_2026_official_deductions.json"
_CSL_CLOUD_URL = "https://xxxniconico.github.io/csl-dashboard-2026/dashboard_embed.json"
_DED_CLOUD_URL = "https://raw.githubusercontent.com/xxxniconico/csl-dashboard-2026/main/config/csl_cfa_2026_official_deductions.json"


def load_csl_data(csl_path: str = _CSL_PATH, deductions_path: str = _DEDUCTIONS_PATH):
    """加载 CSL 比赛数据和扣分配置。返回 (matches, standings_by_round, deductions)。"""
    import requests as _requests
    try:
        data = json.load(open(csl_path))
        deductions = json.load(open(deductions_path))
    except (FileNotFoundError, OSError):
        # Cloud 环境回退到 GitHub Pages
        resp = _requests.get(_CSL_CLOUD_URL, timeout=20)
        resp.raise_for_status()
        raw = resp.json()
        data = raw.get("raw_data", raw)
        resp2 = _requests.get(_DED_CLOUD_URL, timeout=10)
        resp2.raise_for_status()
        ded_config = resp2.json()
        deductions = ded_config.get("deductions_by_club", {})

    all_raw = []
    seen_ids = set()
    seen_combos = set()
    for lg in data.get("leagues", []):
        for m in lg.get("matches", []):
            mid = m.get("match_id", f"{m['date']}_{m['home_club']}_{m['away_club']}")
            combo = (m["date"][:10], m["home_club"], m["away_club"])
            if mid in seen_ids or combo in seen_combos:
                continue
            seen_ids.add(mid)
            seen_combos.add(combo)
            all_raw.append(m)
    all_raw.sort(key=lambda x: x["date"])

    def _safe_score(val):
        if val is None: return None
        try: return int(val)
        except: return None

    matches = []
    for i, m in enumerate(all_raw):
        s = m.get("score", {})
        hg = _safe_score(s.get("home")) if isinstance(s, dict) else None
        ag = _safe_score(s.get("away")) if isinstance(s, dict) else None
        ok = hg is not None and ag is not None and m.get("status") != "scheduled"
        # Use round from JSON data, fall back to computed
        rd = m.get("round", f"第{i // 8 + 1}轮")
        matches.append({
            "date": m["date"][:10],
            "round": rd,
            "home": m["home_club"],
            "away": m["away_club"],
            "hg": hg, "ag": ag,
            "completed": ok,
            "source": m.get("source", ""),
        })

    # Build standings
    ts = defaultdict(lambda: {"p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "pts": 0})
    rounds = {}
    for m in sorted(matches, key=lambda x: x["date"]):
        if not m["completed"]: continue
        rnd, h, a = m["round"], m["home"], m["away"]
        ts[h]["p"] += 1; ts[a]["p"] += 1
        ts[h]["gf"] += m["hg"]; ts[h]["ga"] += m["ag"]
        ts[a]["gf"] += m["ag"]; ts[a]["ga"] += m["hg"]
        if m["hg"] > m["ag"]: ts[h]["w"] += 1; ts[h]["pts"] += 3; ts[a]["l"] += 1
        elif m["hg"] == m["ag"]: ts[h]["d"] += 1; ts[a]["d"] += 1; ts[h]["pts"] += 1; ts[a]["pts"] += 1
        else: ts[a]["w"] += 1; ts[a]["pts"] += 3; ts[h]["l"] += 1

        rank = [(t, s_["p"], s_["pts"], deductions.get(t, 0), s_["pts"] - deductions.get(t, 0),
                 s_["gf"] - s_["ga"], s_["gf"], s_["w"], s_["d"], s_["l"]) for t, s_ in ts.items()]
        rank.sort(key=lambda x: (-x[4], -x[5], -x[6]))
        rounds[rnd] = {t: i + 1 for i, (t, *_) in enumerate(rank)}

    return matches, rounds, deductions


def get_guoan_matches(matches):
    """从所有比赛中提取国安赛程。"""
    guoan = []
    for m in matches:
        if "国安" in m["home"] or "国安" in m["away"]:
            is_home = "国安" in m["home"]
            guoan.append({**m, "is_home": is_home, "opponent": m["away"] if is_home else m["home"]})
    return guoan


def detect_ctx(match: dict, guoan_all: list[dict], standings: dict) -> dict:
    """检测单场比赛的情境上下文。

    Args:
        match: 当前比赛 {'date', 'opponent', 'is_home', ...}
        guoan_all: 国安所有比赛（含历史+当前）
        standings: rounds[rnd] = {team: rank}

    Returns:
        {'away_winless', 'lost_bottom', 'heavy_home_loss', 'short_rest'} 中触发的键
    """
    ctx = {}
    md = pd.Timestamp(match["date"])
    prev = [m for m in guoan_all if m.get("completed") and pd.Timestamp(m["date"]) < md]
    last3 = prev[-3:] if len(prev) >= 3 else prev

    # away_winless: 2+ away in last3, 0 away wins
    away3 = [m for m in last3 if not m["is_home"]]
    if len(away3) >= 2 and sum(1 for m in away3 if (
        (m["is_home"] and m["hg"] > m["ag"]) or (not m["is_home"] and m["ag"] > m["hg"])
    )) == 0:
        ctx["away_winless"] = True

    # lost_bottom: 近3场输给C级弱队(升班马等) 或 B级排名≥12
    for m in last3:
        is_loss = (m["is_home"] and m["hg"] < m["ag"]) or (not m["is_home"] and m["ag"] < m["hg"])
        if not is_loss: continue
        opp_tier = classify_opponent_tier(m["opponent"])
        opp_rank = standings.get(m["round"], {}).get(m["opponent"], 8)
        if opp_tier == "C" or (opp_tier == "B" and opp_rank >= 12):
            ctx["lost_bottom"] = True

    # heavy_home_loss: home loss by 2+, no subsequent win to "wash" it
    for i, m in enumerate(last3):
        if not m["is_home"]: continue
        if m["hg"] is None or m["ag"] is None: continue
        if m["hg"] < m["ag"] and abs(m["hg"] - m["ag"]) >= 2:
            later = last3[i + 1:]
            if not any((lm["is_home"] and lm["hg"] > lm["ag"]) or
                       (not lm["is_home"] and lm["ag"] > lm["hg"]) for lm in later):
                ctx["heavy_home_loss"] = True

    # short_rest: ≤4 days since last home match (双赛周=7天内两个主场，5天不算)
    hp = [m for m in prev if m["is_home"]]
    if hp and (md - pd.Timestamp(hp[-1]["date"])).days <= 4:
        ctx["short_rest"] = True
    # unbeaten_3: 近3场不败 → 球迷乐观溢价（完整30轮验证 +13%）
    if len(last3) >= 3:
        if all((g["is_home"] and g["hg"] > g["ag"]) or (not g["is_home"] and g["ag"] > g["hg"]) or g["hg"] == g["ag"] for g in last3):
            ctx["unbeaten_3"] = True

    return ctx


def predict_with_context(opponent: str, match_date: str,
                         matches=None, guoan_all=None, standings=None):
    """一站式：加载数据 → 检测上下文 → 调用规则引擎预测。

    用法:
        from src.csl_context import predict_with_context
        pred = predict_with_context("河南队俱乐部彩陶坊", "2026-05-23")
    """
    from src.rule_engine import predict

    if matches is None:
        matches, standings, _ = load_csl_data()
    if guoan_all is None:
        guoan_all = get_guoan_matches(matches)
        # Filter CSL-only for accurate context
        guoan_all = [m for m in guoan_all if 'cfl_fixtures_api' in m.get('source','') or 'wikipedia' in m.get('source','')]

    match = {"date": match_date, "opponent": opponent, "is_home": True, "completed": True}
    ctx = detect_ctx(match, guoan_all, standings)

    dt = pd.Timestamp(match_date)
    return predict(
        opponent,
        derby=opponent in DERBY_RIVALS,
        saturday=dt.weekday() == 5,
        late_season=dt.month >= 10,
        midweek=dt.weekday() in (1, 2, 3),
        summer=dt.month in (7, 8),
        match_year=match_date[:4],
        **{k: ctx.get(k, False) for k in ["away_winless", "lost_bottom", "heavy_home_loss", "short_rest"]},
    )
