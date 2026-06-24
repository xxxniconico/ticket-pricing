# 票务看板代码审计 — 2026-06-15

## 审查范围

审查以下文件的所有代码问题：bug、逻辑错误、参数不一致、CSS 问题、Streamlit 反模式、颜色规范违反。

### 核心引擎文件
- src/rule_engine.py — 规则引擎乘数
- src/dynamic_optimizer.py — 动态优化器
- src/pricing_v5.py — V5 定价矩阵
- src/csl_context.py — 情境检测
- src/live_calibrate.py — 实时预售校准
- src/calibrate.py — 上座模型
- src/elasticity.py — 需求弹性
- src/season_engine.py — 赛季引擎

### 看板文件
- dashboard/app_v8.py — V8 主看板 (:8506)
- dashboard/app.py — V7 看板 (:8504)

## 已知坑位清单（必须逐项检查）

### 1. 参数源不一致
- rule_engine.py 的 MULTIPLIERS 和 dashboard/app.py 里硬编码的乘数是否一致？
- 查 heavy、away_winless、short_rest、midweek、opener 五个因子在两处的值
- 叠加规则是否一致（哪些因子允许叠加，哪些互斥）

### 2. CSS 类作用域
- `.rule-line .mul` 只在 `.rule-line` 内生效，外部用 `class="mul"` 不生效
- 检查所有 HTML class 引用是否都有对应的全局 CSS 声明

### 3. 禁用组件
- **禁止 st.dataframe / st.table / pd.to_html** — 会出白色底
- 必须用手写 HTML `<table class="xxx">` + CSS
- 检查是否所有表格都遵守

### 4. 颜色规范
- 红=涨/增长(#ff6b6b)，绿=跌/下降(#51cf66)
- .W=红(胜=好)，.L=绿(负=坏)
- 检查所有颜色变量和内联样式是否一致

### 5. short_rest 阈值
- 阈值必须 ≤4 天（不是 ≤5 天）
- 检查 csl_context.py 和 app.py 两处

### 6. T3-T4 间距
- T3→T4 间距 ≥18%
- 跨级约束 upper_price/1.05

### 7. st.expander 标签
- 不能用 em-dash `—` 或特殊 Unicode → 中文乱码
- 必须用 `|` 分隔

### 8. st.caption
- 不支持 unsafe_allow_html
- 检查是否有 st.caption 里塞了 HTML

### 9. 硬编码 vs 导入
- app_v8.py 是导入 rule_engine.MULTIPLIERS 还是自己硬编码了一套？
- CSL 情境检测是调用 detect_ctx() 还是手动判断？

### 10. 预测上下文
- 所有预测必须用 src/csl_context.py 的 detect_ctx() 
- 禁止手动设 heavy_home_loss=True 等

### 11. 收入底线
- 平衡模式收入 ≥ 基准 × 90%（还是 93%？检查两处）
- 整体收入 Δ < max(0.5%, ¥5,000) 全回退

### 12. 取整规则
- 涨价取整 ¥10
- 涨价单档增量收入 ≥ ¥10,000 才调
- 降价单档增量数量 ≥ 100 人才调
- 变化 < 3% 不调

## 产出要求

1. 按 P0/P1/P2 分级列出所有发现的问题
2. 每个问题标注：文件、行号、问题描述、修复建议
3. P0 = 会导致错误结果或崩溃的 bug
4. P1 = 违反约定但功能正常的代码
5. P2 = 风格/可维护性问题

直接输出审查报告到 docs/plans/code-audit-report.md，不要只描述计划。
