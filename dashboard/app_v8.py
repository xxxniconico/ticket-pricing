"""
国安票务动态定价看板 V8 — 决策工作台（模块化入口）
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dashboard.common import setup  # noqa: F401 — 副作用：page_config + 字体
from dashboard.common.brand import csl_logo_b64, guoan_crest_b64
from dashboard.common.constants import DEDUCTIONS
from dashboard.common.data_cache import (
    SCHEDULE_ENGINE_VERSION,
    build_standings_2026,
    compute_home_predictions,
    load_css,
    load_data,
    resolve_next_matches,
    set_ctx_rounds,
    _round_num,
)
from dashboard.components.ctx_builder import build_pred_args
from dashboard.common.data_cache import get_optimizer, _get_zone_actual_revenue, _get_zone_face_revenue
from dashboard.tabs.tab_next_match import render_tab1
from dashboard.tabs.tab_history import render_history_expanders, render_mae_chart
from dashboard.tabs.tab_opponent import render_opponent_analysis
from dashboard.tabs.tab_standings import render_standings_table
from dashboard.tabs.tab_h2_strategy import render_h2_strategy
from dashboard.tabs.tab_heatmap import render_heatmap_tab
from dashboard.tabs.tab_validation import render_validation_tab
from dashboard.tabs.tab_odds import render_odds_tab

from dashboard.tabs.tab_data_base import render_data_base
import numpy as np
import streamlit as st
from src.pricing_v5 import ZONE_TIERS


def main():
    load_css()

    with st.spinner("加载 CSL 数据..."):
        all_matches, rounds, guoan_matches = load_data()
    if not guoan_matches:
        if not all_matches:
            st.error("无法加载 CSL 数据：数据文件缺失或网络不可用")
        else:
            st.error("国安赛程为空：2026 赛季尚未开赛或数据源未更新")
        st.error("请刷新重试")
        if st.button("🔄 刷新重试"):
            st.cache_data.clear()
            st.rerun()
        st.stop()

    set_ctx_rounds(rounds)
    standings = build_standings_2026(all_matches)

    home_matches = [m for m in guoan_matches if m.get("is_home")]
    home_done = [m for m in home_matches if m.get("completed") and m["date"].startswith("2026")]
    completed = [m for m in guoan_matches if m.get("completed") and m["date"].startswith("2026")]

    total_pts = sum(
        3 if (m["is_home"] and m["hg"] > m["ag"]) or (not m["is_home"] and m["ag"] > m["hg"])
        else 1 if m["hg"] == m["ag"] else 0
        for m in completed
    )
    guoan_ded = DEDUCTIONS.get("北京国安", 0)
    latest_rnd = max(standings.keys(), key=_round_num, default=None)
    guoan_rank = standings.get(latest_rnd, {}).get("北京国安", "?") if latest_rnd else "?"
    home_w = sum(1 for m in home_done if m["hg"] > m["ag"])
    home_d = sum(1 for m in home_done if m["hg"] == m["ag"])
    home_l = sum(1 for m in home_done if m["hg"] < m["ag"])

    crest = guoan_crest_b64()
    csl = csl_logo_b64()
    crest_img = f'<img class="crest" src="{crest}" alt="国安">' if crest else ""
    csl_img = f'<img class="csl-logo" src="{csl}" alt="CSL">' if csl else ""
    st.markdown(f"""<div class="brand-header">
      <div style="display:flex;align-items:center;gap:10px">
        {crest_img}
        <h1>北京国安 · 动态定价</h1>
        {csl_img}
      </div>
      <div class="state-bar" style="margin-left:auto">
        <strong>#{guoan_rank}</strong> {total_pts}分
        <span style="color:#62666d">(扣{guoan_ded}分)</span>
        | 主场 {home_w}-{home_d}-{home_l}
        | 已赛{len(completed)}/30轮
      </div>
    </div>""", unsafe_allow_html=True)

    recent5 = completed[-5:]
    form_icons = []
    for m in recent5:
        res = "W" if (m["is_home"] and m["hg"] > m["ag"]) or (not m["is_home"] and m["ag"] > m["hg"]) else "D" if m["hg"] == m["ag"] else "L"
        form_icons.append(f'<span class="result-{res}">{res}</span>')
    if form_icons:
        st.caption("近5场: " + " · ".join(form_icons), unsafe_allow_html=True)

    home_preds = compute_home_predictions(home_done, guoan_matches)
    next_match, next_home, target_match = resolve_next_matches(guoan_matches)

    if st.sidebar.button("🔄 刷新数据", help="清除缓存并重新拉取赛程"):
        st.cache_data.clear()
        st.rerun()

    preds_arr = np.array([p for _, p, _, _ in home_preds])
    actuals_arr = np.array([a for _, _, a, _ in home_preds])
    mae = np.mean(np.abs(preds_arr - actuals_arr)) if len(preds_arr) > 0 else 0
    pct = len(home_preds) / 15 * 100
    st.markdown(f"""<div class="progress-line">
      <div class="progress-label"><span>赛季主场进度</span><span>{len(home_preds)}/15</span></div>
      <div class="progress-track"><div class="progress-fill" style="width:{pct}%"></div></div>
    </div>""", unsafe_allow_html=True)

    use_dynamic = True  # dynamic tier always on
    tab_names = ["🎯 下一场预测", "📋 历史定价", "🔍 对手分析", "🏆 积分榜", "📊 H2策略", "🔥 座位热力图", "📐 模型验证", "🎲 赔率信号", "🗄️ 数据基座"]
    active_tab = st.radio("导航", tab_names, horizontal=True, label_visibility="collapsed", key="main_tab")

    if active_tab == tab_names[0]:
        if next_match and not next_match["is_home"]:
            st.info(f"📅 下一场 {next_match['date']} @ {next_match['opponent']} 为客场")
            if next_home:
                st.caption(f"最近主场：{next_home['date']} vs {next_home['opponent']}")
        if target_match:
            render_tab1(target_match, home_preds, guoan_matches, standings, mae, use_dynamic)
        else:
            st.info("无未来主场")
        st.caption("💡 详细场景切换 + 瀑布图 → **H2策略** TAB")

    if active_tab == tab_names[1]:
        opt_kpi = get_optimizer()
        cum_scene_qty = cum_delta_qty = cum_scene_rev = cum_delta_rev = 0
        for m, pred, actual, ctx in home_preds:
            pred_args = build_pred_args(m, ctx)
            r_h = opt_kpi.optimize(m["opponent"], **pred_args)
            zone_rev = _get_zone_face_revenue(m)  # 票面收入
            total_actual_rev = sum(zone_rev.values())
            cum_scene_qty += r_h.total_attendance
            cum_delta_qty += r_h.total_attendance - actual
            cum_scene_rev += r_h.total_revenue
            cum_delta_rev += r_h.total_revenue - total_actual_rev
        kc1, kc2, kc3, kc4 = st.columns(4)
        with kc1:
            st.markdown(f'''<div class="kpi-card"><div class="kpi-label">累计场景量</div><div class="kpi-value">{cum_scene_qty:,.0f}张</div></div>''', unsafe_allow_html=True)
        with kc2:
            qty_color = "#ff6b6b" if cum_delta_qty > 0 else "#51cf66"
            st.markdown(f'''<div class="kpi-card"><div class="kpi-label">累计Δ量</div><div class="kpi-value" style="color:{qty_color}">{cum_delta_qty:+,.0f}张</div></div>''', unsafe_allow_html=True)
        with kc3:
            st.markdown(f'''<div class="kpi-card"><div class="kpi-label">累计场景收入</div><div class="kpi-value">¥{cum_scene_rev/1e4:.1f}万</div></div>''', unsafe_allow_html=True)
        with kc4:
            rev_color = "#ff6b6b" if cum_delta_rev > 0 else "#51cf66"
            st.markdown(f'''<div class="kpi-card"><div class="kpi-label">累计Δ收入</div><div class="kpi-value" style="color:{rev_color}">¥{cum_delta_rev/1e4:+.1f}万</div></div>''', unsafe_allow_html=True)
        render_mae_chart(home_preds)
        render_history_expanders(home_preds, guoan_matches)

    if active_tab == tab_names[2]:
        render_opponent_analysis(all_matches)
    if active_tab == tab_names[3]:
        render_standings_table(guoan_matches, standings, guoan_ded)
    if active_tab == tab_names[4]:
        render_h2_strategy(guoan_matches, standings, mae=mae)
    if active_tab == tab_names[5]:
        render_heatmap_tab(guoan_matches)
    if active_tab == tab_names[6]:
        render_validation_tab(home_preds, guoan_matches, all_matches)
    if active_tab == tab_names[7]:
        render_odds_tab()
    if active_tab == tab_names[8]:
        render_data_base()

    st.caption(f"V8.1 · 国安绿品牌 · 决策工作台 · 赛程引擎 {SCHEDULE_ENGINE_VERSION}")


if __name__ == "__main__":
    main()
