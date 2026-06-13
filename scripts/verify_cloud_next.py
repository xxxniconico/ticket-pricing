#!/usr/bin/env python3
"""模拟 Streamlit Cloud：强制走线上 JSON，验证下一场。"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 强制云端回退（与 Streamlit Cloud 一致）
os.environ["CSL_FORCE_CLOUD"] = "1"

from src.csl_context import (  # noqa: E402
    finalize_guoan_schedule,
    get_guoan_matches,
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
    # 让 load_csl_data 必定走 cloud
    import src.csl_context as cc

    _orig = cc.load_csl_data

    def _cloud_only(*a, **kw):
        kw["csl_path"] = "/nonexistent/csl.json"
        kw["deductions_path"] = "/nonexistent/ded.json"
        return _orig(*a, **kw)

    cc.load_csl_data = _cloud_only

    matches, _, _ = load_csl_data()
    guoan = finalize_guoan_schedule(_filter_guoan(get_guoan_matches(matches)))

    dalian = [m for m in guoan if "2026-05-06" in m["date"] and m.get("is_home")]
    print("=== 2026-05-06 主场 ===")
    for m in dalian:
        print(f"  vs {m['opponent']} completed={m['completed']} hg={m['hg']} ag={m['ag']}")

    uncompleted = [
        m for m in guoan
        if not m.get("completed") and str(m.get("date", "")).startswith("2026")
    ]
    print(f"\n=== 未赛 2026 场次 ({len(uncompleted)}) ===")
    for m in uncompleted[:5]:
        print(f"  {m['date']} {'主' if m.get('is_home') else '客'} vs {m['opponent']}")

    _, next_home, target = resolve_next_matches(guoan)
    print(f"\nnext_home: {next_home and next_home['date']} vs {next_home and next_home['opponent']}")
    print(f"target:    {target and target['date']} vs {target and target['opponent']}")

    ok = (
        len(dalian) <= 1
        and (not dalian or dalian[0]["completed"])
        and target
        and target["date"] == "2026-06-27"
        and "武汉" in target["opponent"]
    )
    print("\nPASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
