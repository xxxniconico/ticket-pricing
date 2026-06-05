"""Ablation: unbeaten_3 分级 + C_base 调整"""
import sys, pandas as pd, numpy as np
from pathlib import Path

ROOT = Path('/home/xxxsuli/ticket-pricing')
sys.path.insert(0, str(ROOT))
from src.rule_engine import predict, TIER_BASE, MULTIPLIERS
from src.classify import classify_opponent_tier, DERBY_RIVALS
from src.csl_context import load_csl_data, get_guoan_matches, detect_ctx

NON_CSL = {'河内公安','大埔','麦克阿瑟FC'}
mf = pd.read_parquet(ROOT/'data/processed/match_features.parquet')
csl = mf[(mf['competition']=='CSL')&(~mf['opponent'].isin(NON_CSL))&(mf['match_date'].str.startswith('2026'))]
matches_data,standings,_ = load_csl_data()
guoan = get_guoan_matches(matches_data)

# Build all 2026 records with context
records = []
for _,m in csl.iterrows():
    opp=m['opponent']; actual=int(m['attendance']); date=m['match_date']; md=pd.Timestamp(date)
    tier=classify_opponent_tier(opp)
    ctx=detect_ctx({'date':date,'opponent':opp,'is_home':True,'completed':True},guoan,standings)
    records.append({
        'date':date,'opponent':opp,'tier':tier,'actual':actual,
        'derby':opp in DERBY_RIVALS or any(d in str(opp) for d in DERBY_RIVALS),
        'saturday':md.weekday()==5,'late_season':md.month>=10,
        'season_opener':date=='2026-03-21',
        'midweek':md.weekday()in(1,2,3),'away_winless':ctx.get('away_winless',False),
        'lost_bottom':ctx.get('lost_bottom',False),'heavy_home_loss':ctx.get('heavy_home_loss',False),
        'short_rest':ctx.get('short_rest',False),'unbeaten_3':ctx.get('unbeaten_3',False),
    })

def test_config(label, mods):
    """mods: dict of multiplier overrides or base overrides"""
    import src.rule_engine as re
    old_mults = dict(re.MULTIPLIERS)
    old_bases = dict(re.TIER_BASE)
    
    for k,v in mods.get('multipliers',{}).items():
        re.MULTIPLIERS[k] = v
    for k,v in mods.get('bases',{}).items():
        re.TIER_BASE[k] = v
    
    print(f"\n{label}:")
    print(f"{'日期':<12} {'对手':<10} {'实际':>7} {'预测':>7} {'误差':>7} {'APE':>5}")
    errs = []
    for r in records:
        raw = predict(r['opponent'], derby=r['derby'], saturday=r['saturday'],
                      late_season=r['late_season'], season_opener=r['season_opener'],
                      midweek=r['midweek'], away_winless=r['away_winless'],
                      lost_bottom=r['lost_bottom'], heavy_home_loss=r['heavy_home_loss'],
                      short_rest=r['short_rest'], unbeaten_3=r.get('unbeaten_3',False))
        err = raw - r['actual']; ape = abs(err)/r['actual']*100
        errs.append(abs(err))
        mark = '<<<' if r['opponent'] in ('青岛海牛','河南') else ''
        print(f"  {r['date']} {r['opponent']:<10} {r['actual']:>7} {raw:>7.0f} {err:>+7.0f} {ape:>5.1f}% {mark}")
    print(f"  MAE={np.mean(errs):.0f}")
    
    re.MULTIPLIERS.update(old_mults)
    re.TIER_BASE.update(old_bases)
    return np.mean(errs)

# Baseline
base_mae = test_config('A: 当前 V4.6', {})

# B: unbeaten_3 = 1.0
test_config('B: unbeaten_3=1.0 (移除)', {'multipliers': {'unbeaten_3': 1.0}})

# C: unbeaten_3 分级：S/A=1.02, B/C=1.0
# Need to modify the predict function logic... too complex for a quick test
# Instead: unbeaten_3=1.0 + 青岛海牛→B

# D: C_base=4300
test_config('D: C_base 3800→4300', {'bases': {'C': 4300}})

# E: C_base=4300 + unbeaten_3=1.0  
test_config('E: C_base=4300 + unbeaten_3=1.0', {'bases': {'C': 4300}, 'multipliers': {'unbeaten_3': 1.0}})

# F: 青岛海牛→B (回退之前的分级实验)
# This requires classifier change... let's test a simplified version
# Treat 青岛海牛 as B-tier by overriding base lookup
original = dict(TIER_BASE)
import src.rule_engine as re

def predict_with_override(opp, tier_override=None, **kw):
    if tier_override:
        re.TIER_BASE['_temp'] = re.TIER_BASE[tier_override]
    # hack: monkeypatch
    old = re.TIER_BASE.get('C', 3800)
    if opp == '青岛海牛' and tier_override == 'B':
        re.TIER_BASE['C'] = re.TIER_BASE['B']
    result = predict(opp, **kw)
    if opp == '青岛海牛' and tier_override == 'B':
        re.TIER_BASE['C'] = old
    return result

print("\nF: 青岛海牛→B (等效B_base=8600)")
errs = []
for r in records:
    if r['opponent'] == '青岛海牛':
        raw = re.TIER_BASE['B']  # no multipliers for this match (only unbeaten_3)
        if r['unbeaten_3']: raw *= re.MULTIPLIERS['unbeaten_3']
    else:
        raw = predict(r['opponent'], derby=r['derby'], saturday=r['saturday'],
                      late_season=r['late_season'], season_opener=r['season_opener'],
                      midweek=r['midweek'], away_winless=r['away_winless'],
                      lost_bottom=r['lost_bottom'], heavy_home_loss=r['heavy_home_loss'],
                      short_rest=r['short_rest'], unbeaten_3=r.get('unbeaten_3',False))
    err = raw - r['actual']; ape = abs(err)/r['actual']*100
    errs.append(abs(err))
    mark = '<<<' if r['opponent'] in ('青岛海牛','河南') else ''
    print(f"  {r['date']} {r['opponent']:<10} {r['actual']:>7} {raw:>7.0f} {err:>+7.0f} {ape:>5.1f}% {mark}")
print(f"  MAE={np.mean(errs):.0f}")