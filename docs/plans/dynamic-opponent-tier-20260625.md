# 动态对手分级体系 — 执行计划

> 分工：Hermes/Suli=方案审查 / Resonix=编码+测试 / Claude Code=架构兜底
> 目标：静态 KMeans K=4 集合 → 双维度连续评分（ST实力 + AP吸引力）→ 离散档位映射
> 对接：对外仍输出 S/A/B/C，rule_engine / pricing_v5 无需改动
> 日期：2026-06-25

---

## 背景与目标

### 当前痛点（`src/classify.py`）

1. **静态硬编码集合**：S/A/B/C 四档赛季前确定，赛季中永不变化
2. **手动 patch 成本高**：海港两年内 B→A→B→A 反复调整，每次都要改 `classify.py` + `rule_engine.py` + `pricing_v5.py` 三个文件
3. **升班马零数据冷启动**：辽宁/重庆归 C 级纯保守假设，无法根据首月表现调整
4. **不响应当赛季表现**：山东 2026 战绩异常差仍按 A 级定价
5. **S 档样本不足**：仅申花 1 队，弹性 n=4 置信度低
6. **A 档内部差异大**：成都/山东/天津/海港不应同档

### 设计原则

1. **连续评分 + 离散映射**：内部 0-100 评分，对外仍输出 S/A/B/C
2. **双维度分离**：实力分（ST）影响基值，吸引力分（AP）影响档位+溢价
3. **赛季前锚定 + 月度平滑更新**：避免单场震荡
4. **保留德比硬编码**：申花/山东德比地位不参与动态计算
5. **兼容现有系统**：`rule_engine.predict()` / `pricing_v5.get_pricing_tier()` 签名不变

---

## 总体架构

```
数据层                      评分层                     分级层               业务层
──────────               ──────────                ─────────           ─────────
csl_final_production     compute_elo()             ST (0-100)          classify_opponent_tier()
  _ready.json         →  compute_strength()    →   AP (0-100)       →   ↓ 兼容
standings_*_by_round     compute_appeal()          effective_tier        rule_engine.predict()
all_unified.parquet      get_effective_tier()      (S/A/B/C)             pricing_v5.get_pricing_tier()
                                                                       csl_context.detect_ctx()
```

**数据流**：
```
CSL 比赛结果 ──► ELO 更新 ──► ST 实力分
                                      ↓
历史票务 + 德比关系 ──► AP 吸引力分 ──► effective_tier (S/A/B/C)
                                      ↓
                              替代 classify_opponent_tier()
```

---

## Phase 1: 基建 — 评分引擎 + 销速验证 🔧

**目标**：建立 ELO + ST + AP 评分模块（不对称阈值）+ 销速交叉验证 + 赛中修正 + 赛季初重标，离线生成历史评分，不改业务逻辑
**验收**：
- 所有中超队 2026-06-25 的 ST/AP/档位输出合理
- 申花 ST>80、山东 ST>55、升班马 ST<45
- **3 个错配案例全部纠正**：武汉 B→C、海港 A→B、海牛 C→B
- **武汉 6/27 销速预警触发**（deviation ≈ 39%）

### Task 1.1 — ELO 评分引擎

**文件**：`src/opponent_rating.py`（新建）

**做什么**：实现 ELO rating 计算，从 2023 赛季开始逐场更新，输出每队每轮后的 ELO

**函数签名**：
```python
def compute_elo_history(matches: list[dict]) -> pd.DataFrame:
    """从 2023 起逐场更新 ELO，返回 (date, team, elo) 时间序列。

    Args:
        matches: load_csl_data() 返回的 matches 列表

    Returns:
        DataFrame columns: [date, round, team, elo_before, elo_after, opponent, result]
    """

def get_elo_at(team: str, date: str, elo_history: pd.DataFrame) -> float:
    """查询某队在指定日期前的最新 ELO。"""

def _elo_update(rating_a: float, rating_b: float,
                score_a: float, k: int = 20,
                home_adv: float = 65.0) -> tuple[float, float]:
    """单场 ELO 更新。

    score_a: 1=胜, 0.5=平, 0=负
    home_adv: 主场优势（加到主队 rating 上）
    """
```

**ELO 参数**：
- K-factor：常规 K=20；赛季前 5 轮 K=30（快速收敛）；赛季末 5 轮 K=15（防噪声）
- 主场优势：+65 分
- 初始值（2023 赛季初）：
  - 上赛季冠军 1700、亚军 1650、季军 1600
  - 4-6 名 1550、7-12 名 1500、13-15 名 1450
  - 升班马 1400（2023 赛季的升班马）
  - 2024/2026 新升班马：1400

**公式**：
```python
expected_a = 1 / (1 + 10 ** ((rating_b - (rating_a + home_adv)) / 400))
rating_a_new = rating_a + k * (score_a - expected_a)
rating_b_new = rating_b + k * ((1 - score_a) - (1 - expected_a))
```

**输出文件**：`data/processed/elo_history.parquet`（列：date, round, team, elo_before, elo_after, opponent, result）

**验收**：
- [ ] 申花 2026-06-25 ELO > 1650
- [ ] 升班马（辽宁/重庆）2026-06-25 ELO < 1500
- [ ] 单场 ELO 变化绝对值 ≤ 30
- [ ] 全联赛 ELO 均值约 1500（守恒性）

---

### Task 1.2 — ST 实力分计算

**文件**：`src/opponent_rating.py`（同一文件）

**做什么**：基于 ELO + 当季 PPG + 近 5 场 + 进球差，计算 0-100 的实力分

**函数签名**：
```python
def compute_strength(team: str, date: str,
                     elo_history: pd.DataFrame,
                     standings_by_round: dict,
                     matches: list[dict]) -> float:
    """返回 0-100 的实力分 ST。"""

def _normalize_to_0_100(value: float,
                        min_val: float, max_val: float) -> float:
    """线性归一化到 [0, 100]，超出范围 clip。"""
```

**ST 计算公式**：
```
ST_raw = 0.40 × norm(ELO, 1400, 1700)        # ELO 归一化到 1400-1700 → 0-100
       + 0.30 × norm(PPG, 0.5, 2.0)          # 当季每场得分（提升权重）
       + 0.20 × norm(L5_PPG, 0.0, 2.5)       # 近 5 场 PPG（捕获状态）
       + 0.10 × norm(GD_per, -1.5, 1.5)      # 每场净胜球（降权，噪声大）

ST = clip(ST_raw, 0, 100)
```

**权重调整说明**（vs 原方案）：
- PPG 0.25 → 0.30：当季战绩是实力最直接信号，权重提升
- GD_per 0.15 → 0.10：净胜球噪声大（一场 0-5 会扭曲），降权

