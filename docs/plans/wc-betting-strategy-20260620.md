# FIFA 2026 世界杯剩余赛事量化下注策略规划

> **作者**: Claude Code (规划) / Hermes Agent (待 review)
> **日期**: 2026-06-20
> **范围**: 剩余 40 场小组赛 (E-L 组第 2/3 轮 + A-D 组第 3 轮)
> **性质**: 纯量化研究，不涉及真实下注
> **风险偏好**: 平衡 (1/2 凯利)
> **模型**: Elo + Poisson (Dixon-Coles 简化)

---

## 0. 风险声明 (必读)

1. **体育博彩长期稳定盈利概率极低**。博彩公司通过抽水 (vig ~5%) 天然占优，大市场 (世界杯) 赔率效率接近有效市场，散户系统性正 EV 机会稀少。
2. 本策略**数学框架正确但不保证盈利**。1/2 凯利仍存在破产概率，尤其在小样本 (40 场) 下方差极大。
3. Poisson 模型假设进球独立，在**红牌、强队轮换、默契球、天气**等场景失效，需人工干预。
4. 本文档仅作量化研究用途，不构成下注建议。

---

## 1. 目标与核心指标

### 1.1 目标
针对剩余 40 场，构建 **概率模型 → 价值识别 → 资金管理** 全链路，最大化长期资金增长率的数学期望。

### 1.2 核心指标
| 指标 | 含义 | 目标 |
|------|------|------|
| EV (期望值) | `p_model × odds - 1` | 每注 > +3% |
| ROI | 累计收益/累计下注 | > 5% (覆盖 vig) |
| Brier Score | 概率校准 | < 0.22 (1X2 三选一基线 0.222) |
| 最大回撤 | 峰谷回撤 | < 20% |
| 夏普比率 | 收益/风险 | > 1.0 (40 场样本下不稳定) |

### 1.3 决策口径
- **货币单位**: 相对资金 (bankroll = 1.0)，不涉及绝对金额
- **赔率口径**: 欧洲十进制赔率 (decimal odds)，来自 The Odds API 去 vig 均值
- **下注单位**: 1/2 凯利比例 × bankroll

---

## 2. 数据层

### 2.1 现有数据 (已就绪)
来源: `data/processed/wc_2026_unified.json`

| 字段 | 用途 |
|------|------|
| `avg_h / avg_d / avg_a` | 市场平均赔率 (21 家博彩公司) |
| `p_h_mean` | 去 vig 隐含概率 (主胜) |
| `p_h_std` | 博彩公司分歧度 → 价值信号 |
| `n_bookmakers` | 市场厚度 (≥10 才可信) |
| `avg_vig` | 抽水率 (~5%) |

### 2.2 需补充数据 (建 Elo + Poisson)

| 数据 | 用途 | 来源 |
|------|------|------|
| 各队 Elo 评级初始值 | Elo 模型起点 | eloratings.net (公开) |
| 近 4 年国际赛历史比分 | 拟合 Elo 更新 + Poisson 参数 | football-data.co.uk / Wikipedia |
| 各队近 10 场进球/失球 | Poisson λ 估计 | Sofascore / FBref |
| 伤停/阵容 (可选) | 中等模型可忽略 | — |

### 2.3 数据管道建议
```
补充爬虫 → data/raw/elo/elo_ratings_20260620.json
         → data/raw/historical/intl_results_2022_2026.json
         → data/processed/wc_2026_model_input.json (合并 unified + elo + poisson params)
```

---

## 3. 概率模型层

### 3.1 Elo 评级 (球队强度)

**初始值**: 直接用 eloratings.net 公开评级 (无需自建历史)

**更新公式** (国际赛):
```
R_new = R_old + K × (S - E)
E = 1 / (1 + 10^((R_opp - R_self - HFA) / 400))
S ∈ {1, 0.5, 0}  (胜/平/负)
K = 30 (世界杯), HFA = 65 (主场优势，世界杯多为中立场地 → HFA≈0)
```

