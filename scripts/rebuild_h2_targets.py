#!/usr/bin/env python3
"""Rebuild H2 targets with latest model (rule_engine V5.3 + optimizer V8.2 + pricing V8.1)."""
import sys
sys.path.insert(0, '/home/xxxsuli/ticket-pricing')
sys.path.insert(0, '/mnt/c/Users/xxxsu/.openclaw/workspace/csl_project_v2')

import json
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from src.csl_context import load_csl_data, get_guoan_matches, detect_ctx
from src.rule_engine import predict as rule_predict
from src.classify import classify_opponent_tier, DERBY_RIVALS
from src.dynamic_optimizer import DynamicPricingOptimizer
from src.pricing_v5 import get_pricing_tier, build_price_matrix, ZONE_TIERS
from src.match_notes import get_adjusted_actual

all_matches, rounds, deductions = load_csl_data()
guoan_matches = get_guoan_matches(all_matches)
guoan_matches = [m for m in guoan_matches if 'cfl_fixtures_api' in m.get('source','') or 'wikipedia' in m.get('source','')]
_ctx_rounds = rounds
ROOT = Path('/home/xxxsuli/ticket-pricing')

df = pd.read_parquet(ROOT / 'data/processed/all_unified.parquet')
csl = df[(df['competition']=='CSL') & (~df['is_partial']) & (~df['is_bundle'])]

completed_rev = 0.0
completed_qty = 0
for mid in csl['match_id'].unique():
    md = csl[csl['match_id'] == mid]
    if not str(md['match_date'].iloc[0]).startswith('2026'):
        continue
    completed_rev += md['实际支付价格'].sum()
    completed_qty += get_adjusted_actual(mid, int(md['数量'].sum()))

completed = [m for m in guoan_matches if m['completed'] and m['date'].startswith('2026')]
home_done = [m for m in completed if m['is_home']]
remaining = sorted(
    [m for m in guoan_matches if not m['completed'] and m['is_home'] and m['date'].startswith('2026')],
    key=lambda x: x['date']
)
all_home = sorted(home_done + remaining, key=lambda x: x['date'])

optimizer = DynamicPricingOptimizer(revenue_weight=0.6)
pm = build_price_matrix()

targets = []
total_r = 0
total_q = 0

ctx_keys = ['away_winless', 'lost_bottom', 'heavy_home_loss', 'short_rest', 'unbeaten_3', 'away_winless_losses']

for m in remaining:
    mock = {**m, 'completed': True}
    ctx = detect_ctx(mock, guoan_matches + [mock], _ctx_rounds)
    dt = pd.Timestamp(m['date'])
    opp = m['opponent']
    so = (m == all_home[0])
    tier = classify_opponent_tier(opp)
    pt = get_pricing_tier(opp)

    pred_args = dict(
        derby=opp in DERBY_RIVALS,
        saturday=dt.weekday() == 5,
        late_season=dt.month >= 10,
        midweek=dt.weekday() in (1, 2, 3),
        summer=dt.month in (7, 8),
        season_opener=so,
        match_year='2026',
        **{k: ctx.get(k, False) for k in ctx_keys}
    )
    pred = rule_predict(opp, **pred_args)
    r = optimizer.optimize(opp, **pred_args)

    if r.revenue_weight >= 0.7:
        strat = 'revenue_priority'
    elif r.revenue_weight >= 0.5:
        strat = 'revenue_tilt'
    else:
        strat = 'balanced'

    prices = {zt: pm[pt][zt] for zt in ZONE_TIERS}
    target_rev = int(r.total_revenue)
    target_qty = int(r.total_attendance)
    avg_price = target_rev / target_qty if target_qty > 0 else 0

    risks = []
    if opp in {'辽宁铁人', '重庆铜梁龙'}:
        risks.append('升班马B级潜力(C级定价保守)')
    if dt.month >= 10:
        risks.append('late_season')
    if dt.month in (7, 8):
        risks.append('summer')

    targets.append({
        'date': m['date'],
        'opponent': opp,
        'round': m.get('round', ''),
        'tier': tier,
        'pricing_tier': pt,
        'predicted_quantity': int(pred),
        'strategy': strat,
        'revenue_weight': round(r.revenue_weight, 2),
        'target_revenue': target_rev,
        'target_quantity': target_qty,
        'target_avg_price': round(avg_price, 0),
        'base_prices': {zt: prices[zt] for zt in ZONE_TIERS},
        'context': [k for k, v in ctx.items() if v],
        'risks': risks,
        'model_version': 'V5.3+V8.2',
    })
    total_r += target_rev
    total_q += target_qty

rev_2025 = 45914055
qty_2025 = 145712
annual_rev = completed_rev + total_r
annual_qty = completed_qty + total_q
vs_rev_pct = round((annual_rev / rev_2025 - 1) * 100, 1)
vs_qty_pct = round((annual_qty / qty_2025 - 1) * 100, 1)

output = {
    'model_version': 'V5.3+V8.2',
    'updated': datetime.now().strftime('%Y-%m-%d %H:%M'),
    'completed': {
        'matches': 7,
        'revenue': int(completed_rev),
        'quantity': completed_qty,
    },
    'summary': {
        'total_target_revenue': int(total_r),
        'total_target_quantity': total_q,
        'annual_projection_revenue': int(annual_rev),
        'annual_projection_quantity': annual_qty,
        'vs_2025_revenue_pct': vs_rev_pct,
        'vs_2025_quantity_pct': vs_qty_pct,
    },
    'matches': targets,
    'notes': [
        'rule_engine V5.3 + optimizer V8.2 + pricing V8.1: away_winless拆分(0.98/0.82), 弹性矩阵按对手区分, 策略门槛10000/8000/6000',
        '辽宁铁人/重庆铜梁龙按C级定价(保守), B级升级空间~2M',
        f'全年预估{annual_rev/1e4:.0f}万, 同比{vs_rev_pct:+.1f}%',
    ]
}

out_path = ROOT / 'data/targets/h2_2026_match_targets.json'
with open(out_path, 'w') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f'Written to {out_path}')
print(f'Completed: 7 matches, {completed_rev/1e4:.1f}万 / {completed_qty:,}张')
print(f'Remaining: 8 matches, {total_r/1e4:.1f}万 / {total_q:,}张')
print(f'Annual: {annual_rev/1e4:.1f}万 ({vs_rev_pct:+.1f}% vs 2025) / {annual_qty:,}张 ({vs_qty_pct:+.1f}%)')
for t in targets:
    risks_str = ', '.join(t['risks']) if t['risks'] else '-'
    print(f"  {t['date']} vs {t['opponent']:10s} {t['tier']}/{t['pricing_tier']} pred={t['predicted_quantity']:>5,} {t['strategy']:18s} ¥{t['target_revenue']:>10,} {t['target_quantity']:>5,}  [{risks_str}]")
