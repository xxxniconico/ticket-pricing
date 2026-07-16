#!/usr/bin/env python3
"""9 场 2026 已赛 base MAE 回归验证."""
import sys
sys.path.insert(0, "/home/xxxsuli/ticket-pricing")

from src.opponent_rating import get_effective_tier, load_elo_history
from src.csl_context import load_csl_data

TIER_BASE = {"S": 12600, "A": 10900, "B": 8200, "C": 5700}

# 9 场 2026 国安主场已赛
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

matches, standings_by_round, _ = load_csl_data()
elo_history = load_elo_history()

errors = []
for date, opp, actual in GAMES:
    tier = get_effective_tier(opp, date, elo_history=elo_history,
                              standings_by_round=standings_by_round, matches=matches)
    base = TIER_BASE.get(tier, 5700)
    err = base - actual
    errors.append(abs(err))
    print(f"{date} {opp:10s} tier={tier} base={base:5.0f} actual={actual:5.0f} err={err:+5.0f}")

mae = sum(errors) / len(errors)
print(f"\nMAE = {mae:.0f}")
print(f"剔除武汉 (6/27): MAE = {sum(errors[:5]+errors[6:]):.0f} / 8 = {(sum(errors[:5]+errors[6:])/8):.0f}")
