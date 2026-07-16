#!/usr/bin/env python3
"""16 队 tier 分布 + 9 场 2026 已赛 base MAE 评估."""
import sys
sys.path.insert(0, "/home/xxxsuli/ticket-pricing")

from src.opponent_rating import (get_effective_tier, get_opponent_scorecard,
                                  load_elo_history)
from src.csl_context import load_csl_data

TIER_BASE = {"S": 12600, "A": 10900, "B": 8200, "C": 5700}
TEAMS = ['上海申花','成都蓉城','山东泰山','天津津门虎','上海海港',
         '深圳新鹏城','浙江','河南','武汉三镇','云南玉昆','青岛西海岸',
         '青岛海牛','大连英博海发','辽宁铁人','重庆铜梁龙','长春亚泰']

GAMES = [
    ("2026-03-21", "上海申花", 15483),
    ("2026-04-12", "成都蓉城", 8343),
    ("2026-04-25", "天津津门虎", 11084),
    ("2026-05-06", "大连英博海发", 3992),
    ("2026-05-10", "上海海港", 6576),
    ("2026-05-15", "青岛海牛", 5884),
    ("2026-05-23", "河南", 8224),
    ("2026-06-27", "武汉三镇", 6238),
    ("2026-07-04", "山东泰山", 12956),
]

def main():
    matches, standings, _ = load_csl_data()
    elo = load_elo_history()

    print("=" * 60)
    print("16 队 tier 分布 (2026-07-17)")
    print("=" * 60)
    dist = {"S": 0, "A": 0, "B": 0, "C": 0}
    for t in TEAMS:
        card = get_opponent_scorecard(t, "2026-07-17",
                                      elo_history=elo,
                                      standings_by_round=standings,
                                      matches=matches)
        tier = card["tier"]
        dist[tier] = dist.get(tier, 0) + 1
        print(f"  {t:12s}  ST={card['ST']:5.1f}  AP={card['AP']:5.1f}  tier={tier}")

    print(f"\n  分布: S={dist['S']} A={dist['A']} B={dist['B']} C={dist['C']}")

    print("\n" + "=" * 60)
    print("9 场 2026 已赛 base MAE")
    print("=" * 60)
    errors = []
    for date, opp, actual in GAMES:
        tier = get_effective_tier(opp, date, elo_history=elo,
                                  standings_by_round=standings, matches=matches)
        base = TIER_BASE.get(tier, 5700)
        err = base - actual
        errors.append(abs(err))
        print(f"  {date}  {opp:10s}  tier={tier}  base={base:5.0f}  "
              f"actual={actual:5.0f}  err={err:+5.0f}")

    mae = sum(errors) / len(errors)
    print(f"\n  MAE = {mae:.0f}")
    wuhan_idx = 5  # 武汉三镇 at index 5 in GAMES? No, it's 7th (index 6)
    # Actually let me find 武汉
    for i, (_, opp, _) in enumerate(GAMES):
        if "武汉" in opp:
            excl = [e for j, e in enumerate(errors) if j != i]
            print(f"  剔除 {opp}: MAE = {sum(excl)/len(excl):.0f}")
            break

if __name__ == "__main__":
    main()
