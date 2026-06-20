# V5.6 赔率信号 — 看板展示模块

**日期**: 2026-06-20
**路径**: 路径 3 (不接入 rule_engine, 仅展示)
**作者**: Hermes Agent

---

## 产出

1. `dashboard/tabs/tab_odds.py` (8445 字节) — 赔率展示模块
2. `dashboard/app_v8.py` — 新增 tab 8「🎲 赔率信号」
3. `data/raw/odds/csl_odds_20260620.json` — 首次拉取的赔率快照

---

## 数据流

```
The Odds API (周更一次)
  ↓ curl
data/raw/odds/csl_odds_YYYYMMDD.json
  ↓ _load_latest_odds()
dashboard.tabs.tab_odds.render_odds_tab()
  ↓ Streamlit V8 第 8 tab
用户可视化
```

---

## 看板功能

### 顶部
- 拉取日期
- 全部未来场次列表 (n=8)
- 赔率公司数 (n=10~17)

### 国安场卡片 (逐场)
- 🏠/✈️ 标识主客场
- 🔥 S 级大场高亮
- 4 个 KPI:
  - 博彩公司数
  - **p_home 均值** (隐含主场胜率)
  - **p_home 中位数**
  - **建议乘数** (🟢/🔴/⚪ + 触发原因)
- 公司明细表 (odds / p_home / vig),按 p_home 降序

### V2 信号规则

```python
if opponent_tier in ('S', 'A'):           # 大场
    if p_home >= 0.55: return 1.05        # 市场看好 → +5%
    if p_home <= 0.35: return 0.92        # 市场看低 → -8%
if p_home >= 0.65: return 1.03            # 极端看好 → +3% (任何场次)
if p_home <= 0.30: return 0.95            # 极端看低 → -5%
return 1.00                               # 中性 → 不触发
```

---

## 6/27 国安 vs 武汉三镇 信号输出

| 指标 | 值 |
|---|---|
| 博彩公司数 | 10 |
| p_home 范围 | 0.648 ~ 0.674 |
| **p_home 均值** | **0.664 (66.4%)** |
| 建议乘数 | 🟢 **1.03** (极端看好) |
| 触发原因 | p_home ≥ 0.65 (B 级场次,非大场,故只给 +3% 而非 +5%) |

---

## ⚠️ 路径 3 承诺(铁律)

1. **不动 `rule_engine.py`** — 赔率信号只展示,不进 predict()
2. **不动 `csl_context.py`** — 不注入任何乘数
3. **不动 `dynamic_optimizer.py`** — 容量/份额不受影响
4. **不动 H2 目标** — `h2_2026_match_targets.json` 不重算
5. **只动 dashboard** — 看板 + 数据快照

---

## 周更 cron 建议(待用户决策)

```cron
0 9 * * 1  cd /home/xxxsuli/ticket-pricing && \
  curl -s "https://api.the-odds-api.com/v4/sports/soccer_china_superleague/odds/?regions=eu&markets=h2h&oddsFormat=decimal&apiKey=XXX" \
  > data/raw/odds/csl_odds_$(date +\%Y\%m\%d).json
```

500 次/月 免费档够用(每周 1 次 = 4 次/月,还剩 496 次给突发)。

---

## 回测触发条件

**等 8 月大场样本到 5+ 场再做**:
- 收集 2026-08 ~ 2026-11 期间国安主场 S 级对手场次
- 期望样本数: 上海申花 / 上海海港 / 山东泰山 / 成都蓉城 各 1~2 场
- 触发后:
  1. 把赔率 p_home 作为"事前信号"
  2. 对比 V5.5 残差(actual/predicted)
  3. 看残差是否与 |p_home - 0.50| 同向

---

## 关闭议题(临时)

- ❌ 不写 fetcher.py(curl 一行够了)
- ❌ 不写 implied_prob.py(在 tab 里算就行)
- ❌ 不集成 rule_engine(等大场样本)
- ✅ 仅展示

---

**Status**: 看板 V8 第 8 tab 已上线,本地 streamlit :8506 可看。后续每周拉一次数据,8 月大场样本到后再决定是否进 rule_engine。