# V8 模型参数同步修复

## 问题

`dashboard/app_v8.py` 中硬编码了 4 个乘数，与 `src/rule_engine.py` 的 MULTIPLIERS dict 不一致。

## 修复方案：直接从 rule_engine 导入 MULTIPLIERS

不要硬编码乘数值。改为：

1. 在 app_v8.py 顶部 import 中加入 MULTIPLIERS：
```python
from src.rule_engine import predict_calibrated as rule_predict, TIER_BASE, MULTIPLIERS, PENALTY_FLOOR, get_calibration
```
（MULTIPLIERS 已经在 import 中，确认已导入）

2. 在 `render_tab1()` 中替换所有硬编码乘数为 `MULTIPLIERS["key"]`：

| 当前硬编码 | 应改为 |
|-----------|--------|
| `×0.95` (away_winless L520) | `MULTIPLIERS["away_winless"]` |
| `×1.05` (saturday L513) | `MULTIPLIERS["saturday"]` |
| `×0.75` (short_rest L553) | `MULTIPLIERS["short_rest"]` |
| `×0.90` (midweek L517) | `MULTIPLIERS["midweek"]` |

3. 所有 f-string 中的显示文本也要动态生成，例如：
```python
# 改前: f"周末上座溢价 ×1.05"
# 改后: f"周末上座溢价 ×{MULTIPLIERS['saturday']}"
```

4. 同样检查 `render_history_expanders()` 中是否有硬编码乘数 — 历史定价区用的是 optimizer.optimize() 不是 rule_predict，所以乘数由 optimizer 内部调用 rule_engine，不需要改。

## 验证

修改后，`render_rule_pills` 显示的乘数应与 `MULTIPLIERS` dict 一致：
- away_winless: 0.98
- saturday: 1.02
- short_rest: 0.78
- midweek: 0.92
