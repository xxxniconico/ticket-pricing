#!/usr/bin/env python3
"""亚冠（ACLE/ACL2）折减率与 γ 校准器。

背景：亚冠对手不在中超 ELO 体系内（ST/AP 为外部评估、尺度不可比），
      且 2025 ACL2 三场实证显示"对手维度贡献≈0" → 用 γ（AP/ST 弹性衰减）
      参数化：  Q_i = 锚 × (AP_i/AP_锚)^γ × (ST_i/ST_锚)^γ × ctx_i

用法:
  python scripts/acl_calibrate.py             # 打印校准报告与剩余场次预测
  python scripts/acl_calibrate.py --write     # 同时把库内实测回写 acl_opponent_ratings.json

数据源:
  data/processed/all_unified.parquet          # 实测（competition=ACL）
  data/processed/acl_opponent_ratings.json    # 对手 ST/AP + 引擎基线 + 情境乘数

赛后流程（MD3/MD6/MD8 落地后）:
  1. ingest_match.py <xlsx> ACL
  2. python scripts/acl_calibrate.py --write   # 复算 γ 并回写
  3. 把新的 γ / 预测同步到《亚冠四场预测更新》文档与 Obsidian §〇·四
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RATINGS = ROOT / "data/processed/acl_opponent_ratings.json"
PQ = ROOT / "data/processed/all_unified.parquet"

# 分档结构（2025 ACL2 三场 + 2026 MD1 跨对手稳定）：档位 → (面价, 占比)
STRUCT = {"L1": (199, 0.509), "T3": (299, 0.330), "T4": (459, 0.062),
          "T5": (539, 0.066), "T6": (688, 0.033)}
PAID_RATIO = 0.9765      # MD1 实测实付率
SIGMA = 0.20             # 场次间波动（2026 中超 13 场 CV 21.3% / 2025 ACL2 三场 22.1%）


def load_actuals() -> dict[str, dict]:
    """从 all_unified 读 ACL 各场实测量。"""
    if not PQ.exists():
        return {}
    df = pd.read_parquet(PQ)
    acl = df[df["competition"] == "ACL"]
    out = {}
    for mid, s in acl.groupby("match_id"):
        pay = pd.to_numeric(s["实际支付价格"], errors="coerce")
        out[mid] = {"tickets": int(len(s)), "revenue": float(pay.sum()),
                    "users": int(s["大麦用户id"].nunique())}
    return out


def estimate_gamma(rows: list[dict]) -> tuple[float | None, str]:
    """最小二乘过原点估计 γ（以最近一场已赛为锚）。样本不足时返回 None。"""
    played = [r for r in rows if r["q_norm"]]
    if len(played) < 2:
        return None, "样本不足（<2 场已赛）"
    anchor = played[-1]
    num = den = 0.0
    for r in played[:-1]:
        x = math.log(r["AP"] / anchor["AP"]) + math.log(r["ST"] / anchor["ST"])
        y = math.log(r["q_norm"] / anchor["q_norm"])
        if abs(x) < 1e-9:
            continue
        num += x * y
        den += x * x
    if den == 0:
        return None, "对手强度无差异，γ 不可辨识"
    return num / den, f"最小二乘（{len(played) - 1} 个对照样本）"


def predict(anchor: dict, tgt: dict, gamma: float) -> int:
    ratio = (tgt["AP"] / anchor["AP"]) * (tgt["ST"] / anchor["ST"])
    return round(anchor["q_norm"] * (ratio ** gamma) * tgt["ctx_mult"])


def revenue(tickets: int) -> float:
    """按跨赛季稳定分档结构 + MD1 实付率估算收入（万元）。"""
    total = sum(round(tickets * share) * face for face, share in STRUCT.values())
    return total * PAID_RATIO / 1e4


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="把库内实测回写 ratings JSON")
    args = ap.parse_args()

    if not RATINGS.exists():
        print(f"ERROR: {RATINGS} 不存在")
        return 1
    cfg = json.loads(RATINGS.read_text(encoding="utf-8"))
    actuals = load_actuals()

    rows = []
    for mid, m in cfg["matches"].items():
        a = actuals.get(mid, {})
        tickets = a.get("tickets", m.get("actual_tickets"))
        if args.write and a:
            m["actual_tickets"] = a["tickets"]
            m["actual_revenue_wan"] = round(a["revenue"] / 1e4, 2)
            m["actual_users"] = a["users"]
        ctx = m.get("ctx_mult")
        q_norm = (tickets / ctx) if (tickets and ctx) else None
        rows.append({**m, "match_id": mid, "opp": m.get("opponent", "?"),
                     "tickets": tickets, "ctx_mult": ctx, "q_norm": q_norm,
                     "baseline": m.get("baseline_engine")})
    rows.sort(key=lambda r: str(r.get("match_date") or r["match_id"]))

    print("=" * 96)
    print(f"亚冠校准报告（ACLE 为主） · 数据 as_of {cfg['as_of']}")
    print("=" * 96)
    print(f"{'场次':<12}{'对手':<12}{'ST/AP':<14}{'引擎':>7}{'ctx':>7}{'实际':>7}{'去情境':>8}{'实现率':>8}")
    print("-" * 96)
    for r in rows:
        st_ap = f"{r['ST']}/{r['AP']}" if r.get("ST") else "—（未评估）"
        eng = f"{r['baseline']:,}" if r.get("baseline") else "—"
        act = f"{r['tickets']:,}" if r["tickets"] else "未赛"
        qn = f"{r['q_norm']:,.0f}" if r["q_norm"] else "—"
        impl = f"{r['tickets'] / r['baseline']:.3f}" if (r["tickets"] and r.get("baseline")) else "—"
        print(f"{r['match_id'][:11]:<12}{r['opp'][:10]:<12}{st_ap:<14}{eng:>7}{r['ctx_mult'] or 0:>7.2f}{act:>7}{qn:>8}{impl:>8}")

    played = [r for r in rows if r["q_norm"] and r.get("ST") and r.get("AP")]
    print()
    if not played:
        print("⚠️ 尚无带 ST/AP 的已赛场次 → 无法校准")
        return 0
    anchor = played[-1]
    gamma_hat, how = estimate_gamma(played)
    if gamma_hat is None:
        gamma_hat = cfg["calibration"]["gamma"]
        print(f"γ 估计: {gamma_hat:.3f}（沿用 JSON 预设 — {how}）")
    else:
        print(f"γ 估计: {gamma_hat:.3f}（{how}）")
    print(f"锚: {anchor['match_id']} · 去情境 {anchor['q_norm']:,.0f} 张 "
          f"(ST {anchor['ST']} / AP {anchor['AP']})")

    print("\n剩余场次预测（γ = %.3f，σ = %.0f%%）" % (gamma_hat, SIGMA * 100))
    print("-" * 96)
    print(f"{'场次':<12}{'对手':<12}{'预测':>8}{'68% 区间':>20}{'收入(万)':>10}")
    tot_q = tot_rev = 0
    for r in rows:
        if not (r.get("ST") and r.get("AP") and r.get("ctx_mult")):
            continue
        if r["tickets"]:
            continue          # 已赛
        q = predict(anchor, r, gamma_hat)
        lo, hi = round(q * (1 - SIGMA)), round(q * (1 + SIGMA))
        rev = revenue(q)
        tot_q += q
        tot_rev += rev
        print(f"{r['match_id'][:11]:<12}{r['opp'][:10]:<12}{q:>8,}{f'{lo:,}-{hi:,}':>20}{rev:>10.1f}")
    if tot_q:
        print("-" * 96)
        print(f"{'合计':<24}{tot_q:>8,}{'':>20}{tot_rev:>10.1f}")

    if args.write:
        cfg["calibration"].update({
            "as_of": str(pd.Timestamp.now().date()),
            "gamma": round(gamma_hat, 3),
            "anchor_match": anchor["match_id"],
            "gamma_method": how,
        })
        RATINGS.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n✅ 已回写 {RATINGS.name}（γ={gamma_hat:.3f}，锚={anchor['match_id']}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
