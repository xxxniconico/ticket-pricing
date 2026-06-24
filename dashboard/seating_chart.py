"""
工体座位热力图 V24 — SVG模板 + 销量着色 + Streamlit 内联 img（无 iframe）

⚠️ 已归档：看板 V8 使用 dashboard/seating_heatmap.py（components.html iframe）。
本文件保留供离线调试 / 历史参考，serve.sh 不再引用。
"""
import re, math, base64, shutil, subprocess, tempfile
from io import BytesIO
from pathlib import Path

_SVG_PATH = Path(__file__).parent.parent / "assets" / "stadium_seating_b_class.svg"

def _heat(val):
    """val = 上座率(0-1), 也可能是绝对销量"""
    if val <= 0:      return '#14161c'
    elif val < 0.30:  return '#1a4a7a'
    elif val < 0.50:  return '#2d7ab0'
    elif val < 0.65:  return '#f0c040'
    elif val < 0.80:  return '#e07030'
    elif val < 0.92:  return '#c82828'
    else:             return '#a01020'

_fill_color = _heat
SECTION_BLOCKS = []
_SEC_MAP = {}

# 热力图裁剪：去掉模板右侧图例区，看台占满宽度（手机端可读）
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


def _legend_html() -> str:
    chips = "".join(
        f'<span class="seat-heatmap-legend-chip"><i style="background:{c}"></i>{lbl}</span>'
        for c, lbl in _LEGEND_ITEMS
    )
    return f'<div class="seat-heatmap-legend"><span class="seat-heatmap-legend-title">上座率</span>{chips}</div>'


def _strip_template_decorations(svg: str) -> str:
    """移除 B 类模板中的票价图例、指南针等（热力图不需要）。"""
    svg = re.sub(r'<g transform="translate\(940,48\)">.*?</g>\s*', '', svg, flags=re.DOTALL)
    svg = re.sub(r'<text x="8[47]\d[^"]*".*?</text>\s*', '', svg)
    svg = re.sub(r'<rect x="8[47]\d[^"]*".*?/>\s*', '', svg)
    svg = re.sub(r'<text x="9\d\d".*?</text>\s*', '', svg)
    svg = re.sub(r'<rect x="9\d\d".*?/>\s*', '', svg)
    svg = re.sub(r'<title>.*?</title>\s*', '', svg)
    svg = re.sub(r'<desc>.*?</desc>\s*', '', svg)
    svg = re.sub(r'<g transform="translate\(96\d.*?</g>\s*', '', svg, flags=re.DOTALL)
    return svg


def _make_svg_responsive(svg: str) -> str:
    svg = _strip_template_decorations(svg)
    svg = re.sub(r'<\?xml[^>]*\?>\s*', '', svg, count=1)
    svg = re.sub(r'<!--.*?-->\s*', '', svg, count=1, flags=re.DOTALL)
    svg = re.sub(r'viewBox="0 0 1024 686"', f'viewBox="{_HEATMAP_VIEWBOX}"', svg, count=1)
    svg = re.sub(r'\s+width="[^"]*"', '', svg, count=1)
    svg = re.sub(r'\s+height="[^"]*"', '', svg, count=1)
    if 'preserveAspectRatio' not in svg:
        svg = svg.replace('<svg ', '<svg preserveAspectRatio="xMidYMid meet" ', 1)
    return svg


def svg_to_png_bytes(svg: str, output_width: int = 960) -> bytes | None:
    """SVG → PNG。优先 cairosvg，其次 svglib / rsvg / ImageMagick。"""
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
            if proc.returncode == 0 and proc.stdout:
                return proc.stdout
        except (OSError, subprocess.SubprocessError):
            pass
    convert = shutil.which("convert")
    if convert:
        svg_path = png_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as sf:
                sf.write(svg.encode("utf-8"))
                svg_path = sf.name
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as pf:
                png_path = pf.name
            proc = subprocess.run(
                [convert, svg_path, png_path],
                capture_output=True,
                timeout=8,
                check=False,
            )
            if proc.returncode == 0:
                data = Path(png_path).read_bytes()
                if data:
                    return data
        except (OSError, subprocess.SubprocessError):
            pass
        finally:
            for p in (svg_path, png_path):
                if p:
                    try:
                        Path(p).unlink(missing_ok=True)
                    except OSError:
                        pass
    return None


