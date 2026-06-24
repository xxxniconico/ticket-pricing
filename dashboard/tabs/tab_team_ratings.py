"""球队动态评级 Tab — 16队 ST/AP/ELO + 国安三年走势"""
import streamlit as st
import pandas as pd
import json
from pathlib import Path
from src.opponent_rating import (
    ALL_CSL_TEAMS_2026, get_opponent_scorecard, get_guoan_scorecard,
    load_elo_history, _load_guoan_home_attendance,
    FROZEN_TIERS, PROMOTED_2026, PROMOTED_2024, DERBY_BONUS,
)


def render_team_ratings(matches, standings, use_dynamic=True):
    st.subheader("📊 球队动态评级")

    date_str = st.date_input("快照日期", pd.Timestamp("2026-06-25")).isoformat()

    elo = load_elo_history()
    guoan_hist = _load_guoan_home_attendance()

    # ── 15 对手 + 国安 ──
    cards = []
    for team in ALL_CSL_TEAMS_2026:
        card = get_opponent_scorecard(team, date_str,
            elo_history=elo, standings_by_round=standings,
            matches=matches, guoan_home_history=guoan_hist)
        cards.append(card)

    guoan_card = get_guoan_scorecard(date_str, elo_history=elo,
                                      standings_by_round=standings, matches=matches)

    # ── 表格 ──
    rows = []
    for c in cards:
        ap_sub = c["components"]["AP_sub"]
        st_sub = c["components"]["ST_sub"]
        tag = ""
        if c["opponent"] in FROZEN_TIERS: tag = "🔒"
        elif c["opponent"] in PROMOTED_2026: tag = "🆕"
        elif c["opponent"] in PROMOTED_2024: tag = "⬆"
        elif c["opponent"] in DERBY_BONUS: tag = "⚔"
        rows.append({
            "": tag,
            "球队": c["opponent"],
            "Tier": c["tier"],
            "ST": c["ST"],
            "AP": c["AP"],
            "ELO": c["elo"],
            "PPG": round(st_sub["PPG"], 2),
            "票房%": round(ap_sub["HIST_ATT_pct"], 0),
            "话题": ap_sub["TOPIC"],
        })

    # 国安行
    rows.append({
        "": "🏠",
        "球队": "北京国安",
        "Tier": guoan_card["tier"],
        "ST": guoan_card["ST"],
        "AP": None,
        "ELO": guoan_card["ELO"],
        "PPG": guoan_card["PPG"],
        "票房%": None,
        "话题": None,
    })

    df = pd.DataFrame(rows)

    def color_tier(val):
        if val == "S": return "background-color: #ff6b6b; color: white"
        if val == "A": return "background-color: #ffa726; color: white"
        if val == "B": return "background-color: #66bb6a; color: white"
        if val == "C": return "background-color: #90a4ae; color: white"
        return ""

    st.dataframe(
        df.style.applymap(color_tier, subset=["Tier"]),
        use_container_width=True, hide_index=True,
    )

    # ── Tier 分布 ──
    dist = {"S": 0, "A": 0, "B": 0, "C": 0}
    for c in cards:
        dist[c["tier"]] = dist.get(c["tier"], 0) + 1

    cols = st.columns(5)
    cols[0].metric("S", dist["S"])
    cols[1].metric("A", dist["A"])
    cols[2].metric("B", dist["B"])
    cols[3].metric("C", dist["C"])
    cols[4].metric("🏠 国安", guoan_card["tier"], f"ST={guoan_card['ST']:.1f}")

    # ── 国安三年走势 ──
    st.divider()
    st.subheader("🏠 北京国安 三年 ST 走势")

    trend = []
    for label, dt in [("2023末", "2023-12-31"), ("2024末", "2024-12-31"),
                       ("2025末", "2025-12-31"), ("2026中", "2026-06-25")]:
        card = get_guoan_scorecard(dt, elo_history=elo,
                                    standings_by_round=standings, matches=matches)
        trend.append({"时间": label, "ST": card["ST"], "ELO": card["ELO"],
                       "Tier": card["tier"], "PPG": card["PPG"]})

    trend_df = pd.DataFrame(trend)
    col1, col2 = st.columns(2)
    with col1:
        st.line_chart(trend_df.set_index("时间")[["ST", "ELO"]])
    with col2:
        st.dataframe(trend_df, hide_index=True, use_container_width=True)

    st.caption("国安状态乘数: 监控模式（暂不影响预测）")

    # ── ST vs AP 散点 ──
    st.divider()
    st.subheader("ST vs AP 双维度分布")
    plot_df = pd.DataFrame([{
        "球队": c["opponent"], "ST": c["ST"], "AP": c["AP"], "Tier": c["tier"]
    } for c in cards])

    try:
        import plotly.express as px
        fig = px.scatter(plot_df, x="ST", y="AP", text="球队", color="Tier",
                         title="15队 ST vs AP",
                         color_discrete_map={"S": "red", "A": "orange", "B": "green", "C": "gray"})
        fig.update_traces(textposition="top center")
        fig.add_hline(y=22, line_dash="dash", line_color="gray")
        fig.add_vline(x=35, line_dash="dash", line_color="gray")
        fig.add_hline(y=40, line_dash="dash", line_color="orange")
        fig.add_vline(x=55, line_dash="dash", line_color="orange")
        st.plotly_chart(fig, use_container_width=True)
    except ImportError:
        st.scatter_chart(plot_df.set_index("ST")[["AP"]])

    # ── 档位变更日志 ──
    st.divider()
    st.subheader("📋 档位变更日志")
    log_path = Path(__file__).resolve().parent.parent.parent / "data/processed/tier_changes.json"
    if log_path.exists():
        with open(log_path) as f:
            changes = json.load(f)
        if changes:
            log_df = pd.DataFrame(changes[-10:])
            st.dataframe(log_df[["date", "team", "from", "to", "reason"]],
                         hide_index=True, use_container_width=True)
        else:
            st.caption("暂无变更记录")
    else:
        st.caption("运行 scripts/log_tier_changes.py 生成变更日志")
