"""重建 match_features + 重训"""
import pandas as pd, numpy as np
from pathlib import Path
import json

ROOT = Path('/home/xxxsuli/ticket-pricing')
NON_CSL = {"河内公安", "大埔", "麦克阿瑟FC"}

df = pd.read_parquet(ROOT/'data/processed/all_unified.parquet')

# match_features: CSL only, exclude 亚冠
csl = df[(df['competition']=='CSL') & (~df['opponent'].isin(NON_CSL))]
mf = csl.groupby('match_id').agg(
    attendance=('数量','sum'), unique_users=('大麦用户id','nunique'),
    avg_price=('实际支付价格','mean'), competition=('competition','first'),
    match_date=('match_date','first'), opponent=('opponent','first'),
).reset_index()
mf.to_parquet(ROOT/'data/processed/match_features.parquet', index=False)

print(f"match_features: {len(mf)} 场")
for yr in ['2024','2025','2026']:
    sub = mf[mf['match_date'].str.startswith(yr)]
    print(f"  {yr}: {len(sub)}场, {sub['attendance'].sum():.0f}票")

# Reset calibration
cal = {"tier": {"S": 1.0, "A": 1.0, "B": 1.0, "C": 1.0}, "history": []}
with open(ROOT/'data/processed/calibration.json', 'w') as f:
    json.dump(cal, f, indent=2, ensure_ascii=False)
print("校准已重置")