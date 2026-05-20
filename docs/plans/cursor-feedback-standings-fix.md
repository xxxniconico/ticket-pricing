# Cursor 修复 — 从赛程数据重建正确积分榜

> 问题：`dashboard_embed.json` 的 standings 只有4-5轮，但 matches 有完整赛程。
> 修复：用 matches 数据 + 已知扣分表 重建积分榜。

---

## 修改: `src/data_feeds.py` — 重写 `fetch_csl_standings`

删除旧实现，替换为：

```python
# 赛季前扣分（固定）
_PENALTY_TABLE = {
    "北京国安": 5, "河南": 6, "青岛海牛": 7, "山东泰山": 6,
    "上海海港": 5, "上海申花": 10, "天津津门虎": 10, "武汉三镇": 5, "浙江": 5,
}

def fetch_csl_standings() -> pd.DataFrame:
    """从赛程数据重建积分榜（比赛分 - 赛季前扣分）
    
    用 leagues[0].matches 中所有已赛比赛计算积分，
    叠加 _PENALTY_TABLE 扣分，按有效积分降序排列。
    """
    empty = pd.DataFrame(columns=["rank", "team", "points", "match_points", "deduction"])
    try:
        data = _fetch_dashboard_json()
        raw = data.get("raw_data", {})
        leagues = raw.get("leagues", [])
        if not leagues:
            return empty
        matches = leagues[0].get("matches", [])
        if not matches:
            return empty
        
        # 收集所有队名
        teams: dict[str, dict] = {}
        for m in matches:
            for club in [m.get("home_club", ""), m.get("away_club", "")]:
                club = str(club).strip()
                if club and club not in teams:
                    teams[club] = {"played": 0, "win": 0, "draw": 0, "loss": 0,
                                   "gf": 0, "ga": 0, "points": 0, "deduction": 0}
        
        # 统计已赛结果
        for m in matches:
            score = m.get("score")
            if not score or not isinstance(score, dict):
                continue
            hg = score.get("home")
            ag = score.get("away")
            if hg is None or ag is None:
                continue
            try:
                hg, ag = int(hg), int(ag)
            except (TypeError, ValueError):
                continue
            
            home = str(m.get("home_club", "")).strip()
            away = str(m.get("away_club", "")).strip()
            if home not in teams or away not in teams:
                continue
            
            teams[home]["played"] += 1
            teams[away]["played"] += 1
            teams[home]["gf"] += hg
            teams[home]["ga"] += ag
            teams[away]["gf"] += ag
            teams[away]["ga"] += hg
            
            if hg > ag:
                teams[home]["win"] += 1
                teams[away]["loss"] += 1
                teams[home]["points"] += 3
            elif hg == ag:
                teams[home]["draw"] += 1
                teams[away]["draw"] += 1
                teams[home]["points"] += 1
                teams[away]["points"] += 1
            else:
                teams[home]["loss"] += 1
                teams[away]["win"] += 1
                teams[away]["points"] += 3
        
        # 叠加扣分
        for name in teams:
            teams[name]["deduction"] = _PENALTY_TABLE.get(name, 0)
            teams[name]["effective"] = teams[name]["points"] - teams[name]["deduction"]
        
        # 按有效积分排序
        rows = []
        for name, t in teams.items():
            if t["played"] == 0:
                continue
            rows.append({
                "team": name,
                "points": t["effective"],
                "match_points": t["points"],
                "deduction": t["deduction"],
                "played": t["played"],
                "win": t["win"],
                "draw": t["draw"],
                "loss": t["loss"],
                "gf": t["gf"],
                "ga": t["ga"],
            })
        
        df = pd.DataFrame(rows)
        if df.empty:
            return empty
        df = df.sort_values(["points", "match_points", "gf"], ascending=[False, False, False])
        df = df.reset_index(drop=True)
        df["rank"] = range(1, len(df) + 1)
        return df[["rank", "team", "points", "match_points", "deduction"]]
    except Exception:
        return empty
```

### 验证

```bash
python -c "
from src.data_feeds import fetch_csl_standings
s = fetch_csl_standings()
print(s.to_string())
# 国安应在第11名左右，有效积分~8分
"
```
