"""K League 1 比赛预测决策卡生成器 (v1, 2026-08-04)

流程：
1. 可选赔率输入：从 the-odds-api 拉 Pinnacle 赔率 或手动输入 → 反推泊松 λ
2. 无赔率时：用历史基线 λ + 主客场系数 1.165 + 球队攻防调整
3. 比分概率矩阵（泊松独立）→ Top5 比分
4. 结构规则叠加（docs/notes/kleague_strategy_rules.md K1-K5）
5. 输出决策卡

用法：
  python scripts/kleague_predict.py "Ulsan HD" "Jeonbuk Hyundai Motors"
  python scripts/kleague_predict.py "Ulsan HD" "Jeonbuk Hyundai Motors" 2.05 3.30 3.60
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEASONS = (2022, 2023, 2024, 2025)

LAM_HOME_BASE = 1.376   # 2022-2025 主场场均进球
LAM_AWAY_BASE = 1.181   # 客场场均进球
HOME_COEF = LAM_HOME_BASE / LAM_AWAY_BASE  # 1.165
DRAW_RATE = 0.286       # 全样本平局率


def load_history():
    """返回 {team: {home_goals: [...], away_goals: [...]}} 2026赛季前的攻防表现"""
    stats = {}
    for s in SEASONS:
        d = json.load(open(ROOT / f"data/raw/kleague_{s}_all_matches.json", encoding="utf-8"))
        for m in d:
            for side in ("home", "away"):
                t = m[side]
                stats.setdefault(t, {"gf": [], "ga": []})
                if side == "home":
                    stats[t]["gf"].append(m["home_goals"])
                    stats[t]["ga"].append(m["away_goals"])
                else:
                    stats[t]["gf"].append(m["away_goals"])
                    stats[t]["ga"].append(m["home_goals"])
    return stats


def team_adjust(stats, team):
    """球队攻防调整因子：相对基线。返回 (attack, defense)"""
    if team not in stats or len(stats[team]["gf"]) < 10:
        return 1.0, 1.0
    s = stats[team]
    n = len(s["gf"])
    avg_gf = sum(s["gf"]) / n
    avg_ga = sum(s["ga"]) / n
    league_gf = (LAM_HOME_BASE + LAM_AWAY_BASE) / 2
    return avg_gf / league_gf, avg_ga / league_gf


def odds_to_lambda(h_odds, d_odds, a_odds):
    """从 1X2 赔率反推 λ_home/λ_away（去水后网格搜索）"""
    inv_h, inv_d, inv_a = 1 / h_odds, 1 / d_odds, 1 / a_odds
    total = inv_h + inv_d + inv_a
    ph, pd, pa = inv_h / total, inv_d / total, inv_a / total

    best = None
    for lh in [x / 100 for x in range(50, 300, 2)]:
        for la in [x / 100 for x in range(50, 300, 2)]:
            exp_h = 1 - math.exp(-lh)
            exp_a = 1 - math.exp(-la)
            # 简化：用独立泊松算 1X2 概率
            p_h = 0.0
            for i in range(0, 10):
                for j in range(0, 10):
                    p = (lh ** i) * math.exp(-lh) / math.factorial(i)
                    p *= (la ** j) * math.exp(-la) / math.factorial(j)
                    if i > j:
                        p_h += p
            p_a = 0.0
            for i in range(0, 10):
                for j in range(0, 10):
                    p = (lh ** i) * math.exp(-lh) / math.factorial(i)
                    p *= (la ** j) * math.exp(-la) / math.factorial(j)
                    if i < j:
                        p_a += p
            p_d = 1 - p_h - p_a
            err = (p_h - ph) ** 2 + (p_d - pd) ** 2 + (p_a - pa) ** 2
            if best is None or err < best[0]:
                best = (err, lh, la)
    return best[1], best[2]


def poisson_matrix(lh, la, max_goals=8):
    scores = {}
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            p = (lh ** i) * math.exp(-lh) / math.factorial(i)
            p *= (la ** j) * math.exp(-la) / math.factorial(j)
            scores[(i, j)] = p
    return scores


def predict(home, away, h_odds=None, d_odds=None, a_odds=None):
    stats = load_history()

    if h_odds:
        lh, la = odds_to_lambda(h_odds, d_odds, a_odds)
        src = "赔率反推"
    else:
        att_h, def_h = team_adjust(stats, home)
        att_a, def_a = team_adjust(stats, away)
        lh = LAM_HOME_BASE * att_h * def_a
        la = LAM_AWAY_BASE * att_a * def_h
        src = "历史基线+攻防调整"

    scores = poisson_matrix(lh, la)
    top = sorted(scores.items(), key=lambda x: -x[1])[:5]
    p_h = sum(p for (i, j), p in scores.items() if i > j)
    p_d = sum(p for (i, j), p in scores.items() if i == j)
    p_a = sum(p for (i, j), p in scores.items() if i < j)

    # 结构规则提示
    notes = []
    if abs(p_d - DRAW_RATE) > 0.03:
        notes.append(f"平局概率{p_d:.0%} vs 基线{DRAW_RATE:.0%}")
    if max(p_h, p_a) > 0.55:
        notes.append("单边概率>55%，符合K3主强信号候选（需|PPG差|>0.9）")

    return {
        "home": home, "away": away, "src": src,
        "lambda": (round(lh, 3), round(la, 3)),
        "probs": {"H": p_h, "D": p_d, "A": p_a},
        "top_scores": [(f"{i}:{j}", round(p, 4)) for (i, j), p in top],
        "notes": notes,
    }


def render_card(r):
    print("═" * 46)
    print(f"🇰🇷 K League 1  {r['home']} vs {r['away']}")
    print(f"   λ: {r['lambda'][0]} / {r['lambda'][1]}  ({r['src']})")
    print("═" * 46)
    print(f"  主胜 {r['probs']['H']:.1%} | 平 {r['probs']['D']:.1%} | 客胜 {r['probs']['A']:.1%}")
    print()
    print("  Top5 比分:")
    for sc, p in r["top_scores"]:
        print(f"    {sc}  {p:.1%}")
    if r["notes"]:
        print()
        print("  ⚠️", " | ".join(r["notes"]))
    print("═" * 46)


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        sys.exit(1)
    home, away = args[0], args[1]
    odds = [float(x) for x in args[2:5]] if len(args) >= 5 else None
    result = predict(home, away, *(odds or [None] * 3))
    render_card(result)
