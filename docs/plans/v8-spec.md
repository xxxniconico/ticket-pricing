# 国安票务定价看板 V8 — 完整重写规格

## 任务

基于 `dashboard/app.py`（V7）重写一个新的 Streamlit 看板文件 `dashboard/app_v8.py`。

## 设计系统（铁律）

### 颜色
- 背景 `#0c0d0f` | 卡片 `rgba(255,255,255,0.02)` | 边框 `rgba(255,255,255,0.06)`
- 主文字 `#d0d6e0` | 标题 `#f7f8f8` | 次级 `#8a8f98` | 辅助 `#62666d`
- 涨/赢/增 `#ff6b6b` | 跌/输/减 `#51cf66` | 中性 `#f0c040` | 强调绿 `#c2ef4e`

### 排版
- 正文 `Inter, system-ui` | 等宽 `JetBrains Mono, ui-monospace`
- 标题字重 510 | 圆角 6px | 间距单位 6px

### 禁止
- st.dataframe / st.table / pd.to_html（用手写 HTML table + CSS class）
- Google Fonts
- 白色背景组件

## 架构要求

1. **CSS 拆分**: 所有 CSS 写入 `dashboard/style.css`，app_v8.py 用 `load_css()` 加载
2. **Tab 分区**: 4 个 Tab — "下一场预测" | "历史定价" | "赛季全景" | "对手分析"
3. **复用 src/ 模块**: import 路径和 API 完全不变，不改 src/ 下任何文件

## 必须包含的功能（对照 app.py V7）

### 全局
- ✅ 标题栏：`#排名 N分(扣X分) | 主场 W-D-L | 已赛N/30轮`
- ✅ 近5场 W/D/L 形态条
- ✅ 下一场是客场时自动切换到最近主场

### Tab 1: 下一场预测
- ✅ KPI 卡片行（5个）：下一场对手、赛季MAE、收入底线、已赛主场进度、对手分级
- ✅ 赛季主场进度条（细条）
- ✅ 近期赛果（最近3场 + 上下文影响标注 lost_bottom/heavy_home_loss/away_winless）
- ✅ 命中规则 Pill 标签（横向排列，红=溢价绿=衰减灰=中性）
- ✅ 累计乘数条 + EMA 校准标注
- ✅ 预测置信区间条（基于赛季 MAE，80% 区间）
- ✅ 策略摘要卡片（模式/触发规则/涨降价档位）
- ✅ 定价建议表（手写 HTML table：档位|基准价|优化价Δ%|预测量|场景收入|合计行）
- ✅ What-If 沙盒（st.expander 折叠）：6档价格滑块 + 基准/悲观/乐观预设 + 实时重算对比表 + 收入区间
- ✅ 预测标注"情景推演未经验证"

### Tab 2: 历史定价
- ✅ 模型 MAE 收敛趋势图（水平柱状图，红色正误差绿色负误差）
- ✅ 每场已赛主场比赛 st.expander 折叠，默认仅展开最新一场
- ✅ 每场 expander 标题：日期 vs 对手 | 预测值 实际值 | 误差 APE
- ✅ 每场内展开：策略摘要卡片 + 定价建议表（手写 HTML）

### Tab 3: 赛季全景
- ✅ matplotlib 暗色迷你折线图：预测（红色虚线）vs 实际（绿色实线）
- ✅ 赛季回望表（手写 HTML：日期|对手|预测|实际|误差|APE）
- ✅ 累积 MAE 指标

### Tab 4: 对手分析
- ✅ 对手分级矩阵表：级别|基值|校准因子|校准后
- ✅ 校准因子上色（>1.01红 <0.99绿）

## 技术细节

### 数据加载
```python
from src.csl_context import load_csl_data, get_guoan_matches, detect_ctx
# load_csl_data() 返回 (all_matches, rounds_dict, deductions)
# rounds_dict 是跨赛季的积分排名，作为 detect_ctx 的第三个参数
all_matches, rounds, deductions = load_csl_data()
guoan_matches = get_guoan_matches(all_matches)
guoan_matches = [m for m in guoan_matches if 'cfl_fixtures_api' in m.get('source','') or 'wikipedia' in m.get('source','')]
```

### 积分榜构建
```python
# 构建 2026-only 的 standings dict（用于显示排名和 opp_rank 检测）
standings = {}
ts = defaultdict(lambda: {"p":0,"w":0,"d":0,"l":0,"gf":0,"ga":0,"pts":0})
for m in sorted([x for x in all_matches if x['date'].startswith('2026')], key=lambda x: x['date']):
    if not m.get('completed'): continue
    # ... 积分计算 ...
standings[rnd] = {team: rank}
```

### detect_ctx
```python
ctx = detect_ctx(match, guoan_matches, rounds)  # 第三个参数是 rounds（跨赛季排名dict）
```

### DynamicPricingOptimizer
```python
from src.dynamic_optimizer import DynamicPricingOptimizer
opt = DynamicPricingOptimizer(revenue_weight=0.6)
r = opt.optimize(opponent, strategy='auto', derby=..., saturday=..., ...)
# r.tiers['T1'].base_price, .optimal_price, .base_qty, .predicted_qty, .revenue, .is_frozen
# r.total_revenue, r.base_revenue, r.total_attendance, r.base_attendance, r.revenue_weight, r.attendance_weight
```

### rule_engine
```python
from src.rule_engine import predict_calibrated, TIER_BASE, PENALTY_FLOOR, get_calibration
# TIER_BASE = {'S': 14000, 'A': 12000, 'B': 10400, 'C': 9700}
# PENALTY_FLOOR = 0.5
```

### classify
```python
from src.classify import classify_opponent_tier  # 返回 'S'|'A'|'B'|'C'
from src.pricing_v5 import ZONE_TIERS, classify_opponent, get_pricing_tier
# ZONE_TIERS = ['T1','T2','T3','T4','T5','T6']
# PT_LABELS = {"S_S":"S·德比定价","S_A":"A·标准定价","S_Aminus":"A·降价","S_B":"B·标准定价","S_C":"C·标准定价","S_Cminus":"C·降价"}
```

### 运行方式
```bash
cd ~/ticket-pricing && ~/.hermes/hermes-agent/venv/bin/streamlit run dashboard/app_v8.py --server.port 8506 --server.headless true
```

## 输出要求

- 单个文件 `dashboard/app_v8.py`，干净整洁，函数拆分清晰
- 独立 CSS 文件 `dashboard/style.css`
- 不改变 src/ 下任何现有文件
- 不改变 `dashboard/app.py`（V7 保持原样）
- 代码风格参照 app.py 的函数式写法（st.cache_data、render_xxx 函数、main() 编排）
- ✅ 用手写 HTML table 替代 pd.to_html
