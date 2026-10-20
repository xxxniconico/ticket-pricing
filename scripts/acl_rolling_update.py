#!/usr/bin/env python3
"""亚冠对手 ST/AP 滚动更新器（开票前 7-10 天 / 每个比赛周后执行）。

背景：ST/AP 打分方法（docs/acl-st-ap-scoring.md）是唯一事实源，
      但此前每次更新靠手工改 JSON → 无法审计、易算错。
      本脚本把"分项输入 → ST/AP → 级别"的换算固化为代码。

用法（以 MD3 全北现代为例）：
  python scripts/acl_rolling_update.py --match 2026-10-27_全北现代 \
    --rank 3 --rank-score 82 --league-coef 0.95 \
    --acl-score 82 --gd-score 69 --h2h-score 65 \
    --ap-brand 85 --ap-intl 85 --ap-topic 65 --ap-scarce 60 \
    --as-of 2026-10-20 --note "K1 第32轮(10/18) 第3名 47分 42:32(+10)；亚冠 MD1 2-1柏 / MD2 0-2神户"

权重（方法原文）：
  ST = 40% 联赛排名分×联赛系数 + 30% 亚冠战绩 + 20% 净胜球 + 10% 历史交锋
  AP = 40% 品牌力 + 25% 洲际知名度 + 20% 话题 + 15% 稀缺
级别：ST ≥75 S / 60-75 A / 45-60 B / <45 C（AP 用于细分 + 档）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RATINGS = ROOT / "data/processed/acl_opponent_ratings.json"

W_ST = {"rank": 0.40, "acl": 0.30, "gd": 0.20, "h2h": 0.10}
W_AP = {"brand": 0.40, "intl": 0.25, "topic": 0.20, "scarce": 0.15}


def tier_of(st: float, ap: float) -> str:
    if st >= 75:
        return "S"
    if st >= 60:
        return "A+" if ap >= 65 else "A"
    if st >= 45:
        return "B+" if ap >= 60 else "B"
    return "C"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--match", required=True)
    p.add_argument("--rank", type=int, help="联赛名次（仅记录）")
    p.add_argument("--rank-score", type=float, required=True, help="联赛排名分 0-100")
    p.add_argument("--league-coef", type=float, default=1.0,
                   help="联赛系数（K1=0.95 / J1=1.0 / 泰超=0.8 / 澳超=0.8 / 越V=0.65 / 港超=0.6）")
    p.add_argument("--acl-score", type=float, required=True, help="亚冠战绩分 0-100")
    p.add_argument("--gd-score", type=float, required=True, help="净胜球分 0-100")
    p.add_argument("--h2h-score", type=float, required=True, help="历史交锋分 0-100")
    p.add_argument("--ap-brand", type=float, required=True)
    p.add_argument("--ap-intl", type=float, required=True)
    p.add_argument("--ap-topic", type=float, required=True)
    p.add_argument("--ap-scarce", type=float, required=True)
    p.add_argument("--as-of", required=True, help="数据时点 YYYY-MM-DD")
    p.add_argument("--note", default="", help="本轮更新依据（写入 rolling_log）")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    cfg = json.loads(RATINGS.read_text(encoding="utf-8"))
    m = cfg["matches"].get(a.match)
    if m is None:
        print(f"ERROR: {a.match} 不在 {RATINGS.name}；可选：{list(cfg['matches'])}")
        return 1

    st = (a.rank_score * a.league_coef * W_ST["rank"] + a.acl_score * W_ST["acl"]
          + a.gd_score * W_ST["gd"] + a.h2h_score * W_ST["h2h"])
    ap = (a.ap_brand * W_AP["brand"] + a.ap_intl * W_AP["intl"]
          + a.ap_topic * W_AP["topic"] + a.ap_scarce * W_AP["scarce"])
    st, ap = round(st, 1), round(ap, 1)
    tier = tier_of(st, ap)

    print(f"=== {a.match} ===")
    print(f"ST {m.get('ST')} -> {st}   (排名 {a.rank_score}x{a.league_coef}x0.40="
          f"{a.rank_score * a.league_coef * 0.4:.2f} | 亚冠 {a.acl_score}x0.30={a.acl_score * 0.3:.2f}"
          f" | 净胜球 {a.gd_score}x0.20={a.gd_score * 0.2:.2f}"
          f" | 交锋 {a.h2h_score}x0.10={a.h2h_score * 0.1:.2f})")
    print(f"AP {m.get('AP')} -> {ap}   (品牌 {a.ap_brand}x0.40={a.ap_brand * 0.4:.2f}"
          f" | 洲际 {a.ap_intl}x0.25={a.ap_intl * 0.25:.2f}"
          f" | 话题 {a.ap_topic}x0.20={a.ap_topic * 0.2:.2f}"
          f" | 稀缺 {a.ap_scarce}x0.15={a.ap_scarce * 0.15:.2f})")
    print(f"级别 {m.get('tier')} -> {tier}   (S 阈值 75，距阈值 {st - 75:+.1f})")

    if a.dry_run:
        return 0

    log = m.setdefault("rolling_log", [])
    log.append({
        "date": a.as_of,
        "ST": st, "AP": ap, "tier": tier,
        "ST_prev": m.get("ST"), "AP_prev": m.get("AP"), "tier_prev": m.get("tier"),
        "inputs": {
            "rank": a.rank, "rank_score": a.rank_score, "league_coef": a.league_coef,
            "acl_score": a.acl_score, "gd_score": a.gd_score, "h2h_score": a.h2h_score,
            "ap": {"brand": a.ap_brand, "intl": a.ap_intl,
                   "topic": a.ap_topic, "scarce": a.ap_scarce},
        },
        "note": a.note,
    })
    m.update({"ST": st, "AP": ap, "tier": tier, "data_as_of": a.as_of,
              "source": f"acl_rolling_update.py（{a.as_of} 滚动更新）"})
    if m.get("next_update"):
        m["next_update"] = "赛后（acl_calibrate.py --write 回写实测）"
    cfg["as_of"] = a.as_of
    RATINGS.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写回 {RATINGS.name}（as_of={a.as_of}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
