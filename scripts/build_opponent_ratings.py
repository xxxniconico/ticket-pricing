#!/usr/bin/env python3
"""离线生成对手评分数据 — Phase 1.8

生成:
  - data/processed/elo_history.parquet
  - data/processed/appeal_scores.parquet
  - data/processed/rating_snapshot_YYYYMMDD.json

用法:
  python scripts/build_opponent_ratings.py [--date YYYY-MM-DD]
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.csl_context import load_csl_data
from src.opponent_rating import (
    compute_elo_history, save_elo_history, save_appeal_scores,
    build_snapshot, get_all_tier_distribution, _load_guoan_home_attendance,
    get_opponent_scorecard, ALL_CSL_TEAMS_2026,
)


def main(date_str="2026-06-25"):
    print(f"Building opponent ratings as of {date_str}...")

    # 1. Load CSL data
    print("  Loading CSL data...")
    matches, standings_by_round, _ = load_csl_data()
    print(f"  Loaded {len(matches)} matches ({len([m for m in matches if m.get('completed')])} completed)")

    # 2. Compute ELO history
    print("  Computing ELO history...")
    elo_history = compute_elo_history(matches)
    save_elo_history(elo_history)
    print(f"  ELO history: {len(elo_history)} rows saved")

    # 3. Compute and save AP scores
    print("  Computing AP scores...")
    guoan_home_history = _load_guoan_home_attendance()
    print(f"  Attendance data: {len(guoan_home_history)} home matches")

    appeal_rows = []
    for team in ALL_CSL_TEAMS_2026:
        card = get_opponent_scorecard(
            team, date_str,
            elo_history=elo_history,
            standings_by_round=standings_by_round,
            matches=matches,
            guoan_home_history=guoan_home_history,
        )
        appeal_rows.append({
            "opponent": card["opponent"],
            "as_of": date_str,
            "elo": card["elo"],
            "ST": card["ST"],
            "AP": card["AP"],
            "tier": card["tier"],
        })

    import pandas as pd
    appeal_df = pd.DataFrame(appeal_rows)
    save_appeal_scores(appeal_df)
    print(f"  Appeal scores: {len(appeal_df)} teams saved")

    # 4. Build snapshot
    print("  Building snapshot...")
    cards = build_snapshot(date_str, elo_history=elo_history,
                           matches=matches, standings_by_round=standings_by_round)
    print(f"  Snapshot: {len(cards)} teams")

    # 5. Print summary
    dist = get_all_tier_distribution(date_str, elo_history=elo_history,
                                     matches=matches, standings_by_round=standings_by_round)
    print(f"  Tier distribution: {dist}")

    print()
    print("=" * 60)
    print(f"{'Opponent':<14s} {'ELO':>7s} {'ST':>6s} {'AP':>6s} {'Tier':>5s}")
    print("-" * 42)
    for team in ALL_CSL_TEAMS_2026:
        card = get_opponent_scorecard(team, date_str, elo_history=elo_history,
            standings_by_round=standings_by_round, matches=matches,
            guoan_home_history=guoan_home_history)
        print(f"{card['opponent']:<14s} {card['elo']:>7.1f} {card['ST']:>6.1f} {card['AP']:>6.1f} {card['tier']:>5s}")

    print()
    print("Done!")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Build opponent rating data")
    parser.add_argument("--date", default="2026-06-25", help="Snapshot date (YYYY-MM-DD)")
    args = parser.parse_args()
    main(args.date)
