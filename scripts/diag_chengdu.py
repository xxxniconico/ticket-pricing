#!/usr/bin/env python3
"""成都场 2026-04-12 预测分解诊断。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
from dashboard.components.ctx_builder import build_pred_args
from src.classify import classify_opponent_tier
from src.csl_context import detect_ctx, get_guoan_matches, load_csl_data
from src.rule_engine import MULTIPLIERS, TIER_BASE, predict

DATE = "2026-04-12"
OPP = "成都蓉城"

matches, rounds, _ = load_csl_data()
guoan = [m for m in get_guoan_matches(matches)
         if "cfl_fixtures_api" in m.get("source", "") or "wikipedia" in m.get("source", "")]
target = next(m for m in guoan if m["date"] == DATE and m.get("is_home"))
ctx = detect_ctx(target, guoan, rounds)
pred_args = build_pred_args(target, ctx)

md = pd.Timestamp(DATE)
prev = [m for m in guoan if m.get("completed") and pd.Timestamp(m["date"]) < md]
last3 = prev[-3:]
print(f"=== 赛前近3场 (共{len(last3)}) ===")
for m in last3:
    res = "W" if (m["is_home"] and m["hg"] > m["ag"]) or (not m["is_home"] and m["ag"] > m["hg"]) else "D" if m["hg"] == m["ag"] else "L"
    loc = "主" if m["is_home"] else "客"
    print(f"  {m['date']} {loc} vs {m['opponent']} {m['hg']}-{m['ag']} {res}")

tier = classify_opponent_tier(OPP)
base = TIER_BASE[tier]
print(f"\n=== 情境 ctx ===")
print({k: v for k, v in ctx.items() if v})
print(f"\n=== pred_args ===")
print(pred_args)

mult = 1.0
steps = [("base", base)]
for k in ("derby", "consecutive_home_losses", "heavy_home_loss",
          "away_winless_losses", "away_winless",
          "saturday", "season_opener", "midseason_restart", "midweek", "short_rest", "summer", "top3_form"):
    if pred_args.get(k):
        if k == "away_winless_losses":
            m = 0.77 if tier in ("S", "A") else MULTIPLIERS["away_winless_losses"]
        elif k == "derby" and tier == "A":
            m = MULTIPLIERS["derby_B"]
        else:
            m = MULTIPLIERS.get(k, 1.0)
        mult *= m
        steps.append((k, mult))

raw = predict(OPP, **pred_args)
print(f"\n=== 乘数链 ===")
for name, val in steps:
    if name == "base":
        print(f"  {name}: {val:,.0f}")
    elif name == "away_winless_losses":
        print(f"  ×{name}=0.77(S/A) → cum={val:.4f}")
    else:
        print(f"  ×{name}={MULTIPLIERS.get(name, '?')} → cum={val:.4f}")
print(f"\n预测: {raw:,.0f}  (A基值{TIER_BASE['A']:,.0f} × {mult:.4f})")
print(f"实际: 8,341")
print(f"误差: {raw - 8341:+,.0f}")
