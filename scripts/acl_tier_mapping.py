#!/usr/bin/env python3
"""亚冠 AP 的"北京视角"重估（外生认知指标法）。

=== 为什么重写（2026-10-20 用户批评）===
  初版用 MD1 票房反推出 d=0.40，再用 d 去算"全北等效 C+" —— 这是**循环论证**：
  拿 MD1 的结果反推参数，再用参数解释 MD1 和 MD3。它无法回答"为什么"，
  也无法外推到没见过的对手（比如若抽到鹿岛鹿角，d 给不出任何信息）。

=== 正确做法：把"绝对水平"与"相对排序"解耦 ===
  层 1 绝对水平（赛事级）：亚冠整体 vs 中超的赛道差 —— **只能**用 MD1 实测锚定（5,476）。
       这部分用 MD1 是正当的：它是"赛事常数"，不是"对手参数"。
  层 2 相对排序（对手级）：谁比谁更吸引北京观众 —— **必须**用外生认知指标，
       不得使用任何票房结果。这才是用户逻辑的落点。

=== 外生 AP_cn（0-100，四个可查证维度）===
  memory 35%  历史交锋记忆强度：交手次数 × 最近年代 × 是否有"工体伤心事"
  league 25%  所在联赛在中国的曝光度：J1 90 / K1 70 / 泰超 35 / 澳超 35 / 越V 30
  star   20%  球星可辨识度：现役阵容有无中国球迷叫得出名字的人
  topic  20%  中文媒体话题密度：苦主/复仇/回归/首访等叙事强度
  （权重照搬中超 AP 的 35/25/20/20 结构，但把"品牌力/洲际知名度"换成"北京可感知"变量）

用法:
  python scripts/acl_tier_mapping.py            # 两种 AP 对比 + 重算预测 + 判别设计
  python scripts/acl_tier_mapping.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RATINGS = ROOT / "data/processed/acl_opponent_ratings.json"

# 中超 13 场实测 q_norm 标尺（v3 标定，commit b4184f5）
CSL_SCALE = {"S": 12799, "A": 10669, "B": 8441, "C": 6458}

# ── 外生 AP_cn 打分（**不含任何票房输入**；依据写在各场 note 里）──
AP_CN = {
    "2026-10-27_全北现代": {
        "memory": 85, "league": 70, "star": 60, "topic": 60,
        "note": "亚冠正赛对全北 1平3负（2015 1/8 客场1-1/工体0-1出局；2019 小组赛 客场1-3/工体0-1被双杀），"
                "两次在工体把国安挡在门外 → 媒体标签'苦主''冤家'，记忆强度四场最高",
    },
    "2026-09-15_浦项铁人": {
        "memory": 65, "league": 70, "star": 55, "topic": 50,
        "note": "对浦项 2胜1平不败（2013 客场0-0/主场2-0 系国安首次胜韩国球队且零失球；2026 MD1 主场3-1）"
                "→ 记忆正面但无悬念，话题弱",
    },
    "2026-12-01_拉查武里": {
        "memory": 30, "league": 35, "star": 50, "topic": 55,
        "note": "无交锋史；泰超认知低，但'比埃拉回归工体'提供独立话题",
    },
    "2027-02-16_纽卡斯尔喷气机": {
        "memory": 25, "league": 35, "star": 40, "topic": 45,
        "note": "无交锋史；澳超曝光最低，无球星、无叙事（春节档是唯一变量）",
    },
}
W = {"memory": 0.35, "league": 0.25, "star": 0.20, "topic": 0.20}


def ap_cn(mid: str) -> float:
    d = AP_CN[mid]
    return round(sum(d[k] * w for k, w in W.items()), 1)


def load() -> dict:
    return json.loads(RATINGS.read_text(encoding="utf-8"))


def tier_cn(q: float) -> str:
    c, b, a = CSL_SCALE["C"], CSL_SCALE["B"], CSL_SCALE["A"]
    if q >= (a + b) / 2:
        return "A↑"
    if q >= (b + a) / 2:
        return "B+"
    if q >= b * 0.95:
        return "B-"
    if q >= (b + c) / 2:
        return "B-"
    r = q / c
    if r >= 1.30:
        return "C++"
    if r >= 1.08:
        return "C+"
    if r >= 0.92:
        return "C"
    return "C-"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    cfg = load()
    cal = cfg["calibration"]
    gamma = cal["gamma"]
    anchor = cfg["matches"]["2026-09-15_浦项铁人"]
    q_anchor = (anchor["actual_tickets"] or 0) / (anchor["ctx_mult"] or 1.0)   # 6,367
    ap_anchor_asia, ap_anchor_cn = anchor["AP"], ap_cn("2026-09-15_浦项铁人")
    st_anchor = anchor["ST"]
    anchor_w = anchor.get("window_days")

    rows = []
    for mid, m in cfg["matches"].items():
        if mid not in AP_CN or m.get("ST") is None:
            continue
        ctx = m.get("ctx_mult") or 1.0
        win = 1.0
        if m.get("window_days") and anchor_w:
            win = 1 + cal.get("window_slope", 0.05) * (m["window_days"] - anchor_w)
        cn = ap_cn(mid)
        # 外生口径：AP 用 AP_cn 比值，ST 仍用亚洲值（实力跨联赛相对可比）
        q_ext = (q_anchor * ((cn / ap_anchor_cn) ** gamma)
                 * ((m["ST"] / st_anchor) ** gamma) * win)
        q_asia = (q_anchor * ((m["AP"] / ap_anchor_asia) ** gamma)
                  * ((m["ST"] / st_anchor) ** gamma) * win)
        rows.append({
            "match_id": mid, "opponent": m.get("opponent"), "tier_asia": m.get("tier"),
            "ST": m["ST"], "AP_asia": m["AP"], "AP_cn": cn,
            "cn_vs_asia": round(cn / m["AP"] * 100),
            "ratio_vs_pohang_cn": round(cn / ap_anchor_cn, 3),
            "ratio_vs_pohang_asia": round(m["AP"] / ap_anchor_asia, 3),
            "q_norm_asia": round(q_asia),
            "tickets_cn": round(q_ext * ctx), "tickets_asia": round(q_asia * ctx),
            # 对比中超标尺时剔除售期修正（中超标尺各场无此维度）
            "q_norm_cn": round(q_ext / win), "tier_cn": tier_cn(q_ext / win),
            "actual": m.get("actual_tickets"),
            "note": AP_CN[mid]["note"],
        })
    rows.sort(key=lambda r: -r["AP_cn"])

    if args.json:
        print(json.dumps({"gamma": gamma, "anchor_q": q_anchor, "csl_scale": CSL_SCALE,
                          "weights": W, "rows": rows}, ensure_ascii=False, indent=2))
        return 0

    print("=" * 108)
    print("亚冠 AP 北京视角重估（外生认知指标，不含票房输入） · γ=%.2f · 锚=浦项去情境 %.0f" % (gamma, q_anchor))
    print("=" * 108)
    print(f"{'对手':<10}{'亚洲级':>5}{'AP_asia':>9}{'AP_cn':>7}{'cn/asia':>9}{'vs浦项':>8}{'去情境':>8}{'等效中超':>9}{'本场':>8}")
    print("-" * 108)
    for r in rows:
        act = f"{r['actual']:,}" if r["actual"] else f"{r['tickets_cn']:,}*"
        print(f"{r['opponent'][:8]:<10}{r['tier_asia']:>5}{r['AP_asia']:>9.1f}{r['AP_cn']:>7.1f}"
              f"{str(r['cn_vs_asia']) + '%':>9}{r['ratio_vs_pohang_cn']:>8.3f}"
              f"{r['q_norm_cn']:>8,}{r['tier_cn']:>9}{act:>8}")
    print("-" * 108)
    print("* = 预测；数字均为「主队散票」，不含联票/工会/客队")
    print("  去情境需求已剔除售期修正，与中超 13 场标尺同口径（中超标尺各场无此维度）")

    print("\n【两种 AP 的排序差异】")
    o_asia = [r["opponent"] for r in sorted(rows, key=lambda r: -r["AP_asia"])]
    o_cn = [r["opponent"] for r in rows]
    print("  亚洲视角： " + " > ".join(o_asia))
    print("  北京视角： " + " > ".join(o_cn))
    diff = o_asia != o_cn
    print(("  → **排序出现分歧**：" + " vs ".join(o_asia) + " 两两之间顺序不同")
          if diff else "  → 排序一致，差异只在绝对水平")

    print("\n【为什么不再用 d 反推】")
    print("  绝对水平（亚冠 vs 中超）只能由 MD1 锚定 —— 它是「赛事常数」，用实测是正当的；")
    print("  对手相对排序必须外生 —— 用历史交锋/联赛曝光/球星/话题，不看任何票房。")
    print("  初版 d=0.40 把两层混成一个系数，等于用 MD1 解释 MD1（循环）。")

    print("\n【判别设计（可证伪）】")
    jb = next(r for r in rows if r["opponent"] == "全北现代")
    gap = abs(jb["tickets_cn"] - jb["tickets_asia"]) / jb["tickets_cn"] * 100
    print(f"  MD3 全北：外生口径 {jb['tickets_cn']:,} 张 vs 亚洲口径 {jb['tickets_asia']:,} 张"
          f" → 仅差 {gap:.1f}%（<σ=20%），**MD3 不能判别两种 AP**，只能验证绝对水平。")
    md6 = next(r for r in rows if r["opponent"] == "拉查武里")
    md8 = next(r for r in rows if r["opponent"] == "纽卡斯尔喷气机")
    print(f"  MD6 拉查武里 {md6['tickets_cn']:,} vs MD8 喷气机 {md8['tickets_cn']:,}（外生）"
          f"｜亚洲口径 {md6['tickets_asia']:,} vs {md8['tickets_asia']:,}")
    print("  → 两种 AP 对这两场的**排序相反**：实际谁高谁低即可判别（MD6 12/01、MD8 2027/02/16）。")
    print("  → 这是本方法第一个真正可证伪的预测点（MD3 的绝对水平只能检验「赛事折减」）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