**特殊处理**：
- 赛季未开始（played=0）：ST = 50 + 0.3 × (ELO - 1500) / 10（仅用 ELO）
- 近 5 场不足 5 场：用已有场次，分母仍按 5（保守）
- 升班马首场：ST = 40（保守 C 级上限）

**验收**：
- [ ] 申花 2026-06-25 ST > 75
- [ ] 山东 2026-06-25 ST 在 55-70 之间（战绩差但 ELO 底子在）
- [ ] 武汉 2026-06-25 ST < 35（排名 16，降级区）
- [ ] 辽宁铁人 2026-06-25 ST < 45
- [ ] 国安自身 ST 不计算（只评对手）

---

### Task 1.3 — AP 吸引力分计算

**文件**：`src/opponent_rating.py`（同一文件）

**做什么**：基于历史对国安主场上座 + 德比关系 + **当季实际票房** + 话题度，计算 0-100 吸引力分

**关键改进**：新增 `CUR_YEAR_ATT_ratio` 子项，直接响应当季需求变化（武汉案例的核心缺口）

**函数签名**：
```python
def compute_appeal(opponent: str, match_date: str,
                   guoan_home_history: pd.DataFrame,
                   cur_year_attendance: float | None = None,
                   hist_avg_attendance: float | None = None,
                   last_h2h: dict | None = None,
                   topic_tag: str | None = None) -> float:
    """返回 0-100 的吸引力分 AP。"""

# 德比关系硬编码（保留 classify.py 的 DERBY_RIVALS 思路）
DERBY_BONUS = {
    "上海申花": 30,    # S 级德比
    "山东泰山": 20,    # A 级德比
    "天津津门虎": 10,  # 地理近邻
}

# 话题度标签（人工维护，可选）
TOPIC_SCORES = {
    "title_race": 15,    # 争冠对手
    "relegation": 8,     # 保级对手（有求生欲望）
    "new_promoted": 5,   # 升班马首秀
    "star_player": 10,   # 知名球星来访（如奥斯卡回国）
    "default": 0,
}
```

**AP 计算公式**（新增 CUR_YEAR_ATT_ratio）：
```
AP_raw = 0.40 × HIST_ATT_percentile           # 2023-2025 对国安主场上座百分位（降权）
       + 0.25 × DERBY_bonus                    # 德比加成
       + 0.20 × CUR_YEAR_ATT_ratio             # 当年实际票房 / 历史均值（新增）
       + 0.15 × TOPIC_score                    # 话题度

AP = clip(AP_raw, 0, 100)
```

**权重调整说明**（vs 原方案）：
- HIST_ATT_percentile 0.45 → 0.40：历史权重大幅下降，让位给当季信号
- 新增 CUR_YEAR_ATT_ratio 0.20：直接捕获当年需求变化（武汉 2025 降级、海港 2026 下滑）
- 移除 last_h2h 0.15：与 HIST_ATT 信号重叠，简化

**CUR_YEAR_ATT_ratio 计算**：
```python
def _cur_year_att_ratio(opponent: str, match_date: str,
                        guoan_home_history: pd.DataFrame,
                        hist_avg: float | None) -> float:
    """当年已赛对国安主场上座 / 历史均值。

    - 无当年数据（如赛季首场）→ 返回 1.0（中性）
    - ratio < 0.85 → 当年吸引力下降（武汉 2025: 9032/11300 ≈ 0.80）
    - ratio > 1.15 → 当年吸引力上升
    - clip [0.5, 1.5] 防极端值
    """
```

**历史上座百分位计算**：
```python
def _attendance_percentile(opponent: str,
                           guoan_home_history: pd.DataFrame) -> float:
    """返回对手在国安主场上座中的百分位排名 (0-100)。

    - 去情境化：用实际值 / 该场预测值的 ratio，消除对手级别本身的影响
    - 取该对手所有历史场次的均值
    - 在全联赛对手中计算百分位
    """
```

**冷启动（升班马）**：
- 历史上座为空 → 用 2023-2025 C 级对手的均值（约 30 分）
- 当年无主场上座 → CUR_YEAR_ATT_ratio = 1.0（中性）
- 话题度 `new_promoted` +5 加成

**3 个错配案例验证**（来自武汉偏差分析）：

| 对手 | HIST_ATT_pct | DERBY | CUR_YEAR_ratio | TOPIC | AP 估算 | 旧档 | 新档 |
|------|:----------:|:-----:|:-------------:|:-----:|:------:|:--:|:--:|
| 武汉三镇 | 50 | 0 | 1.0（首场） | 保级+8 | **31.2** | B | **C** ✅ |
| 上海海港 | 75 | 0 | 0.74（40.5%/54.5%） | 争冠+15 | **40.3** | A | **B** ✅ |
| 青岛海牛 | 45 | 0 | 1.1（35.8% 高于 C 档均） | default | **41.5** | C | **B** ✅ |

**验收**：
- [ ] 申花 AP > 85（德比 + 历史上座顶）
- [ ] 山东 AP > 70（德比）
- [ ] 天津 AP > 65（地理近邻 + 历史上座）
- [ ] 武汉 AP < 35（降级区 + 当年票房下滑）
- [ ] 海港 AP 在 35-50 之间（A 档历史但当年下滑）
- [ ] 辽宁/重庆 AP < 40（冷启动）

---

### Task 1.4 — 双维度融合 → effective_tier（不对称阈值·倾向降级）

**文件**：`src/opponent_rating.py`（同一文件）

**做什么**：ST + AP 融合输出 S/A/B/C，**不对称阈值：下调易、上调难**

**核心设计原则**（来自武汉偏差分析）：
> "有分歧时倾向降级——低价风险远小于高价空座风险"

高估（B 档定价但实际 C 档需求）→ 空座损失大
低估（C 档定价但实际 B 档需求）→ 少赚但无空座

**函数签名**：
```python
# 硬锁档位（不参与动态计算）
FROZEN_TIERS = {
    "上海申花": "S",   # 德比永远 S
    "山东泰山": "A",   # 德比永远 A（但允许 ST/AP 影响乘数）
}

def get_effective_tier(opponent: str, match_date: str,
                       elo_history: pd.DataFrame = None,
                       standings_by_round: dict = None,
                       matches: list = None,
                       guoan_home_history: pd.DataFrame = None,
                       last_h2h: dict = None,
                       topic_tag: str = None,
                       soft_boundary: bool = True) -> str:
    """动态计算对手档位，返回 'S'/'A'/'B'/'C'。

    签名设计：可选参数全部 None 时，自动加载缓存数据。
    """

def get_opponent_scorecard(opponent: str, match_date: str) -> dict:
    """调试用：返回完整评分卡。

    Returns:
        {
            'opponent': str,
            'elo': float,
            'ST': float,
            'AP': float,
            'tier': str,
            'soft_boundary': bool,   # 是否在阈值±3区间
            'alt_tier': str | None,  # 软边界内的候选档位
            'components': {...}      # 各子项明细
        }
    """
```

