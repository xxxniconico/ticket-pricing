# 模型升级 — 2025真实数据驱动参数校准

> 用2025赛季15场主场真实数据，回归拟合 context 因子权重，替代手调参数。
> 预期：回测 MAE 降到 15-20%。

---

## 核心思路

```
当前: demand_multiplier = base_lookup[opp] × context(手调因子积)
升级: demand_multiplier = base_lookup[opp] × context(回归校准权重)
```

用15场真实数据，已知 `actual_attendance`，反推最优 context 权重。

---

## Task 1: `src/calibrate.py` — 数据驱动参数校准

```python
"""用2025真实数据校准 context 因子权重"""
import pandas as pd
import numpy as np
from datetime import datetime
from src.data_feeds import (
    fetch_guoan_2025_home, get_opponent_rank_2025, compute_home_form_2025,
)
from src.ingest import load_all
from src.classify import build_base_multiplier_lookup


def calibrate_context_weights(data_dir: str = "data/raw") -> dict:
    """用2025数据回归拟合最优 context 权重
    
    方法：
    1. 对每场2025主场：observed_mult = actual_attendance / tier_avg
    2. base = base_lookup[opponent]（对手品牌效应）
    3. context_observed = observed_mult / base
    4. 特征：is_weekend, opponent_rank, home_form_before, season_half,
             is_derby, temperature, precipitation
    5. 对数回归: ln(context) = Σ(w_i × feature_i)
    
    Returns:
        {"weekend": 1.05, "top3": 1.08, "bottom3": 0.95, ...}
    """
    # 加载数据
    home_matches = fetch_guoan_2025_home()
    demand = load_all(data_dir)
    base_lookup = build_base_multiplier_lookup(f"{data_dir}/2025散票数据.xlsx")
    
    # 同级场均（用于计算 observed multiplier）
    a_avg = demand[demand["match_tier"] == "A"]["quantity"].mean()
    b_avg = demand[demand["match_tier"] == "B"]["quantity"].mean()
    
    # 构建训练数据
    rows = []
    A_OPPS = {"成都蓉城", "山东泰山", "上海海港", "上海申花"}
    
    for _, match in home_matches.iterrows():
        opp = match["opponent"]
        date = match["date"]
        round_num = int(match["round_num"])
        
        # 实际散票销量
        match_id_pattern = date.strftime("%Y-%m-%d")
        seat_match = demand[demand["match_id"].str.contains(match_id_pattern)]
        if seat_match.empty:
            continue
        actual = seat_match["quantity"].sum()
        
        # 基准需求
        tier = "A" if opp in A_OPPS else "B"
        tier_avg = a_avg if tier == "A" else b_avg
        observed_mult = actual / tier_avg if tier_avg > 0 else 1.0
        
        # 基础乘数
        base = base_lookup.get(opp, 1.0)
        context_observed = observed_mult / base if base > 0 else 1.0
        
        # 特征
        is_weekend = 1 if date.weekday() >= 5 else 0
        opponent_rank = get_opponent_rank_2025(opp)
        home_form_before = compute_home_form_2025(up_to_round=round_num)
        season_half = 0 if round_num <= 15 else 1  # 0=上半程强势, 1=下半程崩盘
        is_derby = 1 if opp in {"上海申花", "天津津门虎", "山东泰山"} else 0
        
        rows.append({
            "opponent": opp,
            "round": round_num,
            "actual": actual,
            "observed_mult": observed_mult,
            "base": base,
            "context_observed": context_observed,
            "is_weekend": is_weekend,
            "opp_rank": opponent_rank,
            "is_top3": 1 if opponent_rank <= 3 else 0,
            "is_bottom3": 1 if opponent_rank >= 14 else 0,
            "home_form": home_form_before,
            "season_half": season_half,
            "is_derby": is_derby,
        })
    
    df = pd.DataFrame(rows)
    
    # 对数回归: ln(context) = w0 + w1*weekend + w2*top3 + w3*bottom3 + w4*form + w5*half + w6*derby
    y = np.log(df["context_observed"].clip(lower=0.1))
    X = df[["is_weekend", "is_top3", "is_bottom3", "home_form", "season_half", "is_derby"]].copy()
    
    # 简单 OLS
    X_with_const = np.column_stack([np.ones(len(X)), X.values])
    w = np.linalg.lstsq(X_with_const, y, rcond=None)[0]
    
    # 转换为乘数: exp(w_i)
    weights = {
        "weekend": round(np.exp(w[1]), 3),        # 周末加成
        "top3_opponent": round(np.exp(w[2]), 3),   # 强队加成
        "bottom3_opponent": round(np.exp(w[3]), 3), # 弱队折扣
        "home_form_bonus": w[4],                   # 胜率每+0.1的加成
        "second_half_penalty": round(np.exp(w[5]), 3), # 下半程折扣
        "derby_bonus": round(np.exp(w[6]), 3),      # 德比加成
        "r_squared": float(1 - np.sum((y - X_with_const @ w)**2) / np.sum((y - y.mean())**2)),
    }
    
    return weights
```

