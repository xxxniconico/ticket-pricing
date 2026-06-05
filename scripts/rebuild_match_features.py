"""Rebuild match_features.parquet from all_unified.parquet (includes 2023)."""
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path('/home/xxxsuli/ticket-pricing')
df = pd.read_parquet(ROOT / 'data/processed/all_unified.parquet')

# Only CSL home matches
df = df[df['competition'] == 'CSL']

# Aggregate by match
mf = df.groupby(['match_date', 'opponent', 'match_id', 'competition']).agg(
    attendance=('数量', 'sum'),
    unique_users=('大麦用户id', 'nunique'),
    avg_price=('实际支付价格', 'mean'),
).reset_index()

# Sort by date
mf = mf.sort_values('match_date')

# Show summary
for yr in ['2023', '2024', '2025', '2026']:
    sub = mf[mf['match_date'].str.startswith(yr)]
    if len(sub) > 0:
        print(f"{yr}: {len(sub)}场, {sub['attendance'].sum():,}张, 均价¥{sub['avg_price'].mean():.0f}")

# Save
mf.to_parquet(ROOT / 'data/processed/match_features.parquet', index=False)
print(f"\nSaved: {len(mf)} matches to match_features.parquet")
