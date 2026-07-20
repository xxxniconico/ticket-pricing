"""
国安票务动态定价看板 V7 — Linear暗色风格 · 仅主场预测
"""
import sys, json, math
from pathlib import Path
from collections import defaultdict
import pandas as pd, numpy as np
import streamlit as st
import matplotlib, matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# 注册中文字体：按优先级搜索已知路径
_CN_FONT_NAME = None
for _fp in [
    Path.home() / '.fonts' / 'simhei.ttf',
    Path.home() / '.fonts' / 'msyh.ttc',
    '/mnt/c/Windows/Fonts/simhei.ttf',
    '/mnt/c/Windows/Fonts/msyh.ttc',
    '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
    '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc',
]:
    if _fp.exists():
        fm.fontManager.addfont(str(_fp))
        _CN_FONT_NAME = fm.FontProperties(fname=str(_fp)).get_name()
        break

if _CN_FONT_NAME is None:
    for _name in ['WenQuanYi Micro Hei', 'WenQuanYi Zen Hei', 'Noto Sans CJK SC',
                   'SimHei', 'Microsoft YaHei', 'Noto Sans SC']:
        if any(_name.lower() in str(f).lower() for f in fm.fontManager.ttflist):
            _CN_FONT_NAME = _name
            break

if _CN_FONT_NAME:
    matplotlib.rcParams["font.sans-serif"] = [_CN_FONT_NAME, "DejaVu Sans"]
    fm._load_fontmanager(try_read_cache=False)
else:
    matplotlib.rcParams["font.sans-serif"] = ["DejaVu Sans"]

matplotlib.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parent.parent  # ticket-pricing/
sys.path.insert(0, str(ROOT))

from src.rule_engine import predict_calibrated as rule_predict, TIER_BASE, MULTIPLIERS, PENALTY_FLOOR, get_calibration
from src.dynamic_optimizer import DynamicPricingOptimizer
# live_calibrate removed — no pre-sale data available
from src.pricing_v5 import ZONE_TIERS, ZONE_SECTIONS, classify_opponent, get_pricing_tier, build_price_matrix, build_elasticity_matrix, get_zone_bounds
from src.csl_context import load_csl_data, get_guoan_matches, detect_ctx

st.set_page_config(page_title="国安票务", page_icon="⚽", layout="wide")

PT_LABELS = {"S_S":"S·德比定价","S_A":"A·标准定价","S_Aminus":"A·降价","S_B":"B·标准定价","S_C":"C·标准定价","S_Cminus":"C·降价"}

st.markdown("""
<style>
    .stApp { background: #0c0d0f; }
    section[data-testid="stSidebar"] { display: none; }
    html, body, .stApp, .stMarkdown, p, div, span, label {
        font-family: 'Inter', system-ui, -apple-system, sans-serif !important; color: #d0d6e0;
    }
    h1 { font-family: 'Inter', system-ui, sans-serif !important; font-weight: 510 !important;
         font-size: 1.5rem !important; color: #f7f8f8 !important; letter-spacing: -0.03em !important; margin:0 !important; }
    h2 { font-weight: 510 !important; font-size: 1.1rem !important; color: #e2e4e7 !important; }
    h3, h4 { font-weight: 510 !important; font-size: 0.95rem !important; color: #c8ccd4 !important; }
    .stMetric { background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06);
                border-radius: 6px; padding: 8px 12px !important; }
    .stMetric label { font-size: 0.68rem !important; color: #62666d !important; font-weight: 400 !important;
                      letter-spacing: 0.03em; text-transform: uppercase; }
    .stMetric [data-testid="stMetricValue"] { font-size: 1.2rem !important; font-weight: 510 !important; color: #f7f8f8 !important; }
    .stMetric [data-testid="stMetricDelta"] { font-size: 0.7rem !important; }
    hr { border-color: rgba(255,255,255,0.06) !important; margin: 0.6rem 0 !important; }
    .stDataFrame { border: 1px solid rgba(255,255,255,0.06) !important; border-radius: 6px !important;
                   background: rgba(255,255,255,0.015) !important; }
    .stDataFrame th { background: rgba(255,255,255,0.03) !important; color: #8a8f98 !important;
                      font-size: 0.68rem !important; font-weight: 510 !important; text-transform: uppercase; }
    .stDataFrame td { color: #d0d6e0 !important; font-size: 0.78rem !important;
                      background: transparent !important; }
    [data-testid="stTable"] { background: rgba(255,255,255,0.015) !important; }
    table { width: 100%; border-collapse: collapse; font-size: 0.78rem;
            background: rgba(255,255,255,0.015); border: 1px solid rgba(255,255,255,0.06);
            border-radius: 6px; overflow: hidden; }
    table thead th { background: rgba(255,255,255,0.03); color: #8a8f98; font-weight: 510;
                     font-size: 0.68rem; text-transform: uppercase; padding: 6px 10px;
                     border-bottom: 1px solid rgba(255,255,255,0.06); text-align: center; }
    table tbody td { color: #d0d6e0; padding: 5px 10px; text-align: center;
                     border-bottom: 1px solid rgba(255,255,255,0.03); }
    table tbody tr:hover { background: rgba(255,255,255,0.03); }
    table.compact-table { font-size: 0.7rem; }
    table.compact-table thead th { font-size: 0.6rem; padding: 4px 6px; }
    table.compact-table tbody td { font-size: 0.7rem; padding: 3px 6px; }
    table.history-table { width: 100%; border-collapse: collapse; font-size: 0.65rem;
        background: rgba(255,255,255,0.015); border: 1px solid rgba(255,255,255,0.06);
        border-radius: 6px; overflow: hidden; margin: 4px 0; }
    table.history-table thead th { background: rgba(255,255,255,0.03); color: #8a8f98;
        font-weight: 510; font-size: 0.58rem; padding: 3px 5px;
        border-bottom: 1px solid rgba(255,255,255,0.06); text-align: center; }
    table.history-table tbody td { color: #d0d6e0; padding: 2px 5px; text-align: center;
        border-bottom: 1px solid rgba(255,255,255,0.02);
        font-family: 'JetBrains Mono', ui-monospace, monospace; }
    table.history-table tbody tr:hover { background: rgba(255,255,255,0.02); }
    .streamlit-expanderHeader { background: rgba(255,255,255,0.02) !important;
        border: 1px solid rgba(255,255,255,0.06) !important; border-radius: 6px !important;
        color: #8a8f98 !important; font-size: 0.78rem !important; }
    .state-bar { font-size: 0.75rem; color: #8a8f98; padding: 6px 12px;
                 background: rgba(255,255,255,0.015); border: 1px solid rgba(255,255,255,0.05); border-radius: 6px; }
    .state-bar strong { color: #f7f8f8; font-weight: 510; }
    .rule-line { font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 0.8rem;
                 padding: 3px 10px; margin: 1px 0; background: rgba(255,255,255,0.015);
                 border-radius: 4px; border-left: 2px solid rgba(255,255,255,0.08); }
    .rule-line .val { color: #f7f8f8; font-weight: 510; }
    .rule-line .mul { color: #ff6b6b; } .rule-line .mul-neg { color: #51cf66; }
    .price-tag { display: inline-block; text-align: center; padding: 5px 2px;
                 background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06);
                 border-radius: 6px; width: 100%; }
    .price-tag .label { font-size: 0.55rem; color: #62666d; text-transform: uppercase; letter-spacing: 0.03em; }
    .price-tag .value { font-size: 0.95rem; font-weight: 590; }
    .price-tag .base { font-size: 0.55rem; color: #62666d; }
    .up { color: #ff6b6b; } .down { color: #51cf66; } .flat { color: #8a8f98; }
    .card-row { display: flex; gap: 6px; }
    .season-row { font-size: 0.76rem; padding: 3px 8px; margin: 1px 0; border-radius: 3px;
                  display: flex; justify-content: space-between; font-family: 'JetBrains Mono', ui-monospace, monospace; }
    .season-row.done { background: rgba(255,255,255,0.015); }
    .W { color: #ff6b6b; font-weight: 590; } .D { color: #f0c040; font-weight: 590; }
    .L { color: #51cf66; font-weight: 590; } .pts { color: #c2ef4e; font-weight: 510; }
    .rank-up { color: #ff6b6b; } .rank-down { color: #51cf66; } .muted { color: #4a4d55; }
    ::-webkit-scrollbar { width: 4px; } ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 2px; }
</style>
""", unsafe_allow_html=True)

