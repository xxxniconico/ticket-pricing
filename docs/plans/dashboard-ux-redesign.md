# 国安票务看板 UI/UX 重构 — Cursor 任务单

> **版本**: V8 重构  
> **目标**: 从"模型输出展示器"升级为"定价决策工作台"  
> **设计系统**: Linear 暗色风格 · 中国金融颜色惯例  
> **Streamlit**: 1.57.0  
> **创建**: 2026-05-31

---

## 设计规范（铁律）

### 颜色

```css
背景: #0c0d0f
卡片: rgba(255,255,255,0.02)
卡片边框: rgba(255,255,255,0.06)
卡片悬停: rgba(255,255,255,0.03)
主文字: #d0d6e0
标题: #f7f8f8
次级文字: #8a8f98
辅助文字: #62666d
涨/赢/增: #ff6b6b
跌/输/减: #51cf66
中性/平: #f0c040
强调绿: #c2ef4e
```

### 排版

```css
字体: 'Inter', system-ui, -apple-system, sans-serif
等宽: 'JetBrains Mono', ui-monospace, monospace
标题字重: 510
正文字重: 400
圆角: 6px
间距单位: 6px
```

### 禁止项

- ❌ st.dataframe / st.table / pd.to_html
- ❌ Google Fonts（fonts.googleapis.com）
- ❌ 白色背景组件
- ❌ SVG 元素重叠
- ❌ read_file 输出做 write_file 输入（行号污染）
- ✅ 手写 HTML `<table class="xxx">` + CSS
- ✅ 所有预测标注"情景推演未经验证"

### 文件编辑规则

- 用 **patch 工具** 做精确替换，不用 execute_code 的 read_file → write_file
- 新建文件用 write_file
- **不要改 src/ 下的核心逻辑文件**（rule_engine.py、dynamic_optimizer.py、pricing_v5.py、classify.py、csl_context.py、data_feeds.py、calibrate.py）
- 可以 import 它们，不要改它们

---

## Phase 1: 文件拆分与架构重构

### Task 1.1: 提取 CSS 到独立文件

**文件**: 新建 `dashboard/style.css`

**内容**: 将 app.py L27-L100 的 `<style>` 块内容全部移到 style.css，包括：
- `.stApp` 背景
- 所有 typography（h1/h2/h3/h4）
- `.stMetric` 样式
- `table` / `table.compact-table` / `table.history-table` 样式
- `.price-tag` / `.card-row` / `.season-row` 样式
- `.state-bar` / `.rule-line` 样式
- `.W/.D/.L/.pts/.rank-up/.rank-down/.muted` 颜色类
- 滚动条样式

**app.py 加载方式**:
```python
def load_css():
    css_path = Path(__file__).parent / "style.css"
    with open(css_path) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
```

在 `main()` 开头调用 `load_css()`。

**验收**: 看板启动后视觉与当前完全一致，无样式丢失。

---

### Task 1.2: 提取组件文件

创建 `dashboard/components/` 目录，每个独立渲染函数一个文件：

| 文件 | 从 app.py 提取 | 说明 |
|------|---------------|------|
| `components/__init__.py` | — | 空文件 |
| `components/kpi_cards.py` | — | **新建**：顶部 KPI 摘要卡片行 |
| `components/rules_chain.py` | L265-L340 | 命中规则计算链渲染 |
| `components/pricing_table.py` | L342-L558 | 定价建议区（含策略卡片+定价表+档位详情） |
| `components/season_review.py` | L570-L589 | 赛季回望表格 |
| `components/history_pricing.py` | L591-L682 | 历史定价建议 |
| `components/season_overview.py` | L685-L704 | 赛季全览 |
| `components/seating_chart.py` | L115-L191 | 工体鸟瞰图 SVG |

**app.py 改为**: 只保留数据加载、`main()` 流程编排、调用组件函数。删除所有内联渲染代码。

**验收**: 看板功能完全不变，代码从 704 行缩减到 ~200 行。

---

### Task 1.3: Tab 化分区

在 `main()` 中用 `st.tabs()` 创建 4 个标签页：

```python
tabs = st.tabs(["📊 下一场预测", "📋 历史定价", "📈 赛季全景", "🔍 对手分析"])
```

