# 票务看板代码审计报告

**审查日期**: 2026-06-16
**审查范围**: 全部核心引擎文件 + 看板文件
**依据**: docs/plans/code-audit-spec.md (12项已知坑位)

---

## 审查概要

| 级别 | 数量 | 说明 |
|------|------|------|
| P0 | 4 | 会导致预测结果错误或逻辑分支走错 |
| P1 | 9 | 违反约定但当前功能正常 |
| P2 | 5 | 风格/可维护性问题 |

---

## P0 — 会导致错误结果的 bug

### P0-1: `late_season` 参数被 rule_engine 静默忽略（多处）

**文件**: `dashboard/components/ctx_builder.py:30`, `dashboard/components/prediction_detail.py:68-69`, `dashboard/app.py:316-317`
**问题**: `ctx_builder.py` 将 `late_season: dt.month >= 10` 传入 optimizer，optimizer 再传给 `rule_engine.predict()`。但 `rule_engine.predict()` 的签名是 `**__`（catch-all kwargs），`late_season` 参数被静默丢弃。结果：看板显示「赛季末 ×0.80」规则命中，但引擎根本没应用该乘数，预测值偏高。

**修复**: 在 `rule_engine.predict()` 中增加 `late_season` 参数支持并定义乘数（建议 0.80），或从 `ctx_builder.py` 移除 `late_season`。

### P0-2: `app.py` V7 的 `rule_predict()` 调用缺少多个情境键

**文件**: `dashboard/app.py:599-604`
**问题**: 调用 `rule_predict()` 时只用 `ctx.get(k, False)` 传入了 5 个 key：
```python
['away_winless', 'lost_bottom', 'heavy_home_loss', 'short_rest', 'unbeaten_3']
```
缺少以下 4 个：`consecutive_home_losses`、`away_winless_losses`、`midseason_restart`、`top3_form`。

**影响**: 当 `detect_ctx()` 返回 `consecutive_home_losses=True` 时，引擎收不到 → 回退到 `heavy_home_loss`（如果有），乘数差异为 0.82 vs 0.85。`away_winless_losses` 同理（0.82/0.77 vs 0.94）。

**修复**: 将 key 列表与 `src/csl_context.py` 的 `predict_with_context()` 以及 `dashboard/components/ctx_builder.py` 的 `_CTX_KEYS` 对齐。

### P0-3: `season_engine.py` 的情境检测与 `csl_context.py` 不同步

**文件**: `src/season_engine.py:77-182`
**问题**: `SeasonEngine.detect_context()` 是一个独立的实现，没有调用 `src/csl_context.detect_ctx()`。与 csl_context 相比缺少：

| 检测项 | csl_context | season_engine |
|--------|:-----------:|:-------------:|
| consecutive_home_losses | ✓ | ✗ |
| away_winless_losses (vs away_winless) | ✓ | ✗（只有 away_winless） |
| top3_form | ✓ | ✗ |
| lost_bottom 条件 | 排名 ≥12 | 排名 ≥12（一致） |

**影响**: `SeasonEngine` 被 `backtest_rule_engine.py` 等回测脚本使用，回测结果会与 `detect_ctx()` 驱动的看板不一致。

**修复**: `season_engine.py` 应调用 `csl_context.detect_ctx()`，删除重复实现。

### P0-4: `app.py` V7 的 `rule_engine.update()` 不会触发

**文件**: `dashboard/app.py`
**问题**: `app.py` 的「历史定价建议」部分（line 610-701）只做 `optimizer.optimize()`，从未调用 `rule_engine.update()`。相比之下 `app_v8.py` → `tab_history.py:218` 每场已赛主场都调用了 `rule_update()`。

**影响**: EMA 校准因子在 V7 看板中永不更新，校准数据停滞。

**修复**: 在 `app.py` 历史循环末尾加入 `rule_update()` 调用（或标记 app.py 已归档不再维护）。

---

## P1 — 违反约定但功能正常

### P1-1: 收入底线显示 93% 但代码使用 90%

**文件**: `dashboard/components/pricing_ui.py:43`, `src/dynamic_optimizer.py:267`
**问题**: KPI 卡片显示「收入底线 93%」，但 optimizer 中 balanced 模式的检查阈值是 `base_revenue * 0.90`（90%）。显示值与实际逻辑不一致。

