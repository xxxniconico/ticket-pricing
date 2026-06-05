"""修复 2025/2026 parquet 票档标签"""
import pandas as pd, numpy as np, re
from pathlib import Path

ROOT = Path('/home/xxxsuli/ticket-pricing')
df = pd.read_parquet(ROOT / 'data/processed/all_unified.parquet')

# Backup
import shutil
shutil.copy(ROOT / 'data/processed/all_unified.parquet', 
            ROOT / 'data/processed/all_unified_pre_tier_fix.parquet')
print("备份完成")

# Fix: for rows where 票名称 is missing or "散票", extract from 票价信息
fixed = 0
for idx in df.index:
    ticket_name = str(df.at[idx, '票名称'])
    price_info = str(df.at[idx, '票价信息'])
    
    # Skip if already has proper tier label (like "120元", "180元")
    if '元' in ticket_name and ticket_name != '散票':
        continue
    
    # Only fix 2025/2026
    match_date = str(df.at[idx, 'match_date'])
    if not match_date.startswith('2025') and not match_date.startswith('2026'):
        continue
    
    # Extract face value from 票价信息 (e.g., "160.00*2" → 160)
    m = re.search(r'(\d+\.?\d*)', price_info)
    if m:
        price = int(float(m.group(1)))
        df.at[idx, '票名称'] = f'{price}元'
        fixed += 1

print(f"修复: {fixed} 行")

# Show new distribution
for yr in ['2025', '2026']:
    sub = df[df['match_date'].str.startswith(yr)]
    print(f'\n{yr} 票档分布:')
    for pn, cnt in sub['票名称'].value_counts().sort_index().items():
        print(f'  {pn}: {cnt:,}')

# Save
df.to_parquet(ROOT / 'data/processed/all_unified.parquet', index=False)
print(f'\n保存完成')
