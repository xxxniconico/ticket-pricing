"""
工体座位热力图 — 独立模块（不依赖 seating_chart.py 旧版同步）
"""
import re
import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

_SVG_PATH = Path(__file__).parent.parent / "assets" / "stadium_seating_b_class.svg"
_HEATMAP_VIEWBOX = "118 32 808 628"

_LEGEND_ITEMS = (
    ("#a01020", "95%+"),
    ("#c82828", "80%"),
    ("#e07030", "65%"),
    ("#f0c040", "50%"),
    ("#2d7ab0", "30%"),
    ("#1a4a7a", "<30%"),
    ("#14161c", "无售"),
)


def _heat(val: float) -> str:
    if val <= 0:
        return "#14161c"
    if val < 0.30:
        return "#1a4a7a"
    if val < 0.50:
        return "#2d7ab0"
    if val < 0.65:
        return "#f0c040"
    if val < 0.80:
        return "#e07030"
    if val < 0.92:
        return "#c82828"
    return "#a01020"


def norm_section_id(sec) -> str:
    s = str(sec).strip()
    try:
        return str(int(float(s)))
    except (TypeError, ValueError):
        return s


def _strip_template_decorations(svg: str) -> str:
    svg = re.sub(r'<g transform="translate\(940,48\)">.*?</g>\s*', "", svg, flags=re.DOTALL)
    svg = re.sub(r'<text x="8[47]\d[^"]*".*?</text>\s*', "", svg)
    svg = re.sub(r'<rect x="8[47]\d[^"]*".*?/>\s*', "", svg)
    svg = re.sub(r'<text x="9\d\d".*?</text>\s*', "", svg)
    svg = re.sub(r'<rect x="9\d\d".*?/>\s*', "", svg)
    svg = re.sub(r"<title>.*?</title>\s*", "", svg)
    svg = re.sub(r"<desc>.*?</desc>\s*", "", svg)
    svg = re.sub(r'<g transform="translate\(96\d.*?</g>\s*', "", svg, flags=re.DOTALL)
    return svg


def _make_svg_responsive(svg: str) -> str:
    svg = _strip_template_decorations(svg)
    svg = re.sub(r"<\?xml[^>]*\?>\s*", "", svg, count=1)
    svg = re.sub(r"<!--.*?-->\s*", "", svg, count=1, flags=re.DOTALL)
    svg = re.sub(r'viewBox="0 0 1024 686"', f'viewBox="{_HEATMAP_VIEWBOX}"', svg, count=1)
    svg = re.sub(r'\s+width="[^"]*"', "", svg, count=1)
    svg = re.sub(r'\s+height="[^"]*"', "", svg, count=1)
    if "preserveAspectRatio" not in svg:
        svg = svg.replace("<svg ", '<svg preserveAspectRatio="xMidYMid meet" ', 1)
    return svg


def build_gongti_heatmap_svg(section_fills=None) -> str:
    if section_fills is None:
        section_fills = {}
    fills = {norm_section_id(k): v for k, v in section_fills.items()}

    if not _SVG_PATH.exists():
        raise FileNotFoundError(f"座位 SVG 模板不存在: {_SVG_PATH}")

    svg = _SVG_PATH.read_text(encoding="utf-8")
    svg = svg.replace('fill="#fafafa"', 'fill="transparent"')
    svg = _make_svg_responsive(svg)
    svg = re.sub(
        r"(<svg[^>]*>)",
        r'\1<rect x="118" y="32" width="808" height="628" fill="#0b0c0f"/>',
        svg,
        count=1,
    )

    path_re = re.compile(
        r'<path id="sec-(\d+)" (d="[^"]*")[^>]*fill="([^"]*)"([^/]*)/>'
    )
    for m in path_re.finditer(svg):
        sec, d_attr, orig_fill, rest = m.group(1), m.group(2), m.group(3), m.group(4)
        val = fills.get(sec, 0)
        if isinstance(val, (int, float)) and val > 0:
            new_fill = _heat(val)
        elif orig_fill in ("#ffffff", "#fafafa", "#fff"):
            new_fill = "#3a3f48"
        else:
            new_fill = orig_fill
        new_tag = f'<path id="sec-{sec}" {d_attr} fill="{new_fill}"{rest}/>'
        svg = svg.replace(m.group(0), new_tag, 1)
    return svg


def svg_to_png_bytes(svg: str, output_width: int = 960) -> bytes | None:
    try:
        import cairosvg
        png = cairosvg.svg2png(
            bytestring=svg.encode("utf-8"),
            output_width=output_width,
            background_color="#0b0c0f",
        )
        if png and len(png) > 500:
            return png
    except Exception:
        pass

    try:
        from svglib.svglib import svg2rlg
        from reportlab.graphics import renderPM
        drawing = svg2rlg(BytesIO(svg.encode("utf-8")))
        if drawing:
            buf = BytesIO()
            renderPM.drawToFile(drawing, buf, fmt="PNG")
            data = buf.getvalue()
            if data and len(data) > 500:
                return data
    except Exception:
        pass

    rsvg = shutil.which("rsvg-convert")
    if rsvg:
        try:
            proc = subprocess.run(
                [rsvg, "-f", "png", "--background-color=#0b0c0f"],
                input=svg.encode("utf-8"),
                capture_output=True,
                timeout=8,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout and len(proc.stdout) > 500:
                return proc.stdout
        except (OSError, subprocess.SubprocessError):
            pass
    return None


def heatmap_legend_caption() -> str:
    parts = " · ".join(lbl for _, lbl in _LEGEND_ITEMS)
    return f"上座率图例: {parts}（由低到高: 无售→蓝→黄→红）"


def _iframe_html(svg: str, match_label: str, total_fill: float) -> str:
    title = match_label or "工体座位热力图"
    if total_fill > 0:
        title += f" · 总上座率 {total_fill * 100:.1f}%"
    chips = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:4px;margin:2px 5px;'
        f'color:#a0a4a8;font-size:10px"><i style="display:inline-block;width:10px;'
        f'height:8px;border-radius:2px;background:{c}"></i>{lbl}</span>'
        for c, lbl in _LEGEND_ITEMS
    )
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<style>
html,body{{margin:0;padding:0;background:#0c0d0f}}
body{{font-family:system-ui,sans-serif;padding:6px 4px}}
.title{{text-align:center;color:#f0f2f5;font-size:13px;font-weight:600;padding:2px 0 8px}}
svg{{display:block;width:100%;height:auto}}
.legend{{display:flex;flex-wrap:wrap;justify-content:center;padding:6px 2px}}
.lt{{color:#8a8f98;font-size:10px;font-weight:600;margin-right:4px}}
</style></head><body>
<div class="title">{title}</div>
{svg}
<div class="legend"><span class="lt">上座率</span>{chips}</div>
</body></html>"""


def show_heatmap_in_streamlit(st, components, section_fills, match_label, total_fill, height=680):
    """在看板 Tab 中显示热力图（iframe 内嵌 SVG，随容器宽度缩放）。"""
    svg = build_gongti_heatmap_svg(section_fills)
    png = svg_to_png_bytes(svg)
    if png:
        st.image(png, use_container_width=True)
        st.caption(heatmap_legend_caption())
        return

    components.html(
        _iframe_html(svg, match_label, total_fill),
        height=height,
        scrolling=False,
    )
    st.caption(heatmap_legend_caption())
