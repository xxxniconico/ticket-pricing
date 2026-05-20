# 北京国安票务动态定价模型 — 实施计划 v2

> **For Cursor:** 按任务顺序逐条执行。每任务含完整代码 + TDD + 验证命令。
> **Hermes = 计划者（待命澄清） | Cursor = 工作者+校验者**

**目标:** 基于2025赛季完整销售数据 + 官方定价表，为2026赛季构建「收入60%+上座率40%」优化定价模型。先CLI跑通，再加Streamlit看板。

**技术栈:** Python 3.11, pandas, numpy, scipy, openpyxl, pytest, Streamlit (Phase 2)

**仓库:** `~/ticket-pricing/`

---

## 数据文件（已就位）

| 文件 | 位置 | 内容 |
|------|------|------|
| `座位价格.xlsx` | `data/raw/` | 86区段 × A/B双轨官方定价 + 位置说明 |
| `2025散票数据.xlsx` | `data/raw/` | 529,929行座位级出票记录（场次+座位信息+票种） |
| `25年散票用户购买记录更新.xlsx` | `data/raw/` | 109,846行交易记录（单价+数量+总价，无场次） |

### 座位价格.xlsx 结构
```
列: 区域编号 | A类赛事票价(元) | B类赛事票价(元) | 年票价格 | 区域位置说明
86行，6个价格档位:
  A级: ¥260(6区段) | ¥340(39区段) | ¥440(15区段) | ¥580(6区段) | ¥780(18区段) | ¥1380(2区段)
  B级: ¥160(6区段) | ¥220(39区段) | ¥300(15区段) | ¥460(6区段) | ¥540(18区段) | ¥1080(2区段)
```

### 2025散票数据.xlsx 结构
```
列: 证件号码 | 比赛 | 序号 | 座位信息 | 票名称 | 年龄 | 性别
529,929行，15场比赛(2025全年主场)
票名称: 年卡/散票/客队票/商务年卡/两场通票
比赛格式: "[25年国安数据明细中超]2025-03-29北京国安 VS 成都蓉城"
座位信息格式:
  - 数字区: "130区-1排1座" 或 "310区"
  - 包厢: "10号门-南侧06包厢-1排1座"
  - 主席台: "18号门-主席台-5排5座"
```

### 25年散票用户购买记录更新.xlsx 结构
```
列: 用户 | 票价信息 | 数量 | 实际支付价格
109,846行，63,272独立用户
票价信息: 20个价格点(¥160-¥1380)
数量: 含少量"1#340.00"格式异常值(18条)
```

---

## 项目结构（目标）

```
ticket-pricing/
├── .cursorrules
├── .gitignore
├── README.md
├── requirements.txt
├── data/raw/
│   ├── 座位价格.xlsx
│   ├── 2025散票数据.xlsx
│   └── 25年散票用户购买记录更新.xlsx
├── src/
│   ├── __init__.py
│   ├── ingest.py          ← Task 1
│   ├── elasticity.py      ← Task 2
│   ├── classify.py        ← Task 3
│   ├── optimize.py        ← Task 4
│   └── cli.py             ← Task 5
├── tests/
│   ├── __init__.py
│   ├── test_ingest.py
│   ├── test_elasticity.py
│   ├── test_classify.py
│   └── test_optimize.py
└── docs/plans/
```

---

## Task 0: 环境准备

```bash
cd ~/ticket-pricing
pip install -r requirements.txt
```

---

## Task 1: 数据摄入 `src/ingest.py`

**目标:** 加载三个Excel → 统一成 (场次, 区段, 价格, 销量) 的DataFrame

### 核心映射逻辑

```
座位信息 → 提取区段编号 → 查座位价格.xlsx → A/B级价格
  "130区-1排1座"  → "130区" → A:¥780 B:¥540
  "10号门-南侧06包厢" → "包厢" → A:¥1380 B:¥1080 (VIP)
  "18号门-主席台-5排5座" → "主席台" → A:¥1380 B:¥1080 (VIP)
```

### Step 1: 写测试 `tests/test_ingest.py`

