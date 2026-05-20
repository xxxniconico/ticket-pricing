# Cursor Task 8-10 — 外部数据自动同步

> 让看板自动获取2026赛季对手排名、国安战绩、赛程、天气，不再手调 slider。

---

## Task 8: 数据爬取模块 `src/data_feeds.py`

**目标:** 从中足联、维基、Open-Meteo 自动获取赛程/排名/战绩/天气

### 数据源

| 数据 | 来源 | 方式 |
|------|------|------|
| CSL积分榜 | 中足联官网或 `sports.sina.com.cn/csl/table/` | web_extract / pandas read_html |
| 国安2026赛季页 | `zh.wikipedia.org/wiki/北京国安足球俱乐部2026赛季` | web_extract |
| 天气 | `open-meteo.com` API（免费，无key） | requests |
| 赛程 | 维基赛季页（含对手+日期+比分） | web_extract |

```python
"""外部数据源：积分榜 / 国安战绩 / 天气"""
import requests
import pandas as pd
from datetime import datetime, date

def fetch_csl_standings() -> pd.DataFrame:
    """获取CSL积分榜 → DataFrame，列: rank, team, points, played
    
    优先用新浪 sports.sina.com.cn/csl/table/，pandas read_html 直接解析。
    """
    url = "https://sports.sina.com.cn/csl/table/"
    tables = pd.read_html(url)
    # 通常第一个 table 是积分榜
    df = tables[0]
    # 列名适配（新浪表格列名可能是中文）
    df.columns = ["rank", "team", "played", "win", "draw", "loss", "gf", "ga", "gd", "points"]
    return df[["rank", "team", "points"]]


def fetch_guoan_2026_season() -> pd.DataFrame:
    """爬取国安2026赛季维基页面 → 赛程+结果
    
    Returns DataFrame: date, opponent, venue(H/A), result, guoan_goals, opp_goals
    """
    # 维基赛季页含完整赛程表
    url = "https://zh.wikipedia.org/wiki/北京国安足球俱乐部2026赛季"
    tables = pd.read_html(url)
    # 找赛程表（通常含"轮次"列）
    for t in tables:
        if any("对手" in str(c) or "比分" in str(c) for c in t.columns):
            return t
    return pd.DataFrame()


def compute_home_form(schedule_df: pd.DataFrame, last_n: int = 5) -> float:
    """从赛程数据计算国安近期主场胜率（近N场）"""
    home_matches = schedule_df[schedule_df["venue"] == "H"]  # 或判断主场
    recent = home_matches.tail(last_n)
    if len(recent) == 0:
        return 0.5
    wins = sum(1 for _, r in recent.iterrows() if r.get("result") == "W")
    return wins / len(recent)


def fetch_weather(match_date: str, lat: float = 39.93, lon: float = 116.46) -> dict:
    """Open-Meteo API 获取比赛日天气
    
    Args:
        match_date: "2026-05-15"
        lat/lon: 工体坐标 39.93, 116.46
    
    Returns: {"temperature": float, "precipitation": float}
    """
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&daily=temperature_2m_mean,precipitation_sum"
        f"&start_date={match_date}&end_date={match_date}"
        f"&timezone=Asia/Shanghai"
    )
    resp = requests.get(url, timeout=10)
    data = resp.json()
    daily = data.get("daily", {})
    return {
        "temperature": daily.get("temperature_2m_mean", [20])[0] or 20,
        "precipitation": daily.get("precipitation_sum", [0])[0] or 0,
    }


def get_opponent_standing(team_name: str, standings: pd.DataFrame) -> int:
    """从积分榜查对手排名"""
    match = standings[standings["team"].str.contains(team_name[:2])]
    if len(match) > 0:
        return int(match.iloc[0]["rank"])
    return 8  # 默认中游


def get_next_match(schedule_df: pd.DataFrame) -> dict | None:
    """找下一个未进行的国安主场
    
    Returns: {"opponent": str, "date": str, "is_weekend": bool}
    """
    today = date.today()
    for _, row in schedule_df.iterrows():
        match_date = pd.to_datetime(row["date"]).date()
        if match_date >= today:
            return {
                "opponent": row["opponent"],
                "date": str(match_date),
                "is_weekend": match_date.weekday() >= 5,
            }
    return None
```

