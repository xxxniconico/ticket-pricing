# V8 看板 UI 审查报告

> 审查日期: 2026-06-03  
> 审查文件: `dashboard/app_v8.py` (1354行), `dashboard/style.css` (353行), `src/rule_engine.py`, `src/pricing_v5.py`

## 总评

V8 看板整体处于**生产可用**水平，暗色主题风格统一、KPI 卡片体系清晰、信息密度高。Tab 分区合理覆盖了从单场决策到赛季全景的完整决策链路。但存在三类结构性问题：(1) **代码重复严重** —— 预测参数构建、策略卡片、规则 Pill 链、定价表四个核心 HTML 片段各重复 2-3 次；(2) **数据流混乱** —— `load_csl_data()` 在 Tab 4 内重新调用，未复用 main() 中的缓存结果；(3) **硬编码散落** —— What-If 乘数、瀑布图数据、对手集合等硬编码在视图层。此外，缺少加载/空/错误三态处理，移动端完全未适配。综合评级: **🌟🌟🌟 (3/5)**。

## 各维度评分

| 维度 | 评级 | 一句话 |
|------|------|--------|
| 信息架构 | ⭐⭐⭐⭐ 良 | Tab 划分合理，但 Tab1 过载（预测→定价→沙盒→座位图），`load_csl_data()` 被重复调用 |
| 视觉层次 | ⭐⭐⭐⭐ 良 | KPI 卡片注意力引导有效，颜色规范基本一致，但部分 Tab 缺少视觉锚点 |
| 交互体验 | ⭐⭐⭐ 中 | What-If 预设仅3种，历史页全展开满足偏好，但零加载/空/错误状态 |
| 代码质量 | ⭐⭐ 差 | 4组核心代码块各重复2-3次，12+处硬编码，`load_csl_data()`错误地在Tab4内重新调用 |
| 性能 | ⭐⭐⭐ 中 | 缓存策略基本合理，但parquet被3个函数独立读取，座位图无缓存 |
| 移动端/响应式 | ⭐ 差 | 零移动端适配，8列KPI卡片在小屏必然断裂，Tab溢出无处理 |

## 详细分析

### 维度: 信息架构
**评级:** ⭐⭐⭐⭐ 良

**发现:**

1. **Tab1 功能过载** (`app_v8.py:493-624`)
   - Tab1「下一场预测」包含：近期赛果 → 规则计算链 → 预测柱状图 → 置信区间 → 策略选择 → 定价表 → What-If沙盒 → 座位图
   - 这是看板中视觉高度最高的Tab，用户需要滚动3-4屏才能看完
   - 影响：决策者在时间压力下可能遗漏关键定价信息
   - **建议**: 将座位图抽出为独立 Tab 或折叠到 expander；What-If 可考虑简化为侧边栏常驻面板

2. **`load_csl_data()` 被重复调用** (`app_v8.py:841` vs `app_v8.py:59`)
   - `main()` 第 59 行通过 `@st.cache_data` 的 `load_data()` 已加载全量数据
   - `render_opponent_analysis()` 第 841 行重新调用 `load_csl_data()` 且结果未缓存
   - 影响：每次进入 Tab4 都重新读取 JSON 文件，浪费 ~200ms+ I/O
   - **建议**: 将 `main()` 中 `load_data()` 的结果 `all_matches` 作为参数传入 `render_opponent_analysis()`

3. **KPI 卡片对所有 Tab 全局显示** (`app_v8.py:1311`)
   - KPI 卡片在 `main()` 中渲染一次，在所有 Tab 上方 — 合理 ✓
   - 但「下一场对手」卡片在 Tab3（赛季全景）、Tab4（对手分析）等页面上方出现时显得突兀
   - 影响：信息相关性逐 Tab 递减
   - **建议**: 考虑在非决策类 Tab（赛季全景、对手分析、积分榜）上使用缩略版 KPI 行