**映射规则**（不对称阈值）：
```python
if opponent in FROZEN_TIERS:
    return FROZEN_TIERS[opponent]

# 下调易：任一维度低于下限即降（倾向降级）
if ST < 35 or AP < 35:   return "C"   # 任一维度极低 → C
if ST < 50 or AP < 50:   return "B"   # 任一维度偏低 → B

# 上调难：双维度都需达标才升（保守）
if ST >= 70 and AP >= 65: return "A"  # 双维度都高才升 A
if ST >= 80 and AP >= 80: return "S"  # 实际只有申花，硬锁

return "B"  # 默认 B
```

**阈值对照表**：

| 档位 | 下调阈值（易） | 上调阈值（难） | 说明 |
|------|:----------:|:----------:|------|
| C | ST<35 或 AP<35 | — | 任一维度极低即降 |
| B | ST<50 或 AP<50 | — | 任一维度偏低即降 |
| A | — | ST≥70 **且** AP≥65 | 双维度都需达标 |
| S | — | ST≥80 **且** AP≥80 | 仅申花，硬锁 |

**软边界机制**（`soft_boundary=True` 时）：
- 阈值 ±3 区间内同时计算两个候选档位
- **倾向降级**：取较低档位作为对外输出
- `get_opponent_scorecard()` 返回 `alt_tier`（较高档位）供看板展示

**3 个错配案例验证**（完整链路）：

| 对手 | ST（估） | AP（估） | 旧档 | 新档 | 是否纠正 | 你分析中的应有档 |
|------|:------:|:------:|:--:|:--:|:------:|:----------:|
| 武汉三镇 | 30 | 31 | B | **C** | ✅ | C |
| 上海海港 | 62 | 40 | A | **B** | ✅ | B |
| 青岛海牛 | 45 | 41 | C | **B** | ✅ | B |

- 武汉：ST=30<35 → C ✅
- 海港：AP=40<50 → B（ST 62 达 A 阈值但 AP 不够）✅
- 海牛：ST=45<50 → B（AP 41 也<50）✅

**验收**：
- [ ] 申花返回 "S"（硬锁）
- [ ] 山东返回 "A"（硬锁）
- [ ] 成都 2026-06-25 返回 "A"（ST 高 + AP 高）
- [ ] 武汉 2026-06-25 返回 "C"（ST<35 或 AP<35）
- [ ] 海港 2026-06-25 返回 "B"（AP<50）
- [ ] 海牛 2026-06-25 返回 "B"（ST<50）
- [ ] 辽宁/重庆返回 "C"
- [ ] 所有 16 队档位分布：S=1-2, A=3-5, B=5-7, C=4-6（合理范围）

---

### Task 1.5 — 销速交叉验证机制（新增·来自武汉分析）

**文件**：`src/opponent_rating.py`（新增函数）+ `src/sales_velocity.py`（新建）

**做什么**：开售后用 D4 销速曲线对评级预测做交叉验证，>20% 偏差触发人工审查

**核心机制**（来自武汉偏差分析）：
> "每场定价公告前，用CSV销速曲线做独立交叉验证，差距>20%触发人工审查"

**函数签名**：
```python
# src/sales_velocity.py
def predict_final_from_d4(d4_tickets: int, d4_ratio: float = 0.60) -> int:
    """基于 D4 累计销量预测最终销量。

    历史数据：7天销售周期的比赛中，D4 ≈ 60% 最终销量。
    最终销量 ≈ D4 / 0.60 = D4 × 1.67
    """

def check_velocity_alert(predict: int, d4_tickets: int,
                          d4_ratio: float = 0.60,
                          threshold: float = 0.20) -> dict:
    """检查销速与评级预测的偏差，返回预警信息。

    Returns:
        {
            'alert': bool,           # 是否触发预警
            'direction': str,        # 'overestimate' / 'underestimate'
            'predict': int,          # 评级模型预测
            'd4_predicted': int,     # 销速曲线预测
            'deviation_pct': float,  # 偏差百分比
            'action': str,           # 建议动作
        }
    """
```

**预警逻辑**：
```python
d4_predicted = d4_tickets / d4_ratio  # 销速预测最终值
deviation = (predict - d4_predicted) / d4_predicted

if abs(deviation) > 0.20:
    alert = True
    if deviation > 0:
        action = "倾向降级：高估风险大，建议下调对手档位"
    else:
        action = "倾向保持：低估可接受，低价风险小"
```

**武汉 6/27 案例验证**：
- predict = 9200（B 档基值 8200 × midseason ×1.10 × sat ×1.02）
- D4 = 3959
- d4_predicted = 3959 / 0.60 = 6598 ≈ 6600
- deviation = (9200 - 6600) / 6600 = 39.4% > 20% → **触发预警**
- action = "倾向降级" ✅

**评级调整触发条件**：

| 条件 | 动作 | 说明 |
|------|------|------|
| \|predict - d4_pred\| / d4_pred > 20% | 触发人工审查 | 你的核心建议 |
| D4_pred < predict × 0.85 | 倾向降级 | 高估风险大 |
| D4_pred > predict × 1.15 | 倾向上调 | 低估，但保守不调 |
| 连续 2 场同对手触发审查 | 自动调整 STATIC_TIER_OVERRIDE | 防单场噪声 |

**输出文件**：`data/processed/velocity_alerts.json`（预警日志）

**验收**：
- [ ] 武汉 6/27 数据（D4=3959）触发预警，deviation ≈ 39%
- [ ] 山东 7/4 若 D4=8000（预测 12841 × 0.60 = 7705），deviation < 20%，不触发
- [ ] 预警日志记录到 `velocity_alerts.json`

---

### Task 1.6 — 赛中销速修正乘数（新增·来自武汉分析）

**文件**：`src/sales_velocity.py`（同一文件）

**做什么**：开售后用实际销速曲线对评级预测做修正乘数

**核心机制**（来自武汉偏差分析）：
> "开售后如有销售数据，逐步用实际曲线修正预测"

**函数签名**：
```python
def sales_velocity_adjustment(d4_actual: int, predict: int,
                               d4_ratio: float = 0.60) -> float:
    """基于 D4 销速对预测的修正乘数。

    不对称修正（倾向降级）：
    - 实际差时大幅下调（×0.80）
    - 实际好时小幅上调（×1.05）
    """

def predict_with_velocity(opponent: str, match_date: str,
                          d4_tickets: int | None = None) -> dict:
    """评级预测 + 销速修正的完整链路。

    Returns:
        {
            'tier': str,
            'rating_predict': int,     # 评级模型预测
            'd4_predicted': int,       # 销速预测
            'velocity_mult': float,   # 修正乘数
            'final_predict': int,     # 修正后预测
            'alert': bool,
        }
    """
```

