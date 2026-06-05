#!/usr/bin/env python3
"""V4.7: 5级制重训 (S/A/B1/B2/C)"""
import sys, json, os
from pathlib import Path
import pandas as pd, numpy as np

ROOT = Path("/home/xxxsuli/ticket-pricing")
sys.path.insert(0, str(ROOT))
from src.classify import classify_opponent_tier, DERBY_RIVALS
from src.csl_context import load_csl_data, get_guoan_matches, detect_ctx

NON_CSL = {"河内公安", "大埔", "麦克阿瑟FC"}
TIERS_5 = ['S', 'A', 'B1', 'B2', 'C']

# 1. Load
mf = pd.read_parquet(ROOT / "data/processed/match_features.parquet")
csl = mf[(mf['competition']=='CSL') & (~mf['opponent'].isin(NON_CSL))].sort_values('match_date')
print(f"数据: {len(csl)} 场")

matches_data, standings, _ = load_csl_data()
guoan_all = get_guoan_matches(matches_data)

# Build records
records = []
for _, m in csl.iterrows():
    opp = m['opponent']; actual = int(m['attendance']); date = m['match_date']; md = pd.Timestamp(date)
    tier = classify_opponent_tier(opp)
    is_derby = opp in DERBY_RIVALS or any(d in str(opp) for d in DERBY_RIVALS)
    is_sat = md.weekday() == 5
    is_late = md.month >= 10
    is_midweek = md.weekday() in (1,2,3)
    match_obj = {"date":date,"opponent":opp,"is_home":True,"completed":True}
    ctx = detect_ctx(match_obj, guoan_all, standings)
    records.append({
        'date':date,'opponent':opp,'tier':tier,'actual':actual,'year':date[:4],'month':md.month,
        'derby':is_derby,'saturday':is_sat,'late_season':is_late,'midweek':is_midweek,
        'away_winless':ctx.get('away_winless',False),'lost_bottom':ctx.get('lost_bottom',False),
        'heavy_home_loss':ctx.get('heavy_home_loss',False),'short_rest':ctx.get('short_rest',False),
        'unbeaten_3':ctx.get('unbeaten_3',False),
    })
df_m = pd.DataFrame(records)

CUR_MULT = {'derby':1.25,'derby_B':1.05,'lost_bottom':0.65,'heavy_home_loss':0.90,
            'away_winless':0.82,'saturday':1.15,'late_season':0.70,'season_opener':1.15,
            'short_rest':0.72,'midweek':0.80,'unbeaten_3':1.02}

def decontext_mult(row, mults):
    m = 1.0
    if row['derby']:
        if row['tier'] != 'S':
            if row['tier'] == 'A': m *= mults.get('derby_B',1.15)
            else: m *= mults['derby']
    if row.get('lost_bottom'):
        m *= 0.78 if row['tier'] in ('S','A') else mults['lost_bottom']
    elif row.get('heavy_home_loss'): m *= mults['heavy_home_loss']
    if row.get('away_winless'): m *= mults['away_winless']
    if row['saturday']: m *= mults['saturday']
    if row['late_season']: m *= mults['late_season']
    if row['midweek'] and not row.get('lost_bottom') and not row.get('heavy_home_loss'): m *= mults['midweek']
    if row.get('short_rest') and not row.get('lost_bottom') and not row.get('heavy_home_loss'): m *= mults['short_rest']
    if row.get('unbeaten_3'): m *= mults['unbeaten_3']
    return max(m, 0.35)

def predict_one(row, tier_base, mults):
    return tier_base[row['tier']] * decontext_mult(row, mults)

def compute_mae(df, tier_base, mults):
    preds = df.apply(lambda r: predict_one(r, tier_base, mults), axis=1)
    return np.mean(np.abs(preds - df['actual']))

# 2. Iterate
current_mults = dict(CUR_MULT)
best_mae = float('inf')
for it in range(5):
    df_m['decontext'] = df_m.apply(lambda r: r['actual']/decontext_mult(r, current_mults), axis=1)
    new_bases = {}
    for t in TIERS_5:
        sub = df_m[df_m['tier']==t]
        if len(sub)>0: new_bases[t] = round(np.median(sub['decontext'].values)/100)*100
    mae = compute_mae(df_m, new_bases, current_mults)
    print(f"  Iter {it}: bases={new_bases}, MAE={mae:.0f}")
    if it>0 and mae>=best_mae-5: break
    best_mae = mae

final_bases = new_bases
print(f"收敛基值: {final_bases}")

# 3. Grid search
param_grid = {'derby':[1.20,1.25,1.30],'derby_B':[1.02,1.05,1.08,1.10],
    'lost_bottom':[0.60,0.65,0.70],'heavy_home_loss':[0.85,0.90,0.95],
    'away_winless':[0.80,0.82,0.85,0.88],'saturday':[1.12,1.15,1.18],
    'late_season':[0.65,0.70,0.75],'season_opener':[1.12,1.15,1.18],
    'short_rest':[0.70,0.72,0.75],'midweek':[0.78,0.80,0.82],
    'unbeaten_3':[1.00,1.02,1.05]}

best_mults = dict(CUR_MULT)
best_mae_gs = compute_mae(df_m, final_bases, best_mults)
print(f"基线 MAE: {best_mae_gs:.0f}")

for param in ['derby','lost_bottom','heavy_home_loss','away_winless','saturday',
              'late_season','season_opener','midweek','short_rest','derby_B','unbeaten_3']:
    best_val = best_mults[param]; best_local = best_mae_gs
    for val in param_grid.get(param,[best_val]):
        t = dict(best_mults); t[param]=val
        m = compute_mae(df_m, final_bases, t)
        if m < best_local: best_local=m; best_val=val
    if best_val!=best_mults[param]:
        best_mults[param]=best_val; best_mae_gs=best_local
        print(f"  {param}: → {best_val:.2f} (MAE={best_mae_gs:.0f})")

# R2
for param in ['derby','lost_bottom','heavy_home_loss','away_winless','saturday',
              'late_season','season_opener','midweek','short_rest','derby_B','unbeaten_3']:
    for val in param_grid.get(param,[best_mults[param]]):
        t = dict(best_mults); t[param]=val
        m = compute_mae(df_m, final_bases, t)
        if m < best_mae_gs-3:
            best_mults[param]=val; best_mae_gs=m
            print(f"  R2 {param}: → {val:.2f} (MAE={best_mae_gs:.0f})")

# 4. Per-year
print("\n逐场预测:")
for yr in ['2024','2025','2026']:
    sub = df_m[df_m['year']==yr]
    if len(sub)==0: continue
    errs = [abs(predict_one(r, final_bases, best_mults)-r['actual']) for _,r in sub.iterrows()]
    apes = [abs(predict_one(r, final_bases, best_mults)-r['actual'])/r['actual']*100 for _,r in sub.iterrows()]
    print(f"  {yr}: MAE={np.mean(errs):.0f}, MAPE={np.mean(apes):.1f}%")

total_mae = compute_mae(df_m, final_bases, best_mults)
total_mape = np.mean([abs(predict_one(r, final_bases, best_mults)-r['actual'])/r['actual']*100 for _,r in df_m.iterrows()])
print(f"\n全部: MAE={total_mae:.0f}, MAPE={total_mape:.1f}%")
print(f"TIER_BASE = {final_bases}")
print(f"MULTIPLIERS = {best_mults}")