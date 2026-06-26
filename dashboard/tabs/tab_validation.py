"""Tab: 模型验证。"""
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard.common.data_cache import _get_csl_parquet, get_optimizer
from src.classify import classify_opponent_tier
from src.pricing_v5 import ZONE_TIERS, build_price_matrix

ROOT = Path(__file__).resolve().parent.parent.parent

def render_validation_tab(home_preds, guoan_matches, all_matches):
    """策略验证：仅追踪已确认定价 + 已出实际数据的比赛。
    驱动源: pricing_decisions.json + parquet 实际销量。
    前面的比赛模型未参与决策，不纳入验证。
    """
    
    # -- H2 Experiment Matrix --
    st.divider()
    st.markdown("**H2 定价实验矩阵**")
    exp_data = [
        {"date":"2026-06-27","opponent":"武汉三镇","tier":"B->C","group":"事后对照","t1":"—","t2":"—","t3":"—","status":"已赛"},
        {"date":"2026-07-04","opponent":"山东泰山","tier":"A->A","group":"德比弹性","t1":260,"t2":374,"t3":484,"status":"待武汉数据"},
        {"date":"2026-07-17","opponent":"辽宁铁人","tier":"C->B","group":"升级发现","t1":160,"t2":220,"t3":300,"status":"已确认"},
        {"date":"2026-08-07","opponent":"深圳新鹏城","tier":"B->C","group":"降级发现","t1":126,"t2":180,"t3":280,"status":"已确认"},
        {"date":"2026-08-01","opponent":"浙江","tier":"B->B","group":"对照","t1":160,"t2":220,"t3":300,"status":"已确认"},
        {"date":"2026-08-22","opponent":"云南玉昆","tier":"B->B","group":"对照","t1":160,"t2":220,"t3":300,"status":"已确认"},
        {"date":"2026-10-18","opponent":"青岛西海岸","tier":"B->C","group":"降级验证","t1":126,"t2":180,"t3":280,"status":"已确认"},
        {"date":"2026-11-08","opponent":"重庆铜梁龙","tier":"C->B","group":"升级验证","t1":160,"t2":220,"t3":300,"status":"已确认"},
    ]
    st.dataframe(pd.DataFrame(exp_data), use_container_width=True, hide_index=True)
    st.divider()
