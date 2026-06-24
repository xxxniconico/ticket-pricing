#!/usr/bin/env python3
"""验证下一场主场选取是否正确。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.csl_context import (
    finalize_guoan_schedule,
    get_guoan_matches,
    get_next_guoan_match,
    load_csl_data,
    resolve_next_matches,
)


def _filter_guoan(guoan):
    return [
        m for m in guoan
        if m.get("completed")
        or "cfl_fixtures_api" in m.get("source", "")
        or "wikipedia" in m.get("source", "")
    ]


def main():
    matches, _, _ = load_csl_data()
    guoan = finalize_guoan_schedule(_filter_guoan(get_guoan_matches(matches)))

    dalian = [m for m in guoan if m["date"] == "2026-05-06" and m.get("is_home")]
    print(f"2026-05-06 主场条目数: {len(dalian)}")
    for m in dalian:
        print(f"  vs {m['opponent']} completed={m['completed']} hg={m['hg']} ag={m['ag']}")

    stale = [
        m for m in guoan
        if not m.get("completed") and m["date"].startswith("2026") and m["date"] < "2026-06-13"
    ]
    print(f"过期未赛脏数据: {len(stale)}")
    for m in stale:
        print(f"  {m['date']} vs {m['opponent']} home={m.get('is_home')}")

    _, next_home, target = resolve_next_matches(guoan)
    print(f"next_home: {next_home and next_home['date']} vs {next_home and next_home['opponent']}")
    print(f"target:    {target and target['date']} vs {target and target['opponent']}")

    assert len(dalian) == 1 and dalian[0]["completed"], "大连场应唯一且已完赛"
    assert not stale, f"不应有过期 scheduled 行: {stale}"
    assert next_home and next_home["date"] == "2026-06-27", "下一场主场应为 6/27"
    assert "武汉" in next_home["opponent"]
    print("VERIFY_NEXT_MATCH_PASS")


if __name__ == "__main__":
    main()
