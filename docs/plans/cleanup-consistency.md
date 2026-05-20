# Cursor 修复 — 看板代码一致性清理

> Hermes 和 Cursor 多次交替修改导致变量口径不一致。
> 一次性全局清理所有遗留引用。

---

## 1. 搜索并删除所有未定义变量

```bash
cd ~/ticket-pricing
grep -n "\bmult\b" dashboard/app.py
```

如果 `mult` 出现在以下位置，直接用右侧替换：

| 原代码 | 替换为 |
|--------|--------|
| `mult = 1.0` | `cap_ratio = 1.0` |
| `mult = v2_pred / avg_total` | `cap_ratio = min(v2_pred/total_cap, 1.0)` |
| `* mult` (乘数) | 删除 `* mult` |
| `{mult:.3f}×` | `{cap_ratio:.0%}` |
| `v2÷场均 {mult}` | `容量 {cap_ratio:.0%}` |
| 任何引用 `avg_total_tab` | 替换为 `v2_pred` 或删除 |

## 2. 搜索未定义变量

```bash
grep -n "avg_total_tab\|cal_weights = calibrate" dashboard/app.py
```

- 删除所有 `avg_total_tab` 引用
- 删除所有 `cal_weights = calibrate_context_weights(DATA_DIR)` 重复调用（已在顶部缓存为 `cal_weights = _get_cal_weights()`）

## 3. 回测图表标题清理

```bash
grep -n "乘数=v2" dashboard/app.py
```
替换 `"预测 vs 实际（乘数=v2÷场均）"` 为 `"预测 vs 实际（v2容量约束）"`

## 4. 确认 Tab1/Tab2 无报错

```bash
pkill -f streamlit
cd ~/ticket-pricing
~/hermes-agent/venv/bin/python -c "compile(open('dashboard/app.py').read(), 'app.py', 'exec'); print('OK')"
bash dashboard/serve.sh
```

打开 http://localhost:8504，切换 Tab1/Tab2 确认无代码级报错。
