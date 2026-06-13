"""Tab: 对手分析。"""
import pandas as pd
import streamlit as st

from dashboard.common.brand import team_crest_html
from dashboard.common.constants import DEDUCTIONS, TIER_COLORS
from src.classify import classify_opponent_tier
from src.rule_engine import TIER_BASE, get_effective_calibration
from src.csl_context import get_guoan_matches

def render_opponent_analysis(all_matches):
    # Use all_matches passed from main()
    guoan_all = get_guoan_matches(all_matches)
    tier_opps = {"S": [], "A": [], "B": [], "C": []}
    for opp in sorted(set(m['opponent'] for m in guoan_all)):
        tier_opps[classify_opponent_tier(opp)].append(opp)

    # KPI 摘要行
    kpi_cols = st.columns(4)
    for i, t in enumerate(["S", "A", "B", "C"]):
        clr = TIER_COLORS.get(t, "#8a8f98")
        n = len(tier_opps.get(t, []))
        with kpi_cols[i]:
            st.markdown(f"""<div class="kpi-card" style="border-top:2px solid {clr}">
              <div class="kpi-label">{t}级对手</div>
              <div class="kpi-value" style="color:{clr}">{n} 队</div>
            </div>""", unsafe_allow_html=True)
    
    st.markdown("**对手分级与基值矩阵**")
    tiers_order = ["S", "A", "B", "C"]
    trows = ""
    for t in tiers_order:
        base = TIER_BASE.get(t, 0)
        enable_ema = st.session_state.get("enable_ema_calibration", False)
        cf = get_effective_calibration(t, enable_ema=enable_ema)
        cal_color = "#ff6b6b" if cf > 1.01 else "#51cf66" if cf < 0.99 else "#8a8f98"
        opps_str = " · ".join(tier_opps.get(t, []))
        trows += (
            f'<tr>'
            f'<td style="font-weight:510;color:#f7f8f8">{t}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">{base:,.0f}</td>'
            f'<td style="color:{cal_color};font-family:JetBrains Mono,ui-monospace">{cf:.4f}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace;color:#f7f8f8">{base*cf:,.0f}</td>'
            f'<td style="text-align:left;font-size:0.7rem;color:#8a8f98">{opps_str}</td>'
            f'</tr>'
        )
    st.markdown(f"""<table class="compact-table" style="max-width:700px">
      <thead><tr><th>级别</th><th>基值(张)</th><th>校准因子</th><th>校准后</th><th style="text-align:left">对手</th></tr></thead>
      <tbody>{trows}</tbody>
    </table>""", unsafe_allow_html=True)
    st.caption("基值来自 KMeans 聚类均值 · EMA 校准默认关闭（实验开关在页顶）· 开启后需 ≥8 场/级")
    
    # ── 对手表现数据 ──
    st.divider()
    st.markdown("**对手表现数据**")
    
    from collections import defaultdict as _dd
    ts = _dd(lambda: {"p":0,"w":0,"d":0,"l":0,"gf":0,"ga":0,"pts":0,"form":[]})
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
        tier = classify_opponent_tier(team)
        tier_clr = {"S":"#ff6b6b","A":"#f0c040","B":"#8a8f98","C":"#51cf66"}.get(tier,"#8a8f98")
        # Build form pills
        form_pills = ""
        for ch in form5:
            fc = "#ff6b6b" if ch == 'W' else "#f0c040" if ch == 'D' else "#51cf66"
            form_pills += f'<span style="display:inline-block;width:18px;height:18px;line-height:18px;text-align:center;border-radius:3px;background:{fc}22;color:{fc};font-size:0.6rem;font-weight:590;margin:0 1px">{ch}</span>'
        orows += (
            f'<tr>'
            f'<td style="font-weight:510;color:{tier_clr};text-align:left;padding-left:8px">{team_crest_html(team, "sm")} {team}</td>'
            f'<td style="color:#8a8f98">{tier}</td>'
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
    st.caption("官方积分含 CFA 年初扣分处罚 · S红 A黄 C绿 · 近5场 W红 D黄 L绿")
