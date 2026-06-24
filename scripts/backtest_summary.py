#!/usr/bin/env python3
"""规则引擎回测摘要 — 与看板 compute_home_predictions 同口径。"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dashboard.common.data_cache import compute_home_predictions, load_data, set_ctx_rounds


def main():
    all_matches, rounds, guoan = load_data()
    if not guoan:
        print("BACKTEST_SUMMARY_SKIP: no guoan matches")
        return 1

    set_ctx_rounds(rounds)
    home_done = [m for m in guoan if m.get("is_home") and m.get("completed")]
    preds = compute_home_predictions(home_done, guoan, enable_ema=False)
    if not preds:
        print("BACKTEST_SUMMARY_SKIP: no predictions")
        return 1

    by_year: dict[str, list[float]] = {}
    flag_counts: dict[str, int] = {}
    for m, p, a, ctx in preds:
        yr = m["date"][:4]
        if a > 0:
            by_year.setdefault(yr, []).append(abs(p - a))
        for k in ("consecutive_home_losses", "heavy_home_loss", "away_winless", "top3_form", "midseason_restart"):
            if ctx.get(k):
                flag_counts[k] = flag_counts.get(k, 0) + 1

    print("=" * 60)
    print("规则引擎回测摘要（看板同口径 · EMA 关）")
    print("=" * 60)
    all_errs = []
    for yr in sorted(by_year):
        yr_rows = [(m, p, a) for m, p, a, _ in preds if m["date"].startswith(yr) and a > 0]
        errs = [abs(p - a) for _, p, a in yr_rows]
        all_errs.extend(errs)
        mae = float(np.mean(errs))
        mape = float(np.mean([abs(p - a) / a * 100 for _, p, a in yr_rows]))
        print(f"  {yr}: n={len(errs):2d}  MAE={mae:,.0f}  MAPE={mape:.1f}%")

    overall = float(np.mean(all_errs))
    print(f"\n  合计: n={len(all_errs)}  MAE={overall:,.0f}")
    if flag_counts:
        flags = ", ".join(f"{k}={v}" for k, v in sorted(flag_counts.items()))
        print(f"  情境触发: {flags}")
    print("BACKTEST_SUMMARY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
