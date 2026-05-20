# 国安票务动态定价看板 — 实施计划

> **For Cursor:** 按任务顺序逐条执行。Hermes = 计划者（待命澄清）。

**目标:** 将 CLI 定价模型做成可交互、可检验的 Streamlit 看板，用于 2026 赛季每场比赛的定价决策。

**架构:** Streamlit 单页应用，调用现有 `src/` 模块，Sentry 暗色主题，自上而下布局，端口 8504。

**技术栈:** Python 3.11, Streamlit, pandas, matplotlib, 现有 src/ 模块

**仓库:** `~/ticket-pricing/`

---

## 设计原则

- **Sentry 暗色**: `#1f1633` 背景 + `#c2ef4e` 强调色
- **系统字体**: 无自定义字体，`-apple-system, sans-serif`
- **自上而下**: 无侧边栏，一页到底
- **三层结构**: 顶部执行摘要（定价建议→行动） → 中部原因（弹性/需求分析） → 底部交叉验证（回测/对账）
- **不前置原始警告**: 错误/边界情况放底部

---

## 页面布局

```
┌──────────────────────────────────────────────────┐
│  国安票务动态定价                                   │
│  2026赛季 比赛选择 + 情境参数                          │
├──────────────────────────────────────────────────┤
│  ═══════ 定价建议（行动层）═══════                    │
│  6档位定价表 + 收入/上座率预测                         │
├──────────────────────────────────────────────────┤
│  ═══════ 原因分析 ═══════                           │
│  需求弹性曲线 | 需求乘数分解 | 容量利用                  │
├──────────────────────────────────────────────────┤
│  ═══════ 交叉验证 ═══════                           │
│  2025回测 | 模型vs实际 | 数据对账                     │
└──────────────────────────────────────────────────┘
```

---

## Task 0: 环境准备

```bash
cd ~/ticket-pricing
pip install streamlit matplotlib -q
mkdir -p dashboard
```

---

## Task 1: 看板入口 `dashboard/app.py` — 页面框架 + 参数面板

**目标:** 搭建 Streamlit 页面骨架，Sentry 暗色主题，顶部比赛选择+情境参数

**文件:** Create `dashboard/app.py`

```python
"""国安票务动态定价看板"""
import streamlit as st
import sys
from pathlib import Path

# 项目根加入 path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

st.set_page_config(
    page_title="国安票务定价",
    page_icon="⚽",
    layout="wide",
)

# === 暗色主题 CSS ===
st.markdown("""
<style>
    .stApp { background-color: #1f1633; color: #e0dce8; }
    .stApp header { background: transparent; }
    section[data-testid="stSidebar"] { display: none; }
    h1, h2, h3 { color: #c2ef4e; font-family: -apple-system, sans-serif; }
    .stMetric label { color: #9b8fb8 !important; }
    .stMetric [data-testid="stMetricValue"] { color: #c2ef4e; font-size: 2rem; }
    .price-up { color: #ff6b6b; }
    .price-down { color: #51cf66; }
    .price-flat { color: #9b8fb8; }
    div[data-testid="stHorizontalBlock"] { gap: 0.5rem; }
    .stDataFrame { background: #2a1f3d; }
</style>
""", unsafe_allow_html=True)

# === 标题 ===
st.title("⚽ 北京国安 票务动态定价")
st.caption("2026赛季 · 散票定价决策看板")

# === 顶部参数区（两行） ===
col1, col2, col3, col4 = st.columns(4)
with col1:
    opponent = st.selectbox("对手", [
        "上海申花", "上海海港", "山东泰山", "成都蓉城",
        "天津津门虎", "武汉三镇", "浙江俱乐部", "长春亚泰",
        "河南俱乐部", "深圳新鹏城", "青岛西海岸", "云南玉昆",
        "大连英博海发", "青岛海牛", "梅州客家",
    ])
with col2:
    is_weekend = st.toggle("周末场次", value=True)
with col3:
    season_stage = st.selectbox("赛季阶段",
        ["mid", "crucial", "title_race", "relegation"],
        format_func=lambda x: {"mid":"常规","crucial":"关键战","title_race":"争冠","relegation":"保级"}[x]
    )
with col4:
    revenue_weight = st.slider("收入权重 ω", 0.1, 1.0, 0.6, 0.1,
        help="0=纯上座率最大化, 1=纯收入最大化")

col5, col6, col7, col8 = st.columns(4)
with col5:
    opponent_standing = st.slider("对手排名", 1, 16, 8)
with col6:
    home_form = st.slider("国安近态胜率", 0.0, 1.0, 0.5, 0.05)
with col7:
    temperature = st.slider("气温 ℃", -10, 40, 20)
with col8:
    precipitation = st.slider("降水量 mm", 0, 100, 0)

st.divider()
```

