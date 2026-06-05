"""青岛海牛: OPP_DEVIATION 最优值"""
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

# Build all records
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

def predict_with_dev(opp, dev_map, **kw):
    """Apply OPP_DEVIATION inline"""
    for key, dev in dev_map.items():
        if key in opp or opp in key:
            base = TIER_BASE.get(classify_opponent_tier(opp), 8100) * dev
            # Manually compute prediction with deviated base
            import src.rule_engine as re
            old = dict(re.TIER_BASE)
            t = classify_opponent_tier(opp)
            re.TIER_BASE[t] = base
            result = predict(opp, **kw)
            re.TIER_BASE.update(old)
            return result
    return predict(opp, **kw)

def test_dev(d, label):
    dev_map = {'青岛海牛': d}
    errs = []; hnerrs = []
    for r in records:
        kw = {k:r[k] for k in ['derby','saturday','late_season','season_opener','midweek',
                                'away_winless','lost_bottom','heavy_home_loss','short_rest','unbeaten_3']}
        raw = predict_with_dev(r['opponent'], dev_map, **kw)
        err = abs(raw - r['actual'])
        errs.append(err)
        if r['opponent'] == '青岛海牛': hnerrs.append((r['date'], r['actual'], raw, err))
    
    mae = np.mean(errs)
    # Show 青岛海牛 details
    hn_str = ' | '.join([f"{d}:{a}→{p:.0f}({e:.0f})" for d,a,p,e in hnerrs])
    print(f"  d={d:.2f}: MAE总={mae:.0f} | 海牛: {hn_str}")
    return mae

print("青岛海牛 OPP_DEVIATION 扫描:")
print(f"  当前(d=1.0, 无偏差):")
test_dev(1.0, 'baseline')

best_d, best_mae = 1.0, test_dev(1.0, '')
for d in [1.1, 1.2, 1.3, 1.35, 1.4, 1.45, 1.5, 1.6]:
    m = test_dev(d, '')
    if m < best_mae: best_d, best_mae = d, m

print(f"\n最优: d={best_d:.2f}, MAE总={best_mae:.0f}")

# Show detailed comparison for best d
print(f"\n详细对比 (d={best_d:.2f}):")
dev_map = {'青岛海牛': best_d}
for yr in ['2024','2025','2026']:
    yr_recs = [r for r in records if r['year']==yr]
    errs_old = []; errs_new = []
    for r in yr_recs:
        kw = {k:r[k] for k in ['derby','saturday','late_season','season_opener','midweek',
                                'away_winless','lost_bottom','heavy_home_loss','short_rest','unbeaten_3']}
        old_raw = predict(r['opponent'], **kw)
        new_raw = predict_with_dev(r['opponent'], dev_map, **kw)
        errs_old.append(abs(old_raw-r['actual']))
        errs_new.append(abs(new_raw-r['actual']))
    print(f"  {yr}: MAE {np.mean(errs_old):.0f} → {np.mean(errs_new):.0f}")