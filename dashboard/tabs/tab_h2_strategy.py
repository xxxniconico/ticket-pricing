"""Tab: H2 策略。"""
import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from dashboard.common.brand import team_crest_html
from dashboard.common.constants import DEDUCTIONS
from dashboard.common.data_cache import _get_zone_actual_revenue, get_ctx_rounds, get_optimizer
from dashboard.components.ctx_builder import build_pred_args
from dashboard.components.prediction_detail import render_prediction_detail
from dashboard.components.pricing_ui import render_strategy_card
from dashboard.components.waterfall import compute_h1_waterfall, compute_h2_waterfall, compute_waterfall_decomposition, draw_waterfall
from src.classify import DERBY_RIVALS, classify_opponent_tier
from src.csl_context import detect_ctx, get_next_guoan_match
from src.pricing_v5 import build_price_matrix, get_pricing_tier
from src.rule_engine import predict_calibrated as rule_predict

ROOT = Path(__file__).resolve().parent.parent.parent

def _resolve_match(h2_entry, guoan_matches):
    """将 H2 JSON 场次映射到 guoan_matches 中的完整 match dict。"""
    for m in guoan_matches:
        if m["date"] == h2_entry["date"] and m["opponent"] == h2_entry["opponent"]:
            return m
    return {
        "date": h2_entry["date"],
        "opponent": h2_entry["opponent"],
        "is_home": True,
        "completed": False,
        "round": h2_entry.get("round", ""),
    }


def _h2_actual_revenue(match_date, opponent, guoan_matches):
    """已赛 H2 场次的实际收入（parquet 分区汇总）。"""
    for m in guoan_matches:
        if not m.get("completed") or not m.get("is_home"):
            continue
        if m["date"] == match_date and m["opponent"] == opponent:
            zone_rev = _get_zone_actual_revenue(m)
            return sum(zone_rev.values()) if zone_rev else None
    return None


