#!/usr/bin/env python3
"""动态定价操作工作流 — 赛前预测 / 定价决策 / 赛后校准 / 回测。

用法:
  python scripts/workflow.py pre-match --opponent "武汉三镇" --date 2026-06-27
  python scripts/workflow.py decide --opponent "武汉三镇" --date 2026-06-27 --t1 160 --t2 220 ...
  python scripts/workflow.py post-match --opponent "武汉三镇" --date 2026-06-27 --actual 9100
  python scripts/workflow.py status
  python scripts/workflow.py backtest
"""
import sys
sys.path.insert(0, '/home/xxxsuli/ticket-pricing')

import json, os, argparse
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np

ROOT = Path('/home/xxxsuli/ticket-pricing')
SNAPSHOT_DIR = ROOT / 'data' / 'snapshots'
DECISION_FILE = ROOT / 'data' / 'processed' / 'pricing_decisions.json'
STATE_FILE = ROOT / 'data' / 'processed' / 'season_state.json'
CAL_FILE = ROOT / 'data' / 'processed' / 'calibration.json'

# ── helpers ──

def _load_json(path, default=None):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default if default is not None else {}

def _save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


# ── pre-match ──

def cmd_pre_match(args):
    """赛前预测 + 优化 + 保存快照。"""
    from src.csl_context import predict_with_context
    from src.classify import classify_opponent_tier, DERBY_RIVALS
    from src.pricing_v5 import get_pricing_tier, build_price_matrix, ZONE_TIERS
    from src.dynamic_optimizer import DynamicPricingOptimizer

    opp = args.opponent
    date = args.date
    dt = pd.Timestamp(date)
    tier = classify_opponent_tier(opp)
    pt = get_pricing_tier(opp)

    # 1. 预测
    pred = predict_with_context(opp, date)
    print(f"\n{'='*60}")
    print(f"赛前预测: {date} vs {opp}")
    print(f"{'='*60}")
    print(f"对手级别: {tier} / 定价档位: {pt}")
    print(f"预测上座: {pred:,.0f} 张")

    # 2. 情境检测（单独跑一遍获取详细信息）
    from src.csl_context import load_csl_data, get_guoan_matches, detect_ctx
    all_matches, rounds, _ = load_csl_data()
    guoan = get_guoan_matches(all_matches)
    guoan = [m for m in guoan if 'cfl_fixtures_api' in m.get('source', '') or 'wikipedia' in m.get('source', '')]
    mock = {'date': date, 'opponent': opp, 'is_home': True, 'completed': True}
    from dashboard.components.ctx_builder import ctx_kwargs
    ctx = detect_ctx(mock, guoan, rounds)

    active_ctx = {k: v for k, v in ctx.items() if v and k != "guoan_rank"}
    if active_ctx:
        print(f"\n触发情境:")
        for k in active_ctx:
            from src.rule_engine import MULTIPLIERS
            mult = MULTIPLIERS.get(k, '?')
            print(f"  {k} = {mult}x")
    else:
        print(f"\n触发情境: 无")

    pred_args = dict(
        derby=opp in DERBY_RIVALS,
        saturday=dt.weekday() == 5,
        midweek=dt.weekday() in (1, 2, 3),
        summer=dt.month in (7, 8),
        late_season=dt.month >= 10,
        match_year=str(dt.year),
        **ctx_kwargs(ctx),
    )

    optimizer = DynamicPricingOptimizer(revenue_weight=0.6)
    result = optimizer.optimize(opp, **pred_args)

    pm = build_price_matrix()
    base_prices = {zt: pm[pt][zt] for zt in ['T1', 'T2', 'T3', 'T4', 'T5', 'T6']}

    print(f"\n定价建议 (策略: {result.revenue_weight:.0%} 收入权重):")
    print(f"  目标收入: ¥{result.total_revenue:,.0f}")
    print(f"  目标上座: {result.total_attendance:,.0f} 张")
    print(f"  目标均价: ¥{result.total_revenue/result.total_attendance:.0f}")

    # 4. 保存快照
    snapshot = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'model_version': 'V5.4+V8.2',
        'match': {'date': date, 'opponent': opp},
        'prediction': {
            'tier': tier, 'pricing_tier': pt,
            'predicted_quantity': int(pred),
            'context': {k: v for k, v in ctx.items() if v},
            'context_args': pred_args,
        },
        'optimization': {
            'revenue_weight': round(result.revenue_weight, 2),
            'target_revenue': int(result.total_revenue),
            'target_quantity': int(result.total_attendance),
            'base_prices': base_prices,
        },
    }
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    snap_path = SNAPSHOT_DIR / f'pre_{date}_{opp}.json'
    _save_json(snap_path, snapshot)
    print(f"\n快照已保存: {snap_path}")


