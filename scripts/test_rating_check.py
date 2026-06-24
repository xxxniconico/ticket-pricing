from src.csl_context import load_csl_data
from src.opponent_rating import (get_opponent_scorecard, load_elo_history, get_all_tier_distribution)
from src.classify import classify_opponent_tier as old_classify

matches, standings, deduct = load_csl_data()
elo_history = load_elo_history()

print('=== ST/AP/Tier for all 16 teams on 2026-06-25 ===')
teams = ['上海申花', '成都蓉城', '山东泰山', '天津津门虎', '上海海港',
         '深圳新鹏城', '浙江', '河南', '武汉三镇', '云南玉昆', '梅州客家',
         '青岛西海岸', '青岛海牛', '大连英博海发', '辽宁铁人', '重庆铜梁龙']

for team in teams:
    card = get_opponent_scorecard(team, '2026-06-25', elo_history=elo_history,
        standings_by_round=standings, matches=matches)
    print(f"{card['opponent']:<12s} ELO={card['elo']:>7.1f} ST={card['ST']:>5.1f} AP={card['AP']:>5.1f} Tier={card['tier']}")

dist = get_all_tier_distribution('2026-06-25', elo_history=elo_history, matches=matches, standings_by_round=standings)
print(f"Tier dist: {dist}")

print()
print('=== 3 Mismatch Cases ===')
for team, exp in [('武汉三镇', 'B->C'), ('上海海港', 'A->B'), ('青岛海牛', 'C->B')]:
    old = old_classify(team)
    card = get_opponent_scorecard(team, '2026-06-25', elo_history=elo_history, standings_by_round=standings, matches=matches)
    new = card['tier']
    ok = 'PASS' if new != old else 'FAIL (no change)'
    print(f"  {team}: old={old} new={new} ST={card['ST']:.1f} AP={card['AP']:.1f} [{ok}]")
