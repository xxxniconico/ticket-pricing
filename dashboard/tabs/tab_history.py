"""Tab: 历史定价。"""
import numpy as np
import pandas as pd
import streamlit as st

from dashboard.common.brand import team_crest_html
from dashboard.common.constants import TIER_COLORS
from dashboard.common.data_cache import _get_zone_actual_revenue, _get_zone_face_revenue, _get_zone_qtys, get_optimizer
from dashboard.components.ctx_builder import build_pred_args
from dashboard.components.pricing_ui import render_pricing_table, render_strategy_card
from src.classify import DERBY_RIVALS, classify_opponent_tier
from src.pricing_v5 import ZONE_TIERS, build_price_matrix, get_pricing_tier
from src.rule_engine import update as rule_update
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent

# ══════════════════════════════════════════════════════════
#  Tab 2: 历史定价
# ══════════════════════════════════════════════════════════

def render_mae_chart(home_preds):
    if not home_preds:
        return
    errors = [p - a for _, p, a, _ in home_preds]
    labels = [f"{m['date'][5:]} {m['opponent'][:3]}" for m, _, _, _ in home_preds]

    st.markdown("**模型 MAE 收敛趋势**")
    bars = ""
    max_abs = max(abs(e) for e in errors) if errors else 1
    for label, err in zip(labels, errors):
        pct = abs(err) / max_abs * 100 if max_abs > 0 else 0
        bar_w = max(pct, 3)
        clr = "#ff6b6b" if err > 0 else "#51cf66"
        bars += f"""<div style="display:flex;align-items:center;gap:8px;margin:2px 0">
          <span style="font-size:0.7rem;color:#8a8f98;min-width:90px;font-family:JetBrains Mono,ui-monospace">{label}</span>
          <div style="flex:1;height:14px;background:rgba(255,255,255,0.03);border-radius:3px;overflow:hidden">
            <div style="width:{bar_w}%;height:14px;background:{clr};border-radius:3px;opacity:0.6"></div>
          </div>
          <span style="font-size:0.7rem;color:{clr};font-weight:510;min-width:70px;font-family:JetBrains Mono,ui-monospace">{err:+,.0f}</span>
        </div>"""
    mae_now = np.mean(np.abs(errors)) if errors else 0
    bars += f"""<div style="font-size:0.65rem;color:#8a8f98;margin-top:4px;text-align:right">
      当前 MAE <span style="color:#f7f8f8;font-weight:590">{mae_now:,.0f} 张</span>
    </div>"""
    st.markdown(bars, unsafe_allow_html=True)

def _load_decisions():
    """加载定价决策，返回 {date_opp: decision_dict} 映射。"""
    f = ROOT / 'data' / 'processed' / 'pricing_decisions.json'
    if not f.exists():
        return {}
    with open(f) as fh:
        data = json.load(fh)
    lookup = {}
    for d in data.get('decisions', []):
        key = f"{d['match']['date']}_{d['match']['opponent']}"
        lookup[key] = d
    return lookup

