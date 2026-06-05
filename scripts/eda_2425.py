"""2024-2025训练数据探索"""
import pandas as pd, numpy as np, sys
from pathlib import Path

ROOT = Path('/home/xxxsuli/ticket-pricing')
sys.path.insert(0, str(ROOT))
from src.classify import classify_opponent_tier, DERBY_RIVALS
from src.match_notes import get_adjusted_actual
from src.csl_context import load_csl_data, get_guoan_matches, detect_ctx

NON_CSL = {'河内公安','大埔','麦克阿瑟FC'}
mf = pd.read_parquet(ROOT/'data/processed/match_features.parquet')
train = mf[(mf['competition']=='CSL')&(~mf['opponent'].isin(NON_CSL))&(mf['match_date'].str.startswith(('2024','2025')))].sort_values('match_date')

matches_data,standings,_ = load_csl_data()
guoan = get_guoan_matches(matches_data)

print(f"训练集: {len(train)} 场 (2024:{len(train[train['match_date'].str.startswith('2024')])} 2025:{len(train[train['match_date'].str.startswith('2025')])})")

# Build records with context
records = []
for _,m in train.iterrows():
    opp=m['opponent']; actual=get_adjusted_actual(m['match_id'],int(m['attendance']))
    date=m['match_date']; md=pd.Timestamp(date); tier=classify_opponent_tier(opp)
    ctx=detect_ctx({'date':date,'opponent':opp,'is_home':True,'completed':True},guoan,standings)
    records.append({
        'date':date,'opponent':opp,'tier':tier,'actual':actual,'year':date[:4],'month':md.month,
        'derby':opp in DERBY_RIVALS or any(d in str(opp) for d in DERBY_RIVALS),
        'saturday':md.weekday()==5,'late_season':md.month>=10,'midweek':md.weekday()in(1,2,3),
        'away_winless':ctx.get('away_winless',False),'lost_bottom':ctx.get('lost_bottom',False),
        'heavy_home_loss':ctx.get('heavy_home_loss',False),'short_rest':ctx.get('short_rest',False),
        'unbeaten_3':ctx.get('unbeaten_3',False),
    })
df = pd.DataFrame(records)

# 1. Tier stats
print("\n=== 1. 分级统计 ===")
for t in ['S','A','B','C']:
    sub = df[df['tier']==t]
    if len(sub)==0: continue
    print(f"  {t}: n={len(sub)}, mean={sub['actual'].mean():.0f}, median={sub['actual'].median():.0f}, cv={sub['actual'].std()/sub['actual'].mean():.2f}, range={sub['actual'].min():.0f}-{sub['actual'].max():.0f}")

# 2. By opponent
print("\n=== 2. 对手均值 ===")
opp_stats = df.groupby('opponent').agg(mean=('actual','mean'),n=('actual','count'),tier=('tier','first')).reset_index().sort_values('mean',ascending=False)
for _,r in opp_stats.iterrows():
    print(f"  {r['opponent']:<12} {r['tier']} mean={r['mean']:.0f} n={int(r['n'])}")

# 3. Year-over-year change
print("\n=== 3. 跨年变化(同对手) ===")
for opp in opp_stats[opp_stats['n']>=2]['opponent']:
    sub = df[df['opponent']==opp].sort_values('date')
    yrs = sub[['year','actual']].values
    changes = []
    for i in range(1,len(yrs)):
        changes.append(f"{yrs[i][0]}:{yrs[i][1]:.0f}")
    if len(changes)>0:
        delta = yrs[-1][1]-yrs[0][1]
        print(f"  {opp:<12}: {yrs[0][0]}:{yrs[0][1]:.0f} → {'→'.join(changes)}  Δ={delta:+.0f}")

# 4. 情境乘数实证
print("\n=== 4. 情境效应(同级内比值) ===")
for flag,label in [('saturday','周六'),('derby','德比'),('late_season','末段'),('midweek','周中')]:
    yes=df[df[flag]]; no=df[~df[flag]]
    ratios=[]
    for t in ['S','A','B','C']:
        yt=yes[yes['tier']==t]; nt=no[no['tier']==t]
        if len(yt)>0 and len(nt)>0: ratios.append(yt['actual'].mean()/nt['actual'].mean())
    if ratios: print(f"  {label}: {len(yes)}场 vs {len(no)}场, 同级倍数={np.mean(ratios):.3f}")

# 5. 残差异常
print("\n=== 5. 同级均值偏离>25% ===")
df['tier_mean'] = df.groupby('tier')['actual'].transform('mean')
df['resid_pct'] = (df['actual']-df['tier_mean'])/df['tier_mean']*100
outliers = df[abs(df['resid_pct'])>25].sort_values('resid_pct')
for _,r in outliers.iterrows():
    print(f"  {r['date']} {r['opponent']:<12} {r['tier']} actual={r['actual']:.0f} tier_mean={r['tier_mean']:.0f} {r['resid_pct']:+.0f}%")

# 6. B/C级间差距
print("\n=== 6. B/C级自然断点 ===")
all_opps = df.groupby('opponent').agg(mean=('actual','mean'),tier=('tier','first')).reset_index().sort_values('mean')
for _,r in all_opps.iterrows():
    bar = '█'*int(r['mean']/200)
    print(f"  {r['opponent']:<12} {r['tier']} {r['mean']:>6.0f} {bar}")