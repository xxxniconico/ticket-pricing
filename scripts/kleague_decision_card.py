"""K League 1 决策卡生成器 — 世界杯决策卡格式（8 模块卡片）

格式对齐世界杯投注决策卡（tmp/gen_decision_0706.py）：
  每场一张 ╔═╗ 边框卡片，8 个编号模块：
  【1.基本面】【2.数据时效】【3.胜负平】【4.比分拆分】
  【5.结构规则】【6.历史校准】【7.矛盾点】【8.建议】
  最后 5 场汇总排序 + 策略建议。

用法: python scripts/kleague_decision_card.py
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
from kleague_predict import predict, poisson_matrix  # noqa: E402
from kleague_teams import cn  # noqa: E402

SNAPSHOT = ROOT / "data/raw/kleague_predictions_20260808.json"
HIST_SEASONS = (2022, 2023, 2024, 2025)
CUR_SEASON = 2026
W = 68  # 卡片宽度
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
            s, gf, ga = out["home"], m["home_goals"], m["away_goals"]
        elif m["away"] == team:
            s, gf, ga = out["away"], m["away_goals"], m["home_goals"]
        else:
            continue
        if gf > ga: s[0] += 1
        elif gf == ga: s[1] += 1
        else: s[2] += 1
        s[3] += gf; s[4] += ga
    return out


def hist_score_freq_by_diff():
    """2022-2025 按比赛时点 |PPG差| 分组: {bin: {"freq": {(i,j): p}, "n": N}}"""
    ms = load_matches(HIST_SEASONS)
    ms.sort(key=lambda m: (m["season"], m["date"]))
    pts, played = defaultdict(float), defaultdict(int)
    freq = defaultdict(Counter)
    for m in ms:
        h, a = m["home"], m["away"]
        hp = pts[h] / played[h] if played[h] else 1.3
        ap = pts[a] / played[a] if played[a] else 1.3
        diff = abs(hp - ap)
        b = ">0.9" if diff > 0.9 else ("0.6-0.9" if diff > 0.6 else ("0.3-0.6" if diff > 0.3 else "0-0.3"))
        freq[b][(m["home_goals"], m["away_goals"])] += 1
        if m["home_goals"] > m["away_goals"]: pts[h] += 3
        elif m["home_goals"] < m["away_goals"]: pts[a] += 3
        else: pts[h] += 1; pts[a] += 1
        played[h] += 1; played[a] += 1
    return {b: {"freq": {k: v / sum(c.values()) for k, v in c.items()}, "n": sum(c.values())} for b, c in freq.items()}


def market_probs(m):
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


# ── 渲染工具 ──────────────────────────────────────────

def line(text=""):
    """输出一行带边框的内容，超长截断"""
    t = str(text)
    if len(t) > W - 4:
        t = t[: W - 7] + "..."
    print(f"║  {t:<{W - 4}}║")


def divider():
    print("╠" + "═" * W + "╣")


def section(title):
    line(f"【{title}】")


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

    gaps = {k: (model[k] - mp[k]) * 100 for k in "HDA"}  # pp
    best = max(gaps, key=lambda k: abs(gaps[k]))
    best_dir_cn = {"H": "主胜", "D": "平局", "A": "客胜"}[best]

    hr, hp, hppg = st.get(home, (0, 0, 0))
    ar, ap, appg = st.get(away, (0, 0, 0))
    ppg_diff = hppg - appg
    hf = team_form_2026(home)
    af = team_form_2026(away)
    hw, hd, hl, hgf, hga = hf["home"]
    aw_, ad, al, agf, aga = af["away"]

    # 比分
    scores = poisson_matrix(lh, la)
    top_poisson = sorted(scores.items(), key=lambda x: -x[1])[:5]
    p_11, p_00, p_22 = scores.get((1, 1), 0), scores.get((0, 0), 0), scores.get((2, 2), 0)
    over25 = sum(p for (i, j), p in scores.items() if i + j >= 3)
    diff_bin = ">0.9" if abs(ppg_diff) > 0.9 else ("0.6-0.9" if abs(ppg_diff) > 0.6 else ("0.3-0.6" if abs(ppg_diff) > 0.3 else "0-0.3"))
    hb = hist_freq.get(diff_bin, {"freq": {}, "n": 0})
    hist_top = sorted(hb["freq"].items(), key=lambda x: -x[1])[:4]
    merged = {}
    for (i, j), p in scores.items():
        merged[(i, j)] = 0.6 * p + 0.4 * hb["freq"].get((i, j), 0)
    top_merged = sorted(merged.items(), key=lambda x: -x[1])[:5]

    # 结构规则
    rules = []
    if ppg_diff > 0.9:
        rules.append(("🟡", "K3 主强>0.9", f"|PPG差|={ppg_diff:.2f} 主胜58%/平仅12.5%(24场)"))
    if abs(ppg_diff) < 0.3:
        rules.append(("🟡", "K1 实力接近", "无平局高发区, 基线平28.6%"))
    if abs(ppg_diff) > 0.6:
        strong = home if ppg_diff > 0 else away
        rules.append(("🟢", "K2 弱队可爆冷", f"弱队胜率21.5%, 禁押规则不适用"))

    # 矛盾点
    conflicts = []
    if gaps[best] > 5:
        conflicts.append(f"模型{best_dir_cn}+{gaps[best]:.0f}pp vs 市场定价——市场可能有模型未建模信息")
    if hd >= 4 and "H" in best:
        conflicts.append(f"{cn(home)}主场平局{hd}场偏多, 主胜方向需谨慎")
    if not conflicts:
        conflicts.append("无显著矛盾")

    # ── 输出卡片 ──
    print("╔" + "═" * W + "╗")
    key = f"{cn(home)} vs {cn(away)}"
    print(f"║  {key:<{W - 4}}║")
    line(f"2026-08-08 18:30 | 第{hr}名({hp}分) vs 第{ar}名({ap}分) | PPG差 {ppg_diff:+.2f}")
    divider()

    section("1. 基本面")
    line(f"  {cn(home):<8s} 主场 {hw}W-{hd}D-{hl}L 进{hgf}/失{hga}  λ={lh:.2f}")
    line(f"  {cn(away):<8s} 客场 {aw_}W-{ad}D-{al}L 进{agf}/失{aga}  λ={la:.2f}")

    section("2. 数据时效")
    line(f"  赔率: Pinnacle 主{oh:.2f}/平{od:.2f}/客{oa:.2f} (8/4快照)")
    line(f"  状态: 2026 当前赛季 {CUR_SEASON} 积分榜/主客场 (21轮)")

    section("3. 胜负平")
    line(f"  {'方向':<4s} {'模型':>7s} {'市场':>7s} {'gap':>7s}")
    for k, cn_k in [("H", "主胜"), ("D", "平局"), ("A", "客胜")]:
        sign = "+" if gaps[k] >= 0 else ""
        line(f"  {cn_k:<4s} {model[k]:>6.1%} {mp[k]:>6.1%} {sign}{gaps[k]:>+5.1f}pp")

    section("4. 比分拆分")
    line(f"  泊松Top: " + "  ".join(f"{i}:{j}({p:.1%})" for (i, j), p in top_poisson))
    if hist_top:
        line(f"  历史同档|PPG差|{diff_bin}({hb['n']}场): " + "  ".join(f"{i}:{j}({p:.1%})" for (i, j), p in hist_top))
    line(f"  合并(泊松60%+历史40%): " + "  ".join(f"{i}:{j}({p:.1%})" for (i, j), p in top_merged))
    line(f"  平局细分: 1:1({p_11:.1%}) 0:0({p_00:.1%}) 2:2({p_22:.1%}) | 大球≥3({over25:.1%})")

    section("5. 结构规则")
    if rules:
        for tag, name, desc in rules:
            line(f"  {tag} {name}: {desc}")
    else:
        line(f"  ⚪ 无强信号规则命中 (|PPG差|={abs(ppg_diff):.2f} 在模糊区)")

    section("6. 历史校准")
    if hb["n"]:
        hw_n = sum(v for (i, j), v in hb["freq"].items() if i > j)
        dr_n = sum(v for (i, j), v in hb["freq"].items() if i == j)
        hbf = hb["freq"].get((1, 1), 0)
        line(f"  同档{hb['n']}场: 主胜{hw_n:.0%} 平{dr_n:.0%} | 最常见 1:1 占{hbf:.1%}")

    section("7. 矛盾点")
    for c in conflicts:
        line(f"  ⚠️ {c}")

    section("8. 建议")
    if abs(gaps[best]) >= 5:
        line(f"  ✅ gap={gaps[best]:+.1f}pp 达阈值 → 关注{best_dir_cn}方向")
        line(f"  方向: SPF{'胜' if best=='H' else '平' if best=='D' else '负'} / 比分参考第4节")
    else:
        line(f"  ⚠️ gap={gaps[best]:+.1f}pp<5pp → 无错价, 轻仓或跳过")
    line(f"  参考: 合并比分第1名 = {top_merged[0][0][0]}:{top_merged[0][0][1]}")

    print("╚" + "═" * W + "╝")
    print()
    return {
        "key": key, "best": best, "best_dir_cn": best_dir_cn,
        "gap": gaps[best], "top_merged": top_merged,
    }


def main():
    snap = json.load(open(SNAPSHOT, encoding="utf-8"))
    st = load_standings()
    hist_freq = hist_score_freq_by_diff()

    print("=" * (W + 4))
    print("  K League 1 · 2026-08-08 五场决策卡")
    print(f"  模型 v2 (历史+当前赛季混合) | 快照 {snap['created'][:16]}")
    print("=" * (W + 4))
    print()

    results = []
    for m in snap["matches"]:
        results.append(render(m, st, hist_freq))

    # ── 汇总 ──
    print("=" * (W + 4))
    print("  五场汇总")
    print("=" * (W + 4))
    print()
    for r in results:
        tag = "✅候选" if abs(r["gap"]) >= 5 else "— 中性"
        print(f"  {r['key']:<34s} 最大gap {r['best_dir_cn']} {r['gap']:+.1f}pp  {tag}  首选比分 {r['top_merged'][0][0][0]}:{r['top_merged'][0][0][1]}")
    print()
    print("  优先级(按|gap|排序):")
    for i, r in enumerate(sorted(results, key=lambda x: -abs(x["gap"])), 1):
        print(f"    {i}. {r['key']} — {r['best_dir_cn']} {r['gap']:+.1f}pp")
    print()
    print("  策略: 总预算300Y | 单注≤80Y | gap≥5pp才出手 | CRS优先Top3比分")
    print("  赛后: python scripts/kleague_verify_prediction.py 自动结算验证")
    print("=" * (W + 4))


if __name__ == "__main__":
    main()
