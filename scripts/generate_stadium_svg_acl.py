"""生成工人体育场 B 类赛事看台 — 纯矢量 SVG（path + text，无内嵌位图）。"""
from __future__ import annotations

import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "stadium_seating_acl.svg"

C = {
    780: "#b9bc9f",
    540: "#f66d81",
    460: "#f1f530",
    300: "#f9a61a",
    200: "#27d08a",
}
AWAY = {"126", "234", "235", "334", "335"}
SEG = {"125", "127", "233", "236", "333", "336"}
FAN = {"107", "108", "109", "110"}  # 死忠球迷区（一层西侧）：走球迷通道售卖，不进入正常售卖流程
WHITE = {"205", "206", "207", "239", "240", "301", "302", "303", "304", "305", "306", "339", "340"}

SECTION_PRICE: dict[str, int] = {}
# 最新档位映射（2026-08 中超最近场次销售实证：山东7/4 T4扩容实验+浙江8/1+深圳8/7）
for s in ("101", "102"):
    SECTION_PRICE[s] = 780
for s in ("103", "114", "115", "116", "117", "130"):
    SECTION_PRICE[s] = 540
for s in (
    "104", "113", "118", "129", "218", "219", "220", "221", "222", "223", "224", "225",
    "319", "320", "321", "322", "323", "324",
):
    SECTION_PRICE[s] = 460
for s in (
    "105", "106", "111", "112", "119", "120", "121", "122", "123", "124", "128",
    "208", "209", "210", "211", "212", "213", "214", "215", "216", "217",
    "226", "227", "228", "229", "230", "231", "232", "237", "317", "318",
    "325", "326", "337", "338",
):
    SECTION_PRICE[s] = 300
for s in ("307", "308", "309", "314", "315", "316", "327", "328", "329"):
    SECTION_PRICE[s] = 200
for s in ("310", "311", "312", "313", "330", "331", "332"):
    SECTION_PRICE[s] = 200

RING_100 = [
    "106", "105", "104", "103", "102", "101", "130", "129", "128",
    "121", "122", "123", "124", "125", "126", "127",
    "120", "119",
    "118", "117", "116", "115", "114", "113",
    "112", "111", "110", "109", "108", "107",
]
RING_200 = [
    "209", "208", "207", "206", "205", "__VIP__", "240", "239", "238", "237",
    "230", "231", "232", "233", "234", "235", "236",
    "229", "228", "227", "226", "225", "224", "223", "222", "221", "220", "219", "218",
    "217", "216", "215", "214", "213", "212", "211",
]
# 外环无 VIP 缺口；南侧顺序 …303,302,301|340,339…（301 右侧接 340、339）
RING_300 = [
    "307", "306", "305", "304", "303", "302", "301",
    "340", "339", "338", "337",
    "336", "335", "334", "333", "332", "331", "330", "329", "328", "327",
    "326", "325", "324", "323", "322", "321", "320", "319", "318", "317",
    "316", "315", "314", "313", "312", "311", "310", "309", "308",
]
RING_300_SOUTH_N = 7  # 切分在 301 与 340 之间，南侧居中

W, H = 1024, 686
CX, CY = 500, 338
SOUTH = 90.0
NORTH = 270.0

STADIUM_RX = 352.0
STADIUM_RY = 218.0
PITCH_FW, PITCH_FH = 272.0, 96.0  # 中心球场（原 218×76，约占内环空区 ~85%）
VIP_SPAN_200 = 26.0
RING_100_SOUTH_N = 9
RING_300_WEIGHT = 1.28  # 外环各区略宽

RING_GEOM: dict[str, tuple[float, float, float, float]] = {
    "100": (STADIUM_RX * 0.48, STADIUM_RY * 0.48, STADIUM_RX * 0.62, STADIUM_RY * 0.62),
    "200": (STADIUM_RX * 0.62, STADIUM_RY * 0.62, STADIUM_RX * 0.78, STADIUM_RY * 0.78),
    "300": (STADIUM_RX * 0.78, STADIUM_RY * 0.78, STADIUM_RX * 1.00, STADIUM_RY * 1.00),
}
VIP_GEOM = {
    "200": (STADIUM_RX * 0.62, STADIUM_RY * 0.62, STADIUM_RX * 0.78, STADIUM_RY * 0.78, VIP_SPAN_200),
}

