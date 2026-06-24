"""拉 SCORES endpoint 完整数据并保存."""
import json
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path("/home/xxxsuli/ticket-pricing")
SCORES_DIR = ROOT / "data/raw/scores"
SCORES_DIR.mkdir(parents=True, exist_ok=True)

env = (ROOT / ".env").read_text()
api_key = next(line.split("=", 1)[1].strip() for line in env.splitlines() if line.startswith("ODDS_API_KEY="))

# daysFrom=3 覆盖前 3 天 + 今天
url = "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/scores/?" + urllib.parse.urlencode({
    "apiKey": api_key,
    "daysFrom": 3,
    "dateFormat": "iso",
})
print(f"Fetching: {url[:100]}...")
data = json.loads(urllib.request.urlopen(
    urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
    timeout=20,
).read())

# 时间戳文件
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
out = SCORES_DIR / f"fifa_wc_scores_{stamp}.json"
out.write_text(json.dumps(data, indent=2, ensure_ascii=False))
print(f"Saved {len(data)} matches to {out}")

# 覆盖 latest 指针
(SCORES_DIR / "latest.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
print(f"Also wrote latest.json")

# 统计
done = sum(1 for m in data if m.get("completed"))
print(f"  completed: {done}/{len(data)}")
