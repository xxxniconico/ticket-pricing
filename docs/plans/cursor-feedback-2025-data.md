# Cursor 修复 — 2025赛季数据集成到模型

> 2025国安实际战绩：第4名，17W-6D-7L，57分。
> 当前回测对所有场次用固定 home_form=0.5，忽略了国安2025的实际表现。
> 修复：从维基抓2025赛程 → 注入回测和看板。

---

## 1. 新增: `src/data_feeds.py` — `fetch_guoan_2025_season()`

追加到 data_feeds.py 末尾：

```python
# === 2025赛季硬编码（从维基百科解析，国安主场赛程） ===
_GUOAN_2025_HOME = [
    # (日期, 对手, 国安进球, 对手进球, 结果, 轮次)
    ("2025-03-29", "成都蓉城", 1, 2, "L", 3),
    ("2025-04-06", "浙江俱乐部", 2, 0, "W", 4),
    ("2025-04-19", "山东泰山", 6, 1, "W", 8),
    ("2025-04-25", "河南俱乐部", 3, 1, "W", 9),
    ("2025-05-10", "深圳新鹏城", 2, 0, "W", 11),
    ("2025-06-14", "长春亚泰", 3, 1, "W", 14),
    ("2025-06-17", "青岛西海岸", 2, 0, "W", 6),   # 延期
    ("2025-06-30", "云南玉昆", 4, 2, "W", 16),
    ("2025-07-19", "上海申花", 1, 3, "L", 17),    # 赛季首败
    ("2025-08-03", "天津津门虎", 2, 1, "W", 20),
    ("2025-08-25", "武汉三镇", 2, 0, "W", 22),    # 延期
    ("2025-09-21", "上海海港", 2, 3, "L", 25),
    ("2025-09-26", "大连英博海发", 3, 0, "W", 26),
    ("2025-10-26", "青岛海牛", 2, 1, "W", 28),
    ("2025-11-22", "梅州客家", 5, 1, "W", 30),
]

# 2025对手排名（最终积分榜前8+国安相关）
_OPPONENT_RANK_2025 = {
    "上海海港": 1, "上海申花": 2, "成都蓉城": 3, "北京国安": 4,
    "山东泰山": 5, "天津津门虎": 6, "浙江俱乐部": 7, "河南俱乐部": 8,
    "长春亚泰": 9, "青岛西海岸": 10, "武汉三镇": 11, "深圳新鹏城": 12,
    "云南玉昆": 13, "青岛海牛": 14, "大连英博海发": 15, "梅州客家": 16,
}


def fetch_guoan_2025_home() -> pd.DataFrame:
    """返回2025赛季国安主场赛程（含比分+结果）
    
    Returns: date, opponent, venue(H), guoan_goals, opp_goals, result, round_num
    """
    rows = []
    for date_str, opp, gg, og, res, rnd in _GUOAN_2025_HOME:
        rows.append({
            "date": date_str,
            "opponent": opp,
            "venue": "H",
            "guoan_goals": float(gg),
            "opp_goals": float(og),
            "result": res,
            "round_num": rnd,
        })
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def compute_home_form_2025(up_to_round: int | None = None) -> float:
    """计算2025赛季国安主场胜率（可选：仅统计到某轮之前）
    
    Args:
        up_to_round: 只统计此轮之前的主场比赛。None=全部。
    """
    home = fetch_guoan_2025_home()
    if up_to_round is not None:
        home = home[home["round_num"] < up_to_round]
    if len(home) == 0:
        return 0.5
    wins = (home["result"] == "W").sum()
    return wins / len(home)


def get_opponent_rank_2025(opponent: str) -> int:
    """获取对手在2025赛季的最终排名（模糊匹配）"""
    for name, rank in _OPPONENT_RANK_2025.items():
        if opponent[:2] in name or name[:2] in opponent:
            return rank
    return 8
```

---

## 2. 修改: `dashboard/app.py` — `run_backtest()` 使用2025真实数据

在 `run_backtest()` 函数中，替换固定的 `home_form=0.5, opponent_standing=8, is_weekend=True` 为动态值：

```python
# === 改 run_backtest 中的 classify_match_hybrid 调用 ===
# 新增 import（文件顶部）
from src.data_feeds import compute_home_form_2025, get_opponent_rank_2025
from datetime import datetime

# 回测中替换固定参数：
t_bt, m_bt = classify_match_hybrid(
    opp,
    base_lookup=_lookup,
    opponent_standing=get_opponent_rank_2025(opp),  # 用2025真实排名
    is_weekend=_is_weekend_from_match_id(match_id),  # 从日期判断
    season_stage="mid",
    home_form=compute_home_form_2025(),  # 用2025真实主场胜率
    temperature_c=20.0,
    precipitation_mm=0.0,
)
```

辅助函数：
```python
def _is_weekend_from_match_id(match_id: str) -> bool:
    """从 match_id 中提取日期判断周末"""
    import re
    m = re.search(r"(\d{4}-\d{2}-\d{2})", str(match_id))
    if m:
        d = datetime.strptime(m.group(1), "%Y-%m-%d")
        return d.weekday() >= 5
    return True
```

---

## 3. 修改: Tab2 显示2025实际胜负

在 tab2 的"2025赛季战绩"部分，用真实数据替换 `"比分"="?", "结果"="?"`：

```python
# 加载2025真实数据
from src.data_feeds import fetch_guoan_2025_home
g25 = fetch_guoan_2025_home()

# 合并到 by_match
g25_map = {}
for _, r in g25.iterrows():
    opp = r["opponent"]
    g25_map[opp] = (int(r["guoan_goals"]), int(r["opp_goals"]), r["result"])

for i, row in by_match.iterrows():
    opp = row["对手"]
    if opp in g25_map:
        gg, og, res = g25_map[opp]
        by_match.at[i, "比分"] = f"{gg}-{og}"
        emoji = {"W": "🟢", "D": "🟡", "L": "🔴"}.get(res, "?")
        by_match.at[i, "结果"] = f"{emoji} {res}"
```

---

## 验证

```bash
python -c "
from src.data_feeds import fetch_guoan_2025_home, compute_home_form_2025
g = fetch_guoan_2025_home()
print('2025主场战绩:')
print(g.to_string())
print(f'主场胜率: {compute_home_form_2025():.2f}')
"

# 看板回测应更准确——海牛(排名14)应该有更高预测，成都(排名3)预测降低
```
