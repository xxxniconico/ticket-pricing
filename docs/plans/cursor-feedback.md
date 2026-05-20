# Cursor 修复反馈 — ticket-pricing

> 测试全过，但模型输出有误。三个问题，逐个改。

---

## 🔴 问题1: 跨场次混合回归洗掉了弹性信号

**文件:** `src/elasticity.py` — `fit_by_match_tier()`

**当前做法:** 把A级4场×6档位=24个数据点混在一起做一条回归线。¥340这个点上有vs申花12K张也有vs弱队3K张，模型看到的方差来自场次差异而非价格差异。

**结果:** ε≈-0.6（接近无弹性），R²=0.28。

**正确做法: 每场次单独拟合，取中位数弹性。**

```python
def fit_within_match_elasticities(demand_data: pd.DataFrame) -> dict[str, ElasticityResult]:
    """每场次单独拟合恒定弹性 → 取中位数 ε
    
    思路：同一场比赛内，6个价格档位天然形成需求曲线。
    因为同一场比赛的所有档位面对相同的对手/天气/赛程，
    价量关系更干净。
    """
    results: dict[str, ElasticityResult] = {}
    
    for tier in ["A", "B"]:
        tier_data = demand_data[demand_data["match_tier"] == tier]
        elasticities = []
        base_demands = []
        r2s = []
        
        for match_id in tier_data["match_id"].unique():
            match_data = tier_data[tier_data["match_id"] == match_id]
            if len(match_data) >= 4:  # 至少4个价格点
                result = fit_constant_elasticity(match_data)
                elasticities.append(result.elasticity)
                base_demands.append(result.base_demand)
                r2s.append(result.r_squared)
        
        if elasticities:
            median_eps = float(np.median(elasticities))
            median_r2 = float(np.median(r2s))
            # 基准价格用该级别实际中间档位价（不是数据中位数）
            base_price = 440 if tier == "A" else 300  # A级¥440 / B级¥300 = 中档
            # 基准需求：用中位数弹性反推到基准价格下的需求
            median_bd = float(np.median(base_demands))
            
            results[tier] = ElasticityResult(
                elasticity=median_eps,
                base_demand=median_bd,
                base_price=base_price,
                r_squared=median_r2,
            )
    
    return results
```

替换 `fit_by_match_tier()` 为 `fit_within_match_elasticities()`。同时更新 `cli.py` 中的 import。

**验证:** 跑完后 ε 应该在 -1.5 到 -3.0 之间，R² 应该 > 0.7。

---

## 🔴 问题2: base_price 取数据中位数，不是真实档位价

**文件:** `src/elasticity.py` — `fit_constant_elasticity()` 第41行

```python
base_price = float(np.median(prices))  # ← 当前：A级数据中位数=¥510（不是真实档位）
```

A级真实档位: ¥260, ¥340, ¥440, ¥580, ¥780, ¥1380。中档是 ¥440 或 ¥510（平均）。

**修复:** 改 `fit_constant_elasticity` 签名，允许传入 `base_price` 参数：

```python
def fit_constant_elasticity(data: pd.DataFrame, base_price: float | None = None) -> ElasticityResult:
    ...
    if base_price is None:
        base_price = float(np.median(prices))
```

然后在 `fit_within_match_elasticities` 中传入正确的基准价。

---

## 🔴 问题3: 优化只做单价格点，但实际有6个档位

**文件:** `src/optimize.py` — `optimize_single_price()`

当前优化器假设全场上座率由单一价格决定。实际上国安有6个独立定价档位（vip/tier5/tier4/tier3/tier2/tier1），每个档位的弹性不同，需要联合优化。

**修复: 新增多档位联合优化函数：**

```python
@dataclass
class MultiTierPricingResult:
    optimal_prices: dict[str, float]     # 档位→最优价
    predicted_demand: dict[str, float]   # 档位→预测需求
    tier_revenue: dict[str, float]       # 档位→收入
    total_revenue: float
    total_attendance: float
    attendance_rate: float
    objective_value: float


def optimize_multi_tier(
    models: dict[str, ElasticityResult],   # 档位→弹性模型
    capacities: dict[str, int],            # 档位→容量
    demand_multiplier: float = 1.0,
    revenue_weight: float = 0.6,
    price_floor_pct: float = 0.6,
    price_ceiling_pct: float = 2.5,
) -> MultiTierPricingResult:
    """联合优化6个档位的价格向量
    
    max  ω·Σ(P_i × Q_i) + (1-ω)·(ΣQ_i / ΣCap_i) × baseline_rev
    
    其中 Q_i = D_i × (P_i/P0_i)^ε_i × M
    """
    tiers = list(models.keys())
    n = len(tiers)
    
    x0 = np.array([models[t].base_price for t in tiers])
    bounds = [
        (models[t].base_price * price_floor_pct, 
         models[t].base_price * price_ceiling_pct)
        for t in tiers
    ]
    
    total_capacity = sum(capacities.values())
    baseline_rev = sum(models[t].base_price * models[t].base_demand for t in tiers)
    
    def objective(prices):
        total_rev = 0.0
        total_demand = 0.0
        for i, t in enumerate(tiers):
            p = float(prices[i])
            q = min(models[t].predict(p) * demand_multiplier, capacities[t])
            total_rev += p * q
            total_demand += q
        
        att_rate = total_demand / total_capacity
        rev_score = total_rev / 1_000_000
        att_score = att_rate * baseline_rev / 1_000_000
        return -(revenue_weight * rev_score + (1 - revenue_weight) * att_score)
    
    result = minimize(objective, x0, bounds=bounds, method="L-BFGS-B")
    
    # ... 构建返回结果
```

---

## 🟡 问题4 (次要): cli.py 输出不对板

**文件:** `src/cli.py`

当前 CLI 调用 `optimize_single_price` 输出单价格点，但用户期望的是6档位定价表。

改成调用 `optimize_multi_tier`，输出表格式：

```
=====================================
  北京国安 vs 上海申花  —  定价建议
  比赛级别: A | 需求乘数: 1.708×
=====================================
档位      基准价    建议价    变化     预测需求    档位收入
─────────────────────────────────────────────────────
vip      ¥1,380   ¥1,656   +20%      1,020    ¥1,689,120
tier5    ¥  780   ¥  936   +20%      4,200    ¥3,931,200
tier4    ¥  580   ¥  638   +10%      5,500    ¥3,509,000
tier3    ¥  440   ¥  440     0%     13,800    ¥6,072,000
tier2    ¥  340   ¥  340     0%      8,500    ¥2,890,000
tier1    ¥  260   ¥  234   -10%      9,200    ¥2,152,800
─────────────────────────────────────────────────────
合计                                    42,220   ¥20,244,120

📊 预计上座率: 99% (42,220/42,800)
💰 预计收入: ¥20,244,120
```

---

## 执行顺序

1. 改 `elasticity.py`：新增 `fit_within_match_elasticities()`，替换旧函数
2. 改 `elasticity.py`：`fit_constant_elasticity` 支持外部 base_price
3. 改 `optimize.py`：新增 `optimize_multi_tier()`
4. 改 `cli.py`：调用新函数，输出多档位表
5. 更新测试
6. 跑 `pytest tests/ -v` 确认全过
7. 跑 `python src/cli.py --opponent "上海申花"` 验证输出合理

**验证标准：**
- ε 在 -1.5 到 -3.0 之间
- R² > 0.5
- vs申花 上座率 > 80%
- 不要所有档位都推到天花板或地板
