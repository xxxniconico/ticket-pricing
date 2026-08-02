"""数据缓存与预测计算。"""
from collections import defaultdict
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard.components.ctx_builder import build_pred_args
from src.classify import DERBY_RIVALS
from src.csl_context import (
    detect_ctx,
    finalize_guoan_schedule,
    get_guoan_matches,
    get_next_guoan_match,
    load_csl_data,
    resolve_next_matches,
)
from src.dynamic_optimizer import DynamicPricingOptimizer
from src.pricing_v5 import ZONE_TIERS
from dashboard.common.engine_compat import predict_calibrated_safe as rule_predict

ROOT = Path(__file__).resolve().parent.parent.parent

# 赛程引擎版本 — Streamlit 页脚可见，用于确认线上是否已部署
SCHEDULE_ENGINE_VERSION = "v5-next-fix"

_ctx_rounds: dict = {}


def set_ctx_rounds(rounds):
    global _ctx_rounds
    _ctx_rounds = rounds


def get_ctx_rounds():
    return _ctx_rounds

# ── CSS ─────────────────────────────────────────────────
def load_css():
    css_path = Path(__file__).resolve().parent.parent / "style.css"
    if css_path.exists():
        with open(css_path) as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# ── Cached Data ─────────────────────────────────────────
@st.cache_data(ttl=3600)
def get_optimizer():
    return DynamicPricingOptimizer(revenue_weight=0.6)

def _keep_guoan_match(m: dict) -> bool:
    """保留 CSL 赛程来源；已完赛场次不受 source 限制。"""
    if m.get("completed"):
        return True
    src = m.get("source", "")
    return "cfl_fixtures_api" in src or "wikipedia" in src


@st.cache_data(ttl=7200)
def load_data(_cache_version: int = 5):
    all_matches, rounds, deductions = load_csl_data()
    guoan = get_guoan_matches(all_matches)
    guoan = [m for m in guoan if _keep_guoan_match(m)]
    guoan = finalize_guoan_schedule(guoan)
    return all_matches, rounds, guoan

@st.cache_data(ttl=3600)
def _get_csl_parquet():
    """返回过滤后的 CSL parquet DataFrame（去 partial/bundle）。"""
    pq = ROOT / "data/processed/all_unified.parquet"
    if not pq.exists():
        return None
    df = pd.read_parquet(pq)
    df["数量"] = pd.to_numeric(df["数量"])
    df["实际支付价格"] = pd.to_numeric(df["实际支付价格"])
    df["is_home"] = df["is_home"] == "True"
    return df[(df["competition"] == "CSL") & (df["is_partial"] == "False") & (df["is_bundle"] == "False")]


@st.cache_data(ttl=3600)
def get_actual(m):
    from src.match_notes import get_adjusted_actual
    csl = _get_csl_parquet()
    if csl is None:
        return 0
    for mid in csl["match_id"].unique():
        md = csl[csl["match_id"] == mid]
        if str(md["match_date"].iloc[0]).startswith(m["date"]):
            raw = int(md["数量"].sum())
            return get_adjusted_actual(mid, raw)
    return 0

def _face_to_tier_map(md):
    """按当场票名称面价从低到高映射 T1-T6。
    票名称如"260元"→260。每场取所有面价升序，对应 T1(最低)..T6(最高)。
    返回 {面价数字: 档位}。
    """
    import re as _re
    faces = set()
    for name in md["票名称"].dropna().unique():
        mt = _re.search(r"(\d+)", str(name))
        if mt:
            faces.add(int(mt.group(1)))
    faces = sorted(faces)
    # 升序面价对应 T1..T6
    tiers = ["T1", "T2", "T3", "T4", "T5", "T6"]
    return {fc: tiers[i] for i, fc in enumerate(faces) if i < len(tiers)}


def _parse_face(name):
    import re as _re
    mt = _re.search(r"(\d+)", str(name))
    return int(mt.group(1)) if mt else None


@st.cache_data(ttl=3600)
def _get_zone_qtys(m):
    from src.pricing_v5 import get_zone_sections
    csl = _get_csl_parquet()
    if csl is None:
        return {}
    for mid in csl["match_id"].unique():
        md = csl[csl["match_id"] == mid]
        if str(md["match_date"].iloc[0]).startswith(m["date"]):
            md = md.copy()
            f2t = _face_to_tier_map(md)
            md["zt"] = md["票名称"].map(_parse_face).map(f2t)
            result = {}
            for zt in ZONE_TIERS:
                result[zt] = int(md[md["zt"] == zt]["数量"].sum())
            return result
    return {}