4. **Tab 命名直观性**
   - ✓ 「下一场预测」「历史定价」「对手分析」「积分榜」清晰准确
   - △ 「赛季全景」实际只含预测vs实际折线图+回望表，可更名为「赛季回望」
   - △ 「H2策略」对非内部用户不够直观，可更名为「收入策略」或「H2驾驶舱」

### 维度: 视觉层次
**评级:** ⭐⭐⭐⭐ 良

**发现:**

1. **KPI 卡片注意力引导良好** (`app_v8.py:194-203`, `style.css:228-251`)
   - 8 张卡片分两行 4 列，label/value/sub 三级字体层次清晰
   - 数值用 `font-weight: 590` + `#f7f8f8` 高亮，辅助信息用 `#62666d` / `#8a8f98` 退后 ✓
   - **建议**: 在「下一场对手」卡片上增加对手队徽 emoji 或颜色编码（S=红/A=黄/B=灰/C=绿）

2. **各 Tab 视觉入口分析**
   - Tab1: `subheader` 对手名 + 规则 Pill 链 → 视觉锚点明确 ✓
   - Tab2: MAE 水平条形图 → 独特且有辨识度 ✓
   - Tab3: Matplotlib 折线图 → 图表即入口 ✓
   - Tab4: 对手分级矩阵表格 → 信息密集，缺乏标题引导 △
   - Tab5: 赛季行逐行渲染 → 无汇总入口，需滚动查看 △
   - Tab6: 4 KPI + 下一场盯盘 → 入口清晰但信息密度极高 △
   - **建议**: Tab4 增加 KPI 摘要行（N队S级/N队A级/国安战绩vs各级）；Tab5 顶部增加赛季进度环

3. **颜色规范一致性**
   - 「红涨绿跌」规范: `#ff6b6b` = 涨/好/胜, `#51cf66` = 跌/坏/负 ✓
   - 但存在语义歧义：收入增加 = 红是好的（增收），上座增加 = 红在收入优先模式下也是好的，但在上座优先模式下应为绿 → 当前无区分 △
   - Matplotlib 图表内颜色与 CSS 一致 ✓
   - H2 熔断灯颜色三级（绿/黄/红）语义清晰 ✓
   - **建议**: 统一审核所有 `#ff6b6b` 和 `#51cf66` 的使用场景，确保「红=收入向好」「绿=上座向好」的语义一致

4. **字体层级** (`style.css:7-20`)
   - h1 → 1.5rem, h2 → 1.1rem, h3 → 0.95rem ✓
   - kpi-value → 1.2rem, 正文 → 默认 ✓
   - 等宽字体用于数字（JetBrains Mono）✓
   - **问题**: 多处内联样式覆盖了 CSS 字体大小（如 `font-size:0.75rem` 直接写在 `<div>` 上），导致层级不一致
   - **建议**: 使用 CSS 类替代内联 `font-size`，统一管理字体层级

### 维度: 交互体验
**评级:** ⭐⭐⭐ 中

**发现:**

1. **What-If 预设情景过少** (`app_v8.py:405-413`)
   - 仅 4 种预设: 基准、悲观(-20%)、乐观(+15%)、自定义
   - 悲观/乐观的乘数 0.80/1.15 与 `MULTIPLIERS` 中任何规则都不对应
   - 缺少实际业务场景预设: "德比战"、"工作日减量"、"赛季末促销"、"暑假特惠"
   - 影响：用户无法快速切换到真实定价场景进行对比
   - **建议**: 预设从 `MULTIPLIERS` 导入，增加 6-8 个业务语义预设（如「德比溢价 ×1.25」「暑假活动 ×1.13」「工作日 ×0.86」）

2. **历史定价页全部展开** (`app_v8.py:657-766`)
   - 每场比赛直接渲染全部内容（策略卡片 + 7 列表格），无折叠 ✓
   - 符合已知用户偏好（不喜欢折叠）
   - 但 10+ 场比赛时页面极长，无「快速跳转」或「锚点导航」
   - **建议**: 增加顶部锚点栏（日期快选），不改变展开行为

