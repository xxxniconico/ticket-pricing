# V8 Dashboard P0+P1 Refactor Spec

你是 Streamlit + Python 重构专家。请对 `dashboard/app_v8.py` 和 `dashboard/style.css` 执行以下 P0 和 P1 级别的重构。直接修改文件，不要只输出计划。

## ⚠️ 全局约束

1. **不要改变任何 Tab 的内容或布局** — 用户看到的东西不能变
2. **不要改变颜色、字体、间距** — `style.css` 只在 P1-7 处修改
3. **不要删除或重命名任何 Tab**
4. **每完成一项重构，立即验证**：`python3 -c "import py_compile; py_compile.compile('dashboard/app_v8.py', doraise=True)"`
5. **如果重构引入 bug，回滚该项并跳过**

---

## P0 项目

### P0-1: 抽取 `build_pred_args()` 函数

**当前状态:**
- `render_tab1` L612-616 构建 pred_args
- `render_history_expanders` L678-684 构建 pred_args  
- `render_h2_strategy` L966-971 构建 pred_args

**目标:** 在文件顶部（`def load_css()` 之后）新增：

```python
def build_pred_args(match, ctx, overrides=None):
    """从 match dict + context dict 构建预测参数字典。"""
    dt = pd.Timestamp(match["date"])
    opp = match["opponent"]
    is_home = match.get("is_home", True)
    
    args = {
        'derby': opp in DERBY_RIVALS,
        'saturday': dt.weekday() == 5,
        'late_season': dt.month >= 10,
        'midweek': dt.weekday() in [1, 2, 3],
        'season_opener': False,
        'match_year': match["date"][:4],
        'away_winless': ctx.get('away_winless', False),
        'lost_bottom': ctx.get('lost_bottom', False),
        'heavy_home_loss': ctx.get('heavy_home_loss', False),
        'short_rest': ctx.get('short_rest', False),
        'unbeaten_3': ctx.get('unbeaten_3', False),
        'away_winless_losses': ctx.get('away_winless_losses', False),
        'consecutive_home_losses': ctx.get('consecutive_home_losses', False),
    }
    
    if overrides:
        args.update(overrides)
    
    return args
```

然后替换三处调用：
- `render_tab1` L612-616 → `pred_args = build_pred_args(target_match, ctx, {'season_opener': so, 'unbeaten_3': ub3})`
- `render_history_expanders` L678-684 → `pred_args = build_pred_args(m, ctx, {'summer': dt_m.month in [7,8], 'match_year': m["date"][:4]})`
- `render_h2_strategy` L966-971 → `pred_args = build_pred_args(next_home, ctx, {'season_opener': False, 'match_year': '2026'})`

### P0-2: Tab2 策略卡片复用 `render_strategy_card()`

**当前状态:** `render_history_expanders` L687-718 内联了和 `render_strategy_card()` 完全相同的 HTML。

**目标:** 删除 L687-718 的内联代码，替换为：
```python
render_strategy_card(r_h, pred_args)
```

注意：`render_strategy_card` 需要 `r` 有 `revenue_weight` 和 `attendance_weight` 属性 — 确认 `DynamicPricingOptimizer.optimize()` 返回的对象有此属性后才调用。

### P0-3: `render_opponent_analysis()` 接收参数而非重新加载

**当前状态:** L839-841 在函数内部重新导入并调用 `load_csl_data()` + `get_guoan_matches()`。

**目标:**
1. 删除 L839-841 的内部 import 和 load 调用
2. 修改函数签名：`def render_opponent_analysis(all_matches):`
3. 用 `get_guoan_matches(all_matches)` 替换 `guoan_all = get_guoan_matches(all_m)` (L842)
4. `main()` 中 L1340 调用改为：`render_opponent_analysis(all_matches)`

### P0-4: 德比判断统一使用 `DERBY_RIVALS`

**当前状态:** `opp in {"上海申花", "山东泰山"}` 出现在 L160, L507, L679, L967

**目标:** 全部替换为 `opp in DERBY_RIVALS`（`DERBY_RIVALS` 已从 classify.py 导入）

### P0-5: H2 策略使用 `get_optimizer()` 而非直接 new

**当前状态:** L958: `optimizer = DynamicPricingOptimizer(revenue_weight=0.6)`

**目标:** 改为 `optimizer = get_optimizer()`，删除该行上面的 `from src.dynamic_optimizer import DynamicPricingOptimizer` 内联导入（如果顶部已导入）

---

## P1 项目

### P1-1: 抽取 `build_rule_labels()` 函数

**当前状态:** 
- `render_strategy_card` L334-343 构建 `rules_parts` 列表
- `render_history_expanders` L695-703 构建 `parts` 列表  

**目标:** 新增函数：
```python
def build_rule_labels(pred_args):
    """从 pred_args 构建人类可读的规则标签列表。"""
    labels = []
    if pred_args.get('derby'): labels.append("德比")
    if pred_args.get('saturday'): labels.append("周六")
    if pred_args.get('midweek'): labels.append("工作日")
    if pred_args.get('late_season'): labels.append("赛季末")
    if pred_args.get('lost_bottom'): labels.append("输保级队")
    if pred_args.get('heavy_home_loss'): labels.append("主场惨败")
    if pred_args.get('away_winless_losses'): labels.append("客场连败")
    elif pred_args.get('away_winless'): labels.append("客场不胜")
    if pred_args.get('short_rest'): labels.append("双赛周")
    if pred_args.get('season_opener'): labels.append("揭幕战")
    return labels
```

