"""B拆分探索: B(高) / B-(低) + C"""
import pandas as pd, numpy as np, sys
from pathlib import Path

ROOT = Path("/home/xxxsuli/ticket-pricing")
sys.path.insert(0, str(ROOT))

NON_CSL = {"河内公安", "大埔", "麦克阿瑟FC"}
df = pd.read_parquet(ROOT / "data/processed/all_unified.parquet")
csl = df[(df['competition']=='CSL') & (~df['opponent'].isin(NON_CSL))]

ms = csl.groupby('match_id').agg(tickets=('数量','sum'), opponent=('opponent','first')).reset_index()
team = ms.groupby('opponent').agg(mean=('tickets','mean'), n=('tickets','count')).reset_index().sort_values('mean', ascending=False)

print("各对手均值:")
for _, r in team.iterrows():
    print(f"  {r['opponent']:<12} mean={r['mean']:.0f} n={int(r['n'])}")

# Current A-tier opponents
A_opps = {"成都蓉城", "山东泰山", "天津津门虎"}
# High B (>8500 avg): 长春, 深圳, 云南, 武汉, 浙江, 海港, 梅州
# Low B (<8200 avg): 河南, 西海岸
# C-tier

# Scheme 1: B_high = {长春,深圳,云南,武汉,浙江,海港,梅州}, B_low = {河南,西海岸}
# Scheme 2: B = {长春,深圳,云南,武汉,浙江}, B- = {海港,河南,梅州,西海岸}
# Scheme 3: Move 河南+西海岸 to C (make C bigger, reduce B variance)

print("\n=== 方案对比 ===")

schemes = {
    "A: 当前4级": {
        'S': {'上海申花'}, 'A': A_opps,
        'B': {'长春亚泰','深圳新鹏城','云南玉昆','武汉三镇','浙江','浙江队','浙江俱乐部绿城',
              '上海海港','河南','河南队','河南俱乐部酒祖杜康','河南队俱乐部彩陶坊','梅州客家','青岛西海岸'},
        'C': {'大连英博','大连英博海发','青岛海牛','辽宁铁人','重庆铜梁龙'},
    },
    "B: B拆B_high/B_low": {
        'S': {'上海申花'}, 'A': A_opps,
        'B': {'长春亚泰','深圳新鹏城','云南玉昆','武汉三镇','浙江','浙江队','浙江俱乐部绿城',
              '上海海港','梅州客家'},
        'BL': {'河南','河南队','河南俱乐部酒祖杜康','河南队俱乐部彩陶坊','青岛西海岸'},
        'C': {'大连英博','大连英博海发','青岛海牛','辽宁铁人','重庆铜梁龙'},
    },
    "C: 河南+西海岸→C": {
        'S': {'上海申花'}, 'A': A_opps,
        'B': {'长春亚泰','深圳新鹏城','云南玉昆','武汉三镇','浙江','浙江队','浙江俱乐部绿城',
              '上海海港','梅州客家'},
        'C': {'大连英博','大连英博海发','青岛海牛','辽宁铁人','重庆铜梁龙',
              '河南','河南队','河南俱乐部酒祖杜康','河南队俱乐部彩陶坊','青岛西海岸'},
    },
}

def classify(tiers, opp):
    for t, teams in tiers.items():
        if any(x in str(opp) or str(opp) in x for x in teams):
            return t
    return 'B'

for name, tiers in schemes.items():
    ms['tier_temp'] = ms['opponent'].apply(lambda o: classify(tiers, o))
    stats = []
    for t in ['S','A','B','BL','C']:
        sub = ms[ms['tier_temp'] == t]
        if len(sub) == 0: continue
        stats.append(f"{t}: mean={sub['tickets'].mean():.0f} n={len(sub)} range={sub['tickets'].min():.0f}-{sub['tickets'].max():.0f}")
    print(f"\n{name}:")
    print(f"  {' | '.join(stats)}")
    # Also show per-tier CV
    for t in ['S','A','B','BL','C']:
        sub = ms[ms['tier_temp'] == t]
        if len(sub) == 0: continue
        vals = sub['tickets'].values
        cv = np.std(vals)/np.mean(vals) if np.mean(vals)>0 else 0
        # Per-opponent means in this tier
        by_opp = sub.groupby('opponent')['tickets'].mean().sort_values(ascending=False)
        opps_str = ', '.join([f"{o}({v:.0f})" for o,v in by_opp.items()])
        print(f"    {t}: cv={cv:.2f} | {opps_str}")