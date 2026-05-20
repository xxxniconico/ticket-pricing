#!/usr/bin/env python3
"""Replace render_seating_chart in dashboard/app.py (seating-chart.md)."""
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "dashboard" / "app.py"
text = APP.read_text(encoding="utf-8")
start = text.index("def render_seating_chart(tier, pred, r):")
end = text.index("\ndef render_home_card(match):", start)

NEW_FUNC = r'''def render_seating_chart(tier, pred, r):
    """工体鸟瞰 SVG — 对齐官方票价分区图配色，叠加六档销量/建议价。"""
    tcolors = {
        "T1": "#5cd68a",
        "T2": "#7eb3e8",
        "T3": "#f29c38",
        "T4": "#f5d547",
        "T5": "#e995b8",
        "T6": "#c5d86a",
    }
    tlabels = {
        "T1": "四层低价·260",
        "T2": "四层中价·340",
        "T3": "混合区·440",
        "T4": "四层中间·580",
        "T5": "一层边+二层·780",
        "T6": "死忠/VIP·1380",
    }
    zones = ["T1", "T2", "T3", "T4", "T5", "T6"]
    vshare = {"T1": 0.337, "T2": 0.217, "T3": 0.308, "T4": 0.027, "T5": 0.104, "T6": 0.008}

    tpred = {}
    for zt in zones:
        if zt in r.tiers:
            tpred[zt] = int(pred * vshare.get(zt, 0.1))

    def _rect(x, y, w, h, zt, op=0.92, rx=3):
        c = tcolors[zt]
        return (
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
            f'fill="{c}" fill-opacity="{op}" stroke="#0c0d0f" stroke-width="0.6"/>'
        )

    def _away(x, y, w, h):
        return (
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="3" fill="#3a3f48" '
            f'fill-opacity="0.75" stroke="#5a6270" stroke-width="0.6" stroke-dasharray="3 2"/>'
            f'<text x="{x + w/2}" y="{y + h/2 + 3}" text-anchor="middle" fill="#9aa3b2" '
            f'font-size="7">客队</text>'
        )

    def _tag(cx, cy, zt, small=False):
        vol = tpred.get(zt, 0)
        tr = r.tiers.get(zt)
        if not tr:
            return ""
        lock = "🔒" if tr.is_frozen else ""
        fs, dy = (7, 10) if small else (8, 11)
        return (
            f'<text x="{cx}" y="{cy}" text-anchor="middle" fill="#0c0d0f" '
            f'font-size="{fs}" font-weight="700">{zt}{lock}</text>'
            f'<text x="{cx}" y="{cy + dy}" text-anchor="middle" fill="#14171c" '
            f'font-size="{fs - 1}">{vol:,}张</text>'
            f'<text x="{cx}" y="{cy + dy * 2}" text-anchor="middle" fill="#14171c" '
            f'font-size="{fs - 1}">¥{tr.optimal_price:,.0f}</text>'
        )

    parts = [
        '<svg viewBox="0 0 720 500" xmlns="http://www.w3.org/2000/svg" '
        'style="width:100%;max-width:720px;background:#0c0d0f;border-radius:10px">',
        '<ellipse cx="360" cy="248" rx="332" ry="218" fill="none" stroke="#1e2229" stroke-width="2"/>',
        '<rect x="250" y="183" width="220" height="130" rx="6" fill="#1b4d2a" stroke="#2d6b3d" stroke-width="1"/>',
        '<line x1="360" y1="183" x2="360" y2="313" stroke="#2d6b3d" stroke-width="0.8" opacity="0.7"/>',
        '<circle cx="360" cy="248" r="22" fill="none" stroke="#2d6b3d" stroke-width="0.8" opacity="0.7"/>',
        '<rect x="248" y="221" width="10" height="54" fill="none" stroke="#2d6b3d" stroke-width="0.6"/>',
        '<rect x="462" y="221" width="10" height="54" fill="none" stroke="#2d6b3d" stroke-width="0.6"/>',
        '<text x="360" y="252" text-anchor="middle" fill="#6fcf97" font-size="11" opacity="0.35">FIELD</text>',
        '<g id="north">',
        _rect(118, 34, 52, 22, "T1"),
        _rect(174, 34, 52, 22, "T2"),
        _rect(230, 28, 260, 28, "T4"),
        _rect(494, 34, 52, 22, "T2"),
        _rect(550, 34, 52, 22, "T1"),
        _rect(118, 60, 484, 24, "T3"),
        _rect(148, 88, 424, 20, "T3"),
        _tag(144, 45, "T1", True),
        _tag(200, 45, "T2", True),
        _tag(360, 42, "T4"),
        _tag(520, 45, "T2", True),
        _tag(576, 45, "T1", True),
        _tag(360, 72, "T3", True),
        "</g>",
        '<g id="south">',
        _rect(118, 444, 52, 22, "T1"),
        _rect(174, 444, 52, 22, "T2"),
        _rect(230, 438, 118, 30, "T6"),
        _rect(352, 438, 76, 30, "T5"),
        _rect(432, 438, 58, 30, "T5"),
        _rect(494, 444, 52, 22, "T2"),
        _rect(550, 444, 52, 22, "T1"),
        _rect(118, 418, 484, 22, "T3"),
        _rect(148, 392, 424, 22, "T3"),
        _tag(289, 453, "T6"),
        _tag(390, 453, "T5", True),
        _tag(461, 453, "T5", True),
        _tag(360, 429, "T3", True),
        '<text x="360" y="478" text-anchor="middle" fill="#6b7280" font-size="8">主席台 · 南</text>',
        "</g>",
        '<g id="west">',
        _rect(34, 118, 28, 48, "T5"),
        _rect(34, 170, 28, 56, "T3"),
        _rect(34, 230, 28, 56, "T3"),
        _rect(34, 290, 28, 48, "T2"),
        _rect(34, 342, 28, 48, "T1"),
        _rect(66, 118, 24, 272, "T3"),
        _tag(48, 142, "T5", True),
        _tag(48, 254, "T3", True),
        _tag(48, 366, "T1", True),
        "</g>",
        '<g id="east">',
        _rect(658, 118, 28, 48, "T5"),
        _rect(658, 170, 28, 56, "T3"),
        _rect(658, 230, 28, 56, "T3"),
        _rect(658, 290, 28, 48, "T1"),
        _rect(630, 118, 24, 272, "T3"),
        _tag(672, 142, "T5", True),
        _tag(672, 254, "T3", True),
        _tag(672, 314, "T1", True),
        "</g>",
        _rect(66, 34, 48, 48, "T3"),
        _rect(606, 34, 48, 48, "T3"),
        _rect(66, 418, 48, 48, "T2"),
        _away(606, 418, 48, 28),
        _rect(606, 450, 48, 16, "T1"),
        _tag(90, 58, "T3", True),
        _tag(630, 58, "T3", True),
        _tag(90, 442, "T2", True),
        '<g transform="translate(648,18)">',
        '<circle cx="0" cy="0" r="14" fill="#15181e" stroke="#2a2f38"/>',
        '<text x="0" y="-4" text-anchor="middle" fill="#9aa3b2" font-size="9">N</text>',
        '<path d="M0,-10 L4,2 L0,0 L-4,2 Z" fill="#9aa3b2"/>',
        "</g>",
        f'<text x="12" y="18" fill="#6b7280" font-size="9">对手 {tier}级 · 总预测 {int(pred):,} 张</text>',
        '<g id="legend">',
    ]

    for i, zt in enumerate(zones):
        x = 10 + i * 118
        vol = tpred.get(zt, 0)
        tr = r.tiers.get(zt)
        price = f"¥{tr.optimal_price:,.0f}" if tr else "—"
        base = f"¥{tr.base_price:,.0f}" if tr else ""
        lock = " 🔒" if tr and tr.is_frozen else ""
        parts.append(
            f'<g transform="translate({x},468)">'
            f'<rect x="0" y="0" width="14" height="14" rx="2" fill="{tcolors[zt]}" '
            f'stroke="#0c0d0f" stroke-width="0.5"/>'
            f'<text x="18" y="11" fill="#d0d6e0" font-size="9">{zt} {tlabels[zt]}{lock}</text>'
            f'<text x="18" y="24" fill="#7a8494" font-size="8">{vol:,}张 · {price}'
            + (f" · 基准{base}" if base else "")
            + "</text></g>"
        )

    parts.append("</g></svg>")
    st.markdown("".join(parts), unsafe_allow_html=True)

    st.markdown("**分区销量预测**")
    rows = []
    for zt in zones:
        vol = tpred.get(zt, 0)
        tr = r.tiers.get(zt)
        price = f"¥{tr.optimal_price:,.0f}" if tr else "—"
        base_p = f"¥{tr.base_price:,.0f}" if tr else "—"
        revenue = f"¥{vol * tr.optimal_price / 10000:.1f}万" if tr and tr.optimal_price else "—"
        rows.append(
            {
                "分区": zt,
                "位置": tlabels.get(zt, ""),
                "预测销量": f"{vol:,}",
                "基准价": base_p,
                "建议价": price,
                "预估收入": revenue,
            }
        )
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        use_container_width=True,
        column_config={
            "分区": st.column_config.TextColumn(width="small"),
            "位置": st.column_config.TextColumn(width="medium"),
            "预测销量": st.column_config.TextColumn(width="small"),
            "基准价": st.column_config.TextColumn(width="small"),
            "建议价": st.column_config.TextColumn(width="small"),
            "预估收入": st.column_config.TextColumn(width="small"),
        },
    )

'''

out = text[:start] + NEW_FUNC + text[end:]
APP.write_text(out, encoding="utf-8")
log = Path(__file__).resolve().parent.parent / "patch_seating_done.txt"
log.write_text(f"ok lines={len(out.splitlines())}\n", encoding="utf-8")