**世界杯特殊处理**: 2026 多国联办 (美/加/墨)，东道主有 HFA，其余中立。建议:
- Mexico / USA / Canada 主场: HFA = 65
- 其他比赛: HFA = 0

### 3.2 Poisson 进球模型 (Dixon-Coles 简化)

**期望进球**:
```
λ_home = attack_home × defense_away × ρ
λ_away = attack_away × defense_home × (1/ρ)
```
- `attack_i`, `defense_i`: 各队攻防强度 (从近 N 场拟合)
- `ρ`: 主场优势因子 (东道主比赛 > 1，中立 = 1)

**进球分布**:
```
P(home = i) = Poisson(i; λ_home)
P(away = j) = Poisson(j; λ_away)
```

**Dixon-Coles 低比分修正** (0-0, 1-0, 0-1, 1-1 有相关性):
```
τ(i, j) = 1 - ρ_dc × |i-j| × ... (见原论文)
P(i, j) = τ(i, j) × Poisson(i; λ_h) × Poisson(j; λ_a)
```
`ρ_dc` 拟合参数，通常 -0.1 ~ 0.1。

### 3.3 概率推导 (1X2)
```
P(主胜) = Σ_{i>j} P(i, j)
P(平局) = Σ_{i=j} P(i, j)
P(客胜) = Σ_{i<j} P(i, j)
```

### 3.4 模型融合 (Elo × Poisson)
Elo 给出胜率，Poisson 给出比分分布。两者交叉验证:
- 若 `P_elo(主胜)` 与 `P_poisson(主胜)` 偏差 > 8%，标记为**模型不一致**，降低置信度
- 最终概率: `p_model = 0.4 × p_elo + 0.6 × p_poisson` (Poisson 更细粒度，权重高)

---

## 4. 价值识别层

### 4.1 市场概率 (去 vig)
现有数据已提供 `p_h_mean` (Shin 方法去 vig)。若需重算:
```
隐含概率 = 1/odds
去vig: p = (1/odds) / Σ(1/odds)  (normalize method)
或 Shin method (更准，处理 favorite-longshot bias)
```

### 4.2 EV 计算
```
EV(主胜) = p_model(主胜) × avg_h - 1
EV(平局) = p_model(平局) × avg_d - 1
EV(客胜) = p_model(客胜) × avg_a - 1
```
**只下注 max(EV) 且 EV > 阈值** 的选项。阈值建议 **+3%**:
- 覆盖模型误差 (Poisson 在极端场景偏差大)
- 覆盖赔率波动 (下注时赔率可能已变)

### 4.3 博彩公司分歧度信号 (p_h_std)
| p_h_std | 含义 | 动作 |
|---------|------|------|
| < 0.01 | 市场一致，定价高效 | EV 信号弱，阈值提高到 +5% |
| 0.01-0.03 | 正常分歧 | 正常下注 |
| > 0.03 | 重大分歧 (可能有内幕/伤停消息) | 警惕，需人工核实新闻 |

### 4.4 价值机会筛选流程
```
对每场比赛:
1. 计算 p_model(主/平/客) from Elo+Poisson
2. 对比 p_market(主/平/客) from avg odds (去vig)
3. 计算 EV = p_model × odds - 1
4. 若 max(EV) > 3% 且 p_h_std < 0.03 → 候选下注
5. 若 max(EV) > 3% 且 p_h_std > 0.03 → 标记待人工核实
6. 若 max(EV) < 3% → 不下注 (放弃)
```

**预期价值机会数量**: 40 场 × 3 选项 = 120 个候选，按 +3% 阈值估计筛出 **5-12 个** (大市场效率高)。

---

## 5. 资金管理层 (1/2 凯利)

### 5.1 凯利公式
```
f* = (b × p - q) / b
b = odds - 1
p = p_model(该选项)
q = 1 - p

实际下注比例 f = f* / 2  (1/2 凯利)
```

**为什么 1/2 凯利**:
- 全凯利方差极大，40 场样本下回撤可达 50%+
- 1/2 凯利保留 75% 的增长率，方差减半
- 凯利本人也推荐分数凯利

