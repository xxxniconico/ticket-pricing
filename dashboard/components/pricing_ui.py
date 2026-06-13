"""定价 UI 组件（策略卡 / 定价表 / What-If）。"""
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from dashboard.common.brand import team_crest_html
from dashboard.common.constants import PT_LABELS, TIER_COLORS, TIER_LABELS, WEEKDAYS, WHATIF_SCENARIOS
from dashboard.common.data_cache import get_optimizer
from dashboard.components.ctx_builder import build_rule_labels
from src.classify import DERBY_RIVALS, classify_opponent_tier
from src.pricing_v5 import ZONE_TIERS, get_pricing_tier

ROOT = Path(__file__).resolve().parent.parent.parent

def render_kpi_cards(target_match, home_preds, guoan_rank, total_pts, home_w, home_d, home_l, form_str):
    if target_match:
        opp = target_match["opponent"]
        dt = pd.Timestamp(target_match["date"])
        tier = classify_opponent_tier(opp)
        pt = get_pricing_tier(opp)
        opp_label = f"vs {opp}"
        opp_sub = f"{target_match['date']} {WEEKDAYS[dt.weekday()]} · {target_match['round']}"
        tier_label = f"{tier} 级"
        tier_sub = f"定价: {PT_LABELS.get(pt, '?')}"
    else:
        opp_label = "—"
        opp_sub = "暂无未来主场比赛"
        tier_label = "—"
        tier_sub = "—"

    preds_arr = np.array([p for _, p, _, _ in home_preds])
    actuals_arr = np.array([a for _, _, a, _ in home_preds])
    mae = np.mean(np.abs(preds_arr - actuals_arr)) if len(preds_arr) > 0 else 0
    mape = np.mean(np.abs(preds_arr - actuals_arr) / actuals_arr) * 100 if len(preds_arr) > 0 else 0

    cards = [
        ("下一场对手", opp_label, opp_sub),
        ("赛季 MAE", f"{mae:,.0f} 张", f"MAPE {mape:.1f}% · N={len(preds_arr)}"),
        ("收入底线", "93%", "≥ 基准收入 × 93%"),
        ("已赛主场", f"{len(home_preds)}/15 场", f"进度 {len(home_preds)/15:.0%}"),
        ("对手分级", tier_label, tier_sub),
        ("国安排名", f"#{guoan_rank}", f"积分 {total_pts}分"),
        ("主场战绩", f"{home_w}-{home_d}-{home_l}", f"{home_w}胜 {home_d}平 {home_l}负"),
        ("近5场形态", form_str if form_str else "—", "W胜 D平 L负"),
    ]

    cols1 = st.columns(4)
    for i in range(4):
        label, value, sub = cards[i]
        with cols1[i]:
            st.markdown(f"""<div class="kpi-card">
              <div class="kpi-label">{label}</div>
              <div class="kpi-value">{value}</div>
              <div class="kpi-sub">{sub}</div>
            </div>""", unsafe_allow_html=True)

    cols2 = st.columns(4)
    for i in range(4, 8):
        label, value, sub = cards[i]
        with cols2[i - 4]:
            st.markdown(f"""<div class="kpi-card">
              <div class="kpi-label">{label}</div>
              <div class="kpi-value">{value}</div>
              <div class="kpi-sub">{sub}</div>
            </div>""", unsafe_allow_html=True)

    pct = len(home_preds) / 15 * 100
    st.markdown(f"""<div class="progress-line">
      <div class="progress-label"><span>赛季主场进度</span><span>{len(home_preds)}/15</span></div>
      <div class="progress-track"><div class="progress-fill" style="width:{pct}%"></div></div>
    </div>""", unsafe_allow_html=True)
    return mae

