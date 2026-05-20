from src.dynamic_optimizer import DynamicPricingOptimizer


def test_t4_henan_elastic_cap():
    opt = DynamicPricingOptimizer()
    r = opt.optimize("河南")
    assert r.tiers["T4"].base_price == 460
    assert r.tiers["T4"].optimal_price == 500

    r_sat = opt.optimize("河南", saturday=True)
    assert r_sat.tiers["T4"].optimal_price == 500
