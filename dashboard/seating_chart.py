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

LEGEND_SVG = '<g transform="translate(890, 20)"><text x="0" y="0" fill="#8a8f98" font-size="9" font-family="Inter,sans-serif" font-weight="590">上座率</text><rect x="0" y="14" width="12" height="8" rx="1.5" fill="#a01020" fill-opacity="0.85"/><text x="16" y="21" fill="#a0a4a8" font-size="7" font-family="Inter,sans-serif">95%+</text><rect x="0" y="28" width="12" height="8" rx="1.5" fill="#c82828" fill-opacity="0.85"/><text x="16" y="35" fill="#a0a4a8" font-size="7" font-family="Inter,sans-serif">80%</text><rect x="0" y="42" width="12" height="8" rx="1.5" fill="#e07030" fill-opacity="0.85"/><text x="16" y="49" fill="#a0a4a8" font-size="7" font-family="Inter,sans-serif">65%</text><rect x="0" y="56" width="12" height="8" rx="1.5" fill="#f0c040" fill-opacity="0.85"/><text x="16" y="63" fill="#a0a4a8" font-size="7" font-family="Inter,sans-serif">50%</text><rect x="0" y="70" width="12" height="8" rx="1.5" fill="#2d7ab0" fill-opacity="0.85"/><text x="16" y="77" fill="#a0a4a8" font-size="7" font-family="Inter,sans-serif">30%</text><rect x="0" y="84" width="12" height="8" rx="1.5" fill="#1a4a7a" fill-opacity="0.85"/><text x="16" y="91" fill="#a0a4a8" font-size="7" font-family="Inter,sans-serif">&lt;30%</text></g>'


def render_gongti_heatmap(section_fills=None, _unused=None, match_label="", total_fill=0.0):
    if section_fills is None:
        section_fills = {}
    svg = _SVG_PATH.read_text()

    # 背景透明
    svg = svg.replace('fill="#fafafa"', 'fill="transparent"')

    # 替换每个分区颜色 (数据来源: dict的value = 实际销量张数)
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

    # 去掉旧图例/标题/指南针
    svg = re.sub(r'<text x="9\d\d".*?</text>\r?\n?', '', svg)
    svg = re.sub(r'<rect x="9\d\d".*?/>\r?\n?', '', svg)
    svg = re.sub(r'<title>.*?</title>\r?\n?', '', svg)
    svg = re.sub(r'<desc>.*?</desc>\r?\n?', '', svg)
    svg = re.sub(r'<g transform="translate\(96\d.*?</g>', '', svg, flags=re.DOTALL)
    svg = svg.replace('</svg>', LEGEND_SVG + '\n</svg>')

    title_html = ""
    if match_label:
        title_html = (
            f'<div style="text-align:center;padding:8px 0 4px 0;background:transparent">'
            f'<span style="color:#f0f2f5;font-size:1.1rem;font-weight:590;font-family:Inter,sans-serif">{match_label}</span>'
            f'{f"<span style=\"color:#8a8f98;font-size:0.85rem;margin-left:10px;font-family:Inter,sans-serif\">总上座率 {total_fill*100:.1f}%</span>" if total_fill > 0 else ""}'
            f'</div>'
        )

    html = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
body {{ margin:0; padding:8px; background:#0b0c0f; }}
svg {{ display:block; max-width:100%; height:auto; }}
</style></head>
<body>
{title_html}
{svg}
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
