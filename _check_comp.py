import pandas as pd
df = pd.read_parquet('/home/xxxsuli/ticket-pricing/data/processed/all_unified.parquet')
print('competition:', df['competition'].unique())
print()
ms = df.groupby('match_id').agg(
    tickets=('数量','sum'), date=('match_date','first'), opp=('opponent','first'), comp=('competition','first')
).reset_index().sort_values('date')
for _, r in ms.iterrows():
    print(f"{r['date']} {r['opp']:<12} {r['comp']:<6} {r['tickets']:.0f}")