```python
import pandas as pd
import pytest
from src.ingest import (
    load_pricing_table,
    parse_section_from_seat,
    load_seat_data,
    build_match_price_demand,
)

def test_load_pricing_table():
    df = load_pricing_table("data/raw/座位价格.xlsx")
    assert len(df) == 86
    assert "区域编号" in df.columns
    assert "A类赛事票价（元）" in df.columns
    assert df[df["区域编号"] == 101]["A类赛事票价（元）"].values[0] == 1380

def test_parse_section_standard():
    assert parse_section_from_seat("130区") == "130"
    assert parse_section_from_seat("130区-1排1座") == "130"
    assert parse_section_from_seat("310区-5排10座") == "310"

def test_parse_section_vip():
    assert parse_section_from_seat("10号门-南侧06包厢-1排1座") == "vip"
    assert parse_section_from_seat("18号门-主席台-5排5座") == "vip"

def test_build_match_price_demand():
    # 用模拟数据测试
    seat_data = pd.DataFrame({
        "match": ["2025-03-29 北京国安 VS 成都蓉城"] * 3,
        "section": ["130", "310", "vip"],
        "ticket_type": ["散票"] * 3,
    })
    pricing = pd.DataFrame({
        "区域编号": [130, 310, 101],
        "A类赛事票价（元）": [780, 340, 1380],
        "B类赛事票价（元）": [540, 220, 1080],
    })
    result = build_match_price_demand(seat_data, pricing)
    assert len(result) == 3
    assert "price" in result.columns
    assert "quantity" in result.columns
```

### Step 2: 实现 `src/ingest.py`

```python
"""数据摄入：三个Excel → 统一(场次,区段,价格,销量) DataFrame"""
import pandas as pd
import re
from pathlib import Path


# === A级对手列表（2025-2026） ===
A_TIER_OPPONENTS = {"成都蓉城", "山东泰山", "上海海港", "上海申花"}


def load_pricing_table(filepath: str = "data/raw/座位价格.xlsx") -> pd.DataFrame:
    """加载官方定价表"""
    df = pd.read_excel(filepath)
    df["区域编号"] = df["区域编号"].astype(int)
    return df


def parse_section_from_seat(seat_info: str) -> str:
    """从座位信息提取区段编号或特殊类型
    
    Returns:
        "101"~"340" 表示标准区段
        "vip"        表示包厢/主席台
    """
    if not isinstance(seat_info, str):
        return "unknown"
    
    # 包厢 / 主席台
    if "包厢" in seat_info or "主席台" in seat_info:
        return "vip"
    
    # 标准数字区: "130区" 或 "130区-1排1座"
    m = re.search(r"(\d+)区", seat_info)
    if m:
        return m.group(1)
    
    return "unknown"


def load_seat_data(filepath: str = "data/raw/2025散票数据.xlsx") -> pd.DataFrame:
    """加载座位级出票数据，清洗并提取关键字段"""
    df = pd.read_excel(filepath)
    
    # 只保留散票（排除年卡、商务年卡、客队票）
    df = df[df["票名称"].isin(["散票", "两场通票"])].copy()
    
    # 解析比赛信息
    df["match_date"] = df["比赛"].str.extract(r"(\d{4}-\d{2}-\d{2})")[0]
    df["opponent"] = df["比赛"].str.extract(r"VS\s+(.+)$")[0]
    df["match_id"] = df["match_date"] + " " + df["opponent"]
    
    # 解析区段
    df["section"] = df["座位信息"].apply(parse_section_from_seat)
    
    # 判断A/B级
    df["match_tier"] = df["opponent"].apply(
        lambda x: "A" if any(o in str(x) for o in A_TIER_OPPONENTS) else "B"
    )
    
    return df


def build_match_price_demand(
    seat_data: pd.DataFrame,
    pricing: pd.DataFrame,
) -> pd.DataFrame:
    """合并座位数据+定价表 → (场次, 价格, 销量) 聚合
    
    Returns DataFrame columns:
        match_id, match_tier, price, quantity
    """
    # 构建区段→价格映射
    section_price_a = dict(zip(pricing["区域编号"].astype(str), pricing["A类赛事票价（元）"]))
    section_price_b = dict(zip(pricing["区域编号"].astype(str), pricing["B类赛事票价（元）"]))
    
    # VIP特殊处理
    section_price_a["vip"] = 1380
    section_price_b["vip"] = 1080
    
    # 给每行分配价格
    prices = []
    for _, row in seat_data.iterrows():
        sec = str(row["section"])
        if row["match_tier"] == "A":
            prices.append(section_price_a.get(sec, 0))
        else:
            prices.append(section_price_b.get(sec, 0))
    
    seat_data["price"] = prices
    
    # 过滤掉未匹配价格的记录
    seat_data = seat_data[seat_data["price"] > 0]
    
    # 按场次+价格聚合销量
    demand = seat_data.groupby(["match_id", "match_tier", "price"]).size().reset_index(name="quantity")
    
    return demand


def load_all(data_dir: str = "data/raw") -> pd.DataFrame:
    """一键加载+合并，返回统一DataFrame"""
    pricing = load_pricing_table(f"{data_dir}/座位价格.xlsx")
    seats = load_seat_data(f"{data_dir}/2025散票数据.xlsx")
    demand = build_match_price_demand(seats, pricing)
    return demand
```

