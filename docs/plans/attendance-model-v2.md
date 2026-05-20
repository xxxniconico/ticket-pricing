# 模型修复 v2 — 滚动战绩驱动的上座率预测

> 放弃"下半程"二值变量。用滚动5场全赛事战绩 + 近期是否输保级队 + 争冠距离，
> 捕获「连败→信心崩塌→票房跳水」的链式效应。

---

## 方案对比

| | multiplier系统(旧) | 简单回归(v1) | 滚动战绩回归(v2) |
|---|---|---|---|
| 基准 | 场均销量(含强弱混合) | 对数线性回归 | 对数线性回归 |
| 特征 | 对手品牌×情境因子积 | rank/form/weekend/derby | **滚动5场胜率 + 近期输保级 + 争冠距离** |
| 15场够吗 | — | 边界(5特征) | 好(3个核心特征) |
| 捕获连败 | ❌ | ❌ | ✅ 滚动胜率持续下降 |
| 捕获输保级队 | ❌ | ❌ | ✅ `lost_to_bottom_recent` |

**优点**: 捕获「输申花→输成都→输海港」的连败链，比"下半程"精确得多。
**缺点**: 仍然只有15场——但用3个特征比5个更稳。2026年有新数据后持续改进。

---

## 修改: `src/calibrate.py` — 新增滚动战绩预测

追加到文件末尾：

```python
def build_attendance_model_v2(data_dir: str = "data/raw") -> dict:
    """用滚动战绩预测上座率（捕获连败链效应）
    
    特征:
    - recent_form_5: 本场之前5场全赛事胜率 (0-1)
    - lost_to_bottom_recent: 近3场是否输给排名≥12的队 (0/1)
    - opponent_rank: 对手排名 (1-16)
    - is_derby: 德比 (0/1)
    - is_weekend: 周末 (0/1)
    
    Returns: {feature_name: coefficient, r_squared: float}
    """
    from src.data_feeds import fetch_guoan_2025_all, get_opponent_rank_2025
    from src.ingest import load_all
    from src.classify import DERBY_RIVALS
    
    demand = load_all(data_dir)
    all_matches = fetch_guoan_2025_all()
    
    rows = []
    for _, match in all_matches.iterrows():
        opp = str(match["opponent"]).strip()
        rnd = int(match["round"])
        venue = str(match["venue"]).strip().upper()
        date_str = str(match.get("date", ""))
        
        # 只统计主场上座率
        if venue != "H":
            continue
        
        # 实际散票
        m = demand[demand["match_id"].str.contains(date_str[:10])]
        if m.empty:
            continue
        actual = float(m["quantity"].sum())
        
        # 滚动5场全赛事胜率（本场之前）
        prev = all_matches[(all_matches["round"] < rnd)].tail(5)
        recent_form = float((prev["result"] == "W").sum() / len(prev)) if len(prev) > 0 else 0.5
        
        # 近3场是否输给保级队（排名≥12）
        prev3 = all_matches[(all_matches["round"] < rnd)].tail(3)
        lost_to_bottom = 0
        for _, pm in prev3.iterrows():
            if pm["result"] == "L":
                prank = get_opponent_rank_2025(str(pm["opponent"]))
                if prank >= 12:
                    lost_to_bottom = 1
                    break
        
        opp_rank = get_opponent_rank_2025(opp)
        is_derby = 1 if opp in DERBY_RIVALS else 0
        is_weekend = 1 if pd.Timestamp(date_str).weekday() >= 5 else 0
        
        rows.append({
            "opponent": opp, "round": rnd, "actual": actual,
            "recent_form": recent_form,
            "lost_to_bottom": lost_to_bottom,
            "opp_rank": opp_rank,
            "derby": is_derby,
            "weekend": is_weekend,
        })
    
    df = pd.DataFrame(rows)
    if len(df) < 5:
        return {"intercept": 10.0, "form_coef": 1.5, "lost_bottom_coef": -0.5,
                "rank_coef": -0.03, "derby_coef": 0.2, "weekend_coef": 0.05, "r_squared": 0}
    
    y = np.log(df["actual"])
    X = df[["recent_form", "lost_to_bottom", "opp_rank", "derby", "weekend"]]
    X_with_c = np.column_stack([np.ones(len(X)), X.values])
    w = np.linalg.lstsq(X_with_c, y, rcond=None)[0]
    
    y_hat = X_with_c @ w
    r2 = 1 - np.sum((y - y_hat)**2) / np.sum((y - y.mean())**2)
    
    return {
        "intercept": float(w[0]),
        "form_coef": float(w[1]),       # 滚动胜率每+0.1 → e^(coef*0.1)倍上座
        "lost_bottom_coef": float(w[2]), # 输保级队 → e^coef 倍
        "rank_coef": float(w[3]),        # 对手排名每+1 → e^coef 倍
        "derby_coef": float(w[4]),       # 德比加成
        "weekend_coef": float(w[5]),     # 周末加成
        "r_squared": float(r2),
        "n_samples": len(df),
    }


def predict_attendance_v2(
    recent_form_5: float,
    lost_to_bottom_recent: bool,
    opponent_rank: int,
    is_derby: bool = False,
    is_weekend: bool = True,
    model: dict | None = None,
    max_capacity: int = 27500,
) -> float:
    """用滚动战绩模型预测上座人数"""
    if model is None:
        model = build_attendance_model_v2()
    
    log_att = model["intercept"]
    log_att += model.get("form_coef", 0) * recent_form_5
    log_att += model.get("lost_bottom_coef", 0) * (1 if lost_to_bottom_recent else 0)
    log_att += model.get("rank_coef", 0) * opponent_rank
    log_att += model.get("derby_coef", 0) * (1 if is_derby else 0)
    log_att += model.get("weekend_coef", 0) * (1 if is_weekend else 0)
    
    return min(np.exp(log_att), max_capacity)
```

