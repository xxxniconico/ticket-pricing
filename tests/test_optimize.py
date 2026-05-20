import pytest

from src.elasticity import ElasticityResult
from src.optimize import optimize_multi_tier, optimize_single_price


def test_optimize_single_price_respects_bounds():
    model = ElasticityResult(
        elasticity=-1.2,
        base_demand=8000.0,
        base_price=340.0,
        r_squared=0.9,
    )
    out = optimize_single_price(model, demand_multiplier=1.0, capacity=50000)
    assert model.base_price * 0.6 <= out.optimal_price <= model.base_price * 2.5
    assert 0 <= out.attendance_rate <= 1.0
    # revenue 与「四舍五入后的价×量」可能略有舍入差
    assert out.revenue == pytest.approx(
        out.optimal_price * out.predicted_demand, rel=0.02
    )


def test_optimize_higher_multiplier_raises_demand_cap():
    model = ElasticityResult(
        elasticity=-0.8,
        base_demand=100000.0,
        base_price=200.0,
        r_squared=0.5,
    )
    cap = 200_000
    low = optimize_single_price(
        model, demand_multiplier=0.5, capacity=cap
    ).predicted_demand
    high = optimize_single_price(
        model, demand_multiplier=2.0, capacity=cap
    ).predicted_demand
    assert high >= low


def test_optimize_multi_tier_respects_bounds_and_totals():
    models = {
        "a": ElasticityResult(
            elasticity=-1.0, base_demand=5000.0, base_price=300.0, r_squared=0.8
        ),
        "b": ElasticityResult(
            elasticity=-1.0, base_demand=3000.0, base_price=500.0, r_squared=0.8
        ),
    }
    caps = {"a": 8000, "b": 12000}
    out = optimize_multi_tier(
        models,
        caps,
        demand_multiplier=1.0,
        tier_order=["a", "b"],
    )
    for t in caps:
        assert models[t].base_price * 0.6 <= out.optimal_prices[t] <= models[t].base_price * 2.5
    assert out.total_attendance == pytest.approx(
        out.predicted_demand["a"] + out.predicted_demand["b"], rel=1e-6
    )
    assert out.total_revenue == pytest.approx(
        out.tier_revenue["a"] + out.tier_revenue["b"], rel=1e-6
    )
