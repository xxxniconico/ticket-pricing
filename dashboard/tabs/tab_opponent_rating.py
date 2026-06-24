"""对手评分卡 Tab — Phase 3.4"""
import streamlit as st
import pandas as pd
from src.opponent_rating import (
    ALL_CSL_TEAMS_2026, get_opponent_scorecard,
    load_elo_history, _load_guoan_home_attendance,
    FROZEN_TIERS, PROMOTED_2026, PROMOTED_2024,
)
from src.csl_context import load_csl_data

def render_opponent_rating(matches, standings):
    st.subheader("📊 对手动态评分卡")
    
    date_str = st.date_input("快照日期", pd.Timestamp("2026-06-25")).isoformat()
    
    elo = load_elo_history()
    guoan = _load_guoan_home_attendance()
    
    cards = []
    for team in ALL_CSL_TEAMS_2026:
        card = get_opponent_scorecard(team, date_str,
            elo_history=elo, standings_by_round=standings,
            matches=matches, guoan_home_history=guoan)
        cards.append(card)
    
    # Build DataFrame
    rows = []
    for c in cards:
        ap = c["components"]["AP_sub"]
        st_sub = c["components"]["ST_sub"]
        tag = ""
        if c["opponent"] in FROZEN_TIERS: tag = "🔒"
        elif c["opponent"] in PROMOTED_2026: tag = "🆕"
        elif c["opponent"] in PROMOTED_2024: tag = "⬆"
        rows.append({
            "对手": f"{tag} {c['opponent']}",
            "ELO": c["elo"],
            "ST": c["ST"],
            "AP": c["AP"],
            "Tier": c["tier"],
            "PPG": round(st_sub["PPG"], 2),
            "票房%": round(ap["HIST_ATT_pct"], 0),
            "德比": ap["DERBY_bonus"],
            "话题": ap["TOPIC"],
        })
    
    df = pd.DataFrame(rows)
    
    # Color by tier
    def color_tier(val):
        if val == "S": return "background-color: #ff6b6b; color: white"
        if val == "A": return "background-color: #ffa726; color: white"
        if val == "B": return "background-color: #66bb6a; color: white"
        return "background-color: #90a4ae; color: white"
    
    st.dataframe(
        df.style.applymap(color_tier, subset=["Tier"]),
        use_container_width=True,
        hide_index=True,
    )
    
    # Tier distribution
    dist = df["Tier"].value_counts().to_dict()
    cols = st.columns(4)
    for i, t in enumerate(["S", "A", "B", "C"]):
        cols[i].metric(t, dist.get(t, 0))
    
    # ST/AP scatter
    import plotly.express as px
    fig = px.scatter(
        df, x="ST", y="AP", text="对手", color="Tier",
        title="ST vs AP 双维度分布",
        color_discrete_map={"S": "red", "A": "orange", "B": "green", "C": "gray"}
    )
    fig.update_traces(textposition="top center")
    st.plotly_chart(fig, use_container_width=True)
