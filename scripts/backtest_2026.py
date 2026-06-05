"""2026 7场回测 (含season_opener)"""
import sys, json
from pathlib import Path
import pandas as pd, numpy as np

ROOT = Path('/home/xxxsuli/ticket-pricing')
sys.path.insert(0, str(ROOT))
from src.rule_engine import predict, get_calibration
from src.classify import classify_opponent_tier, DERBY_RIVALS
from src.csl_context import load_csl_data, get_guoan_matches, detect_ctx
from src.match_notes import get_adjusted_actual

NON_CSL = {'河内公安','大埔','麦克阿瑟FC'}
mf = pd.read_parquet(ROOT/'data/processed/match_features.parquet')
csl = mf[(mf['competition']=='CSL')&(~mf['opponent'].isin(NON_CSL))&(mf['match_date'].str.startswith('2026'))]
matches_data,standings,_ = load_csl_data()
guoan = get_guoan_matches(matches_data)
cal = get_calibration()['tier']

print(f"{'日期':<12} {'对手':<10} {'T':<3} {'实际':>7} {'raw':>7} {'校准':>7} {'误差':>7} {'APE':>5} | 情境")
print('-'*90)

errs_raw = []; errs_cal = []
season_years = set()

for _,m in csl.iterrows():
    opp=m['opponent']; actual = get_adjusted_actual(m['match_id'], int(m['attendance'])); date=m['match_date']; md=pd.Timestamp(date)
    tier=classify_opponent_tier(opp)
    ctx=detect_ctx({'date':date,'opponent':opp,'is_home':True,'completed':True},guoan,standings)
    
    yr=str(md.year)
    is_season_opener = yr not in season_years
    if is_season_opener: season_years.add(yr)
    
    kw={
        'derby':opp in DERBY_RIVALS or any(d in str(opp) for d in DERBY_RIVALS),
        'saturday':md.weekday()==5,'late_season':md.month>=10,
        'season_opener':is_season_opener,
        'midweek':md.weekday()in(1,2,3),
        'away_winless':ctx.get('away_winless',False),'lost_bottom':ctx.get('lost_bottom',False),
        'heavy_home_loss':ctx.get('heavy_home_loss',False),'short_rest':ctx.get('short_rest',False),
        'unbeaten_3':ctx.get('unbeaten_3',False),
    }
    raw=predict(opp,**kw)
    calibrated=raw*cal.get(tier,1.0)
    err=calibrated-actual; ape=abs(err)/actual*100
    errs_raw.append(abs(raw-actual)); errs_cal.append(abs(calibrated-actual))
    active=[{'derby':'德','saturday':'六','late_season':'末','season_opener':'揭',
             'midweek':'中','away_winless':'客','lost_bottom':'弱','heavy_home_loss':'惨',
             'short_rest':'短','unbeaten_3':'不'}.get(k,k[:2]) for k,v in kw.items() if v]
    print(f'{date:<12} {opp:<10} {tier:<3} {actual:>7} {raw:>7.0f} {calibrated:>7.0f} {err:>+7.0f} {ape:>5.1f}% | {",".join(active)}')

print(f'\nraw MAE={np.mean(errs_raw):.0f}  cal MAE={np.mean(errs_cal):.0f}  cal MAPE={np.mean([abs(errs_cal[i])/csl.iloc[i]["attendance"]*100 for i in range(len(csl))]):.1f}%')