CSL_JSON_URL = "https://xxxniconico.github.io/csl-dashboard-2026/dashboard_embed.json"

# 2026赛季CFA扣分处罚（静态数据，避免远程超时）
DEDUCTIONS = {
    "北京国安": 5, "上海申花": 10, "天津津门虎": 10,
    "山东泰山": 6, "上海海港": 5, "武汉三镇": 5,
    "浙江": 5, "河南": 6, "青岛海牛": 7,
}

@st.cache_data(ttl=3600)
def get_optimizer():
    return DynamicPricingOptimizer(revenue_weight=0.6)
def render_seating_chart(tier, pred, r):
    """工体鸟瞰图 — 椭圆弧形分区 + 草坪 + 建筑感"""
    tcolors = {
        "T1":"#4a9e6e","T2":"#5b9bd5","T3":"#e8923a",
        "T4":"#e8c547","T5":"#d4739a","T6":"#b8c45a",
    }
    tlabels = {
        "T1":"四层低价","T2":"四层中价","T3":"混合区",
        "T4":"四层中间","T5":"一层边+二层","T6":"死忠/VIP",
    }
    zones = ["T1","T2","T3","T4","T5","T6"]
    vshare = {"T1":0.337,"T2":0.217,"T3":0.308,"T4":0.027,"T5":0.104,"T6":0.008}
    tpred = {}
    for zt in zones:
        if zt in r.tiers:
            tpred[zt] = int(pred * vshare.get(zt, 0.1))

    def arc_path(cx,cy,rx,ry,a1,a2,irx=None,iry=None):
        irx = irx if irx else rx*0.82; iry = iry if iry else ry*0.82
        r1,r2 = math.radians(a1),math.radians(a2)
        ox,oy = cx+rx*math.cos(r1), cy+ry*math.sin(r1)
        ix,iy = cx+irx*math.cos(r1), cy+iry*math.sin(r1)
        ex,ey = cx+rx*math.cos(r2), cy+ry*math.sin(r2)
        large = 1 if (a2-a1)>180 else 0
        return (f"M {ox:.1f} {oy:.1f} "
                f"L {ix:.1f} {iy:.1f} "
                f"A {irx:.1f} {iry:.1f} 0 {large} 1 "
                f"{cx+irx*math.cos(r2):.1f} {cy+iry*math.sin(r2):.1f} "
                f"L {ex:.1f} {ey:.1f} "
                f"A {rx:.1f} {ry:.1f} 0 {large} 0 "
                f"{ox:.1f} {oy:.1f} Z")

    svg_w, svg_h = 540, 460
    cx, cy = svg_w/2, svg_h/2 + 10
    svg = f'<svg viewBox="0 0 {svg_w} {svg_h}" xmlns="http://www.w3.org/2000/svg">'
    svg += f'<defs><filter id="glow"><feGaussianBlur stdDeviation="2" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>'
    svg += f'<rect width="{svg_w}" height="{svg_h}" fill="#0c0d0f"/>'

    # 看台层
    rx_base, ry_base = 200, 160
    # T1: 北看台上层 (北侧, 角度~200-340)
    svg += f'<path d="{arc_path(cx,cy,rx_base*1.05,ry_base*1.05,200,340,rx_base*0.82,ry_base*0.82)}" fill="{tcolors["T1"]}" opacity="0.18" stroke="{tcolors["T1"]}" stroke-width="1" opacity="0.5"/>'
    # T2: 北看台下层 + 部分侧面
    svg += f'<path d="{arc_path(cx,cy,rx_base*0.82,ry_base*0.82,180,350,rx_base*0.64,ry_base*0.64)}" fill="{tcolors["T2"]}" opacity="0.18" stroke="{tcolors["T2"]}" stroke-width="1" opacity="0.5"/>'
    # T3: 东西看台主区 (两侧大弧)
    svg += f'<path d="{arc_path(cx,cy,rx_base,ry_base,50,130)}" fill="{tcolors["T3"]}" opacity="0.18" stroke="{tcolors["T3"]}" stroke-width="1" opacity="0.5"/>'
    svg += f'<path d="{arc_path(cx,cy,rx_base,ry_base,230,310)}" fill="{tcolors["T3"]}" opacity="0.18" stroke="{tcolors["T3"]}" stroke-width="1" opacity="0.5"/>'
    # T4: 四层中间 (南侧小看台)
    svg += f'<path d="{arc_path(cx,cy,rx_base*0.82,ry_base*0.82,130,230,rx_base*0.72,ry_base*0.72)}" fill="{tcolors["T4"]}" opacity="0.18" stroke="{tcolors["T4"]}" stroke-width="1" opacity="0.5"/>'
    # T5: 一层边 + 二层 (南看台周边)
    svg += f'<path d="{arc_path(cx,cy,rx_base*0.95,ry_base*0.95,120,240,rx_base*0.82,ry_base*0.82)}" fill="{tcolors["T5"]}" opacity="0.18" stroke="{tcolors["T5"]}" stroke-width="1" opacity="0.5"/>'
    # T6: 死忠/VIP (南看台核心)
    svg += f'<path d="{arc_path(cx,cy,rx_base*0.64,ry_base*0.64,140,220,rx_base*0.45,ry_base*0.45)}" fill="{tcolors["T6"]}" opacity="0.18" stroke="{tcolors["T6"]}" stroke-width="1" opacity="0.5"/>'

    # 草坪
    svg += f'<ellipse cx="{cx}" cy="{cy}" rx="{rx_base*0.45}" ry="{ry_base*0.45}" fill="#1a3a1a" stroke="#2a5a2a" stroke-width="1"/>'
    svg += f'<line x1="{cx}" y1="{cy-ry_base*0.45}" x2="{cx}" y2="{cy+ry_base*0.45}" stroke="#3a6a3a" stroke-width="1" opacity="0.5"/>'
    svg += f'<circle cx="{cx}" cy="{cy}" r="{ry_base*0.12}" fill="none" stroke="#3a6a3a" stroke-width="1" opacity="0.6"/>'

    # 标签 (手动放置避免重叠)
    label_positions = {
        "T1": (cx, cy-ry_base*0.9),
        "T2": (cx, cy-ry_base*0.7),
        "T3": (cx-rx_base*0.5, cy+5),
        "T4": (cx, cy+ry_base*0.8),
        "T5": (cx+rx_base*0.2, cy+ry_base*0.5),
        "T6": (cx, cy+ry_base*0.55),
    }
    for zt, (lx, ly) in label_positions.items():
        qty = tpred.get(zt, 0)
        c = tcolors.get(zt, "#666")
        svg += f'<text x="{lx}" y="{ly}" fill="{c}" font-size="8" text-anchor="middle" font-family="Inter,sans-serif">{zt} {qty:,}</text>'

    svg += f'<text x="{cx}" y="{cy+4}" fill="#e0e0e0" font-size="11" text-anchor="middle" font-weight="bold">工体</text>'
    svg += f'<text x="{cx}" y="{cy+17}" fill="#888" font-size="7" text-anchor="middle">预测 {pred:,.0f}张</text>'
    svg += '</svg>'
    st.markdown(svg, unsafe_allow_html=True)

