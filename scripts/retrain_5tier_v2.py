"""5级制 V2: B/BL 拆分 (河南+西海岸单独成级)"""
import sys, json
from pathlib import Path
import pandas as pd, numpy as np

ROOT = Path("/home/xxxsuli/ticket-pricing")
sys.path.insert(0, str(ROOT))

# 临时改分级
import src.classify as cl
old_B = cl.B_TIER
cl.B_TIER = {'长春亚泰','深圳新鹏城','云南玉昆','武汉三镇',
             '浙江','浙江队','浙江俱乐部绿城','上海海港','梅州客家'}
cl.BL_TIER = {'河南','河南队','河南俱乐部酒祖杜康','河南队俱乐部彩陶坊','青岛西海岸'}
cl.C_TIER = {'大连英博','大连英博海发','青岛海牛','辽宁铁人','重庆铜梁龙','沧州雄狮','南通支云'}

# 修改 classify_opponent_tier
_old_cls = cl.classify_opponent_tier
def _new_cls(opp):
    o = str(opp).strip()
    if any(t in o or o in t for t in cl.S_TIER): return "S"
    if any(t in o or o in t for t in cl.A_TIER): return "A"
    if any(t in o or o in t for t in cl.B_TIER): return "B"
    if any(t in o or o in t for t in cl.BL_TIER): return "BL"
    if any(t in o or o in t for t in cl.C_TIER): return "C"
    return "B"
cl.classify_opponent_tier = _new_cls

from src.rule_engine import predict, TIER_BASE
from src.csl_context import load_csl_data, get_guoan_matches, detect_ctx

NON_CSL = {'河内公安','大埔','麦克阿瑟FC'}
mf = pd.read_parquet(ROOT/'data/processed/match_features.parquet')
csl = mf[(mf['competition']=='CSL')&(~mf['opponent'].isin(NON_CSL))].sort_values('match_date')
matches_data,standings,_ = load_csl_data()
guoan = get_guoan_matches(matches_data)

TIERS_5 = ['S','A','B','BL','C']

# Records
records = []
for _,m in csl.iterrows():
    opp=m['opponent']; actual=int(m['attendance']); date=m['match_date']; md=pd.Timestamp(date)
    tier=_new_cls(opp)
    ctx=detect_ctx({'date':date,'opponent':opp,'is_home':True,'completed':True},guoan,standings)
    records.append({'date':date,'opponent':opp,'tier':tier,'actual':actual,'year':date[:4],
        'derby':opp in cl.DERBY_RIVALS or any(d in str(opp) for d in cl.DERBY_RIVALS),
        'saturday':md.weekday()==5,'late_season':md.month>=10,'midweek':md.weekday()in(1,2,3),
        'away_winless':ctx.get('away_winless',False),'lost_bottom':ctx.get('lost_bottom',False),
        'heavy_home_loss':ctx.get('heavy_home_loss',False),'short_rest':ctx.get('short_rest',False),
        'unbeaten_3':ctx.get('unbeaten_3',False),
    })
df_m = pd.DataFrame(records)

# Show tier composition
print("分级构成:")
for t in TIERS_5:
    sub = df_m[df_m['tier']==t]
    if len(sub)==0: continue
    vals = sub['actual'].values
    opps = sub.groupby('opponent')['actual'].mean().sort_values(ascending=False)
    print(f"  {t}: n={len(sub)} mean={vals.mean():.0f} median={np.median(vals):.0f} cv={np.std(vals)/np.mean(vals):.2f}")
    for o,v in opps.items():
        print(f"      {o}: {v:.0f}")

# 反推基值
CUR_MULT = {'derby':1.25,'derby_B':1.05,'lost_bottom':0.65,'heavy_home_loss':0.85,
            'away_winless':0.80,'saturday':1.15,'late_season':0.70,'season_opener':1.15,
            'short_rest':0.72,'midweek':0.80,'unbeaten_3':1.00}

