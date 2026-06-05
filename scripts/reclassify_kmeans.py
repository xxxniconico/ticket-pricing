"""KMeans 对手重分级 + 重训模型"""
import sys, json
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path("/home/xxxsuli/ticket-pricing")
sys.path.insert(0, str(ROOT))
from src.classify import classify_opponent_tier, DERBY_RIVALS

NON_CSL = {"河内公安", "大埔", "麦克阿瑟FC"}

# 1. 加载主队数据
df = pd.read_parquet(ROOT / "data/processed/all_unified.parquet")
csl = df[
    (df['competition'] == 'CSL') & 
    (df['match_date'].str.startswith(('2025', '2026'))) &
    (~df['opponent'].isin(NON_CSL))
].copy()

ms = csl.groupby('match_id').agg(
    tickets=('数量', 'sum'),
    opponent=('opponent', 'first'),
    match_date=('match_date', 'first'),
).reset_index()
ms['tier_old'] = ms['opponent'].apply(classify_opponent_tier)

# 2. KMeans 重分级
X = ms['tickets'].values.reshape(-1, 1).astype(float)
vmin, vmax = X.min(), X.max()
centers = np.linspace(vmin, vmax, 4).reshape(-1, 1)

for _ in range(100):
    dists = np.abs(X - centers.T)
    labels = np.argmin(dists, axis=1)
    new_centers = np.array([X[labels==k].mean() if (labels==k).sum()>0 else centers[k] for k in range(4)])
    if np.allclose(centers, new_centers): break
    centers = new_centers

order = np.argsort(centers.flatten())[::-1]
tier_names = ['S','A','B','C']
ms['km_cluster'] = labels
ms['km_tier'] = ms['km_cluster'].map({order[i]: tier_names[i] for i in range(4)})

centers_sorted = [centers.flatten()[o] for o in order]
print("KMeans聚类中心:", {tier_names[i]: f'{centers_sorted[i]:.0f}' for i in range(4)})
print()

# 3. 按队聚合（每队多场的取平均出勤）
team_stats = ms.groupby('opponent').agg(
    avg_tickets=('tickets', 'mean'),
    n_matches=('tickets', 'count'),
    tier_old=('tier_old', 'first'),
    km_tier=('km_tier', lambda x: x.mode().iloc[0] if len(x.mode())>0 else x.iloc[0]),
).reset_index().sort_values('avg_tickets', ascending=False)

print("各队需求排序（去情境化前）:")
for _, r in team_stats.iterrows():
    old = r['tier_old']
    new = r['km_tier']
    flag = '⚠' if old != new else ' '
    print(f"  {r['opponent']:<12} avg={r['avg_tickets']:.0f} n={int(r['n_matches'])} {old}→{new} {flag}")

# 4. 建议新分级
# S: 最顶级（自动从KMeans取）
# A: 其次
# B: 再次
# C: 其余
print("\n建议分级:")
for t in tier_names:
    teams = team_stats[team_stats['km_tier'] == t]['opponent'].tolist()
    print(f"  {t}: {teams}")