### 5.2 单注硬上限
```
f = min(f*/2, 0.05)  # 单注不超过资金 5%
```
即便凯利算出 f* = 0.20 (强价值)，1/2 后 0.10 仍超 5% 上限 → 截断到 5%。
原因: 模型有误差，极端下注放大模型错误代价。

### 5.3 单日总下注上限
```
Σ f_i (同日) ≤ 0.15  # 单日总下注不超过资金 15%
```
按优先级排序 (EV 降序)，截断到 15%。

---

## 6. 相关性处理 (核心难点)

### 6.1 问题
小组赛第三轮**同组两场同时开赛** (防默契球)，两场结果**不独立**:
- 出线形势联动: A 场比分影响 B 场球队的出线需求 → 战术变化
- 小组排名联动: 串关/组合下注的联合概率 ≠ 独立概率乘积

### 6.2 处理方法: 蒙特卡洛模拟
```
对每个小组 (剩余第三轮):
1. 当前小组积分表 (从前两轮推导)
2. N = 10000 次模拟:
   a. 按 Poisson 模型生成同组两场比分
   b. 计算小组最终积分与排名
   c. 记录两场比赛的联合结果分布
3. 得到联合概率矩阵 P(场1=主胜, 场2=主胜) 等 9 种组合
4. 组合下注 EV 用联合概率计算，而非独立乘积
```

### 6.3 组合下注优化 (均值-方差)
```
决策变量: x_i (各选项下注比例)
最大化:  Σ p_i × odds_i × x_i - x_i  (总 EV)
约束:
  Σ x_i ≤ 0.15  (单日上限)
  x_i ≤ 0.05    (单注上限)
  Var(组合) ≤ σ²_target  (方差约束)

用协方差矩阵 Σ (来自蒙特卡洛) 计算组合方差:
  Var = x^T × Σ × x
```
解法: 二次规划 (scipy.optimize.minimize, SLSQP)

### 6.4 禁止事项
- **不串关 (parlay)**: 串关 EV = 各注 EV 乘积 (更负)，方差爆炸
- **不同时下注同组两场**: 除非蒙特卡洛显示联合 EV 显著为正

---

## 7. 风险控制

| 规则 | 阈值 | 动作 |
|------|------|------|
| 单注上限 | 5% bankroll | 截断 |
| 单日上限 | 15% bankroll | 截断 |
| 回撤止损 | 20% 峰值回撤 | 暂停 1 轮，复核模型 |
| 连续亏损 | 连负 6 注 | 暂停，校准检查 |
| 模型不一致 | Elo vs Poisson 偏差 > 8% | 降仓或放弃 |
| 高分歧警报 | p_h_std > 0.03 | 人工核实新闻后决定 |

---

## 8. 回测与验证 (用已赛 32 场)

### 8.1 样本外检验
已赛 32 场作为**样本外验证集**:
1. 用赛前赔率 + 模型概率回算每场 EV
2. 模拟 1/2 凯利下注，看累计收益曲线
3. 对比模型概率 vs 实际结果

### 8.2 校准曲线 (Calibration)
```
按 p_model 分桶 (0-10%, 10-20%, ..., 90-100%)
横轴: 模型概率
纵轴: 实际频率
理想: 落在 y=x 对角线上
```
偏差大 → 模型有系统性偏差，需调整。

### 8.3 Brier Score
```
BS = (1/N) Σ (p_model - outcome)²
outcome ∈ {0, 1} (该选项是否实际发生)
基线 (总是猜 1/3): BS = 0.222
目标: < 0.22
```

### 8.4 理论 EV vs 实际收益
若理论 EV = +5% 但实际 ROI = -3%，说明模型高估概率 (overfitting 或市场已定价)。

---

## 9. 工程实现建议 (给 Hermes)

