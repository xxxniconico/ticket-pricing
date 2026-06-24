# 足球竞猜投注: 深度理论研究

> 配套文档: `docs/plans/wc-betting-strategy-20260620.md` (P1-P8 路线图)
> 数据基础: 2135 场历史国际赛 (2022-01-05..2026-06-19) + 34 场 OOS 世界杯 2026 比赛
> 模型: Dixon-Coles 简化 Poisson ( Maher 1982 → Dixon & Coles 1997 )
> 适用场景: 中国体彩 (China Sporttery) 4 种玩法 EV 扫描, 仅供研究

---

## 1. Dixon-Coles Poisson 的数学基础与局限

### 1.1 模型公式

设主队进球 X ~ Poisson(λ_h), 客队进球 Y ~ Poisson(λ_a), 期望进球:

```
λ_h = μ × exp(attack_h) × exp(defense_a) × ρ      (主队期望进球)
λ_a = μ × exp(attack_a) × exp(defense_h) / ρ      (客队期望进球)
```

其中:
- `μ` — 全局进球尺度 (identifiability: Σ log attack = Σ log defense = 0)
- `attack_t` / `defense_t` — 队伍 t 的进攻/防守强度 (对数尺度)
- `ρ` — 主场优势 (exp(log_rho)); 中立场 ρ=1.0

联合得分概率:

```
P(X=i, Y=j) = τ(i, j) × Poisson(i; λ_h) × Poisson(j; λ_a)
```

Dixon-Coles 低比分修正 τ (仅作用于 0:0 / 0:1 / 1:0 / 1:1 四个格子):

```
τ(0,0) = 1 - λ_h·λ_a·ρ_dc
τ(0,1) = 1 + λ_h·ρ_dc
τ(1,0) = 1 + λ_a·ρ_dc
τ(1,1) = 1 - ρ_dc
τ(i,j) = 1   otherwise
```

当前拟合值: `μ ≈ 1.07, ρ ≈ 1.27` (主场优势), `ρ_dc ≈ -0.11`.

### 1.2 核心局限 — 独立性假设

Poisson 模型假设 X ⊥ Y (两队进球独立). 现实中正相关性来自:

1. **战术博弈**: 弱队防守反击 → 双方进球都少 → 正相关
2. **共同环境因素**: 天气、场地、裁判执法尺度同时影响双方
3. **比赛状态**: 一方领先 → 收缩防守 → 比分固化 → 后续进球减少

独立性假设导致 **所有比分平局** P(i,i) 被系统性低估, 而 τ 仅修正 0:0 和 1:1.
2:2, 3:3 等中高比分平局仍被低估. 这正是本项目 OOS 平局 pred 25.6% vs actual 31.2%
偏差的数学根源.

### 1.3 替代方案对比

| 方法 | 数学原理 | 参数数 | 平局修正范围 | 估计复杂度 | 小样本稳定性 | 适合本项目 |
|------|----------|--------|-------------|-----------|-------------|-----------|
| **对角膨胀** | P(i,i) ×= λ_draw, 重归一化 | +1 | 全部平局 | 极低 (1D 网格) | ★★★ | ✅ |
| **Bivariate Poisson** | X=X₁+X₀, Y=Y₂+X₀; Cov(X,Y)=λ₀ | +1/team | 全部 (通过协方差) | 高 (EM/数值积分) | ★☆☆ | ✗ |
| **Copula** | C(F_X(x), F_Y(y)) 建模相依 | +1~3 | 全部 | 高 | ★☆☆ | ✗ |
| **Platt scaling** | p_calib = σ(a + b·p_raw) | +2/class | 1X2 概率校准 | 极低 (逻辑回归) | ★★★ | ✅ |
| **Isotonic regression** | 单调非参数映射 | 非参数 | 1X2 概率校准 | 低 | ★★☆ | 备选 |

### 1.4 Bivariate Poisson 详析 (Karlis & Ntzoufras 2003)

构造:

```
X = X₁ + X₀,  Y = Y₂ + X₀
X₁ ~ Poisson(λ₁), X₂ ~ Poisson(λ₂), X₀ ~ Poisson(λ₀)
Cov(X, Y) = λ₀   (公共项诱导的正协方差)
```

