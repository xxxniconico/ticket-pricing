"""
三年数据探索 (2024-2026): 找 MAE 下降突破口
"""
import pandas as pd, numpy as np, sys
from pathlib import Path

ROOT = Path("/home/xxxsuli/ticket-pricing")
sys.path.insert(0, str(ROOT))
from src.classify import classify_opponent_tier, DERBY_RIVALS, S_TIER, A_TIER, B_TIER, C_TIER

NON_CSL = {"河内公安", "大埔", "麦克阿瑟FC"}

df = pd.read_parquet(ROOT / "data/processed/all_unified.parquet")
df = df[~df['opponent'].isin(NON_CSL)]

# ============================================================
# 1. 三年整体趋势
# ============================================================
ms = df.groupby('match_id').agg(
    tickets=('数量', 'sum'),
    opponent=('opponent', 'first'),
    match_date=('match_date', 'first'),
    competition=('competition', 'first'),
    users=('大麦用户id', 'nunique'),
    avg_price=('实际支付价格', 'mean'),
).reset_index()
ms['year'] = ms['match_date'].str[:4]
ms['month'] = ms['match_date'].str[5:7].astype(int)
ms['tier'] = ms['opponent'].apply(classify_opponent_tier)

print("=" * 70)
print("1. 三年整体趋势")
print("=" * 70)
csl_ms = ms[(ms['competition'] == 'CSL')]
for yr in ['2024','2025','2026']:
    sub = csl_ms[csl_ms['year'] == yr]
    if len(sub) == 0: continue
    print(f"\n{yr} ({len(sub)}场):")
    print(f"  场均: {sub['tickets'].mean():.0f}  中位: {sub['tickets'].median():.0f}")
    print(f"  票价: ¥{sub['avg_price'].mean():.0f}  用户: {sub['users'].mean():.0f}")
    for t in ['S','A','B','C']:
        st = sub[sub['tier'] == t]
        if len(st) > 0:
            print(f"    {t}: n={len(st)}, mean={st['tickets'].mean():.0f}, median={st['tickets'].median():.0f}")

# ============================================================
# 2. 对手跨年对比
# ============================================================
print("\n" + "=" * 70)
print("2. 对手跨年需求变化")
print("=" * 70)
team_multi = csl_ms.groupby(['opponent', 'year']).agg(
    tickets=('tickets', 'mean'),
    n=('tickets', 'count'),
    tier=('tier', 'first'),
).reset_index()

for opp in sorted(team_multi['opponent'].unique()):
    sub = team_multi[team_multi['opponent'] == opp]
    if len(sub) < 2: continue
    tier = sub['tier'].iloc[0]
    vals = []
    for yr in ['2024','2025','2026']:
        r = sub[sub['year'] == yr]
        v = f"{r['tickets'].iloc[0]:.0f}" if len(r) > 0 else '-'
        vals.append(v)
    # Check for big swings
    nums = [int(v) for v in vals if v != '-']
    if len(nums) >= 2:
        swing = max(nums) - min(nums)
        if swing > 2000:
            print(f"  {opp:<12} {tier} | 2024:{vals[0]:>6} 2025:{vals[1]:>6} 2026:{vals[2]:>6} | swing={swing}")

# ============================================================
# 3. 月份效应
# ============================================================
print("\n" + "=" * 70)
print("3. 月份效应（CSL only）")
print("=" * 70)
for m in range(3, 12):
    sub = csl_ms[csl_ms['month'] == m]
    if len(sub) == 0: continue
    # De-seasonalize: compare to tier average for that year
    ratios = []
    for _, r in sub.iterrows():
        tier_avg = csl_ms[(csl_ms['year'] == r['year']) & (csl_ms['tier'] == r['tier'])]['tickets'].mean()
        if tier_avg > 0:
            ratios.append(r['tickets'] / tier_avg)
    if ratios:
        avg_ratio = np.mean(ratios)
        marker = '▲' if avg_ratio > 1.05 else '▼' if avg_ratio < 0.95 else ' '
        print(f"  {m:2d}月: n={len(sub)}, 相对均值={avg_ratio:.3f} {marker}")

# ============================================================
# 4. 票价敏感度
# ============================================================
print("\n" + "=" * 70)
print("4. 票价 vs 上座（按Tier）")
print("=" * 70)
for t in ['S','A','B','C']:
    sub = csl_ms[csl_ms['tier'] == t]
    if len(sub) < 3: continue
    # Split by price quartile
    sub['price_q'] = pd.qcut(sub['avg_price'], q=2, labels=['低','高'], duplicates='drop')
    for q in ['低','高']:
        sq = sub[sub['price_q'] == q]
        if len(sq) > 0:
            print(f"  {t} 票价{q}: n={len(sq)}, 均价¥{sq['avg_price'].mean():.0f}, 场均{sq['tickets'].mean():.0f}")

