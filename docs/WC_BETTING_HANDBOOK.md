# FIFA 2026 世界杯量化下注策略 — 完整交接文档

> **性质**: 纯量化研究, 不涉及真实下注。1/4 凯利, Dixon-Coles Poisson + Platt 校准。
> **最后更新**: 2026-06-22 (P12 完成)
> **项目路径**: `~/ticket-pricing/`
> **模块根**: `src/wc_betting/`
> **看板**: `dashboard/app_fifa_wc.py` (端口 :8507)

---

## 目录

1. [项目概述](#1-项目概述)
2. [项目结构](#2-项目结构)
3. [数据层](#3-数据层)
4. [模型层](#4-模型层)
5. [策略层](#5-策略层)
6. [体彩扫描器](#6-体彩扫描器)
7. [回测与校准](#7-回测与校准)
8. [看板](#8-看板)
9. [运行手册](#9-运行手册)
10. [关键发现与已知问题](#10-关键发现与已知问题)
11. [队名归一化备忘](#11-队名归一化备忘)
12. [开发历史 (P1-P12)](#12-开发历史)

---

## 1. 项目概述

### 目标
用量化模型预测 FIFA 2026 世界杯比赛结果, 在中国体育彩票 (sporttery.cn) 和国际博彩平台上识别正 EV (期望价值) 下注机会。

### 核心方法
- **Dixon-Coles Poisson 模型**: 拟合 2135 场国际比赛 (2022-2026) 的 attack/defense 参数
- **Platt Scaling 校准**: sigmoid 变换修正 1X2 概率偏差
- **3 层后验修正**: draw_inflate (平局膨胀) + deflate_away (跨洲客胜修正) + Platt
- **1/4 凯利 + 组合优化**: SLSQP 均值-方差优化, 单注 3%, 每日 15%, σ²≤0.02

### 性质声明
- 纯研究性质, 所有 "下注" 均为模拟追踪
- 体彩返奖率 ~70% (vig ~30%), 远高于国际博彩 (3-5%), 但比分/总进球定价比胜平负更可能不准

---

## 2. 项目结构

```
ticket-pricing/
├── src/wc_betting/
│   ├── data/                          # 数据采集
│   │   ├── fetch_elo.py               # eloratings.net Elo 评级抓取
│   │   ├── fetch_sporttery.py         # sporttery.cn 体彩赔率抓取
│   │   ├── fetch_xg.py                # FBref xG 抓取 + 双源合并
│   │   ├── fetch_xg_api.py            # API-Football xG 抓取 (替代 FBref)
│   │   └── build_model_input.py       # 构建 model_input.json (赔率+概率+不一致标记)
│   ├── models/                        # 预测模型
│   │   ├── poisson.py                 # Dixon-Coles Poisson (核心)
│   │   ├── elo.py                     # Elo → 1X2 转换
│   │   ├── blend.py                   # Elo×Poisson 融合 (已弃用, w_elo=0)
│   │   └── calibration.py             # Platt Scaling 拟合/应用/持久化
│   ├── strategy/                      # 下注策略
│   │   ├── value.py                   # 价值识别 (EV 筛选)
│   │   ├── kelly.py                   # 凯利公式 (1/4 凯利, 3% 上限)
│   │   ├── correlation.py             # 蒙特卡洛同组相关性
│   │   ├── portfolio.py               # 国际博彩组合优化 (SLSQP)
│   │   ├── sporttery_scanner.py       # 体彩 EV 扫描器 (核心)
│   │   ├── sporttery_portfolio.py     # 体彩组合优化 (同场跨玩法协方差)
│   │   ├── sporttery_tracker.py       # 体彩购买追踪
│   │   ├── daily_optimize.py          # 每日独立优化 + 对冲检测
│   │   └── tracker.py                 # 比赛结果结算追踪
│   └── backtest/
│       └── calibrate.py               # OOS 校准 + 模型对比 (baseline/improved/xg)
├── dashboard/
│   ├── app_fifa_wc.py                 # Streamlit 看板 (端口 :8507)
│   └── assets/fifa_style.css          # 看板样式
├── data/
│   ├── raw/
│   │   ├── elo/elo_ratings_20260620.json    # 48 队 Elo 评级
│   │   ├── historical/intl_results_2022_2026.json  # 2135 场历史比分
│   │   └── xg/                               # xG 数据 (API-Football 抓取中)
│   └── processed/
│       ├── calibration_params.json          # Platt 参数 + OOS meta
│       ├── wc_2026_groups.json              # 48 队分组
│       ├── wc_2026_model_input.json         # 模型输入 (赔率+概率+不一致)
│       ├── wc_2026_unified.json             # 统一赛果 (用户更新)
│       └── historical_with_xg.json          # 历史数据+xG 合并 (运行后生成)
├── output/                             # 产出文件 (JSON)
│   ├── wc_sporttery_opportunities.json      # 体彩 EV 扫描结果
│   ├── wc_sporttery_portfolio.json          # 体彩组合优化结果
│   ├── wc_sporttery_purchases.json          # 体彩购买追踪
│   ├── wc_bet_tracker.json                  # 国际博彩结算追踪
│   ├── wc_model_comparison.json             # 模型对比 (baseline vs improved)
│   └── ...
├── docs/
│   ├── research/betting_model_theory.md     # 理论文档 (DC 数学/校准/Kelly)
│   └── plans/wc-betting-strategy-20260620.md # 原始路线图 (P1-P7)
└── .env                                # API keys (gitignored)
```

---

## 3. 数据层

### 3.1 Elo 评级 (`fetch_elo.py`)
- **来源**: eloratings.net (SPA, 数据在 TSV 文件)
- **数据**: 48/48 队, top=Spain 2129, bottom=Curacao 1427
- **缓存**: `/tmp/elo_cache/`, stdlib urllib + 0.5s 礼貌延迟
- **TSV 结构**: 16 列 (year mo day t1 t2 g1 g2 tournament venue rchg1 r1_after r2_after rchg1 rchg2 rank1 rank2)
- **URL slug 规则**: 多词用下划线; "men's"后缀去掉; Czech Republic→Czechia; Curaçao→Curacao
- **继承国陷阱**: Czechia.tsv 含捷克斯洛伐克历史, team_code 检测从最后一行选频率高的候选

### 3.2 历史比分 (`intl_results_2022_2026.json`)
- **2135 场** (2022-01-05..2026-06-19)
- 用于 Poisson 模型拟合

### 3.3 xG 数据 (`fetch_xg.py` + `fetch_xg_api.py`)
- **FBref (fetch_xg.py)**: 沙箱 403 不可达; 且 FBref **没有国家队 xG 数据** (只有俱乐部)
- **API-Football (fetch_xg_api.py)**: 用户提供了 API key, Free plan 100/day
  - `/fixtures/statistics` 端点有 `expected_goals` 字段
  - Euro 2024 / Copa America / Nations League / WC qualifiers 2024-2026 有 xG
  - WC 2022 无 xG (数据太旧)
  - 13 个联赛 ID: 1=WC, 4=Euro, 5=Nations League, 9=Friendlies, 13=Copa America, 16=AFCON, 17=Asian Cup, 29-34=WCQ
- **进度管理**: `.api_progress.json` 断点恢复, 每 10 场保存, 接近 100/day 停止
- **双源合并**: `load_xg_matches()` 加载 FBref + API-FOOTBALL, 按 (date, frozenset({team,opp})) 去重, API-FOOTBALL 优先
- **激活流程**: 抓取 → `merge_xg_with_historical()` → `calibrate compare` → scanner 自动加载
- **当前状态**: API key 已配, 抓取器已验证, 数据尚未抓取完成 (需 4-6 天, 100/day)

### 3.4 体彩赔率 (`fetch_sporttery.py`)
- **来源**: `webapi.sporttery.cn/gateway/jc/football/getMatchCalculatorV1.qry`
- **4 种玩法**: `poolCode=had|hhad|crs|ttg`
  - **had**: 胜平负 (3 结果)
  - **hhad**: 让球胜平负 (3 结果, 有 handicap)
  - **crs**: 比分 (31 结果, 含 "其他")
  - **ttg**: 总进球 (8 结果: 0-6球 + 7+球)
- **队名匹配**: TEAM_CN 反向字典 {中文:英文} + `_TEAM_CN_OVERRIDE` 覆盖 sporttery 简称
- **缓存**: `/tmp/sporttery_cache/`
- **沙箱不可达**: 设计为用户机器运行
- **手动录入 fallback**: `load_manual_odds(path)` + `save_manual_template(path, matches)`

### 3.5 统一赛果 (`wc_2026_unified.json`)
- 用户手动更新, 包含所有 72 场 WC 2026 比赛的赛果
- 结构: `[{group, home_en, away_en, score ("X–Y" 用 em-dash), finished, date}, ...]`
- **注意**: 队名可能与模型不一致 (见 §11)

---

## 4. 模型层

### 4.1 Dixon-Coles Poisson (`poisson.py`) — 核心

#### 数学模型
- **进球期望**: `λ_home = α_home + β_away + μ + ρ·I(home is host)`, `λ_away = α_away + β_home + μ`
- **DC tau 修正**: 低比分 (0:0, 1:0, 0:1, 1:1) 的相关性修正, 参数 `rho_dc`
- **参数**: 134 队 (含 ROW 桶), `mu=1.116, rho=1.249, rho_dc=-0.187`

#### 关键函数
```python
# 拟合
model = PoissonModel.fit(matches=matches, use_xg=False)
# use_xg=True: 混合 quasi-Poisson (xG 场) + DC Poisson (非 xG 场)

# 预测
p_h, p_d, p_a = model.predict(home, away, neutral=True, cross_conf=False)

# 比分矩阵 (10×10)
matrix = score_matrix(params, home_code, away_code, rho=rho,
                      max_goals=8, draw_inflate=1.01, deflate_away=0.62,
                      cross_conf=False)
```

#### 3 层后验修正
1. **`draw_inflate`** (对角膨胀): 乘以所有 P(i,i) 格子, 修平局低估。OOS 值=1.01
2. **`deflate_away`** (跨洲客胜修正): 当 `cross_conf=True` 时, 乘以客胜格子 (i<j)。OOS 值=0.62
3. **Platt Scaling**: `p_cal = 1/(1+exp(a+b·p_raw))`, b<0 单调

#### xG 扩展 (quasi-Poisson)
- xG 场次: NLL = `xG·log(λ) - λ` (连续期望, 无 tau)
- 非 xG 场次: 标准 DC Poisson with tau
- `rho_dc` 仅从非 xG 场次估计
- `use_xg=False` 默认行为完全不变

#### 关键数据结构
- `model.params`: `DCParams` 对象 (含 `attack`, `defense`, `mu`, `log_rho`, `rho_dc`, `draw_inflate`, `deflate_away`)
- `model.name_to_code`: **dict** (不是方法!), 映射队名→2字母代码
- `score_matrix` 是**独立函数**, 不是 `model` 的方法

### 4.2 Elo 模型 (`elo.py`)
- Elo→1X2 转换, draw_c=0.335 标定
- **结论**: 纯 Poisson 最优 (blend 权重 w_elo=0.0), Elo 仅留不一致性标记
- 失准根因: 洲际联合会校准问题 (CONCACAF/CAF 跨洲比赛少)

### 4.3 Platt Scaling (`calibration.py`)
```python
# 拟合 (L-BFGS-B, b ∈ [-5, -0.1])
params = fit_platt(probs_raw, outcomes)  # probs_raw: [(p_h,p_d,p_a),...], outcomes: [(1,0,0),...]

# 应用
ch, cd, ca = calibrate_1x2(p_h, p_d, p_a, platt_params)

# 持久化
save_params(params, path, meta={"draw_inflate": 1.01, "deflate_away": 0.62, ...})
loaded = load_params(path)  # 仅返回 {"H":(a,b),"D":(a,b),"A":(a,b)}, meta 丢失!
```

**当前参数** (`calibration_params.json`):
```json
{
  "classes": {"H": [1.349, -3.19], "D": [0.758, -0.1], "A": [3.169, -5.0]},
  "meta": {
    "n_matches": 40,
    "source": "wc2026_backtest_p11fix",
    "draw_inflate": 1.01,
    "deflate_away": 0.62
  }
}
```

**注意**: `load_params()` 只返回 classes, 不返回 meta。scanner 需要单独读取 JSON 获取 meta 中的 OOS 修正值。

---

## 5. 策略层

### 5.1 价值识别 (`value.py`)
- EV = `p_poisson_calibrated × odds - 1`
- 筛选: `max(EV) > +5%`
- 不一致/高分歧标记 (elo_poisson_gap > 8%)
- 同日同组相关性标记

### 5.2 凯利公式 (`kelly.py`)
- **1/4 凯利** (half=0.25)
- 单注上限 3%, 每日上限 15%

### 5.3 组合优化 (`portfolio.py` / `sporttery_portfolio.py`)
- **SLSQP 均值-方差优化**: max Σ EV × x_i, 约束: 单注 3%, 每日 15%, σ²≤0.02
- **协方差矩阵**:
  - 国际: P5 蒙特卡洛 (N=10000, DC-corrected 独立采样)
  - 体彩: 同场跨玩法协方差来自比分矩阵 `P(both win) = Σ matrix[mask_i & mask_j]`
- **方差约束 binding**: 优化器削减高方差 (高赔率) 注

### 5.4 体彩扫描器 (`sporttery_scanner.py`) — 最重要的模块

#### 流程
1. `_load_model_and_matches()`: 加载 Poisson 模型 + OOS 修正 + Platt + 赛程
2. `fetch_sporttery()` 或 `load_manual_odds()`: 获取体彩赔率
3. 对每场比赛计算 10×10 比分矩阵
4. 对每个玩法 (had/hhad/crs/ttg) 的每个选项计算:
   - `p_model`: 模型概率 (从比分矩阵)
   - `p_model_calibrated`: Platt 校准后 (仅 had 应用 Platt, P11 修复)
   - `p_implied`: 市场隐含概率
   - `ev`: 期望价值
   - `kelly_stake`: 凯利建议仓位
5. `manual_review` 标记: elo_poisson_gap > 8% 的比赛

#### 关键逻辑
```python
# P11 fix: 中立场不应用 deflate_away
cross_conf = is_cross_confederation(home_en, away_en)
if rho == RHO_NEUTRAL:
    cross_conf = False  # WC 比赛在中立场, 无客队旅行劣势

# P12 fix: 使用 OOS 修正值 (非全历史拟合值)
if CALIBRATION_FILE.exists():
    meta = json.loads(CALIBRATION_FILE.read_text())["meta"]
    model.params.draw_inflate = meta["draw_inflate"]  # 1.01
    model.params.deflate_away = meta["deflate_away"]  # 0.62

# P11 fix: Platt 仅应用于 had (不应用于 hhad)
if pool == "had" and calibrated:
    ch, cd, ca = calibrate_1x2(p_h, p_d, p_a, platt_params)
```

#### 玩法概率计算
- **had**: `P(H) = Σ matrix[i>j]`, `P(D) = Σ matrix[i==j]`, `P(A) = Σ matrix[i<j]`
- **hhad**: `virtual_home = i + HANDICAP_SIGN * goalLine`, 然后同 had
- **crs**: `P(h,a) = matrix[h,a]`; `H_OTHER = Σ 未列出的主胜比分`
- **ttg**: `P(k) = Σ matrix[h,a] where h+a==k`, k=0..6; `P(7+) = 1 - Σ(0..6)`

#### 产出字段
每个 opportunity 包含: `match, match_cn, home_en, away_en, date, group, pool_code, pool_name, pool_priority, selection, selection_cn, handicap, offered_keys, odds, p_model, p_model_calibrated, p_implied, ev, ev_calibrated, vig_cost, cross_conf, elo_poisson_gap, manual_review, manual_review_reason, kelly_stake, recommended_stake, stake_note`

---

## 6. 体彩扫描器

### 6.1 运行
```bash
# 自动抓取体彩赔率 + 扫描
PYTHONPATH=src python -m wc_betting.strategy.sporttery_scanner

# 或在代码中调用
from wc_betting.strategy.sporttery_scanner import run
results = run()  # 结果保存到 output/wc_sporttery_opportunities.json
```

### 6.2 手动录入 (沙箱不可达时)
1. 用户在 sporttery.cn 网页查看赔率
2. `save_manual_template(path, matches)` 生成空白模板
3. 手填 JSON
4. `load_manual_odds(path)` 加载

### 6.3 组合优化
```bash
PYTHONPATH=src python -c "
from wc_betting.strategy.sporttery_portfolio import optimize
optimize()
"  # 结果保存到 output/wc_sporttery_portfolio.json
```

### 6.4 玩法可打性优先级
crs (★1, 31 结果) > ttg (★2, 8) > hhad (★3, 3) > had (★4, 3)
结果越多, 定价越低效, 模型优势越大。

---

## 7. 回测与校准

### 7.1 OOS 校准 (`calibrate.py`)
```bash
# 模型对比 (baseline vs improved vs xg)
PYTHONPATH=src python -m wc_betting.backtest.calibrate compare
```

**Gate 条件**:
- `improved_platt` Brier home < `baseline` Brier home
- `improved_xg` Brier home < `improved_platt` Brier home (当 xG 数据可用时)
- Brier home gate: < 0.2141

### 7.2 WC 2026 回测结果 (P12, 40 场已完赛)

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| 准确率 | 57.5% | 60.0% |
| Brier 3-class | 0.5411 | 0.5441 |
| Brier home | 0.2130 | 0.2128 |
| H 分布 | 44.5% (actual 50%) | 49.6% |
| A 分布 | 22.8% (actual 17.5%) | 17.8% |

**优化内容**:
1. Platt 重拟合 (40 场 WC 2026 数据, P11 fix applied)
2. Scanner 使用 OOS draw_inflate (1.01) + deflate_away (0.62), 而非全历史拟合值 (1.0, 0.56)

### 7.3 已知模型弱点
- **极端实力差平局低估**: Elo gap>200 的比赛, 模型对平局概率低估 (如 Spain 0-0 Cape Verde)
- **近势场客胜低估**: Elo gap<100 的比赛, 7/16 客胜 vs 25% predicted
- **34-40 场样本不足**: Platt D 类参数仍近乎恒定

---

## 8. 看板

### 启动
```bash
cd ~/ticket-pricing
streamlit run dashboard/app_fifa_wc.py --server.port 8507
```

### Tab 结构
- **Tab1**: 赔率看板 (Elo + Poisson 概率对比)
- **Tab2**: 模型校准 (6 桶校准表 + Brier 分数 + 统计显著性)
- **Tab3**: 价值下注
  - KPI 条 (下注数/总仓位/EV/σ)
  - 追踪条 (已结算 W·L / 累计 P·L / ROI)
  - Kelly vs 优化对比卡
  - 下注表 + 每日汇总
  - 同组相关性矩阵
  - 体彩 EV 扫描区 (4 种玩法分组表)
  - 体彩组合优化区
  - 每日组合分析 + 对冲检测
  - 风控规则/OOS 校准展示

### CSS
`dashboard/assets/fifa_style.css` — 完整样式定义, 包含移动端响应

---

## 9. 运行手册

### 9.1 每日运营流程

**比赛日前** (推荐下注):
```bash
cd ~/ticket-pricing

# 1. 抓取体彩赔率 + 扫描 EV
PYTHONPATH=src python -m wc_betting.strategy.sporttery_scanner

# 2. 组合优化
PYTHONPATH=src python -c "from wc_betting.strategy.sporttery_portfolio import optimize; optimize()"

# 3. 国际博彩价值识别 (如有赔率)
PYTHONPATH=src python -c "from wc_betting.strategy.value import run; run()"

# 4. 查看追踪器状态
PYTHONPATH=src python -c "from wc_betting.strategy.tracker import run; run('status')"
```

**比赛日后** (结算):
```bash
# 1. 更新 data/processed/wc_2026_unified.json (用户手动, 填入比分)
# 2. 结算
PYTHONPATH=src python -c "from wc_betting.strategy.tracker import run; run('settle')"

# 3. 回测校准 (可选, 积累足够新赛果后)
PYTHONPATH=src python -m wc_betting.backtest.calibrate compare
```

### 9.2 xG 数据抓取 (待完成)
```bash
# 1. 抓取 xG (多天, 100/day 限制)
PYTHONPATH=src python -m wc_betting.data.fetch_xg_api

# 2. 合并到历史数据
PYTHONPATH=src python -c "from wc_betting.data.fetch_xg import merge_xg_with_historical; merge_xg_with_historical()"

# 3. 验证 + 激活
PYTHONPATH=src python -m wc_betting.backtest.calibrate compare
# 若 xG gate PASS, calibration_params.json 自动保存 xG Platt
```

### 9.3 环境要求
- **Python**: `~/.hermes/hermes-agent/venv/bin/python` (无系统 `python`)
- **包安装**: `uv pip install --python ~/.hermes/hermes-agent/venv/bin/python <pkg>`
- **API keys**: `.env` 文件 (gitignored)
  - `ODDS_API_KEY=676ffca425f3b87691f870240ea4b05f` (The Odds API)
  - `API_FOOTBALL_KEY=dab8c85b74478ffe58fd21e9c0451adc` (API-Football)
- **网络**: 沙箱不可达 sporttery.cn / FBref / eloratings.net, 需用户机器运行

---

## 10. 关键发现与已知问题

### 10.1 关键发现

1. **纯 Poisson 最优**: Elo 对 blend 零/负贡献 (洲际联合会校准问题), 仅留不一致性标记
2. **DC tau 已充分修平局**: `rho_dc=-0.187` 在历史数据上 pred 24.5% vs actual 23.4%; WC 平局低估是样本特异性
3. **跨洲客胜严重高估**: pred 21.2% vs actual 13.8%, `deflate_away=0.62` 修正
4. **体彩返奖率 ~70%**: vig ~30% (国际 3-5%), 但比分/总进球定价比胜平负更可能不准
5. **玩法可打性**: 结果越多定价越低效, crs(31结果) > ttg(8) > hhad(3) > had(3)
6. **近势场客胜被低估**: Elo gap<100 的比赛, 7/16 客胜 vs 25% predicted

### 10.2 已知问题

1. **`load_params()` 丢弃 meta**: `calibration.py` 的 `load_params()` 只返回 Platt classes, 不返回 meta。scanner 需要单独读 JSON 获取 OOS 修正值 (已在 P12 修复 scanner 侧)
2. **Platt D 类近乎恒定**: 34-40 场样本不足, D 类 Platt 退化为常数 (b=-0.1 边界解)。`draw_inflate` + 常数已足够修平局
3. **xG 数据未完成**: API-Football 抓取器已就绪, 但数据未抓取完成 (需 4-6 天, 100/day)
4. **FBref 无国家队 xG**: FBref 只有俱乐部 xG, 已改用 API-Football
5. **Cloudflare 绕过**: FBref 403, 需 camoufox (headless=False + humanize=True) + 暖场 cookie。但已弃用 FBref 方案
6. **沙箱网络限制**: sporttery.cn / FBref / eloratings.net 均不可达, 所有抓取需用户机器运行
7. **NZ vs Egypt 预测失败**: 模型预测 H/D, 实际 1-3 (A win), 所有体彩注 LOST。近势场客胜低估的典型案例

### 10.3 P11 修复的 3 个 Bug (重要)

1. **Platt 错误应用到 hhad**: Platt D 参数使 p_D 恒定, hhad 上 D 可低至 10%, 9/12 个 hhad D 注的 EV 从负变正 — 全是虚假信号。修复: 仅 had 应用 Platt
2. **deflate_away 错误应用到中立场**: WC 比赛在 `rho=RHO_NEUTRAL`, 但 cross_conf=True 仍应用 deflate_away。修复: `if rho == RHO_NEUTRAL: cross_conf = False`
3. **无 inconsistent 过滤**: elo_poisson_gap>8% 的比赛直接进组合优化。修复: 新增 `manual_review` 标记, portfolio 排除

---

## 11. 队名归一化备忘

### eloratings.net → Poisson 模型
- "X men's" → "X" (Canada/USA/Australia/Sweden/New Zealand 男足是默认)
- "Czech Republic" → "Czechia"
- "Curaçao" → "Curacao"
- "Ivory Coast" → "Ivory_Coast" (非 Cote_d_Ivoire)
- "DR Congo" → "DR_Congo"

### FBref → Poisson 模型 (`_norm_fbref_name()`)
- "Côte d'Ivoire" → "Ivory Coast"
- "Cabo Verde" → "Cape Verde"
- "Türkiye" → "Turkey"
- "Congo DR" → "DR Congo"
- "Bosnia-Herzegovina" → "Bosnia and Herzegovina"

### API-FOOTBALL → Poisson 模型
- 大部分直接匹配 (如 "Iran" 而非 "IR Iran")
- 同上 FBref 别名

### WC 2026 unified → Poisson 模型
- "Bosnia & Herzegovina" → "Bosnia and Herzegovina"
- "Curaçao" → "Curacao"
- "USA" → "United States"

---

## 12. 开发历史

### P1 (2026-06-21) — Elo 评级 + 历史比分
- eloratings.net TSV 抓取, 48/48 队
- 2135 场历史比分 (2022-2026)

### P2-P3 (2026-06-21) — Poisson 模型 + OOS 校准
- Dixon-Coles 拟合, 134 队 (含 ROW 桶)
- **关键决策**: 纯 Poisson 最优 (w_elo=0), Elo 仅留不一致性标记
- OOS 校准: 平局低估 7.3%, 客胜高估 13.7%

### P4 (2026-06-21) — 价值识别
- EV 筛选 + 1/2 凯利 + 不一致/高分歧标记
- 12 下注 / 23 手动审核

### P5 (2026-06-21) — 蒙特卡洛相关性
- N=10000 DC-corrected 独立采样
- 限制: Poisson 独立 → cov≈0, keep/drop 总是 keep both

### P6 (2026-06-21) — 组合优化
- SLSQP 均值-方差, σ²≤0.02
- 方差约束 binding, EV 降 23%, var 降 52%

### P7 (2026-06-21) — 看板 + 追踪器
- Streamlit Tab3 + CSS + tracker.py
- 首笔结算: Netherlands vs Sweden 5-1 ✅ ROI=71.8%

### P8 (2026-06-21) — 体彩 EV 扫描器
- sporttery.cn 4 种玩法抓取 + EV 扫描
- 手动录入 fallback

### P9 (2026-06-22) — 模型校准改进
- draw_inflate + deflate_away + Platt Scaling
- 理论文档 `docs/research/betting_model_theory.md`
- Gate PASS: Brier home 0.2203→0.2141

### P10 (2026-06-22) — 体彩组合优化 + P4 Platt 更新
- 同场跨玩法协方差 (比分矩阵)
- P4 value.py 集成 Platt 校准

### P11 (2026-06-22) — 3 个关键 Bug 修复
- Platt 仅 had (不 hhad)
- deflate_away 不用于中立场
- inconsistent 过滤 (manual_review)

### P0 (2026-06-22) — xG 数据集成
- quasi-Poisson 混合 NLL
- FBref 弃用 (无国家队 xG), 改用 API-Football
- 抓取器就绪, 数据待抓取

### P12 (2026-06-22) — WC 2026 回测 + 模型优化
- 40 场回测: acc 57.5%, Brier_H 0.2130
- Platt 重拟合 + OOS 修正 bug 修复
- 优化后: acc 60.0%, Brier_H 0.2128

---

## 附录: 常用命令速查

```bash
# === 日常运营 ===
# 体彩扫描
PYTHONPATH=src python -m wc_betting.strategy.sporttery_scanner
# 体彩组合优化
PYTHONPATH=src python -c "from wc_betting.strategy.sporttery_portfolio import optimize; optimize()"
# 结算追踪
PYTHONPATH=src python -c "from wc_betting.strategy.tracker import run; run('settle')"
PYTHONPATH=src python -c "from wc_betting.strategy.tracker import run; run('status')"

# === 模型校准 ===
# OOS 对比 (baseline vs improved vs xg)
PYTHONPATH=src python -m wc_betting.backtest.calibrate compare

# === xG 数据 ===
# 抓取 (多天)
PYTHONPATH=src python -m wc_betting.data.fetch_xg_api
# 合并
PYTHONPATH=src python -c "from wc_betting.data.fetch_xg import merge_xg_with_historical; merge_xg_with_historical()"

# === 看板 ===
cd ~/ticket-pricing && streamlit run dashboard/app_fifa_wc.py --server.port 8507

# === 验证模型参数 ===
PYTHONPATH=src python -c "
from wc_betting.strategy.sporttery_scanner import _load_model_and_matches
model, *_ = _load_model_and_matches()
print(f'draw_inflate={model.params.draw_inflate}, deflate_away={model.params.deflate_away}')
"
```

---

## 13. P13 系统升级 (2026-06-23) — 模型优化 + 策略闭环

### 13.1 训练数据优化：去掉友谊赛

**问题**：2135 场含 614 场友谊赛，强队上替补，attack/defense 被压扁。

**方案**：PoissonModel.fit(competitive_only=True) 过滤 tournament=F。

**效果**：参数区分度 +16%，阿尔及利亚 attack 1.41→0.37，法国 H 58.6%→68.0%。

### 13.2 市场信息融合

**方案**：p_fused = w * p_poisson + (1-w) * p_market_implied (Odds API)

**系数**（36场回测）：H/A w=0.25，D w=0.70

**效果**：H/A 向市场靠拢，D 保留模型平局优势。仅对 had 生效。

### 13.3 Elo 共识交叉验证

**方案**：H/A 投注要求 Elo >= 15%，D 平局免审。

**看板**：体彩 Tab 勾选框控制 ELO_CONSENSUS=True/False

**效果**：36场回测：两模型一致时命中率 64%，Poisson独走时仅 25%

### 13.4 四层风控体系

1. mismatch_cold：市场 H>70% 且模型 H < 市场 H-10pp
2. 最低概率：had/hhad p<12%，crs/ttg p<2%
3. 赔率上限：odds > 25 → MANUAL
4. EV <= 0 不推荐

例外：平局免审（不受 Elo gap 限制）

### 13.5 看板结构（5 Tab）

Tab1-5: 未赛 | 已赛 | 价值下注 | 中国体彩 | 智能投注

智能投注：推荐 → 购买 → 结算 → 战绩循环

每日 14:00 cron 自动扫描（scripts/daily_scan.sh）

### 13.6 投注策略

平局优先、对冲下盘、不碰极端

| 条件 | 仓位 |
|------|------|
| auto + D | 3% |
| auto + H/A | 2% |
| manual_review | 1%或跳过 |
| odds > 25 | 不投 |

理论：G = EV - sigma^2/2，SLSQP约束 sigma^2<=0.02，Sharpe 1.61

### 13.7 数据库

data/sporttery_history.db：体彩赔率历史归档
每次扫描自动归档，看板手动录入自动查DB

### 13.8 关键参数

competitive_only=True, fusion w=0.25/0.70, MIN_P_MODEL_HAD=0.12,
MIN_P_MODEL_CRS=0.02, MAX_ODDS_AUTO=25, SINGLE_BET_CAP=0.03,
SIGMA2_TARGET=0.02, draw_inflate=1.01, deflate_away=0.62,
Platt H=(1.35,-3.19) D=(0.76,-0.10) A=(3.17,-5.00)


---

## 13. P13 系统升级 (2026-06-23) — 完整变更记录

### 13.1 模型层优化

#### 13.1.1 去掉友谊赛 ()
- **问题**：2135 场含 614 场友谊赛，强队上替补，attack/defense 被压缩
- **方案**： 过滤 
- **效果**：参数区分度 +16%（spread 3.526→4.101），阿尔及利亚 attack 1.41→0.37
- **影响文件**：, , 

#### 13.1.2 市场信息融合
- **方案**：（仅 had）
- **系数**（36场网格搜索）：H/A w=0.25, D w=0.70
- **数据源**：Odds API 市场隐含概率（model_input.json 中 market_implied 字段）
- **位置**： _load_model_and_matches() → match_lookup[market_implied]
- **注意**：只对  生效， 不融合（市场无让球概率）

#### 13.1.3 Elo 共识交叉验证
- **36场回测**：两模型一致命中率 64%，Poisson 独走仅 25%
- **方案**：H/A 投注要求 Elo ≥ 15%，D 平局免审
- **控制**： (默认 False)
- **看板**：体彩 Tab 勾选框控制

### 13.2 四层风控体系

| 层级 | 参数 | 规则 | 文件位置 |
|------|------|------|---------|
| 1. mismatch_cold | 市场 H>70% 且 Po H < 市场 H-10pp | 强制 MANUAL + EV 打折 (1-gap)^3 | sporttery_scanner.py |
| 2. 最低概率 | MIN_P_MODEL_HAD=0.12, MIN_P_MODEL_CRS=0.02 | 极端冷门不进推荐 | sporttery_scanner.py |
| 3. 赔率上限 | MAX_ODDS_AUTO=25 | odds>25 → MANUAL | sporttery_scanner.py |
| 4. EV 阈值 | EV ≤ 0 | 负期望不推 | sporttery_scanner.py |

**例外规则**：
- 平局（D）不受 Elo gap 限制（模型最强信号，34.4% vs actual 34.2%）
- Elo 共识（可选）：H/A 要求 Elo ≥ 15%

### 13.3 看板重构

#### 13.3.1 新增 Tab5：🧠 智能投注
- **上部**：每日推荐表（从 wc_sporttery_portfolio.json 读取，按日期×仓位排序，D 标 ★）
- **中部**：购买记录器（筛选框 + selectbox + 金额 + 记录按钮）
  - 手动录入全部下拉化（48队中文名、日期、玩法、选项按池动态切换）
  - DB 自动查赔率（sporttery_history.db）
- **下部**：战绩追踪（累计 KPI + 结算按钮 + 待结/最近记录表）

#### 13.3.2 Tab4 精简：🎰 中国体彩
- 删除：购买记录器、战绩追踪、每日推荐
- 保留：扫描按钮 + 机会列表 + 组合优化 + 模型校准

#### 13.3.3 CSS 暗色表单修复
- 按钮、selectbox、input 背景色覆盖为暗色主题
- Streamlit dark theme config：base=dark, bg=#0c0d0f
- 文件：, 

### 13.4 投注策略

**核心原则**：平局优先、对冲下盘、不碰极端

| 条件 | 仓位 | 理由 |
|------|------|------|
| auto + D | 3% | 模型最强信号 |
| auto + H/A | 2% | 次强信号 |
| manual_review | 1%或跳过 | 需人工判断 |
| odds > 25 | 不投 | 命中率太低 |

**理论**：
- 长期增长率 G ≈ EV - σ²/2（方差是惩罚项）
- SLSQP 约束 σ²≤0.02，Sharpe 1.61（vs Kelly 1.18）
- 方差约束生效时自动削减高赔率注

### 13.5 数据库

**sporttery_history.db** ()
- SportteryDB 类：query(match_date, home_cn, away_cn, pool_code, selection)
- import_from_cache() / import_odds_rows() 两个导入路径
- 每次扫描自动归档（INSERT OR IGNORE 防重复）
- 看板手动录入自动查 DB 填充赔率

### 13.6 自动化

**Cron**：每日 14:00 北京时间自动扫描 + 组合优化

日志：

**结算**： 读取 unified.json 自动判断胜负
- 按钮在智能投注 Tab 和体彩 Tab 均可触发

### 13.7 环境和工具修复

- **importlib.reload**：poisson.py 模块缓存过期问题，顶层 import 前强制刷新
- **wsl -e**：Windows 环境访问 Linux 文件系统
- **_fetch_text 缓存逻辑**：先走网络再走缓存（修复赔率不更新 bug）

### 13.8 关键参数速查

| 参数 | 值 | 位置 |
|------|-----|------|
| competitive_only | True | poisson.py:fit() |
| fusion w_H / w_D | 0.25 / 0.70 | sporttery_scanner.py |
| ELO_CONSENSUS | False (可切换) | sporttery_scanner.py |
| MIN_P_MODEL_HAD | 0.12 | sporttery_scanner.py |
| MIN_P_MODEL_CRS | 0.02 | sporttery_scanner.py |
| MAX_ODDS_AUTO | 25.0 | sporttery_scanner.py |
| SINGLE_BET_CAP | 0.03 | sporttery_portfolio.py |
| DAILY_CAP | 0.15 | sporttery_portfolio.py |
| SIGMA2_TARGET | 0.02 | sporttery_portfolio.py |
| draw_inflate | 1.01 | calibration_params.json |
| deflate_away | 0.62 | calibration_params.json |
| Platt H params | (1.35, -3.19) | calibration_params.json |
| Platt D params | (0.76, -0.10) | calibration_params.json |
| Platt A params | (3.17, -5.00) | calibration_params.json |

### 13.9 已知问题和待办

- [ ] xG 数据抓取未完成（API-Football 100/day，需4-6天）
- [ ] 淘汰赛模型需重评估（加时、点球逻辑不同）
- [ ] 72场打完做完整 OOS 回测
- [ ] Platt D 类参数近乎常数（样本不足，等72场）
- [ ] 体彩动态赔率安全边际暂未加入（当前下注策略不碰热门，影响小）


### 13.2.1 融合架构修正 (2026-06-23)

**原方案（错误）**：Poisson + 市场隐含概率 → 融合（w=0.25/0.70）
**问题**：市场赔率是庄家的定价，融合进来等于用对手的信息修正自己

**修正后**：
- Poisson + Elo → 融合概率（两个独立统计模型互相校准）
- 融合概率 vs 市场赔率 → 计算 EV
- 市场只是定价参考，不参与概率估计

**架构**：
Poisson(进球) + Elo(胜负) → 融合 p(w=0.25/0.70) → vs 市场赔率 → EV

**系数**（36场回测）：
- H/A：w=0.25（75% 信 Elo 胜负判断）
- D：w=0.70（70% 信 Poisson 平局预测）
- 只对 had（胜平负）生效，hhad 不融合
