"""Tab: 下一场预测。"""
import pandas as pd
import streamlit as st

from dashboard.common.brand import team_crest_html
from dashboard.common.constants import PT_LABELS, TIER_COLORS, TIER_LABELS, WEEKDAYS
from dashboard.components.prediction_detail import render_prediction_detail
from dashboard.components.pricing_ui import render_recent_results
from src.classify import DERBY_RIVALS, classify_opponent_tier
from src.pricing_v5 import get_pricing_tier


def render_tab1(target_match, home_preds, guoan_matches, standings, mae, use_dynamic=False):
    opp = target_match["opponent"]
    dt = pd.Timestamp(target_match["date"])
    if use_dynamic:
        from src.opponent_rating import get_opponent_scorecard, load_elo_history
        from src.csl_context import load_csl_data
        try:
            elo = load_elo_history()
            all_matches, _, _ = load_csl_data()
            card = get_opponent_scorecard(opp, target_match["date"], elo_history=elo,
                                           standings_by_round=standings, matches=all_matches)
            tier = card["tier"]
            st_score = card["ST"]
            ap_score = card["AP"]
            st_sub = card["components"]["ST_sub"]
            ap_sub = card["components"]["AP_sub"]
            
            # 展示详细分解
            col1, col2, col3 = st.columns([2, 2, 1])
            with col1:
                st.caption(f"**ST 实力分 {st_score:.0f}**")
                st.caption(f"ELO={st_sub['ELO_norm']:.0f} | PPG={st_sub['PPG']:.2f} | L5={st_sub['L5_PPG']:.2f}")
            with col2:
                st.caption(f"**AP 吸引力 {ap_score:.0f}**")
                st.caption(f"票房%={ap_sub['HIST_ATT_pct']:.0f} | 排名分={ap_sub['PERF']:.0f} | 德比={ap_sub['DERBY_bonus']:.0f}")
            with col3:
                tier_color = {"S":"#ff6b6b","A":"#f0c040","B":"#8a8f98","C":"#51cf66"}.get(tier,"#8a8f98")
                st.markdown(f'<div style="text-align:center;padding-top:10px"><span style="font-size:1.4rem;font-weight:590;color:{tier_color}">{tier}</span><br><span style="font-size:0.6rem;color:#62666d">动态分级</span></div>', unsafe_allow_html=True)
        except Exception as e:
            st.warning(f"Dynamic tier failed: {e}")
            tier = classify_opponent_tier(opp)
    else:
        tier = classify_opponent_tier(opp)
    pt = get_pricing_tier(opp, match_date=target_match["date"])

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
    render_prediction_detail(target_match, guoan_matches, standings, mae, key_prefix="tab1", use_dynamic=use_dynamic)