def render_recent_results(target_match, guoan_matches, standings):
    dt = pd.Timestamp(target_match["date"])
    prev_matches = [m for m in guoan_matches if m.get("completed") and pd.Timestamp(m["date"]) < dt]
    last3 = prev_matches[-3:] if len(prev_matches) >= 3 else prev_matches
    if not last3:
        return

    st.markdown("**近期赛果**")
    rec_html = ""
    for m in last3:
        vs = "vs" if m["is_home"] else "@"
        if m["is_home"]:
            res = "W" if m["hg"] > m["ag"] else "D" if m["hg"] == m["ag"] else "L"
            sc = f"{m['hg']}-{m['ag']}"
        else:
            res = "W" if m["ag"] > m["hg"] else "D" if m["ag"] == m["hg"] else "L"
            sc = f"{m['ag']}-{m['hg']}"
        cls = {"W": "mul", "D": "muted", "L": "mul-neg"}[res]
        impact = ""
        if m["is_home"] and res == "L":
            home_prev = [lm for lm in prev_matches if lm["is_home"] and pd.Timestamp(lm["date"]) <= pd.Timestamp(m["date"])]
            if len(home_prev) >= 2:
                last_two = home_prev[-2:]
                if all(lm["hg"] < lm["ag"] for lm in last_two):
                    impact = '<span style="color:#51cf66;font-size:0.65rem"> → consecutive_home_losses (近2主场连败)</span>'
                elif abs(m["hg"] - m["ag"]) >= 2:
                    idx = prev_matches.index(m) if m in prev_matches else -1
                    later = prev_matches[idx + 1:] if idx >= 0 else []
                    has_win = any(
                        (lm["is_home"] and lm["hg"] > lm["ag"]) or (not lm["is_home"] and lm["ag"] > lm["hg"])
                        for lm in later
                    )
                    if not has_win:
                        impact = f'<span style="color:#51cf66;font-size:0.65rem"> → heavy_home_loss (净负{abs(m["hg"]-m["ag"])}球)</span>'
        elif not m["is_home"] and res != "W":
            away_ct = sum(1 for lm in last3 if not lm["is_home"])
            away_wins = sum(1 for lm in last3 if not lm["is_home"] and lm["ag"] > lm["hg"])
            if away_ct >= 2 and away_wins == 0:
                impact = f'<span style="color:#51cf66;font-size:0.65rem"> → away_winless ({away_ct}客{away_wins}胜)</span>'
        rec_html += (
            f'<div style="font-family:JetBrains Mono,ui-monospace;font-size:0.75rem;padding:2px 8px;color:#8a8f98">'
            f'{m["date"]} {vs} {m["opponent"]} '
            f'<span class="{cls}">{sc} {res}</span>{impact}</div>'
        )
    st.markdown(rec_html, unsafe_allow_html=True)

def render_rule_pills(rules_triggered):
    EMOJI = {"基值":"📊","揭幕战":"🎉","德比":"🔥","A级德比":"🔥","周六场":"📅",
             "赛季末":"🍂","工作日":"📉","客场不胜":"🚌","客场连败":"🚌",
             "主场连败":"💔","主场惨败":"💔","双赛周":"⏱️","暑假":"☀️","盛夏重启":"🌞","榜首":"🏆"}
    pills = []
    for i, (name, desc, m_val, detail) in enumerate(rules_triggered):
        emoji = EMOJI.get(name, "")
        if i == 0:
            pills.append(f'<span class="rule-pill rule-base" title="{detail}">{emoji} {name}</span>')
        elif m_val > 1.0:
            pills.append(f'<span class="rule-pill rule-up" title="{detail}">{emoji} {name} ×{m_val:.2f}</span>')
        elif m_val < 1.0:
            pills.append(f'<span class="rule-pill rule-down" title="{detail}">{emoji} {name} ×{m_val:.2f}</span>')
        else:
            pills.append(f'<span class="rule-pill rule-neutral" title="{detail}">{emoji} {name} ×{m_val:.2f}</span>')
    st.markdown(f'<div style="display:flex;gap:6px;flex-wrap:wrap;margin:8px 0">{"".join(pills)}</div>', unsafe_allow_html=True)