def render_history_expanders(home_preds, guoan_matches):
    if not home_preds:
        st.info("暂无已赛主场数据")
        return

    st.divider()
    st.caption("每场比赛展开查看详情 · 情景推演未经验证")

    # 顶部日期锚点快选
    anchor_links = []
    for i, (m, _, _, _) in enumerate(home_preds):
        anchor_links.append(
            f'<a href="#hist-{i}" style="color:#8a8f98;text-decoration:none;'
            f'font-size:0.72rem;padding:2px 6px;border:1px solid rgba(255,255,255,0.08);'
            f'border-radius:4px;margin:0 2px">{m["date"][5:]} {m["opponent"][:4]}</a>'
        )
    st.markdown(
        f'<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px">{"".join(anchor_links)}</div>',
        unsafe_allow_html=True,
    )

    optimizer = get_optimizer()
    _pm = build_price_matrix()
    decisions = _load_decisions()

    for i, (m, p, a, ctx) in enumerate(home_preds):
        opp = m["opponent"]
        dt_m = pd.Timestamp(m["date"])
        ape = abs(p - a) / a * 100 if a > 0 else 0
        ape_color = "#51cf66" if ape < 10 else "#f0c040" if ape < 20 else "#ff6b6b"

        expanded = (i == len(home_preds) - 1)

        st.divider()
        crest_h = team_crest_html(opp, "sm")
        derby_tag = ' 🔥德比' if opp in DERBY_RIVALS else ''
        st.markdown(f'<span id="hist-{i}"></span>', unsafe_allow_html=True)
        dyn_tier = classify_opponent_tier(opp, match_date=m["date"])
        st.markdown(f"{crest_h} **{m['date']} vs {opp}{derby_tag}** `{dyn_tier}` | 预测{p:,.0f} 实际{a:,.0f} | 误差{p - a:+,.0f} APE{ape:.1f}%", unsafe_allow_html=True)
        pred_args = build_pred_args(m, ctx, {'summer': dt_m.month in [7,8], 'match_year': m["date"][:4]})
        r_h = optimizer.optimize(opp, **pred_args)

        # Load actual data first, then render strategy card with vs-actual comparison
        zone_qty = _get_zone_qtys(m)
        zone_rev = _get_zone_face_revenue(m)  # 票面收入（面值×销量），消除折扣偏差
        total_actual_qty = 0
        total_actual_rev = 0

        for zt in ZONE_TIERS:
            tr = r_h.tiers[zt]
            dp = (tr.optimal_price / tr.base_price - 1) * 100 if tr.base_price > 0 else 0
            delta_color = "#51cf66" if dp < -0.5 else "#ff6b6b" if dp > 0.5 else "#8a8f98"
            dp_s = f'<span style="color:{delta_color}">{dp:+.0f}%</span>' if abs(dp) > 1 else ""
            actual_z = zone_qty.get(zt, 0)
            actual_rev = zone_rev.get(zt, 0)
            total_actual_rev += actual_rev
            total_actual_qty += actual_z
            qty_delta_z = tr.predicted_qty - actual_z
            qty_delta_color = "#ff6b6b" if qty_delta_z > 0 else "#51cf66" if qty_delta_z < 0 else "#8a8f98"

        # Strategy card with vs-actual data (dynamic linkage)
        strat_label, rw = render_strategy_card(r_h, pred_args,
            actual_revenue=total_actual_rev, actual_attendance=total_actual_qty)

        # Load actual pricing decision for this match
        dec_key = f"{m['date']}_{opp}"
        decision = decisions.get(dec_key, {})
        actual_prices = decision.get('prices', {})
        decision_note = decision.get('note', '')

        # Build pricing table HTML: 决策质量优先（Δ = 场景 vs 基准预测）
        r_html = ""
        for zt in ZONE_TIERS:
            tr = r_h.tiers[zt]
            dp = (tr.optimal_price / tr.base_price - 1) * 100 if tr.base_price > 0 else 0
            dp_color = "#51cf66" if dp < -0.5 else "#ff6b6b" if dp > 0.5 else "#8a8f98"
            dp_s = f'<span style="color:{dp_color}">{dp:+.0f}%</span>' if abs(dp) > 1 else ""
            # 决策质量 Δ = 场景 - 基准（同一预测基础上的优化效应）
            qty_base_z = tr.base_qty
            qty_opt_z = tr.predicted_qty
            qty_delta_z = qty_opt_z - qty_base_z
            qty_delta_color = "#ff6b6b" if qty_delta_z > 0 else "#51cf66" if qty_delta_z < 0 else "#8a8f98"
            rev_base_z = tr.base_price * tr.base_qty
            rev_opt_z = tr.revenue
            rev_delta_z = rev_opt_z - rev_base_z
            rev_delta_z_color = "#ff6b6b" if rev_delta_z > 0 else "#51cf66" if rev_delta_z < 0 else "#8a8f98"
            # 实际数据（纯参考）
            actual_z = zone_qty.get(zt, 0)
            actual_rev_z = zone_rev.get(zt, 0)
            act_p = actual_prices.get(zt)
            act_p_str = f'¥{act_p:,.0f}' if act_p else '<span style="color:#62666d">—</span>'
            r_html += (
                f'<tr><td>{zt}</td>'
                f'<td>¥{tr.base_price:,.0f}</td>'
                f'<td>¥{tr.optimal_price:,.0f} {dp_s}</td>'
                f'<td>{act_p_str}</td>'
                f'<td style="color:#62666d">{qty_base_z:,.0f}</td>'
                f'<td style="color:#f7f8f8">{qty_opt_z:,.0f}</td>'
                f'<td style="color:{qty_delta_color};font-family:JetBrains Mono,ui-monospace">{qty_delta_z:+,.0f}</td>'
                f'<td>¥{rev_opt_z/10000:.2f}万</td>'
                f'<td style="color:{rev_delta_z_color};font-family:JetBrains Mono,ui-monospace">¥{rev_delta_z/10000:+.1f}万</td>'
                f'<td style="color:#62666d">{actual_z:,}</td>'
                f'<td style="color:#62666d">¥{actual_rev_z/10000:.2f}万</td>'
                f'</tr>'
            )

        # Total row: decision quality deltas (opt - base)
        qty_delta_total = r_h.total_attendance - r_h.base_attendance
        qty_delta_t_color = "#ff6b6b" if qty_delta_total > 0 else "#51cf66" if qty_delta_total < 0 else "#8a8f98"
        rev_delta_total = r_h.total_revenue - (r_h.base_revenue or 0)
        rev_delta_t_color = "#ff6b6b" if rev_delta_total > 0 else "#51cf66" if rev_delta_total < 0 else "#8a8f98"
        r_html += (
            f'<tr style="border-top:1px solid rgba(255,255,255,0.08);font-weight:510">'
            f'<td colspan="4" style="color:#8a8f98">合计</td>'
            f'<td style="color:#62666d">{r_h.base_attendance:,.0f}</td>'
            f'<td style="color:#f7f8f8">{r_h.total_attendance:,.0f}</td>'
            f'<td style="color:{qty_delta_t_color};font-family:JetBrains Mono,ui-monospace">{qty_delta_total:+,.0f}</td>'
            f'<td>¥{r_h.total_revenue/10000:.1f}万</td>'
            f'<td style="color:{rev_delta_t_color};font-family:JetBrains Mono,ui-monospace">¥{rev_delta_total/10000:+.1f}万</td>'
            f'<td style="color:#62666d">{total_actual_qty:,}</td>'
            f'<td style="color:#62666d">¥{total_actual_rev/10000:.1f}万</td>'
            f'</tr>'
        )

        st.markdown(f"""<div class="table-scroll"><table class="history-table">
          <thead><tr><th>档位</th><th>基准价</th><th>优化价</th><th>实际执行价</th><th>基准量</th><th>场景量</th><th>Δ量</th><th>场景收入</th><th>Δ收入</th><th>实际量</th><th>实际收入</th></tr></thead>
          <tbody>{r_html}</tbody>
        </table></div>""", unsafe_allow_html=True)

        # Bad tradeoff 检测：基于决策质量（场景 vs 基准），不是实际 vs 场景
        bad_tradeoff = False
        bad_reason = ""
        if rw >= 0.7 and rev_delta_total < -5000 and qty_delta_total < 100:
            bad_tradeoff = True
            bad_reason = f"⚠️ 收入优先策略下损失 ¥{abs(rev_delta_total)/10000:.1f}万（vs 基准），仅增量 {qty_delta_total:+,.0f}张，tradeoff 不划算"
        elif rw <= 0.3 and qty_delta_total < 0 and rev_delta_total < -3000:
            bad_tradeoff = True
            bad_reason = f"⚠️ 上座优先策略下未增量（{qty_delta_total:+,.0f}张 vs 基准），还损失 ¥{abs(rev_delta_total)/10000:.1f}万"

        # 规则3: 增收但代价过大（收入优先+均衡模式）
        if not bad_tradeoff and rw >= 0.5:
            rev_gain = rev_delta_total
            qty_loss = -qty_delta_total
            if rev_gain > 0 and qty_loss > 100:
                gain_per_lost = rev_gain / qty_loss if qty_loss > 0 else float('inf')
                if gain_per_lost < 50:
                    bad_tradeoff = True
                    bad_reason = f"⚠️ 增收 ¥{rev_gain/10000:.1f}万但上座 -{qty_loss:,.0f}张（仅 ¥{gain_per_lost:.0f}/人），代价过大"

        # 规则4: 降价增量但收入损失过大
        if not bad_tradeoff and rw <= 0.3:
            qty_gain = qty_delta_total
            rev_loss = -rev_delta_total
            if qty_gain > 0 and rev_loss > 5000:
                cost_per_gained = rev_loss / qty_gain if qty_gain > 0 else float('inf')
                if cost_per_gained > 200:
                    bad_tradeoff = True
                    bad_reason = f"⚠️ 增量 {qty_gain:+,.0f}张但损失 ¥{rev_loss/10000:.1f}万（¥{cost_per_gained:.0f}/人），获客成本过高"

        if bad_tradeoff:
            st.markdown(f"""<div style="padding:6px 12px;margin:4px 0;background:rgba(255,107,107,0.08);border:1px solid rgba(255,107,107,0.2);border-radius:6px;font-size:0.72rem;color:#ff6b6b">
              {bad_reason}
            </div>""", unsafe_allow_html=True)

        # 策略审计卡片 — 决策质量评估
        audit_bg = "rgba(81,207,102,0.06)" if not bad_tradeoff else "rgba(255,107,107,0.08)"
        audit_border = "rgba(81,207,102,0.12)" if not bad_tradeoff else "rgba(255,107,107,0.2)"
        audit_color = "#51cf66" if not bad_tradeoff else "#ff6b6b"
        audit_judgment = "✅ 策略目标达成" if not bad_tradeoff else "❌ 策略未达成 — 见上方警告"

        # 预测偏差
        base_qty_dev_audit = (r_h.base_attendance or 0) - total_actual_qty
        base_rev_dev_audit = (r_h.base_revenue or 0) - total_actual_rev

        # Build actual pricing summary for audit card
        act_price_summary = ""
        if actual_prices:
            act_parts = [f"{zt} ¥{actual_prices[zt]:,}" for zt in ZONE_TIERS if zt in actual_prices]
            act_price_summary = f"实际执行价：{' · '.join(act_parts)}<br>"
            if decision_note:
                act_price_summary += f"备注：{decision_note}<br>"
        st.markdown(f"""<div style="padding:8px 12px;margin:4px 0;background:{audit_bg};border:1px solid {audit_border};border-radius:6px;font-size:0.72rem;color:{audit_color}">
          <strong>{opp} 策略审计（决策质量）</strong><br>
          策略模式：{strat_label}（rw={rw:.0%} aw={r_h.attendance_weight:.0%}）<br>
          优化效应：场景 ¥{r_h.total_revenue/10000:.1f}万 vs 基准 ¥{(r_h.base_revenue or 0)/10000:.1f}万（{rev_delta_total/10000:+.1f}万）<br>
          数量效应：场景 {r_h.total_attendance:,.0f}张 vs 基准 {(r_h.base_attendance or 0):.0f}张（{qty_delta_total:+,.0f}张）<br>
          预测偏差：基准 {base_qty_dev_audit:+,.0f}张 · 实际到场 {total_actual_qty:,} · 实际收入 ¥{total_actual_rev/10000:.1f}万<br>
          {act_price_summary}判断：{audit_judgment}
        </div>""", unsafe_allow_html=True)

        # V8.1: 赛后校准已禁用
        rule_update(
            match_id=f"{m['date']}_{opp}",
            opponent=opp,
            actual=a,
            **pred_args
        )


