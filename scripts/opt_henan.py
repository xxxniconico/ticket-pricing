"""河南优化: OPP_DEVIATION + saturday微调"""
import sys, pandas as pd, numpy as np
from pathlib import Path

ROOT = Path('/home/xxxsuli/ticket-pricing')
sys.path.insert(0, str(ROOT))
from src.rule_engine import predict, TIER_BASE, MULTIPLIERS
from src.classify import classify_opponent_tier, DERBY_RIVALS
from src.csl_context import load_csl_data, get_guoan_matches, detect_ctx

NON_CSL = {'河内公安','大埔','麦克阿瑟FC'}
mf = pd.read_parquet(ROOT/'data/processed/match_features.parquet')
csl = mf[(mf['competition']=='CSL')&(~mf['opponent'].isin(NON_CSL))].sort_values('match_date')
matches_data,standings,_ = load_csl_data()
guoan = get_guoan_matches(matches_data)

records = []
for _,m in csl.iterrows():
    opp=m['opponent']; actual=int(m['attendance']); date=m['match_date']; md=pd.Timestamp(date)
    tier=classify_opponent_tier(opp)
    ctx=detect_ctx({'date':date,'opponent':opp,'is_home':True,'completed':True},guoan,standings)
    records.append({'date':date,'opponent':opp,'tier':tier,'actual':actual,'year':date[:4],
        'derby':opp in DERBY_RIVALS or any(d in str(opp) for d in DERBY_RIVALS),
        'saturday':md.weekday()==5,'late_season':md.month>=10,
        'season_opener':date=='2026-03-21',
        'midweek':md.weekday()in(1,2,3),'away_winless':ctx.get('away_winless',False),
        'lost_bottom':ctx.get('lost_bottom',False),'heavy_home_loss':ctx.get('heavy_home_loss',False),
        'short_rest':ctx.get('short_rest',False),'unbeaten_3':ctx.get('unbeaten_3',False),
    })

def test_config(label, opp_devs=None, mult_overrides=None):
    import src.rule_engine as re
    old_devs = dict(re.OPP_DEVIATION)
    old_mults = dict(re.MULTIPLIERS)
    
    if opp_devs: re.OPP_DEVIATION.update(opp_devs)
    if mult_overrides: re.MULTIPLIERS.update(mult_overrides)
    
    errs = []; hn_errs = []; qd_errs = []
    for r in records:
        kw = {k:r[k] for k in ['derby','saturday','late_season','season_opener','midweek',
                                'away_winless','lost_bottom','heavy_home_loss','short_rest','unbeaten_3']}
        raw = predict(r['opponent'], **kw)
        err = abs(raw - r['actual'])
        errs.append(err)
        if r['opponent'] in ('河南','河南队','河南俱乐部酒祖杜康','河南队俱乐部彩陶坊'):
            hn_errs.append((r['date'], r['actual'], raw, err))
        if r['opponent'] == '青岛海牛':
            qd_errs.append((r['date'], r['actual'], raw, err))
    
    re.OPP_DEVIATION.update(old_devs)
    re.MULTIPLIERS.update(old_mults)
    
    hn_str = ' | '.join([f"{d}:{a}→{p:.0f}({e:.0f})" for d,a,p,e in hn_errs])
    print(f"  {label}: MAE={np.mean(errs):.0f} | 河南: {hn_str}")
    return np.mean(errs)

# Baseline
print("河南优化扫描:")
test_config('A: 当前(d海牛=1.4)', {})

# B: Add 河南 OPP_DEVIATION
for d in [0.88, 0.90, 0.92, 0.94, 0.95, 0.96, 0.98]:
    test_config(f'B: 河南×{d:.2f}', {'河南': d, '河南队': d, '河南俱乐部酒祖杜康': d, '河南队俱乐部彩陶坊': d})

# C: Reduce saturday
for s in [1.12, 1.13, 1.14]:
    test_config(f'C: sat={s:.2f}', mult_overrides={'saturday': s})

# D: Both
for d in [0.92, 0.94, 0.95]:
    for s in [1.13, 1.14, 1.15]:
        test_config(f'D: 河南×{d:.2f}+sat={s:.2f}', 
                    {'河南': d, '河南队': d, '河南俱乐部酒祖杜康': d, '河南队俱乐部彩陶坊': d},
                    {'saturday': s})