def render_cumulative_bar(base, final_mult, pred, tier, _cal_factor):
    from src.rule_engine import PENALTY_FLOOR as penalty_floor
    bar_pct = min(pred / 20000 * 100, 100)
    _cal_note = f" · EMA校准 ×{_cal_factor:.4f}" if abs(_cal_factor - 1.0) > 0.001 else ""
    st.markdown(f"""<div style="padding:8px 12px;margin:6px 0;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:6px">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <span style="font-size:0.75rem;color:#62666d">累计乘数 <span style="color:#f7f8f8;font-weight:590">{final_mult:.3f}</span> × 基值 {base:,.0f}{_cal_note} =</span>
        <span style="font-size:1.1rem;font-weight:590;color:#f7f8f8">预测 {pred:,.0f} 张</span>
      </div>
      <div style="margin-top:4px;height:3px;background:rgba(255,255,255,0.06);border-radius:2px">
        <div style="width:{bar_pct}%;height:3px;background:#ff6b6b;border-radius:2px"></div>
      </div>
      <div style="font-size:0.6rem;color:#62666d;margin-top:2px">惩罚底线 ×{penalty_floor} · 上限 20,000张</div>
    </div>""", unsafe_allow_html=True)

def render_confidence_bar(pred, mae):
    if mae == 0:
        return
    ci_low = max(0, pred - mae * 1.5)
    ci_high = min(20000, pred + mae * 1.5)
    pct_low = ci_low / 20000 * 100
    pct_pred = pred / 20000 * 100
    pct_high = ci_high / 20000 * 100
    st.markdown(f"""<div class="confidence-bar">
      <div style="font-size:0.75rem;color:#8a8f98">预测上座 <span style="color:#f7f8f8;font-weight:590">{pred:,.0f} 张</span></div>
      <div class="bar-track">
        <div class="bar-ci" style="left:{pct_low}%;width:{pct_high - pct_low}%"></div>
        <div class="bar-marker" style="left:{pct_pred}%"></div>
      </div>
      <div class="ci-labels"><span>悲观 {ci_low:,.0f}</span><span>乐观 {ci_high:,.0f}</span></div>
      <div class="ci-note">基于赛季 MAE {mae:,.0f} 张 · 80% 置信区间</div>
    </div>""", unsafe_allow_html=True)