**修正乘数逻辑**：
```python
ratio = d4_actual / (predict × d4_ratio)  # 实际/预期

if ratio < 0.85:   return 0.80   # 大幅下调
elif ratio < 0.95: return 0.92   # 小幅下调
elif ratio > 1.15: return 1.05   # 小幅上调（保守）
else:              return 1.00   # 无修正
```

**武汉 6/27 案例验证**：
- predict = 9200
- D4 = 3959
- 预期 D4 = 9200 × 0.60 = 5520
- ratio = 3959 / 5520 = 0.717 < 0.85 → 修正乘数 0.80
- 修正后预测 = 9200 × 0.80 = 7360（比 6600 仍高，但比 9200 接近实际）

**说明**：销速修正乘数是评级模型的**叠加层**，不替代评级。当评级正确时，销速修正应为 1.0。

**验收**：
- [ ] 武汉 6/27 修正乘数 = 0.80
- [ ] 修正后预测 7360 比原始 9200 更接近实际 6600
- [ ] 评级正确时（如山东）修正乘数 = 1.0

---

### Task 1.7 — 赛季初重标机制（新增·来自武汉分析）

**文件**：`src/opponent_rating.py`（新增函数）+ `scripts/reseason_recalibrate.py`（新建）

**做什么**：每年 2 月（赛季前）用近 12 个月数据重新标定基值和评级，不跨年沿用

**核心机制**（来自武汉偏差分析）：
> "每赛季初用近12个月数据重新标定基准值，不跨年沿用"

**函数签名**：
```python
def reseason_recalibrate(year: int) -> dict:
    """赛季初重标：用近 12 个月数据更新基值和评级。

    执行时机：每年 2 月（赛季前）

    Returns:
        {
            'tier_base_new': dict,     # 新基值
            'tier_base_old': dict,     # 旧基值
            'changes': list,           # 变更明细
        }
    """
```

**重标逻辑**：
```python
def reseason_recalibrate(year: int):
    # 1. TIER_BASE 重标（用上赛季全年数据）
    last_season = year - 1
    for tier in ["S", "A", "B", "C"]:
        tier_matches = [m for m in last_season_matches
                        if classify_opponent_tier(m.opp) == tier]
        TIER_BASE[tier] = median(actual_attendance for m in tier_matches)

    # 2. ELO 携带延续（不重置，K=30 加速新赛季前 5 轮收敛）

    # 3. AP 历史窗口滚动（近 3 年）
    HIST_WINDOW = [year-3, year-2, year-1]  # 滚动 3 年

    # 4. 升班马初始 ELO=1400, AP=30
```

**基值滚动示例**：

| 赛季 | S 基值 | A 基值 | B 基值 | C 基值 | 说明 |
|------|:------:|:------:|:------:|:------:|------|
| 2025 | 12600 | 10900 | 8200 | 5700 | 当前 |
| 2026 | 13800 | 10500 | 7800 | 5500 | 申花上行 + 海港/武汉/海牛拖累 |
| 2027 | 待 R30 后计算 | — | — | — | — |

**验收**：
- [ ] 2026 重标后 S 基值 > 13000（申花 2025 上行）
- [ ] 2026 重标后 B 基值 < 8000（武汉/海牛 2025 拖累）
- [ ] ELO 不重置（延续性）
- [ ] AP 历史窗口滚动到近 3 年

---

### Task 1.8 — 离线数据生成脚本

**文件**：`scripts/build_opponent_ratings.py`（新建）

**做什么**：离线跑全量数据，生成 `elo_history.parquet` + `appeal_scores.parquet` + `rating_snapshot.json`

**执行步骤**：
```python
# 1. 加载 CSL 数据（2023-2026 全部比赛）
matches, standings, deductions = load_csl_data()

# 2. 跑 ELO 历史
elo_history = compute_elo_history(matches)
elo_history.to_parquet("data/processed/elo_history.parquet")

# 3. 加载国安主场历史票务
guoan_home = pd.read_parquet("data/processed/all_unified.parquet")
guoan_home = guoan_home[
    (guoan_home["competition"] == "CSL") &
    (guoan_home["match_date"].str.startswith(("2023", "2024", "2025", "2026")))
]

# 4. 生成每队每轮的评分快照
snapshot = []
for team in ALL_CSL_TEAMS_2026:
    sc = get_opponent_scorecard(team, "2026-06-25")
    snapshot.append(sc)

# 5. 保存快照
json.dump(snapshot, open("data/processed/rating_snapshot_20260625.json", "w"),
          ensure_ascii=False, indent=2)

# 6. 打印排行
print("对手评分排行 (2026-06-25):")
for sc in sorted(snapshot, key=lambda x: -x["ST"]):
    print(f"  {sc['opponent']:<12} ST={sc['ST']:.1f} AP={sc['AP']:.1f} → {sc['tier']}")
```

**输出文件**：
- `data/processed/elo_history.parquet`
- `data/processed/appeal_scores.parquet`（每队每年的 AP 分）
- `data/processed/rating_snapshot_20260625.json`（当前快照，供看板/测试读取）

**验收**：
- [ ] 脚本执行无报错
- [ ] 输出 3 个文件
- [ ] 打印排行符合预期（申花/成都/山东/天津/海港居前 5）
- [ ] 国安自身不在排行中（只评对手）

---

## Phase 2: 影子模式 — 并行对比 🔬

**目标**：动态分级与静态分级并行运行，不替换业务逻辑，跑回测对比 MAE + 销速预警验证
**验收**：
- 动态分级在 2023-2025 回测中 MAE 不劣于静态分级 ±0.5pp
- **2025 武汉那场动态误差 < 静态 20%**（武汉分析的核心验证点）
- 3 个错配案例（武汉/海港/海牛）在回测中档位纠正正确

### Task 2.1 — classify.py 增加动态函数

**文件**：`src/classify.py`（修改）

**做什么**：新增 `classify_opponent_tier_dynamic()`，与原 `classify_opponent_tier()` 并存

**改动**：
```python
# 原函数保留不动
def classify_opponent_tier(opponent: str) -> str:
    """静态分级（V4.6 原版，向后兼容）。"""
    ...

# 新增动态版本
def classify_opponent_tier_dynamic(opponent: str, match_date: str = None,
                                    **kwargs) -> str:
    """动态分级（V6.0，基于 ST+AP 评分）。

    Args:
        opponent: 对手名称
        match_date: 比赛日期（YYYY-MM-DD），None=用最新快照

    Returns:
        'S'/'A'/'B'/'C'
    """
    from src.opponent_rating import get_effective_tier
    if match_date is None:
        match_date = date.today().isoformat()
    return get_effective_tier(opponent, match_date, **kwargs)
```

**验收**：
- [ ] 原函数行为不变（32 tests 全过）
- [ ] 新函数对申花/山东返回与原函数一致（硬锁）
- [ ] 新函数对海港可能返回 A 或 B（动态）

