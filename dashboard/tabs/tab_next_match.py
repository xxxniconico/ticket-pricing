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
    
    # 获取动态分级数据
    st_score = ap_score = 0; hist_n = hist_avg = 0
    st_sub = ap_sub = {}
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
            from src.opponent_rating import _load_guoan_home_attendance
            hist_df = _load_guoan_home_attendance()
            opp_hist = hist_df[hist_df["opponent"] == opp]
            hist_n = len(opp_hist)
            hist_avg = opp_hist["attendance"].mean() if hist_n > 0 else 0
        except Exception as e:
            st.warning(f"Dynamic tier failed: {e}")
            tier = classify_opponent_tier(opp)
    else:
        tier = classify_opponent_tier(opp)
    pt = get_pricing_tier(opp, match_date=target_match["date"])

    # 对手头部
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

    # 近期赛果
    render_recent_results(target_match, guoan_matches, standings)

    # ST/AP 动态评级可视化
    st.markdown("**📊 动态分级**")
    if use_dynamic and st_score > 0:
        hpct = ap_sub['HIST_ATT_pct']
        perf = ap_sub['PERF']
        derby = ap_sub['DERBY_bonus']
        elo_n = st_sub['ELO_norm']
        ppg = st_sub['PPG']
        l5 = st_sub['L5_PPG']
        st_val = st_score; ap_val = ap_score
        tc = {"S":"#ff6b6b","A":"#f0c040","B":"#8a8f98","C":"#51cf66"}.get(tier,"#8a8f98")

        if st_val >= 55: st_bar_c = "#ff6b6b"
        elif st_val >= 35: st_bar_c = "#f0c040"
        else: st_bar_c = "#51cf66"
        if ap_val >= 40: ap_bar_c = "#ff6b6b"
        elif ap_val >= 25: ap_bar_c = "#f0c040"
        else: ap_bar_c = "#51cf66"

        st_pills = f"<span style='background:#1a1d22;padding:1px 6px;border-radius:3px;font-size:0.62rem;margin:0 2px'>ELO {elo_n:.0f}</span>"
        st_pills += f"<span style='background:#1a1d22;padding:1px 6px;border-radius:3px;font-size:0.62rem;margin:0 2px'>场均{ppg:.1f}分</span>"
        st_pills += f"<span style='background:#1a1d22;padding:1px 6px;border-radius:3px;font-size:0.62rem;margin:0 2px'>近5场{l5:.1f}</span>"
        ap_pills = f"<span style='background:#1a1d22;padding:1px 6px;border-radius:3px;font-size:0.62rem;margin:0 2px'>票房{hpct:.0f}%</span>"
        ap_pills += f"<span style='background:#1a1d22;padding:1px 6px;border-radius:3px;font-size:0.62rem;margin:0 2px'>排名分{perf:.0f}</span>"
        if hist_n > 0:
            ap_pills += f"<span style='background:#1a1d22;padding:1px 6px;border-radius:3px;font-size:0.62rem;margin:0 2px'>工体{hist_n}场 均{hist_avg:.0f}张</span>"

        if derby > 0:
            ap_pills += f"<span style='background:#1a1d22;padding:1px 6px;border-radius:3px;font-size:0.62rem;margin:0 2px;color:#ff6b6b'>⚔德比{derby:.0f}</span>"

        if st_val >= 80 and ap_val >= 70: reason = "实力顶尖+票房极强"
        elif hpct >= 90: reason = f"德比级票房热度({hpct:.0f}%)"
        elif st_val >= 55 and ap_val >= 40: reason = "实力与票房兼备"
        elif hpct >= 55 and st_val >= 45: reason = "老牌强队保护"
        elif hpct >= 80: reason = f"票房热度保护({hpct:.0f}%)"
        elif ap_val >= 35 and st_val >= 20: reason = "吸引力驱动"
        elif st_val < 35: reason = "实力偏弱"
        elif ap_val < 25: reason = "票房不足"
        else: reason = "实力中等，未触及A/C边界"

        st.markdown(f'''<div style="background:#0e1014;border:1px solid #1a1d22;border-radius:6px;padding:8px 12px;margin:4px 0">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
          <span style="font-size:0.68rem;color:#8a8f98;width:24px">ST</span>
          <div style="flex:1;height:6px;background:#1a1d22;border-radius:3px">
            <div style="width:{min(st_val,100):.0f}%;height:6px;background:{st_bar_c};border-radius:3px"></div>
          </div>
          <span style="font-size:0.75rem;font-weight:590;color:{st_bar_c};width:28px;text-align:right">{st_val:.0f}</span>
          <span style="width:8px"></span>
          <span style="font-size:0.68rem;color:#8a8f98;width:24px">AP</span>
          <div style="flex:1;height:6px;background:#1a1d22;border-radius:3px">
            <div style="width:{min(ap_val,100):.0f}%;height:6px;background:{ap_bar_c};border-radius:3px"></div>
          </div>
          <span style="font-size:0.75rem;font-weight:590;color:{ap_bar_c};width:28px;text-align:right">{ap_val:.0f}</span>
          <span style="font-size:1.3rem;font-weight:590;color:{tc};min-width:24px;text-align:center">{tier}</span>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span style="font-size:0.62rem;color:#62666d">{st_pills}</span>
          <span style="font-size:0.62rem;color:#62666d">{ap_pills}</span>
          <span style="font-size:0.62rem;color:#8a8f98;min-width:50px;text-align:right">← {reason}</span>
        </div>
        </div>''', unsafe_allow_html=True)

    # 决策卡
    render_prediction_detail(target_match, guoan_matches, standings, mae, key_prefix="tab1", use_dynamic=use_dynamic)