---

## Task 2: 看板入口 — 定价建议表（行动层）

**目标:** 调用现有模型，输出 6 档位定价表 + KPI 卡片

**文件:** Modify `dashboard/app.py`（追加到 Task 1 后面）

```python
# === 调用模型 ===
from src.classify import classify_match_hybrid, build_base_multiplier_lookup
from src.elasticity import fit_elasticity_from_transactions
from src.ingest import load_all
from src.optimize import optimize_multi_tier
from src.cli import _build_tier_models, TIER_CAPACITIES, TIER_ORDER

@st.cache_data(ttl=3600)
def load_model_data():
    """加载并缓存模型数据（1小时有效）"""
    demand_df = load_all("data/raw")
    base_lookup = build_base_multiplier_lookup("data/raw/2025散票数据.xlsx")
    txn_el = fit_elasticity_from_transactions("data/raw/25年散票用户购买记录更新.xlsx")
    return demand_df, base_lookup, txn_el

demand_df, base_lookup, txn_el = load_model_data()

tier, mult = classify_match_hybrid(
    opponent, base_lookup=base_lookup,
    opponent_standing=opponent_standing,
    is_weekend=is_weekend,
    season_stage=season_stage,
    home_form=home_form,
    temperature_c=temperature,
    precipitation_mm=precipitation,
)

models = _build_tier_models(demand_df, tier, txn_el)
caps = dict(TIER_CAPACITIES)
result = optimize_multi_tier(models, caps, demand_multiplier=mult, revenue_weight=revenue_weight, tier_order=TIER_ORDER)

# === KPI 卡片 ===
total_cap = sum(caps.values())
k1, k2, k3, k4 = st.columns(4)
k1.metric("比赛级别", f"{tier}级", f"乘数 {mult:.3f}×")
k2.metric("预计收入", f"¥{result.total_revenue:,.0f}")
k3.metric("预计上座", f"{result.total_attendance:,.0f}人",
          f"{result.attendance_rate*100:.0f}%")
# 计算收入变动
baseline_rev = sum(models[t].base_price * models[t].base_demand * mult for t in TIER_ORDER)
rev_change = (result.total_revenue - baseline_rev) / baseline_rev * 100 if baseline_rev else 0
k4.metric("收入变动", f"{rev_change:+.1f}%", "vs 基准定价")

st.divider()

# === 定价建议表 ===
st.subheader("📋 定价建议")
rows = []
for name in TIER_ORDER:
    base = models[name].base_price
    opt = result.optimal_prices[name]
    pct = (opt - base) / base * 100
    dem = result.predicted_demand[name]
    rev = result.tier_revenue[name]
    cap = caps[name]
    
    color = "price-up" if pct > 3 else "price-down" if pct < -3 else "price-flat"
    rows.append({
        "档位": name,
        "基准价": f"¥{base:,.0f}",
        "建议价": f"¥{opt:,.0f}",
        "变动": f"{pct:+.0f}%",
        "预测需求": f"{dem:,.0f}/{cap:,}",
        "档位收入": f"¥{rev:,.0f}",
        "_color": color,
    })

# 渲染为 HTML 表格（支持颜色）
html = "<table style='width:100%; border-collapse:collapse;'>"
html += "<tr style='color:#9b8fb8; border-bottom:1px solid #3a2f55;'>"
for h in ["档位","基准价","建议价","变动","预测需求","档位收入"]:
    html += f"<th style='padding:8px; text-align:right;'>{h}</th>"
html += "</tr>"
for r in rows:
    html += f"<tr style='border-bottom:1px solid #2a1f3d;'>"
    html += f"<td style='padding:8px;'>{r['档位']}</td>"
    html += f"<td style='padding:8px; text-align:right;'>{r['基准价']}</td>"
    html += f"<td style='padding:8px; text-align:right; font-weight:bold;'>{r['建议价']}</td>"
    html += f"<td style='padding:8px; text-align:right; color:{'#ff6b6b' if '+' in r['变动'] else '#51cf66'};'>{r['变动']}</td>"
    html += f"<td style='padding:8px; text-align:right;'>{r['预测需求']}</td>"
    html += f"<td style='padding:8px; text-align:right;'>{r['档位收入']}</td>"
    html += "</tr>"
html += "</table>"
st.markdown(html, unsafe_allow_html=True)
```

