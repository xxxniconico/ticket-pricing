#!/usr/bin/env python3
"""月度档位变更报告 — Phase 4.2

每月 1 号生成上月档位变更建议，输出 markdown。

用法:
  python scripts/monthly_tier_report.py [--month 2026-07]
"""
from __future__ import annotations
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date
from collections import defaultdict
import pandas as pd
from src.csl_context import load_csl_data, get_guoan_matches
from src.opponent_rating import (
    load_elo_history, compute_elo_history, get_opponent_scorecard,
    _load_guoan_home_attendance, FROZEN_TIERS, ALL_CSL_TEAMS_2026,
)
from src.classify import classify_opponent_tier as old_classify

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"


def generate_report(year_month="2026-07"):
    """生成月度档位变更建议报告。"""
    parts = year_month.split("-")
    year, month = int(parts[0]), int(parts[1])

    # Load data
    matches, standings, _ = load_csl_data()
    elo_history = compute_elo_history(matches)
    guoan_home = _load_guoan_home_attendance()
    guoan_matches = get_guoan_matches(matches)

    # Find upcoming home matches for this month
    upcoming = [
        m for m in guoan_matches
        if m.get("is_home") and not m.get("completed")
        and pd.Timestamp(m["date"]).year == year
        and pd.Timestamp(m["date"]).month == month
    ]

    report_date = f"{year}-{month:02d}-01"
    lines = []
    lines.append(f"# 对手档位变更建议 ({year_month})")
    lines.append("")
    lines.append(f"生成日期: {report_date}")
    lines.append(f"评估场次: {len(upcoming)}")
    lines.append("")

    # Evaluate each upcoming opponent
    changes = []
    frozen_applied = []

    for m in upcoming:
        opp = m["opponent"]
        match_date = m["date"]
        card = get_opponent_scorecard(opp, report_date, elo_history=elo_history,
            standings_by_round=standings, matches=matches,
            guoan_home_history=guoan_home)
        static = old_classify(opp)
        dynamic = card["tier"]

        if opp in FROZEN_TIERS:
            frozen_applied.append((opp, match_date, dynamic))
            continue

        if static != dynamic:
            changes.append((opp, match_date, static, dynamic, card))

    # Output
    lines.append("## 变更概览")
    lines.append(f"- 评估场次: {len(upcoming)}")
    lines.append(f"- 建议变更: {len(changes)} 次")
    lines.append(f"- 硬锁生效: {len(frozen_applied)} 次")
    lines.append("")

    if changes:
        lines.append("## 建议变更明细")
        lines.append("")
        for opp, match_date, old, new, card in changes:
            lines.append(f"### {opp}: {old} -> {new}（建议）")
            lines.append(f"- 比赛日期: {match_date}")
            lines.append(f"- 当前 ST: {card['ST']:.1f}")
            lines.append(f"- 当前 AP: {card['AP']:.1f}")
            lines.append(f"- 变更原因: 动态评分触发档位调整")
            lines.append("")

    if frozen_applied:
        lines.append("## 硬锁场次")
        for opp, match_date, tier in frozen_applied:
            lines.append(f"- {match_date} {opp}: {tier} 档（硬锁）")
        lines.append("")

    if not changes:
        lines.append("## 无变更场次")
        lines.append("本月所有对手档位与静态分级一致。")
        lines.append("")

    # Write report
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT_DIR / f"tier_report_{year_month.replace('-', '')}.md"
    report_text = "\n".join(lines)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(report_text)
    print(f"\nReport saved to {report_path}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate monthly tier report")
    parser.add_argument("--month", default="2026-07", help="Year-month (YYYY-MM)")
    args = parser.parse_args()
    generate_report(args.month)
