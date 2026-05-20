"""命令行：对手与情境 → 定价建议"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 支持 `python src/cli.py`（工作目录为项目根）
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd

from src.classify import (
    build_base_multiplier_lookup,
    classify_match_hybrid,
)
from src.elasticity import ElasticityResult, fit_elasticity_from_transactions
from src.ingest import (
    crosscheck_seat_demand_vs_user_purchases,
    load_all,
    load_user_purchases_by_price,
)
from src.optimize import MultiTierPricingResult, optimize_multi_tier

# 输出顺序：高区 → 低区（与反馈示例一致）
TIER_ORDER: list[str] = ["vip", "tier5", "tier4", "tier3", "tier2", "tier1"]
# 各档位散票容量（总散票池 ~27,500）
TIER_CAPACITIES: dict[str, int] = {
    "tier1": 3000,
    "tier2": 9500,
    "tier3": 7000,
    "tier4": 3000,
    "tier5": 4200,
    "vip": 800,
}


def _build_tier_models(
    demand_df,
    match_tier: str,
    txn_el: ElasticityResult | None,
) -> dict[str, ElasticityResult]:
    """六档各一条曲线：共用交易数据 ε，各档 base_price/ base_demand 独立。

    - base_price: 官方定价（A级或B级）
    - base_demand: 该档历史场均散票销量（从座位数据取）
    - elasticity: 统一用交易数据 ε（~-2.5）
    """
    if match_tier == "A":
        prices = {
            "vip": 1380,
            "tier5": 780,
            "tier4": 580,
            "tier3": 440,
            "tier2": 340,
            "tier1": 260,
        }
    else:
        prices = {
            "vip": 1080,
            "tier5": 540,
            "tier4": 460,
            "tier3": 300,
            "tier2": 220,
            "tier1": 160,
        }

    eps = txn_el.elasticity if txn_el else -2.0
    r2 = txn_el.r_squared if txn_el else 0.6

    models: dict[str, ElasticityResult] = {}
    for name, p0 in prices.items():
        if demand_df is not None and not demand_df.empty:
            td = demand_df[demand_df["match_tier"] == match_tier]
            sub = td[td["price"].astype(float) == float(p0)]
            if len(sub) > 0:
                bd = float(sub.groupby("match_id")["quantity"].sum().mean())
            else:
                bd = max(200.0, TIER_CAPACITIES[name] * 0.5)
        else:
            bd = max(200.0, TIER_CAPACITIES[name] * 0.5)

        models[name] = ElasticityResult(
            elasticity=eps,
            base_demand=bd,
            base_price=float(p0),
            r_squared=r2,
        )
    return models


def _print_crosscheck(
    data_dir: str,
    user_xlsx: str | None,
    demand_df=None,
) -> bool:
    """打印座位侧全季按价汇总 vs 用户购买流水按价汇总。成功返回 True。

    若传入 ``demand_df`` 则不再重复读取座位 Excel。
    """
    user_path = user_xlsx or f"{data_dir}/25年散票用户购买记录更新.xlsx"
    try:
        if demand_df is None:
            demand_df = load_all(data_dir)
        user_by_price = load_user_purchases_by_price(user_path)
    except (OSError, FileNotFoundError, ValueError, KeyError) as e:
        print("-------------------------------------")
        print("  对账失败：无法读取座位数据或用户购买表")
        print(f"  原因: {e}")
        print("-------------------------------------")
        return False

    cc = crosscheck_seat_demand_vs_user_purchases(demand_df, user_by_price)
    print("-------------------------------------")
    print("  数据对账（全季按票面价汇总，仅供参考）")
    print(f"  座位数据: {data_dir}/2025散票数据.xlsx → load_all")
    print(f"  用户流水: {user_path}")
    print("-------------------------------------")
    disp = cc.rename(
        columns={
            "price": "票面价(元)",
            "qty_seat": "座位表张数",
            "qty_user": "用户表张数",
            "abs_diff": "差额(座-用户)",
            "rel_diff_user": "相对用户表",
        }
    )
    with pd.option_context("display.max_rows", 50, "display.width", 120):
        print(disp.to_string(index=False))
    print("-------------------------------------")
    return True


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="北京国安主场散票动态定价建议")
    p.add_argument(
        "--opponent",
        default=None,
        help="对手中文名，如 上海申花（--crosscheck-only 时可省略）",
    )
    p.add_argument("--weekend", action="store_true", help="周五–周日场次")
    p.add_argument("--no-weekend", action="store_true", help="周中场次")
    p.add_argument("--holiday", action="store_true", help="法定假日")
    p.add_argument("--home-form", type=float, default=0.5, help="主队近态胜率 0–1")
    p.add_argument("--opponent-standing", type=int, default=8, help="对手排名（1–16）")
    p.add_argument(
        "--season-stage",
        default="mid",
        choices=["mid", "crucial", "title_race", "relegation"],
        help="赛季阶段",
    )
    p.add_argument("--temperature", type=float, default=20.0, help="气温 ℃")
    p.add_argument("--precipitation", type=float, default=0.0, help="降水量 mm")
    p.add_argument(
        "--capacity",
        type=int,
        default=27500,
        help="散票池总容量",
    )
    p.add_argument("--data-dir", default="data/raw", help="原始 Excel 目录")
    p.add_argument("--revenue-weight", type=float, default=0.6, help="收入权重 ω")
    p.add_argument(
        "--crosscheck-user-data",
        action="store_true",
        help="在定价建议之后，输出座位级聚合 vs 用户购买流水按价对账",
    )
    p.add_argument(
        "--crosscheck-only",
        action="store_true",
        help="仅做对账并退出（不需要 --opponent）",
    )
    p.add_argument(
        "--user-purchases-file",
        default=None,
        help="用户购买记录 xlsx 路径，默认 {data-dir}/25年散票用户购买记录更新.xlsx",
    )
    return p.parse_args()


def _print_multi_tier_suggestion(
    opponent: str,
    match_tier: str,
    mult: float,
    mt: MultiTierPricingResult,
    models: dict[str, ElasticityResult],
    total_capacity: int,
) -> None:
    print("=====================================")
    print(f"  北京国安 vs {opponent}  —  定价建议")
    print(f"  比赛级别: {match_tier} | 需求乘数: {mult}×")
    print("  优化目标: 60%收入 + 40%上座率")
    print("=====================================")
    print(
        f"{'档位':<7} {'基准价':>8} {'建议价':>8} {'变化':>6} {'预测需求':>10} {'档位收入':>14}"
    )
    print("─" * 65)
    for name in TIER_ORDER:
        base = models[name].base_price
        opt = mt.optimal_prices[name]
        dem = mt.predicted_demand[name]
        rev = mt.tier_revenue[name]
        pct = (opt - base) / base * 100 if base else 0.0
        pct_s = f"{pct:+.0f}%"
        print(
            f"{name:<7} ¥{base:>7,.0f} ¥{opt:>7,.0f} {pct_s:>6} "
            f"{dem:>10,.0f} ¥{rev:>12,.0f}"
        )
    print("─" * 65)
    tot_dem = mt.total_attendance
    print(f"{'合计':<7} {'':<8} {'':<8} {'':<6} {tot_dem:>10,.0f} ¥{mt.total_revenue:>12,.0f}")

    print()
    print(
        f"📊 预计上座率: {mt.attendance_rate * 100:.0f}% "
        f"({tot_dem:,.0f}/{total_capacity:,.0f})"
    )
    print(f"💰 预计收入: ¥{mt.total_revenue:,.0f}")


def main() -> None:
    args = _parse_args()
    if args.crosscheck_only:
        ok = _print_crosscheck(args.data_dir, args.user_purchases_file, demand_df=None)
        raise SystemExit(0 if ok else 1)

    if not args.opponent:
        print("错误: 需要 --opponent；若仅对账请使用 --crosscheck-only", file=sys.stderr)
        raise SystemExit(2)

    if args.weekend:
        is_weekend = True
    elif args.no_weekend:
        is_weekend = False
    else:
        is_weekend = True

    base_lookup = None
    try:
        base_lookup = build_base_multiplier_lookup(
            f"{args.data_dir}/2025散票数据.xlsx"
        )
    except (OSError, FileNotFoundError, ValueError, KeyError):
        pass

    tier, mult = classify_match_hybrid(
        args.opponent,
        base_lookup=base_lookup,
        opponent_standing=args.opponent_standing,
        is_weekend=is_weekend,
        is_holiday=args.holiday,
        season_stage=args.season_stage,
        home_form=args.home_form,
        temperature_c=args.temperature,
        precipitation_mm=args.precipitation,
    )

    demand_df = None
    txn_el = None
    try:
        demand_df = load_all(args.data_dir)
        txn_path = args.user_purchases_file or (
            f"{args.data_dir}/25年散票用户购买记录更新.xlsx"
        )
        txn_el = fit_elasticity_from_transactions(txn_path)
    except (OSError, FileNotFoundError, ValueError, KeyError):
        pass

    models = _build_tier_models(demand_df, tier, txn_el)
    caps = dict(TIER_CAPACITIES)

    mt = optimize_multi_tier(
        models,
        caps,
        demand_multiplier=mult,
        revenue_weight=args.revenue_weight,
        tier_order=TIER_ORDER,
    )

    total_cap_display = sum(caps.values())
    _print_multi_tier_suggestion(
        args.opponent, tier, mult, mt, models, total_cap_display
    )

    if args.crosscheck_user_data:
        _print_crosscheck(
            args.data_dir, args.user_purchases_file, demand_df=demand_df
        )


if __name__ == "__main__":
    main()
