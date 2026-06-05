# Tab2 数据准确性审计 + 策略卡片动态联动

你是票务数据和 Streamlit 专家。请对 `dashboard/app_v8.py` 的 Tab2 历史定价部分执行两项任务。

## 任务 1: 审计河南实际收入数据

用户反馈河南实际销售没有 ¥435 万，数据可能有问题。

### 1.1 追溯数据来源

在 `render_history_expanders()` 中，实际收入通过以下链路计算：

```python
zone_rev = _get_zone_actual_revenue(m)   # L727
total_actual_rev += actual_rev            # L738
```

`_get_zone_actual_revenue()` (约 L161-180) 从 parquet 读取 `实际支付价格` 列按档位求和。

### 1.2 检查清单

请在函数内部增加诊断输出（用 `st.markdown`），对每场比赛输出：
- parquet 中有多少条记录匹配该比赛
- 各档位实际售出票数和收入明细
- 总实际收入

**重要**: 不要在最终代码中保留诊断输出 — 诊断只是为了确认问题。

### 1.3 检查以下可能的问题

- `match_id` 匹配逻辑是否正确？（当前用 `str(md["match_date"].iloc[0]).startswith(m["date"])` 匹配）
- 河南的 match_date 在 parquet 中是否存在？
- `实际支付价格` 列在 parquet 中是否存在且不为 NaN？
- parquet 中河南的数据量是否明显少于其他比赛？
- 是否有 partial/bundle 过滤误杀了河南的数据？
- `_get_zone_actual_revenue` 中 zone_tier 映射（`get_zone_sections(year)`）对河南的比赛是否正确？

### 1.4 修复

找到根因后直接修复。如果是数据问题（parquet 缺失），在界面上显示明确提示而非虚假数据。

---

## 任务 2: 策略卡片与定价表格动态联动

### 问题

当前历史定价中：
- 策略卡片 `render_strategy_card(r_h, pred_args)` 展示的「优化效果」基于**场景 vs 基准价模型**（`r.total_revenue - r.base_revenue`）
- 下面的定价表格展示的优化效果基于**场景 vs 实际**（`rev_delta_vs_actual`）
- 两者数据源不同步，策略卡片的「优化效果」数字和表格 caption 的数字不一致

用户期望：策略卡片的数据应该反映**和表格一样的对比基准**（场景 vs 实际），而不是场景 vs 基准价模型。这样看到策略卡片就知道真实效果，看表格就知道细节。

### 修改方案

修改 `render_strategy_card()` 使其支持传入实际数据：

#### 2.1 新增可选参数

```python
def render_strategy_card(r, pred_args, actual_revenue=None, actual_attendance=None):
```

当 `actual_revenue` 和 `actual_attendance` 都不为 None 时，优化效果改为**场景 vs 实际**：

```python
if actual_revenue is not None and actual_attendance is not None:
    # 历史模式：场景 vs 实际
    qty_delta = r.total_attendance - actual_attendance
    rev_delta_eff = r.total_revenue - actual_revenue
else:
    # 预测模式：场景 vs 基准价模型（保持原有逻辑不变）
    qty_delta = r.total_attendance - r.base_attendance
    rev_delta_eff = r.total_revenue - r.base_revenue
```

#### 2.2 更新 Tab1 调用

Tab1 `render_strategy_card(r, pred_args)` — 不传实际数据，保持场景 vs 基准价模型（预测模式）✅ 不改变

#### 2.3 更新 Tab2 调用

```python
strat_label, rw = render_strategy_card(r_h, pred_args, 
    actual_revenue=total_actual_rev, 
    actual_attendance=total_actual_qty)
```

这样 Tab2 的策略卡片和下方表格的 caption 数据完全一致。

#### 2.4 删除冗余的 caption

Tab2 中 L839-845 的策略感知 caption 现在与策略卡片重复了：
- 策略卡片已经显示"优化效果（vs 实际）"
- caption 再次显示同样的信息

**方案**: 将 caption 简化为只显示基准价模型参考：

```python
base_label = "增收" if rev_delta_vs_base > 0 else "减收"
st.caption(
    f"实际收入 ¥{total_actual_rev/10000:.1f}万 · 实际上座 {total_actual_qty:,}张"
    f" | 基准价模型 ¥{r_h.base_revenue/10000:.1f}万（{base_label}¥{abs(rev_delta_vs_base)/10000:.1f}万）"
    f" | 情景推演未经验证",
    unsafe_allow_html=True
)
```

但是保留 bad_tradeoff 检测和河南审计卡片（它们仍然有价值）。

---

## 验证

```bash
python3 -c "import py_compile; py_compile.compile('dashboard/app_v8.py', doraise=True)" && echo "OK"
```

## 约束

- 不要改变 Tab1 的行为 — 预测模式保持不变
- 策略卡片中「预期效果」行（L400-403）保持场景 vs 基准价模型（这个语义在预测模式下是正确的）
- 「优化效果」行（L405-419）改为根据是否传入 actual 数据切换基准
- 河南审计卡片保持独立

直接修改文件，每完成一项修改就验证编译。