---

### Task 2.2 — 回测脚本

**文件**：`scripts/backtest_dynamic_tier.py`（新建）

**做什么**：用 2023-2025 已赛场次跑两种分级，对比预测 MAE

**执行步骤**：
```python
# 1. 加载 2023-2025 国安主场已赛场次
guoan_home = load_guoan_home_history()  # 从 all_unified.parquet

# 2. 对每场比赛：
results = []
for match in guoan_home:
    # 静态预测
    tier_static = classify_opponent_tier(match["opponent"])
    pred_static = predict_with_context_static(match)  # 用原 classify

    # 动态预测
    tier_dynamic = classify_opponent_tier_dynamic(
        match["opponent"], match["date"])
    pred_dynamic = predict_with_context_dynamic(match)  # 用新 classify

    # 实际值
    actual = match["actual_attendance"]

    results.append({
        "match_id": match["match_id"],
        "opponent": match["opponent"],
        "date": match["date"],
        "tier_static": tier_static,
        "tier_dynamic": tier_dynamic,
        "tier_changed": tier_static != tier_dynamic,
        "pred_static": pred_static,
        "pred_dynamic": pred_dynamic,
        "actual": actual,
        "err_static": abs(pred_static - actual) / actual,
        "err_dynamic": abs(pred_dynamic - actual) / actual,
    })

# 3. 汇总
df = pd.DataFrame(results)
print(f"静态 MAE: {df['err_static'].mean():.1%}")
print(f"动态 MAE: {df['err_dynamic'].mean():.1%}")
print(f"档位变更场次: {df['tier_changed'].sum()}/{len(df)}")

# 4. 输出明细
df.to_csv("output/dynamic_tier_backtest.csv", index=False)
```

**关键验证点**：

| 场次 | 静态档位 | 期望动态档位 | 验证点 |
|------|---------|------------|--------|
| 2025 梅州（poor_home_form 触发） | B | B（动态应一致） | 动态不应误降 |
| 2026 海港（A 档 poor_form） | A（手动改） | A 或 B（自动） | 无需手动 commit |
| 2026 大连（连败触发） | C | C | 动态应一致 |
| 2023-2024 申花 | S | S（硬锁） | 硬锁生效 |
| 2024-2025 山东 | A | A（硬锁） | 硬锁生效 |
| 2026 升班马辽宁/重庆 | C（保守） | C 或 B | 首月后是否自动升 |

**验收**：
- [ ] 动态 MAE ≤ 静态 MAE + 0.5pp
- [ ] 档位变更场次中，动态预测误差 < 静态预测误差（变更方向正确）
- [ ] 申花/山东硬锁未变
- [ ] 输出 CSV 供人工 review

---

### Task 2.3 — 看板影子模式开关

**文件**：`dashboard/tabs/tab_next_match.py`（修改）

**做什么**：在 Tab1 预测面板增加"分级模式"开关，同时显示静态/动态预测

**UI 设计**：
```
┌─────────────────────────────────────────────┐
│ 分级模式: [静态] [动态] [对比]               │
├─────────────────────────────────────────────┤
│ 对手: 武汉三镇   日期: 2026-06-27           │
│                                              │
│ 静态分级: B (基值 8200)                     │
│   预测上座: 8,364                           │
│                                              │
│ 动态分级: B (ST=52, AP=48)                  │
│   预测上座: 8,420                            │
│   评分详情: [展开]                           │
└─────────────────────────────────────────────┘
```

**对比模式**特别标注档位差异：
- 档位相同：灰色文本
- 档位不同：橙色高亮 + 差异说明

**验收**：
- [ ] 三种模式切换正常
- [ ] 对比模式高亮差异
- [ ] 评分详情可展开（显示 ST/AP/ELO 各子项）

---

## Phase 3: 灰度切换 — H2 启用 🚀

**目标**：H2 未赛场次（8 场）启用动态分级，已赛场次保持静态
**验收**：H2 预测 MAE ≤ 3%（已赛 7 场 MAE 为 1.4% 的容差）

### Task 3.1 — classify.py 默认切换动态

**文件**：`src/classify.py`（修改）

**做什么**：`classify_opponent_tier()` 内部改为调用动态版本，保留 `STATIC_TIER_OVERRIDE` 兜底

**改动**：
```python
# 静态集合保留作为 fallback / override
S_TIER = {"上海申花"}
A_TIER = {"成都蓉城", "山东泰山", "天津津门虎", "上海海港"}
B_TIER = {...}
C_TIER = {...}

# 新增：动态开关
USE_DYNAMIC_TIER = True  # 全局开关，看板可覆盖

# 新增：手动 override（特殊场景兜底）
STATIC_TIER_OVERRIDE = {
    # 空 dict = 全部走动态；如有特殊场景手动加
}

def classify_opponent_tier(opponent: str, match_date: str = None, **kwargs) -> str:
    """对手分级（V6.0 默认动态）。

    优先级：
    1. STATIC_TIER_OVERRIDE 手动覆盖
    2. USE_DYNAMIC_TIER=True → 动态评分
    3. 静态集合 fallback
    """
    o = str(opponent).strip()

    # 1. 手动 override
    for key, tier in STATIC_TIER_OVERRIDE.items():
        if key in o or o in key:
            return tier

    # 2. 动态
    if USE_DYNAMIC_TIER and match_date:
        from src.opponent_rating import get_effective_tier
        return get_effective_tier(o, match_date, **kwargs)

    # 3. 静态 fallback
    if any(t in o or o in t for t in S_TIER): return "S"
    if any(t in o or o in t for t in A_TIER): return "A"
    if any(t in o or o in t for t in B_TIER): return "B"
    if any(t in o or o in t for t in C_TIER): return "C"
    return "B"
```

**向后兼容**：
- 现有调用 `classify_opponent_tier("武汉三镇")` 仍工作（match_date=None → 走静态 fallback）
- 新调用 `classify_opponent_tier("武汉三镇", match_date="2026-06-27")` 走动态
- `rule_engine.predict()` 增加 `match_date` 参数透传

**rule_engine.py 改动**：
```python
def predict(opponent, derby=False, ...,
            match_date: str = None,  # 新增
            **__) -> float:
    tier = classify_opponent_tier(opponent, match_date=match_date)
    ...
```

**验收**：
- [ ] 32 tests 全过（match_date=None 走静态）
- [ ] 新增 test：`classify_opponent_tier("上海申花", "2026-06-27") == "S"`
- [ ] 新增 test：`classify_opponent_tier("武汉三镇", "2026-06-27") in ("B", "C")`

---

### Task 3.2 — csl_context.py 透传 match_date

**文件**：`src/csl_context.py`（修改）

**做什么**：`predict_with_context()` 调用 `predict()` 时透传 `match_date`