def _svg_as_img(svg: str) -> str:
    """优先 PNG data URI（手机 Streamlit 兼容），否则回退 SVG data URI。"""
    png = svg_to_png_bytes(svg)
    if png:
        b64 = base64.b64encode(png).decode("ascii")
        mime = "image/png"
    else:
        b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
        mime = "image/svg+xml"
    return (
        f'<img class="seat-heatmap-img" '
        f'src="data:{mime};base64,{b64}" '
        f'alt="工体座位热力图" loading="lazy" />'
    )


def _norm_section_id(sec) -> str:
    """Parquet 分区号可能是 301.0，统一为 SVG 用的 '301'。"""
    s = str(sec).strip()
    try:
        return str(int(float(s)))
    except (TypeError, ValueError):
        return s


def build_gongti_heatmap_svg(section_fills=None) -> str:
    """生成着色后的 SVG 字符串（内联 HTML 或 PNG 渲染）。"""
    if section_fills is None:
        section_fills = {}
    fills = {_norm_section_id(k): v for k, v in section_fills.items()}

    svg = _SVG_PATH.read_text()
    svg = svg.replace('fill="#fafafa"', 'fill="transparent"')
    svg = _make_svg_responsive(svg)

    # 深色背景，避免 PNG/暗色主题下「全黑看不见」
    bg = (
        f'<rect x="118" y="32" width="808" height="628" fill="#0b0c0f"/>'
    )
    svg = re.sub(r"(<svg[^>]*>)", r"\1" + bg, svg, count=1)

    path_re = re.compile(
        r'<path id="sec-(\d+)" (d="[^"]*")[^>]*fill="([^"]*)"([^/]*)/>'
    )
    for m in path_re.finditer(svg):
        sec = m.group(1)
        d_attr = m.group(2)
        orig_fill = m.group(3)
        rest = m.group(4)
        old = m.group(0)
        val = fills.get(sec, 0)
        if isinstance(val, (int, float)) and val > 0:
            new_fill = _heat(val)
        elif orig_fill in ("#ffffff", "#fafafa", "#fff"):
            new_fill = "#3a3f48"
        else:
            new_fill = orig_fill
        new_tag = f'<path id="sec-{sec}" {d_attr} fill="{new_fill}"{rest}/>'
        svg = svg.replace(old, new_tag, 1)
    return svg


def render_heatmap_title(match_label: str, total_fill: float = 0.0) -> str:
    if not match_label:
        return ""
    sub = (
        f'<span class="seat-heatmap-sub">总上座率 {total_fill * 100:.1f}%</span>'
        if total_fill > 0 else ""
    )
    return (
        f'<div class="seat-heatmap-title">'
        f'<span class="seat-heatmap-match">{match_label}</span>{sub}</div>'
    )


def render_heatmap_chart(svg: str) -> str:
    """仅返回热力图图片区域 HTML。"""
    return f'<div class="seat-heatmap-chart">{_svg_as_img(svg)}</div>'


def render_heatmap_legend() -> str:
    return _legend_html()


def heatmap_legend_caption() -> str:
    """Streamlit App 可用的纯文本图例（不依赖 HTML）。"""
    parts = " · ".join(lbl for _, lbl in _LEGEND_ITEMS)
    return f"上座率图例: {parts}（由低到高: 无售→蓝→黄→红）"


def render_gongti_heatmap(section_fills=None, _unused=None, match_label="", total_fill=0.0):
    """内联 SVG HTML（供 iframe / 静态预览；勿直接 st.markdown，Streamlit 会剥离 svg）。"""
    svg = build_gongti_heatmap_svg(section_fills)
    title_html = render_heatmap_title(match_label, total_fill)
    return f'''<div class="seat-heatmap">
{title_html}
<div class="seat-heatmap-chart">{svg}</div>
{_legend_html()}
</div>'''


