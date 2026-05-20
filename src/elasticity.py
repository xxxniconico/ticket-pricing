"""需求弹性拟合：价格-销量 → 弹性系数"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats


@dataclass
class ElasticityResult:
    elasticity: float
    base_demand: float
    base_price: float
    r_squared: float = 0.0

    def predict(self, price: float) -> float:
        """Q = D₀ × (P/P₀)^ε"""
        ratio = price / self.base_price
        return self.base_demand * (ratio**self.elasticity)

    def revenue_at_price(self, price: float) -> float:
        return price * self.predict(price)


def fit_constant_elasticity(
    data: pd.DataFrame,
    base_price: float | None = None,
) -> ElasticityResult:
    """用恒定弹性模型拟合

    Args:
        data: 含 price, quantity 列的DataFrame
        base_price: 若给定，则在该档位价上反推 base_demand；否则用样本价格中位数
    """
    prices = data["price"].values.astype(float)
    quantities = data["quantity"].values.astype(float)

    log_p = np.log(prices)
    log_q = np.log(quantities)

    slope, intercept, _r_value, _p_value, _std_err = stats.linregress(log_p, log_q)

    if base_price is not None:
        bp = float(base_price)
    else:
        bp = float(np.median(prices))

    base_demand = float(np.exp(intercept + slope * np.log(bp)))

    predicted_log = intercept + slope * log_p
    ss_res = np.sum((log_q - predicted_log) ** 2)
    ss_tot = np.sum((log_q - np.mean(log_q)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    return ElasticityResult(
        elasticity=float(slope),
        base_demand=base_demand,
        base_price=bp,
        r_squared=float(r_squared),
    )


def fit_within_match_elasticities(
    demand_data: pd.DataFrame,
) -> dict[str, ElasticityResult]:
    """每场次单独拟合恒定弹性 → 取中位数 ε；单场反推需求统一锚在 A¥440 / B¥300（回测用，CLI 不用）。"""
    results: dict[str, ElasticityResult] = {}

    for tier in ["A", "B"]:
        anchor = 440.0 if tier == "A" else 300.0
        tier_data = demand_data[demand_data["match_tier"] == tier]
        elasticities: list[float] = []
        base_demands: list[float] = []
        r2s: list[float] = []

        for match_id in tier_data["match_id"].unique():
            match_data = tier_data[tier_data["match_id"] == match_id]
            if len(match_data) >= 4:
                result = fit_constant_elasticity(match_data, base_price=anchor)
                elasticities.append(result.elasticity)
                base_demands.append(result.base_demand)
                r2s.append(result.r_squared)

        if elasticities:
            median_eps = float(np.median(elasticities))
            median_r2 = float(np.median(r2s))
            median_bd = float(np.median(base_demands))

            results[tier] = ElasticityResult(
                elasticity=median_eps,
                base_demand=median_bd,
                base_price=anchor,
                r_squared=median_r2,
            )

    return results


def fit_elasticity_from_transactions(
    filepath: str = "data/raw/25年散票用户购买记录更新.xlsx",
) -> ElasticityResult:
    """从用户购买记录拟合弹性（真实市场行为）

    交易数据中「票价信息」= 用户实际面对的单价，
    「数量」= 购买张数。同一产品在不同价格下的
    购买决策 → 真正的需求曲线。
    """
    from src.ingest import load_user_purchases

    df = load_user_purchases(filepath)
    df = df.dropna(subset=["unit_price", "qty_clean"])

    agg = (
        df.groupby("unit_price")["qty_clean"]
        .sum()
        .reset_index()
        .rename(columns={"unit_price": "price", "qty_clean": "quantity"})
    )

    return fit_constant_elasticity(agg, base_price=None)


# 兼容旧名（计划文档 / 脚本）
fit_by_match_tier = fit_within_match_elasticities


def estimate_tier_elasticity(
    filepath: str = "data/raw/全量散票用户购买记录_统一.xlsx",
) -> dict[str, ElasticityResult]:
    """按 S/A/B/C 分级弹性；交易数据无场次标签时用全局 ε + 级别偏移。"""
    from src.ingest import load_user_purchases

    paths = [
        filepath,
        "data/raw/25年散票用户购买记录更新.xlsx",
    ]
    global_result: ElasticityResult | None = None
    for p in paths:
        try:
            df = load_user_purchases(p)
            agg = (
                df.dropna(subset=["unit_price", "qty_clean"])
                .groupby("unit_price")["qty_clean"]
                .sum()
                .reset_index()
                .rename(columns={"unit_price": "price", "qty_clean": "quantity"})
            )
            if len(agg) >= 3:
                global_result = fit_constant_elasticity(agg, base_price=None)
                break
        except Exception:
            continue

    if global_result is None:
        global_result = ElasticityResult(
            elasticity=-2.5,
            base_demand=1000.0,
            base_price=400.0,
            r_squared=0.0,
        )

    defaults = {
        "S": ElasticityResult(elasticity=-0.5, base_demand=global_result.base_demand, base_price=global_result.base_price, r_squared=0.0),
        "A": ElasticityResult(elasticity=-1.5, base_demand=global_result.base_demand, base_price=global_result.base_price, r_squared=0.0),
        "B": ElasticityResult(elasticity=-2.5, base_demand=global_result.base_demand, base_price=global_result.base_price, r_squared=global_result.r_squared),
        "C": ElasticityResult(elasticity=-3.0, base_demand=global_result.base_demand, base_price=global_result.base_price, r_squared=0.0),
        "global": global_result,
    }

    return defaults
