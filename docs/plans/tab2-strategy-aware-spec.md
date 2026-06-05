# Tab2 历史定价 — 策略感知优化效果 + 河南特检

你是票务定价系统的审计 + 实现专家。请修改 `dashboard/app_v8.py` 的 Tab2 历史定价部分。

## 背景

当前 Tab2 的优化效果只看收入维度，完全忽略了数量维度。用户指出：

1. **策略应该决定核心指标**：
   - 收入优先策略 → 核心目标是增收，数量是次要
   - 上座优先（降价抢用户）→ 核心目标是增量，收入是次要
   - 均衡 → 两者平等

2. **河南案例**：如果优化策略损失了 200 万收入，只换来少量用户增长，这是失败的 tradeoff —— 需要在 UI 上体现出来

## 需要修改的文件

`dashboard/app_v8.py`

## 具体修改

### 1. `render_strategy_card()` — 策略卡片增加「优化效果」行

当前 L380-407 的策略卡片只显示涨价/降价档位和预期效果。在策略卡片底部增加一行「优化效果」：

```python
# 在 L403 后面，st.markdown 之前
qty_delta = r.total_attendance - r.base_attendance
rev_delta = r.total_revenue - r.base_revenue

rw = r.revenue_weight
if rw >= 0.7:
    # 收入优先：收入为主指标
    main_metric = f'<span style="color:{"#ff6b6b" if rev_delta > 0 else "#51cf66"}">{"+" if rev_delta > 0 else ""}¥{rev_delta/10000:.1f}万</span>'
    sub_metric = f'上座 {"↑" if qty_delta > 0 else "↓"}{abs(qty_delta):,.0f}张'
elif rw <= 0.3:
    # 上座优先：数量为主指标
    main_metric = f'<span style="color:{"#ff6b6b" if qty_delta > 0 else "#51cf66"}">{"+" if qty_delta > 0 else ""}{qty_delta:,.0f}张</span>'
    sub_metric = f'收入 {"+" if rev_delta > 0 else ""}¥{rev_delta/10000:.1f}万'
else:
    # 均衡：两者并列
    main_metric = f'<span style="color:{"#ff6b6b" if rev_delta > 0 else "#51cf66"}">{"+" if rev_delta > 0 else ""}¥{rev_delta/10000:.1f}万</span> · <span style="color:{"#ff6b6b" if qty_delta > 0 else "#51cf66"}">{"+" if qty_delta > 0 else ""}{qty_delta:,.0f}张</span>'
    sub_metric = ''

lines.append(f'优化效果：{main_metric}{"（" + sub_metric + "）" if sub_metric else ""}')
```

### 2. Tab2 历史定价表格 — 增加数量对比 + 策略感知

修改 `render_history_expanders()` L724-776，增加以下功能：

#### 2a. 表格增加一列「场景量 Δ」

在表格中「场景量」列后面增加「Δ量」列，显示场景量 - 实际量：

```python
# 在 L744-745 之间插入
qty_delta_z = tr.predicted_qty - actual_z
qty_delta_color = "#ff6b6b" if qty_delta_z > 0 else "#51cf66" if qty_delta_z < 0 else "#8a8f98"
f'<td style="color:{qty_delta_color};font-family:JetBrains Mono,ui-monospace">{qty_delta_z:+,.0f}</td>'
```

表头也需要加一列「Δ量」。

#### 2b. 合计行增加数量对比

```python
qty_delta_total = r_h.total_attendance - total_actual_qty
qty_delta_color = "#ff6b6b" if qty_delta_total > 0 else "#51cf66"
# 在合计行中增加
f'<td style="color:{qty_delta_color};font-family:JetBrains Mono,ui-monospace">{qty_delta_total:+,.0f}</td>'
```

#### 2c. 策略感知的优化效果摘要

将 L770-775 的 caption 改为策略感知版本：