def render_strategy_card(r, pred_args, actual_revenue=None, actual_attendance=None):
    """渲染策略卡片。优化效果始终 vs 基准预测（决策质量），实际数据仅作参考。"""
    rw, aw = r.revenue_weight, r.attendance_weight
    if rw >= 0.7:
        strat_label, strat_color = "收入优先", "#ff6b6b"
    elif rw <= 0.3:
        strat_label, strat_color = "上座优先", "#51cf66"
    else:
        strat_label, strat_color = "均衡优化", "#f0c040"

    ups = [zt for zt in ZONE_TIERS if r.tiers[zt].optimal_price > r.tiers[zt].base_price * 1.01]
    downs = [zt for zt in ZONE_TIERS if r.tiers[zt].optimal_price < r.tiers[zt].base_price * 0.99]
    frozen = [zt for zt in ZONE_TIERS if r.tiers[zt].is_frozen]

    rules_parts = build_rule_labels(pred_args)

    lines = [f'<strong style="color:#f7f8f8">策略：{strat_label}</strong>（收入权重 {rw:.0%} · 上座权重 {aw:.0%}）']
    lines.append(f'触发规则：{" · ".join(rules_parts) if rules_parts else "无特殊规则，基值预测"}')
    if ups: lines.append(f'<span style="color:#ff6b6b">↑ 涨价档位：{" ".join(ups)}（高价创收）</span>')
    if downs: lines.append(f'<span style="color:#51cf66">↓ 降价档位：{" ".join(downs)}（低价抢量）</span>')
    if frozen: lines.append(f'🔒 锁价档位：{" ".join(frozen)}')

    # 决策质量：始终 vs 基准预测（r.base_* = 未优化时的预测值）
    qty_delta = r.total_attendance - r.base_attendance
    rev_delta_eff = r.total_revenue - r.base_revenue
    att_delta_pct = (r.total_attendance / r.base_attendance - 1) * 100 if r.base_attendance > 0 else 0
    rev_sign = "+" if rev_delta_eff > 0 else ""

    if rw >= 0.7:
        main_metric = f'<span style="color:{"#ff6b6b" if rev_delta_eff > 0 else "#51cf66"}">{"+" if rev_delta_eff > 0 else ""}¥{rev_delta_eff/10000:.1f}万</span>'
        sub_metric = f'上座 {"↑" if qty_delta > 0 else "↓"}{abs(qty_delta):,.0f}张'
    elif rw <= 0.3:
        main_metric = f'<span style="color:{"#ff6b6b" if qty_delta > 0 else "#51cf66"}">{"+" if qty_delta > 0 else ""}{qty_delta:,.0f}张</span>'
        sub_metric = f'收入 {"+" if rev_delta_eff > 0 else ""}¥{rev_delta_eff/10000:.1f}万'
    else:
        main_metric = f'<span style="color:{"#ff6b6b" if rev_delta_eff > 0 else "#51cf66"}">{"+" if rev_delta_eff > 0 else ""}¥{rev_delta_eff/10000:.1f}万</span> · <span style="color:{"#ff6b6b" if qty_delta > 0 else "#51cf66"}">{"+" if qty_delta > 0 else ""}{qty_delta:,.0f}张</span>'
        sub_metric = ''

    lines.append(f'决策质量（vs 基准预测）：{main_metric}{"（" + sub_metric + "）" if sub_metric else ""}')

    # 实际参考：仅当有实际数据时展示
    if actual_revenue is not None and actual_attendance is not None:
        base_qty_dev = r.base_attendance - actual_attendance
        base_rev_dev = (r.base_revenue or 0) - actual_revenue
        pred_ape = abs(base_qty_dev) / actual_attendance * 100 if actual_attendance > 0 else 0
        dev_color = "#51cf66" if pred_ape < 10 else "#f0c040" if pred_ape < 20 else "#ff6b6b"
        lines.append(f'<span style="color:#62666d;font-size:0.85em">预测偏差：基准 {base_qty_dev:+,.0f}张（APE {pred_ape:.1f}%）| 实际到场 {actual_attendance:,} 收入 ¥{actual_revenue/10000:.1f}万</span>')

    derby_card_class = "strategy-card derby" if pred_args.get('derby') else "strategy-card"
    st.markdown(f"""<div class="{derby_card_class}" style="border-left:3px solid {strat_color}">
      {'<br>'.join(lines)}
    </div>""", unsafe_allow_html=True)

    return strat_label, rw