| Tab | 内容 | 
|-----|------|
| 下一场预测 | KPI 摘要行 → 比赛信息 → 规则计算链 → 定价建议表（左+右两栏） |
| 历史定价 | 已赛主场定价回顾（每场 st.expander 折叠） |
| 赛季全景 | 预测vs实际趋势迷你图 + 赛季回望表 + 全览表 |
| 对手分析 | 对手分级表 + 基值矩阵 + 校准因子状态 |

**当前结构映射**: 把原来的 5 个平铺区域分配到 4 个 Tab 中。

**验收**: Tab 切换正常，每个 Tab 内容独立加载不串数据。

---

## Phase 2: 决策摘要卡片 (KPI Cards)

### Task 2.1: 顶部 KPI 摘要行

**文件**: `dashboard/components/kpi_cards.py`

在导航标题下方（Tab 之上），用 `st.columns(5)` 展示 5 个关键指标卡片：

```
┌──────────────┬──────────────┬──────────────┬──────────────┬──────────────┐
│  下一场对手   │  赛季 MAE    │  收入底线    │  已赛主场    │  当前分级    │
│  vs 天津津门虎 │  1,035 张   │  93.2%      │  7/15 场    │  A 级       │
│  06-14 周六   │  MAPE 10.9% │  ≥ ¥280万   │  进度条      │  定价 A-minus│
└──────────────┴──────────────┴──────────────┴──────────────┴──────────────┘
```

**实现细节**:
- 使用手写 HTML div + inline CSS（不用 st.metric，它会在暗色背景上出白色底）
- 每个卡片：`background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px 14px`
- 顶部小标签：`font-size: 0.62rem; color: #62666d; text-transform: uppercase; letter-spacing: 0.04em`
- 主数值：`font-size: 1.2rem; font-weight: 590; color: #f7f8f8`
- 副文字：`font-size: 0.68rem; color: #8a8f98`

**数据来源**:
- 下一场对手：`csl_context.load_csl_data()` → 找 `is_home=True` 且 `completed=False` 的第一场
- 赛季 MAE：从已赛主场数据计算 `mean(|pred - actual|)`
- 收入底线：`min(optimized_revenue / base_revenue, 1.0)` 取最近一场
- 已赛主场：`len([m for m in guoan_matches if m['is_home'] and m['completed']])`
- 当前分级：`classify_opponent_tier(opp)` 取下一场对手

**验收**: 5 秒测试 — 不看解释能说出"下一场对谁、模型误差多少、收入达标否"。

---

## Phase 3: What-If 沙盒

### Task 3.1：价格滑块交互区

**文件**: 新建 `dashboard/components/what_if.py`

在"下一场预测" Tab 的定价表上方或右侧，新增一个可折叠的 **What-If 沙盒**：

```python
with st.expander("🔬 What-If 沙盒 — 手动调价测试", expanded=False):
    col1, col2 = st.columns(2)
    with col1:
        t1_price = st.slider("T1 起售价", 100, 400, int(current_t1_price), 10)
        t2_price = st.slider("T2 价格", 100, 350, int(current_t2_price), 10)
        t3_price = st.slider("T3 价格", 80, 300, int(current_t3_price), 10)
    with col2:
        t4_price = st.slider("T4 价格", 60, 250, int(current_t4_price), 10)
        t5_price = st.slider("T5 价格", 50, 200, int(current_t5_price), 10)
        t6_price = st.slider("T6 价格", 40, 180, int(current_t6_price), 10)
```

**实时计算**: 每次滑块拖动，即时重算：
1. 各档位预测销量（用弹性系数反推）
2. 总收入 = Σ 价格 × 预测销量
3. 总上座 = Σ 预测销量

**对比展示**: 用表格显示"基准 vs 优化 vs 手动"三列：
```
| 档位 | 基准价 | 基准量 | 优化价 | 优化量 | 手动价 | 手动量 | 手动Δ收入 |
```

**边界约束检查**: 
- 档位间距 < 5% → 红色警告
- T3-T4 间距 < 18% → 黄色警告
- 总收入低于基准 × 93% → 红色警告

**验收**: 拖动 T1 滑块，下面表格即时更新所有档位的量和收入。

---

### Task 3.2: 情景切换器

在 What-If 沙盒顶部添加情景快捷切换：

```python
scenario = st.radio("预设情景", ["基准（模型推荐）", "悲观（上座-20%）", "乐观（上座+15%）", "自定义"],
                    horizontal=True)
```

**悲观情景**: 所有档位预测量 × 0.8，但收入权重自动切到"上座优先"
**乐观情景**: 所有档位预测量 × 1.15，收入权重切到"收入优先"