WEIGHTS: dict[str, float] = {
    "__VIP__": 1.0,
    "101": 1.15,
    "102": 1.15,
    "205": 0.9,
    "240": 0.9,
    "301": 1.35,
    "302": 1.32,
    "340": 1.30,
    "339": 1.28,
}
ALIGN_SOUTH = frozenset({"101", "102"})
ALIGN_NORTH = frozenset({"113", "114", "115", "116", "117", "118"})


def _angular_err(a: float, target: float) -> float:
    return abs((a - target + 180) % 360 - 180)


def fill_for(sid: str) -> str:
    if sid in AWAY:
        return "url(#awayPattern)"
    if sid in SEG:
        return "#b7b7b7"
    if sid in FAN:
        return "#c39bd3"
    if sid in WHITE:
        return "#ffffff"
    p = SECTION_PRICE.get(sid)
    return C[p] if p else "#ffffff"


def _pt(cx: float, cy: float, rx: float, ry: float, deg: float) -> tuple[float, float]:
    r = math.radians(deg)
    return cx + rx * math.cos(r), cy + ry * math.sin(r)


def annulus_path(cx: float, cy: float, rx0: float, ry0: float, rx1: float, ry1: float, d0: float, d1: float) -> str:
    if d0 <= d1:
        return ""
    x0o, y0o = _pt(cx, cy, rx1, ry1, d0)
    x1o, y1o = _pt(cx, cy, rx1, ry1, d1)
    x0i, y0i = _pt(cx, cy, rx0, ry0, d0)
    x1i, y1i = _pt(cx, cy, rx0, ry0, d1)
    large = 1 if (d0 - d1) > 180 else 0
    return (
        f"M{x0i:.2f},{y0i:.2f}L{x0o:.2f},{y0o:.2f}"
        f"A{rx1:.2f},{ry1:.2f},0,{large},0,{x1o:.2f},{y1o:.2f}"
        f"L{x1i:.2f},{y1i:.2f}A{rx0:.2f},{ry0:.2f},0,{large},1,{x0i:.2f},{y0i:.2f}Z"
    )


def _arc_spans(items: list[str], total_arc: float, weight_scale: float = 1.0) -> list[tuple[str, float]]:
    ws = [WEIGHTS.get(s, 1.0) * weight_scale for s in items]
    tw = sum(ws) or 1.0
    return [(s, total_arc * w / tw) for s, w in zip(items, ws)]


def _emit_arc(
    out: list[tuple[str, float, float]],
    items: list[str],
    deg_start: float,
    arc_total: float,
    weight_scale: float = 1.0,
) -> float:
    deg = deg_start
    for s, span in _arc_spans(items, arc_total, weight_scale):
        out.append((s, deg, deg - span))
        deg -= span
    return deg


def ring_angles(
    ring: list[str],
    vip_span: float = 0.0,
    south_count: int = 0,
    rotation: float = 0.0,
    weight_scale: float = 1.0,
) -> list[tuple[str, float, float]]:
    out: list[tuple[str, float, float]] = []
    usable = 360.0 - vip_span

    if "__VIP__" in ring:
        idx = ring.index("__VIP__")
        before, after = ring[:idx], ring[idx + 1 :]
        wb = sum(WEIGHTS.get(s, 1.0) * weight_scale for s in before)
        wa = sum(WEIGHTS.get(s, 1.0) * weight_scale for s in after)
        arc_b = usable * wb / (wb + wa) if (wb + wa) else 0.0
        arc_a = usable - arc_b
        _emit_arc(out, before, SOUTH + vip_span / 2 + arc_b + rotation, arc_b, weight_scale)
        _emit_arc(out, after, SOUTH - vip_span / 2 + rotation, arc_a, weight_scale)
        return out

    if south_count > 0:
        before, after = ring[:south_count], ring[south_count:]
        wb = sum(WEIGHTS.get(s, 1.0) * weight_scale for s in before)
        wa = sum(WEIGHTS.get(s, 1.0) * weight_scale for s in after)
        arc_b = usable * wb / (wb + wa) if (wb + wa) else 0.0
        arc_a = usable - arc_b
        _emit_arc(out, before, SOUTH + arc_b / 2 + rotation, arc_b, weight_scale)
        _emit_arc(out, after, SOUTH - arc_b / 2 + rotation, arc_a, weight_scale)
        return out

    sections = [s for s in ring if s != "__VIP__"]
    _emit_arc(out, sections, SOUTH + usable / 2 + rotation, usable, weight_scale)
    return out


