"""5级制网格搜索最优分级"""
import pandas as pd, numpy as np, sys
from pathlib import Path

ROOT = Path("/home/xxxsuli/ticket-pricing")
sys.path.insert(0, str(ROOT))

NON_CSL = {"河内公安", "大埔", "麦克阿瑟FC"}

df = pd.read_parquet(ROOT / "data/processed/all_unified.parquet")
csl = df[(df['competition']=='CSL') & (~df['opponent'].isin(NON_CSL))]

ms = csl.groupby('match_id').agg(
    tickets=('数量','sum'), opponent=('opponent','first'),
    match_date=('match_date','first'),
).reset_index()

# 按对手聚合
team = ms.groupby('opponent').agg(
    mean=('tickets','mean'), std=('tickets','std'), n=('tickets','count')
).reset_index().sort_values('mean', ascending=False)

print("各对手三年均值:")
for _, r in team.iterrows():
    print(f"  {r['opponent']:<12} mean={r['mean']:.0f} std={r['std']:.0f} n={int(r['n'])}")

# 建议5级分法
print("\n建议5级:")
# S: top (申花)
# A: 成都/山东/天津
# B1: 长春/深圳/云南/武汉 (high B, >9000 avg)
# B2: 浙江/河南/海港/梅州/西海岸 (mid B, 7000-8800)
# C: 大连/青岛海牛/辽宁/重庆 (low, <5500)
S5 = {"上海申花"}
A5 = {"成都蓉城", "山东泰山", "天津津门虎"}
B15 = {"长春亚泰", "深圳新鹏城", "云南玉昆", "武汉三镇"}
B25 = {"浙江", "浙江队", "浙江俱乐部绿城", "河南", "河南队", "河南俱乐部酒祖杜康", "河南队俱乐部彩陶坊",
        "上海海港", "梅州客家", "青岛西海岸"}
C5 = {"大连英博", "大连英博海发", "青岛海牛", "辽宁铁人", "重庆铜梁龙", "沧州雄狮", "南通支云"}

# 验证: 每个5级的对手列表
for label, teams in [("S",S5),("A",A5),("B1",B15),("B2",B25),("C",C5)]:
    sub = team[team['opponent'].isin(teams)]
    if len(sub) > 0:
        print(f"  {label}: n={int(sub['n'].sum())}场, mean={sub['mean'].mean():.0f}, "
              f"range={sub['mean'].min():.0f}-{sub['mean'].max():.0f}")