3. **策略模式 radio 默认行为** (`app_v8.py:605-610`)
   - `key=f"strategy_{opp}"` 使用对手名做 key，切换比赛时自动重置 → 合理 ✓
   - 但 `format_func` 提示文字过长（"平衡（T1-T3降价抢量+T4-T6涨价补收入）"），在小屏幕上截断
   - **建议**: 将说明文字移至 `st.caption` 或 tooltip

4. **零态/空态/错误态处理缺失**
   - 加载态: 无 `st.spinner()` — 首次打开 parquet 读取无视觉反馈
   - 空态: 仅 `st.info("暂无已赛主场数据")` (第 659, 803 行)，无数据时的 KPI 卡片显示 `"—"` 但未解释原因
   - 错误态: `st.error("无法加载 CSL 数据")` (第 1246 行) 后 `st.stop()` — 无重试按钮
   - 影响：用户面对空白或错误时无所适从
   - **建议**: 
     - 数据加载时包裹 `st.spinner("加载 CSL 数据...")`
     - 空态显示原因："2026 赛季尚未开赛" vs "数据文件缺失"
     - 错误态增加「刷新重试」按钮

5. **Toggle 开关缺少即时反馈** (`app_v8.py:1050-1053`)
   - 「⬆ 升B升级」toggle 切换后，表格数据已更新但无视觉确认
   - **建议**: toggle 切换时增加 `st.toast` 或明显的数值变化动画

### 维度: 代码质量
**评级:** ⭐⭐ 差

**发现:**

1. **`pred_args` 字典构建重复 3 次** — **最严重的重复问题**
   - 位置 1: `render_tab1` 第 612-616 行
   - 位置 2: `render_history_expanders` 第 678-684 行
   - 位置 3: `render_h2_strategy` 第 966-971 行
   - 三次构建的唯一差异：Tab1 多了 `'season_opener': so`, `'unbeaten_3': ub3`；Tab2 多了 `'summer': dt_m.month in [7,8]`, `'match_year': m["date"][:4]`；H2 多了 `'match_year': "2026"`, 少了 `'unbeaten_3'`
   - **建议**: 抽取 `build_pred_args(match, ctx, overrides=None) -> dict` 函数

2. **策略卡片 HTML 重复 2 次** — **结构完全一致**
   - `render_strategy_card()` 第 321-359 行（Tab1 使用）
   - `render_history_expanders()` 第 687-718 行（Tab2 内联实现）
   - Tab2 的策略卡片与 `render_strategy_card()` 功能完全相同，仅调用方式不同
   - **建议**: Tab2 直接调用 `render_strategy_card(r_h, pred_args)`，删除内联复制

3. **规则 Pill 条件判断重复 2 次** — **逻辑完全一致**
   - `render_strategy_card()` 第 334-343 行：从 `pred_args` 构建 `rules_parts` 列表
   - `render_history_expanders()` 第 695-703 行：完全相同的 `if pred_args.get(...)` 链
   - **建议**: 抽取 `build_rule_labels(pred_args) -> list[str]` 函数

4. **定价表 HTML 重复 3 次** — **结构高度相似**
   - Tab1 定价表: `render_pricing_table()` 第 361-399 行（6 列：档位/基准价/优化价/Δ价/预测量/场景收入）
   - What-If 表: `render_what_if()` 第 433-480 行（6 列：档位/基准价/手动价/基准量/手动量/手动收入）
   - Tab2 定价表: `render_history_expanders()` 第 721-766 行（7 列：档位/基准价/优化价/场景量/实际量/场景收入/实际收入）
   - 三者使用相同的 `<tr>` 构建模式，仅列配置不同
   - **建议**: 抽取 `render_price_table(columns: list[tuple[str, callable]], rows_data, totals) -> str` 通用渲染器