### Step 3: 验证

```bash
cd ~/ticket-pricing
pytest tests/test_ingest.py -v

# 快速集成测试
python -c "
from src.ingest import load_all
df = load_all()
print(f'数据行数: {len(df)}')
print(f'场次数: {df.match_id.nunique()}')
print(f'价格点: {sorted(df.price.unique())}')
print(df.groupby('match_tier').quantity.sum())
"
```

### Step 4: Commit

```bash
git add src/ingest.py tests/test_ingest.py
git commit -m "feat: data ingestion with definitive pricing table"
```

---

## Task 2: 需求弹性拟合 `src/elasticity.py`

**目标:** 用15场×6价格档位≈90个数据点，拟合价格-需求曲线

### 方法

```
恒定弹性模型: Q = α × P^ε
取对数: ln(Q) = ln(α) + ε × ln(P)
线性回归 → ε = 弹性系数, R² = 拟合优度
```

**关键洞见:** 同一场比赛内，不同价格档位自然形成需求曲线。用场次固定效应控制对手强弱。

### Step 1: 写测试

```python
# tests/test_elasticity.py
import numpy as np
import pandas as pd
from src.elasticity import fit_constant_elasticity, ElasticityResult

def test_fit_elasticity_negative():
    """需求弹性应为负值"""
    np.random.seed(42)
    prices = np.array([260, 340, 440, 580, 780, 1380])
    quantities = np.array([12000, 10000, 8000, 5000, 3000, 1000]) + np.random.normal(0, 200, 6)
    data = pd.DataFrame({"price": prices, "quantity": quantities})
    
    result = fit_constant_elasticity(data)
    assert result.elasticity < -0.5
    assert result.r_squared > 0.5

def test_predict_demand():
    """涨价→需求下降"""
    result = ElasticityResult(elasticity=-2.0, base_demand=10000, base_price=340)
    assert result.predict(340) == pytest.approx(10000, rel=0.01)
    assert result.predict(680) < 5000  # 翻倍价格→需求<50%
```

### Step 2: 实现

