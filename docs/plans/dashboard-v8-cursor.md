# 看板 V8 重构任务单

> 创建: 2026-05-27 · 状态: 待执行 · 执行方式: Cursor

## 目标

将看板从「线性堆叠」重构为「时间线导航 + 统一卡片 + 趋势图」，提升运营使用效率。

## 设计稿

```
┌──────────────────────────────────────────────────┐
│ KPI 行: 赛季收入 | 场均上座(上座率%) | MAE | 积分#排名 | 下一主场  │
├──────────────────────────────────────────────────┤
│ 赛季时间线: ●申 ●成 ●天 ●大 ●海 ●牛 ●河 ○武 ○山 ○辽 ...  │
│ (实心=已赛 绿W/红L/黄D  空心=未来 灰  选中=白边框高亮)    │
├──────────────────────────────────────────────────┤
│ ▼ vs 上海申花 · 3/21 周六 · S级德比 · 容量 18,000       │
│ ┌──────────────────────────────────────────────┐ │
│ │ 上座: ████████████░░░░ 预测 14,635 (81%)      │ │
│ │       ██████████████░░ 实际 15,482 (86%)      │ │
│ │       误差 -847 (-5.5%)                      │ │
│ │ ───────────────────────────────────          │ │
│ │ 预测链: [基值S 11,900] [揭幕 ×1.15] [周六 ×1.05]  │ │
│ │         [校准 ×1.02] = 14,635                │ │
│ │ ───────────────────────────────────          │ │
│ │ 定价: 收入优先 Δ+28.3万                        │ │
│ │ T1 ¥310→310 T2 ¥400→420 T3 ¥510→560         │ │
│ │ T4 ¥630→680 T5 ¥890→980 T6 ¥1500→1650       │ │
│ │ ───────────────────────────────────          │ │
│ │ 近期: L @武汉 0-2  W vs山东 3-1  D vs辽宁 1-1  │ │
│ └──────────────────────────────────────────────┘ │
├──────────────────────┬───────────────────────────┤
│ 📈 上座趋势(折线)      │  🏆 积分榜                 │
│  实际vs预测 vs容量线   │  1. 成都 15pt              │
│                       │  6. 国安 10pt              │
└──────────────────────┴───────────────────────────┘
```

## 实施步骤

### 第一步: 恢复侧栏（策略切换）

**文件:** `dashboard/app.py`

- 删除第 30 行 `section[data-testid="stSidebar"] { display: none; }`
- 在数据加载完成后添加侧栏代码:

```python
with st.sidebar:
    st.markdown("### ⚙️ 策略模式")
    strat_mode = st.radio("定价策略", ["自动（收入/上座平衡）", "平衡（激进调价）"], index=0)
    use_balanced = "平衡" in strat_mode
    st.divider()
    st.caption(f"V5.2 · TIER_BASE: S={TIER_BASE['S']:,} A={TIER_BASE['A']:,}")
```

- 在历史定价建议的 `optimizer.optimize()` 调用处，当 `use_balanced=True` 时传入 `force_balanced=True`（如该参数不存在则先跳过）

### 第二步: KPI 行

在 `st.divider()` 后、`render_home_card` 前插入:

```python
# 计算 KPI 值
CAPACITY = 18000
avg_att = np.mean([get_actual(m) for m in home_done]) if home_done else 0
mae_val = ...  # 用现有 preds/actuals 列表

cols = st.columns(5)
cols[0].metric("赛季收入", f"¥{total_rev/10000:.0f}万")
cols[1].metric("场均上座", f"{avg_att:,.0f}", f"{avg_att/CAPACITY*100:.0f}%上座率")
cols[2].metric("预测MAE", f"{mae_val:,.0f}")
cols[3].metric("积分", f"{total_pts}分", f"#{guoan_rank}")
cols[4].metric("下一主场", next_h["date"][5:] if next_h else "-", next_h["opponent"] if next_h else "")
```

### 第三步: 时间线导航

在 KPI 行后插入:

```python
# Session state for selected match index
if 'selected_idx' not in st.session_state:
    st.session_state.selected_idx = len(home_done) - 1 if home_done else 0

st.markdown("**赛季主场**")
tl_cols = st.columns(len(home_all))
for i, m in enumerate(home_all):
    is_done = m in home_done
    # 确定结果样式
    if is_done:
        if m["hg"]>m["ag"]: label, css = "W", "color:#51cf66;background:#1a3a2a"
        elif m["hg"]==m["ag"]: label, css = "D", "color:#f0c040;background:#2a2a10"
        else: label, css = "L", "color:#ff6b6b;background:#2a1515"
    else:
        label, css = "○", "color:#4a4d55;background:#14161c"
    
    # 选中高亮
    if i == st.session_state.selected_idx:
        css += ";border:2px solid #f0f2f5"
    
    opp_short = m["opponent"][:2]
    if tl_cols[i].button(f"{opp_short}", key=f"tl_{i}"):
        st.session_state.selected_idx = i

# 获取选中比赛
sel = home_all[st.session_state.selected_idx]
is_past = sel in home_done
```