**改动**：
```python
def predict_with_context(opponent: str, match_date: str, ...):
    ...
    return predict(
        opponent,
        match_date=match_date,  # 新增透传
        derby=opponent in DERBY_RIVALS,
        ...
    )
```

**验收**：
- [ ] 看板 Tab1 预测使用动态分级
- [ ] 已赛 7 场预测结果不变（动态与静态一致或更准）

---

### Task 3.3 — 档位变更日志

**文件**：`data/processed/tier_changes.json`（新建）+ `src/opponent_rating.py`（新增日志函数）

**做什么**：每次动态分级与静态不一致时记录，供审计

**格式**：
```json
{
  "changes": [
    {
      "date": "2026-06-27",
      "opponent": "武汉三镇",
      "tier_static": "B",
      "tier_dynamic": "B",
      "changed": false,
      "st": 52.3,
      "ap": 48.1,
      "reason": "一致"
    },
    {
      "date": "2026-07-04",
      "opponent": "山东泰山",
      "tier_static": "A",
      "tier_dynamic": "A",
      "changed": false,
      "st": 58.2,
      "ap": 72.5,
      "reason": "硬锁A档"
    }
  ]
}
```

**日志函数**：
```python
def log_tier_change(opponent: str, match_date: str,
                    tier_static: str, tier_dynamic: str,
                    scorecard: dict) -> None:
    """记录档位对比，追加到 tier_changes.json。"""
```

**验收**：
- [ ] H2 每场比赛后自动记录
- [ ] JSON 格式正确
- [ ] 看板 Tab2 可展示变更日志

---

### Task 3.4 — 看板新增 Tab：对手评分卡

**文件**：`dashboard/tabs/tab_opponent_rating.py`（新建）+ `dashboard/app_v8.py`（注册 Tab）

**做什么**：展示全联赛 16 队的 ST/AP/ELO/档位

**UI 设计**：
```
┌─────────────────────────────────────────────────────────────┐
│ 对手评分卡 (2026-06-25)                                     │
├─────────────────────────────────────────────────────────────┤
│ [表格]                                                      │
│ 对手        ELO   ST    AP    档位  静态档位  变更  详情   │
│ 上海申花    1680  82.5  88.2  S     S         —     [展开]  │
│ 成都蓉城    1620  71.3  68.5  A     A         —     [展开]  │
│ 山东泰山    1585  58.2  72.5  A     A         硬锁  [展开]  │
│ 上海海港    1560  62.1  65.3  A     A         —     [展开]  │
│ ...                                                         │
├─────────────────────────────────────────────────────────────┤
│ [评分时间轴折线图]                                          │
│ X轴: 日期  Y轴: ST评分  线: 每队一条                       │
│ 高亮: 档位变更节点                                          │
├─────────────────────────────────────────────────────────────┤
│ [档位变更日志表]                                            │
│ 日期       对手      旧档  新档  原因                       │
│ 2026-05-15 上海海港  B    A    poor_home_form 修复后手动    │
│ ...                                                         │
└─────────────────────────────────────────────────────────────┘
```

**验收**：
- [ ] 表格 16 行（全联赛）
- [ ] 时间轴折线图可切换 ST/AP/ELO
- [ ] 变更日志表读取 `tier_changes.json`
- [ ] 详情展开显示评分各子项

---

## Phase 4: 全量启用 + 自动化 📈

**目标**：赛季中自动更新 ELO，月度生成档位变更建议
**验收**：H2 8 场比赛后，档位变更建议 ≤ 2 次/月，且全部经人工确认

### Task 4.1 — ELO 自动更新

**文件**：`scripts/update_elo.py`（新建）+ crontab

**做什么**：每轮 CSL 比赛后，加载最新比赛结果 → 更新 ELO → 写回 parquet

**执行**：
```bash
# 每周一 03:00 跑（上周末比赛后）
0 3 * * 1 cd /home/xxxsuli/ticket-pricing && \
    ~/.hermes/hermes-agent/venv/bin/python scripts/update_elo.py
```

**脚本逻辑**：
```python
# 1. 加载现有 elo_history
elo_history = pd.read_parquet("data/processed/elo_history.parquet")

# 2. 加载最新 CSL 数据（load_csl_data 自动拉云端）
matches, _, _ = load_csl_data()

# 3. 找出未处理的新比赛
last_processed_date = elo_history["date"].max()
new_matches = [m for m in matches if m["date"] > last_processed_date and m["completed"]]

# 4. 增量更新 ELO
for m in new_matches:
    update_elo_single(m, elo_history)

# 5. 写回
elo_history.to_parquet("data/processed/elo_history.parquet")

# 6. 生成最新快照
build_snapshot(date.today().isoformat())
```

**验收**：
- [ ] 脚本手动执行成功
- [ ] crontab 配置正确
- [ ] 快照 `rating_snapshot_YYYYMMDD.json` 生成

---

### Task 4.2 — 月度档位变更报告

**文件**：`scripts/monthly_tier_report.py`（新建）

**做什么**：每月 1 号生成上月档位变更建议报告，输出 markdown

**报告内容**：
```markdown
# 对手档位变更建议 (2026-07)

## 变更概览
- 评估场次: 4
- 建议变更: 1 次
- 硬锁生效: 2 次（申花/山东）

## 建议变更明细

### 上海海港: A → B（建议）
- 当前 ST: 58.2 (阈值 60)
- 当前 AP: 62.1 (阈值 65)
- 近 5 场: 2胜1平2负 (PPG=0.8)
- 原因: 战绩持续低迷，ST 连续 3 轮低于 60
- 影响: TIER_BASE 10900 → 8200，预测上座下降 25%
- 建议: 7/15 主场对深圳启用 B 档定价

## 硬锁场次
- 7/4 山东泰山: A 档（德比）
- 7/17 辽宁铁人: C 档（升班马，ST=38.5）

## 无变更场次
- 7/4 山东泰山: 硬锁
- 7/17 辽宁铁人: 评分稳定
```

**验收**：
- [ ] 报告生成到 `output/tier_report_YYYYMM.md`
- [ ] 变更建议有完整的数据支撑
- [ ] 人工确认后写入 `STATIC_TIER_OVERRIDE`（或保持动态）

---

### Task 4.3 — 文档更新

**文件**：`output/国安动态定价说明_2026.md`（修改）

**做什么**：新增第十四章"动态对手分级"

**章节大纲**：
```markdown
## 十四、动态对手分级体系（V6.0）

### 14.1 设计动机
- 静态 KMeans 的局限
- 海港 A↔B 手动调整案例

### 14.2 双维度评分模型
- ST 实力分（ELO + PPG + 近5场 + GD）
- AP 吸引力分（历史上座 + 德比 + 话题 + 上次交锋）
- 融合规则与软边界

### 14.3 ELO 参数
- K-factor / 主场优势 / 初始值

### 14.4 冷启动机制
- 升班马首月保守 → 4 场后快速校准

### 14.5 赛季中调整规则
- 月度评估 + 滞后 3 轮窗口
- 硬锁与手动 override

### 14.6 回测验证
- 2023-2025 MAE 对比
- 档位变更命中率

### 14.7 看板展示
- 对手评分卡 Tab
- 影子模式对比
```