---

## Task 3: 原因分析区 — 弹性曲线 + 乘数分解

**目标:** 展示「为什么是这个价格」，可视化弹性曲线和乘数构成

**文件:** Modify `dashboard/app.py`（追加）

```python
st.divider()
st.subheader("🔍 原因分析")

c1, c2 = st.columns([3, 2])

with c1:
    # 需求弹性曲线
    import matplotlib.pyplot as plt
    import numpy as np
    
    fig, ax = plt.subplots(figsize=(6, 3.5))
    fig.patch.set_facecolor('#1f1633')
    ax.set_facecolor('#1f1633')
    
    for name in TIER_ORDER:
        m = models[name]
        prices = np.linspace(m.base_price * 0.5, m.base_price * 2.0, 50)
        demands = [min(m.predict(p) * mult, caps[name]) for p in prices]
        ax.plot(prices, demands, label=name, linewidth=1.5)
    
    ax.set_xlabel("价格 (¥)", color='#9b8fb8')
    ax.set_ylabel("预测需求 (人)", color='#9b8fb8')
    ax.set_title("各档位需求弹性曲线", color='#c2ef4e')
    ax.legend(fontsize=8, loc='upper right')
    ax.tick_params(colors='#9b8fb8')
    ax.spines['bottom'].set_color('#3a2f55')
    ax.spines['left'].set_color('#3a2f55')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.grid(alpha=0.15, color='#9b8fb8')
    
    st.pyplot(fig)

with c2:
    # 乘数分解
    st.markdown(f"**需求乘数: {mult:.3f}×**")
    st.markdown(f"弹性系数 ε: {txn_el.elasticity:.2f} (R²={txn_el.r_squared:.2f})")
    
    # 乘数拆解
    base = base_lookup.get(opponent, 1.0)
    ctx = mult / base if base else 1.0
    st.markdown(f"""
    | 因子 | 值 |
    |------|-----|
    | 基础乘数 (对手) | {base:.3f}× |
    | 情境调节 | {ctx:.3f}× |
    | **最终乘数** | **{mult:.3f}×** |
    """)
    
    st.caption(f"情境因子: 周末={is_weekend}, 排名={opponent_standing}, 赛程={season_stage}, 胜率={home_form}")
```

---

## Task 4: 交叉验证区 — 2025回测

**目标:** 验证模型预测 vs 2025实际数据

**文件:** Modify `dashboard/app.py`（追加）

