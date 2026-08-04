"""K League 2026 主胜率漂移监控器

判断 2026 主胜率是否真的偏离历史基线（2022-2025），还是小样本噪声。

用法: python scripts/kleague_monitor_drift.py
输出: 当前主胜率 + 95% 二项 CI + 与基线差异显著性 + 建议

判断逻辑:
- 主胜率落在历史基线 39.2% 的 95% CI 内 → 无漂移证据，维持模型
- 低于 CI 下界 → 漂移显著，提示考虑 2026 专属系数/近期加权
- 市场锚: the-odds-api Pinnacle 隐含主胜率作为独立证据（市场定价）
"""
import json
import math
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_HOME_WIN = 0.392   # 2022-2025 主胜率
SEASONS_HIST = (2022, 2023, 2024, 2025)
SEASON_NOW = 2026
ODDS_KEY = "676ffca425f3b87691f870240ea4b05f"

# the-odds-api 用旧队名 -> 本项目统一队名
ODDS_TEAM_ALIASES = {
    "Sangju Sangmu FC": "Gimcheon Sangmu FC",
    "Ulsan Hyundai FC": "Ulsan HD",
    "Jeonbuk Motors": "Jeonbuk Hyundai Motors",
    "Daejeon Citizen": "Daejeon Hana Citizen",
    "Jeju United FC": "Jeju SK",
    "Suwon City FC": "Suwon FC",
    "Suwon Bluewings": "Suwon Samsung Bluewings",
}


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for binomial proportion."""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def main():
    # 1) 当前赛季主胜率
    d = json.load(open(ROOT / f"data/raw/kleague_{SEASON_NOW}_all_matches.json", encoding="utf-8"))
    n = len(d)
    k = sum(1 for m in d if m["home_goals"] > m["away_goals"])
    rate = k / n
    lo, hi = wilson_ci(k, n)

    print(f"=== K League {SEASON_NOW} 主胜率漂移监控 ===")
    print(f"已完赛 {n} 场, 主胜 {k} 场 = {rate:.1%}")
    print(f"95% Wilson CI: [{lo:.1%}, {hi:.1%}]")
    print(f"历史基线(2022-2025): {BASE_HOME_WIN:.1%}")
    print()

    if lo <= BASE_HOME_WIN <= hi:
        verdict = "✅ 无显著漂移: 基线在 CI 内, 维持 2022-2025 模型"
    elif rate < BASE_HOME_WIN:
        verdict = "⚠️ 主胜率显著低于基线 → 考虑 2026 专属系数/近期加权"
    else:
        verdict = "⚠️ 主胜率显著高于基线 → 检查是否强势球队主场集中"
    print(f"判定: {verdict}")

    # 2) 市场锚: Pinnacle 隐含主胜率
    print()
    try:
        url = f"https://api.the-odds-api.com/v4/sports/soccer_korea_kleague1/odds/?apiKey={ODDS_KEY}&regions=eu&markets=h2h&oddsFormat=decimal"
        odds_data = json.load(urllib.request.urlopen(url, timeout=20))
        ph_list = []
        for g in odds_data:
            for bm in g.get("bookmakers", []):
                if bm["key"] != "pinnacle":
                    continue
                for mkt in bm["markets"]:
                    if mkt["key"] != "h2h":
                        continue
                    odds = {o["name"]: o["price"] for o in mkt["outcomes"]}
                    inv = {k2: 1 / v for k2, v in odds.items()}
                    tot = sum(inv.values())
                    # the-odds-api 用旧队名; 原始名查不到时尝试反向别名（旧名->新名）
                    home_raw = g["home_team"]
                    if home_raw not in inv:
                        home_raw = next(
                            (k for k in inv if ODDS_TEAM_ALIASES.get(k) == g["home_team"]),
                            home_raw,
                        )
                    ph_list.append(inv.get(home_raw, 0) / tot)
                    break
        if ph_list:
            market = sum(ph_list) / len(ph_list)
            print(f"市场锚(Pinnacle {len(ph_list)}场): 隐含主胜率平均 {market:.1%}")
            if abs(market - BASE_HOME_WIN) < 0.05:
                print("  市场定价 ≈ 历史基线 → 市场不认可漂移, 支持维持模型")
            else:
                print(f"  市场定价偏离基线 {abs(market - BASE_HOME_WIN):.1%}pp → 参考市场信号")
    except Exception as e:
        print(f"市场锚获取失败: {e}")

    print()
    print("建议: 每轮更新本脚本; 若赛季结束时主胜率仍 <32% 且市场同步走低, 再启用 2026 专属系数")


if __name__ == "__main__":
    main()
