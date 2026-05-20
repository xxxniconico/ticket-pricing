# Cursor 修复反馈 #2 — 改用交易数据弹性

> 同场跨档位数据测的是档位品质梯度，不是价格弹性。ε≈-0.6 导致优化全推天花板。
> 交易数据（25年散票用户购买记录更新.xlsx）有真正的价格-购买量信号：ε=-2.478, R²=0.646。

---

## 修改1: elasticity.py — 新增交易数据弹性函数

```python
def fit_from_transactions(
    user_filepath: str = "data/raw/25年散票用户购买记录更新.xlsx",
) -> ElasticityResult:
    """从用户购买记录拟合弹性（真实市场行为，非跨档位推断）
    
    交易数据中「票价信息」= 用户实际面对的单价，「数量」= 购买张数。
    同一产品在不同价格下的购买决策 → 真正的需求曲线。
    """
    from src.ingest import load_user_purchases
    
    df = load_user_purchases(user_filepath)
    df = df.dropna(subset=["unit_price", "qty_clean"])
    
    # 按价格聚合总购买量
    agg = (
        df.groupby("unit_price")["qty_clean"]
        .sum()
        .reset_index()
        .rename(columns={"unit_price": "price", "qty_clean": "quantity"})
    )
    
    return fit_constant_elasticity(agg, base_price=None)
```

验证: ε 应在 -1.5 到 -3.0 之间，R² > 0.5。

---

## 修改2: cli.py — 改用交易弹性

当前 `_build_tier_models` 用 `tier_elasticity.elasticity`（来自 fit_within_match_elasticities），值约 -0.6。

改成使用 `fit_from_transactions()` 的 ε = -2.478。

```python
# cli.py main() 中，替换这一段：
from src.elasticity import fit_from_transactions

# ...

try:
    demand_df = load_all(args.data_dir)
    txn_el = fit_from_transactions(
        f"{args.data_dir}/25年散票用户购买记录更新.xlsx"
    )
except (OSError, FileNotFoundError, ValueError, KeyError):
    txn_el = None

# 传给 _build_tier_models 时用 txn_el 而不是 tier_el
models = _build_tier_models(demand_df, tier, txn_el)
```

`_build_tier_models` 不需要改签名——它已经接受 `ElasticityResult | None`，取 `.elasticity` 即可。

---

## 修改3: cli.py — 容量默认值对齐真实散票池

当前 `--capacity` 默认 40000，但实际散票池 = 工体 68000 - 年票 25000 = 43000。

```python
p.add_argument("--capacity", type=int, default=43000, ...)
```

---

## 验证标准

```bash
python src/cli.py --opponent "上海申花" --weekend --home-form 0.6 --opponent-standing 1
```

预期:
- ε ≈ -2.5
- 上座率 > 70%（申花热门场次不应只有 35%）
- 不所有档位推天花板
- 高档位 (vip/tier5) 涨价幅度 > 低档位 (tier1)

```bash
python src/cli.py --opponent "青岛海牛" --no-weekend --home-form 0.3 --opponent-standing 14
```

预期:
- 弱队上座率 < 60%
- tier1 可能接近地板价（需求弱，降价促上座）
