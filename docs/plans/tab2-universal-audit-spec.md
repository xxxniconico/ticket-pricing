# Tab2 全量策略审计 + Bad Tradeoff 强化

你是票务系统审计专家。请修改 `dashboard/app_v8.py` 的 Tab2 历史定价部分。

## 任务 1: 策略审计卡片通用化

当前「河南策略审计」（L847-853 附近）只对 `opp == "河南"` 显示。改为**每场比赛都显示策略审计卡片**。

### 修改方案

1. 移除 `if opp == "河南":` 条件，改为对所有比赛输出
2. 审计卡片标题改为 `**{opp} 策略审计**`
3. 卡片颜色根据策略和 bad_tradeoff 动态调整：
   - 策略达成（无 bad_tradeoff）→ 绿色边框 `rgba(81,207,102,0.12)` + 绿色文字 `#51cf66`
   - 策略未达成（bad_tradeoff）→ 红色边框 `rgba(255,107,107,0.2)` + 红色文字 `#ff6b6b`
4. 判断文字改为：
   - 无 bad_tradeoff → `✅ 策略目标达成`
   - 有 bad_tradeoff → `❌ 策略未达成 — 见上方警告`

---

## 任务 2: 新增 Bad Tradeoff 规则 — 增收不值

当前只有两条 bad tradeoff 规则：
- 收入优先 + 损失>¥1万 + 增量<500张
- 上座优先 + 未增量 + 损失>¥5k

**缺失场景**：收入增加了，但增加幅度远小于上座损失。例如：
- 上海海港：+¥2万 但上座 -2,717张 → 每损失1人只换来 ¥7.36，极不合理

### 新增规则

```python
# 规则3: 增收但代价过大（收入优先+均衡模式）
# 收入有增加但上座大幅下降 → 每增¥1收入损失超过阈值人数
if rw >= 0.5:  # 收入优先或均衡
    rev_gain = rev_delta_vs_actual
    qty_loss = -qty_delta_vs_actual  # 正数 = 损失人数
    if rev_gain > 0 and qty_loss > 100:  # 增收但损失超100人
        # 每损失1人换来的增收
        gain_per_lost = rev_gain / qty_loss if qty_loss > 0 else float('inf')
        if gain_per_lost < 50:  # 低于¥50/人 → bad tradeoff
            bad_tradeoff = True
            bad_reason = f"⚠️ 增收 ¥{rev_gain/10000:.1f}万但上座 -{qty_loss:,.0f}张（仅 ¥{gain_per_lost:.0f}/人），代价过大"

# 规则4: 降价增量但收入损失过大（上座优先模式）
if rw <= 0.3:
    qty_gain = qty_delta_vs_actual
    rev_loss = -rev_delta_vs_actual  # 正数 = 损失金额
    if qty_gain > 0 and rev_loss > 5000:
        cost_per_gained = rev_loss / qty_gain if qty_gain > 0 else float('inf')
        if cost_per_gained > 200:  # 每获得1人花费>¥200 → bad tradeoff
            bad_tradeoff = True
            bad_reason = f"⚠️ 增量 {qty_gain:+,.0f}张但损失 ¥{rev_loss/10000:.1f}万（¥{cost_per_gained:.0f}/人），获客成本过高"
```

**注意**：
- `rev_delta_vs_actual` 和 `qty_delta_vs_actual` 已在 L818-819 计算
- 新增规则放在原有两条规则之后（L828 之后）
- 如果已有 bad_tradeoff（被前面规则触发），不再重复设置
- `gain_per_lost` 阈值 ¥50/人 和 `cost_per_gained` 阈值 ¥200/人 是初始值，标注为可调参数

---

## 测试案例

改完后用以下场景验证规则触发：

1. **上海海港 (2026-05-10)**: 预期触发规则3（增收但代价过大）
2. **河南 (2026-05-23)**: 预期触发规则1（收入优先损失收入）
3. **申花 (2026-03-21)**: 预期不触发任何 bad_tradeoff
4. **成都 (2026-04-12)**: 预期根据数据判断

---

## 验证

```bash
python3 -c "import py_compile; py_compile.compile('dashboard/app_v8.py', doraise=True)"
```

## 约束

- 不改动 Tab1（预测模式）
- 不改动策略卡片的渲染逻辑
- 审计卡片颜色与 bad_tradeoff 联动
- 直接修改文件
