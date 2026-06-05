"""C_base 最优值扫描"""
import sys, pandas as pd, numpy as np
from pathlib import Path

ROOT = Path('/home/xxxsuli/ticket-pricing')
sys.path.insert(0, str(ROOT))

# Keep all other params fixed
from src.rule_engine import predict, TIER_BASE, MULTIPLIERS
from src.classify import classify_opponent_tier, DERBY_RIVALS
from src.csl_context import load_csl_data, get_guoan_matches, detect_ctx
from src.match_notes import get_adjusted_actual

NON_CSL = {'河内公安','大埔','麦克阿瑟FC'}
mf = pd.read_parquet(ROOT/'data/processed/match_features.parquet')
csl = mf[(mf['competition']=='CSL')&(~mf['opponent'].isin(NON_CSL))&(mf['match_date'].str.startswith('2026'))]
matches_data,standings,_ = load_csl_data()
guoan = get_guoan_matches(matches_data)

# Build 2026 records
records = []
for _,m in csl.iterrows():
    opp=m['opponent']; actual=get_adjusted_actual(m['match_id'],int(m['attendance']))
    date=m['match_date']; md=pd.Timestamp(date)
    ctx=detect_ctx({'date':date,'opponent':opp,'is_home':True,'completed':True},guoan,standings)
    records.append({
        'opponent':opp,'actual':actual,'tier':classify_opponent_tier(opp),
        'derby':opp in DERBY_RIVALS or any(d in str(opp) for d in DERBY_RIVALS),
        'saturday':md.weekday()==5,'late_season':md.month>=10,
        'season_opener':date=='2026-03-21','midweek':md.weekday()in(1,2,3),
        'away_winless':ctx.get('away_winless',False),'lost_bottom':ctx.get('lost_bottom',False),
        'heavy_home_loss':ctx.get('heavy_home_loss',False),'short_rest':ctx.get('short_rest',False),
        'unbeaten_3':ctx.get('unbeaten_3',False),
    })

import src.rule_engine as re
old_c = re.TIER_BASE['C']

print(f"{'C_base':>7} {'MAE':>6} {'大连err':>7} {'海牛err':>7} {'大连APE':>6} {'海牛APE':>6}")
print("-" * 50)

for c_base in range(3500, 7001, 250):
    re.TIER_BASE['C'] = c_base
    errs = []
    dl_err = hn_err = None
    for r in records:
        kw = {k:r[k] for k in ['derby','saturday','late_season','season_opener','midweek',
                                'away_winless','lost_bottom','heavy_home_loss','short_rest','unbeaten_3']}
        raw = predict(r['opponent'], **kw)
        err = abs(raw - r['actual'])
        errs.append(err)
        if '大连' in r['opponent']: dl_err = raw - r['actual']
        if '青岛海牛' in r['opponent']: hn_err = raw - r['actual']
    
    mae = np.mean(errs)
    dl_ape = abs(dl_err)/[r['actual'] for r in records if '大连' in r['opponent']][0]*100 if dl_err else 0
    hn_ape = abs(hn_err)/[r['actual'] for r in records if '青岛海牛' in r['opponent']][0]*100 if hn_err else 0
    
    marker = ''
    if mae < 500: marker = '★'
    print(f"{c_base:>7} {mae:>6.0f} {dl_err:>+7.0f} {hn_err:>+7.0f} {dl_ape:>5.1f}% {hn_ape:>5.1f}% {marker}")

re.TIER_BASE['C'] = old_c