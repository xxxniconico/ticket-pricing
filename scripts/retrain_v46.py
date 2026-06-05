#!/usr/bin/env python3
"""
V4.6: 纳入2024数据 + 月份效应 → 重训模型
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
# 1. 加载2024-2026全部数据
# ============================================================
mf = pd.read_parquet(ROOT / "data/processed/match_features.parquet")
csl = mf[
    (mf['competition'] == 'CSL') & 
    (~mf['opponent'].isin(NON_CSL))
].sort_values('match_date').copy()

print(f"全部CSL: {len(csl)} 场 (2024:{len(csl[csl['match_date'].str.startswith('2024')])} "
      f"2025:{len(csl[csl['match_date'].str.startswith('2025')])} "
      f"2026:{len(csl[csl['match_date'].str.startswith('2026')])})")

# Load context
matches_data, standings, _ = load_csl_data()
guoan_all = get_guoan_matches(matches_data)

# Build records
records = []
for _, m in csl.iterrows():
    opp = m['opponent']
    actual = int(m['attendance'])
    date = m['match_date']
    md = pd.Timestamp(date)
    
    tier = classify_opponent_tier(opp)
    is_derby = opp in DERBY_RIVALS or any(d in str(opp) for d in DERBY_RIVALS)
    is_sat = md.weekday() == 5
    is_late = md.month >= 10
    is_midweek = md.weekday() in (1, 2, 3)
    
    # Dynamic context from CSL JSON
    match_obj = {"date": date, "opponent": opp, "is_home": True, "completed": True}
    ctx = detect_ctx(match_obj, guoan_all, standings)
    
    records.append({
        'date': date, 'opponent': opp, 'tier': tier, 'actual': actual,
        'year': date[:4], 'month': md.month,
        'derby': is_derby, 'saturday': is_sat, 'late_season': is_late,
        'midweek': is_midweek,
        'away_winless': ctx.get('away_winless', False),
        'lost_bottom': ctx.get('lost_bottom', False),
        'heavy_home_loss': ctx.get('heavy_home_loss', False),
        'short_rest': ctx.get('short_rest', False),
        'unbeaten_3': ctx.get('unbeaten_3', False),
    })

df_m = pd.DataFrame(records)

# ============================================================
# 2. 当前乘数（V4.5最优）
# ============================================================
CUR_MULT = {
    'derby': 1.25, 'derby_B': 1.15,
    'lost_bottom': 0.65, 'heavy_home_loss': 0.90,
    'away_winless': 0.82, 'saturday': 1.15, 'late_season': 0.70,
    'season_opener': 1.15, 'short_rest': 0.72, 'midweek': 0.80,
    'unbeaten_3': 1.05,
}

def decontext_mult(row, mults):
    """反推中性需求"""
    m = 1.0
    if row['derby']:
        if row['tier'] != 'S':
            if row['tier'] == 'A':
                m *= mults.get('derby_B', 1.15)
            else:
                m *= mults['derby']
    if row.get('lost_bottom', False):
        if row['tier'] in ('S', 'A'):
            m *= 0.78
        else:
            m *= mults['lost_bottom']
    elif row.get('heavy_home_loss', False):
        m *= mults['heavy_home_loss']
    if row.get('away_winless', False):
        m *= mults['away_winless']
    if row['saturday']:
        m *= mults['saturday']
    if row['late_season']:
        m *= mults['late_season']
    if row['midweek'] and not row.get('lost_bottom') and not row.get('heavy_home_loss'):
        m *= mults['midweek']
    if row.get('short_rest') and not row.get('lost_bottom') and not row.get('heavy_home_loss'):
        m *= mults['short_rest']
    if row.get('unbeaten_3', False):
        m *= mults['unbeaten_3']
    return max(m, 0.35)

def predict_one(row, tier_base, mults):
    base = tier_base[row['tier']]
    m = decontext_mult(row, mults)
    return base * m

def compute_mae(df, tier_base, mults):
    preds = df.apply(lambda r: predict_one(r, tier_base, mults), axis=1)
    return np.mean(np.abs(preds - df['actual']))

# ============================================================
# 3. 迭代反推 + 网格搜索
# ============================================================
print("\n迭代反推基值...")
current_mults = dict(CUR_MULT)
for iteration in range(5):
    df_m['decontext'] = df_m.apply(lambda r: r['actual'] / decontext_mult(r, current_mults), axis=1)
    new_bases = {}
    for t in ['S', 'A', 'B', 'C']:
        sub = df_m[df_m['tier'] == t]
        if len(sub) > 0:
            new_bases[t] = round(np.median(sub['decontext'].values) / 100) * 100
    mae = compute_mae(df_m, new_bases, current_mults)
    print(f"  Iter {iteration}: bases={new_bases}, MAE={mae:.0f}")
    if iteration > 0 and mae >= best_mae - 5:
        break
    best_mae = mae

final_bases = new_bases
print(f"收敛基值: {final_bases}")

# ============================================================
# 4. 网格搜索乘数
# ============================================================
print("\n网格搜索乘数...")
param_grid = {
    'derby': [1.15, 1.20, 1.25, 1.30],
    'derby_B': [1.05, 1.10, 1.12, 1.15],
    'lost_bottom': [0.60, 0.65, 0.70],
    'heavy_home_loss': [0.85, 0.90, 0.95],
    'away_winless': [0.82, 0.85, 0.88, 0.90],
    'saturday': [1.10, 1.12, 1.15, 1.18, 1.20],
    'late_season': [0.65, 0.70, 0.75],
    'season_opener': [1.10, 1.12, 1.15],
    'short_rest': [0.72, 0.75, 0.78],
    'midweek': [0.80, 0.82, 0.85],
    'unbeaten_3': [1.02, 1.05, 1.08],
}

best_mults = dict(CUR_MULT)
best_mae_gs = compute_mae(df_m, final_bases, best_mults)
print(f"基线 MAE: {best_mae_gs:.0f}")

search_order = ['derby', 'lost_bottom', 'heavy_home_loss', 'away_winless', 
                'saturday', 'late_season', 'season_opener', 'midweek', 'short_rest',
                'derby_B', 'unbeaten_3']

for param in search_order:
    best_val = best_mults[param]
    best_local_mae = best_mae_gs
    for val in param_grid.get(param, [best_val]):
        test_mults = dict(best_mults)
        test_mults[param] = val
        mae = compute_mae(df_m, final_bases, test_mults)
        if mae < best_local_mae:
            best_local_mae = mae
            best_val = val
    if best_val != best_mults[param]:
        best_mults[param] = best_val
        best_mae_gs = best_local_mae
        print(f"  {param}: → {best_val:.2f} (MAE={best_mae_gs:.0f})")

# Round 2
for param in search_order:
    for val in param_grid.get(param, [best_mults[param]]):
        test_mults = dict(best_mults)
        test_mults[param] = val
        mae = compute_mae(df_m, final_bases, test_mults)
        if mae < best_mae_gs - 3:
            best_mults[param] = val
            best_mae_gs = mae
            print(f"  R2 {param}: → {val:.2f} (MAE={best_mae_gs:.0f})")

# ============================================================
# 5. 逐场展示（按年份分）
# ============================================================
print("\n" + "=" * 70)
print("逐场预测")
print("=" * 70)

for yr in ['2024', '2025', '2026']:
    sub = df_m[df_m['year'] == yr]
    if len(sub) == 0: continue
    print(f"\n{yr} ({len(sub)}场):")
    errors = []
    for _, r in sub.iterrows():
        pred = predict_one(r, final_bases, best_mults)
        err = abs(pred - r['actual'])
        ape = err / r['actual'] * 100
        errors.append(err)
    mae_yr = np.mean(errors)
    mape_yr = np.mean([abs(predict_one(r, final_bases, best_mults)-r['actual'])/r['actual']*100 for _, r in sub.iterrows()])
    print(f"  MAE={mae_yr:.0f}, MAPE={mape_yr:.1f}%")

# Overall
total_mae = compute_mae(df_m, final_bases, best_mults)
total_mape = np.mean([abs(predict_one(r, final_bases, best_mults)-r['actual'])/r['actual']*100 for _, r in df_m.iterrows()])
print(f"\n全部 ({len(df_m)}场): MAE={total_mae:.0f}, MAPE={total_mape:.1f}%")

print(f"\n最终参数:")
print(f"TIER_BASE = {final_bases}")
print(f"MULTIPLIERS = {best_mults}")