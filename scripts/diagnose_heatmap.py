#!/usr/bin/env python3
"""Diagnose seat heatmap rendering."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dashboard.seating_chart import (
    build_gongti_heatmap_svg,
    render_gongti_heatmap,
    svg_to_png_bytes,
    _SVG_PATH,
)

def main():
    print("SVG template exists:", _SVG_PATH.exists(), _SVG_PATH)
    fills = {"301": 0.95, "302": 0.72, "118": 0.45}
    svg = build_gongti_heatmap_svg(fills)
    html = render_gongti_heatmap(fills, None, "2026-05-01 vs TEST", 0.67)
    print("SVG length:", len(svg))
    print("HTML length:", len(html))
    print("viewBox:", re.search(r'viewBox="[^"]+"', svg).group())
    print("path sec count:", len(re.findall(r'id="sec-\d+"', svg)))
    heat_colored = len(re.findall(r'fill="#(?:a01020|c82828|e07030|f0c040|2d7ab0|1a4a7a|14161c)"', svg))
    print("heat-colored paths:", heat_colored)
    print("has pitch:", "pitchGrad" in svg or 'id="pitch"' in svg)
    png = svg_to_png_bytes(svg)
    print("PNG bytes:", len(png) if png else None)
    out_svg = ROOT / "assets" / "_heatmap_debug.svg"
    out_html = ROOT / "assets" / "_heatmap_debug.html"
    out_svg.write_text(svg, encoding="utf-8")
    out_html.write_text(
        f"<!DOCTYPE html><html><body style='background:#0c0d0f;margin:0'>{html}</body></html>",
        encoding="utf-8",
    )
    if png:
        (ROOT / "assets" / "_heatmap_debug.png").write_bytes(png)
    print("Wrote:", out_svg, out_html)

if __name__ == "__main__":
    main()
