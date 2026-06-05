#!/usr/bin/env python3
"""
全量重建管线：剔除客队票 → 重算 TIER_BASE → 重建 match_features → 重置校准
只保留主队散票 (【主队球迷专享】或无前缀的早期数据)
"""
import pandas as pd
import numpy as np
import json
import os
from pathlib import Path
from datetime import datetime

ROOT = Path("/home/xxxsuli/ticket-pricing")
PROCESSED = ROOT / "data/processed"

import sys
sys.path.insert(0, str(ROOT))
from src.classify import classify_opponent_tier

# ============================================================
# 1. Load & Filter
# ============================================================
print("=" * 60)
print("Step 1: 过滤 all_unified.parquet 剔除客队票")

df = pd.read_parquet(PROCESSED / "all_unified.parquet")
print(f"  原始: {len(df):,} 行, {df['数量'].sum():,} 张")

guest_mask = df['场次名称'].str.contains('客队', na=False)
print(f"  客队票: {guest_mask.sum():,} 行, {df[guest_mask]['数量'].sum():,} 张")

df_home = df[~guest_mask].copy()
print(f"  主队票: {len(df_home):,} 行, {df_home['数量'].sum():,} 张")

# 备份
backup_path = PROCESSED / "all_unified_with_guest.parquet"
if not backup_path.exists():
    df.to_parquet(backup_path, index=False)
    print(f"  已备份到 {backup_path.name}")

df_home.to_parquet(PROCESSED / "all_unified.parquet", index=False)
print(f"  已保存 filtered all_unified.parquet")

# ============================================================
# 2. 分析: 主队-only TIER_BASE
# ============================================================
print("\n" + "=" * 60)
print("Step 2: 主队-only 各Tier均值")

match_stats = df_home.groupby('match_id').agg(
    tickets=('数量', 'sum'),
    opponent=('opponent', 'first'),
    match_date=('match_date', 'first'),
    competition=('competition', 'first'),
).reset_index()

csl_2526 = match_stats[
    (match_stats['competition'] == 'CSL') & 
    (match_stats['match_date'].str.startswith(('2025', '2026')))
].copy()

csl_2526['tier'] = csl_2526['opponent'].apply(classify_opponent_tier)

print("  现有分级各Tier（主队-only）:")
for t in ['S', 'A', 'B', 'C']:
    sub = csl_2526[csl_2526['tier'] == t]
    if len(sub) > 0:
        vals = sub['tickets'].values
        print(f"    {t}: n={len(sub)}, mean={vals.mean():.0f}, median={np.median(vals):.0f}")
        print(f"        min={vals.min():.0f}, max={vals.max():.0f}")
    else:
        print(f"    {t}: n=0 (无数据)")

# KMeans without sklearn: simple iterative clustering
print("\n  手工KMeans K=4:")
X = csl_2526['tickets'].values.reshape(-1, 1).astype(float)

# Initialize centers: evenly spaced from min to max
vmin, vmax = X.min(), X.max()
centers = np.linspace(vmin, vmax, 4).reshape(-1, 1)

for iteration in range(100):
    # Assign clusters
    dists = np.abs(X - centers.T)  # (n, 4)
    labels = np.argmin(dists, axis=1)
    
    # Update centers
    new_centers = np.array([X[labels == k].mean() if (labels == k).sum() > 0 else centers[k] 
                            for k in range(4)])
    
    if np.allclose(centers, new_centers):
        break
    centers = new_centers

centers_flat = centers.flatten()
order = np.argsort(centers_flat)[::-1]  # descending
tier_names = ['S', 'A', 'B', 'C']

print(f"  聚类中心: {[f'{centers_flat[o]:.0f}' for o in order]}")

csl_2526['km'] = labels
csl_2526['km_tier'] = csl_2526['km'].map(
    {order[i]: tier_names[i] for i in range(4)}
)

print("\n  KMeans 分级:")
for t in tier_names:
    sub = csl_2526[csl_2526['km_tier'] == t]
    if len(sub) > 0:
        print(f"    {t} (n={len(sub)}):")
        for _, r in sub.sort_values('tickets', ascending=False).iterrows():
            print(f"      {r['match_date']} {r['opponent']}: {r['tickets']:.0f} (原分级={r['tier']})")

# ============================================================
# 3. 重建 match_features.parquet
# ============================================================
print("\n" + "=" * 60)
print("Step 3: 重建 match_features.parquet")

mf = df_home.groupby('match_id').agg(
    attendance=('数量', 'sum'),
    unique_users=('大麦用户id', 'nunique'),
    avg_price=('实际支付价格', 'mean'),
    competition=('competition', 'first'),
    match_date=('match_date', 'first'),
    opponent=('opponent', 'first'),
).reset_index()

mf.to_parquet(PROCESSED / "match_features.parquet", index=False)
print(f"  {len(mf)} 场, 总入座={mf['attendance'].sum():.0f}")

# Check specific matches
for _, r in mf[mf['match_date'].str.startswith('2026')].sort_values('match_date').iterrows():
    print(f"    {r['match_date']} {r['opponent']}: {r['attendance']:.0f}")

# ============================================================
# 4. 重置校准 (简单版, 待完整 backtest)
# ============================================================
print("\n" + "=" * 60)
print("Step 4: 重置 calibration.json")

cal = {
    "S": 1.0, "A": 1.0, "B": 1.0, "C": 1.0,
    "description": "主队-only重建, 待完整backtest填充EMA"
}

with open(PROCESSED / "calibration.json", 'w') as f:
    json.dump(cal, f, indent=2, ensure_ascii=False)

print("  校准已重置为 1.0 (需运行完整 backtest 重建 EMA)")

print("\n" + "=" * 60)
print("重建完成! 下一步:")
print("  1. 根据上述分析确定新 TIER_BASE")
print("  2. 更新 src/rule_engine.py TIER_BASE")
print("  3. 运行 backtest 重建 calibration")
print("  4. 重启看板 :8504")
print("=" * 60)