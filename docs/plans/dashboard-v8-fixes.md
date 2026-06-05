# 看板 V8 修改任务 — Cursor 执行

## 一、布局调整：积分榜→侧栏，策略切换→卡片

### 1.1 积分榜移到侧栏

**位置:** 当前在底部右栏 (约 L600-616)，移到 `st.sidebar` 中策略模式下方。

```python
# 在侧栏 st.divider() 之后添加:
with st.sidebar:
    # ... 策略模式代码保持不变 ...
    
    st.divider()
    st.markdown("**积分榜**")
    if latest_rnd and latest_rnd in standings:
        rstandings = sorted(standings[latest_rnd].items(), key=lambda x: x[1])[:16]
        for team, rank in rstandings:
            bold = "font-weight:700;color:#f0f2f5" if "国安" in team else "color:#8a8f98"
            st.markdown(f'<span style="{bold}">#{rank} {team}</span>', unsafe_allow_html=True)
```

**同时删除:** 底部右栏的积分榜代码（L600-616 附近的 `col_r` 内容）。

### 1.2 策略切换移到卡片内

**删除:** 侧栏中的 `st.radio("定价策略", ...)` 代码块。

**在卡片内添加:** 定价建议表格上方，加一行策略选择：

```python
# 在定价建议标题 st.markdown("**定价建议**") 之后、optimizer.optimize() 之前:
strat_mode = st.radio("策略", ["自动", "平衡"], index=0, horizontal=True, 
                       key=f"strategy_{st.session_state.selected_idx}")
use_balanced = (strat_mode == "平衡")
```

**注意事项:**
- `key` 用 `f"strategy_{st.session_state.selected_idx}"` 确保每场比赛独立记忆策略选择
- 如果 `use_balanced=True`，传给 `optimizer.optimize()` 时需要怎么处理？检查 optimizer 是否有 `force_balanced` 参数，如没有则先保持和现在一样

### 1.3 底部趋势图

积分榜移走后，趋势图可以占满全宽。把 `col_l, col_r = st.columns([3, 1])` 去掉，趋势图直接用全宽。

---

## 二、卡片补充内容

### 2.1 对手当前排名

在卡片标题下方（容量的同一行或下一行），加对手联赛排名：

```python
# 获取对手当前排名
opp_rank = "?"
if sel["round"] in standings:
    opp_rank = standings[sel["round"]].get(opp, "?")
# 在卡片 meta 行追加:
# f'对手排名 #{opp_rank}'
```

### 2.2 对手近期战绩

在卡片下方（定价建议之后），加对手近5场战绩。需要从 `guoan_2026` 中筛选该对手的比赛：

```python
# 对手近5场（在对阵国安之前）
opp_matches = [m for m in guoan_2026 
               if m["completed"] and m["date"] < sel["date"]
               and (m["opponent"] == opp or m["home"] == opp or m["away"] == opp)]
# 这只能查到国安相关的比赛。要查对手所有比赛，需要遍历 all_matches。
# 简化版：从 all_matches 中筛选
opp_all = [m for m in all_matches 
           if m["completed"] and m["date"] < sel["date"]
           and (opp in m["home"] or opp in m["away"])]
opp_last5 = opp_all[-5:]

st.markdown("**对手近况**")
for gm in opp_last5:
    is_home = opp in gm["home"]
    opp_side = gm["away"] if is_home else gm["home"]
    gf = gm["hg"] if is_home else gm["ag"]
    ga = gm["ag"] if is_home else gm["hg"]
    res = "W" if gf>ga else "D" if gf==ga else "L"
    loc = "vs" if is_home else "@"
    st.caption(f'{res} {loc} {opp_side} {gf}-{ga}')
```

### 2.3 天气

天气数据源不在本地，先用占位。在卡片标题行加：

```python
# 占位：后续接入天气 API
weather_info = ""  # 如: "☀️ 22°C"
```

如果暂时没有天气数据源，跳过此项。

---

## 三、自检

改完后运行：

```bash
cd ~/ticket-pricing && python3 -c "
from src.rule_engine import predict_calibrated
from src.dynamic_optimizer import DynamicPricingOptimizer
from src.pricing_v5 import ZONE_TIERS
opt = DynamicPricingOptimizer()
# 验证 7 场对齐
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
    print(f'  {opp:<10} ✓')
print('全部对齐')
"
```

重启看板后验证：
- 侧栏有积分榜
- 卡片内有策略切换
- 卡片内有对手排名 + 对手近况
- 趋势图全宽
- KPI 和预测不变
