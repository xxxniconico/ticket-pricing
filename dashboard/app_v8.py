"""
国安票务动态定价看板 V8 — 决策工作台
Linear暗色风格 · Tab分区 · What-If沙盒 · 不确定性可视化
"""
import sys, json, math
from pathlib import Path
from datetime import datetime
from collections import defaultdict
# Ensure ticket-pricing root is on path for 'dashboard' package imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd, numpy as np
import streamlit as st
from dashboard.seating_chart import render_gongti_seating, render_gongti_heatmap, _fill_color
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
    if Path(_fp).exists():
        fm.fontManager.addfont(str(_fp))
        _CN_FONT_NAME = fm.FontProperties(fname=str(_fp)).get_name()
        break

if _CN_FONT_NAME is None:
    # 尝试已安装的系统字体
    for _name in ['WenQuanYi Micro Hei', 'WenQuanYi Zen Hei', 'Noto Sans CJK SC',
                   'SimHei', 'Microsoft YaHei', 'Noto Sans SC']:
        if any(_name.lower() in str(f).lower() for f in fm.fontManager.ttflist):
            _CN_FONT_NAME = _name
            break

if _CN_FONT_NAME:
    matplotlib.rcParams["font.sans-serif"] = [_CN_FONT_NAME, "DejaVu Sans"]
    # 强制重建字体缓存
    fm._load_fontmanager(try_read_cache=False)
else:
    matplotlib.rcParams["font.sans-serif"] = ["DejaVu Sans"]

matplotlib.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.rule_engine import predict_calibrated as rule_predict, TIER_BASE, MULTIPLIERS, PENALTY_FLOOR, get_calibration, update as rule_update
from src.dynamic_optimizer import DynamicPricingOptimizer
from src.pricing_v5 import ZONE_TIERS, ZONE_SECTIONS, get_pricing_tier, build_price_matrix, build_elasticity_matrix, get_zone_bounds, get_zone_sections
from src.classify import classify_opponent_tier, DERBY_RIVALS
from src.csl_context import load_csl_data, get_guoan_matches, detect_ctx

st.set_page_config(page_title="国安票务 V8", page_icon="⚽", layout="wide")

# 防白屏闪烁: Streamlit 加载 dark CSS 前抢先设黑底
st.markdown("""
<style>
  @media (prefers-color-scheme: dark) {
    body, .stApp, .main { background-color: #0c0d0f !important; }
  }
  .stApp { background-color: #0c0d0f; }
</style>
""", unsafe_allow_html=True)

# ── Constants ───────────────────────────────────────────
PT_LABELS = {
    "S_S": "S·德比定价", "S_A": "A·标准定价", "S_Aminus": "A·降价",
    "S_B": "B·标准定价", "S_C": "C·标准定价", "S_Cminus": "C·降价",
}
DEDUCTIONS = {
    "北京国安": 5, "上海申花": 10, "天津津门虎": 10, "山东泰山": 6,
    "上海海港": 5, "武汉三镇": 5, "浙江": 5, "河南": 6, "青岛海牛": 7,
}
WHATIF_PRESETS = {
    "悲观（-20%）": 0.80,
    "乐观（+15%）": 1.15,
}
TIER_LABELS = {"S": "S·德比", "A": "A·强队", "B": "B·常规", "C": "C·普通"}
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# ── Team Logo Helpers ─────────────────────────────────────
import base64 as _b64
_ASSETS = Path(__file__).parent / "assets"
_TEAM_LOGOS_DIR = _ASSETS / "team_logos"

# 对手名 → logo 文件名（来自 guoan-dashboard-2026 VI 资产）
TEAM_LOGO_MAP = {
    "上海海港": "a26d9fbb0342e6d54677.png",
    "上海申花": "91469528aeb15c37728e.png",
    "云南玉昆": "e3797059ba59e4acc812.png",
    "北京国安": "fa6ea93628b5de170048.png",
    "大连英博": "f0a1a59f36d308bf4ec8.png",
    "大连英博海发": "f0a1a59f36d308bf4ec8.png",
    "天津津门虎": "ae9884f476371aa26455.png",
    "山东泰山": "41181c23e64739adc012.png",
    "成都蓉城": "a6fb6193c5ad4eaa4945.png",
    "武汉三镇": "2096512a047b9b2844a9.png",
    "河南": "55b135463002a23b35a2.png",
    "浙江": "44ff3b38e0ba2dbd39c2.png",
    "浙江队": "44ff3b38e0ba2dbd39c2.png",
    "浙江俱乐部绿城": "44ff3b38e0ba2dbd39c2.png",
    "深圳新鹏城": "c1a9b19592adae833a30.png",
    "辽宁铁人": "fd56a67c37153dbcac8f.png",
    "重庆铜梁龙": "6a1a42ad7079e24257fa.png",
    "青岛海牛": "c98835007d3801568650.png",
    "青岛西海岸": "6e61285455bb3980745d.png",
    "梅州客家": "41181c23e64739adc012.png",  # fallback
    "沧州雄狮": "c1a9b19592adae833a30.png",  # fallback
    "南通支云": "2096512a047b9b2844a9.png",   # fallback
    "长春亚泰": "ae9884f476371aa26455.png",   # fallback
}
_GUOAN_CREST_B64 = None
_CSL_LOGO_B64 = None
_LOGO_CACHE = {}

def _logo_b64(filename: str) -> str:
    """返回 PNG 文件的 base64 data URI，带缓存。"""
    if filename in _LOGO_CACHE:
        return _LOGO_CACHE[filename]
    path = _TEAM_LOGOS_DIR / filename
    if path.exists():
        with open(path, "rb") as f:
            _LOGO_CACHE[filename] = f"data:image/png;base64,{_b64.b64encode(f.read()).decode()}"
    else:
        _LOGO_CACHE[filename] = ""
    return _LOGO_CACHE[filename]

def team_crest_html(opponent: str, size: str = "sm") -> str:
    """返回对手队徽 <img> 标签，未匹配返回空字符串。size: 'sm'=18px, 'lg'=28px."""
    fname = TEAM_LOGO_MAP.get(opponent)
    if not fname:
        return ""
    b64 = _logo_b64(fname)
    if not b64:
        return ""
    cls = "team-crest-lg" if size == "lg" else "team-crest"
    return f'<img class="{cls}" src="{b64}" alt="{opponent}">'

def guoan_crest_b64() -> str:
    """国安队徽 base64，带缓存。"""
    global _GUOAN_CREST_B64
    if _GUOAN_CREST_B64 is None:
        path = _ASSETS / "guoan_crest.png"
        if path.exists():
            with open(path, "rb") as f:
                _GUOAN_CREST_B64 = f"data:image/png;base64,{_b64.b64encode(f.read()).decode()}"
        else:
            _GUOAN_CREST_B64 = ""
    return _GUOAN_CREST_B64

def csl_logo_b64() -> str:
    """CSL logo base64，带缓存。"""
    global _CSL_LOGO_B64
    if _CSL_LOGO_B64 is None:
        path = _ASSETS / "csl_logo_white.png"
        if path.exists():
            with open(path, "rb") as f:
                _CSL_LOGO_B64 = f"data:image/png;base64,{_b64.b64encode(f.read()).decode()}"
        else:
            _CSL_LOGO_B64 = ""
    return _CSL_LOGO_B64
WATERFALL_DATA = [
    ("2025\n实际", 4591),
    ("赛程\n结构", -650),
    ("升班马\nC级", -200),
    ("其他\n因素", -348),
    ("2026\n预估", 3935),
]

# Global: cross-season rounds dict for detect_ctx
_ctx_rounds = {}

# ── CSS ─────────────────────────────────────────────────
def load_css():
    css_path = Path(__file__).parent / "style.css"
    if css_path.exists():
        with open(css_path) as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

def build_pred_args(match, ctx, overrides=None):
    """从 match dict + context dict 构建预测参数字典。"""
    dt = pd.Timestamp(match["date"])
    opp = match["opponent"]

    args = {
        'derby': opp in DERBY_RIVALS,
        'saturday': dt.weekday() == 5,
        'midweek': dt.weekday() in [1, 2, 3],
        'summer': dt.month in [7, 8],
        'midseason_restart': ctx.get('midseason_restart', False),
        'season_opener': ctx.get('season_opener', False),
        'match_year': match["date"][:4],
        'away_winless': ctx.get('away_winless', False),
        'lost_bottom': ctx.get('lost_bottom', False),
        'heavy_home_loss': ctx.get('heavy_home_loss', False),
        'short_rest': ctx.get('short_rest', False),
        'unbeaten_3': ctx.get('unbeaten_3', False),
    }

    if overrides:
        args.update(overrides)

    return args


def build_rule_labels(pred_args):
    """从 pred_args 构建人类可读的规则标签列表。"""
    labels = []
    if pred_args.get('derby'): labels.append("德比")
    if pred_args.get('saturday'): labels.append("周六")
    if pred_args.get('midweek'): labels.append("工作日")
    if pred_args.get('late_season'): labels.append("赛季末")
    if pred_args.get('lost_bottom'): labels.append("输保级队")
    if pred_args.get('heavy_home_loss'): labels.append("主场惨败")
    if pred_args.get('away_winless_losses'): labels.append("客场连败")
    elif pred_args.get('away_winless'): labels.append("客场不胜")
    if pred_args.get('short_rest'): labels.append("双赛周")
    if pred_args.get('season_opener'): labels.append("揭幕战")
    return labels


# ── Cached Data ─────────────────────────────────────────
@st.cache_data(ttl=3600)
def get_optimizer():
    return DynamicPricingOptimizer(revenue_weight=0.6)

@st.cache_data(ttl=7200)
def load_data():
    all_matches, rounds, deductions = load_csl_data()
    guoan = get_guoan_matches(all_matches)
    guoan = [m for m in guoan if 'cfl_fixtures_api' in m.get('source', '') or 'wikipedia' in m.get('source', '')]
    return all_matches, rounds, guoan

@st.cache_data(ttl=3600)
def _get_csl_parquet():
    """返回过滤后的 CSL parquet DataFrame（去 partial/bundle）。"""
    pq = ROOT / "data/processed/all_unified.parquet"
    if not pq.exists():
        return None
    df = pd.read_parquet(pq)
    return df[(df["competition"] == "CSL") & (~df["is_partial"]) & (~df["is_bundle"])]


@st.cache_data(ttl=300)
def get_actual(m):
    from src.match_notes import get_adjusted_actual
    csl = _get_csl_parquet()
    if csl is None:
        return 0
    for mid in csl["match_id"].unique():
        md = csl[csl["match_id"] == mid]
        if str(md["match_date"].iloc[0]).startswith(m["date"]):
            raw = int(md["数量"].sum())
            return get_adjusted_actual(mid, raw)
    return 0

@st.cache_data(ttl=300)
def _get_zone_qtys(m):
    from src.pricing_v5 import get_zone_sections
    csl = _get_csl_parquet()
    if csl is None:
        return {}
    year = m["date"][:4]
    zm = {s: zt for zt, secs in get_zone_sections(year).items() for s in secs}
    for mid in csl["match_id"].unique():
        md = csl[csl["match_id"] == mid]
        if str(md["match_date"].iloc[0]).startswith(m["date"]):
            md = md.copy()
            md["zt"] = md["section"].astype(str).map(zm)
            result = {}
            for zt in ZONE_TIERS:
                result[zt] = int(md[md["zt"] == zt]["数量"].sum())
            return result
    return {}

@st.cache_data(ttl=300)
def _get_zone_actual_revenue(m):
    """返回每档实际收入（从 parquet 实际支付价格列求和）。"""
    from src.pricing_v5 import get_zone_sections
    csl = _get_csl_parquet()
    if csl is None:
        return {}
    year = m["date"][:4]
    zm = {s: zt for zt, secs in get_zone_sections(year).items() for s in secs}
    for mid in csl["match_id"].unique():
        md = csl[csl["match_id"] == mid]
        if str(md["match_date"].iloc[0]).startswith(m["date"]):
            md = md.copy()
            md["zt"] = md["section"].astype(str).map(zm)
            result = {}
            for zt in ZONE_TIERS:
                result[zt] = float(md[md["zt"] == zt]["实际支付价格"].sum())
            return result
    return {}

