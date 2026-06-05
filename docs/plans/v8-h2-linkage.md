# H2策略 × 下一场预测联动

## 目标
在 H2策略 Tab 中，用户可以从8场未来比赛中**任意选中一场**，页面上即时显示该场的完整预测（规则链、定价表、What-If），和"下一场预测" Tab 体验一致。

## 实现方式

### 1. 用 st.selectbox 选比赛
在策略表上方添加下拉选择器：
```python
match_dates = [f"{m['date']} vs {m['opponent']}" for m in matches]
selected = st.selectbox("选择场次查看详细预测", match_dates)
```

### 2. 复用 Tab 1 的预测逻辑
选中某个场次后，调用与 `render_tab1` 相同的预测流程：
- `detect_ctx()` 获取上下文
- `rule_predict()` 计算预测
- `optimizer.optimize()` 优化定价
- 复用已有的 `render_rule_pills()`, `render_cumulative_bar()`, `render_confidence_bar()`, `render_strategy_card()`, `render_pricing_table()`, `render_what_if()`

### 3. 需要解决的问题
- `guoan_matches` 需要包含被选中的未来场次（当前 guoan_matches 已有未来场次，没问题的）
- detect_ctx 需要 standings dict（已有）
- `render_tab1` 函数内部耦合了"近期赛果"，需要提取一个独立的 `render_prediction_detail(match, guoan_matches, standings, mae)` 函数

### 4. 重构建议
将 `render_tab1` 中的预测渲染部分提取为独立函数：
```python
def render_prediction_detail(match, guoan_matches, standings, mae):
    """渲染单个场次的完整预测：规则链+置信+策略+定价+What-If"""
    opp = match["opponent"]
    dt = pd.Timestamp(match["date"])
    # ... 规则链、累计条、置信区间、策略卡片、定价表、What-If
```

然后：
- `render_tab1` 调用 `render_prediction_detail`
- H2 Tab 也调用 `render_prediction_detail`

## 改动范围
- `app_v8.py`：提取 `render_prediction_detail`，修改 `render_tab1` 调用它
- H2 Tab：添加 selectbox + `render_prediction_detail` 调用
- 其他文件不变
