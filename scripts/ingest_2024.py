"""导入2024年数据到 parquet"""
import pandas as pd, numpy as np, re
from pathlib import Path

ROOT = Path('/home/xxxsuli/ticket-pricing')
EXCEL = '/mnt/c/Users/xxxsu/xwechat_files/xxxnicolas_634a/msg/file/2026-05/24年散票购买场次.xlsx'

raw = pd.read_excel(EXCEL)
print(f"读取: {len(raw)} 行")

rows = []
skipped = 0

for _, r in raw.iterrows():
    match_name = str(r['场次名称'])
    uid = str(r['大麦用户id'])
    price_info = str(r['票价信息'])
    payment = float(r['实际支付价格'])
    seat_info = str(r.get('座位信息', '')) if pd.notna(r.get('座位信息')) else ''
    
    # Parse price * quantity
    price = 0.0; qty = 1
    pm = re.search(r'(\d+\.?\d*)', price_info)
    if pm: price = float(pm.group(1))
    if '*' in price_info:
        qm = re.search(r'\*(\d+)', price_info)
        if qm: qty = int(qm.group(1))
    
    # Parse match name: "2024-11-02 周六 15:30（北京国安VS河南队）"
    date_m = re.search(r'(\d{4}-\d{2}-\d{2})', match_name)
    date = date_m.group(1) if date_m else ''
    opp_m = re.search(r'VS(.+?)[）\)]', match_name)
    opponent = opp_m.group(1).strip() if opp_m else ''
    
    # Parse seats
    seats = [s.strip() for s in seat_info.split('|') if s.strip()] if seat_info else ['']
    
    for seat in seats:
        per_pay = payment / qty if qty > 0 else payment
        
        # Parse seat: "四层 309区 12排 28号"
        floor = 0; section = 0; row_num = 0; seat_num = 0
        if seat:
            fm = re.search(r'(\w+)层', seat)
            sm = re.search(r'(\d+)区', seat)
            rm = re.search(r'(\d+)排', seat)
            s2 = re.search(r'(\d+)号', seat)
            floor_map = {'一':1,'二':2,'三':3,'四':4,'五':5}
            if fm:
                for k,v in floor_map.items():
                    if k in fm.group(1): floor = v; break
            if sm: section = int(sm.group(1))
            if rm: row_num = int(rm.group(1))
            if s2: seat_num = int(s2.group(1))
        
        rows.append({
            '场次名称': match_name,
            '大麦用户id': uid,
            '票价信息': price_info,
            '实际支付价格': per_pay,
            '座位信息': seat,
            'match_date': date,
            'opponent': opponent,
            'is_home': True,
            'is_bundle': False,
            'match_id': f'{date} {opponent}',
            '票名称': f'{price:.0f}元',
            '数量': 1,
            'floor': floor,
            'section': section,
            'row_num': row_num,
            'seat_num': seat_num,
            'match_tier': '',
            'competition': 'CSL',
            'is_partial': False,
            '比赛': f'北京国安VS{opponent}',
        })

df_new = pd.DataFrame(rows)

# Ensure dtypes match existing parquet
for col in ['section','floor','row_num','seat_num']:
    df_new[col] = df_new[col].astype('int64')
df_new['数量'] = df_new['数量'].astype('int64')
df_new['大麦用户id'] = df_new['大麦用户id'].astype(str)
df_new['md'] = pd.to_datetime(df_new['match_date'])

print(f"解析: {len(df_new)} 行 (跳过{skipped})")
print(f"场次: {df_new['match_id'].nunique()}")
for m in sorted(df_new['match_id'].unique()):
    tix = df_new[df_new['match_id']==m]['数量'].sum()
    print(f"  {m}: {tix:,} 张")

# 合并到主 parquet
pq_path = ROOT / 'data/processed/all_unified.parquet'
existing = pd.read_parquet(pq_path)

# Check for duplicates
existing_ids = set(existing['match_id'].unique())
new_ids = set(df_new['match_id'].unique())
overlap = existing_ids & new_ids
if overlap:
    print(f"\n⚠ 重复场次: {overlap}, 将覆盖")
    existing = existing[~existing['match_id'].isin(overlap)]

# Align columns
for col in existing.columns:
    if col not in df_new.columns:
        df_new[col] = ''
for col in df_new.columns:
    if col not in existing.columns:
        existing[col] = ''

merged = pd.concat([existing, df_new[existing.columns]], ignore_index=True)
merged.to_parquet(pq_path, index=False)

# Stats
total = len(merged)
for yr in ['2024','2025','2026']:
    sub = merged[merged['match_date'].str.startswith(yr)]
    print(f"  {yr}: {sub['match_id'].nunique()}场, {len(sub):,}行, {sub['数量'].sum():,}张")

# Backup in same dir
import shutil
shutil.copy(pq_path, ROOT/'data/processed/all_unified_before2024_cleanup.parquet')
print(f"\n合并完成: {len(merged):,} 行 ({merged['match_id'].nunique()} 场)")
print("备份: all_unified_before2024_cleanup.parquet")