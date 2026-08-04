"""K League 8/8 五场决策卡生成器

从预测快照 + 模型实时输出，生成完整决策卡（含市场隐含、gap、比分、结构规则）。
用法: python scripts/kleague_decision_card.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
from kleague_predict import predict, poisson_matrix  # noqa: E402
from kleague_teams import cn  # noqa: E402

SNAPSHOT = ROOT / "data/raw/kleague_predictions_20260808.json"
ODDS_TEAM_ALIASES = {
    "Sangju Sangmu FC": "Gimcheon Sangmu FC",
    "Ulsan Hyundai FC": "Ulsan HD",
    "Jeonbuk Motors": "Jeonbuk Hyundai Motors",
    "Daejeon Citizen": "Daejeon Hana Citizen",
    "Jeju United FC": "Jeju SK",
    "Suwon City FC": "Suwon FC",
    "Suwon Bluewings": "Suwon Samsung Bluewings",
}


def load_standings():
    """2026 当前积分榜: {team: (rank, pts)}"""
    d = json.load(open(ROOT / "data/raw/kleague_2026_all_matches.json", encoding="utf-8"))
    from collections import defaultdict
    pts = defaultdict(int)
    for m in d:
        h, a = m["home"], m["away"]
        if m["home_goals"] > m["away_goals"]: pts[h] += 3
        elif m["home_goals"] < m["away_goals"]: pts[a] += 3
        else: pts[h] += 1; pts[a] += 1
    rank = sorted(pts, key=lambda t: -pts[t])
    return {t: (i + 1, pts[t]) for i, t in enumerate(rank)}


def market_probs(m):
    """从快照 pinnacle 赔率计算去水市场概率"""
    inv = {k: 1 / v for k, v in m["pinnacle_odds"].items()}
    tot = sum(inv.values())
    home_raw, away_raw = m["home_odds_raw"], m["away_odds_raw"]
    if home_raw not in inv:
        home_raw = next(k for k in inv if ODDS_TEAM_ALIASES.get(k) == m["home"])
    if away_raw not in inv:
        away_raw = next(k for k in inv if ODDS_TEAM_ALIASES.get(k) == m["away"])
    return {
        "H": inv.get(home_raw, 0) / tot,
        "D": inv.get("Draw", 0) / tot,
        "A": inv.get(away_raw, 0) / tot,
    }, (inv.get(home_raw, 0), inv.get("Draw", 0), inv.get(away_raw, 0))


def render(m):
    home, away = m["home"], m["away"]
    mp, mkt = market_probs(m)
    model = m["model_probs"]
    odds = m["pinnacle_odds"]
    # 赔率显示: 原始名→中文
    def odd_for(team):
        raw = m["home_odds_raw"] if team == m["home"] else m["away_odds_raw"]
        return odds.get(raw) or next((v for k, v in odds.items() if ODDS_TEAM_ALIASES.get(k) == team), None)
    oh, oa = odd_for(home), odd_for(away)
    od = odds.get("Draw")

    gaps = {k: model[k] - mp[k] for k in "HDA"}
    best = max(gaps, key=gaps.get)

    # 比分概率
    lh, la = m["model_lambda"]
    scores = poisson_matrix(lh, la)
    top = sorted(scores.items(), key=lambda x: -x[1])[:4]

    print("═" * 52)
    print(f"🇰🇷 {cn(home)} ({home})  vs  {cn(away)} ({away})")
    st = load_standings()
    hr, hp = st.get(home, (0, 0))
    ar, ap = st.get(away, (0, 0))
    print(f"   开赛 2026-08-08 18:30 (北京时间)   积分榜: {cn(home)} 第{hr}({hp}分) vs {cn(away)} 第{ar}({ap}分)")
    print("─" * 52)
    print(f"   Pinnacle:  主 {oh:.2f} | 平 {od:.2f} | 客 {oa:.2f}")
    print(f"   市场隐含:  主 {mp['H']:.1%} | 平 {mp['D']:.1%} | 客 {mp['A']:.1%}")
    print(f"   模型概率:  主 {model['H']:.1%} | 平 {model['D']:.1%} | 客 {model['A']:.1%}  (λ {lh:.2f}/{la:.2f})")
    print(f"   Gap:       主 {gaps['H']:+.1%} | 平 {gaps['D']:+.1%} | 客 {gaps['A']:+.1%}")
    verdict = "✅ 正EV候选" if gaps[best] > 0.05 else ("⚠️ 负EV" if gaps[best] < -0.05 else "— 中性")
    print(f"   最大gap:   {best} {gaps[best]:+.1%}  {verdict}")
    print(f"   Top比分:   " + "  ".join(f"{i}:{j}({p:.1%})" for (i, j), p in top))
    print("═" * 52)
    print()


def main():
    snap = json.load(open(SNAPSHOT, encoding="utf-8"))
    print(f"📋 K League 1 决策卡 — 2026-08-08（5场）")
    print(f"   生成于 {snap['created'][:16]}，模型 v2（历史+当前赛季混合）\n")
    for m in snap["matches"]:
        render(m)


if __name__ == "__main__":
    main()
