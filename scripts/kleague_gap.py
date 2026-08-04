"""K League 1 赔率 gap 验证：模型 vs Pinnacle 市场隐含概率

找出模型认为被市场高估/低估的方向（gap = 模型概率 - 市场隐含概率）。
gap > 阈值 → 正 EV 候选。

用法: python scripts/kleague_gap.py [--pinnacle-only] [--min-gap 0.05]
"""
import json
import math
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
from kleague_predict import predict  # noqa: E402
from kleague_teams import cn  # noqa: E402

ODDS_KEY = "676ffca425f3b87691f870240ea4b05f"
# the-odds-api 旧队名 -> 本项目统一队名
ODDS_TEAM_ALIASES = {
    "Sangju Sangmu FC": "Gimcheon Sangmu FC",
    "Ulsan Hyundai FC": "Ulsan HD",
    "Jeonbuk Motors": "Jeonbuk Hyundai Motors",
    "Daejeon Citizen": "Daejeon Hana Citizen",
    "Jeju United FC": "Jeju SK",
    "Suwon City FC": "Suwon FC",
    "Suwon Bluewings": "Suwon Samsung Bluewings",
}


def fetch_odds() -> list[dict]:
    url = f"https://api.the-odds-api.com/v4/sports/soccer_korea_kleague1/odds/?apiKey={ODDS_KEY}&regions=eu&markets=h2h&oddsFormat=decimal"
    data = json.load(urllib.request.urlopen(url, timeout=20))
    out = []
    for g in data:
        pin = None
        for bm in g.get("bookmakers", []):
            if bm["key"] == "pinnacle":
                for mkt in bm["markets"]:
                    if mkt["key"] == "h2h":
                        pin = {o["name"]: o["price"] for o in mkt["outcomes"]}
        if not pin:
            continue
        home = ODDS_TEAM_ALIASES.get(g["home_team"], g["home_team"])
        away = ODDS_TEAM_ALIASES.get(g["away_team"], g["away_team"])
        # 用原始队名找主队赔率
        home_raw = g["home_team"]
        if home_raw not in pin:
            home_raw = next((k for k in pin if ODDS_TEAM_ALIASES.get(k) == g["home_team"]), home_raw)
        away_raw = g["away_team"]
        if away_raw not in pin:
            away_raw = next((k for k in pin if ODDS_TEAM_ALIASES.get(k) == g["away_team"]), away_raw)
        inv = {k: 1 / v for k, v in pin.items()}
        tot = sum(inv.values())
        out.append({
            "home": home, "away": away,
            "market": {
                "H": inv.get(home_raw, 0) / tot,
                "D": inv.get("Draw", 0) / tot,
                "A": inv.get(away_raw, 0) / tot,
            },
            "odds": pin,
        })
    return out


def main():
    min_gap = 0.05
    matches = fetch_odds()
    if not matches:
        print("无 Pinnacle 在售场次")
        return

    print(f"{'主队':<20s} {'客队':<20s} {'方向':<3s} {'模型':>6s} {'市场':>6s} {'gap':>6s}  判定")
    print("-" * 70)
    for m in matches:
        r = predict(m["home"], m["away"])
        for k, label in [("H", "主胜"), ("D", "平局"), ("A", "客胜")]:
            p_model = r["probs"][k]
            p_mkt = m["market"][k]
            gap = p_model - p_mkt
            tag = "✅ 正EV候选" if gap > min_gap else ("⚠️ 负EV" if gap < -min_gap else "")
            print(f"{cn(m['home']):<20s} {cn(m['away']):<20s} {label:<3s} {p_model:>5.1%} {p_mkt:>5.1%} {gap:>+5.1%}  {tag}")


if __name__ == "__main__":
    main()