### 验证
```bash
python -c "
from src.data_feeds import fetch_csl_standings, fetch_guoan_2026_season
s = fetch_csl_standings()
print('积分榜:', len(s), '队')
print(s.head(5))
g = fetch_guoan_2026_season()
print('国安赛程:', len(g), '场')
"
```

---

## Task 9: 看板集成 `dashboard/app.py` — 自动加载外部数据

**目标:** 看板打开时自动拉取最新积分榜+赛程+天气，预设 slider 值

### 修改 dashboard/app.py

在参数面板前新增自动数据加载：

```python
# === 自动加载外部数据 ===
from src.data_feeds import (
    fetch_csl_standings, fetch_guoan_2026_season,
    compute_home_form, fetch_weather, get_opponent_standing, get_next_match
)

@st.cache_data(ttl=3600)
def load_external():
    """每小时刷新外部数据"""
    try:
        standings = fetch_csl_standings()
    except Exception:
        standings = pd.DataFrame()
    try:
        schedule = fetch_guoan_2026_season()
    except Exception:
        schedule = pd.DataFrame()
    return standings, schedule

standings, schedule = load_external()

# 自动预设
next_match = get_next_match(schedule) if not schedule.empty else None
default_opponent = next_match["opponent"] if next_match else "上海申花"
default_standing = get_opponent_standing(default_opponent, standings) if not standings.empty else 8
default_form = compute_home_form(schedule) if not schedule.empty else 0.5
default_weather = fetch_weather(next_match["date"]) if next_match else {"temperature": 20, "precipitation": 0}
```

然后修改 slider 的 `value=` 参数：

```python
opponent = st.selectbox("对手", [...], index=OPPONENT_LIST.index(default_opponent))
opponent_standing = st.slider("对手排名", 1, 16, default_standing)
home_form = st.slider("国安近态胜率", 0.0, 1.0, default_form, 0.05)
temperature = st.slider("气温 ℃", -10, 40, int(default_weather["temperature"]))
precipitation = st.slider("降水量 mm", 0, 100, int(default_weather["precipitation"]))
```

### 新增：数据状态栏

```python
st.caption(f"数据更新: 积分榜{len(standings)}队 | 赛程{len(schedule)}场 | 天气{default_weather.get('temperature','?')}℃")
```

---

## Task 10: 训练回路 `src/retrain.py`

**目标:** 2026每场比赛后，放新数据 → 一键重训

```python
"""模型重训：新数据加入 → 更新弹性/乘数"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ingest import load_all, load_seat_data
from src.elasticity import fit_elasticity_from_transactions
from src.classify import build_base_multiplier_lookup

def retrain(data_dir: str = "data/raw"):
    """读取 data/raw/ 下所有数据，重新拟合模型参数"""
    demand = load_all(data_dir)
    txn_el = fit_elasticity_from_transactions(
        f"{data_dir}/25年散票用户购买记录更新.xlsx"
    )
    lookup = build_base_multiplier_lookup(
        f"{data_dir}/2025散票数据.xlsx"
    )
    
    print(f"弹性 ε: {txn_el.elasticity:.3f} (R²={txn_el.r_squared:.3f})")
    print(f"乘数查表: {len(lookup)} 对手")
    print("重训完成。")

if __name__ == "__main__":
    retrain()
```

看板的 `st.cache_data(ttl=3600)` 会自动在1小时后刷新——2026赛后放新Excel，下次打开看板自动重训。

---

## 验证

```bash
# 爬取测试
python -c "from src.data_feeds import fetch_csl_standings; print(fetch_csl_standings().head())"

# 重训
python src/retrain.py

# 看板
bash dashboard/serve.sh
```