**修复**: 将 KPI 显示改为 90%，或将 optimizer 阈值改为 93%。需确认产品需求。

### P1-2: `app.py` V7 使用 `pd.to_html`

**文件**: `dashboard/app.py:607`
**问题**: `pd.DataFrame(rows).to_html(index=False, border=0, justify='center')` 违反了「禁止 `st.dataframe` / `st.table` / `pd.to_html`」的约定。

**修复**: 改用手写 HTML `<table class="history-table">`。

### P1-3: `app_v8.py` 中 `st.caption` 使用 `unsafe_allow_html`

**文件**: `dashboard/app_v8.py:98`
**问题**: `st.caption("近5场: " + " · ".join(form_icons), unsafe_allow_html=True)` — `form_icons` 包含 HTML `<span class="result-W">W</span>` 等标签。Streamlit 的 `st.caption` 不保证支持 `unsafe_allow_html`。

**修复**: 改用 `st.markdown(..., unsafe_allow_html=True)`。

### P1-4: `app.py` V7 硬编码 derby 对手列表

**文件**: `dashboard/app.py:237,599`
**问题**: `opp in {"上海申花","山东泰山"}` 硬编码了 derby 集合，而非导入 `src.classify.DERBY_RIVALS`。

**修复**: 使用 `from src.classify import DERBY_RIVALS` 并替换为 `opp in DERBY_RIVALS`。

### P1-5: `app.py` V7 硬编码乘数不同于 `rule_engine.MULTIPLIERS`

**文件**: `dashboard/app.py:303-331`, `src/rule_engine.py:28-39`
**分歧**:

| 因子 | app.py (V7) | rule_engine (source of truth) |
|------|:-----------:|:----------------------------:|
| season_opener | ×1.15 | ×1.17 |
| saturday | ×1.05 | ×1.02 |
| midweek | ×0.90 | ×0.86 |
| short_rest | ×0.75 | ×0.78 |
| away_winless | ×0.95 | ×0.94 |

**修复**: 所有乘数应从 `MULTIPLIERS` 字典读取，不要硬编码。

### P1-6: `app.py` V7 使用 `midweek` 覆盖 `lost_bottom`

**文件**: `dashboard/app.py:318`
**问题**: `app.py` 的条件是 `if mid and not lb and not hh`，但 `rule_engine.predict()` 中的逻辑是 `if midweek and not lost_bottom`（line 99）—— 只排除了 `lost_bottom`，没有排除 `heavy_home_loss`。`app.py` 额外排除了 `heavy_home_loss`，与引擎行为不一致。

**修复**: 删除 318 行的 `and not hh` 条件，或直接使用 `detect_ctx()` + `predict()` 而非手写规则。

### P1-7: `app.py` V7 传入 `unbeaten_3` 参数到 rule_engine

**文件**: `dashboard/app.py:240,604`
**问题**: `unbeaten_3` 在 app.py 的 UI 中展示为「不败 ×1.00」（中性），但 `rule_engine.predict()` 不接受此参数（通过 `**__` 丢弃）。虽然没有数值影响（乘数=1.0），但不应该出现在参数中。

**修复**: 从 `pred_args` 中移除 `unbeaten_3`。

### P1-8: `app.py` V7 的 `update()` 使用了不完整的 context

**文件**: `dashboard/app.py:634` (构建 pred_args 传给 optimizer)
**问题**: 与 P0-2 同一段代码，`**{k:ctx.get(k,False) for k in ['away_winless','lost_bottom','heavy_home_loss','short_rest','unbeaten_3']}` 缺少关键 context key。即使 app.py 已归档，如果有人参考这段代码来写回测，bug 会传播。

**修复**: 使用 `ctx_builder.build_pred_args()` 替代手动构建。

### P1-9: `style.css` 有重复/覆盖规则块

**文件**: `dashboard/style.css:249,353,406,420`
**问题**:
- `.kpi-card` 定义在 line 249-271，又在 line 406-408 用 `!important` 覆盖 `border-top`
- `.progress-line .progress-fill` 在 line 353（红色 #ff6b6b）和 line 399（绿色 var(--guoan-green)）两次定义，后者胜
- `.stMetric` 在 line 33-38 和 line 420-426 重复定义

