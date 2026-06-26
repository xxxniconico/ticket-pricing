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
    return df[(df["competition"] == "CSL") & (~df["is_partial"]) & (~df["is_bundle"])]


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

@st.cache_data(ttl=3600)
def _get_zone_qtys(m):
    from src.pricing_v5 import get_zone_sections
    csl = _get_csl_parquet()
    if csl is None:
        return {}
    year = m["date"][:4]
    zm = {s: zt for zt, secs in get_zone_sections(year).items() for s in secs}
    for mid in csl["match_id"].unique():
        md = csl[csl["match_id"] == mid]
        if str(md["match_date"].iloc[0]).startswith(m["date"]):
            md = md.copy()
            md["zt"] = md["section"].astype(str).map(zm)
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
    year = m["date"][:4]
    zm = {s: zt for zt, secs in get_zone_sections(year).items() for s in secs}
    for mid in csl["match_id"].unique():
        md = csl[csl["match_id"] == mid]
        if str(md["match_date"].iloc[0]).startswith(m["date"]):
            md = md.copy()
            md["zt"] = md["section"].astype(str).map(zm)
            result = {}
            for zt in ZONE_TIERS:
                result[zt] = float(md[md["zt"] == zt]["实际支付价格"].sum())
            return result
    return {}

# ── Standings Builder ───────────────────────────────────
@st.cache_data(ttl=7200)
def build_standings_2026(all_matches):
    ts = defaultdict(lambda: {"p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "pts": 0})
    standings = {}
    for m in sorted([x for x in all_matches if x['date'].startswith('2026')], key=lambda x: x['date']):
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
        # Dynamic tier support
        opponent_tier = None
        try:
            import streamlit as st
            if st.session_state.get("use_dynamic_tier", False):
                from src.opponent_rating import get_opponent_scorecard, load_elo_history
                from src.csl_context import load_csl_data
                elo_hist = load_elo_history()
                all_matches, _, _ = load_csl_data()
                card = get_opponent_scorecard(m["opponent"], m["date"], elo_history=elo_hist,
                                               standings_by_round=_ctx_rounds, matches=all_matches)
                opponent_tier = card["tier"]
        except Exception as e:
            st.warning(f"Dynamic tier failed: {e}")
        p = rule_predict(m["opponent"], enable_ema=enable_ema,
                         opponent_tier_override=opponent_tier, **pred_args)
        results.append((m, p, a, ctx))
    return results