然后：
- `render_strategy_card` L334-343 替换为 `rules_parts = build_rule_labels(pred_args)`
- `render_history_expanders` L695-703 替换为 `parts = build_rule_labels(pred_args)`

### P1-2: 抽取 `render_price_table()` 通用渲染器

创建一个通用的 HTML table 渲染函数替代三处手写。但这三处表格列配置差异较大（6列/6列/7列），如果抽取会引入过度抽象。

**简化方案:** 不强制抽取，但统一三处的 style 模式：
- 所有 pricing table 使用 `class="history-table"` 一致的 CSS
- 合计行统一样式 `border-top:1px solid rgba(255,255,255,0.08);font-weight:510`
- 颜色变量命名统一（`dp_color` vs `dp_c` vs `dp_clr` — 统一为 `delta_color`）

在 `render_pricing_table` (L361), `render_what_if` (L433), `render_history_expanders` (L721) 三处应用。

### P1-3: 抽取 `_get_csl_parquet()` 消除 parquet 重复读取

**当前状态:** `get_actual()` L67-77, `_get_zone_qtys()` L82-98, `_get_zone_actual_revenue()` L104-120 前8行完全重复。

**目标:** 新增函数：
```python
@st.cache_data(ttl=3600)
def _get_csl_parquet():
    """返回过滤后的 CSL parquet DataFrame（去 partial/bundle）。"""
    pq = ROOT / "data/processed/all_unified.parquet"
    if not pq.exists():
        return None
    df = pd.read_parquet(pq)
    return df[(df["competition"] == "CSL") & (~df["is_partial"]) & (~df["is_bundle"])]
```

然后在 `get_actual()`, `_get_zone_qtys()`, `_get_zone_actual_revenue()` 中调用 `csl = _get_csl_parquet()` 替代重复的读取+过滤代码。

### P1-4: What-If 乘数命名常量化

**当前状态:** L412-413 硬编码 `0.80` 和 `1.15`

**目标:** 在文件顶部常量区添加：
```python
WHATIF_PRESETS = {
    "悲观（-20%）": 0.80,
    "乐观（+15%）": 1.15,
}
```
然后在 `render_what_if` L412-413 使用：
```python
mult = WHATIF_PRESETS.get(scenario, 1.0)
```

### P1-5: H2 瀑布图数据从 summary 计算

**当前状态:** L1104-1107 硬编码 `categories` 和 `values`

**目标:** 从 `h2["summary"]` 动态计算。如果 summary 中没有分解数据，至少将硬编码值提取为函数顶部命名常量：
```python
WATERFALL_DATA = [
    ("2025\n实际", 4591),
    ("赛程\n结构", -650),
    ("升班马\nC级", -200),
    ("其他\n因素", -348),
    ("2026\n预估", 3935),
]
```

### P1-6: 添加加载态 + 错误恢复

**当前状态:** 数据加载无 spinner，错误后无重试按钮。

**目标:**
1. `main()` 中 `load_data()` 包裹 `st.spinner("加载 CSL 数据...")`
2. `st.error("无法加载 CSL 数据，请刷新重试")` 后加一个 `st.button("🔄 刷新重试")`，点击后 `st.rerun()`
3. 空态区分：「2026 赛季尚未开赛」 vs 「数据文件缺失」

### P1-7: 修复 CSS 全局 `table {}` 污染

**当前状态:** `style.css` L67-92 用 `table { }` 选择器影响所有 Streamlit 原生表格。

**目标:** 将 `table { }` 改为 `table.history-table, table.compact-table { }`，同时保留所有内部选择器（`thead th`, `tbody td` 等）不变。

### P1-8: 删除 `render_opponent_analysis()` 内部冗余导入

**当前状态:** L839-841 有 `from src.classify import ...` 和 `from src.csl_context import ...`

**目标:** 删除这三行（已在 P0-3 中一并处理）。

---

## 验证步骤

每完成一个 P 级的所有项目后执行：
```bash
python3 -c "import py_compile; py_compile.compile('dashboard/app_v8.py', doraise=True)" && echo "OK"
```

全部完成后启动验证：
```bash
cd ~/ticket-pricing && ~/.hermes/hermes-agent/venv/bin/streamlit run dashboard/app_v8.py --server.port 8507 --server.headless true &
sleep 5
curl -s -o /dev/null -w "%{http_code}" http://localhost:8507
# 应返回 200
fuser -k 8507/tcp
```

## 注意

- 如果 `DynamicPricingOptimizer` 的 `optimize()` 返回对象没有 `revenue_weight` 属性，P0-2 中 `render_strategy_card()` 调用会失败 → 为 `render_strategy_card` 增加参数 `revenue_weight` 和 `attendance_weight`，由调用方传入。
- 参数名必须保持一致：`pred_args` 中的 key 和 `build_rule_labels()` 中的 key 完全匹配。
- 所有新函数放在 `load_css()` 之后、第一个 `@st.cache_data` 之前。