def _section_mid_angle(sid: str, rotation: float) -> float:
    for s, d0, d1 in ring_angles(RING_100, 0.0, RING_100_SOUTH_N, rotation):
        if s == sid:
            return (d0 + d1) / 2
    raise KeyError(sid)


def _tune_ring100_rotation() -> float:
    best_rot, best_err = 0.0, 1e9
    for rot_i in range(-40, 41):
        rot = float(rot_i) * 0.5
        err = sum(_angular_err(_section_mid_angle(s, rot), SOUTH) ** 2 for s in ALIGN_SOUTH)
        err += sum(_angular_err(_section_mid_angle(s, rot), NORTH) ** 2 for s in ALIGN_NORTH)
        if err < best_err:
            best_err, best_rot = err, rot
    return best_rot


RING_100_ROTATION = _tune_ring100_rotation()
ALIGN_300_SOUTH = frozenset({"301", "302", "340"})


def _section_mid_angle_300(sid: str, rotation: float) -> float:
    for s, d0, d1 in ring_angles(RING_300, 0.0, RING_300_SOUTH_N, rotation, RING_300_WEIGHT):
        if s == sid:
            return (d0 + d1) / 2
    raise KeyError(sid)


def _tune_ring300_rotation(base: float) -> float:
    """外环额外右旋，使 301/302 到主席台正南，301 右侧接 340。"""
    best_rot, best_err = base, 1e9
    for delta in range(-70, 71):
        rot = base + float(delta) * 0.5
        err = 0.0
        err += _angular_err(_section_mid_angle_300("301", rot), SOUTH) ** 2 * 3.0
        err += _angular_err(_section_mid_angle_300("302", rot), SOUTH - 14.0) ** 2
        err += _angular_err(_section_mid_angle_300("340", rot), SOUTH + 14.0) ** 2
        mid301 = _section_mid_angle_300("301", rot)
        mid302 = _section_mid_angle_300("302", rot)
        if mid301 >= mid302:
            err += 80.0
        if err < best_err:
            best_err, best_rot = err, rot
    return best_rot


RING_300_ROTATION = _tune_ring300_rotation(RING_100_ROTATION)


def _ring200_junction_angles(section_rot: float, vip_rot: float) -> tuple[float, float, float, float]:
    """205 东侧、VIP 西/东侧、240 西侧（度）。"""
    segs = {s: (d0, d1) for s, d0, d1 in ring_angles(RING_200, VIP_SPAN_200, 0, section_rot)}
    vip_w = SOUTH + VIP_SPAN_200 / 2 + vip_rot
    vip_e = SOUTH - VIP_SPAN_200 / 2 + vip_rot
    return segs["205"][1], vip_w, vip_e, segs["240"][0]


def _tune_ring200_vip() -> tuple[float, float]:
    """205 略向右、主席台略向左，闭合南侧缺口。"""
    base = RING_100_ROTATION
    best_sr, best_vr, best_err = base, base, 1e9
    for sd in range(-12, 13):
        for vd in range(-12, 13):
            sr = base + float(sd) * 0.5
            vr = base + float(vd) * 0.5
            e205, v0, v1, e240 = _ring200_junction_angles(sr, vr)
            err = max(0.0, v0 - e205) ** 2 * 4.0 + max(0.0, e240 - v1) ** 2 * 4.0
            err += max(0.0, e205 - v0) ** 2 * 0.25 + max(0.0, v1 - e240) ** 2 * 0.25
            if sd > 0:
                err += 6.0
            if vd < 0:
                err += 6.0
            if err < best_err:
                best_err, best_sr, best_vr = err, sr, vr
    return best_sr, best_vr


RING_200_EXTRA_ROTATION = -5.0  # 中环整体逆时针 5°（主席台对齐 101/102 正南后方）
RING_200_ROTATION, VIP_200_ROTATION = _tune_ring200_vip()
RING_200_ROTATION += RING_200_EXTRA_ROTATION
VIP_200_ROTATION += RING_200_EXTRA_ROTATION