# ── Standings Builder ───────────────────────────────────
def build_standings_2026(all_matches):
    ts = defaultdict(lambda: {"p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "pts": 0})
    standings = {}
    for m in sorted([x for x in all_matches if x['date'].startswith('2026')], key=lambda x: x['date']):
        if not m.get('completed'):
            continue
        rnd, h, a = m['round'], m['home'], m['away']
        ts[h]['p'] += 1; ts[a]['p'] += 1
        ts[h]['gf'] += m['hg']; ts[h]['ga'] += m['ag']
        ts[a]['gf'] += m['ag']; ts[a]['ga'] += m['hg']
        if m['hg'] > m['ag']:
            ts[h]['w'] += 1; ts[h]['pts'] += 3; ts[a]['l'] += 1
        elif m['hg'] == m['ag']:
            ts[h]['d'] += 1; ts[a]['d'] += 1; ts[h]['pts'] += 1; ts[a]['pts'] += 1
        else:
            ts[a]['w'] += 1; ts[a]['pts'] += 3; ts[h]['l'] += 1
        rank = [(t, s['p'], s['pts'], s['gf'] - s['ga'], s['gf']) for t, s in ts.items()]
        rank.sort(key=lambda x: (-x[2], -x[3], -x[4]))
        standings[rnd] = {t: i + 1 for i, (t, *_) in enumerate(rank)}
    return standings

def _round_num(r):
    try: return int(str(r).replace("第", "").replace("轮", ""))
    except: return 0

# ── Prediction Computer ─────────────────────────────────
def compute_home_predictions(home_done, guoan_matches):
    """Returns list of (match, prediction, actual, ctx) for completed home games."""
    results = []
    for m in home_done:
        a = get_actual(m)
        if a == 0:
            continue
        ctx = detect_ctx(m, guoan_matches, _ctx_rounds)
        md = pd.Timestamp(m["date"])
        p = rule_predict(
            m["opponent"],
            derby=m["opponent"] in DERBY_RIVALS,
            saturday=md.weekday() == 5,
            midweek=md.weekday() in [1, 2, 3], summer=md.month in [7, 8],
            season_opener=(m == home_done[0]), midseason_restart=ctx.get('midseason_restart', False),
            match_year=m["date"][:4],
            **{k: ctx.get(k, False) for k in ['away_winless', 'lost_bottom', 'heavy_home_loss', 'short_rest', 'unbeaten_3']}
        )
        results.append((m, p, a, ctx))
    return results

# ══════════════════════════════════════════════════════════
#  Tab 1: 下一场预测
# ══════════════════════════════════════════════════════════

def render_kpi_cards(target_match, home_preds, guoan_rank, total_pts, home_w, home_d, home_l, form_str):
    if target_match:
        opp = target_match["opponent"]
        dt = pd.Timestamp(target_match["date"])
        tier = classify_opponent_tier(opp)
        pt = get_pricing_tier(opp)
        opp_label = f"vs {opp}"
        opp_sub = f"{target_match['date']} {WEEKDAYS[dt.weekday()]} · {target_match['round']}"
        tier_label = f"{tier} 级"
        tier_sub = f"定价: {PT_LABELS.get(pt, '?')}"
    else:
        opp_label = "—"
        opp_sub = "暂无未来主场比赛"
        tier_label = "—"
        tier_sub = "—"

    preds_arr = np.array([p for _, p, _, _ in home_preds])
    actuals_arr = np.array([a for _, _, a, _ in home_preds])
    mae = np.mean(np.abs(preds_arr - actuals_arr)) if len(preds_arr) > 0 else 0
    mape = np.mean(np.abs(preds_arr - actuals_arr) / actuals_arr) * 100 if len(preds_arr) > 0 else 0

    cards = [
        ("下一场对手", opp_label, opp_sub),
        ("赛季 MAE", f"{mae:,.0f} 张", f"MAPE {mape:.1f}% · N={len(preds_arr)}"),
        ("收入底线", "93%", "≥ 基准收入 × 93%"),
        ("已赛主场", f"{len(home_preds)}/15 场", f"进度 {len(home_preds)/15:.0%}"),
        ("对手分级", tier_label, tier_sub),
        ("国安排名", f"#{guoan_rank}", f"积分 {total_pts}分"),
        ("主场战绩", f"{home_w}-{home_d}-{home_l}", f"{home_w}胜 {home_d}平 {home_l}负"),
        ("近5场形态", form_str if form_str else "—", "W胜 D平 L负"),
    ]

    cols1 = st.columns(4)
    for i in range(4):
        label, value, sub = cards[i]
        with cols1[i]:
            st.markdown(f"""<div class="kpi-card">
              <div class="kpi-label">{label}</div>
              <div class="kpi-value">{value}</div>
              <div class="kpi-sub">{sub}</div>
            </div>""", unsafe_allow_html=True)

    cols2 = st.columns(4)
    for i in range(4, 8):
        label, value, sub = cards[i]
        with cols2[i - 4]:
            st.markdown(f"""<div class="kpi-card">
              <div class="kpi-label">{label}</div>
              <div class="kpi-value">{value}</div>
              <div class="kpi-sub">{sub}</div>
            </div>""", unsafe_allow_html=True)

    pct = len(home_preds) / 15 * 100
    st.markdown(f"""<div class="progress-line">
      <div class="progress-label"><span>赛季主场进度</span><span>{len(home_preds)}/15</span></div>
      <div class="progress-track"><div class="progress-fill" style="width:{pct}%"></div></div>
    </div>""", unsafe_allow_html=True)
    return mae

def render_recent_results(target_match, guoan_matches, standings):
    dt = pd.Timestamp(target_match["date"])
    prev_matches = [m for m in guoan_matches if m.get("completed") and pd.Timestamp(m["date"]) < dt]
    last3 = prev_matches[-3:] if len(prev_matches) >= 3 else prev_matches
    if not last3:
        return

    st.markdown("**近期赛果**")
    rec_html = ""
    for m in last3:
        vs = "vs" if m["is_home"] else "@"
        if m["is_home"]:
            res = "W" if m["hg"] > m["ag"] else "D" if m["hg"] == m["ag"] else "L"
            sc = f"{m['hg']}-{m['ag']}"
        else:
            res = "W" if m["ag"] > m["hg"] else "D" if m["ag"] == m["hg"] else "L"
            sc = f"{m['ag']}-{m['hg']}"
        cls = {"W": "mul", "D": "muted", "L": "mul-neg"}[res]
        impact = ""
        if m["is_home"] and res == "L" and abs(m["hg"] - m["ag"]) >= 2:
            idx = prev_matches.index(m) if m in prev_matches else -1
            later = prev_matches[idx + 1:] if idx >= 0 else []
            has_win = any(
                (lm["is_home"] and lm["hg"] > lm["ag"]) or (not lm["is_home"] and lm["ag"] > lm["hg"])
                for lm in later
            )
            if not has_win:
                opp_r = standings.get(m["round"], {}).get(m["opponent"], 8)
                if opp_r >= 12:
                    impact = f'<span style="color:#51cf66;font-size:0.65rem"> → lost_bottom (排名#{opp_r}≥12)</span>'
                else:
                    impact = f'<span style="color:#51cf66;font-size:0.65rem"> → heavy_home_loss (净负{abs(m["hg"]-m["ag"])}球)</span>'
        elif not m["is_home"] and res != "W":
            away_ct = sum(1 for lm in last3 if not lm["is_home"])
            away_wins = sum(1 for lm in last3 if not lm["is_home"] and lm["ag"] > lm["hg"])
            if away_ct >= 2 and away_wins == 0:
                impact = f'<span style="color:#51cf66;font-size:0.65rem"> → away_winless ({away_ct}客{away_wins}胜)</span>'
        rec_html += (
            f'<div style="font-family:JetBrains Mono,ui-monospace;font-size:0.75rem;padding:2px 8px;color:#8a8f98">'
            f'{m["date"]} {vs} {m["opponent"]} '
            f'<span class="{cls}">{sc} {res}</span>{impact}</div>'
        )
    st.markdown(rec_html, unsafe_allow_html=True)

def render_rule_pills(rules_triggered):
    EMOJI = {"基值":"📊","不败":"🛡️","揭幕战":"🎉","德比":"🔥","A级德比":"🔥","周六场":"📅",
             "赛季末":"🍂","工作日":"📉","客场不胜":"🚌","客场连败":"🚌","输保级队":"⚠️",
             "主场惨败":"💔","双赛周":"⏱️","暑假":"☀️"}
    pills = []
    for i, (name, desc, m_val, detail) in enumerate(rules_triggered):
        emoji = EMOJI.get(name, "")
        if i == 0:
            pills.append(f'<span class="rule-pill rule-base" title="{detail}">{emoji} {name}</span>')
        elif m_val > 1.0:
            pills.append(f'<span class="rule-pill rule-up" title="{detail}">{emoji} {name} ×{m_val:.2f}</span>')
        elif m_val < 1.0:
            pills.append(f'<span class="rule-pill rule-down" title="{detail}">{emoji} {name} ×{m_val:.2f}</span>')
        else:
            pills.append(f'<span class="rule-pill rule-neutral" title="{detail}">{emoji} {name} ×{m_val:.2f}</span>')
    st.markdown(f'<div style="display:flex;gap:6px;flex-wrap:wrap;margin:8px 0">{"".join(pills)}</div>', unsafe_allow_html=True)

def render_cumulative_bar(base, final_mult, pred, tier, _cal_factor):
    bar_pct = min(pred / 20000 * 100, 100)
    _cal_note = f" · EMA校准 ×{_cal_factor:.4f}" if abs(_cal_factor - 1.0) > 0.001 else ""
    st.markdown(f"""<div style="padding:8px 12px;margin:6px 0;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:6px">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <span style="font-size:0.75rem;color:#62666d">累计乘数 <span style="color:#f7f8f8;font-weight:590">{final_mult:.3f}</span> × 基值 {base:,.0f}{_cal_note} =</span>
        <span style="font-size:1.1rem;font-weight:590;color:#f7f8f8">预测 {pred:,.0f} 张</span>
      </div>
      <div style="margin-top:4px;height:3px;background:rgba(255,255,255,0.06);border-radius:2px">
        <div style="width:{bar_pct}%;height:3px;background:#ff6b6b;border-radius:2px"></div>
      </div>
      <div style="font-size:0.6rem;color:#62666d;margin-top:2px">惩罚底线 ×{PENALTY_FLOOR} · 上限 20,000张</div>
    </div>""", unsafe_allow_html=True)

def render_confidence_bar(pred, mae):
    if mae == 0:
        return
    ci_low = max(0, pred - mae * 1.5)
    ci_high = min(20000, pred + mae * 1.5)
    pct_low = ci_low / 20000 * 100
    pct_pred = pred / 20000 * 100
    pct_high = ci_high / 20000 * 100
    st.markdown(f"""<div class="confidence-bar">
      <div style="font-size:0.75rem;color:#8a8f98">预测上座 <span style="color:#f7f8f8;font-weight:590">{pred:,.0f} 张</span></div>
      <div class="bar-track">
        <div class="bar-ci" style="left:{pct_low}%;width:{pct_high - pct_low}%"></div>
        <div class="bar-marker" style="left:{pct_pred}%"></div>
      </div>
      <div class="ci-labels"><span>悲观 {ci_low:,.0f}</span><span>乐观 {ci_high:,.0f}</span></div>
      <div class="ci-note">基于赛季 MAE {mae:,.0f} 张 · 80% 置信区间</div>
    </div>""", unsafe_allow_html=True)

def render_strategy_card(r, pred_args, actual_revenue=None, actual_attendance=None):
    """渲染策略卡片。优化效果始终 vs 基准预测（决策质量），实际数据仅作参考。"""
    rw, aw = r.revenue_weight, r.attendance_weight
    if rw >= 0.7:
        strat_label, strat_color = "收入优先", "#ff6b6b"
    elif rw <= 0.3:
        strat_label, strat_color = "上座优先", "#51cf66"
    else:
        strat_label, strat_color = "均衡优化", "#f0c040"

    ups = [zt for zt in ZONE_TIERS if r.tiers[zt].optimal_price > r.tiers[zt].base_price * 1.01]
    downs = [zt for zt in ZONE_TIERS if r.tiers[zt].optimal_price < r.tiers[zt].base_price * 0.99]
    frozen = [zt for zt in ZONE_TIERS if r.tiers[zt].is_frozen]

    rules_parts = build_rule_labels(pred_args)

    lines = [f'<strong style="color:#f7f8f8">策略：{strat_label}</strong>（收入权重 {rw:.0%} · 上座权重 {aw:.0%}）']
    lines.append(f'触发规则：{" · ".join(rules_parts) if rules_parts else "无特殊规则，基值预测"}')
    if ups: lines.append(f'<span style="color:#ff6b6b">↑ 涨价档位：{" ".join(ups)}（高价创收）</span>')
    if downs: lines.append(f'<span style="color:#51cf66">↓ 降价档位：{" ".join(downs)}（低价抢量）</span>')
    if frozen: lines.append(f'🔒 锁价档位：{" ".join(frozen)}')

    # 决策质量：始终 vs 基准预测（r.base_* = 未优化时的预测值）
    qty_delta = r.total_attendance - r.base_attendance
    rev_delta_eff = r.total_revenue - r.base_revenue
    att_delta_pct = (r.total_attendance / r.base_attendance - 1) * 100 if r.base_attendance > 0 else 0
    rev_sign = "+" if rev_delta_eff > 0 else ""

    if rw >= 0.7:
        main_metric = f'<span style="color:{"#ff6b6b" if rev_delta_eff > 0 else "#51cf66"}">{"+" if rev_delta_eff > 0 else ""}¥{rev_delta_eff/10000:.1f}万</span>'
        sub_metric = f'上座 {"↑" if qty_delta > 0 else "↓"}{abs(qty_delta):,.0f}张'
    elif rw <= 0.3:
        main_metric = f'<span style="color:{"#ff6b6b" if qty_delta > 0 else "#51cf66"}">{"+" if qty_delta > 0 else ""}{qty_delta:,.0f}张</span>'
        sub_metric = f'收入 {"+" if rev_delta_eff > 0 else ""}¥{rev_delta_eff/10000:.1f}万'
    else:
        main_metric = f'<span style="color:{"#ff6b6b" if rev_delta_eff > 0 else "#51cf66"}">{"+" if rev_delta_eff > 0 else ""}¥{rev_delta_eff/10000:.1f}万</span> · <span style="color:{"#ff6b6b" if qty_delta > 0 else "#51cf66"}">{"+" if qty_delta > 0 else ""}{qty_delta:,.0f}张</span>'
        sub_metric = ''

    lines.append(f'决策质量（vs 基准预测）：{main_metric}{"（" + sub_metric + "）" if sub_metric else ""}')

    # 实际参考：仅当有实际数据时展示
    if actual_revenue is not None and actual_attendance is not None:
        base_qty_dev = r.base_attendance - actual_attendance
        base_rev_dev = (r.base_revenue or 0) - actual_revenue
        pred_ape = abs(base_qty_dev) / actual_attendance * 100 if actual_attendance > 0 else 0
        dev_color = "#51cf66" if pred_ape < 10 else "#f0c040" if pred_ape < 20 else "#ff6b6b"
        lines.append(f'<span style="color:#62666d;font-size:0.85em">预测偏差：基准 {base_qty_dev:+,.0f}张（APE {pred_ape:.1f}%）| 实际到场 {actual_attendance:,} 收入 ¥{actual_revenue/10000:.1f}万</span>')

    derby_card_class = "strategy-card derby" if pred_args.get('derby') else "strategy-card"
    st.markdown(f"""<div class="{derby_card_class}" style="border-left:3px solid {strat_color}">
      {'<br>'.join(lines)}
    </div>""", unsafe_allow_html=True)

    return strat_label, rw

def render_pricing_table(r):
    st.markdown("**定价建议**")
    rows = ""
    for zt in ZONE_TIERS:
        tr = r.tiers[zt]
        dp = (tr.optimal_price / tr.base_price - 1) * 100 if tr.base_price > 0 else 0
        delta_color = "#ff6b6b" if dp > 0.5 else "#51cf66" if dp < -0.5 else "#8a8f98"
        dp_str = f'<span style="color:{delta_color}">{dp:+.0f}%</span>' if abs(dp) > 1 else '<span style="color:#8a8f98">—</span>'
        lock = " 🔒" if tr.is_frozen else ""
        qty_delta = tr.predicted_qty - tr.base_qty
        qty_d_color = "#ff6b6b" if qty_delta > 0 else "#51cf66" if qty_delta < 0 else "#8a8f98"
        rev_delta_z = tr.revenue - (tr.base_price * tr.base_qty)
        rev_d_color = "#ff6b6b" if rev_delta_z > 0 else "#51cf66" if rev_delta_z < 0 else "#8a8f98"
        rows += (
            f'<tr>'
            f'<td style="font-weight:510;color:#f7f8f8">{zt}{lock}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">¥{tr.base_price:,.0f}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace;color:#f7f8f8;font-weight:510">¥{tr.optimal_price:,.0f} {dp_str}</td>'
            f'<td style="color:#62666d">{tr.base_qty:,.0f}</td>'
            f'<td style="color:#f7f8f8">{tr.predicted_qty:,.0f}</td>'
            f'<td style="color:{qty_d_color};font-family:JetBrains Mono,ui-monospace">{qty_delta:+,.0f}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">¥{tr.revenue/10000:.2f}万</td>'
            f'<td style="color:{rev_d_color};font-family:JetBrains Mono,ui-monospace">¥{rev_delta_z/10000:+.1f}万</td>'
            f'</tr>'
        )

    total_dq = (r.total_attendance / r.base_attendance - 1) * 100 if r.base_attendance > 0 else 0
    rev_delta = r.total_revenue - r.base_revenue
    rev_color = "#ff6b6b" if rev_delta > 0 else "#51cf66"
    qty_delta_total = r.total_attendance - r.base_attendance
    qty_d_color = "#ff6b6b" if qty_delta_total > 0 else "#51cf66"

    rows += (
        f'<tr style="border-top:1px solid rgba(255,255,255,0.08);font-weight:510">'
        f'<td colspan="2" style="color:#8a8f98">合计</td>'
        f'<td style="color:#f7f8f8">—</td>'
        f'<td style="color:#62666d">{r.base_attendance:,.0f}</td>'
        f'<td style="color:#f7f8f8">{r.total_attendance:,.0f}</td>'
        f'<td style="color:{qty_d_color};font-family:JetBrains Mono,ui-monospace">{qty_delta_total:+,.0f}</td>'
        f'<td style="color:#f7f8f8">¥{r.total_revenue/10000:.1f}万</td>'
        f'<td style="color:{rev_color};font-family:JetBrains Mono,ui-monospace">¥{rev_delta/10000:+.1f}万</td>'
        f'</tr>'
    )

    st.markdown(f"""<table class="history-table" style="font-size:0.68rem">
      <thead><tr><th>档位</th><th>基准价</th><th>优化价</th><th>基准量</th><th>场景量</th><th>Δ量</th><th>场景收入</th><th>Δ收入</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>""", unsafe_allow_html=True)
    st.caption("情景推演未经验证 · 实际定价请结合实时预售数据")

def render_what_if(r, opp):
    st.divider()
    st.markdown("**What-If 沙盒 | 手动调价测试**")
    scenario = st.radio(
        "预设情景",
        ["基准（模型推荐）", "悲观（-20%）", "乐观（+15%）", "自定义"],
        horizontal=True, key=f"scenario_tab1_{opp}"
    )

    mult = WHATIF_PRESETS.get(scenario, 1.0)

    col1, col2 = st.columns(2)
    sliders = {}
    with col1:
        for zt in ["T1", "T2", "T3"]:
            base = r.tiers[zt].base_price
            val = int(base * mult / 10) * 10 if scenario != "自定义" else int(base / 10) * 10
            sliders[zt] = st.slider(f"{zt} 价格", 40, 400, max(40, val), 10, key=f"wiz_{zt}_{opp}")
    with col2:
        for zt in ["T4", "T5", "T6"]:
            base = r.tiers[zt].base_price
            val = int(base * mult / 10) * 10 if scenario != "自定义" else int(base / 10) * 10
            sliders[zt] = st.slider(f"{zt} 价格", 30, 250, max(30, val), 10, key=f"wiz_{zt}_{opp}")

    # Recalc with optimizer's elasticity matrix
    opp_level = r.opponent_level
    optimizer = get_optimizer()
    eps = optimizer.elasticity[opp_level]

    rows = ""
    total_rev, total_qty = 0, 0
    base_total_rev, base_total_qty = 0, 0
    for zt in ZONE_TIERS:
        tr = r.tiers[zt]
        bp, bq = tr.base_price, tr.base_qty
        mp = sliders[zt]
        ep = eps.get(zt, 0.25)
        price_ratio = mp / bp if bp > 0 else 1
        mq = bq * (price_ratio ** (-ep)) if abs(ep) >= 0.001 else bq
        mq = max(0, min(mq, optimizer.capacities[zt]))
        if mp < bp:
            mq = max(mq, bq)
        mrev = mp * mq
        brev = bp * bq
        total_rev += mrev; total_qty += mq
        base_total_rev += brev; base_total_qty += bq

        delta_color = "#51cf66" if mp < bp else "#ff6b6b" if mp > bp else "#8a8f98"
        dq_clr = "#51cf66" if mq < bq else "#ff6b6b" if mq > bq else "#8a8f98"
        rows += (
            f'<tr>'
            f'<td style="font-weight:510">{zt}</td>'
            f'<td>¥{bp:,.0f}</td>'
            f'<td style="color:{delta_color};font-weight:510">¥{mp:,.0f}</td>'
            f'<td>{bq:,.0f}</td>'
            f'<td style="color:{dq_clr}">{mq:,.0f}</td>'
            f'<td>¥{mrev/10000:.2f}万</td>'
            f'</tr>'
        )

    rev_delta = total_rev - base_total_rev
    rev_clr = "#ff6b6b" if rev_delta > 0 else "#51cf66"
    qty_delta = total_qty - base_total_qty
    qty_clr = "#ff6b6b" if qty_delta > 0 else "#51cf66"
    rows += (
        f'<tr style="border-top:1px solid rgba(255,255,255,0.08);font-weight:510">'
        f'<td colspan="3" style="color:#8a8f98">手动模拟合计</td>'
        f'<td style="color:#f7f8f8">{base_total_qty:,.0f}</td>'
        f'<td style="color:{qty_clr}">{total_qty:,.0f}</td>'
        f'<td style="color:{rev_clr}">{rev_delta/10000:+.1f}万</td>'
        f'</tr>'
    )

    st.markdown(f"""<table class="compact-table">
      <thead><tr><th>档位</th><th>基准价</th><th>手动价</th><th>基准量</th><th>手动量</th><th>手动收入</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>""", unsafe_allow_html=True)

    rev_total = total_rev / 10000
    rev_low = rev_total * 0.80
    rev_high = rev_total * 1.15
    st.markdown(f"""<div style="font-size:0.72rem;color:#8a8f98;margin-top:8px">
      收入区间：
      <span style="color:#51cf66">悲观 ¥{rev_low:.0f}万</span> →
      <span style="color:#f7f8f8;font-weight:590">基准 ¥{rev_total:.0f}万</span> →
      <span style="color:#ff6b6b">乐观 ¥{rev_high:.0f}万</span>
    </div>""", unsafe_allow_html=True)


def render_tab1(target_match, home_preds, guoan_matches, standings, mae):
    opp = target_match["opponent"]
    dt = pd.Timestamp(target_match["date"])
    tier = classify_opponent_tier(opp)
    pt = get_pricing_tier(opp)

    crest_html = team_crest_html(opp, "lg")
    derby_class = "derby-match" if opp in DERBY_RIVALS else ""
    st.markdown(f"""<div style="display:flex;align-items:center;gap:10px;padding:4px 0" class="{derby_class}">
      {crest_html}<span style="font-size:1.3rem;font-weight:590;color:#f7f8f8">{target_match['date']} vs {opp}</span>
    </div>""", unsafe_allow_html=True)
    st.caption(f"{TIER_LABELS.get(tier, tier)} | 定价: {PT_LABELS.get(pt, pt)} | {target_match['round']} | {WEEKDAYS[dt.weekday()]}")
    if opp in DERBY_RIVALS:
        st.caption("🔥 德比战 · 球迷关注度最高 · 建议收入优先策略")

    # Recent results
    render_recent_results(target_match, guoan_matches, standings)

    # Build context
    ctx = detect_ctx(target_match, guoan_matches, _ctx_rounds)
    derby = opp in DERBY_RIVALS
    sat = dt.weekday() == 5
    late = dt.month >= 10
    mid = dt.weekday() in [1, 2, 3]
    sm = dt.month in (7, 8)
    lb = ctx.get("lost_bottom", False)
    hh = ctx.get("heavy_home_loss", False)
    aw = ctx.get("away_winless", False)
    sr = ctx.get("short_rest", False)
    mr = ctx.get("midseason_restart", False)
    ub3 = ctx.get("unbeaten_3", False)
    so = ctx.get("season_opener", False)

    prev_matches = [m for m in guoan_matches if m.get("completed") and pd.Timestamp(m["date"]) < dt]
    last_home_dates = [pd.Timestamp(m["date"]) for m in prev_matches if m["is_home"]]
    days_since_home = (dt - last_home_dates[-1]).days if last_home_dates else 999

    # Rule chain
    st.markdown("**命中规则 · 上座预测计算链**")
    base = TIER_BASE.get(tier, 9000)
    rules_triggered = []
    rules_triggered.append(("基值", f"{tier}级 {base:,.0f}张", 1.0,
        f"{tier}级基值来自KMeans聚类均值（S={TIER_BASE['S']:,.0f} A={TIER_BASE['A']:,.0f} B={TIER_BASE['B']:,.0f} C={TIER_BASE['C']:,.0f}）"))

    if ub3:
        rules_triggered.append(("不败", "近3场不败 ×1.00", 1.00, "近3场未尝败绩，球迷乐观情绪。V5.1网格搜索收敛至中性"))
    if so:
        rules_triggered.append(("揭幕战", "赛季首个主场 ×1.17", 1.17, "揭幕战球迷关注度高，历史上座溢价约17%"))
    if derby:
        if tier == "S":
            rules_triggered.append(("德比", "S级德比不叠加溢价", 1.0, f"申花已是S级最高基值（{TIER_BASE['S']:,}），德比溢价已内嵌在分级中"))
        else:
            m_val = 1.05 if tier == "A" else 1.25
            label = "A级德比" if tier == "A" else "德比"
            rules_triggered.append((label, f"{opp} {label}对手 ×{m_val}", m_val,
                f"{'A级德比溢价5%' if tier == 'A' else '历史数据显示溢价25%'}，S级不叠加"))
    if sat:
        rules_triggered.append(("周六场", "周末上座溢价 ×1.02", 1.02, "周六比赛日球迷时间充裕，V5.1网格搜索最优溢价约2%"))
    if mr and not so:
        rules_triggered.append(("盛夏重启", f"距上场≥28天 下半季回归 ×1.10", 1.10,
            f"长休{28 if not prev_matches else (dt - pd.Timestamp(prev_matches[-1]['date'])).days}天后球迷回流，B级6月重启场次历史均值1.22x，保守标定1.10"))
    if sm and tier in ("B", "C"):
        rules_triggered.append(("暑假效应", "7-8月暑假运营活动 ×1.13", 1.13, "暑假期间球迷观赛时间充裕，运营促销活动叠加"))
    if late:
        rules_triggered.append(("赛季末", f"{dt.month}月 战意衰减 ×0.80", 0.80, "10月以后赛季末，若球队已无争冠/保级悬念，上座下滑"))
    if mid and not lb and not hh:
        rules_triggered.append(("工作日", f"周{'一二三四五六日'[dt.weekday()]} 工作日衰减 ×0.86", 0.86, "周二/三/四工作日影响-14%，不与lost_bottom/heavy叠加"))
    if aw:
        away3 = [m for m in prev_matches[-3:] if not m["is_home"]] if len(prev_matches) >= 3 else []
        rules_triggered.append(("客场不胜", f"近3场{len(away3)}客0胜 ×0.98", 0.98, "球迷对客场表现失望传导至主场观赛意愿"))
    if lb:
        # Find which match triggered it
        lb_match = None
        for m in prev_matches[-3:]:
            is_loss = (m["is_home"] and m["hg"] < m["ag"]) or (not m["is_home"] and m["ag"] < m["hg"])
            if not is_loss: continue
            opp_r = standings.get(m["round"], {}).get(m["opponent"], 8)
            if opp_r >= 12:
                opp_t = classify_opponent_tier(m["opponent"])
                if opp_t == "C":
                    lb_match = (m["date"], m["opponent"], opp_r)
        if lb_match:
            rules_triggered.append(("输保级队", f"{lb_match[0]} {lb_match[1]} 排名#{lb_match[2]}≥12 ×0.65", 0.65,
                f"输给排名≥12的保级队（{lb_match[1]} #{lb_match[2]}），对球迷信心打击极大。对A/S级对手降至×0.78（复仇效应）"))
        else:
            rules_triggered.append(("输保级队", "输排名≥12球队 ×0.65", 0.65, "输保级队打击球迷信心"))
    elif hh:
        hh_match = None
        for m in prev_matches[-3:]:
            if not m["is_home"]: continue
            if m["hg"] is not None and m["ag"] is not None and m["hg"] < m["ag"] and abs(m["hg"] - m["ag"]) >= 2:
                idx = prev_matches.index(m) if m in prev_matches else -1
                later = prev_matches[idx + 1:] if idx >= 0 else []
                has_win = any((lm["is_home"] and lm["hg"] > lm["ag"]) or (not lm["is_home"] and lm["ag"] > lm["hg"]) for lm in later)
                if not has_win:
                    hh_match = (m["date"], m["opponent"], abs(m["hg"] - m["ag"]))
        if hh_match:
            rules_triggered.append(("主场惨败", f"{hh_match[0]} vs {hh_match[1]} 净负{hh_match[2]}球 ×0.85", 0.85,
                f"主场净负≥2球（vs {hh_match[1]} -{hh_match[2]}球），球迷失望情绪压制下场上座"))
        else:
            rules_triggered.append(("主场惨败", "主场净负≥2球 ×0.85", 0.85, "失望情绪压制下场上座"))
    if sr and not lb and not hh:
        rules_triggered.append(("双赛周", f"距上一主场 ≤4天 ×0.78", 0.78, "双赛周疲劳导致观赛意愿下降，乘数0.78"))

    render_rule_pills(rules_triggered)

    # Final prediction
    final_mult = 1.0
    for _, _, m_val, _ in rules_triggered[1:]:
        final_mult *= m_val
    final_mult = max(final_mult, PENALTY_FLOOR)
    raw_pred = min(base * final_mult, 20000)
    _cal = get_calibration()
    _cal_factor = _cal["tier"].get(tier, 1.0)
    pred = raw_pred * _cal_factor

    render_cumulative_bar(base, final_mult, pred, tier, _cal_factor)
    render_confidence_bar(pred, mae)

    # Pricing section
    st.divider()
    st.markdown("**定价建议**")
    st.caption("规则引擎预测 + 分层组合策略优化 · 情景推演未经验证")

    strategy_mode = st.radio(
        "策略模式",
        ["auto", "balanced"], index=0, horizontal=True,
        format_func=lambda x: "自动（动态权重）" if x == "auto" else "平衡（T1-T3降价抢量+T4-T6涨价补收入）",
        key=f"strategy_{opp}"
    )

    pred_args = build_pred_args(target_match, ctx, {'season_opener': so, 'unbeaten_3': ub3})
    optimizer = get_optimizer()
    r = optimizer.optimize(opp, strategy=strategy_mode, **pred_args)

    render_strategy_card(r, pred_args)
    render_pricing_table(r)
    render_what_if(r, opp)


# ══════════════════════════════════════════════════════════
#  Tab 2: 历史定价
# ══════════════════════════════════════════════════════════

def render_mae_chart(home_preds):
    if not home_preds:
        return
    errors = [p - a for _, p, a, _ in home_preds]
    labels = [f"{m['date'][5:]} {m['opponent'][:3]}" for m, _, _, _ in home_preds]

    st.markdown("**模型 MAE 收敛趋势**")
    bars = ""
    max_abs = max(abs(e) for e in errors) if errors else 1
    for label, err in zip(labels, errors):
        pct = abs(err) / max_abs * 100 if max_abs > 0 else 0
        bar_w = max(pct, 3)
        clr = "#ff6b6b" if err > 0 else "#51cf66"
        bars += f"""<div style="display:flex;align-items:center;gap:8px;margin:2px 0">
          <span style="font-size:0.7rem;color:#8a8f98;min-width:90px;font-family:JetBrains Mono,ui-monospace">{label}</span>
          <div style="flex:1;height:14px;background:rgba(255,255,255,0.03);border-radius:3px;overflow:hidden">
            <div style="width:{bar_w}%;height:14px;background:{clr};border-radius:3px;opacity:0.6"></div>
          </div>
          <span style="font-size:0.7rem;color:{clr};font-weight:510;min-width:70px;font-family:JetBrains Mono,ui-monospace">{err:+,.0f}</span>
        </div>"""
    mae_now = np.mean(np.abs(errors)) if errors else 0
    bars += f"""<div style="font-size:0.65rem;color:#8a8f98;margin-top:4px;text-align:right">
      当前 MAE <span style="color:#f7f8f8;font-weight:590">{mae_now:,.0f} 张</span>
    </div>"""
    st.markdown(bars, unsafe_allow_html=True)

def render_history_expanders(home_preds, guoan_matches):
    if not home_preds:
        st.info("暂无已赛主场数据")
        return

    st.divider()
    st.caption("每场比赛展开查看详情 · 情景推演未经验证")

    optimizer = get_optimizer()
    _pm = build_price_matrix()

    for i, (m, p, a, ctx) in enumerate(home_preds):
        opp = m["opponent"]
        dt_m = pd.Timestamp(m["date"])
        ape = abs(p - a) / a * 100 if a > 0 else 0
        ape_color = "#51cf66" if ape < 10 else "#f0c040" if ape < 20 else "#ff6b6b"

        expanded = (i == len(home_preds) - 1)

        st.divider()
        crest_h = team_crest_html(opp, "sm")
        derby_tag = ' 🔥德比' if opp in DERBY_RIVALS else ''
        st.markdown(f"{crest_h} **{m['date']} vs {opp}{derby_tag}** | 预测{p:,.0f} 实际{a:,.0f} | 误差{p - a:+,.0f} APE{ape:.1f}%", unsafe_allow_html=True)
        # 补全 context：season_opener=首场主场, unbeaten_3=赛前3场不败
        is_first_home = (m == home_preds[0][0])
        ub3_before = ctx.get('unbeaten_3', False)
        pred_args = build_pred_args(m, ctx, {'season_opener': is_first_home, 'unbeaten_3': ub3_before,
                                              'summer': dt_m.month in [7,8], 'match_year': m["date"][:4]})
        r_h = optimizer.optimize(opp, **pred_args)

        # Load actual data first, then render strategy card with vs-actual comparison
        zone_qty = _get_zone_qtys(m)
        zone_rev = _get_zone_actual_revenue(m)
        total_actual_qty = 0
        total_actual_rev = 0

        for zt in ZONE_TIERS:
            tr = r_h.tiers[zt]
            dp = (tr.optimal_price / tr.base_price - 1) * 100 if tr.base_price > 0 else 0
            delta_color = "#51cf66" if dp < -0.5 else "#ff6b6b" if dp > 0.5 else "#8a8f98"
            dp_s = f'<span style="color:{delta_color}">{dp:+.0f}%</span>' if abs(dp) > 1 else ""
            actual_z = zone_qty.get(zt, 0)
            actual_rev = zone_rev.get(zt, 0)
            total_actual_rev += actual_rev
            total_actual_qty += actual_z
            qty_delta_z = tr.predicted_qty - actual_z
            qty_delta_color = "#ff6b6b" if qty_delta_z > 0 else "#51cf66" if qty_delta_z < 0 else "#8a8f98"

        # Strategy card with vs-actual data (dynamic linkage)
        strat_label, rw = render_strategy_card(r_h, pred_args,
            actual_revenue=total_actual_rev, actual_attendance=total_actual_qty)

        # Build pricing table HTML: 决策质量优先（Δ = 场景 vs 基准预测）
        r_html = ""
        for zt in ZONE_TIERS:
            tr = r_h.tiers[zt]
            dp = (tr.optimal_price / tr.base_price - 1) * 100 if tr.base_price > 0 else 0
            dp_color = "#51cf66" if dp < -0.5 else "#ff6b6b" if dp > 0.5 else "#8a8f98"
            dp_s = f'<span style="color:{dp_color}">{dp:+.0f}%</span>' if abs(dp) > 1 else ""
            # 决策质量 Δ = 场景 - 基准（同一预测基础上的优化效应）
            qty_base_z = tr.base_qty
            qty_opt_z = tr.predicted_qty
            qty_delta_z = qty_opt_z - qty_base_z
            qty_delta_color = "#ff6b6b" if qty_delta_z > 0 else "#51cf66" if qty_delta_z < 0 else "#8a8f98"
            rev_base_z = tr.base_price * tr.base_qty
            rev_opt_z = tr.revenue
            rev_delta_z = rev_opt_z - rev_base_z
            rev_delta_z_color = "#ff6b6b" if rev_delta_z > 0 else "#51cf66" if rev_delta_z < 0 else "#8a8f98"
            # 实际数据（纯参考）
            actual_z = zone_qty.get(zt, 0)
            actual_rev_z = zone_rev.get(zt, 0)
            r_html += (
                f'<tr><td>{zt}</td>'
                f'<td>¥{tr.base_price:,.0f}</td>'
                f'<td>¥{tr.optimal_price:,.0f} {dp_s}</td>'
                f'<td style="color:#62666d">{qty_base_z:,.0f}</td>'
                f'<td style="color:#f7f8f8">{qty_opt_z:,.0f}</td>'
                f'<td style="color:{qty_delta_color};font-family:JetBrains Mono,ui-monospace">{qty_delta_z:+,.0f}</td>'
                f'<td>¥{rev_opt_z/10000:.2f}万</td>'
                f'<td style="color:{rev_delta_z_color};font-family:JetBrains Mono,ui-monospace">¥{rev_delta_z/10000:+.1f}万</td>'
                f'<td style="color:#62666d">{actual_z:,}</td>'
                f'<td style="color:#62666d">¥{actual_rev_z/10000:.2f}万</td>'
                f'</tr>'
            )

        # Total row: decision quality deltas (opt - base)
        qty_delta_total = r_h.total_attendance - r_h.base_attendance
        qty_delta_t_color = "#ff6b6b" if qty_delta_total > 0 else "#51cf66" if qty_delta_total < 0 else "#8a8f98"
        rev_delta_total = r_h.total_revenue - (r_h.base_revenue or 0)
        rev_delta_t_color = "#ff6b6b" if rev_delta_total > 0 else "#51cf66" if rev_delta_total < 0 else "#8a8f98"
        r_html += (
            f'<tr style="border-top:1px solid rgba(255,255,255,0.08);font-weight:510">'
            f'<td colspan="3" style="color:#8a8f98">合计</td>'
            f'<td style="color:#62666d">{r_h.base_attendance:,.0f}</td>'
            f'<td style="color:#f7f8f8">{r_h.total_attendance:,.0f}</td>'
            f'<td style="color:{qty_delta_t_color};font-family:JetBrains Mono,ui-monospace">{qty_delta_total:+,.0f}</td>'
            f'<td>¥{r_h.total_revenue/10000:.1f}万</td>'
            f'<td style="color:{rev_delta_t_color};font-family:JetBrains Mono,ui-monospace">¥{rev_delta_total/10000:+.1f}万</td>'
            f'<td style="color:#62666d">{total_actual_qty:,}</td>'
            f'<td style="color:#62666d">¥{total_actual_rev/10000:.1f}万</td>'
            f'</tr>'
        )

        st.markdown(f"""<table class="history-table">
          <thead><tr><th>档位</th><th>基准价</th><th>优化价</th><th>基准量</th><th>场景量</th><th>Δ量</th><th>场景收入</th><th>Δ收入</th><th>实际量</th><th>实际收入</th></tr></thead>
          <tbody>{r_html}</tbody>
        </table>""", unsafe_allow_html=True)

        # Bad tradeoff 检测：基于决策质量（场景 vs 基准），不是实际 vs 场景
        bad_tradeoff = False
        bad_reason = ""
        if rw >= 0.7 and rev_delta_total < -5000 and qty_delta_total < 100:
            bad_tradeoff = True
            bad_reason = f"⚠️ 收入优先策略下损失 ¥{abs(rev_delta_total)/10000:.1f}万（vs 基准），仅增量 {qty_delta_total:+,.0f}张，tradeoff 不划算"
        elif rw <= 0.3 and qty_delta_total < 0 and rev_delta_total < -3000:
            bad_tradeoff = True
            bad_reason = f"⚠️ 上座优先策略下未增量（{qty_delta_total:+,.0f}张 vs 基准），还损失 ¥{abs(rev_delta_total)/10000:.1f}万"

        # 规则3: 增收但代价过大（收入优先+均衡模式）
        if not bad_tradeoff and rw >= 0.5:
            rev_gain = rev_delta_total
            qty_loss = -qty_delta_total
            if rev_gain > 0 and qty_loss > 100:
                gain_per_lost = rev_gain / qty_loss if qty_loss > 0 else float('inf')
                if gain_per_lost < 50:
                    bad_tradeoff = True
                    bad_reason = f"⚠️ 增收 ¥{rev_gain/10000:.1f}万但上座 -{qty_loss:,.0f}张（仅 ¥{gain_per_lost:.0f}/人），代价过大"

        # 规则4: 降价增量但收入损失过大
        if not bad_tradeoff and rw <= 0.3:
            qty_gain = qty_delta_total
            rev_loss = -rev_delta_total
            if qty_gain > 0 and rev_loss > 5000:
                cost_per_gained = rev_loss / qty_gain if qty_gain > 0 else float('inf')
                if cost_per_gained > 200:
                    bad_tradeoff = True
                    bad_reason = f"⚠️ 增量 {qty_gain:+,.0f}张但损失 ¥{rev_loss/10000:.1f}万（¥{cost_per_gained:.0f}/人），获客成本过高"

        if bad_tradeoff:
            st.markdown(f"""<div style="padding:6px 12px;margin:4px 0;background:rgba(255,107,107,0.08);border:1px solid rgba(255,107,107,0.2);border-radius:6px;font-size:0.72rem;color:#ff6b6b">
              {bad_reason}
            </div>""", unsafe_allow_html=True)

        # 策略审计卡片 — 决策质量评估
        audit_bg = "rgba(81,207,102,0.06)" if not bad_tradeoff else "rgba(255,107,107,0.08)"
        audit_border = "rgba(81,207,102,0.12)" if not bad_tradeoff else "rgba(255,107,107,0.2)"
        audit_color = "#51cf66" if not bad_tradeoff else "#ff6b6b"
        audit_judgment = "✅ 策略目标达成" if not bad_tradeoff else "❌ 策略未达成 — 见上方警告"

        # 预测偏差
        base_qty_dev_audit = (r_h.base_attendance or 0) - total_actual_qty
        base_rev_dev_audit = (r_h.base_revenue or 0) - total_actual_rev

        st.markdown(f"""<div style="padding:8px 12px;margin:4px 0;background:{audit_bg};border:1px solid {audit_border};border-radius:6px;font-size:0.72rem;color:{audit_color}">
          <strong>{opp} 策略审计（决策质量）</strong><br>
          策略模式：{strat_label}（rw={rw:.0%} aw={r_h.attendance_weight:.0%}）<br>
          优化效应：场景 ¥{r_h.total_revenue/10000:.1f}万 vs 基准 ¥{(r_h.base_revenue or 0)/10000:.1f}万（{rev_delta_total/10000:+.1f}万）<br>
          数量效应：场景 {r_h.total_attendance:,.0f}张 vs 基准 {(r_h.base_attendance or 0):.0f}张（{qty_delta_total:+,.0f}张）<br>
          预测偏差：基准 {base_qty_dev_audit:+,.0f}张 · 实际到场 {total_actual_qty:,} · 实际收入 ¥{total_actual_rev/10000:.1f}万<br>
          判断：{audit_judgment}
        </div>""", unsafe_allow_html=True)

        # V8.1: EMA赛后校准 — 每场已赛主场更新校准因子
        rule_update(
            match_id=f"{m['date']}_{opp}",
            opponent=opp,
            actual=a,
            **pred_args
        )


# ══════════════════════════════════════════════════════════
#  Tab 3: 赛季全景
# ══════════════════════════════════════════════════════════

def render_season_chart(home_preds):
    if len(home_preds) < 2:
        return

    dates = [pd.Timestamp(m["date"]) for m, _, _, _ in home_preds]
    preds_plt = [p for _, p, _, _ in home_preds]
    actuals_plt = [a for _, _, a, _ in home_preds]
    labels_plt = [m["opponent"][:3] for m, _, _, _ in home_preds]

    fig, ax = plt.subplots(figsize=(8, 2.5))
    fig.patch.set_facecolor('#0c0d0f')
    ax.set_facecolor('#0c0d0f')
    x = range(len(dates))
    ax.plot(x, preds_plt, 'o--', color='#ff6b6b', linewidth=1.5, markersize=6, label='预测', alpha=0.8)
    ax.plot(x, actuals_plt, 'o-', color='#51cf66', linewidth=2, markersize=6, label='实际')
    ax.set_xticks(x)
    ax.set_xticklabels(labels_plt, fontsize=8, color='#8a8f98')
    ax.tick_params(axis='y', colors='#62666d', labelsize=8)
    for spine in ['top', 'right']:
        ax.spines[spine].set_visible(False)
    ax.spines['bottom'].set_color('#2a2d33')
    ax.spines['left'].set_color('#2a2d33')
    ax.grid(axis='y', alpha=0.05, color='white')
    ax.legend(loc='upper right', facecolor='#1a1d22', edgecolor='#2a2d33', labelcolor='#8a8f98', fontsize=8)
    st.pyplot(fig)
    plt.close(fig)

def render_season_table(home_preds):
    st.subheader("赛季回望")
    if not home_preds:
        st.info("暂无已赛主场数据")
        return

    rows = []
    preds_all, actuals_all = [], []
    for m, p, a, _ in home_preds:
        preds_all.append(p); actuals_all.append(a)
        ape = abs(p - a) / a * 100
        err_clr = "#ff6b6b" if p > a else "#51cf66"
        rows.append(
            f'<tr>'
            f'<td>{m["date"]}</td>'
            f'<td>{m["opponent"]}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">{p:,.0f}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">{a:,.0f}</td>'
            f'<td style="color:{err_clr};font-family:JetBrains Mono,ui-monospace">{p - a:+,.0f}</td>'
            f'<td>{ape:.1f}%</td>'
            f'</tr>'
        )

    mae = np.mean(np.abs(np.array(preds_all) - np.array(actuals_all)))
    st.markdown(f"""<table class="history-table">
      <thead><tr><th>日期</th><th>对手</th><th>预测</th><th>实际</th><th>误差</th><th>APE</th></tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>""", unsafe_allow_html=True)
    st.metric("累积 MAE", f"{mae:,.0f} 张")


# ══════════════════════════════════════════════════════════
#  Tab 4: 对手分析
# ══════════════════════════════════════════════════════════

def render_opponent_analysis(all_matches):
    _cal = get_calibration()
    
    # Use all_matches passed from main()
    guoan_all = get_guoan_matches(all_matches)
    tier_opps = {"S": [], "A": [], "B": [], "C": []}
    for opp in sorted(set(m['opponent'] for m in guoan_all)):
        tier_opps[classify_opponent_tier(opp)].append(opp)
    
    st.markdown("**对手分级与基值矩阵**")
    tiers_order = ["S", "A", "B", "C"]
    trows = ""
    for t in tiers_order:
        base = TIER_BASE.get(t, 0)
        cf = _cal["tier"].get(t, 1.0)
        cal_color = "#ff6b6b" if cf > 1.01 else "#51cf66" if cf < 0.99 else "#8a8f98"
        opps_str = " · ".join(tier_opps.get(t, []))
        trows += (
            f'<tr>'
            f'<td style="font-weight:510;color:#f7f8f8">{t}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">{base:,.0f}</td>'
            f'<td style="color:{cal_color};font-family:JetBrains Mono,ui-monospace">{cf:.4f}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace;color:#f7f8f8">{base*cf:,.0f}</td>'
            f'<td style="text-align:left;font-size:0.7rem;color:#8a8f98">{opps_str}</td>'
            f'</tr>'
        )
    st.markdown(f"""<table class="compact-table" style="max-width:700px">
      <thead><tr><th>级别</th><th>基值(张)</th><th>校准因子</th><th>校准后</th><th style="text-align:left">对手</th></tr></thead>
      <tbody>{trows}</tbody>
    </table>""", unsafe_allow_html=True)
    st.caption("基值来自 KMeans 聚类均值 · 校准因子 EMA(α=0.20) 基于已赛数据")
    
    # ── 对手表现数据 ──
    st.divider()
    st.markdown("**对手表现数据**")
    
    from collections import defaultdict as _dd
    ts = _dd(lambda: {"p":0,"w":0,"d":0,"l":0,"gf":0,"ga":0,"pts":0,"form":[]})
    for m in sorted([x for x in all_matches if x['date'].startswith('2026')], key=lambda x: x['date']):
        if not m.get('completed'): continue
        h, a = m['home'], m['away']
        ts[h]['p']+=1; ts[a]['p']+=1
        ts[h]['gf']+=m['hg']; ts[h]['ga']+=m['ag']
        ts[a]['gf']+=m['ag']; ts[a]['ga']+=m['hg']
        if m['hg']>m['ag']:
            ts[h]['w']+=1; ts[h]['pts']+=3; ts[a]['l']+=1
            ts[h]['form'].append('W'); ts[a]['form'].append('L')
        elif m['hg']==m['ag']:
            ts[h]['d']+=1; ts[a]['d']+=1; ts[h]['pts']+=1; ts[a]['pts']+=1
            ts[h]['form'].append('D'); ts[a]['form'].append('D')
        else:
            ts[a]['w']+=1; ts[a]['pts']+=3; ts[h]['l']+=1
            ts[a]['form'].append('W'); ts[h]['form'].append('L')
    
    opp_list = sorted(set(m['opponent'] for m in guoan_all))
    orows = ""
    for team in opp_list:
        s = ts.get(team)
        if not s: continue
        d = DEDUCTIONS.get(team, 0)
        eff = s['pts'] - d
        gd = s['gf'] - s['ga']
        form5 = ''.join(s['form'][-5:])
        gd_clr = "#ff6b6b" if gd > 0 else "#51cf66" if gd < 0 else "#8a8f98"
        tier = classify_opponent_tier(team)
        tier_clr = {"S":"#ff6b6b","A":"#f0c040","B":"#8a8f98","C":"#51cf66"}.get(tier,"#8a8f98")
        # Build form pills
        form_pills = ""
        for ch in form5:
            fc = "#ff6b6b" if ch == 'W' else "#f0c040" if ch == 'D' else "#51cf66"
            form_pills += f'<span style="display:inline-block;width:18px;height:18px;line-height:18px;text-align:center;border-radius:3px;background:{fc}22;color:{fc};font-size:0.6rem;font-weight:590;margin:0 1px">{ch}</span>'
        orows += (
            f'<tr>'
            f'<td style="font-weight:510;color:{tier_clr};text-align:left;padding-left:8px">{team_crest_html(team, "sm")} {team}</td>'
            f'<td style="color:#8a8f98">{tier}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">{s["p"]}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">{s["w"]}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">{s["d"]}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">{s["l"]}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">{s["gf"]}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">{s["ga"]}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace;color:{gd_clr}">{gd:+d}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">{s["pts"]}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace;color:#62666d">{d if d>0 else ""}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace;font-weight:590;color:#f7f8f8">{eff}</td>'
            f'<td style="padding:2px 4px">{form_pills}</td>'
            f'</tr>'
        )
    st.markdown(f"""<table class="compact-table">
      <thead><tr>
        <th style="text-align:left;padding-left:8px">球队</th><th>级</th><th>赛</th><th>胜</th><th>平</th><th>负</th>
        <th>进</th><th>失</th><th>净</th><th>分</th><th>扣</th><th>有效</th><th>近5场</th>
      </tr></thead>
      <tbody>{orows}</tbody>
    </table>""", unsafe_allow_html=True)
    st.caption("官方积分含 CFA 年初扣分处罚 · S红 A黄 C绿 · 近5场 W红 D黄 L绿")


# ══════════════════════════════════════════════════════════
#  Tab 6: H2策略驾驶舱
# ══════════════════════════════════════════════════════════

def render_h2_strategy(guoan_matches, standings):
    """策略驾驶舱：H2目标 × V5.3实时预测联动"""
    h2_path = ROOT / "data/targets/h2_2026_match_targets.json"
    if not h2_path.exists():
        st.error("H2策略数据文件不存在")
        return
    with open(h2_path) as f:
        h2 = json.load(f)

    completed = h2["completed"]
    summary = h2["summary"]
    matches = h2["matches"]
    model_ver = h2.get("model_version", "V5.3")
    STRATEGY_LABEL = {"revenue_priority": "收入优先", "revenue_tilt": "收入偏重", "balanced": "均衡"}
    STRATEGY_COLOR = {"revenue_priority": "#ff6b6b", "revenue_tilt": "#f0c040", "balanced": "#c2ef4e"}

    # ── Find next home for live prediction ──
    next_home = next((m for m in guoan_matches if not m["completed"] and m["is_home"] and m["date"].startswith("2026")), None)
    optimizer = get_optimizer()
    pm = build_price_matrix()
    live_pred = None; live_gap = 0; live_opt = None; next_target = None

    if next_home:
        mock = {**next_home, "completed": True}
        ctx = detect_ctx(mock, guoan_matches + [mock], _ctx_rounds)
        dt_ts = pd.Timestamp(next_home["date"]); opp = next_home["opponent"]
        pred_args = build_pred_args(next_home, ctx, {'season_opener': False, 'match_year': '2026'})
        live_pred = rule_predict(opp, **pred_args)
        live_opt = optimizer.optimize(opp, **pred_args)
        next_target = next((m for m in matches if m["date"] == next_home["date"]), None)
        if next_target:
            live_gap = live_opt.total_revenue - next_target["target_revenue"]

    # ══ KPI Row ══
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        vs_pct = summary.get("vs_2025_revenue_pct", 0)
        vs_color = "#51cf66" if vs_pct >= 0 else "#ff6b6b"
        st.markdown(f"""<div class="kpi-card">
          <div class="kpi-label">全年预估</div>
          <div class="kpi-value">¥{summary['annual_projection_revenue']/1e4:,.0f}万</div>
          <div class="kpi-sub">vs 2025: <span style="color:{vs_color}">{vs_pct:+.1f}%</span></div>
        </div>""", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""<div class="kpi-card">
          <div class="kpi-label">剩余目标 · {len(matches)}场</div>
          <div class="kpi-value">¥{summary['total_target_revenue']/1e4:,.0f}万</div>
          <div class="kpi-sub">{summary['total_target_quantity']:,}张</div>
        </div>""", unsafe_allow_html=True)
    with c3:
        gap_2025 = summary["annual_projection_revenue"] - 45914055
        gap_color = "#51cf66" if gap_2025 >= 0 else "#ff6b6b"
        st.markdown(f"""<div class="kpi-card">
          <div class="kpi-label">收入缺口 vs 2025</div>
          <div class="kpi-value"><span style="color:{gap_color}">¥{gap_2025/1e4:+.0f}万</span></div>
          <div class="kpi-sub">¥{completed['revenue']/1e4:.0f}万已完成</div>
        </div>""", unsafe_allow_html=True)
    with c4:
        st.markdown(f"""<div class="kpi-card">
          <div class="kpi-label">模型版本</div>
          <div class="kpi-value">{model_ver}</div>
          <div class="kpi-sub">MAE=384</div>
        </div>""", unsafe_allow_html=True)

    # ══ Next Match Watch ══
    if next_home and live_opt:
        st.divider()
        st.markdown("**下一场盯盘**")
        tier = classify_opponent_tier(next_home["opponent"])
        pt = get_pricing_tier(next_home["opponent"])
        prices = pm[pt]
        ctx_str = "+".join([k for k, v in ctx.items() if v]) or "无触发"
        gap_str = f'<span style="color:{"#51cf66" if live_gap >= 0 else "#ff6b6b"}">¥{live_gap/1e4:+.1f}万</span>' if next_target else "—"

        nc1, nc2, nc3, nc4 = st.columns(4)
        with nc1:
            st.markdown(f"""<div style="padding:8px 12px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:6px">
              <div style="font-size:0.62rem;color:#62666d">V5.3预测</div>
              <div style="font-size:1.1rem;color:#f7f8f8;font-weight:510">{live_pred:,.0f}张</div>
              <div style="font-size:0.62rem;color:#8a8f98">{tier}级 · {ctx_str}</div></div>""", unsafe_allow_html=True)
        with nc2:
            st.markdown(f"""<div style="padding:8px 12px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:6px">
              <div style="font-size:0.62rem;color:#62666d">优化收入</div>
              <div style="font-size:1.1rem;color:#f7f8f8;font-weight:510">¥{live_opt.total_revenue/1e4:.1f}万</div>
              <div style="font-size:0.62rem;color:#8a8f98">rw={live_opt.revenue_weight:.0%}</div></div>""", unsafe_allow_html=True)
        with nc3:
            if next_target:
                st.markdown(f"""<div style="padding:8px 12px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:6px">
                  <div style="font-size:0.62rem;color:#62666d">H2目标</div>
                  <div style="font-size:1.1rem;color:#f7f8f8;font-weight:510">¥{next_target['target_revenue']/1e4:.1f}万</div>
                  <div style="font-size:0.62rem;color:#8a8f98">偏差 {gap_str}</div></div>""", unsafe_allow_html=True)
            else:
                st.caption("无匹配目标")
        with nc4:
            st.markdown(f"""<div style="padding:8px 12px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:6px">
              <div style="font-size:0.62rem;color:#62666d">定价矩阵</div>
              <div style="font-size:0.78rem;color:#c8ccd4">T1¥{prices['T1']} T2¥{prices['T2']} T3¥{prices['T3']}</div>
              <div style="font-size:0.62rem;color:#62666d">T4¥{prices['T4']} T5¥{prices['T5']} T6¥{prices['T6']}</div></div>""", unsafe_allow_html=True)

    # ══ Strategy Table ══
    st.divider()
    tcol1, tcol2 = st.columns([3, 1])
    with tcol1:
        st.markdown("**逐场策略**")
    with tcol2:
        upgrade_toggle = st.toggle("⬆ 升B升级", value=False,
                                    help="辽宁铁人/重庆铜梁龙 C→B级，全年预估 +~¥2M",
                                    key="h2_upgrade_toggle")
    
    # Recalculate if toggled
    annual_rev = summary["annual_projection_revenue"]
    annual_qty = summary["annual_projection_quantity"]
    if upgrade_toggle:
        annual_rev = summary["annual_projection_revenue"] + 2_000_000
        annual_qty = summary["annual_projection_quantity"] + 4_825
    
    rows = ""
    sum_rev = 0; sum_qty = 0
    for m in matches:
        s = m["strategy"]; sc = STRATEGY_COLOR.get(s, "#8a8f98"); sl = STRATEGY_LABEL.get(s, s)
        bp = m["base_prices"]
        risks_str = " · ".join(m["risks"]) if m["risks"] else "—"
        is_next = next_home and m["date"] == next_home["date"]
        row_style = "background:rgba(255,255,255,0.03);" if is_next else ""
        rows += (
            f'<tr style="{row_style}">'
            f'<td style="font-family:JetBrains Mono,ui-monospace;font-size:0.7rem">{m["date"][5:]}</td>'
            f'<td style="font-weight:510;color:#f7f8f8">{m["opponent"]}</td>'
            f'<td style="color:#8a8f98">{m["tier"]}级</td>'
            f'<td><span style="display:inline-block;padding:2px 8px;border-radius:10px;background:{sc}22;color:{sc};font-size:0.68rem;font-weight:510">{sl}</span></td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace">{m["predicted_quantity"]:,}</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace;color:#f7f8f8">¥{m["target_revenue"]/1e4:.1f}万</td>'
            f'<td style="font-family:JetBrains Mono,ui-monospace;color:#8a8f98">¥{bp["T1"]}-¥{bp["T6"]}</td>'
            f'<td style="font-size:0.65rem;color:#8a8f98;max-width:150px">{risks_str}</td>'
            f'</tr>'
        )
        sum_rev += m["target_revenue"]; sum_qty += m["target_quantity"]
    rows += (
        f'<tr style="border-top:1px solid rgba(255,255,255,0.08);font-weight:510">'
        f'<td colspan="5" style="color:#8a8f98">{len(matches)}场合计</td>'
        f'<td style="color:#f7f8f8;font-family:JetBrains Mono,ui-monospace">¥{sum_rev/1e4:.1f}万</td>'
        f'<td style="color:#f7f8f8;font-family:JetBrains Mono,ui-monospace">{sum_qty:,}张</td>'
        f'<td></td></tr>'
    )
    st.markdown(f"""<table class="compact-table">
      <thead><tr><th>日期</th><th>对手</th><th>级</th><th>策略</th><th>目标收入</th><th>预测</th><th>T1-T6</th><th>风险</th></tr></thead>
      <tbody>{rows}</tbody></table>""", unsafe_allow_html=True)

    # ══ Waterfall + Tracking (side by side) ══
    st.divider()
    wf_col, tr_col = st.columns([1, 1])

    with wf_col:
        st.markdown("**收入缺口瀑布**")
        fig, ax = plt.subplots(figsize=(5, 3.5))
        fig.patch.set_facecolor("#0c0d0f"); ax.set_facecolor("#0c0d0f")
        ax.tick_params(colors="#8a8f98", labelsize=7)
        for spine in ax.spines.values(): spine.set_visible(False)

        categories = [c for c, _ in WATERFALL_DATA]
        values = [v for _, v in WATERFALL_DATA]
        colors_wf = ["#5b9bd5", "#ff6b6b", "#f0c040", "#ff6b6b", "#51cf66"]
        running = 0
        for i, (cat, val) in enumerate(zip(categories, values)):
            if i == 0:
                running = val; bottom = 0; h = val
            elif i == len(values) - 1:
                bottom = 0; h = val
            else:
                bottom = running + min(val, 0) if val < 0 else running
                h = abs(val)
                running += val
            ax.bar(i, h, bottom=bottom if i > 0 and i < len(values) - 1 else (0 if i in [0, len(values)-1] else bottom), color=colors_wf[i], width=0.5)
        for i, (cat, val) in enumerate(zip(categories, values)):
            y_pos = val if i == 0 else (running if i < len(values)-1 else val)
            offset = 80 if val >= 0 else -120
            ax.text(i, y_pos + offset, f"{abs(val)}万" if val < 0 and i < len(values)-1 else f"{val}万", ha="center", fontsize=7, color="#c8ccd4")
        ax.set_xticks(range(len(categories))); ax.set_xticklabels(categories, fontsize=6.5, color="#8a8f98")
        ax.axhline(y=0, color="#ffffff22", linewidth=0.5)
        st.pyplot(fig); plt.close()

    with tr_col:
        st.markdown("**累计追踪**")
        cum = 0
        tro = ""
        for m in matches:
            cum += m["target_revenue"]
            tro += (
                f'<tr><td style="font-family:JetBrains Mono,ui-monospace;font-size:0.68rem">{m["date"][5:]}</td>'
                f'<td style="font-weight:510;color:#f7f8f8;font-size:0.72rem">{m["opponent"]}</td>'
                f'<td style="font-family:JetBrains Mono,ui-monospace;font-size:0.7rem">¥{m["target_revenue"]/1e4:.1f}万</td>'
                f'<td style="font-family:JetBrains Mono,ui-monospace;font-size:0.7rem;color:#f7f8f8">¥{cum/1e4:.1f}万</td>'
                f'<td style="font-family:JetBrains Mono,ui-monospace;font-size:0.7rem;color:#62666d">—</td></tr>'
            )
        tro += (
            f'<tr style="border-top:1px solid rgba(255,255,255,0.08);font-weight:510">'
            f'<td colspan="3" style="color:#8a8f98">已完+剩余合计</td>'
            f'<td style="color:#f7f8f8">¥{cum/1e4:.1f}万</td><td></td></tr>'
        )
        st.markdown(f"""<table class="compact-table" style="font-size:0.7rem">
          <thead><tr><th>日期</th><th>对手</th><th>目标</th><th>累计</th><th>实际</th></tr></thead>
          <tbody>{tro}</tbody></table>""", unsafe_allow_html=True)
        st.caption("实际列留空 · 赛后填入")

    # ══ Circuit Breaker Lights ══
    st.divider()
    st.markdown("**熔断灯**")
    lights = [
        ("收入", summary["annual_projection_revenue"] >= 42000000, "¥42M+"),
        ("上座", summary["annual_projection_quantity"] >= 130000, "130K+"),
        ("升班马", not any("升班马" in " ".join(m.get("risks", [])) for m in matches), "待验证"),
        ("综合", summary["vs_2025_revenue_pct"] > -10, ">-10%"),
    ]
    light_html = ""
    for name, ok, note in lights:
        color = "#51cf66" if ok else "#f0c040" if name == "升班马" else "#ff6b6b"
        icon = "●" if ok else "▲" if name == "升班马" else "■"
        light_html += (
            f'<div style="flex:1;text-align:center;padding:8px;background:rgba(255,255,255,0.015);'
            f'border:1px solid rgba(255,255,255,0.05);border-radius:6px;margin:0 4px">'
            f'<div style="font-size:0.6rem;color:#62666d;text-transform:uppercase">{name}</div>'
            f'<div style="font-size:1.3rem;color:{color};margin:4px 0">{icon}</div>'
            f'<div style="font-size:0.62rem;color:#8a8f98">{note}</div></div>'
        )
    st.markdown(f'<div style="display:flex;gap:4px">{light_html}</div>', unsafe_allow_html=True)

    # ══ Model Notes ══
    notes = h2.get("notes", [])
    if notes:
        st.divider()
        st.caption("V5.3 备注")
        for n in notes:
            st.markdown(f'<div style="font-size:0.68rem;color:#62666d;padding:1px 0">· {n}</div>', unsafe_allow_html=True)



# ══════════════════════════════════════════════════════════
#  Tab 5: 积分榜
# ══════════════════════════════════════════════════════════

def render_standings_table(guoan_matches, standings, guoan_ded):
    """渲染国安赛季全览 — 每轮赛果+累计积分+排名变化（同步 V7 右栏）"""
    st.markdown("**国安赛季全览**")
    cum_pts = 0
    prev_rank = None
    for m in guoan_matches:
        if not m["date"].startswith("2026"):
            continue
        rnd = m["round"]
        ds = m["date"][5:]
        opp = m["opponent"]
        vs = "vs" if m["is_home"] else "@ "
        if m.get("completed"):
            if m["is_home"]:
                res = "W" if m["hg"] > m["ag"] else "D" if m["hg"] == m["ag"] else "L"
                sc = f"{m['hg']}-{m['ag']}"
            else:
                res = "W" if m["ag"] > m["hg"] else "D" if m["ag"] == m["hg"] else "L"
                sc = f"{m['ag']}-{m['hg']}"
            cum_pts += 3 if res == "W" else 1 if res == "D" else 0
            rank = standings.get(rnd, {}).get("北京国安", "?")
            rd = ""
            if prev_rank and isinstance(rank, int) and isinstance(prev_rank, int):
                if rank < prev_rank:
                    rd = f'<span class="rank-up">↑{prev_rank - rank}</span>'
                elif rank > prev_rank:
                    rd = f'<span class="rank-down">↓{rank - prev_rank}</span>'
            prev_rank = rank
            crest_s = team_crest_html(opp, "sm")
            st.markdown(
                f'<div class="season-row done">'
                f'<span style="color:#62666d;width:55px">{rnd} {ds}</span>'
                f'<span style="width:95px">{crest_s} {vs} {opp}</span>'
                f'<span style="width:45px;text-align:center">{sc}</span>'
                f'<span class="{res}" style="width:20px;text-align:center">{res}</span>'
                f'<span class="pts" style="width:40px;text-align:right">{cum_pts}分</span>'
                f'<span style="width:50px;text-align:right">#{rank} {rd}</span>'
                f'</div>', unsafe_allow_html=True
            )
        else:
            eff = cum_pts - guoan_ded
            crest_s = team_crest_html(opp, "sm")
            st.markdown(
                f'<div class="season-row">'
                f'<span class="muted" style="width:55px">{rnd} {ds}</span>'
                f'<span class="muted" style="width:95px">{crest_s} {vs} {opp}</span>'
                f'<span class="muted" style="width:45px;text-align:center">——</span>'
                f'<span class="muted" style="width:20px;text-align:center">-</span>'
                f'<span style="color:#8a8f98;width:40px;text-align:right">{cum_pts}分</span>'
                f'<span class="muted" style="width:50px;text-align:right">(有效{eff})</span>'
                f'</div>', unsafe_allow_html=True
            )


# ══════════════════════════════════════════════════════════
#  Tab 7: 座位热力图
# ══════════════════════════════════════════════════════════

@st.cache_data(ttl=86400)
def _get_section_capacities():
    """用 2026 赛季各区最大销量 × 1.05 作为容量基准。

    仅使用 2026 年数据，避免跨年分区变化导致容量虚高
    （2023-2025 工体改造前分区结构与新工体不同）。
    """
    csl = _get_csl_parquet()
    if csl is None:
        return {}
    csl_2026 = csl[csl["match_date"].astype(str).str.startswith("2026")]
    if csl_2026.empty:
        csl_2026 = csl  # fallback
    per_match = csl_2026.groupby(["match_date", "section"])["数量"].sum().reset_index()
    caps = per_match.groupby("section")["数量"].max().to_dict()
    return {str(s): int(v * 1.05) + 1 for s, v in caps.items()}


def _compute_match_fill_rates(match_date: str):
    """计算某场每个分区的上座率。返回 {section_number_str: fill_rate}。"""
    csl = _get_csl_parquet()
    if csl is None:
        return {}, {}, 0.0

    md = csl[csl["match_date"].astype(str).str.startswith(match_date)]
    if md.empty:
        return {}, {}, 0.0

    caps = _get_section_capacities()
    md_copy = md.copy()
    md_copy["section"] = md_copy["section"].astype(str)
    section_qty = md_copy.groupby("section")["数量"].sum()

    section_fills = {}
    section_rev_contrib = {}
    total_sold = 0; total_cap = 0; total_rev = 0

    # 每区销量+收入
    md_rev = md_copy.groupby("section").agg(
        qty=("数量", "sum"), rev=("实际支付价格", "sum")
    )
    for sec, row in md_rev.iterrows():
        sec_str = str(sec)
        cap = caps.get(sec_str, row["qty"])
        section_fills[sec_str] = row["qty"] / max(cap, 1)
        total_sold += row["qty"]
        total_cap += cap
        total_rev += row["rev"]

    total_fill = total_sold / max(total_cap, 1)
    for sec, row in md_rev.iterrows():
        sec_str = str(sec)
        section_rev_contrib[sec_str] = row["rev"] / max(total_rev, 1) if total_rev > 0 else 0

    return section_fills, dict(section_qty), total_fill, section_rev_contrib, total_rev


def render_heatmap_tab(guoan_matches):
    """座位热力图 Tab — SVG热力图(销量着色) + 热力带分布。"""

    home_done = [m for m in guoan_matches if m.get("is_home") and m.get("completed")
                 and m["date"].startswith("2026")]
    if not home_done:
        st.info("暂无已赛主场数据")
        return

    c1, c2 = st.columns([3, 1])
    match_options = {f"{m['date']} vs {m['opponent']}": m for m in home_done}
    with c1:
        selected_label = st.selectbox(
            "选择比赛", list(match_options.keys()),
            index=len(match_options) - 1, key="heatmap_match", label_visibility="collapsed"
        )
    selected = match_options[selected_label]
    opp, match_date = selected["opponent"], selected["date"]

    section_fills, section_qty, total_fill, section_rev, total_revenue = _compute_match_fill_rates(match_date)
    total_sold = sum(section_qty.values())
    # 联票修正（四场联票573张/场，未分区，仅在总量体现）
    from src.match_notes import get_adjusted_actual
    match_id_full = f"{match_date} {opp}"
    adj_total = get_adjusted_actual(match_id_full, total_sold)
    bundle_note = f"（含联票+{adj_total - total_sold:.0f}张）" if adj_total > total_sold else ""

    if not section_qty:
        st.warning("该场比赛暂无分区销售数据")
        return

    with c2:
        st.metric("总售出" if not bundle_note else f"总售出{bundle_note}", f"{adj_total:,}张")

    # ── 热力图 (颜色=上座率) ──
    match_label = f"{match_date}  vs  {opp}"
    heatmap_html = render_gongti_heatmap(section_fills, section_fills, match_label, total_fill)
    # iframe 高度由组件内 JS 按视口动态上报；此处仅作首屏占位（PC 偏大、手机偏小均可被覆盖）
    st.components.v1.html(heatmap_html, height=520, scrolling=False)

    # ── 销售概况 ──
    if section_qty:
        sorted_items = sorted(
            [(s, q, section_fills.get(s, 0)) for s, q in section_qty.items()],
            key=lambda x: -x[2]
        )
        top5 = sorted_items[:8]
        bot5 = sorted_items[-8:][::-1]

        hot_str = " · ".join(f'{s}({fr*100:.0f}%)' for s, q, fr in top5)
        cold_str = " · ".join(f'{s}({fr*100:.0f}%)' for s, q, fr in bot5)

        high_regions = [s for s, q, fr in sorted_items if fr >= 0.90]
        low_regions = [s for s, q, fr in sorted_items if fr < 0.40]
        mid_regions = [s for s, q, fr in sorted_items if 0.40 <= fr < 0.90]

        suggestion_parts = []
        if high_regions:
            suggestion_parts.append(f"📈 {len(high_regions)}区上座率≥90% → 核心区可考虑上调5-10%")
        if low_regions:
            suggestion_parts.append(f"📉 {len(low_regions)}区上座率<40% → 外围区建议促销拉量")
        if mid_regions:
            suggestion_parts.append(f"📊 {len(mid_regions)}区在40-90% → 维持现价观察")
        suggestion = "<br>".join(suggestion_parts) if suggestion_parts else "✅ 各分区上座均衡"

        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(
                f'<div class="kpi-card" style="border-top:2px solid #ff6b6b !important">'
                f'<div class="kpi-label">🔥 上座率最高区</div>'
                f'<div style="font-size:0.72rem;color:#c0c4c8;line-height:1.6">{hot_str}</div>'
                f'</div>', unsafe_allow_html=True)
        with c2:
            st.markdown(
                f'<div class="kpi-card" style="border-top:2px solid #51cf66 !important">'
                f'<div class="kpi-label">❄️ 上座率最低区</div>'
                f'<div style="font-size:0.72rem;color:#c0c4c8;line-height:1.6">{cold_str}</div>'
                f'</div>', unsafe_allow_html=True)
        with c3:
            st.markdown(
                f'<div class="kpi-card" style="border-top:2px solid #f0c040 !important">'
                f'<div class="kpi-label">💡 定价建议</div>'
                f'<div style="font-size:0.72rem;color:#c0c4c8;line-height:1.6">{suggestion}</div>'
                f'</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════

def main():
    load_css()

    with st.spinner("加载 CSL 数据..."):
        all_matches, rounds, guoan_matches = load_data()
    if not guoan_matches:
        st.error("无法加载 CSL 数据，请刷新重试")
        if st.button("🔄 刷新重试"):
            st.rerun()
        st.stop()

    global _ctx_rounds
    _ctx_rounds = rounds

    # Build standings (2026-only)
    standings = build_standings_2026(all_matches)

    # Split matches
    home_matches = [m for m in guoan_matches if m.get("is_home")]
    home_done = [m for m in home_matches if m.get("completed")]
    completed = [m for m in guoan_matches if m.get("completed") and m["date"].startswith("2026")]

    # Season stats
    total_pts = sum(
        3 if (m["is_home"] and m["hg"] > m["ag"]) or (not m["is_home"] and m["ag"] > m["hg"])
        else 1 if m["hg"] == m["ag"] else 0
        for m in completed
    )
    guoan_ded = DEDUCTIONS.get("北京国安", 0)
    latest_rnd = max(standings.keys(), key=_round_num, default=None)
    guoan_rank = standings.get(latest_rnd, {}).get("北京国安", "?") if latest_rnd else "?"
    home_w = sum(1 for m in home_done if m["hg"] > m["ag"])
    home_d = sum(1 for m in home_done if m["hg"] == m["ag"])
    home_l = sum(1 for m in home_done if m["hg"] < m["ag"])

    # Title bar
    crest = guoan_crest_b64()
    csl = csl_logo_b64()
    crest_img = f'<img class="crest" src="{crest}" alt="国安">' if crest else ""
    csl_img = f'<img class="csl-logo" src="{csl}" alt="CSL">' if csl else ""
    st.markdown(f"""<div class="brand-header">
      <div style="display:flex;align-items:center;gap:10px">
        {crest_img}
        <h1>北京国安 · 动态定价</h1>
        {csl_img}
      </div>
      <div class="state-bar" style="margin-left:auto">
        <strong>#{guoan_rank}</strong> {total_pts}分
        <span style="color:#62666d">(扣{guoan_ded}分)</span>
        | 主场 {home_w}-{home_d}-{home_l}
        | 已赛{len(completed)}/30轮
      </div>
    </div>""", unsafe_allow_html=True)

    # Recent form
    recent5 = completed[-5:]
    form_icons = []
    form_str = ""
    for m in recent5:
        res = "W" if (m["is_home"] and m["hg"] > m["ag"]) or (not m["is_home"] and m["ag"] > m["hg"]) else "D" if m["hg"] == m["ag"] else "L"
        form_icons.append(f'<span class="{res}">{res}</span>')
        form_str += res
    if form_icons:
        st.caption("近5场: " + " · ".join(form_icons), unsafe_allow_html=True)

    # Compute home predictions (used by all tabs)
    home_preds = compute_home_predictions(home_done, guoan_matches)

    # Find next/future matches
    next_match = next((m for m in guoan_matches if not m["completed"] and m["date"].startswith("2026")), None)
    next_home = next((m for m in guoan_matches if not m["completed"] and m["is_home"] and m["date"].startswith("2026")), None)

    # Determine target match (away → next home)
    if next_match and next_match["is_home"]:
        target_match = next_match
    elif next_home:
        target_match = next_home
    else:
        target_match = None

    # ══ KPI Cards (removed for mobile UX) ══
    preds_arr = np.array([p for _, p, _, _ in home_preds])
    actuals_arr = np.array([a for _, _, a, _ in home_preds])
    mae = np.mean(np.abs(preds_arr - actuals_arr)) if len(preds_arr) > 0 else 0
    # 赛季进度条
    pct = len(home_preds) / 15 * 100
    st.markdown(f"""<div class="progress-line">
      <div class="progress-label"><span>赛季主场进度</span><span>{len(home_preds)}/15</span></div>
      <div class="progress-track"><div class="progress-fill" style="width:{pct}%"></div></div>
    </div>""", unsafe_allow_html=True)

    # ══ Tabs ══
    tabs = st.tabs(["🎯 下一场预测", "📋 历史定价", "🔍 对手分析", "🏆 积分榜", "📊 H2策略", "🔥 座位热力图"])

    # ── Tab 0: 下一场预测 ──
    with tabs[0]:
        if next_match and not next_match["is_home"]:
            st.info(f"📅 下一场 {next_match['date']} @ {next_match['opponent']} 为客场")
            if next_home:
                st.caption(f"最近主场：{next_home['date']} vs {next_home['opponent']}")
        if target_match:
            render_tab1(target_match, home_preds, guoan_matches, standings, mae)
        else:
            st.info("无未来主场")
        st.caption("💡 详细场景切换 + 瀑布图 → **H2策略** TAB")

    # ── Tab 2: 历史定价 ──
    with tabs[1]:
        # 累计KPI
        opt_kpi = get_optimizer()
        cum_scene_qty = 0; cum_delta_qty = 0; cum_scene_rev = 0; cum_delta_rev = 0
        for m, pred, actual, ctx in home_preds:
            opp = m["opponent"]; dt_m = pd.Timestamp(m["date"])
            is_first = (m == home_preds[0])
            ub3 = ctx.get('unbeaten_3', False)
            pred_args = build_pred_args(m, ctx, {'season_opener': is_first, 'unbeaten_3': ub3,
                                                  'summer': dt_m.month in [7,8], 'match_year': m["date"][:4]})
            r_h = opt_kpi.optimize(opp, **pred_args)
            zone_rev = _get_zone_actual_revenue(m)
            total_actual_rev = sum(zone_rev.values())
            total_actual_qty = actual
            cum_scene_qty += r_h.total_attendance
            cum_delta_qty += r_h.total_attendance - total_actual_qty
            cum_scene_rev += r_h.total_revenue
            cum_delta_rev += r_h.total_revenue - total_actual_rev

        kc1, kc2, kc3, kc4 = st.columns(4)
        with kc1:
            st.markdown(f"""<div class="kpi-card">
              <div class="kpi-label">累计场景量</div>
              <div class="kpi-value">{cum_scene_qty:,.0f}张</div>
            </div>""", unsafe_allow_html=True)
        with kc2:
            qty_color = "#ff6b6b" if cum_delta_qty > 0 else "#51cf66"
            st.markdown(f"""<div class="kpi-card">
              <div class="kpi-label">累计Δ量</div>
              <div class="kpi-value" style="color:{qty_color}">{cum_delta_qty:+,.0f}张</div>
            </div>""", unsafe_allow_html=True)
        with kc3:
            st.markdown(f"""<div class="kpi-card">
              <div class="kpi-label">累计场景收入</div>
              <div class="kpi-value">¥{cum_scene_rev/1e4:.1f}万</div>
            </div>""", unsafe_allow_html=True)
        with kc4:
            rev_color = "#ff6b6b" if cum_delta_rev > 0 else "#51cf66"
            st.markdown(f"""<div class="kpi-card">
              <div class="kpi-label">累计Δ收入</div>
              <div class="kpi-value" style="color:{rev_color}">¥{cum_delta_rev/1e4:+.1f}万</div>
            </div>""", unsafe_allow_html=True)

        render_mae_chart(home_preds)
        render_history_expanders(home_preds, guoan_matches)

    # ── Tab 3: 对手分析 ──
    with tabs[2]:
        render_opponent_analysis(all_matches)

    # ── Tab 4: 积分榜 ──
    with tabs[3]:
        render_standings_table(guoan_matches, standings, guoan_ded)

    # ── Tab 5: H2策略 ──
    with tabs[4]:
        render_h2_strategy(guoan_matches, standings)

    # ── Tab 6: 座位热力图 ──
    with tabs[5]:
        render_heatmap_tab(guoan_matches)

    st.caption("V8.1 · 国安绿品牌 · 决策工作台")


if __name__ == "__main__":
    main()