# ============================================================
# 5. 同级内方差分析
# ============================================================
print("\n" + "=" * 70)
print("5. 同级内方差（对手稳定性）")
print("=" * 70)
for t in ['S','A','B','C']:
    # By opponent
    by_opp = csl_ms[csl_ms['tier'] == t].groupby('opponent').agg(
        mean=('tickets', 'mean'),
        std=('tickets', 'std'),
        cv=('tickets', lambda x: np.std(x)/np.mean(x) if np.mean(x)>0 else 0),
        n=('tickets', 'count'),
    ).reset_index().sort_values('cv', ascending=False)
    
    if len(by_opp) > 0:
        print(f"\n  {t} tier (CV=变异系数):")
        for _, r in by_opp.iterrows():
            cv_flag = '⚠' if r['cv'] > 0.25 else ' '
            print(f"    {r['opponent']:<12} mean={r['mean']:.0f} std={r['std']:.0f} cv={r['cv']:.2f} n={int(r['n'])} {cv_flag}")

# ============================================================
# 6. 情境乘数实际效果
# ============================================================
print("\n" + "=" * 70)
print("6. 情境效果实证（有情境 vs 无情境的差值）")
print("=" * 70)

# Use simple date-based context for this analysis
csl_ms['is_sat'] = pd.to_datetime(csl_ms['match_date']).dt.weekday == 5
csl_ms['is_late'] = pd.to_datetime(csl_ms['match_date']).dt.month >= 10
csl_ms['is_derby'] = csl_ms['opponent'].apply(lambda o: o in DERBY_RIVALS or any(d in str(o) for d in DERBY_RIVALS))

for flag, label in [('is_sat', '周六'), ('is_late', '赛季末'), ('is_derby', '德比')]:
    yes = csl_ms[csl_ms[flag] == True]
    no = csl_ms[csl_ms[flag] == False]
    if len(yes) > 0 and len(no) > 0:
        # Control for tier: compare within same tier
        ratios = []
        for t in ['S','A','B','C']:
            yt = yes[yes['tier'] == t]
            nt = no[no['tier'] == t]
            if len(yt) > 0 and len(nt) > 0:
                ratios.append(yt['tickets'].mean() / nt['tickets'].mean())
        if ratios:
            avg_effect = np.mean(ratios)
            print(f"  {label}: {len(yes)}场 vs {len(no)}场, 同级内倍数={avg_effect:.3f}")

# ============================================================
# 7. 残差分析：识别异常场次
# ============================================================
print("\n" + "=" * 70)
print("7. 残差分析（实际 vs 同级均值）")
print("=" * 70)
csl_ms['tier_mean'] = csl_ms.groupby(['tier', 'year'])['tickets'].transform('mean')
csl_ms['residual'] = csl_ms['tickets'] - csl_ms['tier_mean']
csl_ms['residual_pct'] = csl_ms['residual'] / csl_ms['tier_mean'] * 100

outliers = csl_ms[abs(csl_ms['residual_pct']) > 25].sort_values('residual_pct')
print(f"  超出同级均值±25%的异常场次 ({len(outliers)}):")
for _, r in outliers.iterrows():
    direction = '▲' if r['residual'] > 0 else '▼'
    print(f"    {r['match_date']} {r['opponent']:<12} {r['tier']} actual={r['tickets']:.0f} tier_mean={r['tier_mean']:.0f} {direction}{abs(r['residual_pct']):.1f}%")

# ============================================================
# 8. 关键发现汇总
# ============================================================
print("\n" + "=" * 70)
print("8. 关键发现")
print("=" * 70)
# Check if 2024 data could help
if len(csl_ms[csl_ms['year'] == '2024']) > 0:
    print(f"  2024年有{len(csl_ms[csl_ms['year']=='2024'])}场CSL数据，可用于扩充训练集")
    
# Check which teams have highest CV (unpredictable)
high_cv = csl_ms.groupby('opponent').agg(
    cv=('tickets', lambda x: np.std(x)/np.mean(x) if np.mean(x)>0 else 0),
    n=('tickets', 'count')
).reset_index()
unpredictable = high_cv[(high_cv['cv'] > 0.3) & (high_cv['n'] >= 2)]
if len(unpredictable) > 0:
    print(f"  高方差对手(CV>0.3): {unpredictable['opponent'].tolist()}")

print(f"\n  当前模型用2025-2026共{len(csl_ms[csl_ms['year']!='2024'])}场训练")
print(f"  加入2024后可扩至{len(csl_ms)}场（+{len(csl_ms[csl_ms['year']=='2024'])}场）")