联合分布:

```
P(X=i, Y=j) = Σ_{k=0}^{min(i,j)} Poisson(i-k; λ₁) × Poisson(j-k; λ₂) × Poisson(k; λ₀)
```

λ₀ > 0 时所有平局 P(i,i) 被提升. 但本项目不适合采用:

1. 似然函数需三重求和, 估计需 EM 算法 (E 步用前向递归, M 步更新 λ)
2. λ₀ 的解释 ("联赛整体进球环境") 在跨洲国家队比赛场景牵强
3. 34 场 OOS 不足以稳定区分 λ₀ 与 ρ_dc 的贡献 (参数不可识别风险)
4. 重拟合成本高, 与现有 134 队 attack/defense 估计耦合

**决策**: 对角膨胀 (修全比分平局) + Platt scaling (修 S 形校准偏差). 两者互补:
前者在比分矩阵层修正, 后者在 1X2 概率层修正.

---

## 2. 校准偏差的根源与量化

### 2.1 OOS 校准桶 (34 场, Poisson 主胜概率)

```
[0.00, 0.15)  pred=0.111  actual=0.000  n=3   → 过度高估弱主队
[0.15, 0.30)  pred=0.220  actual=0.250  n=8   → 轻微低估
[0.30, 0.45)  pred=0.408  actual=0.500  n=6   → 低估
[0.45, 0.60)  pred=0.485  actual=0.800  n=5   → 严重低估 (价值区间!)
[0.60, 0.80)  pred=0.695  actual=0.667  n=9   → 轻微高估
[0.80, 1.01)  pred=0.847  actual=0.667  n=3   → 过度高估强主队
```

整体形状为 **S 形 miscalibration**: 中档低估, 两端高估.

### 2.2 S 形偏差的数学本质

理想校准下 pred == actual (对角线). 实际 pred-actual 曲线呈:
- pred ∈ [0.45, 0.60]: actual 偏高 (低估)
- pred ∈ [0.80, 1.0]: actual 偏低 (高估)

Platt scaling 的 sigmoid `p_calib = 1/(1+exp(a + b·p_raw))` 可修正此形状:
- a > 0, b < 0 时: 中间值被推向两端 → 修正中间低估
- 拟合目标: 最小化负对数似然 `−Σ [y·log(p_calib) + (1−y)·log(1−p_calib)]`

注: 标准 Platt 用 logit(p_raw) 作输入, 这里用 p_raw 直接作输入 (因 34 场样本小,
直接线性变换更稳). 单调性约束 (b < 0) 保证概率序不变.

### 2.3 客胜高估根因

2135 场历史数据中洲际联合会跨洲比赛稀少. Poisson 的 attack/defense 参数对弱联合会
队伍 (CONCACAF/CAF) 估计不稳定:

- 强联合会 (UEFA/CONMEBOL) vs 弱联合会 → Poisson 高估弱队进球能力 → 客胜虚高
- WC 小组赛 53.1% 主胜率 (pred 45.1%) 也部分源于此 (中性场名义"主队"实为种子队)

**修正方案**: `deflate_away` — 跨洲比赛时对客胜格子 (i<j) 乘以 < 1 的系数, 重归一化.
仅在 home/away 属不同联合会时启用.

---

## 3. 体彩 30% 抽水的数学分析

### 3.1 抽水计算

体彩返奖率 ~70% → overround = 1/0.70 - 1 ≈ 42.8% (隐含概率和 ≈ 1.43).

盈亏平衡 EV: `EV_break_even = overround / (1 + overround) ≈ 30%`
(需平均 EV > +30% 才能长期盈利)

### 3.2 按玩法的可打性 (124 个扫描机会)