def render_home_card(match):
    opp = match["opponent"]; lvl = classify_opponent(opp, match_date=match["date"]); dt = pd.Timestamp(match["date"])
    pt = get_pricing_tier(opp, match_date=match["date"])
    lnames = {"S":"S·德比","A":"A·强队","B":"B·常规","C":"C·普通"}
    st.subheader(f"下一主场：{match['date']} vs {opp}")
    st.caption(f"{lnames.get(lvl,lvl)} | 定价: {PT_LABELS.get(pt,pt)} | {match['round']} | {['周一','周二','周三','周四','周五','周六','周日'][dt.weekday()]}")

    from src.classify import classify_opponent_tier
    tier = classify_opponent_tier(opp, match_date=match["date"])
    base = TIER_BASE.get(tier, 9000)
    ctx = detect_ctx(match, guoan_matches, standings)
    derby = opp in {"上海申花","山东泰山"}
    sat = dt.weekday()==5; late = dt.month>=10; mid = dt.weekday() in [1,2,3]
    lb = ctx.get("lost_bottom",False); hh = ctx.get("heavy_home_loss",False)
    aw = ctx.get("away_winless",False); sr = ctx.get("short_rest",False); ub3 = ctx.get("unbeaten_3",False)
    so = len([m for m in guoan_matches if m["completed"]]) == 0

    prev_matches = [m for m in guoan_matches if m["completed"] and pd.Timestamp(m["date"]) < dt]
    last3 = prev_matches[-3:] if len(prev_matches) >= 3 else prev_matches
    last_home_dates = [pd.Timestamp(m["date"]) for m in prev_matches if m["is_home"]]
    days_since_home = (dt - last_home_dates[-1]).days if last_home_dates else 999

    if last3:
        st.markdown("**近期赛果**")
        rec_html = ""
        for m in last3:
            vs = "vs" if m["is_home"] else "@"
            if m["is_home"]:
                res = "W" if m["hg"]>m["ag"] else "D" if m["hg"]==m["ag"] else "L"
                sc = f"{m['hg']}-{m['ag']}"
            else:
                res = "W" if m["ag"]>m["hg"] else "D" if m["ag"]==m["hg"] else "L"
                sc = f"{m['ag']}-{m['hg']}"
            cls = {"W":"mul","D":"muted","L":"mul-neg"}[res]
            impact = ""
            if m["is_home"] and res=="L" and abs(m["hg"]-m["ag"])>=2:
                idx = prev_matches.index(m) if m in prev_matches else -1
                later = prev_matches[idx+1:] if idx>=0 else []
                has_win = any((lm["is_home"] and lm["hg"]>lm["ag"]) or (not lm["is_home"] and lm["ag"]>lm["hg"]) for lm in later)
                if not has_win:
                    opp_r = standings.get(m["round"],{}).get(m["opponent"],8)
                    if opp_r >= 12:
                        impact = f'<span style="color:#51cf66;font-size:0.65rem"> → lost_bottom (排名#{opp_r}≥12)</span>'
                    else:
                        impact = f'<span style="color:#51cf66;font-size:0.65rem"> → heavy_home_loss (净负{abs(m["hg"]-m["ag"])}球)</span>'
            elif not m["is_home"] and res!="W":
                away_ct = sum(1 for lm in last3 if not lm["is_home"])
                away_wins = sum(1 for lm in last3 if not lm["is_home"] and lm["ag"]>lm["hg"])
                if away_ct>=2 and away_wins==0:
                    impact = f'<span style="color:#51cf66;font-size:0.65rem"> → away_winless ({away_ct}客{away_wins}胜)</span>'
            rec_html += (f'<div style="font-family:JetBrains Mono,ui-monospace;font-size:0.75rem;padding:2px 8px;color:#8a8f98">'
                        f'{m["date"]} {vs} {m["opponent"]} '
                        f'<span class="{cls}">{sc} {res}</span>{impact}'
                        f'</div>')
        st.markdown(rec_html, unsafe_allow_html=True)

    st.markdown("**命中规则 · 上座预测计算链**")

    lb_found = None; hh_found = None
    for m in last3:
        is_loss = (m["is_home"] and m["hg"]<m["ag"]) or (not m["is_home"] and m["ag"]<m["hg"])
        if not is_loss: continue
        opp_r = standings.get(m["round"],{}).get(m["opponent"],8)
        if opp_r >= 12 and not lb_found:
            lb_found = (m["date"], m["opponent"], opp_r)
        if m["is_home"] and abs(m["hg"]-m["ag"])>=2 and not hh_found:
            idx = prev_matches.index(m) if m in prev_matches else -1
            later = prev_matches[idx+1:] if idx>=0 else []
            has_win = any((lm["is_home"] and lm["hg"]>lm["ag"]) or (not lm["is_home"] and lm["ag"]>lm["hg"]) for lm in later)
            if not has_win:
                hh_found = (m["date"], m["opponent"], abs(m["hg"]-m["ag"]))

    rules_triggered = []
    rules_triggered.append(("基值", f"{tier}级 {base:,.0f}张", 1.0,
        f"{tier}级基值来自KMeans聚类均值（S={TIER_BASE['S']:,.0f} A={TIER_BASE['A']:,.0f} B={TIER_BASE['B']:,.0f} C={TIER_BASE['C']:,.0f}）"))
    if ub3:
        rules_triggered.append(("不败", "近3场不败 ×1.00", 1.00, "国安近3场未尝败绩，球迷乐观情绪传导至主场观赛意愿。V5.1网格搜索收敛至中性，效应不显著"))
    if so:
        rules_triggered.append(("揭幕战", f"赛季首个主场 ×1.15", 1.15, "赛季揭幕战球迷关注度高，历史上座溢价约15%。仅本赛季第一个主场触发"))
    if derby:
        if tier=="S":
            rules_triggered.append(("德比", "S级德比不叠加溢价", 1.0, f"申花已是S级最高基值（{TIER_BASE['S']:,}），德比溢价已内嵌在分级中，不再重复"))
        else:
            m=1.05 if tier=="A" else 1.25
            label = "A级德比" if tier=="A" else "德比"
            rules_triggered.append((label, f"{opp} {label}对手 ×{m}", m,
                f"{'A级德比溢价5%' if tier=='A' else '历史数据显示溢价25%'}，S级不叠加"))
    if sat:
        rules_triggered.append(("周六场", "周末上座溢价 ×1.05", 1.05, "周六比赛日球迷时间充裕，V5.1网格搜索最优溢价约5%"))
    if late:
        rules_triggered.append(("赛季末", f"{dt.month}月 战意衰减 ×0.80", 0.80, "10月以后赛季末，若球队已无争冠/保级悬念，上座下滑。乘数0.80"))
    if mid and not lb and not hh:
        rules_triggered.append(("工作日", f"周{'一二三四五六日'[dt.weekday()]} 工作日衰减 ×0.90", 0.90, "周二/三/四工作日影响-10%，乘数0.90。不与lost_bottom/heavy叠加"))
    if aw:
        away3 = [m for m in last3 if not m["is_home"]]
        rules_triggered.append(("客场不胜", f"近3场{len(away3)}客0胜 ×0.95", 0.95, f"近3场中{len(away3)}个客场无胜，球迷对客场表现失望传导至主场观赛意愿。跨赛季网格搜索最优乘数0.95"))
    if lb and lb_found:
        rules_triggered.append(("输保级队", f"{lb_found[0]} {lb_found[1]} 排名#{lb_found[2]}≥12 ×0.65", 0.65, f"最近3场中输给排名≥12的保级队（{lb_found[1]} #{lb_found[2]}），对球迷信心打击极大。乘数0.65；对A/S级对手降至×0.78（复仇效应）。后续需赢球抵消"))
    elif hh and hh_found:
        rules_triggered.append(("主场惨败", f"{hh_found[0]} vs {hh_found[1]} 净负{hh_found[2]}球 ×0.85", 0.85, f"最近3场中主场净负≥2球（vs {hh_found[1]} -{hh_found[2]}球），球迷失望情绪压制下场上座。惩罚0.85，轻于输保级队"))
    if sr and not lb and not hh:
        if last_home_dates:
            prev_home_date = last_home_dates[-1].strftime('%m/%d')
            rules_triggered.append(("双赛周", f"距上一主场 {prev_home_date} {days_since_home}天 ×0.75", 0.75, f"距上一主场仅{days_since_home}天，双赛周疲劳导致观赛意愿下降。≤4天触发，乘数0.75。不与lost_bottom/heavy叠加"))
        else:
            rules_triggered.append(("双赛周", "双赛周疲劳 ×0.75", 0.75, "双赛周疲劳导致观赛意愿下降。≤4天触发。不与lost_bottom/heavy叠加"))

    final_mult = 1.0
    for name, desc, m_val, detail in rules_triggered[1:]:
        final_mult *= m_val
    final_mult = max(final_mult, PENALTY_FLOOR)
    raw_pred = min(base * final_mult, 20000)

    # 校准因子（EMA 已禁用，固定 1.0）
    _cal = get_calibration()
    _cal_factor = _cal["tier"].get(tier, 1.0)
    pred = raw_pred * _cal_factor

    if len(rules_triggered)==1:
        rules_triggered.append(("—", "无触发规则", 1.0, "无特殊情境触发，直接使用基值预测"))

    running = base
    for i, (name, desc, m_val, detail) in enumerate(rules_triggered):
        if i>0: running *= m_val
        is_up = m_val > 1.0; is_down = m_val < 1.0 and i > 0
        clr = "#ff6b6b" if is_up else "#51cf66" if is_down else "#c2ef4e"
        mul_str = f"<span style='color:{clr};font-weight:590'>×{m_val:.2f}</span>" if i>0 else ""
        bar_color = "#ff6b6b" if running > base else "#51cf66"
        st.markdown(f"""<div style="margin:2px 0;padding:4px 10px;background:rgba(255,255,255,0.015);border-left:2px solid {clr};border-radius:0 4px 4px 0">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span style="font-size:0.82rem;font-weight:510;color:#f7f8f8">{name} {mul_str}</span>
          <span style="font-family:JetBrains Mono,ui-monospace;font-size:0.82rem;color:{bar_color};font-weight:510">{running:,.0f} 张</span>
        </div>
        <div style="font-size:0.65rem;color:#8a8f98;margin-top:1px;line-height:1.4">{detail}</div>
        </div>""", unsafe_allow_html=True)

    bar_pct = min(pred / 20000 * 100, 100)
    _cal_note = f" · EMA校准 ×{_cal_factor:.4f}" if abs(_cal_factor - 1.0) > 0.001 else ""
    st.markdown(f"""<div style="padding:8px 12px;margin-top:6px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:6px">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <span style="font-size:0.75rem;color:#62666d">累计乘数 <span style="color:#f7f8f8;font-weight:590">{final_mult:.3f}</span> × 基值 {base:,.0f}{_cal_note} =</span>
      <span style="font-size:1.1rem;font-weight:590;color:#f7f8f8">预测 {pred:,.0f} 张</span>
    </div>
    <div style="margin-top:4px;height:3px;background:rgba(255,255,255,0.06);border-radius:2px">
      <div style="width:{bar_pct}%;height:3px;background:#ff6b6b;border-radius:2px"></div>
    </div>
    <div style="font-size:0.6rem;color:#62666d;margin-top:2px">惩罚底线 ×{PENALTY_FLOOR} · 上限 20,000张</div>
    </div>""", unsafe_allow_html=True)

    st.markdown("**定价建议**")
    st.caption("规则引擎预测 + 分层组合策略优化 · 情景推演未经验证")

    # 策略选择
    strategy_mode = st.radio("策略模式", ["auto", "balanced"], index=0, horizontal=True,
                              format_func=lambda x: "自动（动态权重）" if x=="auto" else "平衡（T1-T3降价抢量+T4-T6涨价补收入）",
                              key=f"strategy_{opp}")
    
    args = {'derby':derby,'saturday':sat,'late_season':late,'midweek':mid,
            'away_winless':aw,'lost_bottom':lb,'heavy_home_loss':hh,'short_rest':sr,'season_opener':so,'unbeaten_3':ub3}
    
    r = optimizer.optimize(opp, strategy=strategy_mode, **args)

    rw = r.revenue_weight; aw = r.attendance_weight
    if strategy_mode == 'balanced':
        strategy_label = "平衡策略（跨档补贴）"
        strategy_color = "#c2ef4e"
    else:
        strategy_label = "收入优先" if rw>=0.7 else "上座优先" if rw<=0.3 else "均衡优化"
        strategy_color = "#ff6b6b" if rw>=0.7 else "#51cf66" if rw<=0.3 else "#f0c040"
    tier_roles = {"T1":"量价锚·低价抢量","T2":"量价支撑","T3":"弹性区·双向均衡",
                  "T4":"四层中间·弹性跟随","T5":"收入锚·高价创收","T6":"收入锚·VIP"}

    st.markdown(f"""<div style="display:flex;gap:12px;flex-wrap:wrap;margin:8px 0">
    <div style="flex:1;min-width:200px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:8px;padding:10px 14px">
      <div style="font-size:0.62rem;color:#62666d;text-transform:uppercase;letter-spacing:0.04em">策略模式</div>
      <div style="font-size:1.1rem;font-weight:590;color:{strategy_color};margin-top:2px">{strategy_label}</div>
      <div style="font-size:0.65rem;color:#62666d;margin-top:3px">收入权重 {rw:.0%} · 上座权重 {aw:.0%}</div>
    </div>
    <div style="flex:1;min-width:200px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:8px;padding:10px 14px">
      <div style="font-size:0.62rem;color:#62666d;text-transform:uppercase;letter-spacing:0.04em">对手分级</div>
      <div style="font-size:1.1rem;font-weight:590;color:#f7f8f8;margin-top:2px">{lvl}级 · {lnames.get(lvl,'?')}</div>
      <div style="font-size:0.65rem;color:#62666d;margin-top:3px">定价: {PT_LABELS.get(pt,pt)} · T1=¥{r.tiers['T1'].base_price:,.0f}</div>
    </div>
    <div style="flex:1;min-width:200px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:8px;padding:10px 14px">
      <div style="font-size:0.62rem;color:#62666d;text-transform:uppercase;letter-spacing:0.04em">预测阈值</div>
      <div style="font-size:1.1rem;font-weight:590;color:#f7f8f8;margin-top:2px">{pred:,.0f} 张</div>
      <div style="font-size:0.65rem;color:#62666d;margin-top:3px">≥11K收入优先 · ≤7.5K上座优先 · 中间线性过渡</div>
    </div>
    </div>""", unsafe_allow_html=True)

    st.markdown("**档位调价策略**")
    rows_html = ""
    for zt in ZONE_TIERS:
        tr = r.tiers[zt]
        dp = (tr.optimal_price/tr.base_price-1)*100 if tr.base_price>0 else 0
        dq = (tr.predicted_qty/tr.base_qty-1)*100 if tr.base_qty>0 else 0
        eps = optimizer.elasticity[r.opponent_level][zt]
        role = tier_roles.get(zt, "")
        frozen = tr.is_frozen
        if frozen: strategy = "🔒 锁价"
        elif zt in ("T1","T2"):
            if rw <= 0.3: strategy = "↓ 低价抢量·目标降20%"
            elif rw <= 0.6: strategy = "↓ 温和降价·目标降10%"
            else: strategy = "→ 强队不降"
        elif zt in ("T5","T6"):
            if rw >= 0.7: strategy = "↑ 高价创收·目标涨20%"
            elif rw >= 0.4: strategy = "↑ 温和涨价·目标涨10%"
            else: strategy = "→ 弱队不涨"
        elif zt in ("T3", "T4"):
            if rw <= 0.3: strategy = "↓ 弹性降价·目标降15%"
            elif rw >= 0.7: strategy = "↑ 弹性涨价·目标涨15%"
            else:
                ratio = 0.85 + 0.30 * (rw - 0.3) / 0.4
                strategy = f"→ 线性调整·{ratio:.0%}基准"
        else: strategy = "—"
        dp_color = "#ff6b6b" if dp > 0.5 else "#51cf66" if dp < -0.5 else "#8a8f98"
        dq_color = "#ff6b6b" if dq > 0 else "#51cf66" if dq < -0.5 else "#8a8f98"
        dp_str = f'<span style="color:{dp_color}">{dp:+.0f}%</span>' if abs(dp) > 1 else "—"
        dq_str = f'<span style="color:{dq_color}">{dq:+.1f}%</span>' if abs(dq) > 0.5 else "—"
        rows_html += (
            f'<tr><td style="font-weight:510;color:#f7f8f8">{zt}</td>'
            f'<td style="color:#8a8f98;font-size:0.62rem">{role}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">ε={eps:.2f}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace;color:#8a8f98">¥{tr.base_price:,.0f}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace;color:#f7f8f8;font-weight:510">¥{tr.optimal_price:,.0f}</td>'
            f'<td>{dp_str}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">{tr.base_qty:,.0f}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">{tr.predicted_qty:,.0f}</td>'
            f'<td>{dq_str}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">¥{tr.revenue/10000:.2f}万</td>'
            f'<td style="font-size:0.62rem;color:#8a8f98">{strategy}</td></tr>')
    total_dq = (r.total_attendance/r.base_attendance-1)*100 if r.base_attendance>0 else 0
    base_rev = r.base_revenue; opt_rev = r.total_revenue
    rev_delta = opt_rev - base_rev
    rev_color = "#ff6b6b" if rev_delta > 0 else "#51cf66"
    att_color = "#ff6b6b" if total_dq > 0 else "#51cf66"
    rows_html += (
        f'<tr style="border-top:1px solid rgba(255,255,255,0.08);font-weight:510">'
        f'<td colspan="4" style="color:#8a8f98">合计</td><td style="color:#f7f8f8">—</td><td>—</td>'
        f'<td style="color:#f7f8f8">{r.base_attendance:,.0f}</td>'
        f'<td style="color:#f7f8f8">{r.total_attendance:,.0f}</td>'
        f'<td><span style="color:{att_color}">{total_dq:+.1f}%</span></td>'
        f'<td style="color:#f7f8f8">¥{opt_rev/10000:.1f}万</td><td></td></tr>')
    st.markdown(
        f'<table class="history-table" style="font-size:0.68rem">'
        f'<thead><tr><th>档位</th><th>角色</th><th>弹性</th><th>基准价</th><th>优化价</th><th>Δ价</th>'
        f'<th>基准量</th><th>优化量</th><th>Δ量</th><th>收入</th><th>策略</th></tr></thead>'
        f'<tbody>{rows_html}</tbody></table>', unsafe_allow_html=True)

    st.markdown("**量化逻辑**")
    st.markdown(f"""<div style="font-size:0.72rem;color:#8a8f98;line-height:1.6;padding:8px 12px;
    background:rgba(255,255,255,0.015);border:1px solid rgba(255,255,255,0.05);border-radius:6px">
    <strong style="color:#f7f8f8">目标函数：</strong>max <span style="color:#ff6b6b">{rw:.0%}×收入</span> + <span style="color:#51cf66">{aw:.0%}×上座价值</span><br>
    <strong style="color:#f7f8f8">需求模型：</strong>q<sub>opt</sub> = q<sub>0</sub> × (p/p<sub>0</sub>)<sup>−ε</sup> · 恒定弹性 · 降价保护(q<sub>opt</sub>≥q<sub>0</sub>)<br>
    <strong style="color:#f7f8f8">份额分配：</strong>T1 33.7% · T2 21.7% · T3 30.8% · T4 2.7% · T5 10.4% · T6 0.8%（2025历史）<br>
    <strong style="color:#f7f8f8">约束条件：</strong>档位间距≥10% · 变动≥±5%生效 · 降价不减量 · 收入底线仅rw&gt;0.7生效<br>
    <strong style="color:#f7f8f8">情景对比：</strong>
    基准收入 ¥{base_rev/10000:.1f}万 → 优化收入 <span style="color:{rev_color}">¥{opt_rev/10000:.1f}万 ({rev_delta/base_rev*100:+.1f}%)</span> · 
    基准上座 {r.base_attendance:,.0f} → 优化上座 <span style="color:{att_color}">{r.total_attendance:,.0f} ({total_dq:+.1f}%)</span>
    </div>""", unsafe_allow_html=True)

    pc = st.columns(6)
    for i,zt in enumerate(ZONE_TIERS):
        tr = r.tiers[zt]; dp = (tr.optimal_price/tr.base_price-1)*100 if tr.base_price>0 else 0
        cls = "up" if dp>0.5 else "down" if dp<-0.5 else "flat"
        arrow = "↑" if dp>0.5 else "↓" if dp<-0.5 else ""
        lock = "🔒" if tr.is_frozen else ""
        with pc[i]:
            st.markdown(f'<div class="price-tag"><div class="label">{zt} {lock}</div>'
                       f'<div class="value {cls}">¥{tr.optimal_price:,.0f} {arrow}</div>'
                       f'<div class="base">基准¥{tr.base_price:,.0f}</div></div>', unsafe_allow_html=True)

    st.divider()