@st.cache_data(ttl=3600)
def _get_zone_actual_revenue(m):
    """返回每档实际收入（从 parquet 实际支付价格列求和）。"""
    from src.pricing_v5 import get_zone_sections
    csl = _get_csl_parquet()
    if csl is None:
        return {}
    for mid in csl["match_id"].unique():
        md = csl[csl["match_id"] == mid]
        if str(md["match_date"].iloc[0]).startswith(m["date"]):
            md = md.copy()
            f2t = _face_to_tier_map(md)
            md["zt"] = md["票名称"].map(_parse_face).map(f2t)
            result = {}
            for zt in ZONE_TIERS:
                result[zt] = float(md[md["zt"] == zt]["实际支付价格"].sum())
            return result
    return {}

@st.cache_data(ttl=3600)
def _get_zone_face_revenue(m):
    """返回每档票面收入（从 parquet 票价信息列解析面值 × 数量）。
    
    票价信息格式: "300.00*2" → 面值 300.00 × 数量 2 = 票面收入 600.00。
    与 _get_zone_actual_revenue 的区别：不含优惠券/学生折扣偏差。
    """
    from src.pricing_v5 import get_zone_sections
    csl = _get_csl_parquet()
    if csl is None:
        return {}
    for mid in csl["match_id"].unique():
        md = csl[csl["match_id"] == mid]
        if str(md["match_date"].iloc[0]).startswith(m["date"]):
            md = md.copy()
            f2t = _face_to_tier_map(md)
            md["zt"] = md["票名称"].map(_parse_face).map(f2t)
            # 票面收入 = 票名称面价 × 数量
            md["face_unit"] = md["票名称"].map(_parse_face)
            md["face_revenue"] = md["face_unit"] * md["数量"]
            result = {}
            for zt in ZONE_TIERS:
                result[zt] = float(md[md["zt"] == zt]["face_revenue"].sum())
            return result
    return {}

# ── Standings Builder ───────────────────────────────────
@st.cache_data(ttl=7200)
def build_standings_2026(all_matches=None):
    """逐轮排名快照 {round: {team: rank}}。最新轮用 json 官方 standings（含扣分）。

    历史教训（2026-08-03）：自算排名不扣分+postponed 场次场次不齐，
    导致国安显示 #3（官方 #7），top3_form 误触发 ×1.08 溢价。
    """
    try:
        _, rounds, _ = load_csl_data()
        return rounds
    except Exception:
        # 极端 fallback：仅当数据源完全不可用时按已赛比分自算（无扣分，精度受限）
        from src.csl_context import load_csl_data as _ld
        return _build_standings_fallback(all_matches)


def _build_standings_fallback(all_matches):
    ts = defaultdict(lambda: {"p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "pts": 0})
    standings = {}
    if not all_matches:
        return standings
    for m in sorted([x for x in all_matches if str(x.get('date', '')).startswith('2026')], key=lambda x: x['date']):
        if not m.get('completed'):
            continue
        rnd, h, a = m['round'], m['home'], m['away']
        ts[h]['p'] += 1; ts[a]['p'] += 1
        ts[h]['gf'] += m['hg']; ts[h]['ga'] += m['ag']
        ts[a]['gf'] += m['ag']; ts[a]['ga'] += m['hg']
        if m['hg'] > m['ag']:
            ts[h]['w'] += 1; ts[h]['pts'] += 3; ts[a]['l'] += 1
        elif m['hg'] == m['ag']:
            ts[h]['d'] += 1; ts[a]['d'] += 1; ts[h]['pts'] += 1; ts[a]['pts'] += 1
        else:
            ts[a]['w'] += 1; ts[a]['pts'] += 3; ts[h]['l'] += 1
        rank = [(t, s['p'], s['pts'], s['gf'] - s['ga'], s['gf']) for t, s in ts.items()]
        rank.sort(key=lambda x: (-x[2], -x[3], -x[4]))
        standings[rnd] = {t: i + 1 for i, (t, *_) in enumerate(rank)}
    return standings

def _round_num(r):
    try: return int(str(r).replace("第", "").replace("轮", ""))
    except: return 0

# ── Prediction Computer ─────────────────────────────────
def compute_home_predictions(home_done, guoan_matches, enable_ema=False):
    """Returns list of (match, prediction, actual, ctx) for completed home games."""
    results = []
    for m in home_done:
        a = get_actual(m)
        if a == 0:
            continue
        ctx = detect_ctx(m, guoan_matches, _ctx_rounds)
        pred_args = build_pred_args(m, ctx)
        # Dynamic tier (always on)
        opponent_tier = None
        try:
            from src.opponent_rating import get_opponent_scorecard, load_elo_history
            from src.csl_context import load_csl_data
            elo_hist = load_elo_history()
            all_matches, _, _ = load_csl_data()
            card = get_opponent_scorecard(m["opponent"], m["date"], elo_history=elo_hist,
                                           standings_by_round=_ctx_rounds, matches=all_matches)
            opponent_tier = card["tier"]
        except Exception:
            pass
        p = rule_predict(m["opponent"], enable_ema=enable_ema,
                         opponent_tier_override=opponent_tier, **pred_args)
        results.append((m, p, a, ctx))
    return results
