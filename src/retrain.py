"""模型重训：新数据加入 → 更新弹性/乘数。

2026赛季数据路径: data/raw/2026/
  26年散票购买场次.xlsx  →  2026散票数据_座位级.xlsx + 2026散票用户购买记录.xlsx
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.classify import build_base_multiplier_lookup
from src.calibrate import calibrate_context_weights
from src.elasticity import fit_elasticity_from_transactions
from src.ingest import load_all, parse_price_from_ticket_info, parse_user_quantity


def retrain(data_dir: str = "data/raw") -> dict:
    """读取 data/raw/ 下数据，重新拟合并打印关键参数。

    Returns dict: {elasticity_2025, elasticity_2026, ...}
    """
    results = {}

    # ── 2025 基线 ──
    print("=" * 55)
    print("2025 赛季基线")
    print("=" * 55)
    demand = load_all(data_dir)
    txn_el = fit_elasticity_from_transactions(
        f"{data_dir}/25年散票用户购买记录更新.xlsx"
    )
    lookup = build_base_multiplier_lookup(f"{data_dir}/2025散票数据.xlsx")
    weights = calibrate_context_weights(data_dir)

    print(f"  需求聚合行数: {len(demand)}")
    print(f"  弹性 ε: {txn_el.elasticity:.3f} (R²={txn_el.r_squared:.3f})")
    print(f"  乘数查表: {len(lookup)} 对手")
    print(f"  校准权重 (R²={weights.get('r_squared', 0):.3f}):")
    for k, v in weights.items():
        if k != "r_squared":
            print(f"    {k}: {v}")

    results["elasticity_2025"] = txn_el.elasticity
    results["r2_2025"] = txn_el.r_squared
    results["weights_2025"] = weights

    # ── 2026 增量 ──
    path_2026 = f"{data_dir}/2026/"
    txn_2026_path = f"{path_2026}/2026散票用户购买记录.xlsx"
    if Path(txn_2026_path).exists():
        print(f"\n{'=' * 55}")
        print("2026 赛季增量")
        print("=" * 55)
        try:
            df = pd.read_excel(txn_2026_path)
            df["qty_clean"] = df["数量"].apply(parse_user_quantity)
            df["unit_price"] = df["票价信息"].apply(parse_price_from_ticket_info)
            agg = df.dropna(subset=["unit_price", "qty_clean"])
            agg = agg.groupby("unit_price")["qty_clean"].sum().reset_index()

            prices = agg["unit_price"].values
            qtys = agg["qty_clean"].values
            lp, lq = np.log(prices), np.log(qtys)
            slope, intercept = np.polyfit(lp, lq, 1)
            pred = np.exp(intercept) * prices ** slope
            ss_res = float(np.sum((qtys - pred) ** 2))
            ss_tot = float(np.sum((qtys - np.mean(qtys)) ** 2))
            r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0

            print(f"  交易笔数: {len(df)} ({int(df['qty_clean'].sum())} 张)")
            print(f"  弹性 ε: {slope:.3f} (R²={r2:.3f})")
            print(f"  票价梯度: {len(agg)} 个价位 (2025: 12+)")

            if r2 < 0.2:
                print(f"  ⚠️ 2026 弹性不稳定 (样本7场、票价梯度少)")
                print(f"  建议: 继续用 2025 ε={txn_el.elasticity:.1f}")

            results["elasticity_2026"] = slope
            results["r2_2026"] = r2
        except Exception as e:
            print(f"  2026 弹性拟合失败: {e}")

    print(f"\n重训完成。")
    return results


if __name__ == "__main__":
    retrain()