@st.cache_data(ttl=300)
def get_actual(m):
    from src.match_notes import get_adjusted_actual
    pq = ROOT/"data/processed/all_unified.parquet"
    if not pq.exists(): return 0
    df = pd.read_parquet(pq)
    df["数量"] = pd.to_numeric(df["数量"])
    df["实际支付价格"] = pd.to_numeric(df["实际支付价格"])
    df["is_home"] = df["is_home"] == "True"
    csl = df[(df["competition"]=="CSL")&(df["is_partial"] == "False")&(df["is_bundle"] == "False")]
    for mid in csl["match_id"].unique():
        md = csl[csl["match_id"]==mid]
        if str(md["match_date"].iloc[0]).startswith(m["date"]):
            raw = int(md["数量"].sum())
            return get_adjusted_actual(mid, raw)
    return 0

@st.cache_data(ttl=300)
def _get_zone_qtys(m):
    pq = ROOT/"data/processed/all_unified.parquet"
    if not pq.exists(): return {}
    df = pd.read_parquet(pq)
    df["数量"] = pd.to_numeric(df["数量"])
    df["实际支付价格"] = pd.to_numeric(df["实际支付价格"])
    df["is_home"] = df["is_home"] == "True"
    csl = df[(df["competition"]=="CSL")&(df["is_partial"] == "False")&(df["is_bundle"] == "False")]
    zm = {s:zt for zt,secs in ZONE_SECTIONS.items() for s in secs}
    for mid in csl["match_id"].unique():
        md = csl[csl["match_id"]==mid]
        if str(md["match_date"].iloc[0]).startswith(m["date"]):
            md = md.copy()
            md["zt"] = md["section"].astype(str).map(zm)
            result = {}
            for zt in ZONE_TIERS:
                result[zt] = int(md[md["zt"]==zt]["数量"].sum())
            return result
    return {}

