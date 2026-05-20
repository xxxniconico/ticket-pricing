"""优化求解器

[DEPRECATED — 2026-05-19 P0.3] optimize_10tier / TIER_CAPACITIES_V4 基于KMeans 10档聚类，
与国安真实6档×2级 zone 结构不匹配。P1将重建基于 zone_tier_map.json 的6档优化器。
optimize_multi_tier（旧6档）同样待P1替换。
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from src.elasticity import ElasticityResult

TIER_ORDER_10: list[str] = [f"T{i}" for i in range(1, 11)]

# [DEPRECATED] KMeans聚类容量，非真实zone容量
TIER_CAPACITIES_V4: dict[str, int] = {
    "T1": 100,
    "T2": 50,
    "T3": 700,
    "T4": 400,
    "T5": 400,
    "T6": 600,
    "T7": 1700,
    "T8": 1200,
    "T9": 2800,
    "T10": 3900,
}

# [DEPRECATED] KMeans聚类弹性假设，非真实zone弹性（真实弹性见 zone_tier_map.json）
TIER_PRICE_ELASTICITY: dict[str, float] = {
    "T1": -0.8,
    "T2": -0.8,
    "T3": -1.0,
    "T4": -1.5,
    "T5": -1.5,
    "T6": -2.0,
    "T7": -2.0,
    "T8": -2.5,
    "T9": -3.0,
    "T10": -3.5,
}


@dataclass
class PricingResult:
    optimal_price: float
    predicted_demand: float
    revenue: float
    attendance_rate: float
    objective_value: float


@dataclass
class MultiTierPricingResult:
    optimal_prices: dict[str, float]
    predicted_demand: dict[str, float]
    tier_revenue: dict[str, float]
    total_revenue: float
    total_attendance: float
    attendance_rate: float
    objective_value: float


def optimize_single_price(
    model: ElasticityResult,
    demand_multiplier: float = 1.0,
    capacity: int = 40000,
    revenue_weight: float = 0.6,
    price_floor_pct: float = 0.6,
    price_ceiling_pct: float = 2.5,
) -> PricingResult:
    """单价格点优化"""
    p_min = model.base_price * price_floor_pct
    p_max = model.base_price * price_ceiling_pct
    baseline_rev = model.base_price * model.base_demand

    def objective(price: np.ndarray) -> float:
        p = float(price[0])
        demand = min(model.predict(p) * demand_multiplier, capacity)
        revenue = p * demand
        att_rate = demand / capacity
        rev_score = revenue / 1_000_000
        att_score = att_rate * baseline_rev / 1_000_000
        return -(revenue_weight * rev_score + (1 - revenue_weight) * att_score)

    result = minimize(
        objective,
        np.array([model.base_price], dtype=float),
        bounds=[(p_min, p_max)],
        method="L-BFGS-B",
    )

    opt_p = float(result.x[0])
    demand = min(model.predict(opt_p) * demand_multiplier, capacity)

    return PricingResult(
        optimal_price=round(opt_p, 0),
        predicted_demand=round(demand, 0),
        revenue=round(opt_p * demand, 0),
        attendance_rate=round(demand / capacity, 3),
        objective_value=float(-result.fun),
    )


def optimize_multi_tier(
    models: dict[str, ElasticityResult],
    capacities: dict[str, int],
    demand_multiplier: float = 1.0,
    revenue_weight: float = 0.6,
    price_floor_pct: float = 0.6,
    price_ceiling_pct: float = 2.5,
    tier_order: list[str] | None = None,
) -> MultiTierPricingResult:
    """联合优化多档位价格向量

    每个档位可有独立 ``ElasticityResult``（含各自 ε_i、P0_i、D0_i），满足反馈 #3。
    目标: max  ω·Σ(P_i × Q_i) + (1-ω)·(ΣQ_i / ΣCap_i) × baseline_rev
    其中 Q_i = min(D_i × (P_i/P0_i)^ε_i × M, Cap_i)
    """
    tiers = tier_order if tier_order is not None else list(models.keys())
    for t in tiers:
        if t not in models or t not in capacities:
            raise KeyError(f"缺少档位模型或容量: {t}")

    n = len(tiers)
    x0 = np.array([models[t].base_price for t in tiers], dtype=float)
    bounds = [
        (models[t].base_price * price_floor_pct, models[t].base_price * price_ceiling_pct)
        for t in tiers
    ]

    total_capacity = float(sum(capacities[t] for t in tiers))
    baseline_rev = sum(models[t].base_price * models[t].base_demand for t in tiers)

    def objective(prices: np.ndarray) -> float:
        total_rev = 0.0
        total_demand = 0.0
        for i, t in enumerate(tiers):
            p = float(prices[i])
            q = min(models[t].predict(p) * demand_multiplier, capacities[t])
            total_rev += p * q
            total_demand += q

        att_rate = total_demand / total_capacity if total_capacity > 0 else 0.0
        rev_score = total_rev / 1_000_000
        att_score = att_rate * baseline_rev / 1_000_000
        return -(revenue_weight * rev_score + (1 - revenue_weight) * att_score)

    result = minimize(objective, x0, bounds=bounds, method="L-BFGS-B")

    optimal_prices: dict[str, float] = {}
    predicted_demand: dict[str, float] = {}
    tier_revenue: dict[str, float] = {}
    total_dem = 0.0

    for i, t in enumerate(tiers):
        p = float(result.x[i])
        q = min(models[t].predict(p) * demand_multiplier, capacities[t])
        optimal_prices[t] = round(p, 0)
        predicted_demand[t] = round(q, 0)
        tier_revenue[t] = round(p * q, 0)
        total_dem += q

    att_rate = total_dem / total_capacity if total_capacity > 0 else 0.0
    total_rev_rounded = sum(tier_revenue[t] for t in tiers)

    return MultiTierPricingResult(
        optimal_prices=optimal_prices,
        predicted_demand=predicted_demand,
        tier_revenue=tier_revenue,
        total_revenue=float(total_rev_rounded),
        total_attendance=round(total_dem, 0),
        attendance_rate=round(att_rate, 4),
        objective_value=float(-result.fun),
    )


def optimize_10tier(
    models: dict[str, ElasticityResult],
    capacities: dict[str, int] | None = None,
    demand_multiplier: float = 1.0,
    revenue_weight: float = 0.6,
    price_floor_pct: float = 0.6,
    price_ceiling_pct: float = 2.5,
    tier_order: list[str] | None = None,
    frozen_tiers: list[str] | None = None,
) -> MultiTierPricingResult:
    """十档联合优化；``frozen_tiers`` 内档位锁定基准价（死忠/VIP 区）。"""
    tiers = tier_order if tier_order is not None else TIER_ORDER_10
    caps = capacities if capacities is not None else dict(TIER_CAPACITIES_V4)
    frozen = set(frozen_tiers or [])

    for t in tiers:
        if t not in models or t not in caps:
            raise KeyError(f"缺少档位模型或容量: {t}")

    n = len(tiers)
    x0 = np.array([models[t].base_price for t in tiers], dtype=float)
    bounds = [
        (models[t].base_price * price_floor_pct, models[t].base_price * price_ceiling_pct)
        for t in tiers
    ]

    total_capacity = float(sum(caps[t] for t in tiers))
    baseline_rev = sum(models[t].base_price * models[t].base_demand for t in tiers)

    def objective(prices: np.ndarray) -> float:
        total_rev = 0.0
        total_demand = 0.0
        for i, t in enumerate(tiers):
            p = float(prices[i])
            q = min(models[t].predict(p) * demand_multiplier, caps[t])
            total_rev += p * q
            total_demand += q
        att_rate = total_demand / total_capacity if total_capacity > 0 else 0.0
        rev_score = total_rev / 1_000_000
        att_score = att_rate * baseline_rev / 1_000_000
        return -(revenue_weight * rev_score + (1 - revenue_weight) * att_score)

    if frozen:
        free_idx = [i for i, t in enumerate(tiers) if t not in frozen]
        if not free_idx:
            prices_fixed = x0.copy()
        else:
            x0_free = x0[free_idx]
            bounds_free = [bounds[i] for i in free_idx]

            def objective_free(prices_free: np.ndarray) -> float:
                full = x0.copy()
                for j, idx in enumerate(free_idx):
                    full[idx] = float(prices_free[j])
                return objective(full)

            result = minimize(objective_free, x0_free, bounds=bounds_free, method="L-BFGS-B")
            prices_fixed = x0.copy()
            for j, idx in enumerate(free_idx):
                prices_fixed[idx] = float(result.x[j])
    else:
        result = minimize(objective, x0, bounds=bounds, method="L-BFGS-B")
        prices_fixed = result.x

    optimal_prices: dict[str, float] = {}
    predicted_demand: dict[str, float] = {}
    tier_revenue: dict[str, float] = {}
    total_dem = 0.0

    for i, t in enumerate(tiers):
        p = float(prices_fixed[i])
        q = min(models[t].predict(p) * demand_multiplier, caps[t])
        optimal_prices[t] = round(p, 0)
        predicted_demand[t] = round(q, 0)
        tier_revenue[t] = round(p * q, 0)
        total_dem += q

    att_rate = total_dem / total_capacity if total_capacity > 0 else 0.0
    total_rev_rounded = sum(tier_revenue[t] for t in tiers)

    obj_val = float(-objective(prices_fixed))

    return MultiTierPricingResult(
        optimal_prices=optimal_prices,
        predicted_demand=predicted_demand,
        tier_revenue=tier_revenue,
        total_revenue=float(total_rev_rounded),
        total_attendance=round(total_dem, 0),
        attendance_rate=round(att_rate, 4),
        objective_value=obj_val,
    )
