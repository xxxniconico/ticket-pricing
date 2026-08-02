"""单场完整预测渲染：规则链 + 置信区间 + 定价 + What-If。"""
import pandas as pd
import streamlit as st

from dashboard.common.data_cache import get_ctx_rounds, get_optimizer
from dashboard.components.ctx_builder import build_pred_args
from dashboard.components.pricing_ui import (
    render_confidence_bar,
    render_cumulative_bar,
    render_pricing_confirm,
    render_pricing_table,
    render_rule_pills,
    render_strategy_card,
    render_what_if,
)
from src.classify import DERBY_RIVALS, classify_opponent_tier
from src.csl_context import detect_ctx
from dashboard.common.engine_compat import get_effective_calibration
from src.rule_engine import MULTIPLIERS, PENALTY_FLOOR, TIER_BASE
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent


def build_rules_triggered(target_match, ctx, guoan_matches, use_dynamic=False):
    """从 match + ctx 构建规则链条目列表。"""
    opp = target_match["opponent"]
    dt = pd.Timestamp(target_match["date"])
    if use_dynamic:
        tier = classify_opponent_tier(opp, match_date=target_match["date"])
    else:
        tier = classify_opponent_tier(opp)
    derby = opp in DERBY_RIVALS
    sat = dt.weekday() == 5
    late = dt.month >= 10
    mid = dt.weekday() in (1, 2, 3)
    sm = dt.month in (7, 8)
    chl = ctx.get("consecutive_home_losses", False)
    hh = ctx.get("heavy_home_loss", False)
    awl = ctx.get("away_winless_losses", False)
    aw = ctx.get("away_winless", False)
    sr = ctx.get("short_rest", False)
    mr = ctx.get("midseason_restart", False)
    so = ctx.get("season_opener", False)
    t3f = ctx.get("top3_form", False)

    prev_matches = [m for m in guoan_matches if m.get("completed") and pd.Timestamp(m["date"]) < dt]
    base = TIER_BASE.get(tier, 9000)
    rules = [("基值", f"{tier}级 {base:,.0f}张", 1.0,
              f"{tier}级基值来自KMeans聚类均值（S={TIER_BASE['S']:,.0f} A={TIER_BASE['A']:,.0f} B={TIER_BASE['B']:,.0f} C={TIER_BASE['C']:,.0f}）")]

    if so:
        rules.append(("揭幕战", f"赛季首个主场 ×{MULTIPLIERS['season_opener']}", MULTIPLIERS["season_opener"],
                      "揭幕战球迷关注度高，历史上座溢价约17%"))
    if derby:
        if tier == "S":
            rules.append(("德比", "S级德比不叠加溢价", 1.0, f"申花已是S级最高基值（{TIER_BASE['S']:,}），德比溢价已内嵌在分级中"))
        else:
            m_val = 1.05 if tier == "A" else 1.25
            label = "A级德比" if tier == "A" else "德比"
            rules.append((label, f"{opp} {label}对手 ×{m_val}", m_val,
                          f"{'A级德比溢价5%' if tier == 'A' else '历史数据显示溢价25%'}，S级不叠加"))
    if sat:
        rules.append(("周六场", "周末上座溢价 ×1.02", 1.02, "周六比赛日球迷时间充裕，V5.1网格搜索最优溢价约2%"))
    if mr and not so:
        rules.append(("盛夏重启", f"距上场≥28天 下半季回归 ×1.10", 1.10,
                      f"长休{28 if not prev_matches else (dt - pd.Timestamp(prev_matches[-1]['date'])).days}天后球迷回流，B级6月重启场次历史均值1.22x，保守标定1.10"))
    if sm and tier == "C":
        rules.append(("暑假效应", f"7-8月暑假效应 x{MULTIPLIERS['summer_C']}", MULTIPLIERS["summer_C"],
                      "C级暑假实测（辽宁7/17 ratio=1.33）加成最大，勿与B级共用1.13"))
    elif sm and tier == "B":
        rules.append(("暑假效应", f"7-8月暑假运营活动 x{MULTIPLIERS['summer']}", MULTIPLIERS["summer"],
                      "暑假期间球迷观赛时间充裕，运营促销活动叠加"))
    elif sm and tier in ("S", "A"):
        rules.append(("暑假效应", "7-8月暑假效应 x1.08", 1.08,
                      "暑假期间S/A级球队观赛需求小幅上升"))
    if t3f and tier in ("B", "C"):
        rules.append(("榜首", f"国安排名前3 ×{MULTIPLIERS['top3_form']}", MULTIPLIERS["top3_form"],
                      "争冠/亚冠预期溢价，仅 B/C 级生效"))
    if late:
        rules.append(("赛季末", f"{dt.month}月 战意衰减 ×{MULTIPLIERS['late_season']}", MULTIPLIERS["late_season"],
                      "10月以后赛季末，若球队已无争冠/保级悬念，上座下滑"))
    if mid and not chl and not hh:
        rules.append(("工作日", f"周{'一二三四五六日'[dt.weekday()]} 工作日衰减 ×{MULTIPLIERS['midweek']}",
                      MULTIPLIERS["midweek"], "周二/三/四工作日影响，不与连败/惨败叠加"))
    if awl:
        away3 = [m for m in prev_matches[-3:] if not m["is_home"]] if len(prev_matches) >= 3 else []
        aw_mult = 0.77 if tier in ("S", "A") else MULTIPLIERS["away_winless_losses"]
        detail = " · ".join(
            f"{lm['date']} vs {lm['opponent']} {lm['hg']}-{lm['ag']}"
            for lm in away3 if not lm["is_home"]
        )
        rules.append(("客场全败", f"近3场{len(away3)}客全胜负 ×{aw_mult}", aw_mult,
                      f"客场连败压制主场热情（{detail}）· S/A级主场×0.77"))
    elif aw:
        away3 = [m for m in prev_matches[-3:] if not m["is_home"]] if len(prev_matches) >= 3 else []
        rules.append(("客场不胜", f"近3场{len(away3)}客0胜含平 ×{MULTIPLIERS['away_winless']}",
                      MULTIPLIERS["away_winless"], "球迷对客场表现失望传导至主场观赛意愿"))
    if chl:
        home_prev = [m for m in prev_matches if m["is_home"]]
        last_two = home_prev[-2:] if len(home_prev) >= 2 else []
        detail = " · ".join(f"{lm['date']} vs {lm['opponent']} {lm['hg']}-{lm['ag']}" for lm in last_two)
        rules.append(("主场连败", f"近2主场均负 ×{MULTIPLIERS['consecutive_home_losses']}",
                      MULTIPLIERS["consecutive_home_losses"], f"连续主场失利压制上座（{detail}）"))
    elif hh:
        hh_match = None
        for m in prev_matches[-3:]:
            if not m["is_home"]:
                continue
            if m["hg"] is not None and m["ag"] is not None and m["hg"] < m["ag"] and abs(m["hg"] - m["ag"]) >= 2:
                idx = prev_matches.index(m) if m in prev_matches else -1
                later = prev_matches[idx + 1:] if idx >= 0 else []
                has_win = any(
                    (lm["is_home"] and lm["hg"] > lm["ag"]) or (not lm["is_home"] and lm["ag"] > lm["hg"])
                    for lm in later
                )
                if not has_win:
                    hh_match = (m["date"], m["opponent"], abs(m["hg"] - m["ag"]))
        if hh_match:
            rules.append(("主场惨败", f"{hh_match[0]} vs {hh_match[1]} 净负{hh_match[2]}球 ×{MULTIPLIERS['heavy_home_loss']}",
                          MULTIPLIERS["heavy_home_loss"],
                          f"主场净负≥2球（vs {hh_match[1]} -{hh_match[2]}球），球迷失望情绪压制下场上座"))
        else:
            rules.append(("主场惨败", f"主场净负≥2球 ×{MULTIPLIERS['heavy_home_loss']}",
                          MULTIPLIERS["heavy_home_loss"], "失望情绪压制下场上座"))
    if sr and not chl and not hh:
        rules.append(("双赛周", f"距上一主场 ≤4天 ×{MULTIPLIERS['short_rest']}",
                      MULTIPLIERS["short_rest"], "双赛周疲劳导致观赛意愿下降"))
    return rules, tier, base