| 玩法 | 机会数 | 典型 EV | 结果数 | 可打性 | 原因 |
|------|--------|---------|--------|--------|------|
| crs (比分) | 80 | +50%~+220% | 31 | ★★★ | 结果多→体彩定价低效; Poisson 直接产出矩阵→结构性优势 |
| ttg (总进球) | 20 | +20%~+80% | 8 | ★★☆ | 结果中等→定价中等 |
| hhad (让球) | 12 | +5%~+30% | 3 | ★☆☆ | 3 结果→定价高效; 30% 抽水几乎不可破 |
| had (胜平负) | 12 | +5%~+20% | 3 | ☆☆☆ | 最定价高效; 仅极端 EV 时考虑 |

### 3.3 信息效率理论

市场结果数越多 → 定价越低效 (信息收集成本高, 投注者注意力分散).
crs 31 个结果 vs had 3 个结果, 体彩对 crs 的定价粗糙度远高于 had.
Poisson 模型直接产出 10×10 比分矩阵 → 在 crs 市场有信息优势.

**结论**: 策略聚焦 crs + ttg, had/hhad 仅在 EV 显著 (> +30%) 时考虑.

---

## 4. CLV (Closing Line Value) 理论

### 4.1 定义

CLV = 购买赔率 − 收盘赔率 (Pinnacle 锐意盘). 持续正 CLV 是下注技能的金标准,
比短期 ROI 更稳定 (ROI 受方差影响大).

### 4.2 CLV 不可获取时的替代指标

体彩无 Pinnacle 对标, 且赔率变动不公开. 替代:

1. **模型 EV** (= p_model × odds − 1): 衡量模型认为的 edge
2. **预测 EV vs 实际 ROI 对比**: 回测核心 — 若预测 EV 持续正但实际 ROI 负 → false edge
   (模型失准)
3. **体彩赔率变动跟踪**: 若可多次抓取, 跟踪购买时 vs 开赛赔率的变动

### 4.3 统计显著性

二项分布下, n 注、胜率 p、赔率 b 的 ROI 95% 置信区间:

```
σ_ROI ≈ √(p(1−p)·(b−1)² / n)    (n > 30 时正态近似)
CI = ROI ± 1.96·σ_ROI
```

- n < 30: ROI 不可信 (噪声主导)
- n > 100: 较高可信度
- n > 30 且 CI 不含 0: 可初步判断策略有效性

---

## 5. Kelly 仓位理论

### 5.1 Kelly 公式

```
f* = (b·p − q) / b,   b = odds − 1,   p = 模型概率,   q = 1 − p
```

最大化长期资本增长率 g = p·log(1 + b·f) + q·log(1 − f).

### 5.2 分数 Kelly 的理论依据

- 全 Kelly 最大化 g 但方差极大 (破产风险)
- 分数 Kelly (1/2, 1/4) 以牺牲少量 g 换取大幅降方差
- 体彩 30% 抽水下大部分机会 f* < 0 (无 edge), 正 EV 机会 f* 也偏小

### 5.3 按玩法细化 Kelly

| 玩法 | Kelly 系数 | 单注上限 | 理由 |
|------|-----------|---------|------|
| crs | 1/4 | 3% | 高 edge 高方差, 1/4 平衡 |
| ttg | 1/4 | 3% | 中 edge 中方差 |
| hhad | 1/8 | 2% | 低 edge, 极保守 |
| had | 1/8 或不投 | 2% | 最低 edge, 30% 抽水几乎不可破 |

---

## 6. 对角膨胀的数学推导

### 6.1 构造

设原始 (Dixon-Coles 修正后) 比分矩阵为 P₀(i,j), 满足 Σ P₀ ≈ 1 (τ 修正后已重归一).
对角膨胀因子 λ_draw ≥ 1:

```
P₁(i,j) = P₀(i,j) × λ_draw       if i == j
P₁(i,j) = P₀(i,j)                 otherwise
P(i,j)  = P₁(i,j) / Σ P₁         (重归一化)
```

### 6.2 平局概率提升量

平局原概率 D₀ = Σ_i P₀(i,i). 膨胀后:

```
D₁ = (λ_draw × D₀) / (1 + (λ_draw − 1) × D₀)
```

例: D₀ = 0.25, λ_draw = 1.2 → D₁ = 0.3 / 1.05 ≈ 0.286 (提升 +3.6pp).
要使 D₀=0.256 → D₁=0.312 (修正到 actual), 需 λ_draw ≈ 1.27.