def render_h2_strategy(guoan_matches, standings, mae=0):
    """策略驾驶舱：H2目标 × V5.3实时预测联动"""
    h2_path = ROOT / "data/targets/h2_2026_match_targets.json"
    if not h2_path.exists():
        st.error("H2策略数据文件不存在")
        return
    with open(h2_path) as f:
        h2 = json.load(f)

    completed = h2["completed"]
    summary = h2["summary"]
    matches = h2["matches"]
    model_ver = h2.get("model_version", "V5.3")
    STRATEGY_LABEL = {"revenue_priority": "收入优先", "revenue_tilt": "收入偏重", "balanced": "均衡"}
    STRATEGY_COLOR = {"revenue_priority": "#ff6b6b", "revenue_tilt": "#f0c040", "balanced": "#c2ef4e"}

    # ── Find next home for live prediction ──
    next_home = get_next_guoan_match(guoan_matches, home_only=True)
    optimizer = get_optimizer()
    pm = build_price_matrix()
    live_pred = None; live_gap = 0; live_opt = None; next_target = None

    if next_home:
        mock = {**next_home, "completed": True}
        ctx = detect_ctx(mock, guoan_matches + [mock], get_ctx_rounds())
        dt_ts = pd.Timestamp(next_home["date"]); opp = next_home["opponent"]
        pred_args = build_pred_args(next_home, ctx, {'season_opener': False, 'match_year': '2026'})
        live_pred = rule_predict(opp, **pred_args)
        live_opt = optimizer.optimize(opp, **pred_args)
        next_target = next((m for m in matches if m["date"] == next_home["date"]), None)
        if next_target:
            live_gap = live_opt.total_revenue - next_target["target_revenue"]

    # ══ KPI Row ══
    c1, c2, c3, c4 = st.columns(4)
    REV_2025_CSL = 42_035_000  # 2025 CSL散票全年（15场，剔除足协杯+亚冠）

    with c1:
        vs_pct = (summary["annual_projection_revenue"] - REV_2025_CSL) / REV_2025_CSL * 100
        vs_color = "#51cf66" if vs_pct >= 0 else "#ff6b6b"
        st.markdown(f"""<div class="kpi-card">
          <div class="kpi-label">全年预估</div>
          <div class="kpi-value">¥{summary['annual_projection_revenue']/1e4:,.0f}万</div>
          <div class="kpi-sub">vs 2025: <span style="color:{vs_color}">{vs_pct:+.1f}%</span></div>
        </div>""", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""<div class="kpi-card">
          <div class="kpi-label">剩余目标 · {len(matches)}场</div>
          <div class="kpi-value">¥{summary['total_target_revenue']/1e4:,.0f}万</div>
          <div class="kpi-sub">{summary['total_target_quantity']:,}张</div>
        </div>""", unsafe_allow_html=True)
    with c3:
        gap_2025 = summary["annual_projection_revenue"] - REV_2025_CSL
        gap_color = "#51cf66" if gap_2025 >= 0 else "#ff6b6b"
        st.markdown(f"""<div class="kpi-card">
          <div class="kpi-label">收入缺口 vs 2025</div>
          <div class="kpi-value"><span style="color:{gap_color}">¥{gap_2025/1e4:+.0f}万</span></div>
          <div class="kpi-sub">¥{completed['revenue']/1e4:.0f}万已完成</div>
        </div>""", unsafe_allow_html=True)
    with c4:
        mae_label = f"MAE={mae:,.0f}" if mae > 0 else "MAE=—"
        st.markdown(f"""<div class="kpi-card">
          <div class="kpi-label">模型版本</div>
          <div class="kpi-value">{model_ver}</div>
          <div class="kpi-sub">{mae_label}</div>
        </div>""", unsafe_allow_html=True)

    # ══ Next Match Watch ══
    if next_home and live_opt:
        st.divider()
        st.markdown("**下一场盯盘**")
        tier = classify_opponent_tier(next_home["opponent"])
        pt = get_pricing_tier(next_home["opponent"])
        prices = pm[pt]
        ctx_str = "+".join([k for k, v in ctx.items() if v]) or "无触发"
        gap_str = f'<span style="color:{"#51cf66" if live_gap >= 0 else "#ff6b6b"}">¥{live_gap/1e4:+.1f}万</span>' if next_target else "—"

        nc1, nc2, nc3, nc4 = st.columns(4)
        with nc1:
            st.markdown(f"""<div style="padding:8px 12px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:6px">
              <div style="font-size:0.62rem;color:#62666d">V5.3预测</div>
              <div style="font-size:1.1rem;color:#f7f8f8;font-weight:510">{live_pred:,.0f}张</div>
              <div style="font-size:0.62rem;color:#8a8f98">{tier}级 · {ctx_str}</div></div>""", unsafe_allow_html=True)
        with nc2:
            st.markdown(f"""<div style="padding:8px 12px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:6px">
              <div style="font-size:0.62rem;color:#62666d">优化收入</div>
              <div style="font-size:1.1rem;color:#f7f8f8;font-weight:510">¥{live_opt.total_revenue/1e4:.1f}万</div>
              <div style="font-size:0.62rem;color:#8a8f98">rw={live_opt.revenue_weight:.0%}</div></div>""", unsafe_allow_html=True)
        with nc3:
            if next_target:
                st.markdown(f"""<div style="padding:8px 12px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:6px">
                  <div style="font-size:0.62rem;color:#62666d">H2目标</div>
                  <div style="font-size:1.1rem;color:#f7f8f8;font-weight:510">¥{next_target['target_revenue']/1e4:.1f}万</div>
                  <div style="font-size:0.62rem;color:#8a8f98">偏差 {gap_str}</div></div>""", unsafe_allow_html=True)
            else:
                st.caption("无匹配目标")
        with nc4:
            st.markdown(f"""<div style="padding:8px 12px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:6px">
              <div style="font-size:0.62rem;color:#62666d">定价矩阵</div>
              <div style="font-size:0.78rem;color:#c8ccd4">T1¥{prices['T1']} T2¥{prices['T2']} T3¥{prices['T3']}</div>
              <div style="font-size:0.62rem;color:#62666d">T4¥{prices['T4']} T5¥{prices['T5']} T6¥{prices['T6']}</div></div>""", unsafe_allow_html=True)

    # ══ Strategy Table ══
    st.divider()
    tcol1, tcol2 = st.columns([3, 1])
    with tcol1:
        st.markdown("**逐场策略**")
    with tcol2:
        upgrade_toggle = st.toggle("⬆ 升B升级", value=False,
                                    help="辽宁铁人/重庆铜梁龙 C→B级，全年预估 +~¥2M",
                                    key="h2_upgrade_toggle")
    
    # Recalculate if toggled
    annual_rev = summary["annual_projection_revenue"]
    annual_qty = summary["annual_projection_quantity"]
    if upgrade_toggle:
        annual_rev = summary["annual_projection_revenue"] + 2_000_000
        annual_qty = summary["annual_projection_quantity"] + 4_825
    
    rows = ""
    sum_rev = 0; sum_qty = 0
    for m in matches:
        s = m["strategy"]; sc = STRATEGY_COLOR.get(s, "#8a8f98"); sl = STRATEGY_LABEL.get(s, s)
        bp = m["base_prices"]
        risks_str = " · ".join(m["risks"]) if m["risks"] else "—"
        is_next = next_home and m["date"] == next_home["date"]
        row_style = "background:rgba(255,255,255,0.03);" if is_next else ""
        rows += (
            f'<tr style="{row_style}">'
            f'<td style="font-family:JetBrains Mono,ui-monospace;font-size:0.7rem">{m["date"][5:]}</td>'
            f'<td style="font-weight:510;color:#f7f8f8">{m["opponent"]}</td>'
            f'<td style="color:#8a8f98">{m["tier"]}级</td>'
            f'<td><span style="display:inline-block;padding:2px 8px;border-radius:10px;background:{sc}22;color:{sc};font-size:0.68rem;font-weight:510">{sl}</span></td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">{m["predicted_quantity"]:,}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace;color:#f7f8f8">¥{m["target_revenue"]/1e4:.1f}万</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace;color:#8a8f98">¥{bp["T1"]}-¥{bp["T6"]}</td>'
            f'<td style="font-size:0.65rem;color:#8a8f98;max-width:150px">{risks_str}</td>'
            f'</tr>'
        )
        sum_rev += m["target_revenue"]; sum_qty += m["target_quantity"]
    rows += (
        f'<tr style="border-top:1px solid rgba(255,255,255,0.08);font-weight:510">'
        f'<td colspan="5" style="color:#8a8f98">{len(matches)}场合计</td>'
        f'<td style="color:#f7f8f8;font-family:JetBrains Mono,ui-monospace">¥{sum_rev/1e4:.1f}万</td>'
        f'<td style="color:#f7f8f8;font-family:JetBrains Mono,ui-monospace">{sum_qty:,}张</td>'
        f'<td></td></tr>'
    )
    st.markdown(f"""<table class="compact-table">
      <thead><tr><th>日期</th><th>对手</th><th>级</th><th>策略</th><th>目标收入</th><th>预测</th><th>T1-T6</th><th>风险</th></tr></thead>
      <tbody>{rows}</tbody></table>""", unsafe_allow_html=True)

    # ══ 场次详细预测（与 Tab1 联动）══
    st.divider()
    st.markdown("**场次详细预测**")
    match_labels = [f"{m['date']} vs {m['opponent']}" for m in matches]
    default_idx = 0
    if next_home:
        next_label = f"{next_home['date']} vs {next_home['opponent']}"
        if next_label in match_labels:
            default_idx = match_labels.index(next_label)
    selected_label = st.selectbox(
        "选择 H2 场次查看完整预测",
        match_labels,
        index=default_idx,
        key="h2_detail_match",
    )
    selected_h2 = next(m for m in matches if f"{m['date']} vs {m['opponent']}" == selected_label)
    selected_match = _resolve_match(selected_h2, guoan_matches)
    render_prediction_detail(selected_match, guoan_matches, standings, mae, key_prefix="h2")

    # ══ H1 + H2 Waterfall ══
    st.divider()

    with st.spinner("计算收入分解..."):
        wf_h1 = compute_h1_waterfall(tuple(guoan_matches), _version=1)
        wf_h2 = compute_h2_waterfall(
            json.dumps(h2, ensure_ascii=False),
            tuple(guoan_matches),
            _version=1,
        )

    h1_col, h2_col = st.columns([1, 1])

    with h1_col:
        st.markdown("**H1 收入缺口瀑布**")
        st.caption(f"2025 H1 ¥{wf_h1['rev_2025_h1']/1e4:.0f}万 → 2026 H1 ¥{wf_h1['rev_2026_h1']/1e4:.0f}万  "
                   f"(缺口 ¥{(wf_h1['rev_2026_h1']-wf_h1['rev_2025_h1'])/1e4:+.0f}万)")
        fig1 = draw_waterfall(wf_h1["bars"])
        st.pyplot(fig1)
        plt.close()
        for key, cap in wf_h1["captions"].items():
            st.caption(f"**{key}**: {cap}")

    with h2_col:
        st.markdown("**H2 收入缺口瀑布**")
        st.caption(f"2025 H2 ¥{wf_h2['rev_2025_h2']/1e4:.0f}万 → 2026 H2 预测 ¥{wf_h2['rev_2026_h2']/1e4:.0f}万  "
                   f"(缺口 ¥{(wf_h2['rev_2026_h2']-wf_h2['rev_2025_h2'])/1e4:+.0f}万)")
        st.caption("⚠️ H2比赛尚未进行，仅含对手结构和价格优化效应")
        fig2 = draw_waterfall(wf_h2["bars"])
        st.pyplot(fig2)
        plt.close()
        for key, cap in wf_h2["captions"].items():
            st.caption(f"**{key}**: {cap}")

    # ── 累计追踪表（赛后自动回填实际收入）──
    st.markdown("**H2 累计追踪**")
    cum = 0
    cum_actual = 0
    tro = ""
    for m in matches:
        cum += m["target_revenue"]
        actual_rev = _h2_actual_revenue(m["date"], m["opponent"], guoan_matches)
        if actual_rev is not None:
            cum_actual += actual_rev
            actual_cell = f'¥{actual_rev/1e4:.1f}万'
            delta = actual_rev - m["target_revenue"]
            delta_color = "#51cf66" if delta >= 0 else "#ff6b6b"
            actual_cell += f' <span style="color:{delta_color};font-size:0.62rem">({delta/1e4:+.1f}万)</span>'
        else:
            actual_cell = '<span style="color:#62666d">—</span>'
        tro += (
            f'<tr><td style="font-family:JetBrains Mono,ui-monospace;font-size:0.68rem">{m["date"][5:]}</td>'
            f'<td style="font-weight:510;color:#f7f8f8;font-size:0.72rem">{m["opponent"]}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace;font-size:0.7rem">¥{m["target_revenue"]/1e4:.1f}万</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace;font-size:0.7rem;color:#f7f8f8">¥{cum/1e4:.1f}万</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace;font-size:0.7rem">{actual_cell}</td></tr>'
        )
    actual_total_str = f'¥{cum_actual/1e4:.1f}万' if cum_actual > 0 else '—'
    tro += (
        f'<tr style="border-top:1px solid rgba(255,255,255,0.08);font-weight:510">'
        f'<td colspan="3" style="color:#8a8f98">{len(matches)}场合计</td>'
        f'<td style="color:#f7f8f8">¥{cum/1e4:.1f}万</td>'
        f'<td style="color:#f7f8f8">{actual_total_str}</td></tr>'
    )
    st.markdown(f"""<table class="compact-table" style="font-size:0.7rem">
      <thead><tr><th>日期</th><th>对手</th><th>目标</th><th>累计</th><th>实际</th></tr></thead>
      <tbody>{tro}</tbody></table>""", unsafe_allow_html=True)
    st.caption("实际列：已赛主场自动从 parquet 回填；未赛显示 —")

    # ══ Circuit Breaker Lights ══
    st.divider()
    st.markdown("**熔断灯**")
    lights = [
        ("收入", summary["annual_projection_revenue"] >= 42000000, "¥42M+"),
        ("上座", summary["annual_projection_quantity"] >= 130000, "130K+"),
        ("升班马", not any("升班马" in " ".join(m.get("risks", [])) for m in matches), "待验证"),
        ("综合", summary["vs_2025_revenue_pct"] > -10, ">-10%"),
    ]
    light_html = ""
    for name, ok, note in lights:
        color = "#51cf66" if ok else "#f0c040" if name == "升班马" else "#ff6b6b"
        icon = "●" if ok else "▲" if name == "升班马" else "■"
        light_html += (
            f'<div style="flex:1;text-align:center;padding:8px;background:rgba(255,255,255,0.015);'
            f'border:1px solid rgba(255,255,255,0.05);border-radius:6px;margin:0 4px">'
            f'<div style="font-size:0.6rem;color:#62666d;text-transform:uppercase">{name}</div>'
            f'<div style="font-size:1.3rem;color:{color};margin:4px 0">{icon}</div>'
            f'<div style="font-size:0.62rem;color:#8a8f98">{note}</div></div>'
        )
    st.markdown(f'<div style="display:flex;gap:4px">{light_html}</div>', unsafe_allow_html=True)

    # ══ Model Notes ══
    notes = h2.get("notes", [])
    if notes:
        st.divider()
        st.caption("V5.3 备注")
        for n in notes:
            st.markdown(f'<div style="font-size:0.68rem;color:#62666d;padding:1px 0">· {n}</div>', unsafe_allow_html=True)
