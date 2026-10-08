#!/usr/bin/env python3
"""决策卡事实数据统一出口 —— 防止手工誊抄误读。

用法:
  python scripts/card_facts.py form --team 北京国安 --n 5
  python scripts/card_facts.py form --team 青岛西海岸 --n 6
  python scripts/card_facts.py h2h --team 青岛西海岸
  python scripts/card_facts.py attendance --team 青岛西海岸
  python scripts/card_facts.py standings
  python scripts/card_facts.py all --team 青岛西海岸 --n 6     # 出卡所需全部事实

────────────────────────────────────────────────────────────────────────
⚠️ 铁律（2026-10-08 教训，用户要求"以后不要再出现这个问题"）

  决策卡/报告内所有**事实数据**（近期战绩、比分、排名、历史到场、交锋）
  必须由本脚本输出后**直接使用或直接复制**，禁止手工誊抄或凭记忆书写。

  比分一律 **本方视角 GF-GA**（本方进球在前），且必须带主客与对手名。
  输出形如: 客胜天津 4-2 → 表示"国安客场 4:2 战胜天津"

  【根因案例】把 CFL 源 `score.home/away`（主队-客队）当作"本方视角"读取，
  导致国安 8/15 客战天津（源: 天津 2-4 国安）、8/18 客战申花（源: 申花 0-3 国安）
  两场**客胜被写成客负**，错误进入决策卡文字。引擎输出不受影响，但文字误导阅读者。
────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.csl_context import load_csl_data, _normalize_club_name  # noqa: E402

GUOAN = "北京国安"
RESULT_CN = {"W": "胜", "D": "平", "L": "负"}


def _perspective(m: dict, team: str) -> tuple[int, int, str, bool, str]:
    """返回 (本方进球, 本方失球, 结果 W/D/L, 是否主场, 对手名)。"""
    is_home = m["home"] == team
    gf = m["hg"] if is_home else m["ag"]
    ga = m["ag"] if is_home else m["hg"]
    res = "W" if gf > ga else ("D" if gf == ga else "L")
    opp = m["away"] if is_home else m["home"]
    return gf, ga, res, is_home, opp


def _completed(matches: list[dict], team: str, upto: str | None = None) -> list[dict]:
    out = []
    for m in matches:
        if team not in (m["home"], m["away"]):
            continue
        if m.get("hg") is None or m.get("ag") is None:
            continue
        if upto and m["date"] > upto:
            continue
        out.append(m)
    return sorted(out, key=lambda x: x["date"])


def recent_form(matches: list[dict], team: str, n: int = 5, upto: str | None = None) -> str:
    ms = _completed(matches, team, upto)[-n:]
    parts, w, d, l = [], 0, 0, 0
    for m in ms:
        gf, ga, res, is_home, opp = _perspective(m, team)
        w += res == "W"; d += res == "D"; l += res == "L"
        parts.append(f"{'主' if is_home else '客'}{RESULT_CN[res]}{opp} {gf}-{ga}")
    tail = f"（{w}胜{d}平{l}负{'不败' if l == 0 else ''}）"
    return " · ".join(parts) + tail


def recent_form_rows(matches: list[dict], team: str, n: int = 6, upto: str | None = None) -> list[str]:
    """Markdown 表格行（本方视角），可直接粘进决策卡。"""
    rows = []
    for m in _completed(matches, team, upto)[-n:]:
        gf, ga, res, is_home, opp = _perspective(m, team)
        mark = {"W": "✅", "D": "➖", "L": "❌"}[res]
        rnd = str(m.get("round") or "").replace("第", "").replace("轮", "")
        rows.append(f"| {rnd} | {m['date'][5:]} | {'主' if is_home else '客'} | {opp} | {gf}-{ga} | {mark} |")
    return rows


def h2h(matches: list[dict], team: str) -> list[str]:
    rows = []
    for m in _completed(matches, team):
        if GUOAN not in (m["home"], m["away"]):
            continue
        gf, ga, res, _, _ = _perspective(m, GUOAN)
        ha = "主" if m["home"] == GUOAN else "客"
        rows.append(f"| {m['date']} | {m.get('round','')} | {ha} | {m['home']} {m['hg']}-{m['ag']} {m['away']} | 国安{RESULT_CN[res]} {gf}-{ga} |")
    return rows


def attendance(team: str) -> list[str]:
    from src.opponent_rating import _load_guoan_home_attendance
    hh = _load_guoan_home_attendance()
    sub = hh[hh["opponent"] == _normalize_club_name(team)].sort_values("match_date")
    if not len(sub):
        return ["无历史样本"]
    out = [f"样本 {len(sub)} 场 | 场均 {sub['attendance'].mean():,.0f} 张"]
    for _, r in sub.iterrows():
        out.append(f"| {str(r['match_date'])[:10]} | {r['attendance']:,.0f} |")
    return out


def standings_rows() -> list[str]:
    matches, _, ded = load_csl_data()
    dmap = ded.get("deductions_by_club", {}) if isinstance(ded, dict) else {}
    pts, gf, ga, played = {}, {}, {}, {}
    for m in matches:
        if m.get("hg") is None or not m["date"].startswith("2026"):
            continue
        for t, g, c in ((m["home"], m["hg"], m["ag"]), (m["away"], m["ag"], m["hg"])):
            pts[t] = pts.get(t, 0) + (3 if g > c else (1 if g == c else 0))
            gf[t] = gf.get(t, 0) + g; ga[t] = ga.get(t, 0) + c
            played[t] = played.get(t, 0) + 1
    for t in pts:
        pts[t] -= dmap.get(t, 0)
    rk = sorted(pts.items(), key=lambda x: (-x[1], -(gf[x[0]] - ga[x[0]]), -gf[x[0]]))
    rows = ["| 排名 | 球队 | 积分 | 已赛 | 净胜球 | 扣分 |", "|---:|---|---:|---:|---:|---:|"]
    for i, (t, p) in enumerate(rk, 1):
        rows.append(f"| {i} | {t} | {p} | {played[t]} | {gf[t]-ga[t]:+d} | {dmap.get(t,0)} |")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="决策卡事实数据统一出口")
    ap.add_argument("cmd", choices=["form", "formrows", "h2h", "attendance", "standings", "all"])
    ap.add_argument("--team", default="青岛西海岸")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--upto", default=None, help="截止日期 YYYY-MM-DD（默认全部已赛）")
    args = ap.parse_args()

    matches, _, _ = load_csl_data()
    team = _normalize_club_name(args.team)

    if args.cmd == "form":
        for t, n in (("北京国安", 5), (team, max(args.n, 6))):
            print(f"【{t}】近 {n} 场: {recent_form(matches, t, n, args.upto)}")
    elif args.cmd == "formrows":
        print(f"<!-- {team} 近 {args.n} 场（本方视角）-->")
        for r in recent_form_rows(matches, team, args.n, args.upto):
            print(r)
    elif args.cmd == "h2h":
        for r in h2h(matches, team):
            print(r)
    elif args.cmd == "attendance":
        for r in attendance(team):
            print(r)
    elif args.cmd == "standings":
        for r in standings_rows():
            print(r)
    elif args.cmd == "all":
        print("=" * 68)
        print(f"决策卡事实数据 · 对手={team} · 来自 scripts/card_facts.py")
        print("=" * 68)
        for t, n in (("北京国安", 5), (team, max(args.n, 6))):
            print(f"\n【{t}】近 {n} 场（本方视角）")
            print("  " + recent_form(matches, t, n, args.upto))
            for r in recent_form_rows(matches, t, n, args.upto):
                print("  " + r)
        print(f"\n【{team} 作客工体历史到场】")
        for r in attendance(team):
            print("  " + r)
        print(f"\n【{team} vs 国安 交锋】")
        for r in h2h(matches, team):
            print("  " + r)
        print("\n【当前积分榜（官方口径）】")
        for r in standings_rows()[:10]:
            print("  " + r)


if __name__ == "__main__":
    main()