**修复**: 合并为一处定义，移除旧的无用声明。

---

## P2 — 风格/可维护性

### P2-1: `predict_with_context()` 的 `match_completed=True` 硬编码

**文件**: `src/csl_context.py:307`
**问题**: `predict_with_context()` 中 `match = {"date": match_date, "opponent": opponent, "is_home": True, "completed": True}` 将 `completed` 硬编码为 `True`。虽然是为了让 `detect_ctx` 正确过滤（把本场排除在 `prev` 之外），但用 `completed` 字段来做这件事语义不清晰。

**建议**: 添加注释说明原因。

### P2-2: `dynamic_optimizer.py` 中有 4 个连续标注为「7.」的编号步骤

**文件**: `src/dynamic_optimizer.py:251,267,301,313`
**问题**: 注释编号重复（4 个步骤都标注为 `# 7.`）。

**修复**: 修正编号为 `# 6.`, `# 7.`, `# 8.`, `# 9.`。

### P2-3: `prediction_detail.py` 硬编码 late_season 乘数

**文件**: `dashboard/components/prediction_detail.py:69`
**问题**: `('赛季末', f"{dt.month}月 战意衰减 ×0.80", 0.80, ...)` 将 0.80 硬编码。如果将来改变此乘数，需要同步修改多处。

**修复**: 在 `rule_engine.MULTIPLIERS` 中增加 `late_season` 键并从字典取值。

### P2-4: `live_calibrate.py` 的权重逻辑与 `dynamic_optimizer.py` 不完全一致

**文件**: `src/live_calibrate.py:197-202`, `src/dynamic_optimizer.py:134-141`
**问题**: `LiveCalibrator.calibrated_optimize()` 内嵌了自己的一套 `rw` 计算逻辑（基于 blended_pred: ≥11K=0.80, ≤7.5K=0.20, 中间线性插值），而 `DynamicPricingOptimizer.optimize()` 内部也有一份（基于 predicted_total: ≥10K=0.80, ≥8K=0.55, ≥6K=0.35, else 0.20 + 对手级别 cap）。两处逻辑不同但没有注释说明差异原因。

**修复**: 统一权重计算逻辑，或添加注释说明为何 live_calibrate 使用不同的权重分档。

### P2-5: `app.py` V7 未使用 `finalize_guoan_schedule` 去重

**文件**: `dashboard/app.py:534-535`
**问题**: `app.py` 直接使用 `get_guoan_matches(all_matches)` 并 filter source，但未调用 `finalize_guoan_schedule()`。而 `app_v8.py` 的 `data_cache.py` 调用了 `finalize_guoan_schedule`。V7 的 `next_match` 逻辑（line 556-557）也因此没有跳过过期 scheduled 脏数据。

**修复**: 如果 V7 仍需维护，加入 `finalize_guoan_schedule()` 调用。

---

## 逐项坑位检查结果

### 坑位 1: 参数源不一致

| 检查项 | 状态 | 详情 |
|--------|:----:|------|
| MULTIPLIERS vs app.py 硬编码 | ❌ | 5/7 个因子值不一致 (P1-5) |
| app_v8 是否导入 MULTIPLIERS | ✓ | constants.py 导入，prediction_detail 使用 |
| 叠加规则是否一致 | ⚠️ | app.py 多排除了 heavy_home_loss (P1-6) |
| late_season 无对应乘数 | ❌ | 两处使用但引擎未实现 (P0-1) |

### 坑位 2: CSS 类作用域

| 检查项 | 状态 | 详情 |
|--------|:----:|------|
| .mul 全局可用 | ✓ | style.css 有全局 `.mul` 声明 |
| .mul-neg 全局可用 | ✓ | style.css 有全局 `.mul-neg` 声明 |
| 所有 CSS class 有声明 | ✓ | result-W/D/L, guoan-row 等均有声明 |

### 坑位 3: 禁用组件

| 检查项 | 状态 | 详情 |
|--------|:----:|------|
| app_v8 表格 | ✓ | 全部手写 HTML `<table>` |
| app.py V7 表格 | ❌ | pd.to_html 违规 (P1-2) |
| 全局 st.dataframe/st.table | ✓ | 未发现使用 |