---

## 看板集成

Tab1 替换为:
```python
att_model = build_attendance_model_v2(DATA_DIR)

# 2026 国安滚动战绩（从 schedule 数据取）
recent_5 = compute_home_form(schedule)  # 已有函数

# 近期是否输保级队（2026数据暂缺 → 默认 False）
lost_bottom = False  # TODO: 从2026赛程数据计算

predicted_base = predict_attendance_v2(
    recent_form_5=recent_5,
    lost_to_bottom_recent=lost_bottom,
    opponent_rank=opponent_standing,
    is_derby=(opponent in {"上海申花","天津津门虎","山东泰山"}),
    is_weekend=is_weekend,
    model=att_model,
)
```

Tab2 回测替换为:
```python
# 滚动战绩从30轮全数据实时计算
all25 = fetch_guoan_2025_all()
prev = all25[all25["round"] < rnd].tail(5)
recent_form = (prev["result"] == "W").sum() / len(prev) if len(prev) > 0 else 0.5

predicted_base = predict_attendance_v2(
    recent_form_5=recent_form,
    lost_to_bottom_recent=lost_bottom,
    opponent_rank=get_opponent_rank_2025(opp),
    ...
)
```

---

## 验证

```bash
python -c "
from src.calibrate import build_attendance_model_v2, predict_attendance_v2
m = build_attendance_model_v2()
print(f'R²={m[\"r_squared\"]:.3f} (n={m[\"n_samples\"]})')
# 上半程强势期: form=0.8, 没输保级队, vs中游
print(f'上半程vs中游: {predict_attendance_v2(0.8, False, 8, model=m):.0f}')
# 崩盘期: form=0.2, 刚输保级队, vs中游
print(f'崩盘期vs中游: {predict_attendance_v2(0.2, True, 8, model=m):.0f}')
# 海牛(rank14)
print(f'崩盘vs海牛:   {predict_attendance_v2(0.2, True, 14, model=m):.0f}')
"
```