5. **硬编码乘数值未从 `rule_engine.py` 导入**
   - What-If 悲观乘数 `0.80` (第 412 行) vs 应有的规则乘数
   - What-If 乐观乘数 `1.15` (第 413 行) — 接近但不等于 `MULTIPLIERS["season_opener"]` (1.17)
   - 德比判断 `opp in {"上海申花", "山东泰山"}` (第 160, 507, 679, 967 行) — 应使用 `DERBY_RIVALS` (已从 classify.py 导入但未在此处使用)
   - **建议**: What-If 预设乘数从 `MULTIPLIERS` 导入；德比判断统一使用 `DERBY_RIVALS`

6. **H2 瀑布图数据硬编码** (`app_v8.py:1104-1107`)
   - `categories` 和 `values` 完全硬编码为 `[4591, -650, -200, -348, 3935]`
   - 与 `summary["annual_projection_revenue"]` 和 `summary["vs_2025_revenue_pct"]` 存在冗余
   - **建议**: 从 `summary` 动态计算瀑布图数值，或在 JSON 中存储分解数据

7. **`render_opponent_analysis()` 内部重新导入** (`app_v8.py:839-841`)
   - `from src.classify import classify_opponent_tier` — 已在文件顶部导入
   - `from src.csl_context import load_csl_data, get_guoan_matches` — 未使用顶部导入，且 `load_csl_data` 结果未缓存
   - **建议**: 删除内部导入，接收 `all_matches` 参数

8. **`get_optimizer()` 被调用 4 次** (`app_v8.py:430, 617, 665, 958`)
   - 每次调用返回同一 `@st.cache_data` 实例 — 合理 ✓
   - 但第 958 行在 `render_h2_strategy` 中绕过缓存直接构造 `DynamicPricingOptimizer(revenue_weight=0.6)` (第 958 行)
   - **建议**: 统一使用 `get_optimizer()`

9. **CSS 类命名**
   - `.kpi-card`, `.strategy-card`, `.rule-pill`, `.confidence-bar`, `.progress-line` — 前缀命名清晰 ✓
   - `.up`, `.down`, `.flat`, `.W`, `.D`, `.L` — 单字母类名在大型项目中可能冲突 △
   - `.history-table` 全局选择器 `table { }` 影响 Streamlit 原生表格 — 有缓存风险 △
   - **建议**: 为 `.W/.D/.L` 添加命名空间前缀如 `.result-W`；`table { }` 改为 `.history-table, .compact-table { }` 避免全局污染

10. **文件级硬编码**
    - `ROOT` 路径重复定义：第 19-20 行独立设置，第 67/82/104 行使用 `ROOT / "data/processed/all_unified.parquet"` — 4 次拼接同一路径
    - **建议**: 定义 `PARQUET_PATH = ROOT / "data/processed/all_unified.parquet"` 常量

### 维度: 性能
**评级:** ⭐⭐⭐ 中

**发现:**

1. **`@st.cache_data` 使用分析**
   - `get_optimizer()` TTL=3600 ✓ — 优化器不变
   - `load_data()` TTL=600 ✓ — 比赛数据可能更新
   - `get_actual()` TTL=300 — 过短，实际收入数据写入后不会改变；且每次从 parquet 全量读取后遍历匹配 ⚠
   - `_get_zone_qtys()` TTL=300 — 同上 ⚠
   - `_get_zone_actual_revenue()` TTL=300 — 同上 ⚠
   - **问题**: TTL=300 对历史数据毫无意义（历史不会变），却导致频繁重新读取 parquet
   - **建议**: 历史数据 TTL 改为 3600 或 None（永不失效）；或用 `st.cache_resource` 持久缓存

2. **Parquet 重复读取**
   - `get_actual()` (第 67-77 行), `_get_zone_qtys()` (第 80-98 行), `_get_zone_actual_revenue()` (第 100-120 行) 各自独立调用 `pd.read_parquet(pq)` + 相同过滤逻辑
   - 三个函数的前 8 行代码（读 parquet → 过滤 CSL → 去 partial/bundle → 遍历 match_id → 日期匹配）完全重复
   - 影响：Tab2 渲染一场比赛时触发 3 次独立的 parquet 读取
   - **建议**: 抽取 `_get_csl_parquet() -> pd.DataFrame` 共用，或一次读取后传入各函数