def render_pricing_table(r):
    st.markdown("**定价建议**")
    rows = ""
    for zt in ZONE_TIERS:
        tr = r.tiers[zt]
        dp = (tr.optimal_price / tr.base_price - 1) * 100 if tr.base_price > 0 else 0
        delta_color = "#ff6b6b" if dp > 0.5 else "#51cf66" if dp < -0.5 else "#8a8f98"
        dp_str = f'<span style="color:{delta_color}">{dp:+.0f}%</span>' if abs(dp) > 1 else '<span style="color:#8a8f98">—</span>'
        lock = " 🔒" if tr.is_frozen else ""
        qty_delta = tr.predicted_qty - tr.base_qty
        qty_d_color = "#ff6b6b" if qty_delta > 0 else "#51cf66" if qty_delta < 0 else "#8a8f98"
        rev_delta_z = tr.revenue - (tr.base_price * tr.base_qty)
        rev_d_color = "#ff6b6b" if rev_delta_z > 0 else "#51cf66" if rev_delta_z < 0 else "#8a8f98"
        rows += (
            f'<tr>'
            f'<td style="font-weight:510;color:#f7f8f8">{zt}{lock}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">¥{tr.base_price:,.0f}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace;color:#f7f8f8;font-weight:510">¥{tr.optimal_price:,.0f} {dp_str}</td>'
            f'<td style="color:#62666d">{tr.base_qty:,.0f}</td>'
            f'<td style="color:#f7f8f8">{tr.predicted_qty:,.0f}</td>'
            f'<td style="color:{qty_d_color};font-family:JetBrains Mono,ui-monospace">{qty_delta:+,.0f}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">¥{tr.revenue/10000:.2f}万</td>'
            f'<td style="color:{rev_d_color};font-family:JetBrains Mono,ui-monospace">¥{rev_delta_z/10000:+.1f}万</td>'
            f'</tr>'
        )

    total_dq = (r.total_attendance / r.base_attendance - 1) * 100 if r.base_attendance > 0 else 0
    rev_delta = r.total_revenue - r.base_revenue
    rev_color = "#ff6b6b" if rev_delta > 0 else "#51cf66"
    qty_delta_total = r.total_attendance - r.base_attendance
    qty_d_color = "#ff6b6b" if qty_delta_total > 0 else "#51cf66"

    rows += (
        f'<tr style="border-top:1px solid rgba(255,255,255,0.08);font-weight:510">'
        f'<td colspan="2" style="color:#8a8f98">合计</td>'
        f'<td style="color:#f7f8f8">—</td>'
        f'<td style="color:#62666d">{r.base_attendance:,.0f}</td>'
        f'<td style="color:#f7f8f8">{r.total_attendance:,.0f}</td>'
        f'<td style="color:{qty_d_color};font-family:JetBrains Mono,ui-monospace">{qty_delta_total:+,.0f}</td>'
        f'<td style="color:#f7f8f8">¥{r.total_revenue/10000:.1f}万</td>'
        f'<td style="color:{rev_color};font-family:JetBrains Mono,ui-monospace">¥{rev_delta/10000:+.1f}万</td>'
        f'</tr>'
    )

    st.markdown(f"""<table class="history-table" style="font-size:0.68rem">
      <thead><tr><th>档位</th><th>基准价</th><th>优化价</th><th>基准量</th><th>场景量</th><th>Δ量</th><th>场景收入</th><th>Δ收入</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>""", unsafe_allow_html=True)
    st.caption("情景推演未经验证 · 实际定价请结合实时预售数据")