**验收**: 点击"悲观"，所有数字变绿色（下行），收入预估显著降低。

---

## Phase 4: 不确定性可视化

### Task 4.1: 置信区间展示

**文件**: `dashboard/components/rules_chain.py` 底部

在规则计算链输出后，用 HTML/CSS 绘制置信区间条：

```python
# 用历史 MAE 反推
mae = 1035  # 从已赛数据计算
pred = 14000
ci_low = pred - mae * 1.5   # ~90% 置信下界
ci_high = pred + mae * 1.5  # ~90% 置信上界

pct_low = ci_low / 20000 * 100
pct_pred = pred / 20000 * 100
pct_high = ci_high / 20000 * 100
```

HTML 结构：
```html
<div class="confidence-bar">
  <div>预测上座: {pred:,} 张</div>
  <div class="bar-track">
    <div class="bar-ci" style="left:{pct_low}%;width:{pct_high-pct_low}%"></div>
    <div class="bar-marker" style="left:{pct_pred}%"></div>
  </div>
  <div class="ci-labels">
    <span>悲观 {ci_low:,}</span>
    <span>乐观 {ci_high:,}</span>
  </div>
  <div class="ci-note">基于赛季 MAE {mae:,} 张 · 80% 置信区间</div>
</div>
```

CSS:
```css
.confidence-bar { margin: 10px 0; }
.bar-track { position: relative; height: 6px; background: rgba(255,255,255,0.06); border-radius: 3px; margin: 6px 0; }
.bar-ci { position: absolute; height: 6px; background: rgba(255,255,255,0.15); border-radius: 3px; }
.bar-marker { position: absolute; width: 3px; height: 14px; background: #ff6b6b; border-radius: 2px; top: -4px; }
```

**验收**: 置信区间条清晰展示预测的不确定性范围，不会是"精确到个位"的假象。

---

### Task 4.2: 收入预测区间

在定价表底部（总计行下方），添加收入预测区间：

```
预计收入: ¥412万
├─ 悲观（上座-20%）: ¥350万
├─ 基准: ¥412万  
└─ 乐观（上座+15%）: ¥465万
```

**验收**: 三个数字用不同透明度展示，乐观用红色、悲观用绿色。

---

## Phase 5: 视觉提升

### Task 5.1: 规则 Pill 标签化

**文件**: `dashboard/components/rules_chain.py`

将当前 L265-L340 的规则链改为横向 pill 排列：

```html
<div style="display:flex;gap:6px;flex-wrap:wrap">
  <span class="rule-pill rule-base">基值 S级 14,000张</span>
  <span class="rule-pill rule-up">德比 ×1.25</span>
  <span class="rule-pill rule-up">周六 ×1.05</span>
  <span class="rule-pill rule-down">工作日 ×0.90</span>
</div>
```

CSS:
```css
.rule-pill { display: inline-block; padding: 3px 10px; border-radius: 12px; 
             font-size: 0.72rem; font-weight: 510; font-family: 'JetBrains Mono', ui-monospace; }
.rule-base { background: rgba(255,255,255,0.04); color: #8a8f98; border: 1px solid rgba(255,255,255,0.08); }
.rule-up { background: rgba(255,107,107,0.08); color: #ff6b6b; border: 1px solid rgba(255,107,107,0.15); }
.rule-down { background: rgba(81,207,102,0.08); color: #51cf66; border: 1px solid rgba(81,207,102,0.15); }
```

**验收**: 规则链从竖排文字列表变成横向 pill 流，一行内可见所有触发规则。

---

### Task 5.2: 预测 vs 实际迷你趋势图

**文件**: `dashboard/components/season_overview.py`

用 matplotlib 在暗色主题下画预测 vs 实际对比折线图：

```python
fig, ax = plt.subplots(figsize=(8, 2.5))
fig.patch.set_facecolor('#0c0d0f')
ax.set_facecolor('#0c0d0f')
# 两条线：预测（虚线 #ff6b6b）、实际（实线 #51cf66）
# X 轴：比赛日期，Y 轴：上座人数
# 图例在右上角
ax.legend(loc='upper right', facecolor='#1a1d22', edgecolor='#2a2d33', labelcolor='#8a8f98')
```

关键配置：
- 坐标轴颜色: `#2a2d33`
- 刻度标签颜色: `#62666d`
- 网格: `alpha=0.05`, 白色
- 去掉顶部和右侧脊线

**验收**: 暗色折线图，预测红色虚线、实际绿色实线，一目了然。

