# Cursor 修复 — data_feeds.py 改用 CSL Dashboard JSON

> 用户自有看板 `xxxniconico.github.io/csl-dashboard-2026/` 的 `dashboard_embed.json` 每轮比赛后更新。
> 替代失败的新浪/维基爬取。

---

## 修改: `src/data_feeds.py` — 重写 `fetch_csl_standings` 和 `fetch_guoan_2026_season`

### 删除旧实现
删除 `_read_html_tables`, `fetch_csl_standings`, `_normalize_schedule_columns`, `fetch_guoan_2026_season` 的当前实现。

### 替换为

```python
import json

_CSL_JSON_URL = "https://xxxniconico.github.io/csl-dashboard-2026/dashboard_embed.json"


def _fetch_dashboard_json() -> dict:
    """获取 CSL Dashboard JSON 数据"""
    resp = requests.get(_CSL_JSON_URL, timeout=20, headers={"User-Agent": _DEFAULT_UA})
    resp.raise_for_status()
    return resp.json()


def fetch_csl_standings() -> pd.DataFrame:
    """从 dashboard_embed.json 解析积分榜（有效积分 = 赛场积分 - 扣分）
    
    Returns DataFrame: rank, team, points (official), match_points, deduction
    """
    try:
        data = _fetch_dashboard_json()
        raw = data.get("raw_data", {})
        leagues = raw.get("leagues", [])
        if not leagues:
            return pd.DataFrame(columns=["rank", "team", "points", "match_points", "deduction"])
        
        standings = leagues[0].get("standings", [])
        rows = []
        for i, s in enumerate(standings):
            rows.append({
                "rank": i + 1,
                "team": s["club_name"],
                "points": s.get("effective_points", s.get("points", 0) - s.get("penalty_points", 0)),
                "match_points": s.get("points", 0),
                "deduction": s.get("penalty_points", 0),
            })
        df = pd.DataFrame(rows)
        # 按 official points 降序排（JSON 可能不是按有效积分排的）
        df = df.sort_values("points", ascending=False).reset_index(drop=True)
        df["rank"] = range(1, len(df) + 1)
        return df
    except Exception:
        return pd.DataFrame(columns=["rank", "team", "points", "match_points", "deduction"])


def fetch_guoan_2026_season() -> pd.DataFrame:
    """从 dashboard_embed.json 解析国安赛程
    
    Returns DataFrame: date, opponent, venue, result, guoan_goals, opp_goals
    """
    try:
        data = _fetch_dashboard_json()
        raw = data.get("raw_data", {})
        fixtures = raw.get("fixtures", raw.get("matches", []))
        
        if not fixtures:
            return pd.DataFrame(columns=["date", "opponent", "venue", "result"])
        
        rows = []
        for f in fixtures:
            # 找国安参与的比赛
            home = f.get("home_team", f.get("home", ""))
            away = f.get("away_team", f.get("away", ""))
            
            if "国安" not in str(home) and "国安" not in str(away):
                continue
            
            is_home = "国安" in str(home)
            opponent = away if is_home else home
            venue = "H" if is_home else "A"
            
            # 比分
            score = f.get("score", f.get("result", ""))
            result = ""
            if score:
                parts = str(score).replace(" ", "").split("-")
                if len(parts) == 2:
                    try:
                        hg, ag = int(parts[0]), int(parts[1])
                        if is_home:
                            result = "W" if hg > ag else "D" if hg == ag else "L"
                        else:
                            result = "W" if ag > hg else "D" if ag == hg else "L"
                    except ValueError:
                        pass
            
            rows.append({
                "date": f.get("date", f.get("match_date", "")),
                "opponent": str(opponent).strip(),
                "venue": venue,
                "result": result,
            })
        
        df = pd.DataFrame(rows)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
        return df.sort_values("date") if "date" in df.columns else df
    except Exception:
        return pd.DataFrame(columns=["date", "opponent", "venue", "result"])
```

### JSON 字段说明

```json
{
  "raw_data": {
    "leagues": [{
      "standings": [
        {
          "club_name": "成都蓉城",
          "points": 31,           // 赛场积分
          "penalty_points": 0,    // 扣分
          "effective_points": 31, // 有效积分 = points - penalty_points
          "played": 11,
          "w_d_l": [10, 1, 0]
        }
      ]
    }],
    "fixtures": [  // 或 "matches"
      {
        "date": "2026-05-10",
        "home_team": "北京国安",
        "away_team": "上海海港",
        "score": "2-2"
      }
    ]
  }
}
```

### 验证

```bash
python -c "
from src.data_feeds import fetch_csl_standings, fetch_guoan_2026_season
s = fetch_csl_standings()
print(f'积分榜: {len(s)}队')
print(s.to_string())
g = fetch_guoan_2026_season()
print(f'\n国安赛程: {len(g)}场')
print(g.head(10).to_string())
"
```