def render_ring(
    ring: list[str],
    geom_key: str,
    vip_span: float = 0.0,
    south_count: int = 0,
    rotation: float = 0.0,
    weight_scale: float = 1.0,
) -> list[str]:
    rx0, ry0, rx1, ry1 = RING_GEOM[geom_key]
    lrx, lry = (rx0 + rx1) / 2, (ry0 + ry1) / 2
    lines: list[str] = []
    for sid, d0, d1 in ring_angles(ring, vip_span, south_count, rotation, weight_scale):
        if sid == "__VIP__":
            continue
        d = annulus_path(CX, CY, rx0, ry0, rx1, ry1, d0, d1)
        if not d:
            continue
        fill = fill_for(sid)
        lines.append(f'<path id="sec-{sid}" d="{d}" fill="{fill}" stroke="#1a1a1a" stroke-width="0.55"/>')
        mx, my = _pt(CX, CY, lrx, lry, (d0 + d1) / 2)
        fs = 6.5 if rx1 < 200 else 7.5 if rx1 < 280 else 8.5
        lines.append(
            f'<text x="{mx:.1f}" y="{my:.1f}" text-anchor="middle" dominant-baseline="middle" '
            f'font-size="{fs}" font-family="Arial,Helvetica,sans-serif" fill="#111">{sid}</text>'
        )
    return lines


def vip_paths() -> list[str]:
    lines: list[str] = []
    for tag, (rx0, ry0, rx1, ry1, span) in VIP_GEOM.items():
        rot = VIP_200_ROTATION if tag == "200" else 0.0
        d0, d1 = SOUTH + span / 2 + rot, SOUTH - span / 2 + rot
        d = annulus_path(CX, CY, rx0, ry0, rx1, ry1, d0, d1)
        lines.append(f'<path id="sec-vip-{tag}" d="{d}" fill="#fff" stroke="#1a1a1a" stroke-width="0.7"/>')
        if tag == "200":
            mx, my = _pt(CX, CY, (rx0 + rx1) / 2, (ry0 + ry1) / 2, SOUTH + rot)
            lines.append(
                f'<text x="{mx:.1f}" y="{my:.1f}" text-anchor="middle" dominant-baseline="middle" '
                f'font-size="11" font-weight="600" font-family="SimHei,Arial,sans-serif" fill="#333">主席台</text>'
            )
    return lines


def pitch_defs(fw: float, fh: float) -> list[str]:
    return [
        '    <linearGradient id="pitchGrad" x1="0%" y1="0%" x2="100%" y2="100%">',
        '      <stop offset="0%" stop-color="#5aad6a"/>',
        '      <stop offset="45%" stop-color="#3f8f52"/>',
        '      <stop offset="100%" stop-color="#2d7340"/>',
        "    </linearGradient>",
        f'    <pattern id="grassStripe" width="12" height="{fh:.0f}" patternUnits="userSpaceOnUse">',
        '      <rect width="6" height="100%" fill="#ffffff" opacity="0.12"/>',
        '      <rect x="6" width="6" height="100%" fill="#000000" opacity="0"/>',
        "    </pattern>",
        '    <filter id="pitchShadow" x="-10%" y="-15%" width="120%" height="130%">',
        '      <feDropShadow dx="0" dy="2" stdDeviation="2.5" flood-color="#1a3d24" flood-opacity="0.28"/>',
        "    </filter>",
    ]


def pitch_group(cx: float, cy: float, fw: float, fh: float) -> list[str]:
    x, y = cx - fw / 2, cy - fh / 2
    ml = 5.0
    inner_w, inner_h = fw - 2 * ml, fh - 2 * ml
    line = "rgba(255,255,255,0.78)"
    thin = 0.72
    lines = [
        '  <g id="pitch" filter="url(#pitchShadow)">',
        f'    <rect x="{x:.1f}" y="{y:.1f}" width="{fw}" height="{fh}" rx="4" fill="url(#pitchGrad)"/>',
        f'    <rect x="{x:.1f}" y="{y:.1f}" width="{fw}" height="{fh}" rx="4" fill="url(#grassStripe)"/>',
        f'    <rect x="{x + ml:.1f}" y="{y + ml:.1f}" width="{inner_w:.1f}" height="{inner_h:.1f}" '
        f'fill="none" stroke="{line}" stroke-width="{thin}"/>',
        f'    <line x1="{cx:.1f}" y1="{y + ml:.1f}" x2="{cx:.1f}" y2="{y + fh - ml:.1f}" '
        f'stroke="{line}" stroke-width="{thin * 0.95}"/>',
    ]
    r_circle = min(fw, fh) * 0.14
    lines.append(
        f'    <circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r_circle:.1f}" fill="none" '
        f'stroke="{line}" stroke-width="{thin * 0.95}"/>'
    )
    lines.append(f'    <circle cx="{cx:.1f}" cy="{cy:.1f}" r="1.3" fill="{line}"/>')
    pb_depth = fw * 0.155
    pb_span = fh * 0.58
    ga_depth = fw * 0.052
    ga_span = fh * 0.30
    for goal_x in (x + ml, x + fw - ml - pb_depth):
        py = cy - pb_span / 2
        lines.append(
            f'    <rect x="{goal_x:.1f}" y="{py:.1f}" width="{pb_depth:.1f}" height="{pb_span:.1f}" '
            f'fill="none" stroke="{line}" stroke-width="{thin * 0.9}" opacity="0.88"/>'
        )
        gx = goal_x if goal_x < cx else goal_x + pb_depth - ga_depth
        gy = cy - ga_span / 2
        lines.append(
            f'    <rect x="{gx:.1f}" y="{gy:.1f}" width="{ga_depth:.1f}" height="{ga_span:.1f}" '
            f'fill="none" stroke="{line}" stroke-width="{thin * 0.85}" opacity="0.82"/>'
        )
    lines.append(
        f'    <rect x="{x:.1f}" y="{y:.1f}" width="{fw}" height="{fh}" rx="4" '
        f'fill="none" stroke="#1a4d2c" stroke-width="1.15"/>'
    )
    lines.append("  </g>")
    return lines


