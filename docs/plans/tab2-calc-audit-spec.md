# Tab2 历史定价 — 计算逻辑审计

你是票务定价系统的审计专家。请对 `dashboard/app_v8.py` 中 Tab2 历史定价部分进行深入的计算逻辑审查。

## 审查范围

`render_history_expanders()` 函数（约 L699-766），特别是每个已赛主场的定价表格和优化效果计算。

## 核心问题

用户质疑：**"优化效果为什么是场景量-预测量，是不是应该用场景量-实际量？"**

请逐一检查以下计算链路：

### 1. 数据来源追溯
- `r_h = optimizer.optimize(opp, **pred_args)` — 优化器返回的 `TierResult` 各字段含义
  - `tr.predicted_qty` 是什么？是规则引擎预测的上座还是优化后的上座？
  - `tr.base_qty` 是什么？
  - `r_h.predicted_total` 是什么？和 `total_pred_qty` 的关系？
- `zone_qty = _get_zone_qtys(m)` — 从 parquet 读的是什么？各档实际售出票数？
- `zone_rev = _get_zone_actual_revenue(m)` — 从 parquet 读的是什么？各档实际收入？

### 2. 表格列计算审计
逐列审计 L729-748 的表格渲染代码：
```
档位 | 基准价 | 优化价 | 场景量 | 实际量 | 场景收入 | 实际收入
```
- "场景量"列：`tr.predicted_qty` — 这是什么场景下的预测量？
- "场景收入"列：`tr.revenue` — 这是 `optimal_price * predicted_qty` 还是 `base_price * base_qty`？

### 3. 优化效果计算审计
L750-766 的合计行和 caption：
- `rev_delta = r_h.total_revenue - r_h.base_revenue` — 这是什么 vs 什么的增量？
- `total_scenario` vs `total_fixed` — 两者的语义
- `total_pred_qty` — 这个变量名有歧义，它实际存的是什么？

### 4. 语义正确性判断

请判断以下说法的正确性：

A) "优化效果 = 场景收入 - 基准收入" — 这衡量的是优化定价相比不优化能多赚多少
B) "优化效果 = 场景收入 - 实际收入" — 这衡量的是如果用了优化定价，相比实际能多赚多少
C) "场景量 - 预测量" — 当前 L756 的 `total_pred_qty` 和 `r_h.base_attendance` 的关系
D) "场景量 - 实际量" — 用户建议的对比方式

**关键判断**: 在「历史定价」Tab 中，比赛已经踢完了，用户想看的是「如果我们当时用了这个优化定价，会比实际结果好多少」。所以用户说的「场景量-实际量」是否更合理？

### 5. 其他潜在 Bug
- `total_pred_qty` 变量名是否会误导（它存的是场景量而非预测量）？
- `total_scenario` vs `r_h.total_revenue` 是否有重复？
- `_get_zone_qtys` 和 `_get_zone_actual_revenue` 各自独立读 parquet（虽然已通过 `_get_csl_parquet` 缓存），它们的 match_id 匹配逻辑是否正确？
- `total_fixed` vs 实际收入是否一致？

## 输出

直接修改代码修复所有发现的问题，包括：
1. 如果语义错误，修正对比基准
2. 如果变量名误导，重命名
3. 清理冗余代码

修改后验证编译：`python3 -c "import py_compile; py_compile.compile('dashboard/app_v8.py', doraise=True)"`
