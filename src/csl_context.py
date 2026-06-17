"""CSL 上下文检测 — 共享模块。看板和测试共用，避免手写上下文。"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path

import pandas as pd

from src.classify import classify_opponent_tier, DERBY_RIVALS

# 队名别名 — 合并 CSL 数据源中同一俱乐部的不同写法（如 大连英博 / 大连英博海发）
_CLUB_ALIASES = {
    "浙江队": "浙江",
    "浙江俱乐部绿城": "浙江",
    "河南队": "河南",
    "河南俱乐部彩陶坊": "河南",
    "大连英博": "大连英博海发",
    "辽宁铁人楠波湾": "辽宁铁人",
}


def _normalize_club_name(name: str) -> str:
    s = str(name).strip()
    if s in _CLUB_ALIASES.values():
        return s
    return _CLUB_ALIASES.get(s, s)


def _match_has_score(m: dict) -> bool:
    s = m.get("score", {})
    if not isinstance(s, dict):
        return False
    return s.get("home") is not None and s.get("away") is not None


def _match_dedup_priority(m: dict) -> tuple:
    """去重时优先保留已完赛、有比分的记录。"""
    has_score = _match_has_score(m)
    finished = m.get("status") not in (None, "scheduled") and has_score
    return (1 if finished else 0, 1 if has_score else 0, len(m.get("events") or []))

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
        # Cloud数据source字段为空, 统一标记为云端来源
        for lg in data.get("leagues", []):
            for m in lg.get("matches", []):
                if not m.get("source"):
                    m["source"] = "cfl_fixtures_api"
        resp2 = _requests.get(_DED_CLOUD_URL, timeout=10)
        resp2.raise_for_status()
        ded_config = resp2.json()
        deductions = ded_config.get("deductions_by_club", {})

    by_combo: dict[tuple, dict] = {}
    seen_ids: set[str] = set()
    for lg in data.get("leagues", []):
        for m in lg.get("matches", []):
            mid = m.get("match_id", f"{m['date']}_{m['home_club']}_{m['away_club']}")
            if mid in seen_ids:
                continue
            seen_ids.add(mid)
            combo = (
                m["date"][:10],
                _normalize_club_name(m["home_club"]),
                _normalize_club_name(m["away_club"]),
            )
            if combo not in by_combo or _match_dedup_priority(m) > _match_dedup_priority(by_combo[combo]):
                by_combo[combo] = m
    all_raw = sorted(by_combo.values(), key=lambda x: x["date"])

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
            "home": _normalize_club_name(m["home_club"]),
            "away": _normalize_club_name(m["away_club"]),
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


def get_next_guoan_match(guoan_matches: list[dict], *, home_only: bool = False) -> dict | None:
    """下一场未赛国安比赛。跳过已过期但仍标 scheduled 的脏数据。"""
    today = pd.Timestamp(date.today())
    for m in guoan_matches:
        if not str(m.get("date", "")).startswith("2026"):
            continue
        if m.get("completed"):
            continue
        if home_only and not m.get("is_home"):
            continue
        if pd.Timestamp(m["date"]) < today:
            continue
        return m
    return None


def finalize_guoan_schedule(guoan_matches: list[dict]) -> list[dict]:
    """国安赛程后处理：同日同主客去重（保留已赛），丢弃过期 scheduled 脏行。"""
    today = pd.Timestamp(date.today())
    by_key: dict[tuple, dict] = {}
    for m in guoan_matches:
        key = (m["date"], m.get("is_home"))
        prev = by_key.get(key)
        if prev is None:
            by_key[key] = m
        elif m.get("completed") and not prev.get("completed"):
            by_key[key] = m
        elif m.get("completed") and prev.get("completed") and m.get("hg") is not None:
            by_key[key] = m
    out = sorted(by_key.values(), key=lambda x: x["date"])
    return [
        m for m in out
        if m.get("completed") or pd.Timestamp(m["date"]) >= today
    ]


def resolve_next_matches(guoan_matches: list[dict]) -> tuple[dict | None, dict | None, dict | None]:
    """返回 (next_match, next_home, target_match)。"""
    next_match = get_next_guoan_match(guoan_matches)
    next_home = get_next_guoan_match(guoan_matches, home_only=True)
    if next_match and next_match.get("is_home"):
        target = next_match
    elif next_home:
        target = next_home
    else:
        target = None
    return next_match, next_home, target


def detect_ctx(match: dict, guoan_all: list[dict], standings: dict) -> dict:
    """检测单场比赛的情境上下文（V5.6 对齐 rule_engine.predict）。

    Returns:
        可能包含的键: away_winless, away_winless_losses, consecutive_home_losses,
        poor_home_form, heavy_home_loss, short_rest, midseason_restart, season_opener, top3_form
    """
    ctx = {}
    md = pd.Timestamp(match["date"])
    prev = [m for m in guoan_all if m.get("completed") and pd.Timestamp(m["date"]) < md]
    last3 = prev[-3:] if len(prev) >= 3 else prev

    # away_winless / away_winless_losses: 近3场中≥2客且0胜
    away3 = [m for m in last3 if not m["is_home"]]
    if len(away3) >= 2 and sum(1 for m in away3 if (
        (m["is_home"] and m["hg"] > m["ag"]) or (not m["is_home"] and m["ag"] > m["hg"])
    )) == 0:
        all_losses = all(
            (m["hg"] < m["ag"]) if m["is_home"] else (m["ag"] < m["hg"])
            for m in away3
        )
        if all_losses:
            ctx["away_winless_losses"] = True
        else:
            ctx["away_winless"] = True

    # consecutive_home_losses: 最近两主场均失利（V5.5，优先级高于惨败/输保级）
    home_prev = [m for m in prev if m["is_home"]]
    if len(home_prev) >= 2:
        last_two = home_prev[-2:]
        if all(
            m["hg"] is not None and m["ag"] is not None and m["hg"] < m["ag"]
            for m in last_two
        ):
            ctx["consecutive_home_losses"] = True

    # poor_home_form: 近3主场≥2负（V5.7，与consecutive_home_losses互斥，更宽泛）
    # 标定: S/A档×0.77, B/C档×0.82 — 2025梅州(B)21.5%→0.4%, 2026海港(A+poor_form)29.3%→0.4%
    if not ctx.get("consecutive_home_losses") and len(home_prev) >= 3:
        last_three = home_prev[-3:]
        losses = sum(
            1 for m in last_three
            if m["hg"] is not None and m["ag"] is not None and m["hg"] < m["ag"]
        )
        if losses >= 2:
            ctx["poor_home_form"] = True

    # heavy_home_loss: home loss by 2+, no subsequent win to "wash" it
    if not ctx.get("consecutive_home_losses") and not ctx.get("poor_home_form"):
        for i, m in enumerate(last3):
            if not m["is_home"]:
                continue
            if m["hg"] is None or m["ag"] is None:
                continue
            if m["hg"] < m["ag"] and abs(m["hg"] - m["ag"]) >= 2:
                # 德比对手的大败不触发惨败惩罚 — 输给宿敌是情感对决而非实力崩盘
                if m.get("opponent") in DERBY_RIVALS:
                    continue
                later = last3[i + 1:]
                if not any((lm["is_home"] and lm["hg"] > lm["ag"]) or
                           (not lm["is_home"] and lm["ag"] > lm["hg"]) for lm in later):
                    ctx["heavy_home_loss"] = True

    # short_rest: ≤4 days since last home match (双赛周=7天内两个主场，5天不算)
    hp = [m for m in prev if m["is_home"]]
    if hp and (md - pd.Timestamp(hp[-1]["date"])).days <= 4:
        ctx["short_rest"] = True
    # midseason_restart: >=28 days since last match, months 6-7, not season opener
    if prev and md.month in (6, 7):
        if (md - pd.Timestamp(prev[-1]["date"])).days >= 28:
            ctx["midseason_restart"] = True
    # season_opener: 该自然年首场主场比赛
    same_year_home = [m for m in prev if m["is_home"] and pd.Timestamp(m["date"]).year == md.year]
    if not same_year_home:
        ctx["season_opener"] = True
    # top3_form: 国安排名前三 → 争冠/亚冠预期溢价 (V5.6)
    # 2025年6-8月国安排名前3时B级比值均值1.32x vs 非前3的1.12x，溢价~18%
    # 保守标定1.08，仅对B/C级生效（S/A级已含高质量对手溢价）
    if prev and standings:
        guoan_rank = None
        yr = str(md.year)
        # standings keys 可能是 '2025_01' (复合键) 或 '第15轮' (字符串) 或 15 (数字)
        # 统一转为 (year, round_num) 排序
        parsed = []
        for k in standings.keys():
            s = str(k)
            # 检测复合键: '2025_01'
            if '_' in s and s[:4].isdigit():
                parsed.append((int(s[:4]), int(s.split('_')[1]), k))
            elif '第' in s and '轮' in s:
                n = int(s.replace('第','').replace('轮',''))
                parsed.append((9999, n, k))  # 无年份信息，放最后
            else:
                digits = ''.join(filter(str.isdigit, s))
                if digits:
                    parsed.append((9999, int(digits), k))
        parsed.sort(key=lambda x: (x[0], x[1]), reverse=True)
        # 找到比赛日期所属赛季的最新轮次
        for py, pn, pk in parsed:
            if py != 9999 and py != int(yr):
                continue
            if '北京国安' in standings[pk]:
                guoan_rank = standings[pk]['北京国安']
                break
        if guoan_rank is not None and guoan_rank <= 3:
            ctx["top3_form"] = True
            ctx["guoan_rank"] = guoan_rank

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
    ctx_kwargs = {k: ctx.get(k, False) for k in [
        "away_winless", "away_winless_losses", "consecutive_home_losses", "heavy_home_loss",
        "short_rest", "midseason_restart", "season_opener",
        "top3_form",
    ]}
    return predict(
        opponent,
        derby=opponent in DERBY_RIVALS,
        saturday=dt.weekday() == 5,
        midweek=dt.weekday() in (1, 2, 3),
        summer=dt.month in (7, 8),
        match_year=match_date[:4],
        **ctx_kwargs,
    )