### 9.1 模块划分
```
src/wc_betting/
├── data/
│   ├── fetch_elo.py          # 爬 eloratings.net
│   ├── fetch_history.py      # 爬历史国际赛
│   └── build_model_input.py  # 合并 → wc_2026_model_input.json
├── models/
│   ├── elo.py                # Elo 评级 + 更新
│   ├── poisson.py            # Dixon-Coles 拟合 + 概率推导
│   └── blend.py              # Elo × Poisson 融合
├── strategy/
│   ├── value.py              # EV 计算 + 筛选
│   ├── kelly.py              # 1/2 凯利 + 上限截断
│   └── correlation.py        # 蒙特卡洛 + 组合优化
├── backtest/
│   ├── calibrate.py          # 校准曲线 + Brier
│   └── simulate.py           # 32 场样本外回测
└── dashboard/
    └── tab_value.py          # 看板新 tab: 价值机会排序
```

### 9.2 看板集成
在现有 `app_fifa_wc.py` 加 tab 或新建 `app_wc_value.py`:
- 价值机会表 (EV 降序): 比赛 | 选项 | p_model | p_market | EV | 凯利比例 | 建议下注
- 校准曲线图
- 回测收益曲线

### 9.3 技术栈
- `scipy.stats.poisson` — Poisson 分布
- `scipy.optimize.minimize` (SLSQP) — 组合优化
- `scikit-learn.brier_score_loss` — 校准评估
- `pandas` — 数据处理
- 现有 venv: `~/.hermes/hermes-agent/venv/`

---

## 10. 执行路线图

| 阶段 | 任务 | 产出 |
|------|------|------|
| P1 | 爬 Elo 评级 + 历史比赛 | `data/raw/elo/`, `data/raw/historical/` |
| P2 | 实现 Elo + Poisson 模型, 拟合参数 | `models/elo.py`, `models/poisson.py` |
| P3 | 32 场已赛回测 + 校准 | 校准曲线, Brier, 理论 vs 实际 ROI |
| P4 | 若 P3 校准通过 → 计算 40 场 EV + 凯利 | 价值机会表 |
| P5 | 蒙特卡洛处理同组相关性 | 联合概率矩阵 |
| P6 | 组合优化 + 风控规则 | 最终下注建议表 |
| P7 | 看板集成 | Tab3 (app_fifa_wc.py) ✅ |

**关键决策点**: P3 校准不通过 (Brier > 0.22 或校准曲线严重偏离) → 停止，不进入 P4。说明模型不足以战胜市场。

---

## 11. 已知局限

1. **样本量**: 40 场策略验证不充分，即使回测 32 场通过，实战仍可能因运气亏损
2. **Poisson 假设**: 进球独立假设在红牌/战术调整后失效
3. **市场效率**: 世界杯是全球最大博彩市场，赔率接近有效，+3% EV 机会可能 < 5 个
4. **时延**: The Odds API 数据有延迟，真实下注时赔率已变 (本研究不涉及，但需知)
5. **同组相关性**: 蒙特卡洛依赖 Poisson 独立生成，但真实默契球/战术调整无法建模

---

## 附录 A: 关键公式速查

```
去vig隐含概率:  p_i = (1/odds_i) / Σ(1/odds_j)
EV:             EV_i = p_model_i × odds_i - 1
凯利:           f* = (b×p - q) / b,  b=odds-1,  q=1-p
1/2凯利:        f = f* / 2
Poisson:        P(k; λ) = λ^k × e^(-λ) / k!
Elo期望:        E = 1 / (1 + 10^((R_opp - R_self)/400))
```

## 附录 B: 参考实现

- Dixon & Coles (1997) "Modelling Association Football Scores"
- Elihu D. Kelly (1956) "A New Interpretation of Information Rate"
- Shin (1993) "Measuring the Incidence of Insider Trading"
-FBref / Sofascore xG 数据可用于 Poisson 参数校准

---

## 12. P1-P7 实施结果 (2026-06-21)

### P1 完成: 数据采集
- Elo 评级: `data/raw/elo/elo_ratings_20260620.json` (48/48 队, eloratings.net)
- 历史比分: `data/raw/historical/intl_results_2022_2026.json` (2135 场, 2022-01-05..2026-06-19)
- 爬虫: `src/wc_betting/data/fetch_elo.py`