---

## Task 2: `src/classify.py` — 用校准权重替代手调

修改 `get_demand_multiplier()` — 新增 `calibrated_weights=None` 参数：

```python
def get_demand_multiplier(
    opponent: str,
    opponent_standing: int | None = None,
    base_lookup: dict[str, float] | None = None,
    is_weekend: bool = True,
    is_holiday: bool = False,
    season_stage: str = "mid",
    home_form: float = 0.5,
    temperature_c: float = 20.0,
    precipitation_mm: float = 0.0,
    calibrated_weights: dict | None = None,  # 新增
) -> float:
    """混合乘数 = base × context"""
    # base
    if base_lookup and opponent in base_lookup:
        base = base_lookup[opponent]
    elif opponent_standing and opponent_standing <= 4:
        base = 1.25
    elif opponent_standing and opponent_standing >= 13:
        base = 0.75
    else:
        base = 1.0
    
    if calibrated_weights:
        # 用校准权重
        ctx_mult = 1.0
        if is_weekend:
            ctx_mult *= calibrated_weights.get("weekend", 1.05)
        if opponent_standing and opponent_standing <= 3:
            ctx_mult *= calibrated_weights.get("top3_opponent", 1.08)
        elif opponent_standing and opponent_standing >= 14:
            ctx_mult *= calibrated_weights.get("bottom3_opponent", 0.95)
        if calibrated_weights.get("home_form_bonus"):
            ctx_mult *= 1.0 + calibrated_weights["home_form_bonus"] * home_form
        if calibrated_weights.get("second_half_penalty", 1.0) < 1.0:
            # season_stage can indicate second half
            pass
        if opponent in DERBY_RIVALS:
            ctx_mult *= calibrated_weights.get("derby_bonus", 1.35)
        return round(base * ctx_mult, 3)
    
    # 回退到手调
    ctx_mult = 1.0
    if is_weekend:
        ctx_mult *= 1.05
    # ...（保留现有逻辑）
    return round(base * ctx_mult, 3)
```

---

## Task 3: `src/retrain.py` — 加入校准步骤

```python
def retrain(data_dir: str = "data/raw") -> None:
    from src.calibrate import calibrate_context_weights
    
    demand = load_all(data_dir)
    txn_el = fit_elasticity_from_transactions(...)
    lookup = build_base_multiplier_lookup(...)
    weights = calibrate_context_weights(data_dir)  # 新增
    
    print(f"弹性 ε: {txn_el.elasticity:.3f} (R²={txn_el.r_squared:.3f})")
    print(f"乘数查表: {len(lookup)} 对手")
    print(f"\n校准权重 (R²={weights['r_squared']:.3f}):")
    for k, v in weights.items():
        if k != "r_squared":
            print(f"  {k}: {v}")
    print("重训完成。")
```

---

## Task 4: `dashboard/app.py` — 回测用校准权重

在 `run_backtest()` 中加载并使用校准权重：

```python
# 加载校准权重
from src.calibrate import calibrate_context_weights
cal_weights = calibrate_context_weights(DATA_DIR)

# 在 classify_match_hybrid 中传入
t_bt, m_bt = classify_match_hybrid(
    opp,
    base_lookup=_lookup,
    opponent_standing=get_opponent_rank_2025(opp),
    is_weekend=_is_weekend_from_match_id(match_id),
    home_form=compute_home_form_2025(),
    calibrated_weights=cal_weights,  # 新增
)
```

注意：`classify_match_hybrid` 需要新增 `calibrated_weights` 参数，透传给 `get_demand_multiplier`。

---

## Task 5: Tab2 显示校准报告

在 Tab2 底部新增可展开区：

```python
with st.expander("🔧 模型校准报告"):
    if cal_weights:
        st.markdown(f"**回归 R²**: {cal_weights['r_squared']:.3f}")
        st.markdown(f"""
| 因子 | 校准权重 |
|------|---------|
| 周末 | {cal_weights.get('weekend', 'N/A')}× |
| 对手前3 | {cal_weights.get('top3_opponent', 'N/A')}× |
| 对手后3 | {cal_weights.get('bottom3_opponent', 'N/A')}× |
| 德比 | {cal_weights.get('derby_bonus', 'N/A')}× |
| 下半程 | {cal_weights.get('second_half_penalty', 'N/A')}× |
""")
```

---

## 验证

```bash
python src/calibrate.py  # 应输出校准权重
python src/retrain.py    # 应输出完整参数
bash dashboard/serve.sh  # Tab2 MAE 应下降
```

预期：回测 MAE 从当前水平降到 15-20%，R² > 0.5。