# ── decide ──

def cmd_decide(args):
    """记录定价决策。"""
    decisions = _load_json(DECISION_FILE, {'decisions': []})

    prices = {}
    for t in ['T1', 'T2', 'T3', 'T4', 'T5', 'T6']:
        val = getattr(args, t.lower(), None)
        if val is not None:
            prices[t] = val

    decision = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'match': {'date': args.date, 'opponent': args.opponent},
        'prices': prices,
        'note': args.note or '',
    }
    decisions['decisions'].append(decision)
    _save_json(DECISION_FILE, decisions)
    print(f"定价决策已记录: {args.date} vs {args.opponent}")
    for t, p in prices.items():
        print(f"  {t}: ¥{p}")


# ── post-match ──

def cmd_post_match(args):
    """赛后校准：更新 calibration + season_state。"""
    from src.csl_context import predict_with_context
    from src.classify import classify_opponent_tier

    opp = args.opponent
    date = args.date
    actual = args.actual
    tier = classify_opponent_tier(opp)

    # 1. 重新预测（用赛后能看到的最新数据）
    pred = predict_with_context(opp, date)

    err = abs(pred - actual)
    err_pct = round(err / actual * 100, 1) if actual > 0 else 0

    print(f"\n{'='*60}")
    print(f"赛后校准: {date} vs {opp}")
    print(f"{'='*60}")
    print(f"预测上座: {pred:,.0f}")
    print(f"实际上座: {actual:,}")
    print(f"误差: {err:,.0f} 张 ({err_pct}%)")

    # 2. 更新 EMA 校准
    cal = _load_json(CAL_FILE, {'tier': {'S': 1.0, 'A': 1.0, 'B': 1.0, 'C': 1.0}, 'history': []})
    alpha = 0.20
    ratio = actual / pred if pred > 0 else 1.0
    old_cal = cal['tier'].get(tier, 1.0)
    new_cal = round(alpha * ratio + (1 - alpha) * old_cal, 4)
    new_cal = max(0.3, min(2.0, new_cal))
    cal['tier'][tier] = new_cal

    cal['history'].append({
        'match_id': f'{date}_{opp}',
        'date': date, 'opponent': opp, 'tier': tier,
        'predicted': round(pred, 0), 'actual': actual,
        'error': round(err, 0), 'error_pct': err_pct,
        'ratio': round(ratio, 4),
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M'),
    })
    _save_json(CAL_FILE, cal)

    print(f"\n{tier}级校准: {old_cal} → {new_cal}")
    print(f"当前各级校准: {cal['tier']}")

    # 3. 更新 season state
    state = _load_json(STATE_FILE, {})
    history = state.get('history', [])
    completed = len(history) + 1
    cumulative_mae = (sum(h['error'] for h in history) + err) / completed if completed > 0 else err

    history.append({
        'round': completed,
        'date': date, 'opponent': opp, 'tier': tier,
        'actual': actual, 'predicted': round(pred, 0),
        'error': round(err, 0), 'error_pct': err_pct,
        'cumulative_mae': round(cumulative_mae, 0),
        'cal_factors': dict(cal['tier']),
    })
    state.update({
        'season': str(pd.Timestamp(date).year),
        'completed': completed,
        'cumulative_mae': round(cumulative_mae, 0),
        'tier_cal': cal['tier'],
        'history': history[-30:],  # keep last 30
    })
    _save_json(STATE_FILE, state)

    print(f"累积 MAE: {cumulative_mae:,.0f} 张 ({completed} 场)")
    print(f"赛季状态已更新: {STATE_FILE}")

    # 4. 显示决策对比（如果有赛前决策记录）
    decisions = _load_json(DECISION_FILE, {'decisions': []})
    match_decisions = [d for d in decisions['decisions']
                       if d['match']['date'] == date and d['match']['opponent'] == opp]
    if match_decisions:
        d = match_decisions[-1]
        print(f"\n赛前决策回顾: {d['timestamp']}")
        print(f"  采用价格: {d['prices']}")
        if d.get('note'):
            print(f"  备注: {d['note']}")


# ── status ──

