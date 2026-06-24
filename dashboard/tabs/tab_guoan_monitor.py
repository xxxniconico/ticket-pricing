"""国安监控 Tab — 三年 ST 走势 + ELO/PPG 仪表盘"""
import streamlit as st
import pandas as pd
from src.opponent_rating import get_guoan_scorecard, load_elo_history
from src.csl_context import load_csl_data


def render_guoan_monitor(matches, standings):
    st.subheader("📈 北京国安 动态监控")

    elo = load_elo_history()

    # 当前快照
    card = get_guoan_scorecard("2026-06-25", elo_history=elo,
                                standings_by_round=standings, matches=matches)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("ST 实力分", f"{card['ST']:.1f}", help="0-100, ELO+PPG+L5+GD综合")
    col2.metric("ELO", f"{card['ELO']:.0f}", help="多赛季累积评分")
    col3.metric("PPG", f"{card['PPG']:.2f}", help="当季场均得分")
    col4.metric("Tier", card["tier"], help="ST>=55→A, >=35→B, else C")

    st.divider()

    # 三年走势
    trend = []
    for label, dt in [("2023末", "2023-12-31"), ("2024末", "2024-12-31"),
                       ("2025末", "2025-12-31"), ("2026中", "2026-06-25")]:
        c = get_guoan_scorecard(dt, elo_history=elo,
                                 standings_by_round=standings, matches=matches)
        trend.append({"时间": label, "ST": c["ST"], "ELO": c["ELO"],
                       "PPG": c["PPG"], "Tier": c["tier"]})

    df = pd.DataFrame(trend)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("ST / ELO 走势")
        st.line_chart(df.set_index("时间")[["ST", "ELO"]])
    with col2:
        st.subheader("数据明细")
        st.dataframe(df, hide_index=True, use_container_width=True)

    st.caption("国安状态乘数: 监控模式（暂不影响预测）。争冠 +8%、保级 -8% 待启用。")