all_matches, rounds, deductions = load_csl_data()
# Filter: 国安 only, CSL only
guoan_matches = get_guoan_matches(all_matches)
guoan_matches = [m for m in guoan_matches if 'cfl_fixtures_api' in m.get('source','') or 'wikipedia' in m.get('source','')]
standings = rounds  # alias for backward compat
if not guoan_matches:
    st.warning("数据加载失败，请刷新页面重试")
    st.stop()
price_matrix = build_price_matrix()
elasticity_matrix = build_elasticity_matrix()
optimizer = get_optimizer()
# calibrator removed

completed = [m for m in guoan_matches if m["completed"] and m["date"].startswith("2026")]
home_done = [m for m in completed if m["is_home"]]
total_pts = sum(3 if (m["is_home"] and m["hg"]>m["ag"]) or (not m["is_home"] and m["ag"]>m["hg"]) else 1 if m["hg"]==m["ag"] else 0 for m in completed)
guoan_ded = deductions.get("北京国安",0)
def _round_num(rnd: str) -> int:
    try: return int(str(rnd).replace("第","").replace("轮",""))
    except: return 0

latest_rnd = max(standings.keys(), key=_round_num, default=None) if standings else None
guoan_rank = standings.get(latest_rnd, {}).get("北京国安", "?") if latest_rnd else "?"

