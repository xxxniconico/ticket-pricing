from src.dynamic_optimizer import DynamicPricingOptimizer


def test_t4_henan_elastic_cap():
    opt = DynamicPricingOptimizer()
    r = opt.optimize("河南")
    assert r.tiers["T4"].base_price == 460
    # V8.1: T4 涨价增量收入 ¥8,470 < ¥10,000 阈值 → 维持基准价
    assert r.tiers["T4"].optimal_price == 460

    r_sat = opt.optimize("河南", saturday=True)
    assert r_sat.tiers["T4"].optimal_price == 460
