# 模型修复 — 上座率预测改为直接回归

> 问题: multiplier 系统量程 0.59-1.64，实际需求波动 0.29-0.87（相对同级均值）。
> 根因: base_demand 用场均销量，场均已混合强弱，乘数拉不开。
> 修复: 用15场数据直接训练线性回归预测上座率，替代 multiplier。

---

## 修改: `src/calibrate.py` — 新增上座率预测函数

追加到文件末尾：

```python
def build_attendance_model(data_dir: str = "data/raw") -> dict:
    """用2025数据训练上座率直接预测模型
    
    方法: 对数线性回归
    ln(attendance) = w0 + w1*rank + w2*form + w3*weekend + w4*derby + w5*half
    
    Returns: {"intercept": float, "rank_coef": float, "form_coef": float, ...}
    """
    from src.data_feeds import fetch_guoan_2025_home, get_opponent_rank_2025, compute_home_form_2025
    from src.ingest import load_all
    from src.classify import DERBY_RIVALS
    
    demand = load_all(data_dir)
    home = fetch_guoan_2025_home()
    
    # 每场实际散票
    rows = []
    for _, match in home.iterrows():
        opp = str(match["opponent"]).strip()
        date = str(match.get("date", ""))
        rnd = int(match["round_num"])
        
        # 实际散票
        m = demand[demand["match_id"].str.contains(date[:10])]
        if m.empty:
            continue
        actual = m["quantity"].sum()
        
        rank = get_opponent_rank_2025(opp)
        form = compute_home_form_2025(up_to_round=rnd)
        is_weekend = 1 if pd.Timestamp(date).weekday() >= 5 else 0
        is_derby = 1 if opp in DERBY_RIVALS else 0
        is_second_half = 1 if rnd > 15 else 0
        
        rows.append({
            "opponent": opp, "actual": actual,
            "rank": rank, "form": form,
            "weekend": is_weekend, "derby": is_derby,
            "second_half": is_second_half,
        })
    
    df = pd.DataFrame(rows)
    if len(df) < 5:
        return {"intercept": 10.0, "rank_coef": -0.02, "form_coef": 0.5,
                "weekend_coef": 0.05, "derby_coef": 0.2, "second_half_coef": -0.1, "r_squared": 0}
    
    y = np.log(df["actual"])
    X = df[["rank", "form", "weekend", "derby", "second_half"]]
    X_with_c = np.column_stack([np.ones(len(X)), X.values])
    w = np.linalg.lstsq(X_with_c, y, rcond=None)[0]
    
    y_hat = X_with_c @ w
    r2 = 1 - np.sum((y - y_hat)**2) / np.sum((y - y.mean())**2)
    
    return {
        "intercept": float(w[0]),
        "rank_coef": float(w[1]),
        "form_coef": float(w[2]),
        "weekend_coef": float(w[3]),
        "derby_coef": float(w[4]),
        "second_half_coef": float(w[5]),
        "r_squared": float(r2),
    }


def predict_attendance(
    opponent_rank: int,
    home_form: float,
    is_weekend: bool = True,
    is_derby: bool = False,
    is_second_half: bool = False,
    model: dict | None = None,
    max_capacity: int = 27500,
) -> float:
    """直接预测上座人数
    
    Args:
        model: build_attendance_model() 的输出
    """
    if model is None:
        model = build_attendance_model()
    
    log_att = model["intercept"]
    log_att += model.get("rank_coef", 0) * opponent_rank
    log_att += model.get("form_coef", 0) * home_form
    log_att += model.get("weekend_coef", 0) * (1 if is_weekend else 0)
    log_att += model.get("derby_coef", 0) * (1 if is_derby else 0)
    log_att += model.get("second_half_coef", 0) * (1 if is_second_half else 0)
    
    return min(np.exp(log_att), max_capacity)
```

---

## 修改: `dashboard/app.py` — Tab1 用直接预测替代 multiplier

### 1. 新增 import
```python
from src.calibrate import build_attendance_model, predict_attendance
```

### 2. 替换分类逻辑
删除 Tab1 中 `classify_match_hybrid` 调用，改为直接预测：

```python
att_model = build_attendance_model(DATA_DIR)

# 判断德比
is_derby = opponent in {"上海申花", "天津津门虎", "山东泰山"}

# 直接预测基准上座率
predicted_base = predict_attendance(
    opponent_rank=opponent_standing,
    home_form=home_form,
    is_weekend=is_weekend,
    is_derby=is_derby,
    is_second_half=(season_stage != "mid"),
    model=att_model,
)

# 基准上座率 ÷ 场均总需求 = 替代原来的 multiplier
avg_total_demand = demand_df.groupby("match_id")["quantity"].sum().mean()
demand_mult = predicted_base / avg_total_demand if avg_total_demand > 0 else 1.0

# KPI 显示
st.metric("预测基准上座", f"{predicted_base:,.0f}人", f"乘数 {demand_mult:.3f}×")
```

### 3. 原因区显示回归系数
```python
st.markdown(f"**上座率预测模型** (R²={att_model.get('r_squared',0):.3f})")
st.markdown(f"""
| 因子 | 系数 |
|------|------|
| 基准 | {att_model.get('intercept',0):.2f} |
| 排名 | {att_model.get('rank_coef',0):+.3f} /名 |
| 胜率 | {att_model.get('form_coef',0):+.3f} |
| 周末 | {att_model.get('weekend_coef',0):+.3f} |
| 德比 | {att_model.get('derby_coef',0):+.3f} |
| 下半程 | {att_model.get('second_half_coef',0):+.3f} |
""")
```

---

## 修改: Tab2 回测用直接预测

```python
# 在 run_backtest 中，用 predict_attendance 替代 classify_match_hybrid
att_model = build_attendance_model(DATA_DIR)
predicted_base = predict_attendance(
    opponent_rank=get_opponent_rank_2025(opp),
    home_form=compute_home_form_2025(),
    model=att_model,
)
demand_mult = predicted_base / avg_total
```

---

## 验证

```bash
python -c "
from src.calibrate import build_attendance_model, predict_attendance
m = build_attendance_model()
print(f'R²={m[\"r_squared\"]:.3f}')
print(f'海牛(rank14): {predict_attendance(14, 0.6, model=m):.0f}')
print(f'申花(derby):  {predict_attendance(2, 0.6, is_derby=True, model=m):.0f}')
"
# 海牛应≈8000，申花应≈24000
```
