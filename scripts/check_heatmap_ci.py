#!/usr/bin/env python3
"""热力图 CI 门禁：SVG 可生成、HTML iframe 可构建、PNG 路径可选。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dashboard.seating_heatmap import (  # noqa: E402
    _SVG_PATH,
    build_gongti_heatmap_svg,
    svg_to_png_bytes,
    _iframe_html,
)


def main() -> int:
    if not _SVG_PATH.exists():
        print(f"FAIL: SVG template missing: {_SVG_PATH}")
        return 1

    fills = {"301": 0.95, "302": 0.72, "118": 0.45}
    svg = build_gongti_heatmap_svg(fills)
    if len(svg) < 30_000:
        print(f"FAIL: SVG too small ({len(svg)} bytes), expected > 30KB")
        return 1
    print(f"OK: SVG {len(svg)} bytes")

    html = _iframe_html(svg, "CI test", 0.67)
    if len(html) < 30_000 or "<svg" not in html:
        print(f"FAIL: iframe HTML invalid ({len(html)} bytes)")
        return 1
    print(f"OK: iframe HTML {len(html)} bytes")

    png = svg_to_png_bytes(svg)
    if png and len(png) > 500:
        print(f"OK: PNG {len(png)} bytes")
    else:
        print("WARN: PNG unavailable (iframe SVG fallback is primary)")

    print("HEATMAP_CI_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