next_match = next((m for m in guoan_matches if not m["completed"] and m["date"].startswith("2026")), None)
next_home = next((m for m in guoan_matches if not m["completed"] and m["is_home"] and m["date"].startswith("2026")), None)
home_w = sum(1 for m in home_done if m["hg"]>m["ag"])
home_d = sum(1 for m in home_done if m["hg"]==m["ag"])
home_l = sum(1 for m in home_done if m["hg"]<m["ag"])

st.markdown(f"""
<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0">
  <div><h1>⚽ 北京国安 · 动态定价</h1></div>
  <div class="state-bar"><strong>#{guoan_rank}</strong> {total_pts}分 <span style="color:#62666d">(扣{guoan_ded}→有效{total_pts-guoan_ded})</span> | 主场 {home_w}-{home_d}-{home_l} | 已赛{len(completed)}/30轮</div>
</div>""", unsafe_allow_html=True)

recent5 = completed[-5:]
form_icons = []
for m in recent5:
    res = "W" if (m["is_home"] and m["hg"]>m["ag"]) or (not m["is_home"] and m["ag"]>m["hg"]) else "D" if m["hg"]==m["ag"] else "L"
    form_icons.append(f'<span class="{res}">{res}</span>')
st.caption("近5场: " + " · ".join(form_icons), unsafe_allow_html=True)

