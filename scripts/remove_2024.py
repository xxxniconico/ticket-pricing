"""删除2024数据，备份后重建"""
import pandas as pd
from pathlib import Path
import shutil

ROOT = Path('/home/xxxsuli/ticket-pricing')
pq = ROOT/'data/processed/all_unified.parquet'

df = pd.read_parquet(pq)
print(f"当前: {len(df):,} 行")

# 备份
bak = ROOT/'data/processed/all_unified_v46_backup.parquet'
shutil.copy(pq, bak)
print(f"已备份到 {bak.name}")

# 删2024
df_new = df[~df['match_date'].str.startswith('2024')].copy()
n_2024 = df[df['match_date'].str.startswith('2024')]['match_id'].nunique()
print(f"删除2024: {len(df)-len(df_new):,} 行 ({n_2024} 场)")

df_new.to_parquet(pq, index=False)
print(f"保存: {len(df_new):,} 行")

# 重建 match_features
NON_CSL = {"河内公安", "大埔", "麦克阿瑟FC"}
mf = df_new[~df_new['opponent'].isin(NON_CSL)].groupby('match_id').agg(
    attendance=('数量','sum'), unique_users=('大麦用户id','nunique'),
    avg_price=('实际支付价格','mean'), competition=('competition','first'),
    match_date=('match_date','first'), opponent=('opponent','first'),
).reset_index()
mf.to_parquet(ROOT/'data/processed/match_features.parquet', index=False)
print(f"match_features: {len(mf)} 场, {mf['attendance'].sum():.0f} 票")

# 重置校准
import json
cal = {"tier": {"S": 1.0, "A": 1.0, "B": 1.0, "C": 1.0}, "history": []}
with open(ROOT/'data/processed/calibration.json', 'w') as f:
    json.dump(cal, f, indent=2, ensure_ascii=False)
print("校准已重置")

# 统计
for yr in ['2025','2026']:
    sub = mf[mf['match_date'].str.startswith(yr)]
    print(f"  {yr}: {len(sub)}场, {sub['attendance'].sum():.0f}票")