def cmd_status(args):
    """查看赛季状态。"""
    state = _load_json(STATE_FILE)
    cal = _load_json(CAL_FILE)

    if not state:
        print("暂无赛季状态。先跑一次 post-match 开始记录。")
        return

    print(f"\n赛季 {state.get('season', '?')} | 已完成 {state['completed']} 场")
    print(f"累积 MAE: {state.get('cumulative_mae', '?'):,} 张")
    print(f"各级校准: {cal.get('tier', state.get('tier_cal', {}))}")

    history = state.get('history', [])
    if history:
        print(f"\n逐场记录:")
        for h in history[-10:]:
            print(f"  R{h['round']:>2} {h['date']} {h['opponent']:10s} [{h['tier']}] "
                  f"pred={h['predicted']:>5,.0f} actual={h['actual']:>5,} "
                  f"err={h['error']:>4,.0f} ({h['error_pct']}%)")


# ── backtest ──

def cmd_backtest(args):
    """跑本赛季完整回测。"""
    from src.csl_context import predict_with_context
    from src.classify import classify_opponent_tier

    # 从 parquet 读取所有已赛数据
    parquet = ROOT / 'data/processed/all_unified.parquet'
    if not os.path.exists(parquet):
        print("parquet 文件不存在，先跑 rebuild_parquet.py")
        return

    df = pd.read_parquet(parquet)
    df["数量"] = pd.to_numeric(df["数量"])
    df["实际支付价格"] = pd.to_numeric(df["实际支付价格"])
    df["is_home"] = df["is_home"] == "True"
    csl = df[(df['competition'] == 'CSL') & (df["is_partial"] == "False") & (df["is_bundle"] == "False")]

    # 收集所有场次
    records = []
    for mid in sorted(csl['match_id'].unique()):
        md = csl[csl['match_id'] == mid]
        date = str(md['match_date'].iloc[0])[:10]
        opp = md['opponent'].iloc[0] if 'opponent' in md.columns else mid.split('_')[-1]
        actual = int(md['数量'].sum())
        records.append({'date': date, 'opponent': opp, 'actual': actual})

    records.sort(key=lambda x: x['date'])

    # 逐场回测（模拟赛后逐场更新）
    print(f"\n{'='*70}")
    print(f"回测: {len(records)} 场 CSL")
    print(f"{'='*70}")
    print(f"{'日期':>12} {'对手':10s} {'级别':>4} {'预测':>7} {'实际':>7} {'误差':>7} {'误差率':>7}")
    print("-" * 70)

    errors = []
    tier_cal = {'S': 1.0, 'A': 1.0, 'B': 1.0, 'C': 1.0}

    for i, r in enumerate(records):
        tier = classify_opponent_tier(r['opponent'])
        pred = predict_with_context(r['opponent'], r['date'])
        pred *= tier_cal.get(tier, 1.0)
        err = pred - r['actual']
        err_pct = err / r['actual'] * 100 if r['actual'] > 0 else 0
        errors.append(abs(err))

        print(f"{r['date']:>12} {r['opponent']:10s} {tier:>4} {pred:>7,.0f} {r['actual']:>7,} {err:>+7,.0f} {err_pct:>+6.1f}%")

        # 模拟 EMA 更新
        ratio = r['actual'] / pred if pred > 0 else 1.0
        old = tier_cal[tier]
        tier_cal[tier] = round(0.20 * ratio + 0.80 * old, 4)

    mae = np.mean(errors)
    print("-" * 70)
    print(f"MAE: {mae:,.0f} 张 | MAPE: {np.mean([abs(e) for e in errors]) / np.mean([r['actual'] for r in records]) * 100:.1f}%")
    print(f"最终各级校准: {tier_cal}")


# ── CLI ──

def main():
    parser = argparse.ArgumentParser(description='动态定价工作流')
    sub = parser.add_subparsers(dest='cmd')

    p = sub.add_parser('pre-match', help='赛前预测 + 优化 + 保存快照')
    p.add_argument('--opponent', required=True)
    p.add_argument('--date', required=True)

    p = sub.add_parser('decide', help='记录定价决策')
    p.add_argument('--opponent', required=True)
    p.add_argument('--date', required=True)
    for t in ['t1', 't2', 't3', 't4', 't5', 't6']:
        p.add_argument(f'--{t}', type=int)
    p.add_argument('--note')

    p = sub.add_parser('post-match', help='赛后校准')
    p.add_argument('--opponent', required=True)
    p.add_argument('--date', required=True)
    p.add_argument('--actual', type=int, required=True)

    p = sub.add_parser('status', help='查看赛季状态')

    p = sub.add_parser('backtest', help='跑本赛季回测')

    args = parser.parse_args()

    if args.cmd == 'pre-match':
        cmd_pre_match(args)
    elif args.cmd == 'decide':
        cmd_decide(args)
    elif args.cmd == 'post-match':
        cmd_post_match(args)
    elif args.cmd == 'status':
        cmd_status(args)
    elif args.cmd == 'backtest':
        cmd_backtest(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