---

### Task 5.3: 赛季主场进度条

在 KPI 卡片下方添加：

```html
<div style="margin:8px 0">
  <div style="display:flex;justify-content:space-between;font-size:0.65rem;color:#62666d">
    <span>赛季进度</span><span>7/15 主场</span>
  </div>
  <div style="height:3px;background:rgba(255,255,255,0.06);border-radius:2px;margin-top:4px">
    <div style="width:46.7%;height:3px;background:#ff6b6b;border-radius:2px"></div>
  </div>
</div>
```

**验收**: 细条进度条，Linear 风格。

---

### Task 5.4: 数据刷新时间戳

在页面标题右侧显示：

```python
col1, col2 = st.columns([6, 1])
with col1:
    st.markdown("<h1>国安票务动态定价</h1>", unsafe_allow_html=True)
with col2:
    st.caption(f"数据更新\n{last_update}")
```

其中 `last_update` 从 CSL JSON 的加载时间或文件修改时间获取。

**验收**: 右上角显示"数据更新 05-31 08:02"，不显眼但可见。

---

## Phase 6: 历史定价区改造

### Task 6.1: 历史定价折叠优化

**文件**: `dashboard/components/history_pricing.py`

- 每场已赛主场比赛包在一个 `st.expander` 中
- **默认只展开最近一场**，其余折叠
- Expander 标题格式：`R{轮次} {日期} vs {对手} — 预测 {pred} 实际 {actual} 误差 {ape}%`
- 标题颜色：APE < 10% 绿色，10-20% 黄色，>20% 红色

**验收**: 页面加载后只看到一排折叠条，仅最新一场展开。

---

### Task 6.2: 策略描述卡片化

当前每场比赛的策略描述是一大段文字（L634-L652）。改为结构化卡片：

```
┌─────────────────────────────────────────┐
│ 策略: 均衡优化（收入权重60% 上座40%）     │
│ 触发: 德比溢价 · 周六场                  │
│ ↑ 涨价: T5 T6（高价创收）               │
│ ↓ 降价: T1 T2（低价抢量）               │
│ 🔒 锁价: T3 T4                          │
│ 预期: 增收 +¥2.3万 · 上座 ↑2%           │
└─────────────────────────────────────────┘
```

**验收**: 策略信息不再是一大段文字，而是结构化小卡片。

---

### Task 6.3: 模型学习回路图

在"历史定价" Tab 顶部，添加 MAE 收敛趋势：

```
模型 MAE 收敛趋势
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
R3 申花  ████████████ +1,847  V3
R5 成都  ██████       -943    V4
R8 津门虎 ██████████   -1,612  V4.1
R10 英博 ██████████████ +2,103  V4.1
...
当前 MAE 1,035 | ↓ 改善趋势
```

用 HTML 水平柱状图，红色正误差、绿色负误差，标注模型版本。

**验收**: 一眼能看到模型在迭代中收敛，历史错误不是"失败"而是"学习过程"。

---

## 执行顺序

```
Phase 1 (基础重构)
  Task 1.1 → Task 1.2 → Task 1.3
    ↓
Phase 2 (KPI卡片)
  Task 2.1
    ↓
Phase 3 (What-If沙盒) ← 核心功能
  Task 3.1 → Task 3.2
    ↓
Phase 4 (不确定性)
  Task 4.1 → Task 4.2
    ↓
Phase 5 (视觉提升)
  Task 5.1 → Task 5.2 → Task 5.3 → Task 5.4
    ↓
Phase 6 (历史定价)
  Task 6.1 → Task 6.2 → Task 6.3
```

每个 Phase 完成后 **重启看板验证**，确认无回归再进入下一 Phase。

---

## 验收总清单

- [ ] `http://localhost:8504` 可访问，加载无报错
- [ ] 4 个 Tab 可正常切换
- [ ] 顶部 5 个 KPI 卡片数据正确
- [ ] 规则链为横向 pill 排列
- [ ] What-If 滑块拖动即时生效
- [ ] 置信区间条展示预测不确定性
- [ ] 历史定价默认仅展开最新一场
- [ ] 预测 vs 实际迷你趋势图正常渲染
- [ ] 赛季进度条显示正确
- [ ] 所有表格为手写 HTML（无 pd.to_html）
- [ ] 无 Google Fonts 引用
- [ ] 颜色规范：红涨绿跌
- [ ] 数据标注"情景推演未经验证"