# ══════════════════════════════════════════════════════════
#  Tab 3: 赛季全景
# ══════════════════════════════════════════════════════════

def render_season_chart(home_preds):
    if len(home_preds) < 2:
        return

    dates = [pd.Timestamp(m["date"]) for m, _, _, _ in home_preds]
    preds_plt = [p for _, p, _, _ in home_preds]
    actuals_plt = [a for _, _, a, _ in home_preds]
    labels_plt = [m["opponent"][:3] for m, _, _, _ in home_preds]

    fig, ax = plt.subplots(figsize=(8, 2.5))
    fig.patch.set_facecolor('#0c0d0f')
    ax.set_facecolor('#0c0d0f')
    x = range(len(dates))
    ax.plot(x, preds_plt, 'o--', color='#ff6b6b', linewidth=1.5, markersize=6, label='预测', alpha=0.8)
    ax.plot(x, actuals_plt, 'o-', color='#51cf66', linewidth=2, markersize=6, label='实际')
    ax.set_xticks(x)
    ax.set_xticklabels(labels_plt, fontsize=8, color='#8a8f98')
    ax.tick_params(axis='y', colors='#62666d', labelsize=8)
    for spine in ['top', 'right']:
        ax.spines[spine].set_visible(False)
    ax.spines['bottom'].set_color('#2a2d33')
    ax.spines['left'].set_color('#2a2d33')
    ax.grid(axis='y', alpha=0.05, color='white')
    ax.legend(loc='upper right', facecolor='#1a1d22', edgecolor='#2a2d33', labelcolor='#8a8f98', fontsize=8)
    st.pyplot(fig)
    plt.close(fig)

