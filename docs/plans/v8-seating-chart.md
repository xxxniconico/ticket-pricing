# V8 座区图 + 逐区定价

## 数据
- `data/processed/zone_tier_map.json`: T1-T6 分区定义 + 2025基准价 + 弹性系数
- V8 的 `render_pricing_table` 已产生 `r.tiers[zt].base_price` 和 `.optimal_price`

## 实现

### 1. 新增函数 `render_seating_chart(r)` 
放在 `dashboard/app_v8.py` 的 `render_pricing_table` 附近。

渲染工体简化鸟瞰 SVG：
- 椭圆形体育场，中间绿色草坪
- 按 T1-T6 分色块，每个 section 一个矩形区块
- 颜色方案：
  - T1（四层低价）: #4a9e6e
  - T2（四层中价）: #5b9bd5
  - T3（一层边+二层+四层中）: #e8923a
  - T4（四层中间）: #e8c547
  - T5（一层边+二层好位）: #d4739a
  - T6（一层死忠/商务）: #b8c45a

### 2. 布局
- 三层同心椭圆环（一层内环 → 二层中环 → 四层外环）
- 每层分成 4 个看台（东西南北），section 按编号排列
- 每个色块标注 section 编号（如 101, 102）
- 右侧图例显示 T1-T6 名称 + 基准价 → 优化价

### 3. 叠加定价信息
在每个 zone 区域旁边标注：
- 基准价 → 优化价
- 涨幅百分比（红涨绿跌）

### 4. 集成
在 `render_pricing_table(r)` 调用之后、`render_what_if` 之前，调用 `render_seating_chart(r)`。

或者放在定价表右侧，形成左右两栏布局。

## 技术约束
- 纯 SVG + HTML，不依赖外部库
- 暗色背景适配
- 不改 src/ 文件
- 完整的 section 覆盖（101-130, 208-237, 308-338）
