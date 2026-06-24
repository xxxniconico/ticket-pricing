#!/usr/bin/env python3
"""ELO 自动更新 — Phase 4.1

每轮 CSL 比赛后，加载最新结果 -> 增量更新 ELO -> 写回 parquet -> 生成快照。

用法:
  python scripts/update_elo.py [--rebuild]
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date
from src.csl_context import load_csl_data
from src.opponent_rating import (
    compute_elo_history, load_elo_history, save_elo_history, build_snapshot,
    _ELO_PATH,
)


def main(rebuild=False):
    print("Updating ELO ratings...")

    # Load existing ELO history
    elo_history = load_elo_history()
    print(f"  Existing ELO: {len(elo_history)} rows")

    # Load latest CSL data
    matches, standings, _ = load_csl_data()

    if rebuild or elo_history.empty:
        # Full rebuild
        print("  Full rebuild...")
        elo_history = compute_elo_history(matches)
    else:
        # Incremental: find new matches
        last_date = elo_history["date"].max()
        new_matches = [
            m for m in matches
            if m.get("completed") and m.get("date", "") > str(last_date)[:10]
        ]
        if not new_matches:
            print(f"  No new matches since {last_date}")
        else:
            print(f"  Processing {len(new_matches)} new matches...")
            elo_history = compute_elo_history(matches)

    # Save
    save_elo_history(elo_history)
    print(f"  Saved {len(elo_history)} ELO rows")

    # Generate today's snapshot
    today = date.today().isoformat()
    cards = build_snapshot(today, elo_history=elo_history, matches=matches,
                           standings_by_round=standings)
    print(f"  Snapshot {today}: {len(cards)} teams")
    print("Done!")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Update ELO ratings")
    parser.add_argument("--rebuild", action="store_true", help="Full rebuild")
    args = parser.parse_args()
    main(rebuild=args.rebuild)