left, right = st.columns([6.5, 3.5])

with left:
    st.divider()
    if next_match and next_match["is_home"]:
        render_home_card(next_match)
    elif next_match and not next_match["is_home"]:
        st.info(f"📅 下一场 {next_match['date']} @ {next_match['opponent']} 为**客场**，无散票定价需求")
        if next_home:
            st.caption(f"下一个主场：{next_home['date']} vs {next_home['opponent']} ({next_home['round']})")
            render_home_card(next_home)
    elif next_home:
        render_home_card(next_home)

    st.divider()
    st.subheader("赛季回望")
    if home_done:
        rows=[]; preds=[]; actuals=[]
        for m in home_done:
            a = get_actual(m)
            if a==0: continue
            ctx = detect_ctx(m, guoan_matches, standings)
            dt = pd.Timestamp(m["date"])
            opp = m["opponent"]
            p = rule_predict(opp, derby=opp in {"上海申花","山东泰山"},
                            saturday=dt.weekday()==5, late_season=dt.month>=10, midweek=dt.weekday() in [1,2,3],
                            summer=dt.month in [7,8],
                            season_opener=(m==home_done[0]),
                            match_year=m["date"][:4],
                            **{k:ctx.get(k,False) for k in ['away_winless','lost_bottom','heavy_home_loss','short_rest','unbeaten_3']})
            preds.append(p); actuals.append(a)
            rows.append({"日期":m["date"],"对手":opp,"预测":f"{p:,.0f}","实际":f"{a:,.0f}","误差":f"{p-a:+,.0f}","APE":f"{abs(p-a)/a*100:.1f}%"})
        st.markdown(pd.DataFrame(rows).to_html(index=False, border=0, justify='center'), unsafe_allow_html=True)
        if preds: st.metric("累积MAE", f"{np.mean(np.abs(np.array(preds)-np.array(actuals))):,.0f}张")

    if home_done:
        st.divider()
        st.subheader("历史定价建议（情景假设）")
        st.caption("规则引擎预测 + 分层组合策略优化 · 情景推演未经验证")
        for i, m in enumerate(home_done):
            if i > 0:
                st.markdown('<hr style="margin:10px 0;border-color:rgba(255,255,255,0.04)">', unsafe_allow_html=True)
            a = get_actual(m)
            if a==0: continue
            opp=m["opponent"]; dt=pd.Timestamp(m["date"])
            ctx=detect_ctx(m, guoan_matches, standings)
            zone_qty=_get_zone_qtys(m)
            from src.classify import classify_opponent_tier
            mt=classify_opponent_tier(opp, match_date=match_date)
            lvl = classify_opponent(opp, match_date=match_date)
            _pm = build_price_matrix()
            pt_hist = get_pricing_tier(opp, match_date=match_date)
            prices_fixed = {zt: _pm[pt_hist][zt] for zt in ZONE_TIERS}
            fixed_rev=sum(zone_qty.get(zt,0)*prices_fixed[zt] for zt in ZONE_TIERS)
            pred_args={'derby':opp in {"上海申花","山东泰山"},
                       'saturday':dt.weekday()==5,'late_season':dt.month>=10,
                       'midweek':dt.weekday() in [1,2,3],'summer':dt.month in [7,8],
                       'season_opener':(m==home_done[0]),
                       'match_year':m["date"][:4],
                       **{k:ctx.get(k,False) for k in ['away_winless','lost_bottom','heavy_home_loss','short_rest','unbeaten_3']}}
            r=optimizer.optimize(opp, **pred_args)
            rw = r.revenue_weight; aw = r.attendance_weight
            if rw >= 0.7: strat_label, strat_color = "收入优先", "#ff6b6b"
            elif rw <= 0.3: strat_label, strat_color = "上座优先", "#51cf66"
            else: strat_label, strat_color = "均衡优化", "#f0c040"
            ups = [zt for zt in ZONE_TIERS if r.tiers[zt].optimal_price > r.tiers[zt].base_price * 1.01]
            downs = [zt for zt in ZONE_TIERS if r.tiers[zt].optimal_price < r.tiers[zt].base_price * 0.99]
            frozen = [zt for zt in ZONE_TIERS if r.tiers[zt].is_frozen]
            rules_parts = []
            if pred_args.get('derby'): rules_parts.append("德比溢价")
            if pred_args.get('saturday'): rules_parts.append("周六场")
            if pred_args.get('midweek'): rules_parts.append("工作日")
            if pred_args.get('late_season'): rules_parts.append("赛季末衰减")
            if pred_args.get('lost_bottom'): rules_parts.append("输保级队惩罚")
            if pred_args.get('heavy_home_loss'): rules_parts.append("主场惨败惩罚")
            if pred_args.get('away_winless'): rules_parts.append("客场不胜")
            if pred_args.get('short_rest'): rules_parts.append("双赛周疲劳")
            if pred_args.get('season_opener'): rules_parts.append("揭幕战溢价")
            desc_lines = []
            desc_lines.append(f"**策略：{strat_label}**（预测 {r.predicted_total:,.0f} 张 → 收入权重 {rw:.0%} 上座权重 {aw:.0%}）")
            if rules_parts: desc_lines.append(f"触发规则：{' · '.join(rules_parts)}")
            else: desc_lines.append("触发规则：无特殊规则，基值预测")
            if ups: desc_lines.append(f"↑ 涨价档位：{' '.join(ups)}（高价创收，目标涨10-20%）")
            if downs: desc_lines.append(f"↓ 降价档位：{' '.join(downs)}（低价抢量，目标降10-25%）")
            if frozen: desc_lines.append(f"🔒 锁价档位：{' '.join(frozen)}")
            # 预期效果：优化 vs 基准（同模型基线对比，不含实际数据）
            rev_delta_model = r.total_revenue - r.base_revenue
            att_delta_pct = (r.total_attendance / r.base_attendance - 1) * 100 if r.base_attendance > 0 else 0
            if rev_delta_model > 0:
                desc_lines.append(f"预期效果：增收 ¥{rev_delta_model/10000:+.1f}万（{rev_delta_model/r.base_revenue*100:+.1f}%），上座 {r.total_attendance:,.0f}（{'↑' if att_delta_pct>0 else '↓'}{abs(att_delta_pct):.0f}%）")
            else:
                desc_lines.append(f"预期效果：以价换量，增收 ¥{rev_delta_model/10000:+.1f}万，上座 {r.total_attendance:,.0f}（{'↑' if att_delta_pct>0 else '↓'}{abs(att_delta_pct):.0f}%）")
            strategy_html = f"""<div style="font-size:0.7rem;color:#8a8f98;line-height:1.5;padding:6px 10px;
            margin:6px 0;background:rgba(255,255,255,0.015);border:1px solid rgba(255,255,255,0.05);border-radius:6px;
            border-left:3px solid {strat_color}">
            {'<br>'.join(desc_lines)}
            </div>"""
            st.caption(f"{m['date']} vs {opp}（{lvl}级 · {mt}分级 · 定价:{PT_LABELS.get(pt_hist,pt_hist)}）")
            st.markdown(strategy_html, unsafe_allow_html=True)
            rows_html = ""
            total_fixed = 0; total_scenario = 0
            total_pred_qty = 0; total_actual_qty = 0
            for zt in ZONE_TIERS:
                tr=r.tiers[zt]
                dp=(tr.optimal_price/tr.base_price-1)*100 if tr.base_price>0 else 0
                actual_z=zone_qty.get(zt,0)
                actual_rev=actual_z*prices_fixed[zt]
                total_fixed += actual_rev; total_scenario += tr.revenue
                total_pred_qty += tr.base_qty; total_actual_qty += actual_z
                dp_color = "#51cf66" if dp < -0.5 else "#ff6b6b" if dp > 0.5 else "#8a8f98"
                dp_str = f'<span style="color:{dp_color}">{dp:+.0f}%</span>' if abs(dp) > 1 else ""
                rows_html += (f'<tr><td>{zt}</td><td>¥{tr.base_price:,.0f}</td>'
                             f'<td>¥{tr.optimal_price:,.0f} {dp_str}</td>'
                             f'<td>{tr.base_qty:,.0f}</td><td>{actual_z:,}</td>'
                             f'<td>¥{tr.revenue/10000:.2f}万</td><td>¥{actual_rev/10000:.2f}万</td></tr>')
            rev_delta_model = r.total_revenue - r.base_revenue
            rev_color = "#ff6b6b" if rev_delta_model > 0 else "#51cf66"
            rev_sign = "+" if rev_delta_model > 0 else ""
            rev_delta_str = f'<span style="color:{rev_color}">{rev_sign}¥{rev_delta_model/10000:.1f}万</span>'
            rows_html += (f'<tr style="border-top:1px solid rgba(255,255,255,0.08);font-weight:510">'
                         f'<td colspan="3" style="color:#8a8f98">合计</td>'
                         f'<td style="color:#f7f8f8">{total_pred_qty:,.0f}</td>'
                         f'<td style="color:#f7f8f8">{total_actual_qty:,}</td>'
                         f'<td style="color:#f7f8f8">¥{total_scenario/10000:.1f}万</td>'
                         f'<td style="color:#f7f8f8">¥{total_fixed/10000:.1f}万</td></tr>')
            st.markdown(f'<table class="history-table"><thead><tr><th>档位</th><th>基准价</th><th>优化价</th><th>场景量</th><th>实际量</th><th>场景收入</th><th>实际收入</th></tr></thead><tbody>{rows_html}</tbody></table>', unsafe_allow_html=True)
            st.caption(f"优化效果 {rev_delta_str}（vs 基准价模型收入 ¥{r.base_revenue/10000:.1f}万）| 实际收入 ¥{total_fixed/10000:.1f}万（仅供参考，未验证）", unsafe_allow_html=True)

