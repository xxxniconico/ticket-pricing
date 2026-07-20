"""Tab: 对手分析（含动态评级 + 积分榜 + 基值矩阵）"""
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard.common.brand import team_crest_html
from dashboard.common.constants import DEDUCTIONS, TIER_COLORS
from src.classify import classify_opponent_tier
from src.rule_engine import TIER_BASE
from src.csl_context import get_guoan_matches
from src.opponent_rating import (
    ALL_CSL_TEAMS_2026, get_opponent_scorecard, get_guoan_scorecard,
    load_elo_history, _load_guoan_home_attendance,
    FROZEN_TIERS, PROMOTED_2026, PROMOTED_2024, DERBY_BONUS,
)

ROOT = Path(__file__).resolve().parent.parent.parent


def render_opponent_analysis(all_matches):
    guoan_all = get_guoan_matches(all_matches)
    date_str = pd.Timestamp("today").isoformat()[:10]

    # ── 动态分级数据 ──
    elo = load_elo_history()
    guoan_hist = _load_guoan_home_attendance()

    cards = []
    for team in ALL_CSL_TEAMS_2026:
        card = get_opponent_scorecard(team, date_str,
            elo_history=elo,
            matches=all_matches, guoan_home_history=guoan_hist)
        cards.append(card)

    # ── 动态 Tier 分布 ──
    dist = {"S": 0, "A": 0, "B": 0, "C": 0}
    dyn_tier_opps = {"S": [], "A": [], "B": [], "C": []}
    for c in cards:
        t = c["tier"]
        dist[t] = dist.get(t, 0) + 1
        dyn_tier_opps[t].append(c["opponent"])

    kpi_cols = st.columns(4)
    for i, t in enumerate(["S", "A", "B", "C"]):
        clr = TIER_COLORS.get(t, "#8a8f98")
        n = dist[t]
        with kpi_cols[i]:
            st.markdown(f"""<div class="kpi-card" style="border-top:2px solid {clr}">
              <div class="kpi-label">{t}级对手</div>
              <div class="kpi-value" style="color:{clr}">{n} 队</div>
            </div>""", unsafe_allow_html=True)

    # ── 对手分级与基值矩阵（动态分级） ──
    st.markdown("**对手分级与基值矩阵**")
    trows = ""
    for t in ["S", "A", "B", "C"]:
        base = TIER_BASE.get(t, 0)
        t_cards = [c for c in cards if c["tier"] == t]
        avg_st = sum(c["ST"] for c in t_cards) / len(t_cards) if t_cards else 0
        avg_ap = sum(c["AP"] for c in t_cards) / len(t_cards) if t_cards else 0
        st_color = "#ff6b6b" if avg_st >= 55 else "#f0c040" if avg_st >= 35 else "#8a8f98"
        ap_color = "#ff6b6b" if avg_ap >= 40 else "#f0c040" if avg_ap >= 25 else "#8a8f98"
        opps_str = " · ".join(dyn_tier_opps.get(t, []))
        trows += (
            f'<tr>'
            f'<td style="font-weight:510;color:{TIER_COLORS.get(t,"#f7f8f8")}">{t}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">{base:,.0f}</td>'
            f'<td style="color:{st_color};font-family:JetBrains Mono,ui-monospace">ST {avg_st:.0f}</td>'
            f'<td style="color:{ap_color};font-family:JetBrains Mono,ui-monospace">AP {avg_ap:.0f}</td>'
            f'<td style="text-align:left;font-size:0.7rem;color:#8a8f98">{opps_str}</td>'
            f'</tr>'
        )
    st.markdown(f"""<table class="compact-table" style="max-width:750px">
      <thead><tr><th>级别</th><th>基值(张)</th><th>ST均</th><th>AP均</th><th style="text-align:left">对手（动态分级）</th></tr></thead>
      <tbody>{trows}</tbody>
    </table>""", unsafe_allow_html=True)
    st.caption(f"快照 {date_str} · 基值来自 KMeans 聚类均值 · 对手按动态 ST/AP 引擎实时分级")

    # ── 动态评级明细表 ──
    st.divider()
    st.markdown("**动态评级明细**")
    rows = []
    for c in sorted(cards, key=lambda x: (-x["ST"], -x["AP"])):
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
        })

    df = pd.DataFrame(rows)
    def color_tier(val):
        return {
            "S": "background-color: #ff6b6b; color: white",
            "A": "background-color: #ffa726; color: white",
            "B": "background-color: #66bb6a; color: white",
            "C": "background-color: #90a4ae; color: white",
        }.get(val, "")

    st.dataframe(
        df.style.map(color_tier, subset=["Tier"]),
        use_container_width=True, hide_index=True,
        column_config={
            "ST": st.column_config.NumberColumn(format="%.0f"),
            "AP": st.column_config.NumberColumn(format="%.0f"),
            "ELO": st.column_config.NumberColumn(format="%.0f"),
        },
    )

    # ── ST vs AP 散点 ──
    col_a, col_b = st.columns([2, 1])
    with col_a:
        st.caption("**ST vs AP 双维度**")
        plot_df = pd.DataFrame([{
            "球队": c["opponent"], "ST": c["ST"], "AP": c["AP"], "Tier": c["tier"]
        } for c in cards])
        try:
            import plotly.express as px
            fig = px.scatter(plot_df, x="ST", y="AP", text="球队", color="Tier",
                             color_discrete_map={"S": "red", "A": "orange", "B": "green", "C": "gray"})
            fig.update_traces(textposition="top center")
            fig.add_hline(y=25, line_dash="dash", line_color="gray", annotation_text="C线")
            fig.add_hline(y=40, line_dash="dash", line_color="orange", annotation_text="A线")
            fig.add_vline(x=35, line_dash="dash", line_color="gray")
            fig.add_vline(x=55, line_dash="dash", line_color="orange")
            fig.update_layout(height=350, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        except ImportError:
            st.scatter_chart(plot_df.set_index("ST")[["AP"]])

    with col_b:
        st.caption("**Tier 分布**")
        for t in ["S", "A", "B", "C"]:
            clr = TIER_COLORS.get(t, "#8a8f98")
            st.markdown(f'<span style="color:{clr};font-weight:590">{t}</span>: {dist[t]} 队', unsafe_allow_html=True)

    # ── 对手表现数据（积分榜） ──
    st.divider()
    st.markdown("**对手表现数据（积分榜）**")

    ts = defaultdict(lambda: {"p":0,"w":0,"d":0,"l":0,"gf":0,"ga":0,"pts":0,"form":[]})
    for m in sorted([x for x in all_matches if x['date'].startswith('2026')], key=lambda x: x['date']):
        if not m.get('completed'): continue
        h, a = m['home'], m['away']
        ts[h]['p']+=1; ts[a]['p']+=1
        ts[h]['gf']+=m['hg']; ts[h]['ga']+=m['ag']
        ts[a]['gf']+=m['ag']; ts[a]['ga']+=m['hg']
        if m['hg']>m['ag']:
            ts[h]['w']+=1; ts[h]['pts']+=3; ts[a]['l']+=1
            ts[h]['form'].append('W'); ts[a]['form'].append('L')
        elif m['hg']==m['ag']:
            ts[h]['d']+=1; ts[a]['d']+=1; ts[h]['pts']+=1; ts[a]['pts']+=1
            ts[h]['form'].append('D'); ts[a]['form'].append('D')
        else:
            ts[a]['w']+=1; ts[a]['pts']+=3; ts[h]['l']+=1
            ts[a]['form'].append('W'); ts[h]['form'].append('L')

    opp_list = sorted(set(m['opponent'] for m in guoan_all))
    orows = ""
    for team in opp_list:
        s = ts.get(team)
        if not s: continue
        d = DEDUCTIONS.get(team, 0)
        eff = s['pts'] - d
        gd = s['gf'] - s['ga']
        form5 = ''.join(s['form'][-5:])
        gd_clr = "#ff6b6b" if gd > 0 else "#51cf66" if gd < 0 else "#8a8f98"
        tier = classify_opponent_tier(team, match_date=date_str)
        tier_clr = TIER_COLORS.get(tier, "#8a8f98")
        form_pills = ""
        for ch in form5:
            fc = "#ff6b6b" if ch == 'W' else "#f0c040" if ch == 'D' else "#51cf66"
            form_pills += f'<span style="display:inline-block;width:18px;height:18px;line-height:18px;text-align:center;border-radius:3px;background:{fc}22;color:{fc};font-size:0.6rem;font-weight:590;margin:0 1px">{ch}</span>'
        orows += (
            f'<tr>'
            f'<td style="font-weight:510;color:{tier_clr};text-align:left;padding-left:8px">{team_crest_html(team, "sm")} {team}</td>'
            f'<td style="color:{tier_clr}">{tier}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">{s["p"]}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">{s["w"]}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">{s["d"]}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">{s["l"]}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">{s["gf"]}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">{s["ga"]}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace;color:{gd_clr}">{gd:+d}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">{s["pts"]}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace;color:#62666d">{d if d>0 else ""}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace;font-weight:590;color:#f7f8f8">{eff}</td>'
            f'<td style="padding:2px 4px">{form_pills}</td>'
            f'</tr>'
        )
    st.markdown(f"""<div class="table-scroll"><table class="compact-table">
      <thead><tr>
        <th style="text-align:left;padding-left:8px">球队</th><th>级</th><th>赛</th><th>胜</th><th>平</th><th>负</th>
        <th>进</th><th>失</th><th>净</th><th>分</th><th>扣</th><th>有效</th><th>近5场</th>
      </tr></thead>
      <tbody>{orows}</tbody>
    </table></div>""", unsafe_allow_html=True)
    st.caption("官方积分含 CFA 年初扣分处罚 · 近5场 W红 D黄 L绿 · 分级为动态引擎实时判定")

    # ── 分级快照（按 ST 降序） ──
    st.divider()
    st.caption("**分级快照（动态引擎实时输出）**")
    snap = sorted(cards, key=lambda c: -c["ST"])
    snap_rows = ""
    for c in snap:
        t = c["tier"]
        clr = TIER_COLORS.get(t, "#8a8f98")
        snap_rows += (
            "<tr>"
            f"<td style='color:{clr};font-weight:510'>{t}</td>"
            f"<td style='text-align:left'>{c['opponent']}</td>"
            f"<td style='font-family:JetBrains Mono'>{c['ST']:.0f}</td>"
            f"<td style='font-family:JetBrains Mono'>{c['AP']:.0f}</td>"
            f"<td style='font-family:JetBrains Mono'>{c['elo']:.0f}</td>"
            "</tr>"
        )
    st.markdown(f"""<table class="compact-table" style="max-width:550px">
      <thead><tr><th>Tier</th><th style="text-align:left">球队</th><th>ST</th><th>AP</th><th>ELO</th></tr></thead>
      <tbody>{snap_rows}</tbody>
    </table>""", unsafe_allow_html=True)