3. **Matplotlib vs HTML/CSS 图表性能**
   - Matplotlib: `render_season_chart()` (第 773-798 行) 和 H2 瀑布图 (第 1099-1124 行) → 每次渲染创建 Figure
   - HTML 条形图: `render_mae_chart()` (第 631-655 行) → 纯 HTML/CSS 渲染，无后端开销 ✓
   - **对比**: MAE 条形图用 HTML 渲染是正确选择；折线图用 Matplotlib 合理（HTML/CSS 折线图复杂度高）
   - **建议**: 为 Matplotlib 图表增加 `@st.cache_data` 缓存（按数据哈希），避免重复渲染

4. **座位图 SVG 性能** (`app_v8.py:624`)
   - `render_gongti_seating()` 每次调用生成完整 SVG（含多边形坐标计算）
   - 嵌入在 `st.components.v1.html()` 中，无缓存
   - 影响：每次切换 Tab 或参数变化时重新生成 SVG，约 50-100ms
   - **建议**: 如果座位图不随比赛变化，预生成 SVG 并缓存；或使用 `st.cache_data`

5. **`build_standings_2026()` 无缓存** (`app_v8.py:123-142`)
   - 每次 `main()` 调用重新遍历 `all_matches` 计算积分榜
   - 影响：数据不变但每次重新遍历约 240 场比赛
   - **建议**: 增加 `@st.cache_data` 或直接在 `load_csl_data()` 中预计算

### 维度: 移动端/响应式
**评级:** ⭐ 差

**发现:**

1. **零移动端 CSS 适配**
   - 整个 `style.css` (353 行) 中无任何 `@media` 查询
   - 无 `max-width`、`overflow-x`、`viewport` 设置
   - 影响：在手机浏览器上打开时完全不可用

2. **KPI 卡片在移动端必然断裂** (`app_v8.py:205-223`)
   - `st.columns(4)` 两行共 8 列 → 小屏上每个列宽度 < 80px，卡片内容溢出
   - **建议**: `@media (max-width: 768px)` 下 KPI 卡片改为 2 列或纵向堆叠

3. **Tab 导航在小屏上的可用性**
   - 6 个 Tab 标签在 375px 宽度下必然溢出
   - Streamlit 原生 Tab 无横向滚动 → 超出部分被裁切
   - **建议**: CSS `@media` 下减小 Tab padding 和字体，或使用 selectbox 切换

4. **表格无横向滚动**
   - H2 策略表 8 列、对手分析表 13 列 → 小屏幕无法显示
   - `table { }` CSS 无 `overflow-x: auto` 或 `display: block` 包裹
   - **建议**: 为 `.compact-table`, `.history-table` 添加 `display: block; overflow-x: auto; white-space: nowrap` 包裹容器

5. **Matplotlib 图表 `figsize` 硬编码**
   - `figsize=(8, 2.5)` (第 782 行), `figsize=(5, 3.5)` (第 1099 行) → 不随容器宽度自适应
   - **建议**: 使用 `st.columns` 的宽度动态计算，或设置 `figsize` 为比例值

---

## 优化路线图

### P0 - 必须修复（影响数据正确性和用户体验底线）

| # | 问题 | 位置 | 方案 | 工作量 |
|---|------|------|------|--------|
| P0-1 | `pred_args` 重复构建 3 次 | L612-616, L678-684, L966-971 | 抽取 `build_pred_args(m, ctx) -> dict` | 30min |
| P0-2 | Tab2 策略卡片内联复制 `render_strategy_card()` | L687-718 vs L321-359 | Tab2 直接调用 `render_strategy_card(r_h, pred_args)` | 15min |
| P0-3 | `render_opponent_analysis()` 内部重新调用 `load_csl_data()` | L841 | 接收 `all_matches` 参数，复用 main() 结果 | 10min |
| P0-4 | 德比判断硬编码 `"上海申花", "山东泰山"` | L160, L507, L679, L967 | 统一使用 `DERBY_RIVALS` | 5min |
| P0-5 | `render_h2_strategy()` 绕过缓存直接 new optimizer | L958 | 改用 `get_optimizer()` | 5min |