def render_prediction_detail(target_match, guoan_matches, standings, mae, key_prefix="tab1", use_dynamic=False):
    """渲染单个场次的完整预测：规则链 + 置信 + 策略 + 定价 + What-If。"""
    opp = target_match["opponent"]
    if use_dynamic:
        tier = classify_opponent_tier(opp, match_date=target_match["date"])
    else:
        tier = classify_opponent_tier(opp)
    ctx = detect_ctx(target_match, guoan_matches, get_ctx_rounds())

    st.markdown("**命中规则 · 上座预测计算链**")
    rules_triggered, tier, base = build_rules_triggered(target_match, ctx, guoan_matches, use_dynamic)
    render_rule_pills(rules_triggered)

    # 预测一律走引擎 predict_calibrated（与优化器同函数同参数，含 EMA 校准），
    # 展示层不再自算——防止规则链与引擎漂移（历史教训：C级暑假 1.13 vs 1.30 双轨）
    from src.rule_engine import predict_calibrated as _engine_predict
    pred_args0 = build_pred_args(target_match, ctx)
    pred = _engine_predict(opp, **pred_args0, opponent_tier_override=tier)
    cal_factor = get_effective_calibration(tier, enable_ema=True)

    render_cumulative_bar(base, max(pred / max(base, 1) / max(cal_factor, 1e-9), PENALTY_FLOOR), pred, tier, cal_factor)
    render_confidence_bar(pred, mae)

    st.divider()
    st.markdown("**定价建议**")
    st.caption("规则引擎预测 + 分层组合策略优化 · 情景推演未经验证")

    strategy_mode = st.radio(
        "策略模式",
        ["auto", "balanced"], index=0, horizontal=True,
        format_func=lambda x: "自动（动态权重）" if x == "auto" else "平衡",
        key=f"strategy_{key_prefix}_{opp}",
    )
    if strategy_mode == "balanced":
        st.caption("平衡模式：T1-T3 降价抢量 + T4-T6 涨价补收入")

    pred_args = pred_args0
    optimizer = get_optimizer()
    # Check for pricing overrides
    import json
    override_path = ROOT / "data" / "processed" / "pricing_overrides.json"
    ovr = {}
    if override_path.exists():
        ovr = json.load(open(override_path)).get(opp, {})
    overrides = ovr.get("prices", {})
    from dashboard.components.pricing_ui import get_prev_match_inventory
    prev_inv = get_prev_match_inventory(target_match["date"])
    r = optimizer.optimize(opp, match_date=target_match["date"], strategy=strategy_mode, capacity_overrides=prev_inv, **pred_args)
    if overrides:
        for zt, p in overrides.items():
            if zt in r.tiers:
                r.tiers[zt].optimal_price = p
    # Also override quantities if provided
    qty_overrides = ovr.get("qtys", {})
    if qty_overrides:
        for zt, q in qty_overrides.items():
            if zt in r.tiers:
                r.tiers[zt].predicted_qty = q
                r.tiers[zt].revenue = q * r.tiers[zt].optimal_price
        r.total_attendance = sum(tr.predicted_qty for tr in r.tiers.values())
        r.total_revenue = sum(tr.revenue for tr in r.tiers.values())

    # ── 库存与份额（V9.1 分级均值+T4/T5扩容值）──
    st.markdown("**库存与份额**")
    from src.pricing_v5 import ZONE_TIERS
    caps = getattr(optimizer, "capacities", {})
    cap_rows = ""
    for zt in ZONE_TIERS:
        tr = r.tiers[zt]
        cap = caps.get(zt, 0)
        share = tr.base_qty / max(r.base_attendance, 1) * 100
        cap_rows += (
            f"<tr>"
            f"<td style='font-weight:510'>{zt}</td>"
            f"<td style='font-family:JetBrains Mono'>{cap:,.0f}座</td>"
            f"<td style='font-family:JetBrains Mono'>{tr.base_qty:,.0f}张</td>"
            f"<td style='font-family:JetBrains Mono'>{share:.1f}%</td>"
            f"<td>\u00a5{tr.base_price:,.0f}</td>"
            f"</tr>"
        )
    avg_price = r.base_revenue / r.base_attendance if r.base_attendance > 0 else 0
    total_cap = sum(caps.values()) if caps else r.base_attendance
    cap_rows += (
        f'<tr style="border-top:1px solid rgba(255,255,255,0.08);font-weight:510">'
        f'<td>合计</td>'
        f'<td style="font-family:JetBrains Mono">{total_cap:,.0f}座</td>'
        f'<td style="font-family:JetBrains Mono">{r.base_attendance:,.0f}张</td>'
        f'<td>100%</td>'
        f'<td style="font-family:JetBrains Mono">均¥{avg_price:.0f}</td></tr>'
    )
    st.markdown(f"""<table class="compact-table" style="max-width:550px;font-size:0.72rem">
      <thead><tr><th>档位</th><th>容量</th><th>分配量</th><th>份额</th><th>基准价</th></tr></thead>
      <tbody>{cap_rows}</tbody>
    </table>""", unsafe_allow_html=True)
    st.caption(f"V9.1分级均值+T4/T5扩容真实值 · 预测上座 {r.base_attendance:,.0f}张")

    render_strategy_card(r, pred_args)
    render_pricing_table(r)
    if overrides:
        note = ovr.get("note", "")
        if note:
            st.info(f"定价说明：{note}")
    sandbox_sliders, sandbox_inventory = render_what_if(r, opp, match_date=target_match["date"])
    render_pricing_confirm(r, opp, target_match["date"], pred, pred_args, sandbox_sliders, sandbox_inventory)
    return pred, r
