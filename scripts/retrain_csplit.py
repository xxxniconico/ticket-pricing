"""C拆C/C2: 大连=低C, 海牛=高C"""
import sys, json
from pathlib import Path
import pandas as pd, numpy as np

ROOT = Path("/home/xxxsuli/ticket-pricing")
sys.path.insert(0, str(ROOT))

# Temp override classifier
import src.classify as cl
old_C = cl.C_TIER
cl.C_TIER = {'大连英博','大连英博海发','辽宁铁人','重庆铜梁龙'}
cl.C2_TIER = {'青岛海牛','沧州雄狮','南通支云'}
_old_cls = cl.classify_opponent_tier
def _new_cls(opp):
    o=str(opp).strip()
    if any(t in o or o in t for t in cl.S_TIER): return "S"
    if any(t in o or o in t for t in cl.A_TIER): return "A"
    if any(t in o or o in t for t in cl.B_TIER): return "B"
    if any(t in o or o in t for t in cl.C_TIER): return "C"
    if any(t in o or o in t for t in cl.C2_TIER): return "C2"
    return "B"
cl.classify_opponent_tier = _new_cls

from src.rule_engine import predict, TIER_BASE
from src.csl_context import load_csl_data, get_guoan_matches, detect_ctx
from src.match_notes import get_adjusted_actual

NON_CSL = {'河内公安','大埔','麦克阿瑟FC'}
mf = pd.read_parquet(ROOT/'data/processed/match_features.parquet')
csl = mf[(mf['competition']=='CSL')&(~mf['opponent'].isin(NON_CSL))].sort_values('match_date')
matches_data,standings,_ = load_csl_data(); guoan=get_guoan_matches(matches_data)

TIERS = ['S','A','B','C','C2']

records = []
for _,m in csl.iterrows():
    opp=m['opponent']; actual=get_adjusted_actual(m['match_id'],int(m['attendance']))
    date=m['match_date']; md=pd.Timestamp(date); tier=_new_cls(opp)
    ctx=detect_ctx({'date':date,'opponent':opp,'is_home':True,'completed':True},guoan,standings)
    records.append({'date':date,'opponent':opp,'tier':tier,'actual':actual,'year':date[:4],
        'derby':opp in cl.DERBY_RIVALS or any(d in str(opp) for d in cl.DERBY_RIVALS),
        'saturday':md.weekday()==5,'late_season':md.month>=10,'midweek':md.weekday()in(1,2,3),
        'away_winless':ctx.get('away_winless',False),'lost_bottom':ctx.get('lost_bottom',False),
        'heavy_home_loss':ctx.get('heavy_home_loss',False),'short_rest':ctx.get('short_rest',False),
        'unbeaten_3':ctx.get('unbeaten_3',False),
    })
df_m = pd.DataFrame(records)

print("C拆分后构成:")
for t in TIERS:
    sub=df_m[df_m['tier']==t]
    if len(sub)==0: continue
    vals=sub['actual'].values
    opps=sub.groupby('opponent')['actual'].mean().sort_values(ascending=False)
    print(f"  {t}: n={len(sub)} mean={vals.mean():.0f} median={np.median(vals):.0f} cv={np.std(vals)/np.mean(vals):.2f}")
    for o,v in opps.items(): print(f"      {o}: {v:.0f}")

# Decontext + iterate
CUR_MULT = {'derby':1.25,'derby_B':1.05,'lost_bottom':0.65,'heavy_home_loss':0.90,
            'away_winless':0.82,'saturday':1.15,'late_season':0.75,'season_opener':1.15,
            'short_rest':0.72,'midweek':0.80,'unbeaten_3':1.02}

def dm(row,mults):
    m=1.0
    if row['derby']:
        if row['tier']!='S': m*=mults['derby_B'] if row['tier']=='A' else mults['derby']
    if row.get('lost_bottom'): m*=0.78 if row['tier']in('S','A') else mults['lost_bottom']
    elif row.get('heavy_home_loss'): m*=mults['heavy_home_loss']
    if row.get('away_winless'): m*=mults['away_winless']
    if row['saturday']: m*=mults['saturday']
    if row['late_season']: m*=mults['late_season']
    if row['midweek']and not row.get('lost_bottom')and not row.get('heavy_home_loss'): m*=mults['midweek']
    if row.get('short_rest')and not row.get('lost_bottom')and not row.get('heavy_home_loss'): m*=mults['short_rest']
    if row.get('unbeaten_3'): m*=mults['unbeaten_3']
    return max(m,0.35)

def pred1(row,bases,mults): return bases.get(row['tier'],8600)*dm(row,mults)
def mae(df,bases,mults):
    ps=df.apply(lambda r:pred1(r,bases,mults),axis=1)
    return np.mean(np.abs(ps-df['actual']))

current_mults=dict(CUR_MULT)
for it in range(5):
    df_m['dc']=df_m.apply(lambda r:r['actual']/dm(r,current_mults),axis=1)
    nb={}
    for t in TIERS:
        sub=df_m[df_m['tier']==t]
        if len(sub)>0: nb[t]=round(np.median(sub['dc'].values)/100)*100
    m=mae(df_m,nb,current_mults)
    print(f"  Iter {it}: bases={nb} MAE={m:.0f}")
    if it>0 and m>=best_mae-5: break
    best_mae=m
fb=nb
print(f"收敛: {fb}")

# Grid search
pg={'derby':[1.20,1.25],'derby_B':[1.02,1.05,1.08],'lost_bottom':[0.60,0.65,0.70],
    'heavy_home_loss':[0.85,0.90],'away_winless':[0.80,0.82,0.85],'saturday':[1.12,1.15,1.18],
    'late_season':[0.70,0.75],'season_opener':[1.12,1.15],'short_rest':[0.70,0.72,0.75],
    'midweek':[0.78,0.80,0.82],'unbeaten_3':[1.00,1.02]}
bm=dict(CUR_MULT); bgm=mae(df_m,fb,bm)
for p in ['derby','lost_bottom','heavy_home_loss','away_winless','saturday',
          'late_season','season_opener','midweek','short_rest','derby_B','unbeaten_3']:
    bv=bm[p]; bl=bgm
    for v in pg.get(p,[bv]):
        t=dict(bm); t[p]=v; m=mae(df_m,fb,t)
        if m<bl: bl=m; bv=v
    if bv!=bm[p]: bm[p]=bv; bgm=bl; print(f"  {p}: →{bv:.2f} MAE={bgm:.0f}")

for yr in ['2024','2025','2026']:
    sub=df_m[df_m['year']==yr]
    if len(sub)==0: continue
    es=[abs(pred1(r,fb,bm)-r['actual']) for _,r in sub.iterrows()]
    print(f"  {yr}: MAE={np.mean(es):.0f}")

total=mae(df_m,fb,bm)
print(f"\n全部: MAE={total:.0f}")
print(f"TIER_BASE={fb}")
print(f"MULTIPLIERS={bm}")

# Restore
cl.classify_opponent_tier=_old_cls; cl.C_TIER=old_C
if hasattr(cl,'C2_TIER'): del cl.C2_TIER