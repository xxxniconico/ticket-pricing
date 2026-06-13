"""Tab: 座位热力图。"""
import streamlit as st
import streamlit.components.v1 as components

from dashboard.common.data_cache import _get_csl_parquet
from dashboard.seating_heatmap import norm_section_id, show_heatmap_in_streamlit

def _get_section_capacities():
    """用 2026 赛季各区最大销量 × 1.05 作为容量基准。

    仅使用 2026 年数据，避免跨年分区变化导致容量虚高
    （2023-2025 工体改造前分区结构与新工体不同）。
    """
    csl = _get_csl_parquet()
    if csl is None:
        return {}
    csl_2026 = csl[csl["match_date"].astype(str).str.startswith("2026")]
    if csl_2026.empty:
        csl_2026 = csl  # fallback
    per_match = csl_2026.groupby(["match_date", "section"])["数量"].sum().reset_index()
    caps = per_match.groupby("section")["数量"].max().to_dict()
    return {norm_section_id(s): int(v * 1.05) + 1 for s, v in caps.items()}


def _compute_match_fill_rates(match_date: str):
    """计算某场每个分区的上座率。返回 {section_number_str: fill_rate}。"""
    csl = _get_csl_parquet()
    if csl is None:
        return {}, {}, 0.0

    md = csl[csl["match_date"].astype(str).str.startswith(match_date)]
    if md.empty:
        return {}, {}, 0.0

    caps = {norm_section_id(k): v for k, v in _get_section_capacities().items()}
    md_copy = md.copy()
    md_copy["section"] = md_copy["section"].map(norm_section_id)
    section_qty = md_copy.groupby("section")["数量"].sum()

    section_fills = {}
    section_rev_contrib = {}
    total_sold = 0; total_cap = 0; total_rev = 0

    # 每区销量+收入
    md_rev = md_copy.groupby("section").agg(
        qty=("数量", "sum"), rev=("实际支付价格", "sum")
    )
    for sec, row in md_rev.iterrows():
        sec_str = norm_section_id(sec)
        cap = caps.get(sec_str, row["qty"])
        section_fills[sec_str] = row["qty"] / max(cap, 1)
        total_sold += row["qty"]
        total_cap += cap
        total_rev += row["rev"]

    total_fill = total_sold / max(total_cap, 1)
    for sec, row in md_rev.iterrows():
        sec_str = norm_section_id(sec)
        section_rev_contrib[sec_str] = row["rev"] / max(total_rev, 1) if total_rev > 0 else 0

    return section_fills, dict(section_qty), total_fill, section_rev_contrib, total_rev


def render_heatmap_tab(guoan_matches):
    """座位热力图 Tab — SVG热力图(销量着色) + 热力带分布。"""

    home_done = [m for m in guoan_matches if m.get("is_home") and m.get("completed")
                 and m["date"].startswith("2026")]
    if not home_done:
        st.info("暂无已赛主场数据")
        return

    c1, c2 = st.columns([3, 1])
    match_options = {f"{m['date']} vs {m['opponent']}": m for m in home_done}
    with c1:
        selected_label = st.selectbox(
            "选择比赛", list(match_options.keys()),
            index=len(match_options) - 1, key="heatmap_match", label_visibility="collapsed"
        )
    selected = match_options[selected_label]
    opp, match_date = selected["opponent"], selected["date"]

    section_fills, section_qty, total_fill, section_rev, total_revenue = _compute_match_fill_rates(match_date)
    total_sold = sum(section_qty.values())
    # 联票修正（四场联票573张/场，未分区，仅在总量体现）
    from src.match_notes import get_adjusted_actual
    match_id_full = f"{match_date} {opp}"
    adj_total = get_adjusted_actual(match_id_full, total_sold)
    bundle_note = f"（含联票+{adj_total - total_sold:.0f}张）" if adj_total > total_sold else ""

    if not section_qty:
        st.warning("该场比赛暂无分区销售数据")
        return

    with c2:
        st.metric("总售出" if not bundle_note else f"总售出{bundle_note}", f"{adj_total:,}张")

    # ── 热力图：components.html iframe（Streamlit 会剥离 markdown 里的 <svg>）──
    match_label = f"{match_date}  vs  {opp}"
    show_heatmap_in_streamlit(st, components, section_fills, match_label, total_fill)

    # ── 销售概况 ──
    if section_qty:
        sorted_items = sorted(
            [(s, q, section_fills.get(s, 0)) for s, q in section_qty.items()],
            key=lambda x: -x[2]
        )
        top5 = sorted_items[:8]
        bot5 = sorted_items[-8:][::-1]

        hot_str = " · ".join(f'{s}({fr*100:.0f}%)' for s, q, fr in top5)
        cold_str = " · ".join(f'{s}({fr*100:.0f}%)' for s, q, fr in bot5)

        high_regions = [s for s, q, fr in sorted_items if fr >= 0.90]
        low_regions = [s for s, q, fr in sorted_items if fr < 0.40]
        mid_regions = [s for s, q, fr in sorted_items if 0.40 <= fr < 0.90]

        suggestion_parts = []
        if high_regions:
            suggestion_parts.append(f"📈 {len(high_regions)}区上座率≥90% → 核心区可考虑上调5-10%")
        if low_regions:
            suggestion_parts.append(f"📉 {len(low_regions)}区上座率<40% → 外围区建议促销拉量")
        if mid_regions:
            suggestion_parts.append(f"📊 {len(mid_regions)}区在40-90% → 维持现价观察")
        suggestion = "<br>".join(suggestion_parts) if suggestion_parts else "✅ 各分区上座均衡"

        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(
                f'<div class="kpi-card" style="border-top:2px solid #ff6b6b !important">'
                f'<div class="kpi-label">🔥 上座率最高区</div>'
                f'<div style="font-size:0.72rem;color:#c0c4c8;line-height:1.6">{hot_str}</div>'
                f'</div>', unsafe_allow_html=True)
        with c2:
            st.markdown(
                f'<div class="kpi-card" style="border-top:2px solid #51cf66 !important">'
                f'<div class="kpi-label">❄️ 上座率最低区</div>'
                f'<div style="font-size:0.72rem;color:#c0c4c8;line-height:1.6">{cold_str}</div>'
                f'</div>', unsafe_allow_html=True)
        with c3:
            st.markdown(
                f'<div class="kpi-card" style="border-top:2px solid #f0c040 !important">'
                f'<div class="kpi-label">💡 定价建议</div>'
                f'<div style="font-size:0.72rem;color:#c0c4c8;line-height:1.6">{suggestion}</div>'
                f'</div>', unsafe_allow_html=True)