def _heatmap_iframe_html(section_fills=None, match_label="", total_fill=0.0) -> str:
    """自包含 HTML，供 streamlit.components.v1.html 使用。"""
    svg = build_gongti_heatmap_svg(section_fills)
    title = match_label or "工体座位热力图"
    if total_fill > 0:
        title += f" · 总上座率 {total_fill * 100:.1f}%"
    chips = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:4px;margin:2px 5px;'
        f'color:#a0a4a8;font-size:10px;white-space:nowrap">'
        f'<i style="display:inline-block;width:10px;height:8px;border-radius:2px;background:{c}"></i>'
        f'{lbl}</span>'
        for c, lbl in _LEGEND_ITEMS
    )
    return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<style>
  html,body{{margin:0;padding:0;background:#0c0d0f}}
  body{{font-family:system-ui,-apple-system,sans-serif;padding:6px 4px 4px}}
  .title{{text-align:center;color:#f0f2f5;font-size:13px;font-weight:600;line-height:1.35;padding:2px 0 8px}}
  svg{{display:block;width:100%;height:auto;max-width:100%}}
  .legend{{display:flex;flex-wrap:wrap;align-items:center;justify-content:center;padding:6px 2px 2px}}
  .legend-label{{color:#8a8f98;font-size:10px;font-weight:600;margin-right:4px}}
</style>
</head><body>
<div class="title">{title}</div>
{svg}
<div class="legend"><span class="legend-label">上座率</span>{chips}</div>
</body></html>"""


def show_heatmap_in_streamlit(section_fills=None, match_label="", total_fill=0.0, height: int = 660):
    """在看板中显示热力图。

    Streamlit 的 st.markdown 会剥离 <svg>，约 40KB 内联 SVG 也可能触发消息截断。
    因此：优先 st.image(PNG)；否则 components.html iframe 内嵌完整 SVG。
    """
    import streamlit as st
    import streamlit.components.v1 as components

    if section_fills is None:
        section_fills = {}

    svg = build_gongti_heatmap_svg(section_fills)
    png = svg_to_png_bytes(svg)

    if png and len(png) > 500:
        st.image(png, use_container_width=True)
        st.caption(heatmap_legend_caption())
        return

    components.html(_heatmap_iframe_html(section_fills, match_label, total_fill), height=height, scrolling=False)
    st.caption(heatmap_legend_caption())
    if not png:
        st.caption("ℹ️ PNG 引擎未就绪，当前为 SVG 模式（已自动切换，无需安装 cairo）")


# ── 兼容 ──
C={'1080':'#d4a843','540':'#e0556a','460':'#e0b840','300':'#e08840','220':'#5b9bd5','160':'#5cb878','away':'#7a7f88','iso':'#4a4a4a'}
ZONES=[]; LR={'i':(0.44,0.64),'m':(0.69,0.82),'o':(0.86,0.99)}
def _band(cx,cy,rxo,ryo,ri,ro,a1,a2):
    s,e=math.radians(a1),math.radians(a2); rox,roy=rxo*ro,ryo*ro; rix,riy=rxo*ri,ryo*ri
    ox1=cx+rox*math.cos(s);oy1=cy+roy*math.sin(s);ix1=cx+rix*math.cos(s);iy1=cy+riy*math.sin(s)
    ox2=cx+rox*math.cos(e);oy2=cy+roy*math.sin(e);ix2=cx+rix*math.cos(e);iy2=cy+riy*math.sin(e)
    la=1 if(a2-a1)>180 else 0
    return(f'M{ox1:.1f} {oy1:.1f} L{ix1:.1f} {iy1:.1f} A{rix:.1f} {riy:.1f} 0 {la} 1 {ix2:.1f} {iy2:.1f} L{ox2:.1f} {oy2:.1f} A{rox:.1f} {roy:.1f} 0 {la} 0 {ox1:.1f} {oy1:.1f}Z')
def render_gongti_seating(t=None,p=None,r=None):
    cx,cy=270,230;rxo,ryo=240,185
    out=['<div style="overflow-x:auto"><svg viewBox="0 0 560 460" width="100%" style="max-width:560px;background:#08090a;border-radius:8px;border:1px solid rgba(255,255,255,0.04)">']
    out.append('<defs><pattern id="dot" width="4" height="4" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1" fill="#7a7f88" opacity="0.5"/></pattern><pattern id="hatch" width="4" height="4" patternUnits="userSpaceOnUse"><line x1="0" y1="4" x2="4" y2="0" stroke="#4a4a4a" stroke-width="0.8" opacity="0.35"/></pattern></defs>')
    out.append(f'<rect width="560" height="460" fill="#08090a"/>')
    out.append(f'<ellipse cx="{cx}" cy="{cy}" rx="{rxo}" ry="{ryo}" fill="none" stroke="rgba(255,255,255,0.025)" stroke-width="1"/>')
    for pk,a1,a2,lyr in ZONES:
        if pk not in C: continue; color=C[pk]; ri,ro=LR[lyr]
        if pk=='away': out.append(f'<path d="{_band(cx,cy,rxo,ryo,ri,ro,a1,a2)}" fill="url(#dot)" stroke="#7a7f88" stroke-width="0.3" opacity="0.7"/>')
        elif pk=='iso': out.append(f'<path d="{_band(cx,cy,rxo,ryo,ri,ro,a1,a2)}" fill="url(#hatch)" stroke="#4a4a4a" stroke-width="0.3" opacity="0.65"/>')
        else: out.append(f'<path d="{_band(cx,cy,rxo,ryo,ri,ro,a1,a2)}" fill="{color}" fill-opacity="0.52" stroke="{color}" stroke-width="0.4" stroke-opacity="0.45"/>')
    for rs in[0.66,0.84]: out.append(f'<ellipse cx="{cx}" cy="{cy}" rx="{rxo*rs:.1f}" ry="{ryo*rs:.1f}" fill="none" stroke="rgba(255,255,255,0.03)" stroke-width="0.4"/>')
    frx,fry=rxo*0.42,ryo*0.42
    out.append(f'<ellipse cx="{cx}" cy="{cy}" rx="{frx}" ry="{fry}" fill="#0b1a0b" stroke="#162a16" stroke-width="1.2"/>')
    out.append(f'<line x1="{cx}" y1="{cy-fry}" x2="{cx}" y2="{cy+fry}" stroke="#162a16" stroke-width="0.6"/>')
    out.append(f'<circle cx="{cx}" cy="{cy}" r="{fry*0.28}" fill="none" stroke="#162a16" stroke-width="0.6"/>')
    out.append(f'<circle cx="{cx}" cy="{cy}" r="1.5" fill="#1a2a1a"/>')
    out.append(f'<text x="{cx}" y="{cy+4}" fill="#1d301d" font-size="12" text-anchor="middle" font-weight="bold">工体</text>')
    out.append(f'<polygon points="500,28 497,22 503,22" fill="#8a8f98"/><text x="500" y="34" fill="#8a8f98" font-size="6.5" text-anchor="middle">N</text>')
    lx,ly=20,420; out.append(f'<text x="{lx}" y="{ly}" fill="#94a3b8" font-size="9" font-weight="600">分区</text>')
    LEG=[('1080','VIP'),('540','好位'),('460','中位'),('300','基础'),('220','远台'),('160','边角'),('away','客队'),('iso','隔离')]
    for i,(pk,label) in enumerate(LEG):
        r2,c2=i//4,i%4; px2=lx+c2*130; py2=ly+14+r2*18
        if pk=='away': out.append(f'<rect x="{px2}" y="{py2}" width="12" height="9" rx="1.5" fill="url(#dot)" stroke="#7a7f88" stroke-width="0.3"/>')
        elif pk=='iso': out.append(f'<rect x="{px2}" y="{py2}" width="12" height="9" rx="1.5" fill="url(#hatch)" stroke="#4a4a4a" stroke-width="0.3"/>')
        else: out.append(f'<rect x="{px2}" y="{py2}" width="12" height="9" rx="1.5" fill="{C[pk]}" fill-opacity="0.6"/>')
        out.append(f'<text x="{px2+16}" y="{py2+8}" fill="#a0a4a8" font-size="8">{label} ¥{pk}</text>')
    if p: out.append(f'<text x="450" y="450" fill="#8a8f98" font-size="7" text-anchor="end">预测 {p:,.0f} 张</text>')
    out.append('</svg></div>')
    return '\n'.join(out)