```python
st.divider()
st.subheader("📊 交叉验证: 2025赛季回测")

@st.cache_data(ttl=3600)
def run_backtest():
    """2025赛季全量回测"""
    from src.ingest import load_seat_data
    seats = load_seat_data("data/raw/2025散票数据.xlsx")
    
    results = []
    for match_id in seats["match_id"].unique():
        md = seats[seats["match_id"] == match_id]
        opp = md["opponent"].iloc[0]
        actual = len(md)
        
        tier, mult = classify_match_hybrid(opp, base_lookup=base_lookup, is_weekend=True)
        models_bt = _build_tier_models(demand_df, tier, txn_el)
        caps_bt = dict(TIER_CAPACITIES)
        opt = optimize_multi_tier(models_bt, caps_bt, demand_multiplier=mult, tier_order=TIER_ORDER)
        
        results.append({
            "match_id": match_id,
            "opponent": opp,
            "tier": tier,
            "multiplier": mult,
            "actual": actual,
            "predicted": opt.total_attendance,
            "revenue_pred": opt.total_revenue,
        })
    
    import pandas as pd
    return pd.DataFrame(results)

bt = run_backtest()
bt["error_pct"] = (bt["predicted"] - bt["actual"]) / bt["actual"] * 100

# 回测图表
fig2, ax2 = plt.subplots(figsize=(8, 4))
fig2.patch.set_facecolor('#1f1633')
ax2.set_facecolor('#1f1633')

x = range(len(bt))
ax2.bar(x, bt["actual"], width=0.35, label="实际", color='#c2ef4e', alpha=0.8)
ax2.bar([i+0.35 for i in x], bt["predicted"], width=0.35, label="预测", color='#ff6b6b', alpha=0.8)
ax2.set_xticks([i+0.175 for i in x])
ax2.set_xticklabels(bt["opponent"].str[:4], rotation=45, color='#9b8fb8', fontsize=8)
ax2.set_ylabel("散票数", color='#9b8fb8')
ax2.legend()
ax2.tick_params(colors='#9b8fb8')
ax2.spines['bottom'].set_color('#3a2f55')
ax2.spines['left'].set_color('#3a2f55')
ax2.spines['top'].set_visible(False)
ax2.spines['right'].set_visible(False)
ax2.grid(alpha=0.15, color='#9b8fb8', axis='y')
st.pyplot(fig2)

# 回测指标
mae = abs(bt["error_pct"]).mean()
c1, c2, c3 = st.columns(3)
c1.metric("平均误差", f"{mae:.0f}%")
c2.metric("预测总收入", f"¥{bt['revenue_pred'].sum():,.0f}")
c3.metric("实际散票总张数", f"{bt['actual'].sum():,}")
```

---

## Task 5: 启动脚本

**目标:** 一行命令启动看板

**文件:** Create `dashboard/serve.sh`

```bash
#!/bin/bash
# 国安票务定价看板 — 端口 8504
cd "$(dirname "$0")/.."
streamlit run dashboard/app.py --server.port 8504 --server.headless true --theme.base dark
```

```bash
chmod +x dashboard/serve.sh
```

---

## Task 6: 数据对账区（底部）

**目标:** 模型预测 vs 用户交易数据交叉验证

**文件:** Modify `dashboard/app.py`（追加到最底部）

```python
st.divider()
st.subheader("📋 数据对账")

with st.expander("座位数据 vs 用户交易流水（按票面价）"):
    from src.ingest import crosscheck_seat_demand_vs_user_purchases, load_user_purchases_by_price
    user_prices = load_user_purchases_by_price("data/raw/25年散票用户购买记录更新.xlsx")
    cc = crosscheck_seat_demand_vs_user_purchases(demand_df, user_prices)
    st.dataframe(cc, use_container_width=True, hide_index=True)
```

---

## Task 7: 模型报告导出（底部按钮）

**目标:** 一键下载当前定价建议为 CSV

**文件:** Modify `dashboard/app.py`（追加到末尾）

```python
st.divider()
c1, c2 = st.columns([1, 5])
with c1:
    import io
    csv_data = io.StringIO()
    csv_data.write("档位,基准价,建议价,变动%,预测需求,档位收入\n")
    for name in TIER_ORDER:
        base = models[name].base_price
        opt = result.optimal_prices[name]
        pct = (opt - base) / base * 100
        csv_data.write(f"{name},{base:.0f},{opt:.0f},{pct:+.0f}%,{result.predicted_demand[name]:.0f},{result.tier_revenue[name]:.0f}\n")
    
    st.download_button(
        "📥 导出 CSV",
        csv_data.getvalue(),
        f"定价建议_{opponent}_{tier}级.csv",
        "text/csv",
    )
```

---

## 验证

```bash
# 启动看板
bash dashboard/serve.sh

# 浏览器打开 http://localhost:8504
```

预期:
- 暗色主题，无侧边栏
- 顶部选对手+调参数 → 实时更新定价表
- KPI 卡片显示收入/上座率/收入变动
- 弹性曲线图含 6 条档位线
- 底部回测柱状图对比预测 vs 实际
- 导出 CSV 按钮可用

---

## 执行顺序

Task 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7

每个 Task 完成后 `git add -A && git commit -m "..."`。
