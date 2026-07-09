"""Tab: 模型验证。"""
import numpy as np
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard.common.data_cache import _get_csl_parquet, get_optimizer
from src.classify import classify_opponent_tier as static_tier
from src.opponent_rating import get_opponent_scorecard, load_elo_history
from dashboard.components.ctx_builder import build_pred_args
from dashboard.common.data_cache import get_ctx_rounds as _ctx_rounds

def get_dynamic_tier(opp, date):
    try:
        elo = load_elo_history()
        from src.csl_context import load_csl_data
        matches, standings, _ = load_csl_data()
        card = get_opponent_scorecard(opp, date, elo_history=elo, standings_by_round=standings, matches=matches)
        return card["tier"]
    except:
        return static_tier(opp)
from src.pricing_v5 import ZONE_TIERS, build_price_matrix, get_pricing_tier

ROOT = Path(__file__).resolve().parent.parent.parent

def render_validation_tab(home_preds, guoan_matches, all_matches):
    """策略验证：仅追踪已确认定价 + 已出实际数据的比赛。
    驱动源: pricing_decisions.json + parquet 实际销量。
    前面的比赛模型未参与决策，不纳入验证。
    """
    
    # -- H2 Experiment Matrix --
    st.divider()
    st.markdown("**H2 定价实验矩阵**")
    
    # Load pricing decisions for past matches
    decision_file = ROOT / 'data' / 'processed' / 'pricing_decisions.json'
    decision_prices = {}
    if decision_file.exists():
        with open(decision_file) as f:
            dd = json.load(f)
        for d in dd.get('decisions', []):
            key = f"{d['match']['date']}_{d['match']['opponent']}"
            decision_prices[key] = d.get('prices', {})
    
    # Future match plan (hardcoded targets)
    future_plan = [
        {"date":"2026-07-17","opponent":"辽宁铁人","tier":"C->B","group":"升级发现","t1":160,"t2":220,"t3":300,"status":"已确认"},
        {"date":"2026-08-01","opponent":"浙江","tier":"B->B","group":"对照","t1":160,"t2":220,"t3":300,"status":"已确认"},
        {"date":"2026-08-07","opponent":"深圳新鹏城","tier":"B->C","group":"降级发现","t1":126,"t2":180,"t3":280,"status":"已确认"},
        {"date":"2026-10-18","opponent":"青岛西海岸","tier":"B->C","group":"降级验证","t1":126,"t2":180,"t3":280,"status":"已确认"},
        {"date":"2026-11-08","opponent":"重庆铜梁龙","tier":"C->B","group":"升级验证","t1":160,"t2":220,"t3":300,"status":"已确认"},
    ]
    
    # Past matches: read actual pricing from decisions
    past_matches = [
        {"date":"2026-06-27","opponent":"武汉三镇","tier":"B->C","group":"事后对照","status":"已赛"},
        {"date":"2026-07-04","opponent":"山东泰山","tier":"A->A","group":"德比弹性","status":"已赛"},
    ]
    
    exp_data = []
    for pm in past_matches:
        key = f"{pm['date']}_{pm['opponent']}"
        prices = decision_prices.get(key, {})
        row = dict(pm)
        for zt in ['T1','T2','T3','T4','T5','T6']:
            row[zt.lower()] = prices.get(zt) if prices.get(zt) else None
        exp_data.append(row)
    for fm in future_plan:
        exp_data.append(fm)
    
    st.dataframe(pd.DataFrame(exp_data), use_container_width=True, hide_index=True)
    st.divider()
    st.markdown("**策略验证 · 赛后追踪**")
    st.caption("反事实分解：分级效应 + 调价效应 = 总策略贡献。票面收入口径。")

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
    ZT = ZONE_TIERS

    # Import face revenue function
    from dashboard.common.data_cache import _get_zone_face_revenue, _get_zone_qtys

    records = []
    pending = []

    for d in decisions:
        match_date = d['match']['date']
        opp = d['match']['opponent']
        confirmed_prices = d['prices']
        note = d.get('note', '')
        ts = d.get('timestamp', '')

        static = static_tier(opp)
        dynamic = get_dynamic_tier(opp, match_date)
        tier_label = f"{static}->{dynamic}"
        pt = get_pricing_tier(opp, match_date=match_date)
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
            pending.append({'date': match_date, 'opponent': opp, 'tier': tier_label,
                           'confirmed': confirmed, 'baseline': baseline_prices, 'note': note})
            continue

        # ── 有实际数据：反事实分解（山东复盘方法论）──
        actual_qty = int(actual_match['数量'].sum())
        
        # 票面收入（面值×销量），与预测收入口径一致
        face_rev_dict = _get_zone_face_revenue({'date': match_date, 'opponent': opp})
        actual_rev = sum(face_rev_dict.values())
        
        # 分档位实际销量
        zone_qty = _get_zone_qtys({'date': match_date, 'opponent': opp})

        # 从快照取预测值
        snap_path = ROOT / 'data' / 'snapshots' / f'pre_{match_date}_{opp}.json'
        pred_qty = None
        if snap_path.exists():
            with open(snap_path) as f:
                snap = json.load(f)
            pred_qty = snap.get('prediction', {}).get('predicted_quantity')

        if pred_qty is None:
            from src.rule_engine import predict as raw_predict
            pred_qty = raw_predict(opp, opponent_tier_override=dynamic, 
                                   derby=opp in ["上海申花","山东泰山"], 
                                   saturday=pd.Timestamp(match_date).weekday()==5,
                                   midweek=pd.Timestamp(match_date).weekday() in (1,2,3),
                                   summer=pd.Timestamp(match_date).month in (7,8),
                                   match_year=match_date[:4])

        # ── 反事实对比（同对手份额 × 基准价，透明计算）──
        # 加载快照数据
        snap_data_cf = {}
        snap_path_cf = ROOT / 'data' / 'snapshots' / f'pre_{match_date}_{opp}.json'
        if snap_path_cf.exists():
            with open(snap_path_cf) as f:
                snap_data_cf = json.load(f)
        
        # 步骤1: 获取同对手2025份额（无则用级别基线）
        from src.dynamic_optimizer import DynamicPricingOptimizer
        _tmp_opt = DynamicPricingOptimizer.__new__(DynamicPricingOptimizer)
        _tmp_opt._opponent_share_baseline = {
            "成都蓉城": {"T1":0.225,"T2":0.262,"T3":0.349,"T4":0.102,"T5":0.053,"T6":0.008},
            "山东泰山": {"T1":0.262,"T2":0.294,"T3":0.294,"T4":0.054,"T5":0.084,"T6":0.010},
            "浙江俱乐部绿城": {"T1":0.352,"T2":0.233,"T3":0.297,"T4":0.019,"T5":0.090,"T6":0.008},
            "浙江": {"T1":0.352,"T2":0.233,"T3":0.297,"T4":0.019,"T5":0.090,"T6":0.008},
            "河南俱乐部酒祖杜康": {"T1":0.378,"T2":0.222,"T3":0.301,"T4":0.015,"T5":0.078,"T6":0.005},
            "河南": {"T1":0.378,"T2":0.222,"T3":0.301,"T4":0.015,"T5":0.078,"T6":0.005},
            "河南队": {"T1":0.378,"T2":0.222,"T3":0.301,"T4":0.015,"T5":0.078,"T6":0.005},
            "深圳新鹏城": {"T1":0.292,"T2":0.278,"T3":0.286,"T4":0.020,"T5":0.116,"T6":0.008},
            "长春亚泰": {"T1":0.281,"T2":0.279,"T3":0.303,"T4":0.018,"T5":0.111,"T6":0.008},
            "青岛西海岸": {"T1":0.485,"T2":0.122,"T3":0.271,"T4":0.012,"T5":0.101,"T6":0.009},
            "上海申花": {"T1":0.227,"T2":0.308,"T3":0.344,"T4":0.016,"T5":0.100,"T6":0.005},
            "天津津门虎": {"T1":0.221,"T2":0.269,"T3":0.324,"T4":0.049,"T5":0.127,"T6":0.010},
            "武汉三镇": {"T1":0.362,"T2":0.204,"T3":0.308,"T4":0.012,"T5":0.109,"T6":0.005},
            "上海海港": {"T1":0.424,"T2":0.176,"T3":0.271,"T4":0.026,"T5":0.095,"T6":0.007},
            "大连英博海发": {"T1":0.551,"T2":0.091,"T3":0.241,"T4":0.010,"T5":0.102,"T6":0.006},
            "大连英博": {"T1":0.551,"T2":0.091,"T3":0.241,"T4":0.010,"T5":0.102,"T6":0.006},
            "青岛海牛": {"T1":0.518,"T2":0.095,"T3":0.259,"T4":0.011,"T5":0.112,"T6":0.005},
            "梅州客家": {"T1":0.469,"T2":0.174,"T3":0.255,"T4":0.010,"T5":0.087,"T6":0.005},
        }
        _tmp_opt._tier_share_baseline = {"A":{"T1":0.35,"T2":0.22,"T3":0.27,"T4":0.09,"T5":0.065,"T6":0.005}}
        opponent_share = _tmp_opt._opponent_share_baseline.get(opp)
        if opponent_share:
            cf_shares = opponent_share
        else:
            cf_shares = _tmp_opt._tier_share_baseline.get(dynamic, {"T1":0.5,"T2":0.12,"T3":0.25,"T4":0.02,"T5":0.095,"T6":0.006})
        
        # 步骤2: 优先用快照基准预测量，无快照时用规则引擎
        snap_baseline_qty = snap_data_cf.get('baseline', {}).get('predicted_quantity')
        if snap_baseline_qty:
            cf_total_qty = snap_baseline_qty
        else:
            from src.rule_engine import predict as raw_predict
            cf_total_qty = raw_predict(opp, opponent_tier_override=dynamic,
                                        derby=opp in ["上海申花","山东泰山"],
                                        saturday=pd.Timestamp(match_date).weekday()==5,
                                        midweek=pd.Timestamp(match_date).weekday() in (1,2,3),
                                        summer=pd.Timestamp(match_date).month in (7,8),
                                        match_year=match_date[:4])
        
        # 步骤3: 反事实 = Σ(预测总量 × 份额 × 基准价)
        cf_baseline_rev = 0.0
        cf_baseline_qty = 0.0
        for zt in ZT:
            bp = baseline_prices.get(zt, 0)
            cf_q = cf_total_qty * cf_shares.get(zt, 0.1)
            cf_baseline_rev += bp * cf_q
            cf_baseline_qty += cf_q
        
        # 策略贡献 = 实际票面收入 - 反事实收入
        total_strategy = actual_rev - cf_baseline_rev
        price_effect = total_strategy

        has_adjustment = any(abs(confirmed[zt] - baseline_prices.get(zt, 0)) > 5 for zt in ZT)

        # ── 效应分解（标准回测流程）──
        # 加载快照基准数据
        snap_baseline_qtys = {}
        snap_path_decomp = ROOT / 'data' / 'snapshots' / f'pre_{match_date}_{opp}.json'
        if snap_path_decomp.exists():
            with open(snap_path_decomp) as f:
                sd = json.load(f)
            snap_baseline_qtys = sd.get('baseline', {}).get('base_qtys', {})
        
        # 赛后更新动态弹性表
        from src.pricing_v5 import update_elasticity_from_match
        update_elasticity_from_match(
            match_date, opp, pt,
            confirmed, baseline_prices,
            zone_qty, snap_baseline_qtys
        )
        
        # 调价效应: Σ(实际销量 × (确认价 - 基准价))
        price_eff = 0.0
        price_eff_detail = {}
        for zt in ZT:
            bp = baseline_prices.get(zt, 0)
            cp = confirmed.get(zt, bp)
            aq_z = zone_qty.get(zt, 0)
            pe_z = aq_z * (cp - bp)
            price_eff += pe_z
            price_eff_detail[zt] = int(pe_z)
        
        # 库存效应: Σ((实际销量 - 基准预测量) × 基准价)
        inv_eff = 0.0
        inv_eff_detail = {}
        for zt in ZT:
            bp = baseline_prices.get(zt, 0)
            aq_z = zone_qty.get(zt, 0)
            bq_z = snap_baseline_qtys.get(zt, aq_z) if snap_baseline_qtys else aq_z
            ie_z = (aq_z - bq_z) * bp
            inv_eff += ie_z
            inv_eff_detail[zt] = int(ie_z)
        
        # 总效应 = 调价 + 库存
        total_eff = price_eff + inv_eff

        records.append({
            'date': match_date, 'opponent': opp, 'tier': tier_label,
            'pred_qty': int(pred_qty), 'actual_qty': actual_qty,
            'actual_rev': actual_rev, 
            'cf_baseline_rev': cf_baseline_rev,
            'cf_baseline_qty': cf_baseline_qty,
            'strategy_contribution': total_strategy,
            'price_effect': price_eff,
            'inv_effect': inv_eff,
            'total_effect': total_eff,
            'price_eff_detail': price_eff_detail,
            'inv_eff_detail': inv_eff_detail,
            'confirmed': confirmed, 'baseline': baseline_prices,
            'has_adjustment': has_adjustment, 'note': note, 'ts': ts,
        })

        # ══ KPI 卡片 ══
    if records:
        total_actual_rev = sum(r['actual_rev'] for r in records)
        total_baseline_rev = sum(r['cf_baseline_rev'] for r in records)
        total_strategy = sum(r['strategy_contribution'] for r in records)
        pred_errs = [abs(r['pred_qty'] - r['actual_qty']) for r in records]
        mae = np.mean(pred_errs)
        has_adj = [r for r in records if r['has_adjustment']]
        positive = sum(1 for r in has_adj if r['strategy_contribution'] > 0)

        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f"""<div class="kpi-card">
              <div class="kpi-label">已追踪场次</div>
              <div class="kpi-value">{len(records)}场</div>
              <div style="font-size:0.7rem;color:#8a8f98">预测 MAE {mae:,.0f}张 · {len(has_adj)}场调价</div>
            </div>""", unsafe_allow_html=True)
        with c2:
            delta_color = "#ff6b6b" if total_strategy > 0 else "#51cf66"
            st.markdown(f"""<div class="kpi-card">
              <div class="kpi-label">策略净贡献</div>
              <div class="kpi-value" style="color:{delta_color}">¥{total_strategy/1e4:+.1f}万</div>
              <div style="font-size:0.7rem;color:#8a8f98">实际 vs 弹性反事实</div>
            </div>""", unsafe_allow_html=True)
        with c3:
            st.markdown(f"""<div class="kpi-card">
              <div class="kpi-label">增收场次</div>
              <div class="kpi-value">{positive}/{len(has_adj) if has_adj else 1}</div>
              <div style="font-size:0.7rem;color:#8a8f98">调价后增收占比</div>
            </div>""", unsafe_allow_html=True)

        # ══ 逐场回测卡片（标准流程）══
        st.divider()
        st.markdown("**赛后追踪 · 回测卡片**")
        st.caption("标准回测流程：效应分解 = 调价效应 + 库存效应。基准预测量来自快照基线。")

        for r in records:
            err = r['pred_qty'] - r['actual_qty']
            err_pct = err / r['actual_qty'] * 100 if r['actual_qty'] > 0 else 0
            err_color = "#ff6b6b" if err > 0 else "#51cf66"
            
            # Load snapshot
            snap_path_r = ROOT / 'data' / 'snapshots' / f'pre_{r["date"]}_{r["opponent"]}.json'
            snap_data = {}
            if snap_path_r.exists():
                with open(snap_path_r) as f:
                    snap_data = json.load(f)
            
            pe = r.get('price_effect', 0)
            ie = r.get('inv_effect', 0)
            te = r.get('total_effect', 0)
            pe_pct = abs(pe) / max(abs(pe) + abs(ie), 1) * 100
            ie_pct = abs(ie) / max(abs(pe) + abs(ie), 1) * 100
            
            # ── Three-scenario table ──
            strategy_contrib = r.get('strategy_contribution', 0)
            pm_ts = snap_data.get('postmortem', {}).get('three_scenarios')
            scenario_html = ''
            if pm_ts:
                pred_s = pm_ts['prediction']
                act_s = pm_ts['actual']
                cf_s = pm_ts['counterfactual']
                scenario_html = (
                    '<table class="compact-table" style="font-size:0.65rem;margin:4px 0">'
                    '<thead><tr><th>场景</th><th>价格</th><th>库存</th><th>销量</th><th>收入</th><th>均价</th></tr></thead>'
                    '<tbody>'
                    f'<tr><td>{pred_s["label"]}</td><td>执行价</td><td>新</td><td>{pred_s["qty"]:,}</td><td>¥{pred_s["rev"]/1e4:.1f}万</td><td>¥{pred_s["avg_price"]}</td></tr>'
                    f'<tr><td>{act_s["label"]}</td><td>执行价</td><td>新</td><td>{act_s["qty"]:,}</td><td>¥{act_s["rev"]/1e4:.1f}万</td><td>¥{act_s["avg_price"]}</td></tr>'
                    f'<tr style="background:rgba(255,255,255,0.03)"><td><b>{cf_s["label"]}</b></td><td><b>S_A基价</b></td><td><b>原</b></td><td><b>{cf_s["qty"]:,}</b></td><td><b>¥{cf_s["rev"]/1e4:.1f}万</b></td><td><b>¥{cf_s["avg_price"]}</b></td></tr>'
                    '</tbody></table>'
                )
                strategy_contrib = pm_ts.get('strategy_contribution', strategy_contrib)
            
            # ── Compute opponent-share predicted quantities ──
            cf_shares = {}
            try:
                from src.dynamic_optimizer import DynamicPricingOptimizer
                _tmp_opt = DynamicPricingOptimizer.__new__(DynamicPricingOptimizer)
                _tmp_opt._opponent_share_baseline = {
                    "成都蓉城": {"T1":0.225,"T2":0.262,"T3":0.349,"T4":0.102,"T5":0.053,"T6":0.008},
                    "山东泰山": {"T1":0.262,"T2":0.294,"T3":0.294,"T4":0.054,"T5":0.084,"T6":0.010},
                    "浙江": {"T1":0.352,"T2":0.233,"T3":0.297,"T4":0.019,"T5":0.090,"T6":0.008},
                    "河南": {"T1":0.378,"T2":0.222,"T3":0.301,"T4":0.015,"T5":0.078,"T6":0.005},
                    "深圳新鹏城": {"T1":0.292,"T2":0.278,"T3":0.286,"T4":0.020,"T5":0.116,"T6":0.008},
                    "长春亚泰": {"T1":0.281,"T2":0.279,"T3":0.303,"T4":0.018,"T5":0.111,"T6":0.008},
                    "青岛西海岸": {"T1":0.485,"T2":0.122,"T3":0.271,"T4":0.012,"T5":0.101,"T6":0.009},
                    "上海申花": {"T1":0.227,"T2":0.308,"T3":0.344,"T4":0.016,"T5":0.100,"T6":0.005},
                    "天津津门虎": {"T1":0.221,"T2":0.269,"T3":0.324,"T4":0.049,"T5":0.127,"T6":0.010},
                    "武汉三镇": {"T1":0.362,"T2":0.204,"T3":0.308,"T4":0.012,"T5":0.109,"T6":0.005},
                    "上海海港": {"T1":0.424,"T2":0.176,"T3":0.271,"T4":0.026,"T5":0.095,"T6":0.007},
                    "大连英博海发": {"T1":0.551,"T2":0.091,"T3":0.241,"T4":0.010,"T5":0.102,"T6":0.006},
                    "大连英博": {"T1":0.551,"T2":0.091,"T3":0.241,"T4":0.010,"T5":0.102,"T6":0.006},
                    "青岛海牛": {"T1":0.518,"T2":0.095,"T3":0.259,"T4":0.011,"T5":0.112,"T6":0.005},
                    "梅州客家": {"T1":0.469,"T2":0.174,"T3":0.255,"T4":0.010,"T5":0.087,"T6":0.005},
                }
                cf_shares = _tmp_opt._opponent_share_baseline.get(r['opponent'], {})
            except:
                pass
            
            cf_total = snap_data.get('baseline', {}).get('predicted_quantity', r['pred_qty'])
            
            # ── Per-tier breakdown ──
            tier_rows = ""
            for zt in ZT:
                cp = r['confirmed'].get(zt, 0)
                bp = r['baseline'].get(zt, 0)
                aq = snap_data.get('actual', {}).get('quantities', {}).get(zt, 0)
                ar = snap_data.get('actual', {}).get('revenues', {}).get(zt, 0)
                # 预测量: 优先用同对手份额 × 基准总量
                if cf_shares:
                    bq = cf_total * cf_shares.get(zt, 0.1)
                else:
                    bq = snap_data.get('baseline', {}).get('base_qtys', {}).get(zt, 0)
                pe_z = r.get('price_eff_detail', {}).get(zt, 0)
                ie_z = r.get('inv_eff_detail', {}).get(zt, 0)
                
                p_diff = cp - bp
                pc = "#ff6b6b" if p_diff > 0 else "#51cf66" if p_diff < 0 else "#8a8f98"
                ps = f'+¥{p_diff}' if p_diff > 0 else (f'¥{p_diff}' if p_diff < 0 else '—')
                
                pe_c = "#ff6b6b" if pe_z > 0 else "#51cf66" if pe_z < 0 else "#8a8f98"
                ie_c = "#ff6b6b" if ie_z > 0 else "#51cf66" if ie_z < 0 else "#8a8f98"
                
                tier_rows += (
                    '<tr>'
                    f'<td style="font-weight:510">{zt}</td>'
                    f'<td>¥{bp:,.0f}</td>'
                    f'<td style="color:{pc}">¥{cp:,.0f} {ps}</td>'
                    f'<td>{bq:,.0f}</td>'
                    f'<td>{aq:,}</td>'
                    f'<td style="color:{pe_c}">¥{pe_z/1e4:+.1f}万</td>'
                    f'<td style="color:{ie_c}">¥{ie_z/1e4:+.1f}万</td>'
                    f'<td>¥{ar/1e4:.1f}万</td>'
                    '</tr>'
                )
            
            # ── Analysis ──
            analysis = []
            # 策略增量 (主): 实际 vs 反事实
            rev_delta = r['actual_rev'] - r['cf_baseline_rev']
            analysis.append(f'策略增量: 实际收入 ¥{r["actual_rev"]/1e4:.1f}万 vs 反事实 ¥{r["cf_baseline_rev"]/1e4:.1f}万 = ¥{rev_delta/1e4:+.1f}万')
            # 模型偏差 (辅): 预测 vs 实际
            if abs(err_pct) < 10:
                analysis.append(f'模型偏差: {abs(err_pct):.1f}% 可接受')
            else:
                analysis.append(f'模型偏差: {abs(err_pct):.1f}% 需复核 ({err:+d}张)')
            
            # Tier role analysis
            t1_dev = abs(r['confirmed'].get('T1',0) - r['baseline'].get('T1',0))
            t5_dev = abs(r['confirmed'].get('T5',0) - r['baseline'].get('T5',0))
            if t1_dev <= 5:
                analysis.append('T1压舱石：未调价，刚需稳定')
            if t5_dev > 10:
                t5_pct = (r['confirmed'].get('T5',0) / r['baseline'].get('T5',1) - 1) * 100
                analysis.append(f'T5利润锚：调价{t5_pct:+.0f}%，弹性验证中')
            
            # Dominant effect
            if abs(pe) > abs(ie):
                analysis.append(f'主导效应：调价 (¥{pe/1e4:+.1f}万, {pe_pct:.0f}%)')
            else:
                analysis.append(f'主导效应：库存 (¥{ie/1e4:+.1f}万, {ie_pct:.0f}%)')
            
            # 动态弹性摘要
            from src.pricing_v5 import get_dynamic_elasticity_value
            eps_summary = []
            pt_val = get_pricing_tier(r['opponent'], match_date=r['date'])
            for zt in ZT:
                ep_z = get_dynamic_elasticity_value(pt_val, zt)
                if ep_z and r['confirmed'].get(zt,0) != r['baseline'].get(zt,0):
                    eps_summary.append(f'{zt}={ep_z:.2f}')
            if eps_summary:
                analysis.append(f'弹性参数: {" · ".join(eps_summary)}')
            
            # Key tier deviations
            for zt in ZT:
                bq = snap_data.get('baseline', {}).get('base_qtys', {}).get(zt, 0)
                aq = snap_data.get('actual', {}).get('quantities', {}).get(zt, 0)
                if bq and bq > 100:
                    dev = (aq - bq) / bq
                    if abs(dev) > 0.3:
                        d = '超预期' if dev > 0 else '低于预期'
                        analysis.append(f'{zt}销量偏差{dev:+.0%}（{d}）')
            
            atext = '<br>'.join(f'• {a}' for a in analysis)
            
            # ── Next steps ──
            pm_data = snap_data.get('postmortem')
            if pm_data:
                dec = pm_data['decomposition']
                nxt = f'✅ 已完成复盘。库存 +¥{dec["inventory_restructure"]["rev_delta"]/1e4:.1f}万 + 调价 +¥{dec["pricing_adjustment"]["rev_delta"]/1e4:.1f}万 = 净贡献 +¥{dec["total"]["rev_delta"]/1e4:.1f}万'
            else:
                note = r.get('note', '')
                if note:
                    nxt = f'📝 {note}'
                else:
                    suggestions = []
                    if abs(pe) > abs(ie) and pe > 0:
                        suggestions.append('调价策略有效，下次可复用涨价幅度')
                    elif abs(ie) > abs(pe) and ie > 0:
                        suggestions.append('库存重组效果显著，建议标准化T4扩容方案')
                    if abs(err_pct) > 15:
                        suggestions.append(f'预测偏差{abs(err_pct):.0f}%，建议复核分级和情境乘数')
                    nxt = '🔍 ' + ('；'.join(suggestions) if suggestions else '待人工复盘')
            
            # ── Render card ──
            pe_color = "#ff6b6b" if pe > 0 else "#51cf66"
            ie_color = "#ff6b6b" if ie > 0 else "#51cf66"
            te_color = "#ff6b6b" if te > 0 else "#51cf66"
            
            card = (
                f'<div style="background:#1a1a2e;border:1px solid #333;border-radius:8px;padding:14px;margin:10px 0">'
                f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">'
                f'<strong style="font-size:1.05rem">{r["date"]} vs {r["opponent"]}</strong>'
                f'<span style="font-size:0.72rem;color:#8a8f98">{r["tier"]}</span>'
                f'</div>'
                f'<div style="display:flex;gap:12px;margin:2px 0 8px 0;font-size:0.7rem;color:#62666d">'
                f'<span>📊 模型偏差: 预测{r["pred_qty"]:,} vs 实际{r["actual_qty"]:,} | <b style="color:{err_color}">{err:+d}张 ({err_pct:+.1f}%)</b></span>'
                f'</div>'
                f'{scenario_html}'
                f'<div style="display:flex;gap:8px;margin:4px 0 6px 0;font-size:0.72rem">'
                f'<span style="background:rgba(240,192,64,0.15);padding:3px 10px;border-radius:4px;border:1px solid rgba(240,192,64,0.3)">策略贡献 <b style="color:{te_color}">¥{strategy_contrib/1e4:+.1f}万</b></span>'
                f'<table class="compact-table" style="font-size:0.66rem;margin:6px 0">'
                f'<thead><tr><th>档位</th><th>基准价</th><th>确认价</th><th>预测量</th><th>实际量</th><th>调价效应</th><th>库存效应</th><th>票面收入</th></tr></thead>'
                f'<tbody>{tier_rows}</tbody></table>'
                f'<div style="margin-top:6px;padding:6px 10px;background:rgba(255,255,255,0.02);border-radius:4px;font-size:0.68rem;color:#a0a8b0;line-height:1.5">'
                f'<b>回测分析</b><br>{atext}</div>'
                f'<div style="margin-top:4px;padding:4px 10px;background:rgba(81,207,102,0.05);border-left:2px solid #51cf66;border-radius:2px;font-size:0.68rem;color:#a0a8b0">'
                f'<b>下一步</b> {nxt}</div>'
                f'</div>'
            )
            st.markdown(card, unsafe_allow_html=True)

        st.caption("✅ 调价效应 = Σ(实际销量 × 价差) · 库存效应 = Σ((实际量-基准量) × 基准价) · 合计 = 调价+库存")
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