### 坑位 4: 颜色规范

| 检查项 | 状态 | 详情 |
|--------|:----:|------|
| 红 #ff6b6b = 涨/胜 | ✓ | 全代码一致 |
| 绿 #51cf66 = 跌/负 | ✓ | 全代码一致 |
| .W/.L CSS 一致 | ✓ | style.css 正确定义 |

### 坑位 5: short_rest 阈值

| 检查项 | 状态 | 详情 |
|--------|:----:|------|
| csl_context.py | ✓ | `<= 4` (line 244) |
| season_engine.py | ✓ | `<= 4` (line 166) |
| app.py 描述 | ✓ | 显示「≤4天」 |

### 坑位 6: T3-T4 间距

| 检查项 | 状态 | 详情 |
|--------|:----:|------|
| T3 upper bound = T4 / 1.18 | ✓ | dynamic_optimizer.py:228 |
| 跨级约束 upper_price / 1.05 | ✓ | dynamic_optimizer.py:377 |

### 坑位 7: st.expander 标签

| 检查项 | 状态 | 详情 |
|--------|:----:|------|
| app_v8 / app.py 中有无 em-dash | ✓ | 未使用 st.expander |
| tab_history.py expander 替代方案 | ✓ | 使用 div + inline 渲染 |

### 坑位 8: st.caption unsafe_allow_html

| 检查项 | 状态 | 详情 |
|--------|:----:|------|
| app_v8.py line 98 | ❌ | 使用 `unsafe_allow_html` (P1-3) |
| 其他 caption 调用 | ✓ | 均为纯文本 |

### 坑位 9: 硬编码 vs 导入

| 检查项 | 状态 | 详情 |
|--------|:----:|------|
| app_v8 导入 rule_engine.MULTIPLIERS | ✓ | 通过 constants.py 导入 |
| app.py V7 使用硬编码 | ❌ | derby 集合、乘数均硬编码 (P1-4, P1-5) |
| CSL 情境检测调用 detect_ctx | ✓ / ❌ | app_v8 ✓；season_engine ✗ (P0-3) |

### 坑位 10: 预测上下文

| 检查项 | 状态 | 详情 |
|--------|:----:|------|
| app_v8 使用 detect_ctx | ✓ | data_cache.py:164 |
| app.py V7 使用 detect_ctx | ⚠️ | 使用但传入不完整 key (P0-2) |
| 无手动 heavy_home_loss=True | ✓ | 未发现硬编码 |

### 坑位 11: 收入底线

| 检查项 | 状态 | 详情 |
|--------|:----:|------|
| Balanced 模式 ≥ 基准 × 90% | ✓ | dynamic_optimizer.py:267 |
| KPI 卡片显示 93% | ❌ | 显示值与代码不一致 (P1-1) |
| 整体收入 Δ < max(0.5%, ¥5,000) | ✓ | dynamic_optimizer.py:303 |

### 坑位 12: 取整规则

| 检查项 | 状态 | 详情 |
|--------|:----:|------|
| 涨价取整 ¥10 | ✓ | dynamic_optimizer.py:500 |
| 涨价增量收入 ≥ ¥10,000 | ✓ | dynamic_optimizer.py:521 |
| 降价增量数量 ≥ 100 人 | ✓ | dynamic_optimizer.py:528 |
| 变化 < 3% 不调 | ✓ | dynamic_optimizer.py:504 |

---

## 总结

| 优先级 | 数量 | 核心问题 |
|--------|:----:|----------|
| P0 | 4 | `late_season` 静默丢弃、V7 缺少情境键、season_engine 不同步、V7 缺少 update |
| P1 | 9 | 收入底线显示不一致、pd.to_html、caption HTML、硬编码乘数/derby 集合、CSS 重复 |
| P2 | 5 | 编号错误、硬编码 magic number、权重逻辑不一致、未使用去重函数 |

**建议**: P0-1 (`late_season`) 和 P0-2 (V7 缺少 context key) 影响所有看板预测的正确性，应优先修复。P0-3 (season_engine) 影响回测，建议在下一轮回测前修复。`app.py` V7 已标注为归档文件，其 P0/P1 问题可通过切换到 V8 解决。
