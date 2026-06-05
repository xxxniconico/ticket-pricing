#!/usr/bin/env python3
"""
V4.4→V4.5: 完整模型重训
1. 反推中性基值：actual ÷ product(active_multipliers) → decontext
2. 网格搜索最优乘数（min MAE）
3. 迭代收敛
"""
import sys, json, os
from pathlib import Path
from itertools import product
import pandas as pd
import numpy as np

ROOT = Path("/home/xxxsuli/ticket-pricing")
sys.path.insert(0, str(ROOT))

from src.classify import classify_opponent_tier, DERBY_RIVALS
from src.csl_context import load_csl_data, get_guoan_matches, detect_ctx

NON_CSL = {"河内公安", "大埔", "麦克阿瑟FC"}

# ============================================================
# 1. 加载数据
# ============================================================
mf = pd.read_parquet(ROOT / "data/processed/match_features.parquet")
csl = mf[
    (mf['competition'] == 'CSL') & 
    (mf['match_date'].str.startswith(('2025', '2026'))) &
    (~mf['opponent'].isin(NON_CSL))
].sort_values('match_date').copy()

# 加载 CSL 情境
matches_data, standings, _ = load_csl_data()
guoan_all = get_guoan_matches(matches_data)

# 为每场比赛检测情境
records = []
for _, m in csl.iterrows():
    opp = m['opponent']
    actual = int(m['attendance'])
    date = m['match_date']
    md = pd.Timestamp(date)
    
    match_obj = {"date": date, "is_home": True, "completed": True}
    ctx = detect_ctx(match_obj, guoan_all, standings)
    
    # 基础情境
    tier = classify_opponent_tier(opp)
    is_derby = ctx.get('derby', False)
    is_sat = md.weekday() == 5
    is_late = md.month >= 10
    is_season_opener = ctx.get('season_opener', False)
    is_midweek = md.weekday() in (1, 2, 3)
    is_short_rest = ctx.get('short_rest', False)
    is_away_winless = ctx.get('away_winless', False)
    is_lost_bottom = ctx.get('lost_bottom', False)
    is_heavy_home_loss = ctx.get('heavy_home_loss', False)
    is_unbeaten_3 = ctx.get('unbeaten_3', False)
    
    records.append({
        'date': date, 'opponent': opp, 'tier': tier, 'actual': actual,
        'derby': is_derby, 'saturday': is_sat, 'late_season': is_late,
        'season_opener': is_season_opener, 'midweek': is_midweek,
        'short_rest': is_short_rest, 'away_winless': is_away_winless,
        'lost_bottom': is_lost_bottom, 'heavy_home_loss': is_heavy_home_loss,
        'unbeaten_3': is_unbeaten_3,
    })

df_m = pd.DataFrame(records)
print(f"数据集: {len(df_m)} 场 CSL")
print(f"\n情境触发频次:")
for col in ['derby','saturday','late_season','season_opener','midweek',
            'short_rest','away_winless','lost_bottom','heavy_home_loss','unbeaten_3']:
    n = df_m[col].sum()
    if n > 0:
        print(f"  {col}: {n} 场")

# ============================================================
# 2. 反推中性基值（使用当前乘数）
# ============================================================
CUR_MULT = {
    'derby': 1.25, 'derby_B': 1.15,
    'lost_bottom': 0.65, 'heavy_home_loss': 0.85,
    'away_winless': 0.88, 'saturday': 1.10, 'late_season': 0.60,
    'season_opener': 1.15, 'short_rest': 0.78, 'midweek': 0.80,
    'unbeaten_3': 1.08,
}

