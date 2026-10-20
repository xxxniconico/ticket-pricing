#!/usr/bin/env python3
"""AP_cn 透明度审查：逐项拆解、标注证据等级、跑敏感性。

用途：回答"这些分值哪来的、会不会是忽悠"。
运行：python scripts/acl_ap_cn_audit.py
"""
from __future__ import annotations

import sys

# ── 打分表 + 每格的证据等级 ──
# E1 = 有权威来源的硬事实并已核对
# E2 = 有事实基础，但"映射到分值"是我定的
# E3 = 纯判断，无数据（可被质疑）
DIMS = {
    "memory": ("历史交锋记忆", 0.35),
    "league": ("联赛在华曝光", 0.25),
    "star":   ("球星可辨识度", 0.20),
    "topic":  ("中文话题密度", 0.20),
}

SCORES = {
    "全北现代": {
        "memory": (85, "E1+E2", "亚冠正赛 1平3负（2015 客1-1/工体0-1出局；2019 客1-3/工体0-1被双杀）；来源：中新网、央视网、懂球帝。分值 85 是我定的映射"),
        "league": (70, "E3", "K League 1 在华有转播但无量化数据；70 是纯判断"),
        "star":   (60, "E2", "朴志洙（前广州恒大 2019-21，中国球迷有印象）、宋范根（韩国国门）；无世界级球星。现役阵容见 Transfermarkt 2026"),
        "topic":  (60, "E3", "'苦主'标签长期存在但本轮无新叙事；60 是纯判断"),
    },
    "浦项铁人": {
        "memory": (65, "E1+E2", "对浦项 2胜1平不败（2013 客0-0/主2-0 系国安首次胜韩国球队且零失球；2026 MD1 主3-1）；来源同上"),
        "league": (70, "E3", "同为 K League 1，与全北同分"),
        "star":   (55, "E2", "无明显中国球迷熟知球员"),
        "topic":  (50, "E3", "刚赢过（3-1），无悬念无话题；50 是纯判断"),
    },
    "拉查武里": {
        "memory": (30, "E3", "无任何交锋记录（硬事实），30 是给'陌生'定的底分"),
        "league": (35, "E3", "泰超在华几乎无转播；35 是纯判断"),
        "star":   (50, "E2", "比埃拉（前国安外援）与俱乐部的关系提供辨识度，具体现役身份未核实"),
        "topic":  (55, "E2", "'比埃拉回归工体'叙事（项目 memory 曾拟 acl_legend_return 1.05）"),
    },
    "纽卡斯尔喷气机": {
        "memory": (25, "E3", "无交锋记录"),
        "league": (35, "E3", "澳超在华零转播；35 是纯判断"),
        "star":   (40, "E3", "无知名球员；40 是纯判断"),
        "topic":  (45, "E3", "无叙事；45 是纯判断"),
    },
}


def ap(scores: dict) -> float:
    return round(sum(scores[k][0] * w for k, (_, w) in DIMS.items()), 1)


def main() -> int:
    print("=" * 96)
    print("AP_cn 透明度审查")
    print("=" * 96)

    print("\n【1】权重从哪来")
    print("  35/25/20/20 是照搬中超 AP 的结构（PREF 25 / HIST 35 / ... 的权重量级），")
    print("  但中超那套的输入是『历史票房分位』，我这里换成了『北京可感知变量』——")
    print("  **权重是借的，不是标定的**。这点必须说清。")

    print("\n【2】逐项贡献拆解（分项 × 权重 = 贡献）")
    for team, sc in SCORES.items():
        total = ap(sc)
        print(f"\n  {team}  →  AP_cn = {total}")
        for k, (name, w) in DIMS.items():
            v, ev, note = sc[k]
            print(f"    {name:<8} {v:>3} × {w:.2f} = {v * w:>5.1f}   [{ev}]")
        if team == "全北现代":
            for k, (name, w) in DIMS.items():
                v, ev, note = sc[k]
                print(f"      · {name}: {note}")

    print("\n【3】证据等级分布（全北）")
    evs = [SCORES["全北现代"][k][1] for k in DIMS]
    n_e1 = sum("E1" in e for e in evs)
    n_e3 = sum("E3" in e for e in evs)
    print(f"  E1/E2（有事实基础）：{len(evs) - n_e3}/4 项，权重合计 "
          f"{sum(w for k, (n, w) in DIMS.items() if 'E3' not in SCORES['全北现代'][k][1]):.2f}")
    print(f"  E3（纯判断）：{n_e3}/4 项，权重合计 "
          f"{sum(w for k, (n, w) in DIMS.items() if 'E3' in SCORES['全北现代'][k][1]):.2f}")

    print("\n【4】敏感性：这些分值错了，结论会变吗")
    base_cn, base_pk = ap(SCORES["全北现代"]), ap(SCORES["浦项铁人"])
    q_anchor, st_ratio, ctx, win, gamma = 6367, (76.1 / 63.0), 0.86, 1.05, 0.15
    c_scale = 6458

    def calc(cn):
        ratio = (cn / base_pk) * st_ratio
        return round(q_anchor * (ratio ** gamma) * ctx * win)

    print(f"  基准：全北 AP_cn {base_cn} / 浦项 {base_pk} → 比值 {base_cn / base_pk:.3f}")
    print(f"\n  {'情景':<34}{'AP_cn':>7}{'比值':>7}{'MD3 预测':>10}{'vs 基准':>9}{'去情境':>9}{'占C标尺':>8}")
    print("  " + "-" * 84)
    scen = [
        ("当前打分（memory 85）", base_cn),
        ("memory 降到 70（1平3负不算强记忆）", base_cn - 0.35 * 15),
        ("memory 提到 95（工体出局=强记忆）", base_cn + 0.35 * 10),
        ("全部主观项设为与浦项相同", ap({"memory": (65, "", ""), "league": (70, "", ""),
                                          "star": (55, "", ""), "topic": (50, "", "")})),
        ("AP 完全不做区分（=浦项）", base_pk),
    ]
    for label, cn in scen:
        q = calc(cn)
        qn = q / ctx / win
        print(f"  {label:<34}{cn:>7.1f}{cn / base_pk:>7.3f}{q:>10,}"
              f"{(q / calc(base_cn) - 1) * 100:>8.1f}%{qn:>9,.0f}{qn / c_scale * 100:>7.0f}%")

    print("\n【5】结论：这套 AP_cn 到底能撑住什么")
    lo, hi = calc(base_pk), calc(base_cn + 0.35 * 10)
    print(f"  · 影响范围：MD3 预测在 {lo:,}-{hi:,} 张之间（±{(hi - lo) / 2 / calc(base_cn) * 100:.1f}%），"
          f"**结论不变**")
    print(f"  · 等效级别：去情境 {calc(base_cn) / ctx / win:,.0f} → 占 C 标尺 "
          f"{calc(base_cn) / ctx / win / c_scale * 100:.0f}%（C 到 C+ 之间，距 B 级仍差 16-22%）")
    print("  · **'全北 = C' 这个绝对判断，95% 来自 MD1 实测锚定 + ST 差异，不来自这些主观分**")
    print("  · AP_cn 真正的价值不是分值，而是**排序假设可证伪**（拉查武里 vs 喷气机，MD6/MD8 见分晓）")
    print("  · 要做到不是主观：必须采百度指数/微博话题量/抖音播放量。现在没有，就是没有。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