**验收**：
- [ ] 章节内容完整
- [ ] 同步到 Obsidian（`/mnt/c/Users/xxxsu/Documents/Obsidian Vault/`）

---

## 测试要求

### 单元测试

**文件**：`tests/test_opponent_rating.py`（新建）

**测试用例**：
```python
class TestEloUpdate:
    def test_elo_conservancy(self):
        """全联赛 ELO 均值应守恒在 1500 附近。"""

    def test_home_advantage(self):
        """主场优势 +65 应提高主队 expected。"""

    def test_k_factor_variation(self):
        """赛季前 5 轮 K=30，中段 K=20，末 5 轮 K=15。"""

    def test_single_match_max_change(self):
        """单场 ELO 变化 ≤ 30。"""

class TestStrengthScore:
    def test_high_elo_high_st(self):
        """ELO 1700 → ST > 80。"""

    def test_low_elo_low_st(self):
        """ELO 1400 → ST < 40。"""

    def test_season_not_started(self):
        """赛季未开始 → ST = 50 + ELO 调整。"""

    def test_promoted_team_cold_start(self):
        """升班马首场 → ST = 40。"""

class TestAppealScore:
    def test_derby_bonus(self):
        """申花 AP 加 30 德比分。"""

    def test_cold_start_promoted(self):
        """升班马 AP 用 C 级均值兜底。"""

    def test_history_attendance_percentile(self):
        """历史票房高的队 AP 高。"""

class TestEffectiveTier:
    def test_frozen_tier_shenhua(self):
        """申花硬锁 S 档。"""

    def test_frozen_tier_shandong(self):
        """山东硬锁 A 档。"""

    def test_soft_boundary(self):
        """ST=72（阈值 70-75）应返回软边界标记。"""

    def test_tier_distribution(self):
        """全联赛档位分布合理（S=1-2, A=3-5, B=5-7, C=4-6）。"""

class TestClassifyCompat:
    def test_legacy_call_no_date(self):
        """classify_opponent_tier('武汉三镇') 无 match_date 走静态。"""

    def test_dynamic_call_with_date(self):
        """classify_opponent_tier('武汉三镇', '2026-06-27') 走动态。"""

    def test_all_existing_tests_pass(self):
        """32 tests 全过。"""
```

**验收**：
- [ ] 新增测试全过
- [ ] 原 32 tests 全过
- [ ] 覆盖率 > 85%

---

## 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 动态分级在已赛场次 MAE 反弹 | 中 | 高 | Phase 2 影子模式强制验证，未通过不进 Phase 3 |
| 升班马冷启动误判 | 中 | 中 | 保守 C 级 + 首月 4 场后快速校准 |
| 边界球队震荡（海港 A↔B） | 高 | 中 | 软边界 + 滞后 3 轮窗口 |
| ELO 初始值偏差 | 中 | 低 | K=30 加速前 5 轮收敛 |
| 申花独占 S 档样本不足 | 已知 | 中 | AP 维度拉高，effective_tier 硬锁 |
| 球迷对档位变更不透明反感 | 低 | 高 | 月度调整 + 公告 + 看板透明展示 |
| resonix 实施时遗漏兼容性 | 中 | 高 | 每个 Task 都有向后兼容验收 |

---

## 执行顺序与依赖

```
Phase 1 (基建)
  ├─ Task 1.1 ELO 引擎
  ├─ Task 1.2 ST 计算         ← 依赖 1.1
  ├─ Task 1.3 AP 计算         ← 独立（含 CUR_YEAR_ATT_ratio）
  ├─ Task 1.4 融合映射（不对称阈值）← 依赖 1.2 + 1.3
  ├─ Task 1.5 销速交叉验证    ← 独立（武汉分析核心建议）
  ├─ Task 1.6 赛中销速修正    ← 依赖 1.5
  ├─ Task 1.7 赛季初重标      ← 独立
  └─ Task 1.8 离线脚本        ← 依赖 1.1-1.7
                              ↓
Phase 2 (影子模式)
  ├─ Task 2.1 classify 增加 dynamic   ← 依赖 1.8
  ├─ Task 2.2 回测脚本                ← 依赖 2.1（含 3 个错配验证）
  └─ Task 2.3 看板影子开关             ← 依赖 2.1
                              ↓
Phase 3 (灰度切换)
  ├─ Task 3.1 classify 默认动态        ← 依赖 2.2 验证通过
  ├─ Task 3.2 csl_context 透传         ← 依赖 3.1
  ├─ Task 3.3 档位变更日志             ← 依赖 3.1
  └─ Task 3.4 看板评分卡 Tab           ← 依赖 3.3
                              ↓
Phase 4 (全量自动化)
  ├─ Task 4.1 ELO 自动更新             ← 依赖 3.1
  ├─ Task 4.2 月度报告                 ← 依赖 4.1
  └─ Task 4.3 文档更新                 ← 依赖 4.2
```

**关键里程碑**：
- Phase 1 完成：评分快照生成，3 个错配案例（武汉/海港/海牛）全部纠正
- Phase 2 完成：回测 MAE 验证通过（动态不劣于静态）+ 销速预警验证通过
- Phase 3 完成：H2 首场（7/4 山东）灰度启用
- Phase 4 完成：赛季末全量自动化 + 下赛季 2 月重标

---

## 文件清单

### 新建文件

| 文件 | Phase | 说明 |
|------|-------|------|
| `src/opponent_rating.py` | 1 | 评分引擎核心（ST/AP/融合/重标）|
| `src/sales_velocity.py` | 1 | 销速交叉验证 + 赛中修正乘数 |
| `scripts/build_opponent_ratings.py` | 1 | 离线数据生成 |
| `scripts/reseason_recalibrate.py` | 1 | 赛季初重标脚本 |
| `scripts/backtest_dynamic_tier.py` | 2 | 回测对比（含 3 个错配验证）|
| `scripts/update_elo.py` | 4 | ELO 自动更新 |
| `scripts/monthly_tier_report.py` | 4 | 月度报告 |
| `dashboard/tabs/tab_opponent_rating.py` | 3 | 评分卡 Tab |
| `tests/test_opponent_rating.py` | 1-3 | 单元测试 |
| `tests/test_sales_velocity.py` | 1 | 销速模块测试 |
| `data/processed/elo_history.parquet` | 1 | ELO 历史 |
| `data/processed/appeal_scores.parquet` | 1 | AP 评分 |
| `data/processed/rating_snapshot_YYYYMMDD.json` | 1 | 每日快照 |
| `data/processed/tier_changes.json` | 3 | 档位变更日志 |
| `data/processed/velocity_alerts.json` | 1 | 销速预警日志 |