def build_svg() -> str:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!-- 纯矢量：path + text，无内嵌 PNG/JPEG；由 scripts/generate_stadium_svg_acl.py 生成（亚冠9月 L1合并版） -->",
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">',
        "  <defs>",
        '    <pattern id="awayPattern" width="5" height="5" patternUnits="userSpaceOnUse">',
        '      <rect width="5" height="5" fill="#fff"/>',
        '      <circle cx="2.5" cy="2.5" r="1" fill="#888"/>',
        "    </pattern>",
        *pitch_defs(PITCH_FW, PITCH_FH),
        "  </defs>",
        *pitch_group(CX, CY, PITCH_FW, PITCH_FH),
        *render_ring(RING_300, "300", 0, RING_300_SOUTH_N, RING_300_ROTATION, RING_300_WEIGHT),
        *render_ring(RING_200, "200", VIP_SPAN_200, 0, RING_200_ROTATION),
        *render_ring(RING_100, "100", 0, RING_100_SOUTH_N, RING_100_ROTATION),
        *vip_paths(),
        '<g id="legend">',
        '<rect x="778" y="546" width="224" height="140" rx="6" fill="#ffffff" fill-opacity="0.93" stroke="#888" stroke-width="1"/>',
        '<text x="790" y="566" font-size="12" font-weight="600" font-family="SimHei,Arial,sans-serif" fill="#222">亚冠 9月 主场票价</text>',
        '<rect x="790" y="574" width="14" height="10" fill="#27d08a"/>',
        '<text x="812" y="583" font-size="10" font-family="Arial,sans-serif" fill="#333">L1（T1+T2 合并 36区） ¥200</text>',
        '<rect x="790" y="592" width="14" height="10" fill="#f9a61a"/>',
        '<text x="812" y="601" font-size="10" font-family="Arial,sans-serif" fill="#333">T3 ¥300</text>',
        '<rect x="790" y="610" width="14" height="10" fill="#f1f530"/>',
        '<text x="812" y="619" font-size="10" font-family="Arial,sans-serif" fill="#333">T4 ¥460</text>',
        '<rect x="790" y="628" width="14" height="10" fill="#f66d81"/>',
        '<text x="812" y="637" font-size="10" font-family="Arial,sans-serif" fill="#333">T5 ¥540</text>',
        '<rect x="790" y="646" width="14" height="10" fill="#b9bc9f"/>',
        '<text x="812" y="655" font-size="10" font-family="Arial,sans-serif" fill="#333">T6 ¥1080（含商务餐饮）</text>',
        '<rect x="790" y="662" width="14" height="10" fill="#c39bd3"/>',
        '<text x="812" y="671" font-size="10" font-family="Arial,sans-serif" fill="#333">球迷区 107-110（T3折扣¥200）</text>',
        '</g>',
        "</svg>",
    ]
    return "\n".join(parts) + "\n"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    svg = build_svg()
    OUT.write_text(svg, encoding="utf-8")
    n_path = svg.count("<path ")
    print(
        f"OK {OUT}  pure vector, {n_path} paths, "
        f"ring100_rot={RING_100_ROTATION:.1f} ring200_rot={RING_200_ROTATION:.1f} "
        f"vip200_rot={VIP_200_ROTATION:.1f} ring300_rot={RING_300_ROTATION:.1f}"
    )


if __name__ == "__main__":
    main()
