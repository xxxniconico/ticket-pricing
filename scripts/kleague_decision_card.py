"""K League 1 完整决策卡生成器（8/8 五场）

模块：赔率/市场隐含、模型概率、Gap、比分预测(泊松+历史同实力差频率交叉验证)、
球队主客场状态、结构规则命中、大球小球、建议。

用法: python scripts/kleague_decision_card.py
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
from kleague_predict import predict, poisson_matrix  # noqa: E402
from kleague_teams import cn  # noqa: E402

SNAPSHOT = ROOT / "data/raw/kleague_predictions_20260808.json"
HIST_SEASONS = (2022, 2023, 2024, 2025)
CUR_SEASON = 2026
ODDS_TEAM_ALIASES = {
    "Sangju Sangmu FC": "Gimcheon Sangmu FC",
    "Ulsan Hyundai FC": "Ulsan HD",
    "Jeonbuk Motors": "Jeonbuk Hyundai Motors",
    "Daejeon Citizen": "Daejeon Hana Citizen",
    "Jeju United FC": "Jeju SK",
    "Suwon City FC": "Suwon FC",
    "Suwon Bluewings": "Suwon Samsung Bluewings",
}


# ── 数据层 ──────────────────────────────────────────

def load_matches(seasons):
    ms = []
    for s in seasons:
        d = json.load(open(ROOT / f"data/raw/kleague_{s}_all_matches.json", encoding="utf-8"))
        for m in d:
            m["season"] = s
        ms.extend(d)
    return ms


def load_standings():
    """2026 当前积分榜: {team: (rank, pts, ppg)}"""
    d = load_matches([CUR_SEASON])
    pts, played = defaultdict(int), defaultdict(int)
    for m in d:
        h, a = m["home"], m["away"]
        if m["home_goals"] > m["away_goals"]: pts[h] += 3
        elif m["home_goals"] < m["away_goals"]: pts[a] += 3
        else: pts[h] += 1; pts[a] += 1
        played[h] += 1; played[a] += 1
    rank = sorted(pts, key=lambda t: -pts[t])
    return {t: (i + 1, pts[t], pts[t] / played[t]) for i, t in enumerate(rank)}


def team_form_2026(team):
    """2026 主/客场战绩: (home: [W,D,L,GF,GA], away: [...])"""
    d = load_matches([CUR_SEASON])
    out = {"home": [0, 0, 0, 0, 0], "away": [0, 0, 0, 0, 0]}
    for m in d:
        if m["home"] == team:
            s = out["home"]
            gf, ga = m["home_goals"], m["away_goals"]
        elif m["away"] == team:
            s = out["away"]
            gf, ga = m["away_goals"], m["home_goals"]
        else:
            continue
        if gf > ga: s[0] += 1
        elif gf == ga: s[1] += 1
        else: s[2] += 1
        s[3] += gf; s[4] += ga
    return out


def hist_score_freq_by_diff():
    """2022-2025 按比赛时点 |PPG差| 分组的真实比分频率 {bin: {(i,j): count}}"""
    ms = load_matches(HIST_SEASONS)
    ms.sort(key=lambda m: (m["season"], m["date"]))
    pts, played = defaultdict(float), defaultdict(int)
    freq = defaultdict(Counter := __import__("collections").Counter)
    for m in ms:
        h, a = m["home"], m["away"]
        hp = pts[h] / played[h] if played[h] else 1.3
        ap = pts[a] / played[a] if played[a] else 1.3
        diff = abs(hp - ap)
        if diff < 0.3: b = "0-0.3"
        elif diff < 0.6: b = "0.3-0.6"
        elif diff < 0.9: b = "0.6-0.9"
        else: b = ">0.9"
        freq[b][(m["home_goals"], m["away_goals"])] += 1
        if m["home_goals"] > m["away_goals"]: pts[h] += 3
        elif m["home_goals"] < m["away_goals"]: pts[a] += 3
        else: pts[h] += 1; pts[a] += 1
        played[h] += 1; played[a] += 1
    return {
        b: {"freq": {k: v / sum(c.values()) for k, v in c.items()}, "n": sum(c.values())}
        for b, c in freq.items()
    }


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
    }


def find_rule(ppg_diff_home, home, away, st):
    """结构规则命中（kleague_strategy_rules.md K1-K5 简化版）"""
    notes = []
    diff = ppg_diff_home
    if diff > 0.9:
        notes.append("K3: 主强|PPG差|>0.9 → 主胜58%/平局仅12.5%（样本24场，置信中低）")
    if abs(diff) < 0.3:
        notes.append("K1: 实力接近，无平局高发区（基线平28.6%）")
    return notes


# ── 渲染 ──────────────────────────────────────────

def render(m, st, hist_freq):
    home, away = m["home"], m["away"]
    mp = market_probs(m)
    model = m["model_probs"]
    odds = m["pinnacle_odds"]
    lh, la = m["model_lambda"]

    def odd_for(team):
        raw = m["home_odds_raw"] if team == m["home"] else m["away_odds_raw"]
        return odds.get(raw) or next((v for k, v in odds.items() if ODDS_TEAM_ALIASES.get(k) == team), None)
    oh, oa = odd_for(home), odd_for(away)
    od = odds.get("Draw")

    gaps = {k: model[k] - mp[k] for k in "HDA"}
    best = max(gaps, key=gaps.get)
    verdict = "✅ 正EV候选" if gaps[best] > 0.05 else ("⚠️ 负EV" if gaps[best] < -0.05 else "— 中性")

    hr, hp, hppg = st.get(home, (0, 0, 0))
    ar, ap, appg = st.get(away, (0, 0, 0))
    ppg_diff = hppg - appg
    hf = team_form_2026(home)
    af = team_form_2026(away)

    # ── 比分预测：泊松矩阵 ──
    scores = poisson_matrix(lh, la)
    top_poisson = sorted(scores.items(), key=lambda x: -x[1])[:5]
    # 平局细分
    p_11 = scores.get((1, 1), 0); p_00 = scores.get((0, 0), 0); p_22 = scores.get((2, 2), 0)
    # 大球/零封
    over25 = sum(p for (i, j), p in scores.items() if i + j >= 3)
    zero_h = sum(p for (i, j), p in scores.items() if j == 0)
    zero_a = sum(p for (i, j), p in scores.items() if i == 0)
    p_h, p_d, p_a = model["H"], model["D"], model["A"]

    # ── 交叉验证：历史同实力差区间真实比分 ──
    diff_bin = ">0.9" if abs(ppg_diff) > 0.9 else ("0.6-0.9" if abs(ppg_diff) > 0.6 else ("0.3-0.6" if abs(ppg_diff) > 0.3 else "0-0.3"))
    hist_block = hist_freq.get(diff_bin, {"freq": {}, "n": 0})
    hist_n = hist_block["n"]
    hist_top = sorted(hist_block["freq"].items(), key=lambda x: -x[1])[:4]
    # 合并：泊松60% + 历史同档频率40%（仿 CSL 交叉验证法）
    merged = {}
    for (i, j), p in scores.items():
        merged[(i, j)] = 0.6 * p + 0.4 * hist_block["freq"].get((i, j), 0)
    top_merged = sorted(merged.items(), key=lambda x: -x[1])[:5]

    print("═" * 56)
    print(f"🇰🇷 {cn(home)} ({home})  vs  {cn(away)} ({away})")
    print(f"   2026-08-08 18:30 | 积分榜: 第{hr}({hp}分, PPG {hppg:.2f}) vs 第{ar}({ap}分, PPG {appg:.2f}) | PPG差 {ppg_diff:+.2f}")
    print("─" * 56)
    print(f"【1. 赔率】Pinnacle: 主 {oh:.2f} | 平 {od:.2f} | 客 {oa:.2f}")
    print(f"           市场隐含: 主 {mp['H']:.1%} | 平 {mp['D']:.1%} | 客 {mp['A']:.1%}")
    print(f"【2. 模型】λ {lh:.2f}/{la:.2f} → 主 {p_h:.1%} | 平 {p_d:.1%} | 客 {p_a:.1%}")
    print(f"【3. Gap】主 {gaps['H']:+.1%} | 平 {gaps['D']:+.1%} | 客 {gaps['A']:+.1%} → 最大 {best} {gaps[best]:+.1%} {verdict}")
    print("─" * 56)
    # 球队状态
    hw, hd, hl, hgf, hga = hf["home"]
    aw_, ad, al, agf, aga = af["away"]
    print(f"【4. 状态】{cn(home)} 主场 {hw}胜{hd}平{hl}负 进{hgf}/失{hga} | {cn(away)} 客场 {aw_}胜{ad}平{al}负 进{agf}/失{aga}")
    # 结构规则
    rules = find_rule(ppg_diff, home, away, st)
    if rules:
        print(f"【5. 结构】{' | '.join(rules)}")
    # 比分预测
    print(f"【6. 比分预测】泊松: " + "  ".join(f"{i}:{j}({p:.1%})" for (i, j), p in top_poisson))
    if hist_top:
        print(f"          历史同档|PPG差|{diff_bin}({hist_n}场): " +
              "  ".join(f"{i}:{j}({p:.1%})" for (i, j), p in hist_top))
    print(f"          合并: " + "  ".join(f"{i}:{j}({p:.1%})" for (i, j), p in top_merged))
    print(f"          平局细分: 1:1({p_11:.1%}) 0:0({p_00:.1%}) 2:2({p_22:.1%}) | 大球≥3球({over25:.1%}) | 零封:主{zero_h:.1%}/客{zero_a:.1%}")
    print("═" * 56)
    print()


def main():
    snap = json.load(open(SNAPSHOT, encoding="utf-8"))
    st = load_standings()
    hist_freq = hist_score_freq_by_diff()
    print(f"📋 K League 1 完整决策卡 — 2026-08-08（5场，18:30 北京时间）")
    print(f"   模型 v2（历史+当前赛季混合）| 比分交叉验证: 泊松60%+历史同档40%\n")
    for m in snap["matches"]:
        render(m, st, hist_freq)


if __name__ == "__main__":
    main()
