"""K League 1 结构规则回测 (2022-2025, 912场)

用比赛时点的赛季累计 PPG 计算实力差，仿 CSL 的 ST 差规则做分层统计。
结论（2026-08-04，见 docs/notes/kleague_strategy_rules.md）：
- K League 无 CSL 式"平局高发区"：实力接近组平局仅 ~27-28%（CSL 是 39%）
- 弱队爆冷率 ~21.5%，远超 CSL 的 5% → 不能禁押弱队
- 唯一强信号：主强且|PPG差|>0.9 → 主胜58%、平局仅12.5%
- 强队客场只有 ~48% 胜率，K League 主场优势弱于中超
"""
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEASONS = (2022, 2023, 2024, 2025)


def load():
    ms = []
    for s in SEASONS:
        d = json.load(open(ROOT / f"data/raw/kleague_{s}_all_matches.json", encoding="utf-8"))
        for m in d:
            m["season"] = s
        ms.extend(d)
    ms.sort(key=lambda m: (m["season"], m["date"]))
    pts, played = defaultdict(float), defaultdict(int)
    for m in ms:
        h, a = m["home"], m["away"]
        m["home_ppg"] = pts[h] / played[h] if played[h] else 1.3
        m["away_ppg"] = pts[a] / played[a] if played[a] else 1.3
        m["ppg_diff"] = m["home_ppg"] - m["away_ppg"]
        m["abs_diff"] = abs(m["ppg_diff"])
        if m["home_goals"] > m["away_goals"]:
            pts[h] += 3
        elif m["home_goals"] < m["away_goals"]:
            pts[a] += 3
        else:
            pts[h] += 1
            pts[a] += 1
        played[h] += 1
        played[a] += 1
    return ms


def row(name, ms):
    n = len(ms)
    hw = sum(1 for m in ms if m["home_goals"] > m["away_goals"]) / n
    dr = sum(1 for m in ms if m["home_goals"] == m["away_goals"]) / n
    aw = sum(1 for m in ms if m["home_goals"] < m["away_goals"]) / n
    return f"{name:24s}: {n:3d}场 主胜{hw:.1%} 平{dr:.1%} 客胜{aw:.1%}"


def main():
    ms = load()
    mature = [m for m in ms if m["round"] >= 10]
    print(f"全样本 {len(ms)}场 | 成熟期(轮>=10) {len(mature)}场\n")
    print("=== 成熟期 绝对实力差 |PPG差| ===\n")
    for lo, hi in [(0, 0.3), (0.3, 0.6), (0.6, 0.9), (0.9, 99)]:
        print(row(f"|diff| {lo}-{hi}", [m for m in mature if lo <= m["abs_diff"] < hi]))
    print()
    print("=== 成熟期 强弱悬殊 (|diff|>0.6) ===\n")
    ms_big = [m for m in mature if m["abs_diff"] > 0.6]
    print(row("强队主场", [m for m in ms_big if m["ppg_diff"] > 0]))
    print(row("强队客场", [m for m in ms_big if m["ppg_diff"] < 0]))
    print(row("主强|diff|>0.9", [m for m in mature if m["ppg_diff"] > 0.9]))
    print(row("主强|diff|>1.2", [m for m in mature if m["ppg_diff"] > 1.2]))


if __name__ == "__main__":
    main()
