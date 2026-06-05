"""验证 saturday=1.10 vs 1.15"""
import sys, pandas as pd, numpy as np
from pathlib import Path

ROOT = Path("/home/xxxsuli/ticket-pricing")
sys.path.insert(0, str(ROOT))
from src.rule_engine import predict, TIER_BASE, MULTIPLIERS
from src.classify import classify_opponent_tier, DERBY_RIVALS
from src.csl_context import load_csl_data, get_guoan_matches, detect_ctx

NON_CSL = {"河内公安", "大埔", "麦克阿瑟FC"}
mf = pd.read_parquet(ROOT / "data/processed/match_features.parquet")
csl = mf[(mf['competition']=='CSL') & (~mf['opponent'].isin(NON_CSL))].sort_values('match_date')
matches_data, standings, _ = load_csl_data()
guoan_all = get_guoan_matches(matches_data)

def test_mult(sat_val):
    import copy
    mults = dict(MULTIPLIERS)
    mults['saturday'] = sat_val
    
    # Monkey-patch
    import src.rule_engine as re
    old = dict(re.MULTIPLIERS)
    re.MULTIPLIERS.update(mults)
    
    errors = []
    sat_errors = []
    nonsat_errors = []
    for _, m in csl.iterrows():
        opp = m['opponent']; actual = int(m['attendance']); date = m['match_date']
        md = pd.Timestamp(date); tier = classify_opponent_tier(opp)
        
        match_obj = {"date":date,"opponent":opp,"is_home":True,"completed":True}
        ctx = detect_ctx(match_obj, guoan_all, standings)
        
        is_sat = md.weekday() == 5
        pred_kw = {
            'derby': opp in DERBY_RIVALS or any(d in str(opp) for d in DERBY_RIVALS),
            'saturday': is_sat,
            'late_season': md.month >= 10,
            'midweek': md.weekday() in (1,2,3),
            'away_winless': ctx.get('away_winless',False),
            'lost_bottom': ctx.get('lost_bottom',False),
            'heavy_home_loss': ctx.get('heavy_home_loss',False),
            'short_rest': ctx.get('short_rest',False),
            'unbeaten_3': ctx.get('unbeaten_3',False),
        }
        raw = predict(opp, **pred_kw)
        err = abs(raw - actual)
        errors.append(err)
        if is_sat: sat_errors.append(err)
        else: nonsat_errors.append(err)
    
    re.MULTIPLIERS.update(old)
    
    n_sat = len(sat_errors)
    n_nonsat = len(nonsat_errors)
    print(f"  saturday={sat_val}: MAE总={np.mean(errors):.0f}, 周六MAE={np.mean(sat_errors):.0f}(n={n_sat}), 非周六MAE={np.mean(nonsat_errors):.0f}(n={n_nonsat})")

print("saturday 乘数对比:")
test_mult(1.00)
test_mult(1.10)
test_mult(1.15)
test_mult(1.18)
test_mult(1.20)