def decontext_mult(row, mults):
    m = 1.0
    if row['derby']:
        if row['tier']!='S':
            if row['tier']=='A': m*=mults.get('derby_B',1.15)
            else: m*=mults['derby']
    if row.get('lost_bottom'): m*=0.78 if row['tier']in('S','A') else mults['lost_bottom']
    elif row.get('heavy_home_loss'): m*=mults['heavy_home_loss']
    if row.get('away_winless'): m*=mults['away_winless']
    if row['saturday']: m*=mults['saturday']
    if row['late_season']: m*=mults['late_season']
    if row['midweek']and not row.get('lost_bottom')and not row.get('heavy_home_loss'): m*=mults['midweek']
    if row.get('short_rest')and not row.get('lost_bottom')and not row.get('heavy_home_loss'): m*=mults['short_rest']
    if row.get('unbeaten_3'): m*=mults['unbeaten_3']
    return max(m,0.35)

def predict_one(row, bases, mults):
    return bases.get(row['tier'],8600)*decontext_mult(row,mults)

def compute_mae(df, bases, mults):
    preds = df.apply(lambda r:predict_one(r,bases,mults),axis=1)
    return np.mean(np.abs(preds-df['actual']))

# Iterate
current_mults = dict(CUR_MULT)
for it in range(5):
    df_m['decontext'] = df_m.apply(lambda r:r['actual']/decontext_mult(r,current_mults),axis=1)
    new_bases = {}
    for t in TIERS_5:
        sub=df_m[df_m['tier']==t]
        if len(sub)>0: new_bases[t]=round(np.median(sub['decontext'].values)/100)*100
    mae=compute_mae(df_m,new_bases,current_mults)
    print(f"  Iter {it}: bases={new_bases}, MAE={mae:.0f}")
    if it>0 and mae>=best_mae-5: break
    best_mae=mae

final_bases = new_bases
print(f"收敛: {final_bases}")

# Grid search
param_grid = {'derby':[1.20,1.25,1.30],'derby_B':[1.02,1.05,1.08],
    'lost_bottom':[0.60,0.65,0.70],'heavy_home_loss':[0.85,0.90],
    'away_winless':[0.80,0.82,0.85],'saturday':[1.12,1.15,1.18],
    'late_season':[0.65,0.70,0.75],'season_opener':[1.12,1.15],
    'short_rest':[0.70,0.72,0.75],'midweek':[0.78,0.80,0.82],
    'unbeaten_3':[1.00,1.02]}

best_mults = dict(CUR_MULT)
best_mae_gs = compute_mae(df_m, final_bases, best_mults)
for param in ['derby','lost_bottom','heavy_home_loss','away_winless','saturday',
              'late_season','season_opener','midweek','short_rest','derby_B','unbeaten_3']:
    best_val=best_mults[param]; best_local=best_mae_gs
    for val in param_grid.get(param,[best_val]):
        t=dict(best_mults); t[param]=val
        m=compute_mae(df_m,final_bases,t)
        if m<best_local: best_local=m; best_val=val
    if best_val!=best_mults[param]:
        best_mults[param]=best_val; best_mae_gs=best_local
        print(f"  {param}: →{best_val:.2f} MAE={best_mae_gs:.0f}")

# Per-year
for yr in ['2024','2025','2026']:
    sub=df_m[df_m['year']==yr]
    if len(sub)==0: continue
    errs=[abs(predict_one(r,final_bases,best_mults)-r['actual']) for _,r in sub.iterrows()]
    print(f"  {yr}: MAE={np.mean(errs):.0f}")

total=compute_mae(df_m,final_bases,best_mults)
print(f"\n全部: MAE={total:.0f}")
print(f"TIER_BASE={final_bases}")
print(f"MULTIPLIERS={best_mults}")

# Restore classifier
cl.classify_opponent_tier = _old_cls
cl.B_TIER = old_B
if hasattr(cl,'BL_TIER'): del cl.BL_TIER