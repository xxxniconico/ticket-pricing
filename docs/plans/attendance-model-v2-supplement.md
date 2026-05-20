# 补充: 比赛日类型 + 双赛周 → 加入 attendance-model-v2

> 加到 `docs/plans/attendance-model-v2.md` 的特征列表和回归中。

---

## 新增特征

在 `build_attendance_model_v2` 的特征矩阵中增加：

### 1. `day_of_week` (0-6, 周一=0)
替换二值 `is_weekend`。

| 值 | 含义 | 预期影响 |
|----|------|---------|
| 5-6 | 周五/周六 | 正向（休息日前夜+休息日） |
| 4 | 周五 vs... 其实周五晚上也是工作日白天 | 中性偏正 |
| 0-3 | 周一-周四 | 负向（工作日） |

### 2. `days_since_last_home` (天数)
距离上一个主场比赛的天数。>7天=充分间隔，3-4天=双赛周紧缩。

预期：间隔越短 → 上座越低。

### 3. `is_double_matchweek` (0/1)
本轮前后4天内是否有另一场国安比赛（主或客）。

预期：双赛周 → 分流 → 上座降低。

---

## 修改代码

在 `build_attendance_model_v2` 中，替换特征构建部分：

```python
# === 新增: 比赛日类型 ===
match_date = pd.Timestamp(date_str)
day_of_week = match_date.weekday()  # 0=Mon, 6=Sun

# === 新增: 距上一主场天数 ===
home_matches_before = all_matches[
    (all_matches["venue"] == "H") & (all_matches["round"] < rnd)
]
if not home_matches_before.empty:
    last_home_date = pd.Timestamp(home_matches_before.iloc[-1]["date"])
    days_since_last = (match_date - last_home_date).days
else:
    days_since_last = 14  # 赛季首个主场默认2周间隔

# === 新增: 是否双赛周 ===
nearby_matches = all_matches[
    (all_matches["round"] != rnd)
]
nearby_dates = pd.to_datetime(nearby_matches["date"])
days_diff = abs((nearby_dates - match_date).dt.days)
is_double = int((days_diff <= 4).any())

# 特征矩阵
rows.append({
    ...
    "day_of_week": day_of_week,
    "days_since_last": days_since_last,
    "is_double": is_double,
    "recent_form": recent_form,
    "lost_to_bottom": lost_to_bottom,
    "opp_rank": opp_rank,
    "derby": is_derby,
})
```

回归特征向量:
```python
X = df[["recent_form", "lost_to_bottom", "opp_rank", "derby", 
        "day_of_week", "days_since_last", "is_double"]]
```

`predict_attendance_v2` 新增参数:
```python
def predict_attendance_v2(
    recent_form_5: float,
    lost_to_bottom_recent: bool,
    opponent_rank: int,
    is_derby: bool = False,
    day_of_week: int = 5,          # 新增
    days_since_last_home: int = 7, # 新增
    is_double_matchweek: bool = False,  # 新增
    model: dict | None = None,
    max_capacity: int = 27500,
) -> float:
```

---

## 2026看板集成

```python
# 从 schedule 数据计算
next_match_date = pd.Timestamp(next_match["date"]) if next_match else pd.Timestamp.now()
day_of_week = next_match_date.weekday()

# 距上一个已赛主场天数
completed_home = schedule[(schedule["venue"].str.upper().isin(["H","HOME"])) 
                          & (schedule["result"].notna()) & (schedule["result"] != "")]
if not completed_home.empty:
    last_home_date = pd.Timestamp(completed_home["date"].iloc[-1])
    days_since = (next_match_date - last_home_date).days
else:
    days_since = 14

# 双赛周判断
nearby = schedule[schedule["date"].notna()]
nearby_dates = pd.to_datetime(nearby["date"])
is_double = (abs((nearby_dates - next_match_date).dt.days) <= 4).sum() > 1

predicted_base = predict_attendance_v2(
    recent_form_5=compute_home_form(schedule),
    lost_to_bottom_recent=False,  # 2026暂缺
    opponent_rank=opponent_standing,
    is_derby=(opponent in {"上海申花","天津津门虎","山东泰山"}),
    day_of_week=day_of_week,
    days_since_last_home=days_since,
    is_double_matchweek=is_double,
    model=att_model,
)
```

---

## 预期效果

| 场景 | 旧预测 | 新预测 |
|------|--------|--------|
| 周六单赛, form=0.8, vs中游 | ~20,000 | ~22,000 (+周末+单赛) |
| 周三双赛, form=0.5, vs中游 | ~15,000 | ~11,000 (-工作日-双赛) |
| 崩盘期, 周二, 双赛, vs海牛 | ~8,000 | ~5,000 (叠加所有负面) |