def decontext_mult(row, mults):
    """反推中性需求: actual / product(active multipliers)"""
    m = 1.0
    if row['derby']:
        if row['tier'] != 'S':
            if row['tier'] == 'A':
                m *= mults.get('derby_B', 1.15)
            else:
                m *= mults['derby']
    if row['lost_bottom']:
        if row['tier'] in ('S', 'A'):
            m *= 0.78
        else:
            m *= mults['lost_bottom']
    elif row['heavy_home_loss']:
        m *= mults['heavy_home_loss']
    if row['away_winless']:
        m *= mults['away_winless']
    if row['saturday']:
        m *= mults['saturday']
    if row['late_season']:
        m *= mults['late_season']
    if row['season_opener']:
        m *= mults['season_opener']
    if row['midweek'] and not row['lost_bottom'] and not row['heavy_home_loss']:
        m *= mults['midweek']
    if row['short_rest'] and not row['lost_bottom'] and not row['heavy_home_loss']:
        m *= mults['short_rest']
    if row['unbeaten_3']:
        m *= mults['unbeaten_3']
    return max(m, 0.35)

df_m['decontext'] = df_m.apply(lambda r: r['actual'] / decontext_mult(r, CUR_MULT), axis=1)

print("\n" + "=" * 70)
print("Pass 1: 用当前乘数去情境化 → 中性基值")
print("=" * 70)

for t in ['S', 'A', 'B', 'C']:
    sub = df_m[df_m['tier'] == t]
    if len(sub) == 0: continue
    dc = sub['decontext'].values
    actuals = sub['actual'].values
    print(f"\n{t} tier (n={len(sub)}):")
    for _, r in sub.iterrows():
        mult = decontext_mult(r, CUR_MULT)
        print(f"  {r['date']} {r['opponent']}: actual={r['actual']:.0f} ×1/{mult:.2f}={r['decontext']:.0f}")
    print(f"  decontext median={np.median(dc):.0f}, mean={dc.mean():.0f}")
    print(f"  actual median={np.median(actuals):.0f}")

# ============================================================
# 3. 迭代反推（收敛到稳定基值）
# ============================================================
print("\n" + "=" * 70)
print("迭代收敛: 反推基值 → 预测 → 调整乘数")
print("=" * 70)

def predict_one(row, tier_base, mults):
    """预测单场"""
    base = tier_base[row['tier']]
    m = decontext_mult(row, mults)
    return base * m

def compute_mae(df, tier_base, mults):
    """计算 MAE"""
    preds = df.apply(lambda r: predict_one(r, tier_base, mults), axis=1)
    return np.mean(np.abs(preds - df['actual']))

# Start with current multipliers, iterate
current_mults = dict(CUR_MULT)
best_mae = float('inf')

for iteration in range(5):
    # Step A: de-contextualize with current multipliers
    df_m['decontext'] = df_m.apply(lambda r: r['actual'] / decontext_mult(r, current_mults), axis=1)
    
    # Step B: compute new tier bases
    new_bases = {}
    for t in ['S', 'A', 'B', 'C']:
        sub = df_m[df_m['tier'] == t]
        if len(sub) > 0:
            new_bases[t] = round(np.median(sub['decontext'].values) / 100) * 100
    
    # Step C: evaluate
    mae = compute_mae(df_m, new_bases, current_mults)
    print(f"  Iter {iteration}: bases={new_bases}, MAE={mae:.0f}")
    
    if mae < best_mae - 10:  # meaningful improvement
        best_mae = mae
    else:
        break

final_bases = new_bases
print(f"\n收敛基值: {final_bases}")

# ============================================================
# 4. 网格搜索最优乘数
# ============================================================
print("\n" + "=" * 70)
print("网格搜索: 最优乘数 (min MAE)")
print("=" * 70)

# 固定基值，搜索乘数
FIXED_BASES = final_bases

