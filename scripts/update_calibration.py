#!/usr/bin/env python3
"""赛后自动校准：遍历国安已赛主场，把缺失场次写入 EMA calibration。

用法:
  .venv/bin/python scripts/update_calibration.py            # 全量补齐缺失场次
  .venv/bin/python scripts/update_calibration.py --dry-run  # 只打印不写盘

背景（2026-08-03）:
  - 校准原本在 dashboard/tabs/tab_history.py 渲染时惰性触发——不打开"历史定价"
    tab 就不更新，导致浙江 8/1 等场次从未进 calibration.json
  - 现改为脚本驱动：ingest_match.py 导入销售数据后自动调用本脚本
"""
import sys, argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from src.csl_context import load_csl_data, detect_ctx, get_guoan_matches
from dashboard.common.data_cache import get_ctx_rounds, get_actual, set_ctx_rounds
from dashboard.components.ctx_builder import build_pred_args
from src.rule_engine import update as rule_update, _load_cal


def collect_pending_home_matches():
    """返回 [(match, pred_args, actual)]：已赛、有实际销量、未在 calibration history 的主场。"""
    cal = _load_cal()
    done_ids = {h.get("match_id") for h in cal.get("history", [])}

    matches, rounds, _ = load_csl_data()
    set_ctx_rounds(rounds)
    guoan = get_guoan_matches(matches)

    pending = []
    for m in guoan:
        if not m.get("completed") or not m.get("is_home"):
            continue
        if not m["date"].startswith("2026"):
            continue
        mid = f"{m['date']}_{m['opponent']}"
        if mid in done_ids:
            continue
        a = get_actual(m)
        if a == 0:
            print(f"  ⏭️ {mid}: 无实际销量数据（get_actual=0），跳过")
            continue
        ctx = detect_ctx(m, guoan, rounds)
        pred_args = build_pred_args(m, ctx, {
            'summer': pd.Timestamp(m['date']).month in (7, 8),
            'match_year': m['date'][:4],
        })
        pending.append((m, pred_args, a))
    return pending


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只打印不写盘")
    args = ap.parse_args()

    pending = collect_pending_home_matches()
    if not pending:
        print("✅ 无缺失场次，calibration 已是最新")
        return

    print(f"发现 {len(pending)} 场已赛未校准:")
    for m, pa, a in pending:
        print(f"  - {m['date']} vs {m['opponent']} actual={a}")

    if args.dry_run:
        print("\n(dry-run) 未写盘")
        return

    for m, pa, a in pending:
        mid = f"{m['date']}_{m['opponent']}"
        rule_update(match_id=mid, opponent=m['opponent'], actual=a, **pa)
        print(f"  ✅ {mid}: 校准已写入 (actual={a})")

    cal = _load_cal()
    print(f"\n完成。tier 校准因子: {cal['tier']} | history {len(cal['history'])} 条")


if __name__ == "__main__":
    main()