with right:
    st.subheader("赛季全览")
    cum_pts=0; prev_rank=None
    for m in guoan_matches:
        if not m["date"].startswith("2026"): continue
        rnd=m["round"]; ds=m["date"][5:]; opp=m["opponent"]; vs="vs" if m["is_home"] else "@ "
        if m["completed"]:
            if m["is_home"]: res="W" if m["hg"]>m["ag"] else "D" if m["hg"]==m["ag"] else "L"; sc=f"{m['hg']}-{m['ag']}"
            else: res="W" if m["ag"]>m["hg"] else "D" if m["ag"]==m["hg"] else "L"; sc=f"{m['ag']}-{m['hg']}"
            cum_pts+=3 if res=="W" else 1 if res=="D" else 0
            rank=standings.get(rnd,{}).get("北京国安","?")
            rd=""
            if prev_rank and isinstance(rank,int) and isinstance(prev_rank,int):
                if rank<prev_rank: rd=f'<span class="rank-up">↑{prev_rank-rank}</span>'
                elif rank>prev_rank: rd=f'<span class="rank-down">↓{rank-prev_rank}</span>'
            prev_rank=rank
            st.markdown(f'<div class="season-row done"><span style="color:#62666d;width:55px">{rnd} {ds}</span><span style="width:80px">{vs} {opp}</span><span style="width:45px;text-align:center">{sc}</span><span class="{res}" style="width:20px;text-align:center">{res}</span><span class="pts" style="width:40px;text-align:right">{cum_pts}分</span><span style="width:50px;text-align:right">#{rank} {rd}</span></div>', unsafe_allow_html=True)
        else:
            eff=cum_pts-guoan_ded
            st.markdown(f'<div class="season-row"><span class="muted" style="width:55px">{rnd} {ds}</span><span class="muted" style="width:80px">{vs} {opp}</span><span class="muted" style="width:45px;text-align:center">——</span><span class="muted" style="width:20px;text-align:center">-</span><span style="color:#8a8f98;width:40px;text-align:right">{cum_pts}分</span><span class="muted" style="width:50px;text-align:right">(有效{eff})</span></div>', unsafe_allow_html=True)

st.caption("V7 · Linear暗色 · 仅主场预测")