```python
"""需求弹性拟合：价格-销量 → 弹性系数"""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy import stats


@dataclass
class ElasticityResult:
    elasticity: float
    base_demand: float
    base_price: float
    r_squared: float
    
    def predict(self, price: float) -> float:
        """Q = D₀ × (P/P₀)^ε"""
        ratio = price / self.base_price
        return self.base_demand * (ratio ** self.elasticity)
    
    def revenue_at_price(self, price: float) -> float:
        return price * self.predict(price)


def fit_constant_elasticity(data: pd.DataFrame) -> ElasticityResult:
    """用恒定弹性模型拟合
    
    Args:
        data: 含 price, quantity 列的DataFrame
    """
    prices = data["price"].values.astype(float)
    quantities = data["quantity"].values.astype(float)
    
    # 取对数
    log_p = np.log(prices)
    log_q = np.log(quantities)
    
    # 线性回归
    slope, intercept, r_value, p_value, std_err = stats.linregress(log_p, log_q)
    
    base_price = float(np.median(prices))
    base_demand = np.exp(intercept + slope * np.log(base_price))
    
    # R²
    predicted_log = intercept + slope * log_p
    ss_res = np.sum((log_q - predicted_log) ** 2)
    ss_tot = np.sum((log_q - np.mean(log_q)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
    
    return ElasticityResult(
        elasticity=slope,
        base_demand=base_demand,
        base_price=base_price,
        r_squared=r_squared,
    )


def fit_by_match_tier(demand_data: pd.DataFrame) -> dict[str, ElasticityResult]:
    """按A/B级分别拟合弹性"""
    results = {}
    for tier in ["A", "B"]:
        tier_data = demand_data[demand_data["match_tier"] == tier]
        if len(tier_data) >= 6:  # 至少6个价格点
            results[tier] = fit_constant_elasticity(tier_data)
    return results
```

### Step 3: 验证

```bash
pytest tests/test_elasticity.py -v

# 集成：用真实数据拟合
python -c "
from src.ingest import load_all
from src.elasticity import fit_by_match_tier
df = load_all()
results = fit_by_match_tier(df)
for tier, r in results.items():
    print(f'{tier}级: 弹性={r.elasticity:.2f}, R²={r.r_squared:.2f}, P₀=¥{r.base_price:.0f}')
"
```

### Step 4: Commit

```bash
git add src/elasticity.py tests/test_elasticity.py
git commit -m "feat: constant elasticity demand model"
```

---

## Task 3: 比赛分级 `src/classify.py`

**目标:** 在A/B基础上叠加需求乘数（德比、排名、周末、天气等）

### 需求乘数因子

| 因子 | 条件 | 乘数 |
|------|------|------|
| 德比/宿敌 | vs申花/天津/山东 | ×1.35 |
| A级对手 | 成都/山东/海港/申花 | ×1.25 |
| 周末 | 周五-周日 | ×1.10 |
| 对手前3 | 排名≤3 | ×1.15 |
| 对手后3 | 排名≥14 | ×0.90 |
| 关键赛程 | 争冠/保级/收官 | ×1.20 |
| 主场强势 | 近5场胜率>60% | ×1.08 |
| 主场弱势 | 近5场胜率<30% | ×0.92 |
| 节假日 | 法定假期 | ×1.12 |
| 极端天气 | <5°C或暴雨 | ×0.85 |

```python
"""比赛分级：A/B + 多维需求乘数"""
from dataclasses import dataclass

A_TIER_OPPONENTS = {"成都蓉城", "山东泰山", "上海海港", "上海申花"}
DERBY_RIVALS = {"上海申花", "天津津门虎", "山东泰山"}


@dataclass
class MatchContext:
    opponent: str
    is_weekend: bool = True
    is_holiday: bool = False
    season_stage: str = "mid"
    home_form: float = 0.5
    opponent_standing: int = 8
    temperature_c: float = 20
    precipitation_mm: float = 0


def compute_demand_multiplier(ctx: MatchContext) -> float:
    mult = 1.0
    if ctx.opponent in DERBY_RIVALS:
        mult *= 1.35
    elif ctx.opponent in A_TIER_OPPONENTS:
        mult *= 1.25
    if ctx.is_weekend:
        mult *= 1.10
    if ctx.opponent_standing <= 3:
        mult *= 1.15
    elif ctx.opponent_standing >= 14:
        mult *= 0.90
    if ctx.season_stage in ("crucial", "title_race", "relegation"):
        mult *= 1.20
    if ctx.home_form > 0.6:
        mult *= 1.08
    elif ctx.home_form < 0.3:
        mult *= 0.92
    if ctx.is_holiday:
        mult *= 1.12
    if ctx.temperature_c < 5 or ctx.precipitation_mm > 25:
        mult *= 0.85
    return round(mult, 3)


def classify_match(opponent: str, **kwargs) -> tuple[str, float]:
    """返回 (A/B, demand_multiplier)"""
    ctx = MatchContext(opponent=opponent, **kwargs)
    tier = "A" if opponent in A_TIER_OPPONENTS else "B"
    return tier, compute_demand_multiplier(ctx)
```