def render_what_if(r, opp):
    st.divider()
    st.markdown("**What-If 沙盒 | 手动调价测试**")
    scenario_keys = list(WHATIF_SCENARIOS.keys())
    scenario = st.radio(
        "预设情景",
        scenario_keys,
        horizontal=True, key=f"scenario_tab1_{opp}"
    )

    mult = WHATIF_SCENARIOS.get(scenario)
    is_custom = mult is None

    col1, col2 = st.columns(2)
    sliders = {}
    with col1:
        for zt in ["T1", "T2", "T3"]:
            base = r.tiers[zt].base_price
            lo, hi = max(40, int(base * 0.6 / 10) * 10), int(base * 1.3 / 10) * 10
            val = int(base * mult / 10) * 10 if not is_custom else int(base / 10) * 10
            sliders[zt] = st.slider(f"{zt} 价格", lo, hi, max(lo, min(hi, val)), 10, key=f"wiz_{zt}_{opp}")
    with col2:
        for zt in ["T4", "T5", "T6"]:
            base = r.tiers[zt].base_price
            lo, hi = max(30, int(base * 0.6 / 10) * 10), int(base * 1.3 / 10) * 10
            val = int(base * mult / 10) * 10 if not is_custom else int(base / 10) * 10
            sliders[zt] = st.slider(f"{zt} 价格", lo, hi, max(lo, min(hi, val)), 10, key=f"wiz_{zt}_{opp}")

    # Recalc with optimizer's elasticity matrix
    opp_level = r.opponent_level
    optimizer = get_optimizer()
    eps = optimizer.elasticity[opp_level]

    rows = ""
    total_rev, total_qty = 0, 0
    base_total_rev, base_total_qty = 0, 0
    # 场景乘数同时作用于价格起始值（上方 slider）和基础需求（此处 bq）
    qty_mult = mult if not is_custom else 1.0
    for zt in ZONE_TIERS:
        tr = r.tiers[zt]
        bp, bq = tr.base_price, tr.base_qty
        mp = sliders[zt]
        # 悲观→需求下降，乐观→需求上升
        adj_bq = bq * qty_mult
        ep = eps.get(zt, 0.25)
        price_ratio = mp / bp if bp > 0 else 1
        mq = adj_bq * (price_ratio ** (-ep)) if abs(ep) >= 0.001 else adj_bq
        mq = max(0, min(mq, optimizer.capacities[zt]))
        if mp < bp:
            mq = max(mq, adj_bq)
        mrev = mp * mq
        brev = bp * bq
        total_rev += mrev; total_qty += mq
        base_total_rev += brev; base_total_qty += bq

        delta_color = "#51cf66" if mp < bp else "#ff6b6b" if mp > bp else "#8a8f98"
        dq_clr = "#51cf66" if mq < bq else "#ff6b6b" if mq > bq else "#8a8f98"
        rows += (
            f'<tr>'
            f'<td style="font-weight:510">{zt}</td>'
            f'<td>¥{bp:,.0f}</td>'
            f'<td style="color:{delta_color};font-weight:510">¥{mp:,.0f}</td>'
            f'<td>{bq:,.0f}</td>'
            f'<td style="color:{dq_clr}">{mq:,.0f}</td>'
            f'<td>¥{mrev/10000:.2f}万</td>'
            f'</tr>'
        )

    rev_delta = total_rev - base_total_rev
    rev_clr = "#ff6b6b" if rev_delta > 0 else "#51cf66"
    qty_delta = total_qty - base_total_qty
    qty_clr = "#ff6b6b" if qty_delta > 0 else "#51cf66"
    rows += (
        f'<tr style="border-top:1px solid rgba(255,255,255,0.08);font-weight:510">'
        f'<td colspan="3" style="color:#8a8f98">手动模拟合计</td>'
        f'<td style="color:#f7f8f8">{base_total_qty:,.0f}</td>'
        f'<td style="color:{qty_clr}">{total_qty:,.0f}</td>'
        f'<td style="color:{rev_clr}">{rev_delta/10000:+.1f}万</td>'
        f'</tr>'
    )

    st.markdown(f"""<table class="compact-table">
      <thead><tr><th>档位</th><th>基准价</th><th>手动价</th><th>基准量</th><th>手动量</th><th>手动收入</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>""", unsafe_allow_html=True)

    rev_total = total_rev / 10000
    rev_low = rev_total * 0.80
    rev_high = rev_total * 1.15
    st.markdown(f"""<div style="font-size:0.72rem;color:#8a8f98;margin-top:8px">
      收入区间：
      <span style="color:#51cf66">悲观 ¥{rev_low:.0f}万</span> →
      <span style="color:#f7f8f8;font-weight:590">基准 ¥{rev_total:.0f}万</span> →
      <span style="color:#ff6b6b">乐观 ¥{rev_high:.0f}万</span>
    </div>""", unsafe_allow_html=True)

    return sliders


def load_pricing_decisions():
    """加载所有定价决策。"""
    f = ROOT / 'data' / 'processed' / 'pricing_decisions.json'
    if f.exists():
        with open(f) as fh:
            return json.load(fh)
    return {'decisions': []}


