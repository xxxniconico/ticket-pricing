# V8 新增 H2 策略 Tab

## 数据源
- JSON: `data/targets/h2_2026_match_targets.json`
- 结构: `{completed: {matches, revenue, quantity}, summary: {total_target_revenue, annual_projection_revenue, vs_2025_revenue_pct}, matches: [{date, opponent, round, tier, strategy, revenue_weight, target_revenue, target_quantity, target_avg_price, base_prices: {T1-T6}, risks, context}], notes}`

## Tab 位置
在 `app_v8.py` 中加入第 6 个 Tab "H2策略"，放在"积分榜"之后。

## 布局

### 顶部：策略总览 KPI 行（4 卡片）
| 卡片 | 值 | 副值 |
|------|-----|------|
| 已完成 | ¥20.58M / 59,583张 | 7场 |
| 剩余目标 | ¥18.77M / 66,461张 | 8场 |
| 全年预估 | ¥39.35M | vs 2025: -14.3% |
| 模型版本 | V5.3 | MAE=384 |

### 中部：策略分级图例
横向 pill 展示 3 种策略：revenue_priority(收入优先/红)、revenue_tilt(收入偏重/橙)、balanced(均衡/黄)

### 主体：逐场策略表
手写 HTML table，列：
`日期 | 对手 | 级别 | 策略 | 预测(张) | 目标量 | 目标均价 | 目标收入 | T1基价 | T6基价 | 风险`

每行右侧或下方用小字显示上下文/风险标注。

### 底部：动态追踪 + 熔断规则
- 累计追踪表：每场累计目标收入 vs 实际收入（实际留空/占位）
- 风险熔断规则折叠展示（4 条规则）

## 技术
- 函数: `render_h2_strategy()` 放在 `render_opponent_analysis()` 附近
- 读取 JSON: `json.load(open(ROOT/"data/targets/h2_2026_match_targets.json"))`
- 不改 src/ 任何文件
- 暗色 Linear 风格，手写 HTML table
- 策略颜色: revenue_priority=#ff6b6b, revenue_tilt=#f0c040, balanced=#c2ef4e