**测试:**
```python
def test_derby_multiplier():
    _, mult = classify_match("上海申花")
    assert mult >= 1.3

def test_weak_opponent():
    _, mult = classify_match("青岛海牛", opponent_standing=15)
    assert mult < 1.0
```

---

## Task 4: 优化求解器 `src/optimize.py`

**目标:** max(0.6×revenue + 0.4×attendance_rate)，受限于价格天花板/地板

### 方法

```
给定:
  - 弹性模型: Q(P) = D₀ × (P/P₀)^ε
  - 需求乘数: M (来自classify)
  - 权重: ω = 0.6 (收入), 1-ω = 0.4 (上座率)
  
目标函数:
  max  ω × P × Q(P) × M  +  (1-ω) × Q(P) × M / capacity × baseline_rev
  
约束:
  P_min ≤ P ≤ P_max  (地板=基准价×0.6, 天花板=基准价×2.5)
  Q(P) ≤ capacity      (不超过容量)
```

使用 `scipy.optimize.minimize` L-BFGS-B 求解。

```python
"""优化求解器"""
import numpy as np
from dataclasses import dataclass
from scipy.optimize import minimize
from src.elasticity import ElasticityResult


@dataclass
class PricingResult:
    optimal_price: float
    predicted_demand: float
    revenue: float
    attendance_rate: float
    objective_value: float


def optimize_single_price(
    model: ElasticityResult,
    demand_multiplier: float = 1.0,
    capacity: int = 40000,
    revenue_weight: float = 0.6,
    price_floor_pct: float = 0.6,
    price_ceiling_pct: float = 2.5,
) -> PricingResult:
    """单价格点优化"""
    p_min = model.base_price * price_floor_pct
    p_max = model.base_price * price_ceiling_pct
    baseline_rev = model.base_price * model.base_demand
    
    def objective(price):
        p = float(price[0])
        demand = min(model.predict(p) * demand_multiplier, capacity)
        revenue = p * demand
        att_rate = demand / capacity
        rev_score = revenue / 1_000_000
        att_score = att_rate * baseline_rev / 1_000_000
        return -(revenue_weight * rev_score + (1 - revenue_weight) * att_score)
    
    result = minimize(objective, [model.base_price], bounds=[(p_min, p_max)], method="L-BFGS-B")
    
    opt_p = float(result.x[0])
    demand = min(model.predict(opt_p) * demand_multiplier, capacity)
    
    return PricingResult(
        optimal_price=round(opt_p, 0),
        predicted_demand=round(demand, 0),
        revenue=round(opt_p * demand, 0),
        attendance_rate=round(demand / capacity, 3),
        objective_value=float(-result.fun),
    )
```

---

## Task 5: CLI `src/cli.py`

```bash
python src/cli.py --opponent "上海申花" --weekend --home-form 0.6 --opponent-standing 1
```

输出:
```
=====================================
  北京国安 vs 上海申花  —  定价建议
  比赛级别: A | 需求乘数: 1.35×
  优化目标: 60%收入 + 40%上座率
=====================================
  当前价: ¥340  →  建议价: ¥510 (+50%)
  预测需求: 8,200人
  预测收入: ¥4,182,000
  预测上座率: 82%
```

---

## 开放问题

1. ~~定价表~~ ✅ 已确认（座位价格.xlsx）
2. ~~数据格式~~ ✅ 已确认三个文件
3. 2026赛季剩余赛程+日期？（CLI需要对手名+周末/周中判断）
4. 是否有「开票时间窗口」数据（第几天开售影响销售节奏）？
5. 年票数据要纳入考虑吗？（固定收入池，减掉后才是散票池）

---

## 下一步

Cursor 打开 `~/ticket-pricing`，从 Task 0→5 逐条执行。
Hermes 待命回答问题。