### 第四步: 统一比赛卡片

删除现有的:
- `render_home_card()` 及其调用
- `st.subheader("赛季回望")` 及表格
- `st.subheader("历史定价建议")` 及所有循环

替换为统一卡片（基于选中的 `sel`）:

```python
# 计算上下文（复用现有逻辑，提取为函数）
opp = sel["opponent"]; dt = pd.Timestamp(sel["date"])
ctx = detect_ctx(sel, guoan_matches, standings)
# ... 计算所有上下文变量 ...

# 预测
pred_raw = rule_predict(opp, ...)

# === 卡片 HTML ===
st.markdown(f"### vs {opp} · {sel['date']} · S级德比 · 容量 {CAPACITY:,}")

# 上座容量条
pred_pct = pred_raw / CAPACITY * 100
st.progress(min(pred_pct/100, 1.0), text=f"预测 {pred_raw:,.0f} 张 ({pred_pct:.0f}%)")

if is_past:
    actual = get_actual(sel)
    actual_pct = actual / CAPACITY * 100
    st.progress(min(actual_pct/100, 1.0), text=f"实际 {actual:,.0f} 张 ({actual_pct:.0f}%)")
    err = pred_raw - actual
    st.caption(f"误差 {err:+,.0f} 张 ({abs(err)/actual*100:.1f}%)")

# 预测计算链（用彩色标签展示）
# ... 复用现有 rules_triggered 逻辑 ...

# 定价建议
r = optimizer.optimize(opp, ...)
# 显示策略标签 + 6档价格表（只标变化的档位）
# ... 复用现有定价表格逻辑 ...

# 近期赛果（复用 existing last3 logic）
```

### 第五步: 底部趋势图 + 积分榜

删除 `st.subheader("赛季全览")` 及循环。

替换为:

```python
st.divider()
col_l, col_r = st.columns([3, 1])

with col_l:
    st.markdown("**上座趋势**")
    # matplotlib 折线图: 实际 vs 预测 vs 容量线
    fig, ax = plt.subplots(figsize=(8, 3))
    # 暗色主题, dates vs actuals vs preds
    st.pyplot(fig)

with col_r:
    st.markdown("**积分榜**")
    # 当前轮次 standings 表格
```

### 第六步: 清理

删除不再使用的:
- `render_home_card()` 函数
- `render_seating_chart()` 函数（如果未在别处使用）
- `render_match_card()` 相关辅助
- 赛季回望表格代码
- 历史定价建议循环代码

## 保留内容（不动）

- CSS 样式（追加新样式，不删旧的）
- `get_actual()` / `_get_zone_qtys()` / `get_optimizer()` 函数
- `load_csl_data` / `detect_ctx` import
- 数据加载逻辑

## 自测检查项

```bash
cd ~/ticket-pricing && python3 -c "
from src.dynamic_optimizer import DynamicPricingOptimizer
from src.rule_engine import predict_calibrated
from src.pricing_v5 import ZONE_TIERS

opt = DynamicPricingOptimizer()
games = [
    ('上海申花', {'derby':True,'saturday':True,'season_opener':True,'match_year':'2026'}),
    ('成都蓉城', {'away_winless':True,'lost_bottom':True,'match_year':'2026'}),
    ('天津津门虎', {'derby':True,'saturday':True,'match_year':'2026'}),
    ('大连英博海发', {'heavy_home_loss':True,'midweek':True,'match_year':'2026'}),
    ('上海海港', {'short_rest':True,'match_year':'2026'}),
    ('青岛海牛', {'unbeaten_3':True,'match_year':'2026'}),
    ('河南', {'saturday':True,'unbeaten_3':True,'match_year':'2026'}),
]
d = {'derby':False,'saturday':False,'season_opener':False,'lost_bottom':False,
     'heavy_home_loss':False,'away_winless':False,'short_rest':False,
     'midweek':False,'unbeaten_3':False,'late_season':False,'summer':False}
for opp, cargs in games:
    fc = {**d, **cargs}
    pred = predict_calibrated(opp, **fc)
    r = opt.optimize(opp, **fc)
    base_sum = sum(r.tiers[zt].base_qty for zt in ZONE_TIERS)
    assert abs(pred - base_sum) < 1, f'{opp}: pred={pred:.0f} != base_sum={base_sum:.0f}'
    print(f'  {opp:<10} pred={pred:>6.0f} base={base_sum:>6.0f} ✓')
print('全部对齐 ✅')
"
```

## KPI 值计算参考

```python
# 赛季收入（实际）
total_rev = sum(
    sum(zone_qty[zt] * prices_fixed[zt] for zt in ZONE_TIERS)
    for m in home_done
)

# MAE
preds = [rule_predict(...) for m in home_done]
actuals = [get_actual(m) for m in home_done]
mae_val = np.mean(np.abs(np.array(preds) - np.array(actuals)))

# 下一主场
next_h = next((m for m in home_all if not m["completed"]), None)
```
