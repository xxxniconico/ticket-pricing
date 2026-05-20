# Cursor 修复 — 三个问题一次性修

---

## 问题1: 2026战绩不见了

**原因**: Tab1 的 `st.expander("📅 国安2026赛季战绩")` 被 Cursor 删除或缩进错了。

**检查位置**: `dashboard/app.py` 中 tab1 区域（标题下），搜索 `"国安2026赛季战绩"`。

**修复**: 确保此 expander 在 tab1 内，并在对手选择前显示。完整代码已在之前的 feedback 中给出。

---

## 问题2: 2025只显示主场，成绩缺失

**原因**: Tab2 用了 `fetch_guoan_2025_home()` 而非 `fetch_guoan_2025_all()`。而且 `_GUOAN_2025_HOME` 的数据可能仍是旧版（只有主场）。

**修复2a**: 确认 `src/data_feeds.py` 中有以下全部30轮数据：

```python
_GUOAN_2025_ALL = [
    (1, "云南玉昆", "A", 2, 0, "W"),
    (2, "上海申花", "A", 1, 1, "D"),
    (3, "成都蓉城", "H", 1, 2, "L"),
    (4, "浙江俱乐部", "H", 2, 0, "W"),
    (5, "长春亚泰", "A", 2, 1, "W"),
    (6, "青岛西海岸", "H", 2, 0, "W"),
    (7, "武汉三镇", "A", 1, 1, "D"),
    (8, "山东泰山", "H", 6, 1, "W"),
    (9, "河南俱乐部", "H", 3, 1, "W"),
    (10, "上海海港", "A", 2, 1, "W"),
    (11, "深圳新鹏城", "H", 2, 0, "W"),
    (12, "大连英博海发", "A", 2, 0, "W"),
    (13, "梅州客家", "A", 2, 2, "D"),
    (14, "长春亚泰", "H", 3, 1, "W"),
    (15, "梅州客家", "H", 5, 1, "W"),
    (16, "云南玉昆", "H", 4, 2, "W"),
    (17, "上海申花", "H", 1, 3, "L"),
    (18, "成都蓉城", "A", 0, 1, "L"),
    (19, "浙江俱乐部", "A", 3, 3, "D"),
    (20, "天津津门虎", "H", 2, 1, "W"),
    (21, "山东泰山", "A", 1, 2, "L"),
    (22, "武汉三镇", "H", 2, 0, "W"),
    (23, "上海海港", "H", 2, 3, "L"),
    (24, "深圳新鹏城", "A", 0, 1, "L"),
    (25, "大连英博海发", "H", 3, 0, "W"),
    (26, "青岛西海岸", "A", 1, 1, "D"),
    (27, "河南俱乐部", "A", 1, 2, "L"),
    (28, "青岛海牛", "H", 2, 1, "W"),
    (29, "天津津门虎", "A", 3, 1, "W"),
    (30, "梅州客家", "H", 5, 1, "W"),
]
```

**修复2b**: 替换 `fetch_guoan_2025_home()` 函数：
```python
def fetch_guoan_2025_all() -> pd.DataFrame:
    rows = [{"round": r, "opponent": o, "venue": v, 
             "guoan_goals": float(g), "opp_goals": float(og), "result": res}
            for r, o, v, g, og, res in _GUOAN_2025_ALL]
    return pd.DataFrame(rows)

def fetch_guoan_2025_home() -> pd.DataFrame:
    df = fetch_guoan_2025_all()
    return df[df["venue"] == "H"].reset_index(drop=True)
```

**修复2c**: Tab2 战绩表改为显示全部30轮：
```python
g25_all = fetch_guoan_2025_all()
# 显示全部30轮表格，不是只有主场
st.dataframe(g25_all[...], ...)
```

**修复2d**: Tab2 的"比分"列要从 `_GUOAN_2025_ALL` 中匹配：
```python
# 构建查表
g25_map = {}
for _, r in g25_all.iterrows():
    opp = r["opponent"]
    g25_map[opp] = (int(r["guoan_goals"]), int(r["opp_goals"]), r["result"], r["venue"])

# 填充 by_match
for i, row in by_match.iterrows():
    opp = row["对手"]
    if opp in g25_map:
        gg, og, res, venue = g25_map[opp]
        by_match.at[i, "比分"] = f"{gg}-{og}"
        emoji = {"W": "🟢", "D": "🟡", "L": "🔴"}.get(res, "?")
        by_match.at[i, "结果"] = f"{emoji} {res}"
        # 注意：座位数据只有主场，所以 venue 应该都是 "H"
```

---

## 问题3: 文字乱码

**可能原因**:
1. matplotlib 字体缓存未清除
2. `¥` 符号仍在某处使用
3. Streamlit 本身需要重启

**修复**:
```bash
# 彻底清除 matplotlib 缓存
rm -rf ~/.cache/matplotlib ~/.matplotlib

# 确认 dashboard/app.py 开头有：
import matplotlib
matplotlib.rcParams["font.sans-serif"] = ["SimHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

# 替换所有图表中的 "¥" 为 "元"
# 搜索: grep -n "¥" dashboard/app.py
# 如果出现在 matplotlib 图表标签中，改为 "元"
```

如果 `¥` 出现在 HTML 渲染的内容中（非图表），不需要改——HTML 中的 ¥ 是 Unicode 字符，浏览器能正常渲染。

---

## 验证

```bash
cd ~/ticket-pricing
PYTHONPATH=. python -c "
from src.data_feeds import fetch_guoan_2025_all
g = fetch_guoan_2025_all()
print(f'全部: {len(g)}场, 主{g[g.venue==\"H\"].shape[0]}客{g[g.venue==\"A\"].shape[0]}')
print(g.to_string())
"

pkill -f streamlit
rm -rf ~/.cache/matplotlib ~/.matplotlib
bash dashboard/serve.sh
```

Tab1 应显示2026战绩 expander；
Tab2 应显示全部30轮主客场胜负；
图表中文正常。
