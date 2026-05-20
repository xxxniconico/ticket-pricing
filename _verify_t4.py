from src.dynamic_optimizer import DynamicPricingOptimizer
opt = DynamicPricingOptimizer()
r = opt.optimize('河南')
print('T4:', r.tiers['T4'].base_price, '->', r.tiers['T4'].optimal_price)