def render_season_table(home_preds):
    st.subheader("赛季回望")
    if not home_preds:
        st.info("暂无已赛主场数据")
        return

    rows = []
    preds_all, actuals_all = [], []
    for m, p, a, _ in home_preds:
        preds_all.append(p); actuals_all.append(a)
        ape = abs(p - a) / a * 100
        err_clr = "#ff6b6b" if p > a else "#51cf66"
        rows.append(
            f'<tr>'
            f'<td>{m["date"]}</td>'
            f'<td>{m["opponent"]}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">{p:,.0f}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">{a:,.0f}</td>'
            f'<td style="color:{err_clr};font-family:JetBrains Mono,ui-monospace">{p - a:+,.0f}</td>'
            f'<td>{ape:.1f}%</td>'
            f'</tr>'
        )

    mae = np.mean(np.abs(np.array(preds_all) - np.array(actuals_all)))
    st.markdown(f"""<table class="history-table">
      <thead><tr><th>日期</th><th>对手</th><th>预测</th><th>实际</th><th>误差</th><th>APE</th></tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>""", unsafe_allow_html=True)
    st.metric("累积 MAE", f"{mae:,.0f} 张")


# ══════════════════════════════════════════════════════════
#  Tab 4: 对手分析
# ══════════════════════════════════════════════════════════

from dashboard.common.data_cache import get_ctx_rounds
