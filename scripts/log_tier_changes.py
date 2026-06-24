#!/usr/bin/env python3
"""档位变更日志 — Phase 3.3

每次 build_snapshot 时对比上一次快照，记录档位变更。
生成 data/processed/tier_changes.json
"""
import sys, json
from pathlib import Path
from datetime import date
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.opponent_rating import build_snapshot, ALL_CSL_TEAMS_2026, _DATA_DIR
from src.classify import classify_opponent_tier as old_classify

CHANGES_PATH = _DATA_DIR / "tier_changes.json"

def log_changes(date_str=None):
    if date_str is None:
        date_str = date.today().isoformat()
    
    cards = build_snapshot(date_str)
    current = {c["opponent"]: c["tier"] for c in cards}
    static = {t: old_classify(t) for t in ALL_CSL_TEAMS_2026}
    
    # Load previous snapshot
    prev = {}
    prev_path = sorted(_DATA_DIR.glob("rating_snapshot_*.json"))
    if len(prev_path) >= 2:
        with open(prev_path[-2]) as f:
            prev_data = json.load(f)
        prev = {c["opponent"]: c["tier"] for c in prev_data.get("cards", [])}
    
    # Load existing changes log
    changes = []
    if CHANGES_PATH.exists():
        with open(CHANGES_PATH) as f:
            changes = json.load(f)
    
    # Check for changes vs previous snapshot and vs static
    for team in ALL_CSL_TEAMS_2026:
        new_tier = current.get(team)
        old_dynamic = prev.get(team)
        old_static = static.get(team)
        
        if old_dynamic and old_dynamic != new_tier:
            changes.append({
                "date": date_str, "team": team,
                "from": old_dynamic, "to": new_tier,
                "type": "dynamic_shift",
                "reason": f"Dynamic tier changed: {old_dynamic} -> {new_tier}"
            })
        elif new_tier != old_static:
            # Check if already logged
            already = any(
                c["team"] == team and c["to"] == new_tier and c["type"] == "static_diff"
                for c in changes
            )
            if not already:
                changes.append({
                    "date": date_str, "team": team,
                    "from": old_static, "to": new_tier,
                    "type": "static_diff",
                    "reason": f"Dynamic vs static: {old_static} -> {new_tier}"
                })
    
    with open(CHANGES_PATH, "w") as f:
        json.dump(changes, f, ensure_ascii=False, indent=2)
    
    print(f"Tier changes logged: {len(changes)} entries")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=None)
    args = p.parse_args()
    log_changes(args.date)
