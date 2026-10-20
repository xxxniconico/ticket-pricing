#!/usr/bin/env python3
"""亚冠 ST/AP → 中超等效级别映射（本士认知折扣法）。

=== 用户 2026-10-20 提出的逻辑 ===
  亚冠在中国的宣传较弱 → 即使亚冠球队 ST（实力）较高，
  但因为与国安交手少、球迷不熟悉 → **在北京观众心里形成的 AP（吸引力）很低**。
  所以"亚洲 S 级"不等于"工体 S 级"。

=== 为什么现有 AP 打分必然偏高 ===
  现用 AP = 40% 品牌力 + 25% 洲际知名度 + 20% 话题 + 15% 稀缺
  这四项全部是**亚足联/洲际视角**的指标（全北：亚冠 2 冠、K1 豪门），
  完全不包含"北京观众能否叫出对手名字 / 是否记得某场交锋"。
  → 它是"对手在亚洲有多强"，不是"北京球迷有多想买票"。

=== 本脚本的两种等价表达（对数线性下可互相换算）===
  (a) 弹性衰减：γ_ac = γ_cn × d      （v4 采用，γ=0.15，d = 0.15/0.352 = 0.43）
  (b) 认知折扣：AP_cn = AP_asia × d  （本脚本采用，把 AP 折算回中超尺度 0-45）
  两者在 log-linear 下近似等价：AP^γ_ac = (AP×d)^γ_cn ⟺ γ_ac = γ_cn·d

=== 用 MD1 实测反推 d（唯一实证锚）===
  MD1 浦项：亚洲 AP 66.3 → 去情境 q_norm 6,367 → 落在中超 C 级标尺（实测均值 6,458）
  → 北京感知 AP ≈ 中超 C 级区间（22-28），即 d ≈ 0.35-0.42

用法:
  python scripts/acl_tier_mapping.py            # 打印映射表 + 回测
  python scripts/acl_tier_mapping.py --json     # 机器可读
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RATINGS = ROOT / "data/processed/acl_opponent_ratings.json"

# ── 中超 13 场实测 q_norm 标尺（v3 标定，commit b4184f5，α=0.352/β=0.408）──
CSL_SCALE = {          # 级别 → 实测 q_norm 均值
    "S": 12799,
    "A": 10669,
    "B": 8441,
    "C": 6458,
}
CSL_ENGINE = {"S": 12600, "A": 10900, "B": 8200, "C": 5700}   # 引擎基准（中超）
CSL_AP_RANGE = {       # 中超 AP 实测区间（对手维度上限 44.7 = 申花）
    "S": (40.0, 44.7),
    "A": (32.0, 40.0),
    "B": (25.0, 32.0),
    "C": (0.0, 25.0),
}

# ── 本土认知折扣 d（待标定，当前取 MD1 反推中值）──
D_LOCAL = 0.40


def tier_from_qnorm(q: float) -> tuple[str, str]:
    """把去情境 q_norm 插入中超实测标尺 → 返回 (级别标签, 说明)。

    级别切分用中超实测均值的相邻中点，两端各留 ±15% 缓冲。
    """
    s, a, b, c = CSL_SCALE["S"], CSL_SCALE["A"], CSL_SCALE["B"], CSL_SCALE["C"]
    if q >= (s + a) / 2:
        return "S", f"≥{(s + a) / 2:,.0f}"
    if q >= (a + b) / 2:
        return "A", f"{(a + b) / 2:,.0f}-{(s + a) / 2:,.0f}"
    if q >= (b + c) / 2:
        return "B", f"{(b + c) / 2:,.0f}-{(a + b) / 2:,.0f}"
    if q >= c * 0.85:
        return "C", f"{c * 0.85:,.0f}-{(b + c) / 2:,.0f}"
    return "C-", f"<{c * 0.85:,.0f}"


def fine_label(q: float) -> str:
    """以中超 C 级实测均值 (6,458) 为原点做细分：±8% 内=C，上=C+，下=C-。

    实证：亚冠四场全部落在 C 区间（C-/C/C+），无一达到中超 B 级（8,441）。
    """
    base, _ = tier_from_qnorm(q)
    if base == "C":
        r = q / CSL_SCALE["C"]
        if r >= 1.30:
            return "C++"
        if r >= 1.08:
            return "C+"
        if r >= 0.92:
            return "C"
        return "C-"
    if base == "B":
        b, a = CSL_SCALE["B"], CSL_SCALE["A"]
        frac = (q - b) / (a - b)
        return "B+" if frac >= 0.5 else "B-"
    return base


def local_ap(ap_asia: float, d: float = D_LOCAL) -> float:
    """亚洲视角 AP → 北京感知 AP（折算进中超 0-45 尺度）。"""
    return round(ap_asia * d, 1)


def load() -> dict:
    return json.loads(RATINGS.read_text(encoding="utf-8"))


def build_rows(cfg: dict) -> list[dict]:
    """对每场算去情境 q_norm + 等效中超级别 + 北京感知 AP。"""
    rows = []
    for mid, m in cfg["matches"].items():
        if m.get("ST") is None:
            continue
        ctx = m.get("ctx_mult") or 1.0
        win = 1.0
        anchor_w = cfg["matches"].get("2026-09-15_浦项铁人", {}).get("window_days")
        if m.get("window_days") and anchor_w:
            win = 1 + cfg["calibration"].get("window_slope", 0.05) * (m["window_days"] - anchor_w)

        actual = m.get("actual_tickets")
        engine = m.get("baseline_engine")
        if actual:                       # 已赛：用实测
            q = actual / ctx / win
            src = "实测"
        else:                            # 未赛：用同模型预测
            anchor = cfg["matches"]["2026-09-15_浦项铁人"]
            ap_a, st_a = anchor["AP"], anchor["ST"]
            anchor_ctx = anchor["ctx_mult"] or 1.0
            q_anchor = (anchor["actual_tickets"] or 0) / anchor_ctx
            g = cfg["calibration"]["gamma"]
            ratio = (m["AP"] / ap_a) * (m["ST"] / st_a)
            q = q_anchor * (ratio ** g) * win
            src = "模型"

        tier, _ = tier_from_qnorm(q)
        rows.append({
            "match_id": mid, "opponent": m.get("opponent"), "tier_asia": m.get("tier"),
            "ST": m.get("ST"), "AP": m.get("AP"),
            "AP_cn": local_ap(m["AP"]),
            "ctx": ctx, "window": win, "q_norm": round(q),
            "tier_cn": fine_label(q), "tier_cn_base": tier,
            "engine_csl": engine, "source": src,
            "pct_of_c": round(q / CSL_SCALE["C"] * 100),
            "pct_of_b": round(q / CSL_SCALE["B"] * 100),
        })
    rows.sort(key=lambda r: -r["q_norm"])
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    cfg = load()
    rows = build_rows(cfg)

    if args.json:
        print(json.dumps({"d_local": D_LOCAL, "csl_scale": CSL_SCALE, "rows": rows},
                         ensure_ascii=False, indent=2))
        return 0

    print("=" * 100)
    print("亚冠 ST/AP → 中超等效级别映射（本土认知折扣 d = %.2f）" % D_LOCAL)
    print("=" * 100)
    print(f"{'场次':<12}{'对手':<10}{'亚洲级':>6}{'ST/AP':>12}{'AP_cn':>7}{'去情境':>8}{'等效中超':>9}{'占C标尺':>9}")
    print("-" * 100)
    for r in rows:
        stap = f"{r['ST']}/{r['AP']}"
        print(f"{r['match_id'][:10]:<12}{r['opponent'][:8]:<10}{r['tier_asia']:>6}"
              f"{stap:>12}{r['AP_cn']:>7}"
              f"{r['q_norm']:>8,}{r['tier_cn']:>9}{str(r['pct_of_c']) + '%':>9}")

    print()
    print("中超 13 场实测标尺（q_norm）：" + " ｜ ".join(f"{k} {v:,}" for k, v in CSL_SCALE.items()))
    print("中超引擎基准：" + " ｜ ".join(f"{k} {v:,}" for k, v in CSL_ENGINE.items()))
    print()
    print("读法：'等效中超' = 把亚冠对手的去情境需求，插进中超真实票房标尺后得到的级别；")
    print("      它回答的是「北京观众愿意为这个对手掏多少钱」，不是「这个对手在亚洲有多强」。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