def save_pricing_decision(match_date, opponent, prices, note, model_version="V5.4+V8.2"):
    """持久化定价决策 — 同场覆盖，不重复。"""
    data = load_pricing_decisions()
    entry = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'model_version': model_version,
        'match': {'date': match_date, 'opponent': opponent},
        'prices': {zt: int(prices[zt]) for zt in ZONE_TIERS},
        'note': note,
    }
    # 覆盖同场旧记录
    idx = next((i for i, d in enumerate(data['decisions'])
                if d['match']['date'] == match_date and d['match']['opponent'] == opponent), None)
    if idx is not None:
        data['decisions'][idx] = entry
    else:
        data['decisions'].append(entry)
    decision_file = ROOT / 'data' / 'processed' / 'pricing_decisions.json'
    decision_file.parent.mkdir(parents=True, exist_ok=True)
    with open(decision_file, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_snapshot(match_date, opponent, pred, pred_args, result, model_version="V5.4+V8.2"):
    """保存赛前预测快照 — 同场覆盖。"""
    snap_dir = ROOT / 'data' / 'snapshots'
    snap_dir.mkdir(parents=True, exist_ok=True)
    snapshot = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'model_version': model_version,
        'match': {'date': match_date, 'opponent': opponent},
        'prediction': {
            'predicted_quantity': int(pred),
            'tier': classify_opponent_tier(opponent),
        },
        'context': {k: v for k, v in pred_args.items() if v},
        'optimization': {
            'revenue_weight': round(result.revenue_weight, 2),
            'target_revenue': int(result.total_revenue),
            'target_quantity': int(result.total_attendance),
            'prices': {zt: int(result.tiers[zt].base_price) for zt in ZONE_TIERS},
        },
    }
    snap_path = snap_dir / f'pre_{match_date}_{opponent}.json'
    with open(snap_path, 'w') as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2, default=str)
    return snap_path


def render_pricing_confirm(r, opp, match_date, pred, pred_args, sandbox_sliders):
    """定价确认 + 快照：复用沙盒滑块值，持久化决策和预测状态。"""
    st.divider()
    st.markdown("**定价确认 · 快照**")

    prices = {}
    for zt in ZONE_TIERS:
        prices[zt] = sandbox_sliders.get(zt, int(r.tiers[zt].base_price))

    # 读取已有决策
    data = load_pricing_decisions()
    existing = next((d for d in data['decisions']
                     if d['match']['date'] == match_date and d['match']['opponent'] == opp), None)

    if existing:
        st.caption(f"已有决策: {existing['timestamp']} | 备注: {existing.get('note', '无')}")
        default_note = existing.get('note', '')
    else:
        default_note = ''

    note = st.text_input("备注（调价理由）", key=f"confirm_note_{opp}",
                         value=default_note,
                         placeholder="例如：重启效应预期偏高，T6保守")

    c1, c2 = st.columns(2)
    with c1:
        label = "更新定价决策" if existing else "确认定价 · 记录决策"
        if st.button(label, key=f"btn_confirm_{opp}", use_container_width=True):
            save_pricing_decision(match_date, opp, prices, note)
            st.success(f"已{'更新' if existing else '记录'} {opp} 定价决策")
            st.rerun()
    with c2:
        snap_path = ROOT / 'data' / 'snapshots' / f'pre_{match_date}_{opp}.json'
        label = "更新快照" if snap_path.exists() else "保存快照 · 锁定状态"
        if st.button(label, key=f"btn_snapshot_{opp}", use_container_width=True):
            save_snapshot(match_date, opp, pred, pred_args, r)
            st.success(f"快照已{'更新' if snap_path.exists() else '保存'}: {snap_path.name}")

    price_tags = " · ".join(f"{zt} ¥{prices[zt]:,}" for zt in ZONE_TIERS)
    st.caption(f"当前生效: {price_tags}")


