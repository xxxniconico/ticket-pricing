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
                st.caption(f"ELO={st_sub['ELO_norm']:.0f} | 场均积分={st_sub['PPG']:.2f} | 近5场={st_sub['L5_PPG']:.2f}")
            with col2:
                st.caption(f"**AP 吸引力 {ap_score:.0f}**")
                st.caption(f"票房排位={ap_sub['HIST_ATT_pct']:.0f}% | 联赛分位={ap_sub['PERF']:.0f} | 德比加分={ap_sub['DERBY_bonus']:.0f}")
            with col3:
                tier_color = {"S":"#ff6b6b","A":"#f0c040","B":"#8a8f98","C":"#51cf66"}.get(tier,"#8a8f98")
                st.markdown(f'<div style="text-align:center;padding-top:10px"><span style="font-size:1.4rem;font-weight:590;color:{tier_color}">{tier}</span><br><span style="font-size:0.6rem;color:#62666d">动态分级</span></div>', unsafe_allow_html=True)

            # 判定原因（中文细分指数）
            hpct = ap_sub['HIST_ATT_pct']
            perf = ap_sub['PERF']
            derby = ap_sub['DERBY_bonus']
            elo_n = st_sub['ELO_norm']
            ppg = st_sub['PPG']
            l5 = st_sub['L5_PPG']

            # 构建自然语言解释
            parts = []
            # ST描述
            st_desc = f"ELO分位{elo_n:.0f}"
            if ppg >= 1.8: st_desc += f"，场均{ppg:.1f}分(强)"
            elif ppg >= 1.2: st_desc += f"，场均{ppg:.1f}分(中)"
            else: st_desc += f"，场均{ppg:.1f}分(弱)"
            if l5 >= 2.0: st_desc += f"，近5场{l5:.1f}分(状态火热)"
            elif l5 >= 1.2: st_desc += f"，近5场{l5:.1f}分(状态平稳)"
            else: st_desc += f"，近5场{l5:.1f}分(状态低迷)"

            # AP描述
            ap_desc = f"历史票房排位{hpct:.0f}%"
            if perf >= 70: ap_desc += f"，联赛排名靠前(分位{perf:.0f})"
            elif perf >= 40: ap_desc += f"，联赛中上游(分位{perf:.0f})"
            elif perf >= 20: ap_desc += f"，联赛中下游(分位{perf:.0f})"
            else: ap_desc += f"，联赛下游(分位{perf:.0f})"
            if derby > 0: ap_desc += f"，德比加分{derby:.0f}"

            # Tier原因
            st_val = st_score; ap_val = ap_score
            if st_val >= 80 and ap_val >= 70:
                reason = f"S级：实力顶尖(ST={st_val:.0f})且票房号召力极强(AP={ap_val:.0f})"
            elif hpct >= 90:
                reason = f"A级：历史票房分位{hpct:.0f}%≥90%，德比级票房热度"
            elif st_val >= 55 and ap_val >= 40:
                reason = f"A级：实力较强(ST={st_val:.0f}≥55)且票房吸引力达标(AP={ap_val:.0f}≥40)"
            elif hpct >= 55 and st_val >= 45:
                reason = f"A级：老牌强队(票房分位{hpct:.0f}%≥55%，ST={st_val:.0f}≥45)"
            elif hpct >= 80:
                reason = f"B级：历史票房分位{hpct:.0f}%≥80%，票房热度保护"
            elif ap_val >= 35 and st_val >= 20:
                reason = f"B级：吸引力较高(AP={ap_val:.0f}≥35)，实力尚可(ST={st_val:.0f}≥20)"
            elif st_val < 35:
                reason = f"C级：实力不足(ST={st_val:.0f}<35)"
            elif ap_val < 25:
                reason = f"C级：票房号召力不足(AP={ap_val:.0f}<25)"
            else:
                reason = f"B级：实力中等(ST={st_val:.0f})，票房一般(AP={ap_val:.0f})，未触及A/C边界"
            
            st.caption(f"{st_desc}")
            st.caption(f"{ap_desc}")
            st.caption(f"→ {reason}")
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