```python
# 计算两个维度的 delta
qty_delta_vs_actual = r_h.total_attendance - total_actual_qty
rev_delta_vs_actual = r_h.total_revenue - total_actual_rev
rev_delta_vs_base = r_h.total_revenue - r_h.base_revenue

rw = r_h.revenue_weight

# 核心指标（策略感知）
if rw >= 0.7:
    # 收入优先
    primary_color = "#ff6b6b" if rev_delta_vs_actual > 0 else "#51cf66"
    primary_sign = "+" if rev_delta_vs_actual > 0 else ""
    primary_text = f"<span style='color:{primary_color}'>{primary_sign}¥{rev_delta_vs_actual/10000:.1f}万</span>"
    secondary_text = f"上座 {qty_delta_vs_actual:+,.0f}张"
    goal_text = "目标：增收"
elif rw <= 0.3:
    # 上座优先
    primary_color = "#ff6b6b" if qty_delta_vs_actual > 0 else "#51cf66"
    primary_sign = "+" if qty_delta_vs_actual > 0 else ""
    primary_text = f"<span style='color:{primary_color}'>{primary_sign}{qty_delta_vs_actual:,.0f}张</span>"
    secondary_text = f"收入 {rev_delta_vs_actual/10000:+.1f}万"
    goal_text = "目标：增量"
else:
    # 均衡
    rev_color = "#ff6b6b" if rev_delta_vs_actual > 0 else "#51cf66"
    qty_color = "#ff6b6b" if qty_delta_vs_actual > 0 else "#51cf66"
    primary_text = f"<span style='color:{rev_color}'>¥{rev_delta_vs_actual/10000:+.1f}万</span> · <span style='color:{qty_color}'>{qty_delta_vs_actual:+,.0f}张</span>"
    secondary_text = ""
    goal_text = "目标：均衡"

# Bad tradeoff 检测
bad_tradeoff = False
bad_reason = ""
if rw >= 0.7 and rev_delta_vs_actual < -10000 and qty_delta_vs_actual < 500:
    # 收入优先但损失 >1万收入，只换来 <500 张增量 = bad tradeoff
    bad_tradeoff = True
    bad_reason = f"⚠️ 收入优先策略下损失 ¥{abs(rev_delta_vs_actual)/10000:.1f}万，仅增量 {qty_delta_vs_actual:+,.0f}张，tradeoff 不划算"
elif rw <= 0.3 and qty_delta_vs_actual < 0 and rev_delta_vs_actual < -5000:
    # 上座优先但量也没增、收入还掉了 = bad
    bad_tradeoff = True
    bad_reason = f"⚠️ 上座优先策略下未增量（{qty_delta_vs_actual:+,.0f}张），还损失 ¥{abs(rev_delta_vs_actual)/10000:.1f}万"

base_label = "增收" if rev_delta_vs_base > 0 else "减收"

if bad_tradeoff:
    st.markdown(f"""<div style="padding:6px 12px;margin:4px 0;background:rgba(255,107,107,0.08);border:1px solid rgba(255,107,107,0.2);border-radius:6px;font-size:0.72rem;color:#ff6b6b">
      {bad_reason}
    </div>""", unsafe_allow_html=True)

st.caption(
    f"{goal_text} | 优化效果 {primary_text}"
    f"{'（' + secondary_text + '）' if secondary_text else ''}"
    f" | 实际收入 ¥{total_actual_rev/10000:.1f}万 · 实际上座 {total_actual_qty:,}张"
    f" | 基准价模型 ¥{r_h.base_revenue/10000:.1f}万（{base_label}¥{abs(rev_delta_vs_base)/10000:.1f}万）",
    unsafe_allow_html=True
)
```

### 3. 河南特检

在 `render_history_expanders()` 中，对河南（opponent == "河南"）的比赛额外输出一行分析：

```python
if opp == "河南":
    # 河南特检
    st.markdown(f"""<div style="padding:8px 12px;margin:4px 0;background:rgba(240,192,64,0.06);border:1px solid rgba(240,192,64,0.12);border-radius:6px;font-size:0.72rem;color:#f0c040">
      <strong>河南策略审计</strong><br>
      策略模式：{strat_label}（rw={rw:.0%} aw={aw:.0%}）<br>
      收入差：场景 ¥{r_h.total_revenue/10000:.1f}万 vs 实际 ¥{total_actual_rev/10000:.1f}万（{rev_delta_vs_actual/10000:+.1f}万）<br>
      数量差：场景 {r_h.total_attendance:,.0f}张 vs 实际 {total_actual_qty:,}张（{qty_delta_vs_actual:+,.0f}张）<br>
      判断：{'✅ 合理 — 策略目标达成' if not bad_tradeoff else '❌ 不合理 — 见上方警告'}
    </div>""", unsafe_allow_html=True)
```

### 4. 表头更新

表格从 7 列扩展为 8 列：
```
档位 | 基准价 | 优化价 | 场景量 | 实际量 | Δ量 | 场景收入 | 实际收入
```

---

## 验证

```bash
python3 -c "import py_compile; py_compile.compile('dashboard/app_v8.py', doraise=True)"
```

## 注意

- `r_h.revenue_weight` 和 `r_h.attendance_weight` 可能不存在于 OptimizerResult —— 如果不存在，从 `render_strategy_card` 已有的 `rw` 变量传入，或者直接复用策略卡片中已计算的 `rw` 值
- 为了避免在 `render_history_expanders` 中重复策略判断逻辑，可以复用 `render_strategy_card` 已计算的 `strat_label` — 但需要修改 `render_strategy_card` 使其返回 `(strat_label, rw)` 以便调用方使用
- 颜色规范：红=涨/增收/增量，绿=跌/减收/减量

直接修改文件，修复完成后验证编译。
