"""Tab: 下一场预测。"""
import pandas as pd
import streamlit as st

from dashboard.common.brand import team_crest_html
from dashboard.common.constants import PT_LABELS, TIER_COLORS, TIER_LABELS, WEEKDAYS
from dashboard.components.prediction_detail import render_prediction_detail
from dashboard.components.pricing_ui import render_recent_results
from src.classify import DERBY_RIVALS, classify_opponent_tier
from src.pricing_v5 import get_pricing_tier


def render_tab1(target_match, home_preds, guoan_matches, standings, mae):
    opp = target_match["opponent"]
    dt = pd.Timestamp(target_match["date"])
    tier = classify_opponent_tier(opp)
    pt = get_pricing_tier(opp)

    crest_html = team_crest_html(opp, "lg")
    derby_class = "derby-match" if opp in DERBY_RIVALS else ""
    tier_color = TIER_COLORS.get(tier, "#8a8f98")
    st.markdown(f"""<div style="display:flex;align-items:center;gap:10px;padding:4px 0" class="{derby_class}">
      {crest_html}<span style="font-size:1.3rem;font-weight:590;color:#f7f8f8">{target_match['date']} vs {opp}</span>
      <span style="font-size:0.72rem;font-weight:590;color:{tier_color};background:{tier_color}22;
        padding:2px 8px;border-radius:4px;border:1px solid {tier_color}44">{tier}级</span>
    </div>""", unsafe_allow_html=True)
    st.caption(f"{TIER_LABELS.get(tier, tier)} | 定价: {PT_LABELS.get(pt, pt)} | {target_match['round']} | {WEEKDAYS[dt.weekday()]}")
    if opp in DERBY_RIVALS:
        st.caption("🔥 德比战 · 球迷关注度最高 · 建议收入优先策略")

    render_recent_results(target_match, guoan_matches, standings)
    render_prediction_detail(target_match, guoan_matches, standings, mae, key_prefix="tab1")