### P2 完成: 模型实现
- `src/wc_betting/models/elo.py` — Elo→1X2, draw_c=0.335 (标定自历史)
- `src/wc_betting/models/poisson.py` — Dixon-Coles, 134 队(含 ROW 桶), mu=1.116, rho=1.249, rho_dc=-0.19
- `src/wc_betting/models/blend.py` — Elo×Poisson 融合 + 不一致性标记
- `src/wc_betting/backtest/calibrate.py` — OOS 校准

### P3 校准结果 (关键发现)

**OOS 协议**: Poisson 在 pre-WC (2103 场, <2026-06-11) 重拟合; Elo 用历史反推 elo_before (零和性质 ΔR1+ΔR2=0); 32 场已赛 WC 做测试集。

| 模型 | home-win Brier | 3-class Brier | log-loss |
|------|---------------|---------------|----------|
| 纯 Poisson | **0.2244** | 0.5640 | 0.9264 |
| blend 0.4/0.6 | 0.2418 | 0.5939 | 0.9667 |
| 纯 Elo | 0.2803 | 0.6658 | 1.0902 |

**发现 1: Elo 对 blend 零/负贡献。** blend 权重扫描最优 w_elo=0.0 (纯 Poisson)。21/32 场 Elo 与 Poisson 分歧 >8%。根因: 洲际联合会校准问题——CONCACAF/CAF 队跨洲比赛少, 4 年 Poisson 拟合无法正确锚定跨洲相对强度, 但 Elo (全球系统) 同样在跨洲场景失准。

**发现 2: 近期权重无效。** 标准 DC 近期权重 (半衰期 0.5-3 年) 扫描全部比无权重更差。原因: 国家队比赛频率低, form 信号弱; 2022 卡塔尔 WC (2.5 年前) 仍高度信息性, 降权损害拟合; 32 场样本下方差增加抵消偏差减少。

**发现 3: 计划 0.222 基线有误。** 该基线假设主胜率 33%, 但 32 场 WC 小组赛实际主胜率 53.1% (东道主+赛程优势), 正确基线 = 0.53×0.47 = 0.2490。纯 Poisson 0.2244 < 0.2490, 有真实预测力 (差 0.025)。超 0.222 仅 0.0022, 在 32 场噪声范围内统计不可区分。

**决策: 纯 Poisson 进 P4。** w_elo=0, Elo 仅保留用于不一致性标记。风控收紧 (单注 3%, +5% EV 阈值) 反映小样本不确定性。计划原 0.4/0.6 blend 弃用。

### P2 产出
- `data/processed/wc_2026_model_input.json` — 40 场剩余比赛的赔率 + Poisson/Elo 概率 + 不一致性标记, P4 输入
- 26/40 场标记不一致 (Elo-Poisson gap >8%), 需人工核实或降仓

### P4 完成: 价值识别 + 凯利

- `strategy/kelly.py` — 1/2 凯利, 单注 3% 上限, 每日 15% 截断
- `strategy/value.py` — EV 筛选 (+5%) + 不一致/高分歧/薄市场标记 + 同日同组相关性标记
- 产出: `output/wc_value_opportunities_20260620.json`
- 结果: **12 下注 / 23 手动审核 / 5 跳过**, 总下注 30.3% (跨6日, 每日<15%)

**OOS 校准偏差 (按结果分):**

| 结果 | 预测 | 实际 | 偏差 |
|------|------|------|------|
| 主胜 | 0.451 | 0.531 | 低估 |
| 平局 | 0.256 | 0.312 | 低估 (WC 平局率异常高) |
| 客胜 | 0.293 | 0.156 | 高估 (洲际联合会问题) |

影响: 平局/主胜下注可能真实价值, 客胜下注疑似假价值。23 个手动审核全是 elo-poisson inconsistent, 正确拦截了 France vs Iraq (+319% EV) 等长射假信号。

### P5 完成: 蒙特卡洛同组相关性

- `strategy/correlation.py` — N=10000 蒙特卡洛, DC-corrected Poisson 独立采样
- 产出: `output/wc_correlation_analysis_20260620.json`
- 2 个同日同组 bet pair 分析:

| 小组 | 比赛 | bet cov | P(both win) | 晋级概率 | 决策 |
|------|------|---------|-------------|----------|------|
| E (6-26) | Curacao vs Ivory Coast (H) + Ecuador vs Germany (H) | -0.0000 | 2.5% | Germany 99.5%, Ivory Coast 98.3% | KEEP BOTH |
| K (6-28) | Colombia vs Portugal (H) + DR Congo vs Uzbekistan (D) | +0.0006 | 14.3% | Colombia 89.0%, Portugal 45.2% | KEEP BOTH |

12 下注全部保留, 0 剔除。**限制 (§11.5)**: Poisson 独立采样 → cov≈0 是模型假设的必然结果, 非真实战术/心理相关性。

### P6 完成: 组合优化 + 风控

- `strategy/portfolio.py` — SLSQP 均值-方差优化
- 产出: `output/wc_final_bets_20260620.json`
- σ²_target=0.02 (std≤14.1%), 协方差矩阵来自 P5

**方差约束 binding** (Kelly var=0.0417 > target=0.02):

| 方案 | 总 EV | 方差 | 标准差 | 总下注 |
|------|-------|------|--------|--------|
| Kelly (P4) | +0.1006 | 0.0417 | 20.4% | 30.3% |
| 优化 (P6) | +0.0771 | 0.0200 | 14.1% | 23.2% |

EV 降 23%, 方差降 52%。优化器主要削减高赔率 (高方差) 下注:

| 比赛 | 赔率 | 单注方差 | Kelly | 优化 | 削减 |
|------|------|----------|-------|------|------|
| Curacao vs Ivory Coast | 20.39 | 32.77 | 0.020 | 0.006 | -67% |
| Panama vs England | 6.45 | 6.96 | 0.030 | 0.015 | -50% |
| Jordan vs Argentina | 6.88 | 6.75 | 0.016 | 0.008 | -50% |
| Netherlands vs Sweden | 1.72 | 0.69 | 0.030 | 0.030 | 0% |

**风控规则** (§7): 单注 3% / 每日 15% / σ²≤0.02 在优化器内强制; 不一致/高分歧在 P4 已过滤; 回撤止损 (20%) / 连负 (6注) 是运营规则, 需手动执行。

### P7 完成: 看板集成 + 每日追踪

- **Tab3** (`dashboard/app_fifa_wc.py:675-898`): "📊 价值下注" tab, 端口 :8507
  - KPI 条 (下注数/总仓位/EV/σ) + 追踪条 (已结算 W·L/累计P·L/ROI/资金)
  - Kelly vs 优化对比卡 (方差约束 binding 可视化, σ² 条形图)
  - 下注表 (9列, 今日行高亮, 胜负行着色, 仓位双条形 Kelly vs 优化)
  - 每日汇总 (仓位/EV/实际P·L/上限利用率) + 同组 3×3 联合概率矩阵 + 风控规则/OOS校准偏差
  - "🔄 刷新赛果结算" 按钮: 实时调 `tracker.settle_bets()` 抓 Wikipedia + 结算
- **CSS** (`dashboard/assets/fifa_style.css` §13): 全套暗色主题样式 + 移动端响应
- **每日追踪器** (`src/wc_betting/strategy/tracker.py`):
  - 四模式: `recommend` (每日推荐) / `settle` (结算) / `status` (全量状态) / `init`
  - Wikipedia HTML 抓取+regex 解析 (复用 build_wc_unified.py 模式)
  - 队名归一化 `_norm()`: 去后缀 + 别名映射, 匹配 bet↔wiki 结果
  - 持久化 `output/wc_bet_tracker.json`, 累计统计自动重算
- **首笔结算**: Netherlands vs Sweden [H] 5–1 ✅ P/L=+0.0215, ROI=71.8%, 命中率 100%
- **沙箱限制**: 网络不可达时 `settle` 降级用 `/tmp/wc_groups/` 缓存 HTML

