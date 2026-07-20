"""单场完整预测渲染：规则链 + 置信区间 + 定价 + What-If。"""
import pandas as pd
import streamlit as st

from dashboard.common.data_cache import get_ctx_rounds, get_optimizer
from dashboard.components.ctx_builder import build_pred_args
# pricing_ui components no longer used — see inline 6-step chain
from src.classify import DERBY_RIVALS, classify_opponent_tier
from src.csl_context import detect_ctx
from src.rule_engine import MULTIPLIERS, PENALTY_FLOOR, TIER_BASE
from src.pricing_v5 import ZONE_TIERS
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
    if sm and tier in ("B", "C"):
        rules.append(("暑假效应", f"7-8月暑假运营活动 x{MULTIPLIERS["summer"]}", MULTIPLIERS["summer"],
                      "暑假期间球迷观赛时间充裕，运营促销活动叠加"))
    elif sm and tier in ("S", "A"):
        rules.append(("暑假效应", "7-8月暑假效应 x1.08", 1.08,
                      "暑假期间S/A级球队观赛需求小幅上升"))
    if t3f and tier in ("B", "C"):
        rules.append(("榜首", f"国安排名前3 ×{MULTIPLIERS['top3_form']}", MULTIPLIERS["top3_form"],
                      "争冠/亚冠预期溢价，仅 B/C 级生效"))
    if late:
        rules.append(("赛季末", f"{dt.month}月 战意衰减 ×0.80", 0.80, "10月以后赛季末，若球队已无争冠/保级悬念，上座下滑"))
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
    """完整决策卡：6步计算链 → 定价建议"""
    opp = target_match["opponent"]
    ctx = detect_ctx(target_match, guoan_matches, get_ctx_rounds())
    
    # ── ① 动态评级 ──
    st.markdown("#### ① ST+AP 动态评级")
    if use_dynamic:
        from src.opponent_rating import get_opponent_scorecard, load_elo_history
        from src.csl_context import load_csl_data
        try:
            elo = load_elo_history()
            all_matches, _, _ = load_csl_data()
            card = get_opponent_scorecard(opp, target_match["date"], elo_history=elo,
                                           standings_by_round=standings, matches=all_matches)
            tier = card["tier"]
            st_sub = card["components"]["ST_sub"]
            ap_sub = card["components"]["AP_sub"]
            hpct = ap_sub['HIST_ATT_pct']; perf = ap_sub['PERF']
            derby = ap_sub['DERBY_bonus']; elo_n = st_sub['ELO_norm']
            ppg = st_sub['PPG']; l5 = st_sub['L5_PPG']
            st_val = card["ST"]; ap_val = card["AP"]

            col1, col2, col3 = st.columns([2, 2, 1])
            with col1:
                st.caption(f"**ST 实力分 {st_val:.0f}**")
                st.caption(f"ELO={elo_n:.0f} | 场均积分={ppg:.2f} | 近5场={l5:.2f}")
            with col2:
                st.caption(f"**AP 吸引力 {ap_val:.0f}**")
                st.caption(f"票房排位={hpct:.0f}% | 联赛分位={perf:.0f} | 德比加分={derby:.0f}")
            with col3:
                tc = {"S":"#ff6b6b","A":"#f0c040","B":"#8a8f98","C":"#51cf66"}.get(tier,"#8a8f98")
                st.markdown(f'<div style="text-align:center;padding-top:10px"><span style="font-size:1.4rem;font-weight:590;color:{tc}">{tier}</span><br><span style="font-size:0.6rem;color:#62666d">动态分级</span></div>', unsafe_allow_html=True)
            
            # 判定原因
            st_desc = f"ELO分位{elo_n:.0f}"
            if ppg >= 1.8: st_desc += f"，场均{ppg:.1f}分(强)"
            elif ppg >= 1.2: st_desc += f"，场均{ppg:.1f}分(中)"
            else: st_desc += f"，场均{ppg:.1f}分(弱)"
            if l5 >= 2.0: st_desc += f"，近5场{l5:.1f}分(状态火热)"
            elif l5 >= 1.2: st_desc += f"，近5场{l5:.1f}分(状态平稳)"
            else: st_desc += f"，近5场{l5:.1f}分(状态低迷)"
            ap_desc = f"历史票房排位{hpct:.0f}%"
            if perf >= 70: ap_desc += f"，联赛排名靠前(分位{perf:.0f})"
            elif perf >= 40: ap_desc += f"，联赛中上游(分位{perf:.0f})"
            elif perf >= 20: ap_desc += f"，联赛中下游(分位{perf:.0f})"
            else: ap_desc += f"，联赛下游(分位{perf:.0f})"
            if derby > 0: ap_desc += f"，德比加分{derby:.0f}"
            if st_val >= 80 and ap_val >= 70: reason = f"S级：实力顶尖且票房号召力极强"
            elif hpct >= 90: reason = f"A级：历史票房分位{hpct:.0f}%≥90%，德比级热度"
            elif st_val >= 55 and ap_val >= 40: reason = f"A级：实力较强(ST={st_val:.0f}≥55)且票房达标(AP={ap_val:.0f}≥40)"
            elif hpct >= 55 and st_val >= 45: reason = f"A级：老牌强队(票房{hpct:.0f}%≥55%，ST={st_val:.0f}≥45)"
            elif hpct >= 80: reason = f"B级：历史票房{hpct:.0f}%≥80%，热度保护"
            elif ap_val >= 35 and st_val >= 20: reason = f"B级：吸引力较高(AP={ap_val:.0f}≥35)"
            elif st_val < 35: reason = f"C级：实力不足(ST={st_val:.0f}<35)"
            elif ap_val < 25: reason = f"C级：票房号召力不足(AP={ap_val:.0f}<25)"
            else: reason = f"B级：实力中等，票房一般，未触及A/C边界"
            st.caption(f"{st_desc}")
            st.caption(f"{ap_desc}")
            st.caption(f"→ {reason}")
        except Exception:
            tier = classify_opponent_tier(opp)
            st.warning("动态评分暂不可用，使用静态分级")
    else:
        tier = classify_opponent_tier(opp)
    
    # ── ② 分级基值 ──
    base = TIER_BASE.get(tier, 9000)
    st.markdown("#### ② 分级基值")
    st.caption(f"{tier}级基准上座 = **{base:,}** 张  |  S={TIER_BASE['S']:,}  A={TIER_BASE['A']:,}  B={TIER_BASE['B']:,}  C={TIER_BASE['C']:,}")

    # ── ③ 命中规则 ──
    st.markdown("#### ③ 命中规则")
    rules_triggered, _, _ = build_rules_triggered(target_match, ctx, guoan_matches, use_dynamic)
    final_mult = 1.0
    rule_lines = ""
    for name, label, mult, desc in rules_triggered:
        final_mult *= mult
        color = "#ff6b6b" if mult > 1.01 else "#51cf66" if mult < 0.99 else "#8a8f98"
        sign = "×" if mult >= 1 else ""
        rule_lines += f'<tr><td style="color:#f7f8f8">{label}</td><td style="color:{color};font-family:JetBrains Mono">{sign}{mult:.2f}</td><td style="color:#8a8f98;font-size:0.7rem">{desc}</td></tr>'
    if rule_lines:
        st.markdown(f"""<table class="compact-table" style="max-width:500px">
          <thead><tr><th>规则</th><th>乘数</th><th>说明</th></tr></thead>
          <tbody>{rule_lines}</tbody>
        </table>""", unsafe_allow_html=True)
    else:
        st.caption("无特殊规则命中，使用基值预测")
    final_mult = max(final_mult, PENALTY_FLOOR)

    # ── ④ 预测上座 ──
    raw_pred = min(base * final_mult, 20000)
    st.markdown("#### ④ 预测上座")
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        st.metric("预测上座", f"{raw_pred:,.0f} 张", delta=f"MAE ±{mae:.0f}张", delta_color="off")
    with col_p2:
        st.caption(f"计算：{base:,} × {final_mult:.2f} = {raw_pred:,.0f}")

    # ── ⑤ 库存+份额模型 ──
    st.markdown("#### ⑤ 库存+份额模型")
    pred_args = build_pred_args(target_match, ctx)
    optimizer = get_optimizer()
    r = optimizer.optimize(opp, match_date=target_match["date"], strategy="auto", **pred_args)
    
    inv_rows = ""
    for zt in ZONE_TIERS:
        tr = r.tiers[zt]
        share = tr.base_qty / max(r.base_attendance, 1) * 100
        inv_rows += (
            f"<tr>"
            f"<td style='font-weight:510'>{zt}</td>"
            f"<td>¥{tr.base_price:,.0f}</td>"
            f"<td style='font-family:JetBrains Mono'>{tr.capacity:,.0f}座</td>"
            f"<td style='font-family:JetBrains Mono'>{tr.base_qty:,.0f}张</td>"
            f"<td style='color:#8a8f98'>{share:.1f}%</td>"
            f"</tr>"
        )
    inv_rows += (
        f'<tr style="border-top:1px solid rgba(255,255,255,0.08);font-weight:510">'
        f'<td>合计</td><td>—</td>'
        f'<td style="font-family:JetBrains Mono">{r.total_capacity:,.0f}座</td>'
        f'<td style="font-family:JetBrains Mono">{r.base_attendance:,.0f}张</td>'
        f'<td>100%</td></tr>'
    )
    st.markdown(f"""<table class="compact-table" style="max-width:550px;font-size:0.72rem">
      <thead><tr><th>档位</th><th>基准价</th><th>容量</th><th>基准量</th><th>份额</th></tr></thead>
      <tbody>{inv_rows}</tbody>
    </table>""", unsafe_allow_html=True)

    # ── ⑥ 动态定价建议 ──
    st.markdown("#### ⑥ 动态定价建议")
    
    rw, aw = r.revenue_weight, r.attendance_weight
    if rw >= 0.7: strat_label = "收入优先"
    elif rw <= 0.3: strat_label = "上座优先"
    else: strat_label = "均衡优化"
    
    price_rows = ""
    for zt in ZONE_TIERS:
        tr = r.tiers[zt]
        dp = (tr.optimal_price / tr.base_price - 1) * 100 if tr.base_price > 0 else 0
        dp_c = "#ff6b6b" if dp > 0.5 else "#51cf66" if dp < -0.5 else "#8a8f98"
        dp_s = f'{dp:+.0f}%' if abs(dp) > 1 else '—'
        qd = tr.predicted_qty - tr.base_qty
        qd_c = "#ff6b6b" if qd > 0 else "#51cf66" if qd < 0 else "#8a8f98"
        rd = tr.revenue - (tr.base_price * tr.base_qty)
        rd_c = "#ff6b6b" if rd > 0 else "#51cf66" if rd < 0 else "#8a8f98"
        lock = " 🔒" if tr.is_frozen else ""
        price_rows += (
            f"<tr>"
            f"<td style='font-weight:510'>{zt}{lock}</td>"
            f"<td style='font-family:JetBrains Mono'>¥{tr.optimal_price:,.0f}</td>"
            f"<td style='color:{dp_c}'>{dp_s}</td>"
            f"<td style='font-family:JetBrains Mono'>{tr.predicted_qty:,.0f}</td>"
            f"<td style='color:{qd_c};font-family:JetBrains Mono'>{qd:+,.0f}</td>"
            f"<td style='font-family:JetBrains Mono'>¥{tr.revenue/10000:.1f}万</td>"
            f"<td style='color:{rd_c};font-family:JetBrains Mono'>¥{rd/10000:+.1f}万</td>"
            f"</tr>"
        )
    
    total_qd = r.total_attendance - r.base_attendance
    total_rd = r.total_revenue - r.base_revenue
    tqd_c = "#ff6b6b" if total_qd > 0 else "#51cf66"
    trd_c = "#ff6b6b" if total_rd > 0 else "#51cf66"
    price_rows += (
        f'<tr style="border-top:1px solid rgba(255,255,255,0.08);font-weight:510">'
        f'<td>合计</td><td>—</td><td>—</td>'
        f'<td style="font-family:JetBrains Mono">{r.total_attendance:,.0f}</td>'
        f'<td style="color:{tqd_c};font-family:JetBrains Mono">{total_qd:+,.0f}</td>'
        f'<td style="font-family:JetBrains Mono">¥{r.total_revenue/10000:.1f}万</td>'
        f'<td style="color:{trd_c};font-family:JetBrains Mono">¥{total_rd/10000:+.1f}万</td>'
        f'</tr>'
    )
    
    st.caption(f"策略：**{strat_label}**（收入权重{rw:.0%} · 上座权重{aw:.0%}）")
    st.markdown(f"""<table class="history-table" style="font-size:0.7rem">
      <thead><tr><th>档位</th><th>优化价</th><th>Δ价</th><th>场景量</th><th>Δ量</th><th>收入</th><th>Δ收入</th></tr></thead>
      <tbody>{price_rows}</tbody>
    </table>""", unsafe_allow_html=True)
    st.caption("情景推演未经验证 · 实际定价请结合实时预售数据")

    return raw_pred, r