"""CFL 源文件质量检测 + standings 自洽校验（防线3，2026-08-05）

检测 sync_csl_data.py 输入源的质量问题——本次 bug 根因（round 空 + 重复记录）
就出在 CFL 源文件。独立脚本，sync 完成后自动联动执行。

检查项：
1. CFL 源文件重复记录 (date, home, away) —— INFO（sync 去重已处理, 建议 Hermes 侧清理）
2. round 为空/非"第N轮"的已赛场次 —— INFO（同上）
3. 已赛场次守恒（每轮≤8场, 无少赛轮时总量=轮数×8）—— FAIL 项
4. standings parquet 自洽（played 单调、最新轮 12-16 队）—— FAIL 项

用法: python scripts/verify_standings.py
退出码: 0=通过(仅INFO), 1=发现影响性问题, 2=错误
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CFL_JSON = Path("/mnt/c/Users/xxxsu/.openclaw/workspace/csl_project_v2/data/csl_final_production_ready.json")
STANDINGS = ROOT / "data/processed/standings_2026_by_round.parquet"

# 队名归一化（与 src/csl_context 对齐）
_NAME_ALIASES = {
    "大连英博": "大连英博海发",
    "河南俱乐部彩陶坊": "河南",
    "浙江俱乐部绿城": "浙江",
    "辽宁铁人楠波湾": "辽宁铁人",
}


def _norm(name: str) -> str:
    return _NAME_ALIASES.get(name, name)


def load_cfl_matches() -> list[dict]:
    if not CFL_JSON.exists():
        print(f"[ERROR] CFL 源文件不存在: {CFL_JSON}")
        sys.exit(2)
    d = json.load(open(CFL_JSON))
    matches = []
    for lg in d.get("leagues", []):
        if "中超" not in lg.get("name", ""):
            continue
        for m in lg.get("matches", []):
            s = m.get("score", {}) or {}
            if s.get("home") is None or s.get("away") is None:
                continue
            matches.append({
                "date": m["date"][:10],
                "round": str(m.get("round", "")),
                "home": _norm(m.get("home_club") or m.get("home") or ""),
                "away": _norm(m.get("away_club") or m.get("away") or ""),
            })
    return matches


def main():
    issues = []
    notes = []

    # ── 1) 重复记录（INFO: 源遗留, sync 已处理）──
    ms = load_cfl_matches()
    keys = Counter((m["date"], m["home"], m["away"]) for m in ms)
    dup = {k: v for k, v in keys.items() if v > 1}
    if dup:
        notes.append(
            f"CFL 源重复记录 {len(dup)} 组 (去重后{len(ms) - sum(v - 1 for v in dup.values())}场) "
            f"— sync 已按完整round优先处理, 建议 Hermes 侧清理"
        )

    # ── 2) round 空/非第N轮（INFO: 同上）──
    bad_round = [m for m in ms if not m["round"].startswith("第")]
    if bad_round:
        notes.append(
            f"CFL 源 {len(bad_round)} 场 round 为空/非'第N轮' — sync 去重已优先完整round版本, 不影响结果"
        )

    # ── 3) 场次守恒（FAIL 项）──
    dedup = list({(m["date"], m["home"], m["away"]): m for m in ms}.values())
    per_round = Counter(m["round"] for m in dedup if m["round"].startswith("第"))
    n_rounds = len(per_round)
    underfull = {r: c for r, c in per_round.items() if c < 8}
    overfull = {r: c for r, c in per_round.items() if c > 8}
    if n_rounds:
        if overfull:
            issues.append(f"轮次场次>8 (异常): {overfull}")
        expected = n_rounds * 8
        if not underfull and len(dedup) != expected:
            issues.append(f"无少赛轮但总场次 {len(dedup)} ≠ {expected}——存在未识别缺失")
        print(f"已赛 {len(dedup)} 场 / {n_rounds} 轮 (每轮8场共{expected}, 少赛轮: "
              + (", ".join(f"{r}:{c}场" for r, c in sorted(underfull.items())) or "无") + ")")

    # ── 4) standings parquet 自洽（FAIL 项）──
    if STANDINGS.exists():
        df = pd.read_parquet(STANDINGS)
        for t in df["team"].unique():
            sub = df[df["team"] == t].sort_values(
                "round",
                key=lambda s: s.map(
                    lambda r: int(re.search(r"(\d+)", r).group(1)) if re.search(r"(\d+)", r) else 0
                ),
            )
            prev = 0
            for _, r in sub.iterrows():
                if r["played"] < prev:
                    issues.append(f"parquet {t} {r['round']} played 回退 {prev}→{r['played']}")
                prev = r["played"]
        last_rnd = df["round"].iloc[-1]
        n_last = (df["round"] == last_rnd).sum()
        if not (12 <= n_last <= 16):
            issues.append(f"parquet 最新轮 {last_rnd} 有 {n_last} 队 (期望12-16)")
        print(f"parquet: {df['round'].nunique()} 轮, 最新 {last_rnd} {n_last} 队")
    else:
        issues.append(f"parquet 不存在: {STANDINGS}")

    # ── 汇总 ──
    print(f"\n检查项: CFL {len(ms)}条(去重后{len(dedup)}) | 问题 {len(issues)} 个")
    for n in notes:
        print(f"  [INFO] {n}")
    if issues:
        print("[FAIL] 发现影响 standings 的问题:")
        for x in issues:
            print(f"  - {x}")
        sys.exit(1)
    print("[OK] standings 自洽, 无影响性错误")
    sys.exit(0)


if __name__ == "__main__":
    main()