### 修改文件

| 文件 | Phase | 改动 |
|------|-------|------|
| `src/classify.py` | 2→3 | 新增 dynamic 函数 → 默认动态 |
| `src/rule_engine.py` | 3 | predict() 增加 match_date 参数 |
| `src/csl_context.py` | 3 | predict_with_context 透传 match_date |
| `dashboard/app_v8.py` | 3 | 注册新 Tab |
| `dashboard/tabs/tab_next_match.py` | 2 | 影子模式开关 |
| `output/国安动态定价说明_2026.md` | 4 | 新增第十四章 |

### 不改动文件（重要）

- `src/pricing_v5.py` — 定价矩阵不变，仍接收 S/A/B/C
- `src/dynamic_optimizer.py` — 优化器不变
- `dashboard/components/waterfall.py` — 瀑布图不变
- `data/processed/all_unified.parquet` — 只读
- `data/processed/calibration.json` — 只读

---

## 附录 A：CSL 2026 全联赛队名规范

```python
ALL_CSL_TEAMS_2026 = [
    "北京国安",      # 自身，不评分
    "上海申花",      # S 硬锁
    "成都蓉城",
    "山东泰山",      # A 硬锁
    "天津津门虎",
    "上海海港",
    "深圳新鹏城",
    "浙江",
    "河南",
    "武汉三镇",
    "云南玉昆",
    "梅州客家",
    "青岛西海岸",
    "青岛海牛",
    "大连英博海发",
    "辽宁铁人",
    "重庆铜梁龙",
]
```

队名别名沿用 `csl_context.py` 的 `_CLUB_ALIASES`。

---

## 附录 B：ELO 初始值表（2023 赛季初）

| 队名 | 2022 最终排名 | 初始 ELO |
|------|:----------:|:--------:|
| 武汉三镇 | 1 (冠军) | 1700 |
| 山东泰山 | 2 | 1650 |
| 浙江 | 3 | 1600 |
| 成都蓉城 | 5 | 1550 |
| 上海海港 | 4 | 1550 |
| 北京国安 | 6 | 1550 |
| 上海申花 | 10 | 1500 |
| 河南嵩山龙门 | 8 | 1500 |
| 天津津门虎 | 8 | 1500 |
| 梅州客家 | 9 | 1500 |
| 深圳队 | 13 | 1450 |
| 大连人 | 11 | 1450 |
| 长春亚泰 | 7 | 1500 |
| 沧州雄狮 | 12 | 1450 |
| 广州城 | 15 | 1400 |
| 广州队 | 17 (降级) | — |

**注**：2024/2026 新升班马（辽宁铁人、重庆铜梁龙、云南玉昆、深圳新鹏城、大连英博海发、青岛西海岸）初始 ELO = 1400，首场后开始更新。

resonix 实施时如 2022 排名数据不全，可用 2023 赛季首场前的博彩公司夺冠赔率倒推，或直接用 1500 均值启动，K=30 加速收敛。

---

## 附录 C：验收检查清单

### Phase 1 验收
- [ ] `src/opponent_rating.py` 实现完整（ST/AP/融合/重标）
- [ ] `src/sales_velocity.py` 实现完整（销速验证 + 修正乘数）
- [ ] `data/processed/elo_history.parquet` 生成
- [ ] `data/processed/appeal_scores.parquet` 生成
- [ ] `data/processed/rating_snapshot_20260625.json` 生成
- [ ] 申花 ST>80、山东 ST>55、升班马 ST<45
- [ ] 武汉 ST<35、海港 AP<50、海牛 AP 40-50
- [ ] 全联赛 ELO 均值 1500±20
- [ ] 3 个错配案例（武汉/海港/海牛）全部纠正
- [ ] 武汉 6/27 销速预警触发（deviation ≈ 39%）
- [ ] 武汉 6/27 销速修正乘数 = 0.80

### Phase 2 验收
- [ ] `scripts/backtest_dynamic_tier.py` 跑通
- [ ] 动态 MAE ≤ 静态 MAE + 0.5pp
- [ ] 2025 武汉那场动态误差 < 静态 20%
- [ ] 档位变更场次中动态误差 < 静态误差
- [ ] 看板影子模式开关可用
- [ ] `tests/test_opponent_rating.py` 全过
- [ ] `tests/test_sales_velocity.py` 全过

### Phase 3 验收
- [ ] `classify_opponent_tier()` 默认动态
- [ ] 原 32 tests 全过
- [ ] H2 首场（7/4 山东）灰度启用
- [ ] `tier_changes.json` 生成
- [ ] 看板评分卡 Tab 上线

### Phase 4 验收
- [ ] `scripts/update_elo.py` crontab 配置
- [ ] 月度报告生成
- [ ] 文档第十四章完成
- [ ] Obsidian 同步
- [ ] 下赛季 2 月重标脚本就绪

---

## 实施注意事项（给 resonix）

1. **不要动 `pricing_v5.py` 和 `dynamic_optimizer.py`** — 定价层完全不变
2. **向后兼容是硬约束** — 任何 `classify_opponent_tier()` 调用不带 `match_date` 必须走静态 fallback
3. **ELO 计算用 floats 不要 ints** — 避免精度丢失
4. **队名规范化统一走 `_normalize_club_name()`** — 不要自己写别名逻辑
5. **测试必须包含 2023-2025 回测** — 不能只测 2026
6. **每个 Phase 完成后 commit** — 便于回滚
7. **遇到数据缺失（如 2022 排名）用附录 B 的兜底方案** — 不要卡住
8. **软边界只在内部计算** — 对外永远输出单一档位
9. **申花/山东硬锁不可移除** — 即使 ST 下降也保持 S/A
10. **看板改动最小化** — 只加 Tab 和开关，不改现有 Tab 布局
11. **不对称阈值是核心设计** — 下调易（任一维度低即降）、上调难（双维度都需达标），不要改成对称阈值
12. **销速模块独立于评级** — `sales_velocity.py` 是叠加层，不替代评级；评级正确时修正乘数应为 1.0
13. **CUR_YEAR_ATT_ratio 是 AP 核心改进** — 必须实现，不能用 last_h2h 替代
14. **3 个错配案例必须验证通过** — 武汉 B→C、海港 A→B、海牛 C→B，这是武汉分析的实证锚点
15. **倾向降级原则** — 高估（B 档定价但实际 C 档需求）空座损失大；低估（C 档定价但实际 B 档需求）少赚但无空座

---

*计划制定：Claude Code (2026-06-25)*
*方案审查：Hermes/Suli*
*实施：Resonix*
