"""
工体座位热力图 V23 — SVG模板 + 销量着色 + 热力色阶图例
"""
import re, math
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
    ("#1a4a7a", "&lt;30%"),
    ("#14161c", "无售"),
)


def _legend_html() -> str:
    chips = "".join(
        f'<span class="lg-chip"><i style="background:{c}"></i>{lbl}</span>'
        for c, lbl in _LEGEND_ITEMS
    )
    return f'<div class="lg-bar"><span class="lg-title">上座率</span>{chips}</div>'


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
    svg = re.sub(r'viewBox="0 0 1024 686"', f'viewBox="{_HEATMAP_VIEWBOX}"', svg, count=1)
    svg = re.sub(r'\s+width="[^"]*"', '', svg, count=1)
    svg = re.sub(r'\s+height="[^"]*"', '', svg, count=1)
    if 'preserveAspectRatio' not in svg:
        svg = svg.replace('<svg ', '<svg preserveAspectRatio="xMidYMid meet" ', 1)
    return svg


def render_gongti_heatmap(section_fills=None, _unused=None, match_label="", total_fill=0.0):
    if section_fills is None:
        section_fills = {}
    svg = _SVG_PATH.read_text()
    svg = svg.replace('fill="#fafafa"', 'fill="transparent"')
    svg = _make_svg_responsive(svg)

    # 替换每个分区颜色 (数据来源: dict的value = 实际上座率 0-1)
    for m in re.finditer(r'<path id="sec-(\d+)" (d="[^"]*")[^>]*fill="([^"]*)"([^/]*)/>', svg):
        sec = m.group(1); d_attr = m.group(2); orig_fill = m.group(3); rest = m.group(4); old = m.group(0)
        val = section_fills.get(sec, 0)
        if isinstance(val, (int, float)) and val > 0:
            new_fill = _heat(val)
        elif orig_fill in ('#ffffff', '#fafafa', '#fff'):
            new_fill = '#e8e8e8'
        else:
            continue
        new_tag = f'<path id="sec-{sec}" {d_attr} fill="{new_fill}"{rest}/>'
        svg = svg.replace(old, new_tag, 1)

    title_html = ""
    if match_label:
        sub = (
            f'<span class="hm-sub">总上座率 {total_fill * 100:.1f}%</span>'
            if total_fill > 0
            else ""
        )
        title_html = (
            f'<div class="hm-title"><span class="hm-match">{match_label}</span>{sub}</div>'
        )

    # viewBox 宽高比 808:628 — 用于 JS 按容器宽度推算高度
    html = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover">
<style>
* {{ box-sizing: border-box; }}
html, body {{
  margin: 0; padding: 0; width: 100%; max-width: 100%;
  overflow-x: hidden; background: #0b0c0f;
  font-family: Inter, system-ui, sans-serif;
}}
.hm-wrap {{ width: 100%; max-width: 100%; padding: 4px 6px 6px; }}
.hm-title {{ text-align: center; padding: 4px 0 2px; line-height: 1.35; }}
.hm-match {{ color: #f0f2f5; font-size: clamp(0.78rem, 3.2vw, 1.1rem); font-weight: 600; }}
.hm-sub {{ display: block; color: #8a8f98; font-size: clamp(0.68rem, 2.8vw, 0.88rem); margin-top: 2px; }}
@media (min-width: 480px) {{
  .hm-sub {{ display: inline; margin-top: 0; margin-left: 8px; }}
}}
.chart-box {{
  width: 100%; margin: 0 auto; overflow: hidden;
  max-width: min(100%, var(--hm-chart-max-w, 960px));
}}
.chart-box svg {{
  display: block; width: 100%; height: auto; max-width: 100%;
  max-height: var(--hm-chart-max-h, clamp(240px, 55vh, 720px));
}}
/* CSS 断点兜底（无 JS 时） */
@media (max-width: 479px) {{
  .chart-box svg {{ max-height: min(56vh, 380px); }}
}}
@media (min-width: 480px) and (max-width: 767px) {{
  .chart-box svg {{ max-height: min(58vh, 440px); }}
}}
@media (min-width: 768px) and (max-width: 1199px) {{
  .chart-box {{ max-width: min(100%, 820px); }}
  .chart-box svg {{ max-height: min(68vh, 620px); }}
}}
@media (min-width: 1200px) {{
  .chart-box {{ max-width: min(100%, 1024px); }}
  .chart-box svg {{ max-height: min(78vh, 860px); }}
}}
.lg-bar {{
  display: flex; flex-wrap: wrap; align-items: center; justify-content: center;
  gap: 6px 12px; padding: 8px 4px 2px;
}}
.lg-title {{ color: #8a8f98; font-size: clamp(0.62rem, 2vw, 0.75rem); font-weight: 600; margin-right: 2px; }}
.lg-chip {{
  display: inline-flex; align-items: center; gap: 4px;
  color: #a0a4a8; font-size: clamp(0.58rem, 1.8vw, 0.7rem); white-space: nowrap;
}}
.lg-chip i {{
  display: inline-block; width: 10px; height: 8px; border-radius: 2px; opacity: 0.9;
}}
</style></head>
<body>
<div class="hm-wrap">
{title_html}
<div class="chart-box">{svg}</div>
{_legend_html()}
</div>
<script>
(function() {{
  var VB_W = 808, VB_H = 628;

  function chartLimits() {{
    var vw = window.innerWidth, vh = window.innerHeight;
    var maxW, maxH;
    if (vw < 480) {{
      maxW = vw - 16;
      maxH = Math.min(vh * 0.56, 380);
    }} else if (vw < 768) {{
      maxW = vw - 24;
      maxH = Math.min(vh * 0.58, 440);
    }} else if (vw < 1200) {{
      maxW = Math.min(vw - 48, 820);
      maxH = Math.min(vh * 0.68, 620);
    }} else {{
      maxW = Math.min(vw - 64, 1024);
      maxH = Math.min(vh * 0.78, 860);
    }}
    var box = document.querySelector(".chart-box");
    var wrapW = box ? box.clientWidth : maxW;
    if (wrapW > 0) maxW = Math.min(maxW, wrapW);
    var byAspect = maxW * (VB_H / VB_W);
    maxH = Math.max(200, Math.min(maxH, byAspect));
    return {{ maxW: maxW, maxH: maxH }};
  }}

  function applyChartSize() {{
    var lim = chartLimits();
    var root = document.documentElement;
    root.style.setProperty("--hm-chart-max-w", lim.maxW + "px");
    root.style.setProperty("--hm-chart-max-h", lim.maxH + "px");
  }}

  function reportHeight() {{
    var h = Math.ceil(document.documentElement.scrollHeight) + 6;
    window.parent.postMessage({{type: "streamlit:setFrameHeight", height: h}}, "*");
  }}

  function onLayout() {{
    applyChartSize();
    requestAnimationFrame(reportHeight);
  }}

  onLayout();
  window.addEventListener("resize", onLayout);
  if (window.ResizeObserver) {{
    var box = document.querySelector(".chart-box");
    if (box) new ResizeObserver(onLayout).observe(box);
  }}
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(onLayout);
}})();
</script>
</body></html>'''
    return html


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