param_grid = {
    'derby': [1.15, 1.20, 1.25, 1.30, 1.35],
    'derby_B': [1.05, 1.10, 1.12, 1.15, 1.18],
    'lost_bottom': [0.55, 0.60, 0.65, 0.70, 0.75],
    'heavy_home_loss': [0.80, 0.85, 0.90, 0.95],
    'away_winless': [0.82, 0.85, 0.88, 0.90, 0.92],
    'saturday': [1.05, 1.08, 1.10, 1.12, 1.15],
    'late_season': [0.50, 0.55, 0.60, 0.65, 0.70],
    'season_opener': [1.10, 1.12, 1.15, 1.18, 1.20],
    'short_rest': [0.72, 0.75, 0.78, 0.80, 0.82],
    'midweek': [0.75, 0.78, 0.80, 0.82, 0.85],
    'unbeaten_3': [1.05, 1.08, 1.10, 1.12],
}

# 先从当前最优开始
best_mults = dict(CUR_MULT)
best_mae_gs = compute_mae(df_m, FIXED_BASES, best_mults)
print(f"基线 MAE: {best_mae_gs:.0f}")

# 逐个乘数搜索
search_order = ['derby', 'lost_bottom', 'heavy_home_loss', 'away_winless', 
                'saturday', 'late_season', 'season_opener', 'midweek', 'short_rest',
                'derby_B', 'unbeaten_3']

for param in search_order:
    best_val = best_mults[param]
    best_local_mae = best_mae_gs
    
    for val in param_grid.get(param, [best_val]):
        test_mults = dict(best_mults)
        test_mults[param] = val
        mae = compute_mae(df_m, FIXED_BASES, test_mults)
        
        if mae < best_local_mae:
            best_local_mae = mae
            best_val = val
    
    if best_val != best_mults[param]:
        best_mults[param] = best_val
        best_mae_gs = best_local_mae
        print(f"  {param}: → {best_val:.2f} (MAE={best_mae_gs:.0f})")

# 第二轮（交互效应）
for param in search_order:
    for val in param_grid.get(param, [best_mults[param]]):
        test_mults = dict(best_mults)
        test_mults[param] = val
        mae = compute_mae(df_m, FIXED_BASES, test_mults)
        if mae < best_mae_gs - 5:
            best_mults[param] = val
            best_mae_gs = mae
            print(f"  Round2 {param}: → {val:.2f} (MAE={best_mae_gs:.0f})")

print(f"\n最优乘数 (MAE={best_mae_gs:.0f}):")
for k, v in best_mults.items():
    if v != CUR_MULT.get(k):
        print(f"  {k}: {CUR_MULT.get(k)} → {v} {'▲' if v > CUR_MULT.get(k) else '▼'}")
    else:
        print(f"  {k}: {v} (不变)")

# ============================================================
# 5. 展示逐场预测
# ============================================================
print("\n" + "=" * 70)
print("逐场预测 vs 实际")
print("=" * 70)

errors = []
for _, r in df_m.iterrows():
    pred = predict_one(r, FIXED_BASES, best_mults)
    err = pred - r['actual']
    ape = abs(err) / r['actual'] * 100
    errors.append({'ape': ape, 'abs_err': abs(err), 'err': err})
    active = [k[:4] for k in ['derby','saturday','late_season','season_opener',
              'midweek','short_rest','away_winless','lost_bottom',
              'heavy_home_loss','unbeaten_3'] if r.get(k)]
    flag = ','.join(active) if active else '-'
    print(f"  {r['date']} {r['opponent']:<10} {r['tier']} actual={r['actual']:.0f} "
          f"pred={pred:.0f} err={err:+.0f} ape={ape:.1f}% [{flag}]")

mae_final = np.mean([e['abs_err'] for e in errors])
mape_final = np.mean([e['ape'] for e in errors])
print(f"\nMAE={mae_final:.0f} MAPE={mape_final:.1f}%")

# ============================================================
# 6. 输出最终参数
# ============================================================
print("\n" + "=" * 70)
print("最终参数 (V4.5)")
print("=" * 70)
print(f"TIER_BASE = {FIXED_BASES}")
print(f"MULTIPLIERS = {best_mults}")
print(f"MAE={mae_final:.0f} MAPE={mape_final:.1f}%")