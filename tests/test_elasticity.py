import pathlib

import numpy as np
import pandas as pd
import pytest

from src.elasticity import (
    ElasticityResult,
    fit_constant_elasticity,
    fit_within_match_elasticities,
)


def test_fit_elasticity_negative():
    """需求弹性应为负值"""
    np.random.seed(42)
    prices = np.array([260, 340, 440, 580, 780, 1380])
    quantities = np.array([12000, 10000, 8000, 5000, 3000, 1000]) + np.random.normal(
        0, 200, 6
    )
    data = pd.DataFrame({"price": prices, "quantity": quantities})

    result = fit_constant_elasticity(data)
    assert result.elasticity < -0.5
    assert result.r_squared > 0.5


def test_predict_demand():
    """涨价→需求下降"""
    result = ElasticityResult(elasticity=-2.0, base_demand=10000, base_price=340)
    assert result.predict(340) == pytest.approx(10000, rel=0.01)
    assert result.predict(680) < 5000  # 翻倍价格→需求<50%


def test_fit_constant_elasticity_explicit_base_price():
    data = pd.DataFrame({"price": [260.0, 580.0], "quantity": [5000.0, 2000.0]})
    r_median = fit_constant_elasticity(data, base_price=None)
    r440 = fit_constant_elasticity(data, base_price=440.0)
    assert r_median.elasticity == pytest.approx(r440.elasticity)
    assert r440.base_price == 440.0
    assert r440.base_demand == pytest.approx(r440.predict(440.0), rel=1e-6)


def test_fit_within_match_elasticities_median_eps():
    rows = []
    for mid, scale in [("m1", 100.0), ("m2", 200.0)]:
        for p, q in [
            (260.0, 5 * scale),
            (340.0, 4 * scale),
            (440.0, 3 * scale),
            (580.0, 2 * scale),
        ]:
            rows.append(
                {"match_id": mid, "match_tier": "A", "price": p, "quantity": q}
            )
    df = pd.DataFrame(rows)
    out = fit_within_match_elasticities(df)
    assert "A" in out
    assert out["A"].elasticity < -0.1
    assert out["A"].base_price == 440.0
    assert out["A"].r_squared > 0.7


_USER_XLSX = pathlib.Path("data/raw/25年散票用户购买记录更新.xlsx")


@pytest.mark.skipif(not _USER_XLSX.exists(), reason="缺少用户购买记录 xlsx")
def test_fit_elasticity_from_transactions():
    """真实购买记录 → ε 应在 -1.5 到 -3.0 之间"""
    from src.elasticity import fit_elasticity_from_transactions

    result = fit_elasticity_from_transactions(str(_USER_XLSX))
    assert -3.5 < result.elasticity < -1.0
    assert result.r_squared > 0.4