st.markdown("**策略验证 · 赛后追踪**")
    st.caption("仅显示你确认了定价决策的场次。实际数据出来后自动计算策略贡献。")

    # 加载定价决策
    decision_file = ROOT / 'data' / 'processed' / 'pricing_decisions.json'
    if not decision_file.exists():
        st.info("暂无定价决策记录。在 Tab 1 中为比赛确认定价后，这里会出现。")
        return

    with open(decision_file) as f:
        decisions_data = json.load(f)
    decisions = decisions_data.get('decisions', [])
    if not decisions:
        st.info("暂无定价决策。")
        return

    csl = _get_csl_parquet()
    pm = build_price_matrix()
    optimizer = get_optimizer()
    ZT = ZONE_TIERS

    records = []
    pending = []

    for d in decisions:
        match_date = d['match']['date']
        opp = d['match']['opponent']
        confirmed_prices = d['prices']
        note = d.get('note', '')
        ts = d.get('timestamp', '')

        tier = classify_opponent_tier(opp)
        pt = get_pricing_tier(opp)
        baseline_prices = {zt: int(pm[pt][zt]) for zt in ZT}
        confirmed = {zt: int(confirmed_prices.get(zt, baseline_prices.get(zt, 0))) for zt in ZT}

        # 尝试匹配 parquet 实际数据
        actual_match = None
        if csl is not None:
            for mid in csl['match_id'].unique():
                md = csl[csl['match_id'] == mid]
                if str(md['match_date'].iloc[0])[:10] == match_date:
                    actual_match = md
                    break

        if actual_match is None:
            # 还没出实际数据
            pending.append({'date': match_date, 'opponent': opp, 'tier': tier,
                           'confirmed': confirmed, 'baseline': baseline_prices, 'note': note})
            continue

        # 有实际数据：计算验证指标
        actual_qty = int(actual_match['数量'].sum())
        actual_rev = float(actual_match['实际支付价格'].sum())

        # 从快照取预测值（如果存在）
        snap_path = ROOT / 'data' / 'snapshots' / f'pre_{match_date}_{opp}.json'
        pred_qty = None
        if snap_path.exists():
            with open(snap_path) as f:
                snap = json.load(f)
            pred_qty = snap.get('prediction', {}).get('predicted_quantity')

        # 如果没有快照，用当前模型重跑
        if pred_qty is None:
            from src.csl_context import predict_with_context
            pred_qty = predict_with_context(opp, match_date)

        # 分档位反事实：如果按基准价卖
        from src.pricing_v5 import get_zone_sections
        year = match_date[:4]
        zm = {str(s): zt for zt, secs in get_zone_sections(year).items() for s in secs}
        cf_rev = 0.0
        for zt in ZT:
            bp = baseline_prices.get(zt, 0)
            cp = confirmed.get(zt, bp)
            if bp <= 0:
                continue
            # 获取该档位实际数据
            zone_md = actual_match.copy()
            zone_md['zt'] = zone_md['section'].astype(str).map(zm)
            zmd = zone_md[zone_md['zt'] == zt]
            aq = int(zmd['数量'].sum())
            ar = float(zmd['实际支付价格'].sum())
            if aq > 0:
                ap = ar / aq
                ep = optimizer.elasticity.get(tier, {}).get(zt, 0.25)
                # 反事实：按基准价卖
                cf_q = aq * ((ap / bp) ** ep) if ap > 0 else aq
                cf_q = min(cf_q, optimizer.capacities.get(zt, 9999))
                cf_rev += cf_q * bp

        strategy_delta = actual_rev - cf_rev

        # 判断是否有实际调价（确认价 vs 基准价）
        has_adjustment = any(abs(confirmed[zt] - baseline_prices.get(zt, 0)) > 5 for zt in ZT)

        records.append({
            'date': match_date, 'opponent': opp, 'tier': tier,
            'pred_qty': int(pred_qty), 'actual_qty': actual_qty,
            'actual_rev': actual_rev, 'cf_rev': cf_rev,
            'strategy_delta': strategy_delta,
            'confirmed': confirmed, 'baseline': baseline_prices,
            'has_adjustment': has_adjustment, 'note': note, 'ts': ts,
        })

    # ══ KPI 卡片 ══
    if records:
        total_actual_rev = sum(r['actual_rev'] for r in records)
        total_cf_rev = sum(r['cf_rev'] for r in records)
        total_delta = total_actual_rev - total_cf_rev
        pred_errs = [abs(r['pred_qty'] - r['actual_qty']) for r in records]
        mae = np.mean(pred_errs)
        mape = np.mean([e / r['actual_qty'] * 100 for e, r in zip(pred_errs, records)]) if records else 0
        has_adj = [r for r in records if r['has_adjustment']]
        positive = sum(1 for r in has_adj if r['strategy_delta'] > 0)

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(f"""<div class="kpi-card">
              <div class="kpi-label">策略追踪场次</div>
              <div class="kpi-value">{len(records)}场</div>
              <div style="font-size:0.7rem;color:#8a8f98">预测 MAE {mae:,.0f}张</div>
            </div>""", unsafe_allow_html=True)
        with c2:
            st.markdown(f"""<div class="kpi-card">
              <div class="kpi-label">实际调价场次</div>
              <div class="kpi-value">{len(has_adj)}场</div>
              <div style="font-size:0.7rem;color:#8a8f98">确认价≠基准价</div>
            </div>""", unsafe_allow_html=True)
        with c3:
            delta_color = "#ff6b6b" if total_delta > 0 else "#51cf66"
            st.markdown(f"""<div class="kpi-card">
              <div class="kpi-label">策略净贡献</div>
              <div class="kpi-value" style="color:{delta_color}">¥{total_delta/1e4:+.1f}万</div>
              <div style="font-size:0.7rem;color:#8a8f98">vs 基准价反事实</div>
            </div>""", unsafe_allow_html=True)
        with c4:
            st.markdown(f"""<div class="kpi-card">
              <div class="kpi-label">增收场次</div>
              <div class="kpi-value">{positive}/{len(has_adj) if has_adj else 1}</div>
              <div style="font-size:0.7rem;color:#8a8f98">调价后增收占比</div>
            </div>""", unsafe_allow_html=True)

        # ══ 逐场验证表 ══
        st.divider()
        st.markdown("**已完成验证**")

        rows = ""
        for r in records:
            err = r['pred_qty'] - r['actual_qty']
            err_pct = err / r['actual_qty'] * 100 if r['actual_qty'] > 0 else 0
            err_color = "#ff6b6b" if err > 0 else "#51cf66"
            delta_color = "#ff6b6b" if r['strategy_delta'] > 0 else "#51cf66"
            # 确认价 vs 基准价 摘要
            price_changes = []
            for zt in ZT:
                cp = r['confirmed'].get(zt, 0)
                bp = r['baseline'].get(zt, 0)
                if abs(cp - bp) > 5:
                    price_changes.append(f"{zt}{'↑' if cp > bp else '↓'}¥{abs(cp-bp)}")
            change_str = " · ".join(price_changes) if price_changes else "未调价"
            if not r['has_adjustment']:
                change_str = "—"

            rows += (
                f'<tr>'
                f'<td style="font-size:0.75rem;color:#8a8f98">{r["date"][5:]}</td>'
                f'<td style="font-weight:510">{r["opponent"]}</td>'
                f'<td>{r["tier"]}</td>'
                f'<td>{r["pred_qty"]:,}</td>'
                f'<td>{r["actual_qty"]:,}</td>'
                f'<td style="color:{err_color}">{err:+d} ({err_pct:+.1f}%)</td>'
                f'<td>{change_str}</td>'
                f'<td style="color:{delta_color}">¥{r["strategy_delta"]/1e4:+.1f}万</td>'
                f'</tr>'
            )

        st.markdown(f"""<table class="compact-table">
          <thead><tr>
            <th>日期</th><th>对手</th><th>级别</th>
            <th>预测</th><th>实际</th><th>预测偏差</th>
            <th>调价</th><th>策略贡献</th>
          </tr></thead>
          <tbody>{rows}</tbody>
        </table>""", unsafe_allow_html=True)

        st.caption("策略贡献 = 实际收入 - 反事实收入（同销量按基准价卖）。调价列显示实际执行的价差。")
    else:
        st.info("所有已确认场次均待赛后验证。")

    # ══ 待验证 ══
    if pending:
        st.divider()
        st.markdown("**待赛后验证**")
        pending_rows = ""
        for p in pending:
            changes = []
            for zt in ZT:
                cp = p['confirmed'].get(zt, 0)
                bp = p['baseline'].get(zt, 0)
                if abs(cp - bp) > 5:
                    changes.append(f"{zt} ¥{bp}→¥{cp}")
            change_str = " · ".join(changes) if changes else "采用基准价"
            pending_rows += (
                f'<tr>'
                f'<td>{p["date"]}</td><td style="font-weight:510">{p["opponent"]}</td>'
                f'<td>{p["tier"]}</td><td>{change_str}</td>'
                f'<td style="color:#8a8f98">{p.get("note","")}</td>'
                f'</tr>'
            )
        st.markdown(f"""<table class="compact-table">
          <thead><tr><th>日期</th><th>对手</th><th>级别</th><th>确认价调整</th><th>备注</th></tr></thead>
          <tbody>{pending_rows}</tbody>
        </table>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════