### P1 - 建议修复（提升代码质量和可维护性）

| # | 问题 | 位置 | 方案 | 工作量 |
|---|------|------|------|--------|
| P1-1 | 规则 Pill 条件判断重复 `build_rule_labels()` | L334-343, L695-703 | 抽取共享函数 | 20min |
| P1-2 | 定价表 HTML 构建重复 3 次 | L361-399, L433-480, L721-766 | 抽取 `render_price_table()` 通用渲染器 | 1h |
| P1-3 | Parquet 读取重复 3 次(相同前8行) | L67-77, L82-98, L104-120 | 抽取 `_get_csl_parquet()` | 30min |
| P1-4 | 硬编码 What-If 乘数 0.80/1.15 | L412-413 | 从 `MULTIPLIERS` 导入或定义为命名常量 | 10min |
| P1-5 | H2 瀑布图数据硬编码 | L1104-1107 | 从 `summary` 计算或 JSON 存储 | 20min |
| P1-6 | 零加载态/错误恢复 | 全局 | 加 `st.spinner()`, 错误态加重试按钮 | 30min |
| P1-7 | 全局 `table {}` CSS 污染 | style.css L67-92 | 限定为 `.history-table, .compact-table` | 10min |
| P1-8 | Tab4 删除冗余内部导入 | L839-841 | 删除重复 import | 5min |

### P2 - 锦上添花（提升体验和健壮性）

| # | 问题 | 位置 | 方案 | 工作量 |
|---|------|------|------|--------|
| P2-1 | 移动端响应式适配 | style.css 全文件 | 添加 `@media (max-width: 768px)` 断点 | 1.5h |
| P2-2 | What-If 增加业务场景预设 | L405-413 | 预设从 `MULTIPLIERS` 导入，含 6-8 个语义场景 | 30min |
| P2-3 | Tab1 座位图独立或可折叠 | L623-624 | 放入 expander 或独立 Tab | 15min |
| P2-4 | Matplotlib 图表缓存 | L773-798, L1099-1124 | `@st.cache_data` 按数据哈希缓存 | 15min |
| P2-5 | 历史定价顶部锚点导航 | L657-660 | 日期快选锚点栏 | 20min |
| P2-6 | Tab5 积分榜顶部赛季环 | L1185-1234 | 增加进度环/摘要 KPI | 30min |
| P2-7 | CSS 单字母类名命名空间化 | style.css L214-223 | `.W` → `.result-W` | 10min |
| P2-8 | TTL=300 改为长期缓存 | L67, L79, L100 | 历史数据改为 TTL=3600 或 None | 5min |

---

## 附录: 代码质量指标

- **总行数**: 1354 (app_v8.py) + 353 (style.css) = 1707
- **函数数**: 26 (app_v8.py)
- **重复代码块数**: 4 组核心重复 (pred_args ×3, strategy_card ×2, rule_labels ×2, pricing_table ×3)
- **硬编码常数量**: 12+ 处
  - 对手集合: `{"上海申花", "山东泰山"}` ×4
  - What-If 乘数: 0.80, 1.15
  - H2 瀑布图值: [4591, -650, -200, -348, 3935]
  - Parquet 路径拼接: `ROOT / "data/processed/all_unified.parquet"` ×4
  - Matplotlib figsize: (8, 2.5), (5, 3.5)
  - 收入权重: `revenue_weight=0.6` ×2 (L55, L958)
  - 分红绿阈值: `abs(dp) > 1`, `dp > 0.5`, `dp < -0.5`
- **非缓存数据加载调用数**: 1 (L841 `load_csl_data()` 在 `render_opponent_analysis()` 中)
- **Streamlit widget 总数**: 约 20 个 (4 radio, 6 slider, 1 toggle, 6+ columns, 1 html 组件)