### 6.3 拟合

最大化平局对数似然:

```
λ_draw* = argmax_{λ}  Σ_{m ∈ draws}  log P(i_m, i_m; λ)
```

1D 网格搜索 (λ ∈ [1.0, 1.5], step 0.01) 足够, 复杂度极低.
历史数据上拟合 (非 OOS), 作为超参数.

### 6.4 与 Bivariate Poisson 的等价性

对角膨胀在"仅提升平局"这一目标上与 Bivariate Poisson (λ₀ > 0) 数学等价,
但参数数更少 (1 vs 1/team) 且无需 EM. 在 34 场 OOS 下两者不可区分,
故选对角膨胀 (Occam's razor).

---

## 7. Platt Scaling 的数学推导

### 7.1 模型

对二分类 (如 home win yes/no):

```
p_calib = σ(a + b · p_raw) = 1 / (1 + exp(−(a + b · p_raw)))
```

注: 本实现用 `p_calib = 1/(1+exp(a + b·p_raw))` 形式 (a, b 直接为输出), 拟合时
约束 b < 0 保证单调性 (高 p_raw → 高 p_calib).

### 7.2 拟合 (梯度下降 / L-BFGS)

损失: 交叉熵 `L = −Σ [y·log(p_calib) + (1−y)·log(1−p_calib)]`.

梯度:

```
∂L/∂a = Σ (p_calib − y)
∂L/∂b = Σ (p_calib − y) · p_raw
```

L-BFGS-B 带 b < 0 约束, 50 次迭代收敛.

### 7.3 三分类扩展 (1X2)

对 H/D/A 分别拟合 (a_h, b_h), (a_d, b_d), (a_a, b_a), 然后重归一化:

```
p_h' = σ(a_h + b_h · p_h)
p_d' = σ(a_d + b_d · p_d)
p_a' = σ(a_a + b_a · p_a)
S = p_h' + p_d' + p_a'
p_h_final = p_h' / S,  etc.
```

### 7.4 小样本稳健性

34 场 OOS 拟合 6 参数 (3 类 × 2) 偏紧. 缓解:
- 用 L2 正则 (λ=0.01) 防过拟合
- 限制 b ∈ [−5, 0] 防极端变换
- 拟合后检查单调性 (p_raw 升序 → p_calib 升序)

---

## 8. 联合会客胜修正的数学推导

### 8.1 构造

当 home/away 属不同 FIFA 联合会时, 对客胜格子 (i < j) 乘以 deflate_away ≤ 1:

```
P₁(i,j) = P₀(i,j) × deflate_away    if i < j  (客胜)
P₁(i,j) = P₀(i,j)                    otherwise
P(i,j)  = P₁(i,j) / Σ P₁            (重归一化)
```

### 8.2 客胜概率下调量

客胜原概率 A₀ = Σ_{i<j} P₀(i,j). 下调后:

```
A₁ = (deflate_away × A₀) / (1 − A₀ + deflate_away × A₀)
```

例: A₀ = 0.293, deflate_away = 0.85 → A₁ = 0.249 / 0.956 ≈ 0.260 (下调 −3.3pp).
要使 A₀=0.293 → A₁=0.156 (修正到 actual), 需 deflate_away ≈ 0.63 (较激进).

### 8.3 拟合

在跨洲比赛子集上最大化对数似然:

```
deflate_away* = argmax_{δ}  Σ_{m ∈ cross-conf}  log P(gh_m, ga_m; δ)
```

1D 网格搜索 (δ ∈ [0.5, 1.0], step 0.01).

### 8.4 联合会映射

48 队 WC 2026 阵容按 FIFA 联合会:

| 联合会 | 队数 | 代表队 |
|--------|------|--------|
| UEFA | 16 | Spain, France, England, Germany, Netherlands, Portugal, Croatia, Belgium, Switzerland, Austria, Sweden, Norway, Turkey, Scotland, Czech Republic, Bosnia |
| CONMEBOL | 6 | Argentina, Brazil, Colombia, Ecuador, Paraguay, Uruguay |
| CONCACAF | 6 | Mexico, United States, Canada, Panama, Haiti, Curacao |
| CAF | 10 | Morocco, Senegal, Egypt, Algeria, Tunisia, Ivory Coast, Ghana, South Africa, DR Congo, Cape Verde |
| AFC | 9 | Japan, South Korea, Iran, Saudi Arabia, Qatar, Iraq, Jordan, Uzbekistan, Australia |
| OFC | 1 | New Zealand |

注: Australia 2006 年从 OFC 转入 AFC.

---

## 9. 完整改进管线

### 9.1 改进模型流程

```
1. fit() → DCParams (attack/defense/mu/rho/rho_dc)
2. fit_draw_inflate() → λ_draw (历史数据上最大化平局对数似然)
3. fit_deflate_away() → δ (跨洲比赛上最大化对数似然)
4. score_matrix(draw_inflate=λ_draw, deflate_away=δ) → 校正后比分矩阵
5. predict_1x2() → (p_h, p_d, p_a) 原始概率
6. calibrate_1x2(p_h, p_d, p_a, platt_params) → 校准后 (p_h', p_d', p_a')
7. EV = p_calib × odds − 1
8. Kelly stake = f* / 4, capped at 3%
```

### 9.2 各层修正的职责

| 层 | 修正对象 | 方法 | 参数数 |
|----|----------|------|--------|
| 比分矩阵 | 全平局低估 | 对角膨胀 | 1 (λ_draw) |
| 比分矩阵 | 跨洲客胜高估 | deflate_away | 1 (δ) |
| 1X2 概率 | S 形校准偏差 | Platt scaling | 6 (3类×2) |

三层互补, 不冲突: 对角膨胀 + deflate_away 在矩阵层修正结构性偏差, Platt 在概率层
修正残余的 S 形偏差.

---

## 10. 文献参考

- Maher, M.J. (1982). *Modelling association football scores*. Statistica Neerlandica, 36, 109-118.
  — 首次提出独立 Poisson 进球模型.
- Dixon, M.J. & Coles, S.G. (1997). *Modelling Association Football Scores and Inefficiencies in the Football Betting Market*. Applied Statistics, 46(2), 265-280.
  — 引入低比分 τ 修正 + 时间衰减 + 博彩市场低效实证.
- Karlis, D. & Ntzoufras, I. (2003). *Analysis of sports data by using bivariate Poisson models*. The Statistician, 52(3), 381-393.
  — Bivariate Poisson (λ₀ 公共项) 详析, EM 估计算法.
- Karlis, D. & Ntzoufras, I. (2009). *Bayesian modelling of football outcomes: using the Skellam's distribution for the goal difference*. IMA J. Management Math.
  — Skellam 分布建模进球差, 与 BivPoisson 对比.
- Kelly, J.L. (1956). *A New Interpretation of Information Rate*. Bell System Technical Journal, 35, 917-926.
  — Kelly 公式原始论文.
- Buchdahl, J. *Against the Odds* — CLV 理论与市场效率实证 (Football-Data.co.uk).
  — 持续正 CLV 是下注技能金标准, 比 ROI 更稳定.
- Platt, J. (1999). *Probabilistic Outputs for Support Vector Machines and Comparisons to Regularized Likelihood Methods*. Advances in Large Margin Classifiers.
  — Platt scaling 原始方法 (SVM 概率校准).
- Gneiting, T. & Raftery, A.E. (2007). *Strictly Proper Scoring Rules, Prediction, and Estimation*. JASA, 102(477), 359-378.
  — Brier 分数、Log-loss 的严格 proper scoring rule 理论.

---

## 附录 A: 符号表

| 符号 | 含义 |
|------|------|
| μ | 全局进球尺度 |
| ρ | 主场优势 (exp(log_rho)) |
| ρ_dc | Dixon-Coles 低比分修正参数 |
| λ_h, λ_a | 主/客队期望进球 |
| τ(i,j) | DC 低比分修正因子 |
| λ_draw | 对角膨胀因子 (≥1) |
| δ (deflate_away) | 跨洲客胜下调因子 (≤1) |
| (a, b) | Platt scaling 参数 |
| σ(·) | sigmoid 函数 |
| EV | 期望价值 = p × odds − 1 |
| f* | Kelly 最优分数 |
| CLV | Closing Line Value |
| OOS | Out-of-Sample (样本外) |

## 附录 B: 校准桶定义

主胜概率校准桶边界: [0.00, 0.15, 0.30, 0.45, 0.60, 0.80, 1.01]
(与 `backtest/calibrate.py:calibration_buckets` 一致)

各桶意义:
- [0, 0.15): 弱主队 (应很少胜)
- [0.15, 0.30): 中弱主队
- [0.30, 0.45): 中档主队 (价值区间下沿)
- [0.45, 0.60): 中档主队 (价值区间上沿, 低估最严重)
- [0.60, 0.80): 强主队
- [0.80, 1.0): 极强主队 (高估)


---

## 9. 模型 vs 市场：标准处理框架

### 9.1 核心问题

你有一个概率估计（Poisson+Elo 融合，记为 p_model），市场有一个隐含概率
（从赔率反推，记为 p_market）。它们不一致。你应该：

A. 融合两者得到更好概率？
B. 用差值决定投注大小？
C. 什么都不做，只看差值做决策？

### 9.2 行业标准：不做融合，做信号提取

学界和业界共识：市场赔率已经包含了几乎所有的公开信息（Kuyper 2000,
Forrest & Simmons 2008）。如果你用一个公开模型（Poisson）去融合市场数据，
唯一的结果是让你自己的信号退化——你最后得到的不过是市场的平滑版本。

**标准做法**（Thorp 1997, Benter 2008）：



赔率的作用：计算期望值 + 决定仓位。**永远不进概率估计。**

### 9.3 Favorite-Longshot Bias（热门-冷门偏差）

这是博彩市场最稳健的结构性偏差（Thaler & Ziemba 1988, Snowberg & Wolfers 2010）：

- 市场系统性**高估**冷门概率（赔率不够高）
- 市场系统性**低估**热门概率（赔率偏高）
- 偏差在赔率>10 的极端冷门上最显著

这解释了为什么 Poisson 模型在平局和冷门方向能找到正 EV：不是模型更准，
是市场在这些区域有已知的结构性高估。

**这个偏差是你在博弈中赚钱的来源，不是你的模型参数需要调整的错误。**

### 9.4 Brier Decomposition（Brier 分解）

Murphy (1973) 将 Brier 分数分解为三项：



- **Reliability（校准）**：你的概率是否准确？说 30% 的时候是不是真的 30%？
- **Resolution（区分度）**：你的概率能否区分不同结果？
- **Uncertainty（不确定性）**：事件本身的随机性

市场赔率通常有很好的 **Reliability**（校准好），但 **Resolution** 差
（对稀有事件缺乏区分度）。

你的模型：**Reliability** 比市场差（样本少），但 **Resolution** 可能更好
（Poisson 比分分布能区分不同类型的冷门）。

### 9.5 结论：不改模型，只记录信号

市场数据的最正确用法：

1. **不改你的概率**
2. **只记录信号差异**——p_model vs p_market，按比赛类型分组
3. **积累后做统计检验**
4. **EV 和 Kelly 已经用了市场数据**——赔率决定仓位，这就够了

### 参考文献

- Benter, W. (2008). Computer Based Horse Race Handicapping and Wagering Systems.
- Forrest, D. & Simmons, R. (2008). Sentiment in the betting market on Spanish football.
- Kelly, J.L. (1956). A New Interpretation of Information Rate.
- Kuyper, F. (2000). Efficiency in the UK Fixed-Odds Football Betting Market.
- Murphy, A.H. (1973). A New Vector Partition of the Probability Score.
- Snowberg, E. & Wolfers, J. (2010). Explaining the Favorite-Longshot Bias.
- Thaler, R. & Ziemba, W. (1988). Parimutuel Betting Markets.
- Thorp, E.O. (1997). The Kelly Criterion in Blackjack, Sports Betting, and the Stock Market.

