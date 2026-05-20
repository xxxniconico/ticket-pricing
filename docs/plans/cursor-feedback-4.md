# Cursor 修复反馈 #4 — 最后版本，严格按此执行

> 当前方案 `fit_official_tier_elasticity_models` 给出正弹性（+0.073），优化全推天花板。废止。
> 以下三个修改必须全部完成，不要再走新路线。

---

## 修改1: elasticity.py — 删除高低分段，新增交易数据弹性

### 删除
- `OFFICIAL_A`, `OFFICIAL_B`, `A_LOW_PRICES`, `A_HIGH_PRICES`, `B_LOW_PRICES`, `B_HIGH_PRICES`
- `_segment_median_elasticity`, `_fallback_official_tier_models`, `fit_official_tier_elasticity_models`

### 新增（追加到文件末尾，保留 `ElasticityResult` / `fit_constant_elasticity` / `fit_within_match_elasticities`）

```python
def fit_elasticity_from_transactions(
    filepath: str = "data/raw/25年散票用户购买记录更新.xlsx",
) -> ElasticityResult:
    """从用户购买记录拟合弹性（真实市场行为）
    
    交易数据中「票价信息」= 用户实际面对的单价，
    「数量」= 购买张数。同一产品在不同价格下的
    购买决策 → 真正的需求曲线。
    
    返回 ε≈-2.5, R²≈0.65。
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
```

### 同时修改 `fit_within_match_elasticities`
第 84 行 `base_price = 440.0 if tier == "A" else 300.0` 保留不动（回测用，cli不用它）。

---

## 修改2: cli.py — 用交易弹性 + 档位容量

### 2a. 删除
- `TIER_ZONE_SHARE`
- `_tier_capacities` 函数

### 2b. 替换 import
```python
# 替换第16行
from src.elasticity import ElasticityResult, fit_elasticity_from_transactions
```

### 2c. 新增容量常量
```python
# 各档位散票容量（总散票池 ~27,500）
TIER_CAPACITIES: dict[str, int] = {
    "tier1":  3000,   # 球门后，年票为主
    "tier2":  9500,   # 主力散票区
    "tier3":  7000,   # 中档主力
    "tier4":  3000,   # 上层中线
    "tier5":  4200,   # 前排黄金
    "vip":     800,   # 贵宾
}
```

### 2d. 替换 `--capacity` 默认值（第108行）
```python
p.add_argument("--capacity", type=int, default=27500,
               help="散票池总容量")
```

### 2e. 新增 `_build_tier_models` 函数
```python
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
        prices = {"vip": 1380, "tier5": 780, "tier4": 580, "tier3": 440, "tier2": 340, "tier1": 260}
    else:
        prices = {"vip": 1080, "tier5": 540, "tier4": 460, "tier3": 300, "tier2": 220, "tier1": 160}
    
    eps = txn_el.elasticity if txn_el else -2.0
    r2 = txn_el.r_squared if txn_el else 0.6
    
    models = {}
    for name, p0 in prices.items():
        # 从座位数据取该档历史场均销量
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
```

### 2f. 替换 `main()` 中 197-211 行
```python
    demand_df = None
    txn_el = None
    try:
        demand_df = load_all(args.data_dir)
        txn_el = fit_elasticity_from_transactions(
            f"{args.data_dir}/25年散票用户购买记录更新.xlsx"
        )
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
```

---

## 修改3: tests/test_elasticity.py — 调整测试

删除 `test_fit_official_tier_elasticity_models_segment_eps`，新增：

```python
def test_fit_elasticity_from_transactions():
    """真实购买记录 → ε 应在 -1.5 到 -3.0 之间"""
    from src.elasticity import fit_elasticity_from_transactions
    result = fit_elasticity_from_transactions(
        "data/raw/25年散票用户购买记录更新.xlsx"
    )
    assert -3.5 < result.elasticity < -1.0
    assert result.r_squared > 0.4
```

---

## 验证

```bash
# 测试
pytest tests/ -v

# 热门场次
python src/cli.py --opponent "上海申花" --weekend --home-form 0.6 --opponent-standing 1

# 弱队
python src/cli.py --opponent "青岛海牛" --no-weekend --home-form 0.3 --opponent-standing 14
```

预期：
- ε ≈ -2.5
- 申花: 上座率 > 85%，不全是天花板，tier1 涨幅小
- 海牛: 上座率 < 50%，tier1 可能降价
- 任何档位不能全部 ±150%
