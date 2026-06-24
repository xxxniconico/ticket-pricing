"""
FIFA 世界杯赔率 + 战绩看板 V5 (重写)
====================================

独立 Streamlit app, 端口 8507 (云端: ?app=fifa)
设计语言: 参照 FIFA.com / Flashscore / SofaScore / OddsPortal
- FIFA 蓝 (#326295) + 金 (#93764d) 主色
- 比赛作为"行" (CSS Grid .match-row), 紧凑高密度
- 国旗圆形锚 + mono 字体 + Group chip
- 状态色彩编码 (FT / LIVE / NS)

V5 重写要点:
1. cn() 先 html.unescape, 再去 's / men's 后缀, 48 国家队全覆盖
2. 移除旧 KPI 里的 placeholder 空循环
3. render_header 对 None 字段稳健
4. 已赛按 Group A-L 渲染, 未赛按日期排序
5. 赔率列显示主/平/客 3 列, 用 .odd.best 高亮最低赔率 (隐含概率最高)

数据源 (只读):
- data/processed/wc_2026_unified.json  (69 场: 33 已赛 + 36 未赛)

作者: Hermes Agent
日期: 2026-06-21
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path

import streamlit as st

# === 路径 ===
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
for _p in (str(ROOT), str(SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

UNIFIED_FILE = ROOT / "data" / "processed" / "wc_2026_unified.json"
CSS_FILE = ROOT / "dashboard" / "assets" / "fifa_style.css"

# === 48 国家队英文 → (中文, 国旗) ===
# 注意:
# - Canada / USA / Australia 等的 "men's" 变体在 cn() 里归一化后也命中这里
# - Scotland / England 用 gb-sct / gb-eng (flagcdn 的 sub-region code)
# - 字段顺序: 中文名, ISO 3166-1 alpha-2 code (用于 flagcdn.com URL)
TEAM_CN: dict[str, tuple[str, str]] = {
    # A
    "Mexico":               ("墨西哥", "mx"),
    "South Africa":         ("南非", "za"),
    "South Korea":          ("韩国", "kr"),
    "Czech Republic":       ("捷克", "cz"),
    # B
    "Canada":               ("加拿大", "ca"),
    "Bosnia and Herzegovina": ("波黑", "ba"),
    "Qatar":                ("卡塔尔", "qa"),
    "Switzerland":          ("瑞士", "ch"),
    # C
    "Brazil":               ("巴西", "br"),
    "Morocco":              ("摩洛哥", "ma"),
    "Haiti":                ("海地", "ht"),
    "Scotland":             ("苏格兰", "gb-sct"),
    # D
    "USA":                  ("美国", "us"),
    "United States":        ("美国", "us"),
    "Paraguay":             ("巴拉圭", "py"),
    "Australia":            ("澳大利亚", "au"),
    "Turkey":               ("土耳其", "tr"),
    # E
    "Germany":              ("德国", "de"),
    "Curaçao":              ("库拉索", "cw"),
    "Curacao":              ("库拉索", "cw"),
    "Ivory Coast":          ("科特迪瓦", "ci"),
    "Ecuador":              ("厄瓜多尔", "ec"),
    "Netherlands":          ("荷兰", "nl"),
    # F
    "Japan":                ("日本", "jp"),
    "Sweden":               ("瑞典", "se"),
    "Tunisia":              ("突尼斯", "tn"),
    "Belgium":              ("比利时", "be"),
    "Egypt":                ("埃及", "eg"),
    # G
    "Iran":                 ("伊朗", "ir"),
    "New Zealand":          ("新西兰", "nz"),
    "Spain":                ("西班牙", "es"),
    "Cape Verde":           ("佛得角", "cv"),
    "Saudi Arabia":         ("沙特", "sa"),
    # H
    "Uruguay":              ("乌拉圭", "uy"),
    "France":               ("法国", "fr"),
    "Senegal":              ("塞内加尔", "sn"),
    "Iraq":                 ("伊拉克", "iq"),
    "Norway":               ("挪威", "no"),
    # I
    "Argentina":            ("阿根廷", "ar"),
    "Algeria":              ("阿尔及利亚", "dz"),
    "Austria":              ("奥地利", "at"),
    "Jordan":               ("约旦", "jo"),
    # J
    "Portugal":             ("葡萄牙", "pt"),
    "DR Congo":             ("刚果(金)", "cd"),
    "Uzbekistan":           ("乌兹别克斯坦", "uz"),
    "Colombia":             ("哥伦比亚", "co"),
    # K
    "England":              ("英格兰", "gb-eng"),
    "Croatia":              ("克罗地亚", "hr"),
    "Ghana":                ("加纳", "gh"),
    "Panama":               ("巴拿马", "pa"),
}

# 国旗 CDN — flagcdn.com 提供 PNG, 尺寸 w20/w40/w80/w160/w320/w640/w1280/w2560
FLAG_BASE_URL = "https://flagcdn.com"
FLAG_WIDTH = 40  # px, 适合 ~32px 圆形容器

# Wikipedia / Wikidata 常见后缀变体 (在 cn() 里被剥掉)
_SUFFIX_PATTERNS = [
    re.compile(r"\s+men'?s?\s*$", re.IGNORECASE),
    re.compile(r"\s+women'?s?\s*$", re.IGNORECASE),
    re.compile(r"\s+national\s+team\s*$", re.IGNORECASE),
    re.compile(r"\s+national\s+football\s+team\s*$", re.IGNORECASE),
]


def normalize_team(name: str) -> str:
    """球队名归一化: unescape HTML 实体 → 去 men's / women's / national team 后缀
    → & 标准化为 'and' (Bosnia & Herzegovina → Bosnia and Herzegovina)
    """
    if not name:
        return ""
    s = unescape(name).strip()
    # Bosnia & Herzegovina / Bosnia and Herzegovina → 同一 key
    s = s.replace(" & ", " and ")
    for pat in _SUFFIX_PATTERNS:
        s = pat.sub("", s)
    return s.strip()


def cn(name: str) -> tuple[str, str]:
    """球队名 → (中文, ISO 3166-1 alpha-2 code).

    调用方用 flag_img(iso) 生成 <img> 标签 (真实国旗 PNG from flagcdn.com).

    测试用例:
      cn("Canada men&#39;s")     -> ("加拿大", "ca")
      cn("USA")                  -> ("美国",   "us")
      cn("Bosnia & Herzegovina") -> ("波黑",   "ba")
      cn("Scotland")             -> ("苏格兰", "gb-sct")
      cn("England")              -> ("英格兰", "gb-eng")
    """
    if not name:
        return ("?", "")
    # 先按原名查
    if name in TEAM_CN:
        return TEAM_CN[name]
    # 归一化后再查 (处理 men's / Bosnia & Herzegovina 等变体)
    norm = normalize_team(name)
    if norm in TEAM_CN:
        return TEAM_CN[norm]
    # 已归一化但仍缺 → 返回归一化名 + 空 code (后续降级用 emoji fallback)
    return (norm or "?", "")


def flag_img(iso_code: str, fallback: str = "🏳️") -> str:
    """生成 <img> 国旗标签, CDN 失败时显示 emoji fallback.

    flagcdn.com 提供 24x24 / 48x48 / 80x80 等真实国旗 PNG.
    """
    if not iso_code:
        return f'<span class="flag-emoji">{fallback}</span>'
    return (
        f'<img src="{FLAG_BASE_URL}/w{FLAG_WIDTH}/{iso_code}.png" '
        f'class="flag-img" alt="{iso_code}" '
        f'loading="lazy" '
        f'onerror="this.outerHTML=\'<span class=flag-emoji>{fallback}</span>\'"/>'
    )


def emoji_flag(iso_code: str) -> str:
    """ISO 3166-1 alpha-2 code → emoji regional indicator 序列.

    每个字母转成对应的 regional indicator symbol (A=🇦 ... Z=🇿).
    例: 'mx' → 🇲🇽, 'gb-eng' → 🏴󠁧󠁢󠁥󠁮󠁧󠁿.

    注: 当前 button label 不需要 emoji (用纯文本 + 真实国旗图), 此函数保留作为备用工具.
    """
    if not iso_code:
        return "🏳️"
    iso = iso_code.lower()
    special = {"gb-sct": "🏴󠁧󠁢󠁳󠁣󠁴󠁿", "gb-eng": "🏴󠁧󠁢󠁥󠁮󠁧󠁿"}
    if iso in special:
        return special[iso]
    if len(iso) == 2 and iso.isalpha():
        return chr(0x1F1E6 + ord(iso[0]) - ord("a")) + chr(0x1F1E6 + ord(iso[1]) - ord("a"))
    return "🏳️"


# === 页面配置 ===
st.set_page_config(
    page_title="FIFA 2026 赔率看板",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items=None,  # 隐藏右上角 hamburger
)


# === 工具 ===
# 兼容老版本 streamlit (<1.31 没有 st.html)
HTML_RENDERER = getattr(st, "html", None)
def render_html(html: str) -> None:
    """统一 HTML 渲染入口. 新版本用 st.html, 老版本 fallback"""
    if HTML_RENDERER is not None:
        HTML_RENDERER(html)
    else:
        st.markdown(html, unsafe_allow_html=True)


def inject_css() -> None:
    """注入 FIFA 专属 CSS (style 标签必须用 markdown, 否则被解析)"""
    if CSS_FILE.exists():
        css = CSS_FILE.read_text(encoding="utf-8")
        # <style> 必须用 markdown, 否则 <style> 内的 {} 会被 f-string 解析
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


@st.cache_data(ttl=300)
def _load_unified() -> list[dict] | None:
    if not UNIFIED_FILE.exists():
        return None
    return json.loads(UNIFIED_FILE.read_text(encoding="utf-8"))


def _to_bj(iso: str) -> datetime:
    """ISO UTC → 北京时间 (naive)"""
    return datetime.fromisoformat(iso.replace("Z", "")) + timedelta(hours=8)


def _now_utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _format_score(score: str) -> str:
    """把 '2-1' 或 '2–1' 都渲染成 '2 <span class="sep">–</span> 1'"""
    if not score:
        return "–"
    parts = re.split(r"[-–—]", score, maxsplit=1)
    if len(parts) != 2:
        return score
    return f'{parts[0]} <span class="sep">–</span> {parts[1]}'


# === Header ===
def render_header(finished_total: int, unfinished_total: int, next_match: dict | None) -> None:
    """FIFA 蓝品牌 header + 下一场倒计时"""
    if next_match:
        utc = datetime.fromisoformat(next_match["commence_time"].replace("Z", ""))
        now = _now_utc_naive()
        diff = utc.replace(tzinfo=None) - now
        if diff.total_seconds() > 0:
            days = int(diff.total_seconds() // 86400)
            hours = int((diff.total_seconds() % 86400) // 3600)
            mins = int((diff.total_seconds() % 3600) // 60)
            countdown = f"<strong>{days}d {hours}h {mins}m</strong>"
            countdown_label = "下一场开赛"
            home_cn, _ = cn(next_match.get("home_en", ""))
            away_cn, _ = cn(next_match.get("away_en", ""))
            match_str = f" · {home_cn} vs {away_cn}"
        else:
            countdown = "<strong>LIVE</strong>"
            countdown_label = "进行中"
            match_str = ""
    else:
        countdown = "—"
        countdown_label = "已完赛"
        match_str = ""

    html = f"""
    <div class="fifa-header">
      <h1>🌍 FIFA 世界杯 2026 · 赔率看板</h1>
      <p class="subtitle">{finished_total} 已赛 · {unfinished_total} 未赛 · 数据源 The Odds API + Wikipedia{match_str}</p>
      <div class="countdown">⏱ {countdown_label}: {countdown}</div>
    </div>
    """
    render_html(html)


# === KPI ===
def render_kpi_strip(finished: int, unfinished: int, groups_done: int) -> None:
    """紧凑 KPI 条 (4 列): 总场次 / 已赛 / 未赛 / 小组"""
    total = finished + unfinished
    html = f"""
    <div class="kpi-strip">
      <div class="kpi-cell">
        <span class="kpi-icon">🏟️</span>
        <div class="kpi-text">
          <span class="kpi-value">{total}</span>
          <span class="kpi-label">总场次</span>
        </div>
      </div>
      <div class="kpi-cell">
        <span class="kpi-icon">✅</span>
        <div class="kpi-text">
          <span class="kpi-value">{finished}</span>
          <span class="kpi-label">已完赛 FT</span>
        </div>
      </div>
      <div class="kpi-cell">
        <span class="kpi-icon">⏳</span>
        <div class="kpi-text">
          <span class="kpi-value">{unfinished}</span>
          <span class="kpi-label">未开赛</span>
        </div>
      </div>
      <div class="kpi-cell">
        <span class="kpi-icon">🅰️</span>
        <div class="kpi-text">
          <span class="kpi-value">{groups_done}</span>
          <span class="kpi-label">已开赛小组</span>
        </div>
      </div>
    </div>
    """
    render_html(html)


# === 行渲染 (用 streamlit 原生 columns + 每段独立 markdown) ===
# 不依赖 st.html / st.markdown 大块 HTML, 避免 markdown 解析破坏嵌套 div
# 每个 cell 一个独立 st.markdown(unsafe_allow_html=True) 单段 HTML, 兼容性最好

def _match_time_html(m: dict) -> str:
    iso = m.get("commence_time")
    if not iso:
        return '<div class="m-time">—</div>'
    bj = _to_bj(iso)
    utc = datetime.fromisoformat(iso.replace("Z", ""))
    diff_min = (utc.replace(tzinfo=None) - _now_utc_naive()).total_seconds() / 60
    if -120 <= diff_min <= 0:
        return '<div class="m-time live">LIVE</div>'
    return f'<div class="m-time">{bj.strftime("%m-%d %H:%M")}</div>'



@st.cache_data(ttl=3600)
def _get_elo_tiers():
    from wc_betting.models.elo import EloModel
    elo = EloModel(); elo.calibrate()
    ratings = {}
    for t in TEAM_CN:
        try: ratings[t] = elo.elo_of(t)
        except: ratings[t] = 1500
    sorted_teams = sorted(ratings.items(), key=lambda x: -x[1])
    n = len(sorted_teams)
    tiers = {}
    for i, (team, _) in enumerate(sorted_teams):
        if i < 8: tiers[team] = 1
        elif i < 20: tiers[team] = 2
        elif i < 36: tiers[team] = 3
        else: tiers[team] = 4
    return tiers

def tier_badge(team_en):
    tiers = _get_elo_tiers()
    t = tiers.get(team_en, 4)
    colors = {1: '#ffd700', 2: '#c0c0c0', 3: '#cd7f32', 4: '#888'}
    return '<span class=tier-badge style=background:' + colors[t] + ';color:#000;padding:0 6px;border-radius:3px;font-size:0.7rem;font-weight:700>T' + str(t) + '</span>'

def render_match_row_upcoming(m: dict) -> None:
    """未赛比赛行 - 用 st.columns + 每段单独 st.markdown"""
    home_cn, home_flag = cn(m.get("home_en", ""))
    away_cn, away_flag = cn(m.get("away_en", ""))
    grp = m.get("group", "?")
    time_html = _match_time_html(m)
    home_flag_img = flag_img(home_flag)
    away_flag_img = flag_img(away_flag)

    # 赔率
    metrics = m.get("metrics") or {}
    h = float(metrics.get("avg_h") or 0)
    d = float(metrics.get("avg_d") or 0)
    a = float(metrics.get("avg_a") or 0)
    odds = [(h, "主"), (d, "平"), (a, "客")]
    if h > 0 and d > 0 and a > 0:
        best_val = min(odds, key=lambda x: x[0])[0]
    else:
        best_val = None

    # === 用单个 st.markdown 渲染整行 (CSS grid 处理响应式) ===
    # 第一行: 时间 | 主队 | vs | 客队 | 占位 | Group chip
    row1_html = f"""<div class="match-row">
      {time_html}
      <div class="m-team home"><span class="flag">{home_flag_img}</span><span>{home_cn}</span></div>
      <div class="m-score"><span class="vs">vs</span></div>
      <div class="m-team away"><span class="flag">{away_flag_img}</span><span>{away_cn}</span></div>
      <div></div>
      <div class="m-status">{tier_badge(m.get("home_en",""))} <span class="badge group">Group {grp}</span> {tier_badge(m.get("away_en",""))}</div>
    </div>"""
    st.markdown(row1_html, unsafe_allow_html=True)

    # === 第二行: 赔率 + 概率 (全宽) ===
    if best_val is not None:
        odds_html = ""
        for val, label in odds:
            cls = "odd best" if val == best_val else "odd"
            odds_html += f'<div class="{cls}"><span class="label">{label}</span><span class="value">{val:.2f}</span></div>'

        p_html = ""
        p_h = float(metrics.get("p_h_mean") or 0)
        if p_h > 0 and h > 0 and d > 0 and a > 0:
            raw = 1/h + 1/d + 1/a
            p_h_nv = (1/h) / raw
            p_d_nv = (1/d) / raw
            p_a_nv = (1/a) / raw
            probs = [p_h_nv, p_d_nv, p_a_nv]
            max_idx = max(range(3), key=lambda i: probs[i])
            hl = ["", "", ""]
            hl[max_idx] = " highlight"
            p_html = (
                '<div class="m-prob">'
                f'<span class="prob{hl[0]}"><span class="label">主</span><span class="value">{p_h_nv:.0%}</span></span>'
                f'<span class="prob{hl[1]}"><span class="label">平</span><span class="value">{p_d_nv:.0%}</span></span>'
                f'<span class="prob{hl[2]}"><span class="label">客</span><span class="value">{p_a_nv:.0%}</span></span>'
                '</div>'
            )
        stack_html = f'<div class="m-stack"><div class="m-odds">{odds_html}</div>{p_html}</div>'
        st.markdown(stack_html, unsafe_allow_html=True)


# === 赛季总进度 (统一的页面头部, 两个 Tab 共享) ===
def render_season_progress(finished: list[dict], upcoming: list[dict]) -> None:
    """统一的赛季进度条 + 倒计时 + 刷新按钮. 显示在两个 Tab 之上, 不会被 tab 包裹"""
    # 进度条
    finished_count = len(finished)
    upcoming_count = len(upcoming)
    total_count = finished_count + upcoming_count
    pct_done = finished_count / total_count if total_count > 0 else 0

    progress_html = f"""
    <div class="overall-progress">
      <span class="label">赛季进度</span>
      <div class="track"><div class="fill" style="width:{pct_done*100:.1f}%"></div></div>
      <span class="value">{finished_count} / {total_count} ({pct_done*100:.0f}%)</span>
    </div>
    """
    render_html(progress_html)

    # 手动刷新按钮 + 数据时间戳 (也统一在头部)
    rc1, rc2, rc3 = st.columns([1, 1, 4])
    with rc1:
        if st.button("🔄 立即刷新数据", use_container_width=True):
            _load_unified.clear()
            st.rerun()
    with rc2:
        try:
            mtime = UNIFIED_FILE.stat().st_mtime
            last_update = datetime.fromtimestamp(mtime)
            st.caption(f"📅 数据更新: {last_update.strftime('%m-%d %H:%M')}")
        except Exception:
            st.caption("📅 数据更新时间未知")


# === 已赛区块 ===
def render_finished_section(finished: list[dict]) -> None:
    """已赛区块: 2 列紧凑网格, 默认折叠. 进度条在外部 render_season_progress 渲染"""
    # 初始化 session_state
    if "expanded_groups" not in st.session_state:
        st.session_state.expanded_groups = set()

    # 标题 + 全局展开/折叠按钮 (Tab2 内部)
    # === 标题 + 全局展开/折叠按钮 ===
    st.markdown(f"### ✅ 已赛 {len(finished)} 场 · 按小组")
    cs1, cs2 = st.columns([1, 1])
    with cs1:
        if st.button("📂 展开全部", use_container_width=True, key="expand_all_finished"):
            st.session_state.expanded_groups = {"ALL"}
    with cs2:
        if st.button("📁 折叠全部", use_container_width=True, key="collapse_all_finished"):
            st.session_state.expanded_groups = set()

    by_group: dict[str, list[dict]] = defaultdict(list)
    for m in finished:
        by_group[m.get("group", "?")].append(m)

    # 收集有比赛的 group (按 A-L 顺序)
    active_groups = [g for g in "ABCDEFGHIJKL" if g in by_group]

    # === 12 个 Group, 每个 1 行, 整行可点击展开/折叠 ===
    # 用 streamlit button + 视觉跟 cell 一样
    for grp in active_groups:
        matches = by_group[grp]
        # 收集该组 4 队
        teams: list[str] = []
        for m in matches:
            for t in [m.get("home_en", ""), m.get("away_en", "")]:
                if t and t not in teams:
                    teams.append(t)
            if len(teams) >= 4:
                break

        done = len(matches)
        is_expanded = grp in st.session_state.expanded_groups or "ALL" in st.session_state.expanded_groups

        # 整行 markdown card (Group chip + 国旗 + 进度 + 队名)
        flags_html = "".join(flag_img(cn(t)[1]) for t in teams[:4])
        team_names = [cn(t)[0] for t in teams[:4]]
        teams_str = " · ".join(team_names)

        # 用 columns 让 card 占大部分, button 占小部分
        card_col, btn_col = st.columns([9, 1], gap="small")

        with card_col:
            render_html(f"""
            <div class="group-card {'expanded' if is_expanded else 'collapsed'}" data-group="{grp}">
              <div class="group-card-left">
                <span class="group-chip">Group {grp}</span>
                <span class="group-progress">{done}<span class="dim">/6</span></span>
              </div>
              <div class="group-card-flags">{flags_html}</div>
              <span class="group-card-teams">{teams_str}</span>
            </div>
            """)

        with btn_col:
            state_arrow = "▼" if is_expanded else "▶"
            # button 取消 padding 让它跟 card 同高
            if st.button(state_arrow, key=f"toggle_{grp}", use_container_width=True):
                if grp in st.session_state.expanded_groups:
                    st.session_state.expanded_groups.remove(grp)
                else:
                    st.session_state.expanded_groups.add(grp)
                st.rerun()

        # === 展开内容紧贴 button 下方 (穿插到 group 之间) ===
        if is_expanded:
            standings = _compute_standings(matches)
            render_standings(standings, grp)
            rows_html = "".join(_finished_row_html(m) for m in matches)
            render_html(f'<div class="match-list expanded expanded-section">{rows_html}</div>')


def _compute_standings(matches: list[dict]) -> list[dict]:
    """从已赛比赛算积分 + 净胜球. FIFA 规则: 胜=3 平=1 负=0"""
    stats: dict[str, dict] = defaultdict(lambda: {
        "pts": 0, "mp": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0,
    })
    for m in matches:
        score = (m.get("score") or "").replace("–", "-").replace("—", "-").replace("−", "-")
        if "-" not in score:
            continue
        try:
            h, a = score.split("-")
            h, a = int(h.strip()), int(a.strip())
        except (ValueError, AttributeError):
            continue
        h_team, a_team = m.get("home_en", ""), m.get("away_en", "")
        if not h_team or not a_team:
            continue
        # 累加
        for team in (h_team, a_team):
            stats[team]["mp"] += 1
        stats[h_team]["gf"] += h
        stats[h_team]["ga"] += a
        stats[a_team]["gf"] += a
        stats[a_team]["ga"] += h
        if h > a:
            stats[h_team]["pts"] += 3; stats[h_team]["w"] += 1; stats[a_team]["l"] += 1
        elif h < a:
            stats[a_team]["pts"] += 3; stats[a_team]["w"] += 1; stats[h_team]["l"] += 1
        else:
            stats[h_team]["pts"] += 1; stats[h_team]["d"] += 1
            stats[a_team]["pts"] += 1; stats[a_team]["d"] += 1
    # 排序: 积分降序, 净胜球降序, 进球数降序
    sorted_standings = sorted(
        stats.items(),
        key=lambda kv: (-kv[1]["pts"], -(kv[1]["gf"] - kv[1]["ga"]), -kv[1]["gf"]),
    )
    return [{"team_en": team, **stats} for team, stats in sorted_standings]


def render_standings(standings: list[dict], grp: str) -> None:
    """渲染 Group 积分榜 (排名 + 队名 + 国旗 + 积分 + 净胜球)"""
    rows = []
    for idx, s in enumerate(standings, 1):
        team_en = s["team_en"]
        team_cn, team_iso = cn(team_en)
        flag = flag_img(team_iso)
        gd = s["gf"] - s["ga"]
        # 排名 1-4, 用排名 marker (1️⃣2️⃣3️⃣4️⃣)
        rank_icon = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"][idx - 1] if idx <= 4 else f"{idx}."
        # 净胜球带 + / - 符号
        gd_str = f"+{gd}" if gd > 0 else str(gd)
        row = (
            f'<div class="standing-row">'
            f'<span class="standing-rank">{rank_icon}</span>'
            f'<span class="standing-flag">{flag}</span>'
            f'<span class="standing-name">{team_cn}</span>'
            f'<span class="standing-mp">{s["mp"]}MP</span>'
            f'<span class="standing-record">{s["w"]}W {s["d"]}D {s["l"]}L</span>'
            f'<span class="standing-gd" data-pos="{gd > 0}">{gd_str}</span>'
            f'<span class="standing-pts"><strong>{s["pts"]}</strong></span>'
            f'</div>'
        )
        rows.append(row)
    html = (
        f'<div class="standings" data-group="{grp}">'
        f'<div class="standings-header">'
        f'<span class="sh-rank">#</span>'
        f'<span class="sh-team">球队</span>'
        f'<span class="sh-mp">场</span>'
        f'<span class="sh-record">胜平负</span>'
        f'<span class="sh-gd">净胜球</span>'
        f'<span class="sh-pts">积分</span>'
        f'</div>'
        + "".join(rows)
        + "</div>"
    )
    render_html(html)


def _finished_row_html(m: dict) -> str:
    """已赛比赛行 HTML (供 render_finished_section 拼接)

    时间列: '<MM-DD><br>FT' (date 来自 Wikipedia dtstart, ISO 2026-06-15)
    """
    home_cn, home_flag = cn(m.get("home_en", ""))
    away_cn, away_flag = cn(m.get("away_en", ""))
    grp = m.get("group", "?")
    score = m.get("score") or "–"
    home_flag_img = flag_img(home_flag)
    away_flag_img = flag_img(away_flag)

    # 日期展示: 2026-06-15 → "06-15"  (两行: 日期在上, FT 在下)
    date_iso = m.get("date") or ""
    if len(date_iso) == 10 and date_iso[4] == "-" and date_iso[7] == "-":
        date_label = date_iso[5:]   # 06-15
    else:
        date_label = ""
    time_html = (
        f'<div class="m-time">'
        f'<span class="m-date">{date_label}</span>'
        f'<span class="m-ft">FT</span>'
        f'</div>'
    )

    return (
        f'<div class="match-row finished">'
        f'{time_html}'
        f'<div class="m-team home"><span class="flag">{home_flag_img}</span><span>{home_cn}</span></div>'
        f'<div class="m-score">{_format_score(score)}</div>'
        f'<div class="m-team away"><span class="flag">{away_flag_img}</span><span>{away_cn}</span></div>'
        f'<div></div>'
        f'<div class="m-status">{tier_badge(m.get("home_en",""))} <span class="badge group">Group {grp}</span> {tier_badge(m.get("away_en",""))}</div>'
        f'</div>'
    )


# === 未赛区块 ===
def render_upcoming_section(upcoming: list[dict]) -> None:
    """未赛区块: 按日期分组, 含赔率 3 列"""
    st.markdown(f"### ⏳ 未赛 {len(upcoming)} 场 · 按日期")

    by_date: dict[str, list[dict]] = defaultdict(list)
    for m in upcoming:
        iso = m.get("commence_time")
        if not iso:
            continue
        bj = _to_bj(iso)
        date_key = bj.strftime("%Y-%m-%d")
        by_date[date_key].append(m)

    weekday_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    today_bj = (_now_utc_naive() + timedelta(hours=8)).date()

    for date_key in sorted(by_date.keys()):
        matches = sorted(by_date[date_key], key=lambda x: x.get("commence_time", ""))
        dt = datetime.strptime(date_key, "%Y-%m-%d")
        wd = weekday_cn[dt.weekday()]
        date_label = "今天" if dt.date() == today_bj else date_key[5:]  # MM-DD
        full_label = date_key if dt.date() != today_bj else f"{date_key} (今天)"

        header = f"""
        <div class="date-header">
          <span class="date-label">📅 {full_label}</span>
          <span class="date-weekday">{wd}</span>
          <span class="date-count">{len(matches)} 场比赛</span>
        </div>
        """
        render_html(header)

        # 行列表 - 直接循环调 render_match_row_upcoming
        for m in matches:
            render_match_row_upcoming(m)


# === Legend ===
def render_legend() -> None:
    """字段解读"""
    html = """
    <div class="legend">
      <strong>📐 字段解读</strong><br>
      • <span class="legend-key">主 / 平 / 客</span> 主胜 / 平局 / 客胜赔率 (去 vig 后均值),<span class="legend-key">绿色底</span>=隐含概率最高<br>
      • <span class="legend-key">FT</span> 已完赛 (Full Time) · <span class="legend-key">LIVE</span> 进行中 · <span class="legend-key">NS</span> 未开赛 (Not Started)<br>
      • <span class="legend-key">Group X</span> 所在小组 (A-L)<br>
      <em>设计参考: FIFA.com, Flashscore, SofaScore, OddsPortal</em>
    </div>
    """
    render_html(html)


# === Tab3: 价值下注 ===
FINAL_BETS_FILE = ROOT / "output" / "wc_final_bets.json"
TRACKER_FILE = ROOT / "output" / "wc_bet_tracker.json"
CORR_FILE = ROOT / "output" / "wc_correlation_analysis.json"
DAILY_FILE = ROOT / "output" / "wc_daily_analysis.json"
SPORTTERY_FILE = ROOT / "output" / "wc_sporttery_opportunities.json"
SPORTTERY_PORTFOLIO_FILE = ROOT / "output" / "wc_sporttery_portfolio.json"
PURCHASES_FILE = ROOT / "output" / "wc_sporttery_purchases.json"
MODEL_COMPARISON_FILE = ROOT / "output" / "wc_model_comparison.json"

# Pool code -> (badge class suffix, short Chinese label, full Chinese label)
SP_POOLS: list[tuple[str, str, str]] = [
    ("had",  "胜平负",   "胜平负"),
    ("hhad", "让球",     "让球胜平负"),
    ("crs",  "比分",     "比分"),
    ("ttg",  "总进球",   "总进球数"),
]

# Manual purchase form: common score options per pool
CRS_SCORES = ["1:0", "2:0", "2:1", "3:0", "3:1", "3:2",
              "0:0", "1:1", "2:2", "3:3",
              "0:1", "0:2", "1:2", "0:3", "1:3", "2:3",
              "胜其他", "平其他", "负其他"]
TTG_OPTS = ["0", "1", "2", "3", "4", "5", "6", "7+"]


@st.cache_data(ttl=300)
def _load_sporttery():
    if not SPORTTERY_FILE.exists():
        return None
    return json.loads(SPORTTERY_FILE.read_text(encoding="utf-8"))


@st.cache_data(ttl=300)
def _load_sporttery_portfolio():
    if not SPORTTERY_PORTFOLIO_FILE.exists():
        return None
    return json.loads(SPORTTERY_PORTFOLIO_FILE.read_text(encoding="utf-8"))


@st.cache_data(ttl=30)
def _load_sporttery_purchases():
    if not PURCHASES_FILE.exists():
        return None
    return json.loads(PURCHASES_FILE.read_text(encoding="utf-8"))


@st.cache_data(ttl=300)
def _load_final_bets():
    if not FINAL_BETS_FILE.exists():
        return None
    return json.loads(FINAL_BETS_FILE.read_text(encoding="utf-8"))

@st.cache_data(ttl=30)
def _load_tracker_data():
    if not TRACKER_FILE.exists():
        return None
    return json.loads(TRACKER_FILE.read_text(encoding="utf-8"))

@st.cache_data(ttl=300)
def _load_correlation():
    if not CORR_FILE.exists():
        return None
    return json.loads(CORR_FILE.read_text(encoding="utf-8"))

@st.cache_data(ttl=300)
def _load_daily_analysis():
    if not DAILY_FILE.exists():
        return None
    return json.loads(DAILY_FILE.read_text(encoding="utf-8"))


@st.cache_data(ttl=300)
def _load_model_comparison():
    if not MODEL_COMPARISON_FILE.exists():
        return None
    return json.loads(MODEL_COMPARISON_FILE.read_text(encoding="utf-8"))


def _ev_class(ev: float) -> str:
    if ev > 0.50: return "ev-top"
    if ev > 0.20: return "ev-high"
    return "ev-mid"

def _sel_class(sel: str) -> str:
    return {"H": "sel-h", "D": "sel-d", "A": "sel-a"}.get(sel, "sel-d")


def _render_value_kpi(final_bets: dict) -> None:
    n = final_bets["n_bets"]; stake = final_bets["total_stake"]
    ev = final_bets["total_ev"]; std = final_bets["optimization"]["optimal_portfolio_std"]
    render_html(f"""<div class="kpi-strip">
      <div class="kpi-cell"><span class="kpi-icon">🎯</span><div class="kpi-text">
        <span class="kpi-value">{n}</span><span class="kpi-label">下注数</span></div></div>
      <div class="kpi-cell"><span class="kpi-icon">💰</span><div class="kpi-text">
        <span class="kpi-value">{stake:.1%}</span><span class="kpi-label">总仓位</span></div></div>
      <div class="kpi-cell"><span class="kpi-icon">📈</span><div class="kpi-text">
        <span class="kpi-value">{ev:+.2%}</span><span class="kpi-label">总 EV</span></div></div>
      <div class="kpi-cell"><span class="kpi-icon">⚠️</span><div class="kpi-text">
        <span class="kpi-value">{std:.1%}</span><span class="kpi-label">组合 σ</span></div></div>
    </div>""")


def _render_tracker_strip(tracker: dict) -> None:
    c = tracker.get("cumulative", {})
    pl_cls = "pos" if c.get("total_profit", 0) >= 0 else "neg"
    roi_cls = "pos" if c.get("roi", 0) >= 0 else "neg"
    render_html(f"""<div class="tracker-strip">
      <div class="ts-cell"><div class="ts-label">已结算</div>
        <div class="ts-value">{c.get('settled', 0)}场 <span style="font-size:0.8rem;color:var(--green-best)">{c.get('won', 0)}W</span> <span style="font-size:0.8rem;color:var(--red-live)">{c.get('lost', 0)}L</span></div>
        <div class="ts-sub">待结算 {c.get('pending', 0)} 场</div></div>
      <div class="ts-cell"><div class="ts-label">累计盈亏</div>
        <div class="ts-value {pl_cls}">{c.get('total_profit', 0):+.4f}</div>
        <div class="ts-sub">下注 {c.get('total_staked', c.get('total_stake', 0)):.4f}</div></div>
      <div class="ts-cell"><div class="ts-label">ROI</div>
        <div class="ts-value {roi_cls}">{c.get('roi', 0):+.1%}</div>
        <div class="ts-sub">命中率 {c.get('hit_rate', 0):.0%}</div></div>
      <div class="ts-cell"><div class="ts-label">资金</div>
        <div class="ts-value">{c.get('bankroll', 1.0):.4f}</div>
        <div class="ts-sub">初始 1.0000</div></div>
    </div>""")


def _render_compare_card(final_bets: dict) -> None:
    opt = final_bets["optimization"]
    kv, ov = opt["kelly_portfolio_variance"], opt["optimal_portfolio_variance"]
    kw, ow = min(kv / 0.05 * 100, 100), min(ov / 0.05 * 100, 100)
    html = f"""<div class="compare-card">
      <div class="cc-col">
        <div class="cc-title">Kelly (1/2)</div>
        <div class="cc-row"><span class="cc-label">总 EV</span><span class="cc-value pos">{opt['kelly_total_ev']:+.4f}</span></div>
        <div class="cc-row"><span class="cc-label">标准差 σ</span><span class="cc-value warn">{opt['kelly_portfolio_std']:.1%}</span></div>
        <div class="cc-row"><span class="cc-label">方差 σ²</span><span class="cc-value">{kv:.4f}</span></div>
        <div class="cc-varbar"><div class="fill kelly" style="width:{kw:.0f}%"></div></div>
      </div><div class="cc-col">
        <div class="cc-title">优化 (SLSQP · σ²≤0.02)</div>
        <div class="cc-row"><span class="cc-label">总 EV</span><span class="cc-value pos">{opt['optimal_total_ev']:+.4f}</span></div>
        <div class="cc-row"><span class="cc-label">标准差 σ</span><span class="cc-value">{opt['optimal_portfolio_std']:.1%}</span></div>
        <div class="cc-row"><span class="cc-label">方差 σ²</span><span class="cc-value">{ov:.4f}</span></div>
        <div class="cc-varbar"><div class="fill opt" style="width:{ow:.0f}%"></div></div>
      </div></div>"""
    if opt["variance_constraint_binding"]:
        html += (f'<div style="font-size:0.72rem;color:var(--ink-on-dark-3);'
                 f'margin-top:-8px;margin-bottom:16px;padding:0 18px;">'
                 f"✅ 方差约束 binding: EV 降 {abs(1-opt['optimal_total_ev']/opt['kelly_total_ev'])*100:.0f}%, "
                 f"σ 降 {abs(1-opt['optimal_portfolio_std']/opt['kelly_portfolio_std'])*100:.0f}%</div>")
    render_html(html)


def _render_bet_table(final_bets: dict, tracker_by_match: dict, today_bj: str) -> None:
    bets = sorted(final_bets["final_bets"], key=lambda x: (x["date"], -x["ev"]))
    cap = 0.03; rows = ""
    for b in bets:
        tr = tracker_by_match.get(b["match"], {})
        status = tr.get("status", "pending"); score = tr.get("score")
        row_cls = ""
        if b["date"] == today_bj: row_cls = "today"
        if status == "won": row_cls = "won"
        elif status == "lost": row_cls = "lost"
        if status == "won":
            sb = f'<span class="status-badge st-won">✅ {score}</span>'
        elif status == "lost":
            sb = f'<span class="status-badge st-lost">❌ {score}</span>'
        else:
            sb = '<span class="status-badge st-pending">⏳</span>'
        h_cn, h_iso = cn(b.get("home", "")); a_cn, a_iso = cn(b.get("away", ""))
        corr = ' 🔗' if "correlated_same_day_group" in b else ''
        mh = (f'<div class="bt-match"><span class="flag">{flag_img(h_iso)}</span>'
              f'{h_cn} vs {a_cn}<span class="flag">{flag_img(a_iso)}</span>'
              f'<span class="corr-mark">{corr}</span></div>')
        kw = min(b.get("kelly_stake", 0) / cap * 100, 100)
        ow = min(b["optimal_stake"] / cap * 100, 100)
        sh = (f'<div class="stake-cell"><div class="bar-bg">'
              f'<div class="bar-kelly" style="width:{kw:.0f}%"></div>'
              f'<div class="bar-opt" style="width:{ow:.0f}%"></div></div>'
              f'<span class="stake-num">{b["optimal_stake"]:.1%}</span></div>')
        rows += f"""<tr class="{row_cls}"><td>{b['date'][5:]}</td>
          <td><span class="badge group">{b['group']}</span></td><td>{mh}</td>
          <td><span class="sel-badge {_sel_class(b['selection'])}">{b['selection']}</span></td>
          <td class="num">{b['p_model']:.1%}</td><td class="num">{b['odds']:.2f}</td>
          <td class="num"><span class="ev-badge {_ev_class(b['ev'])}">{b['ev']:+.1%}</span></td>
          <td class="num">{sh}</td><td>{sb}</td></tr>"""
    render_html(f"""<table class="bet-table"><thead><tr>
      <th>日期</th><th>组</th><th>比赛</th><th>选</th><th>模型P</th>
      <th class="num">赔率</th><th class="num">EV</th><th class="num">建议仓位</th><th>状态</th>
      </tr></thead><tbody>{rows}</tbody></table>""")


def _render_daily_summary(final_bets: dict, tracker_by_match: dict) -> None:
    bets = final_bets["final_bets"]
    by_date: dict[str, list] = defaultdict(list)
    for b in bets: by_date[b["date"]].append(b)
    rows = ""
    for date in sorted(by_date):
        db = by_date[date]
        stake = sum(b["optimal_stake"] for b in db)
        ev = sum(b["ev"] * b["optimal_stake"] for b in db)
        st = [b for b in db if tracker_by_match.get(b["match"], {}).get("status") in ("won", "lost")]
        pl = sum(tracker_by_match[b["match"]].get("profit", 0) for b in st) if st else 0
        cp = min(stake / 0.15 * 100, 100)
        rows += f"<tr><td>{date}</td><td>{len(db)}</td><td>{stake:.1%}</td><td>{ev:+.4f}</td><td>{(f'{pl:+.4f}' if st else '—')}</td><td><div class='cap-bar'><div class='cb-bg'><div class='cb-fill' style='width:{cp:.0f}%'></div></div>{stake:.0%}/15%</div></td></tr>"
    ts = sum(b["optimal_stake"] for b in bets); te = sum(b["ev"] * b["optimal_stake"] for b in bets)
    asl = [b for b in bets if tracker_by_match.get(b["match"], {}).get("status") in ("won", "lost")]
    tp = sum(tracker_by_match[b["match"]].get("profit", 0) for b in asl) if asl else 0
    rows += f"<tr class='total'><td>合计</td><td>{len(bets)}</td><td>{ts:.1%}</td><td>{te:+.4f}</td><td>{tp:+.4f}</td><td></td></tr>"
    render_html(f"<h3>📊 每日汇总</h3><table class='daily-table'><thead><tr><th>日期</th><th>注数</th><th>仓位</th><th>预期EV</th><th>实际P/L</th><th>上限</th></tr></thead><tbody>{rows}</tbody></table>")


def _render_correlation_analysis(corr: dict) -> None:
    labels = ["H", "D", "A"]
    for g in corr["groups"]:
        joint = g["joint_matrix"]; adv = g.get("advancement_prob", {})
        adv_s = "  ".join(f"{cn(t)[0]} {p:.0%}" for t, p in sorted(adv.items(), key=lambda x: -x[1])[:4])
        mat = '<div class="corr-matrix"><div class="cm-cell cm-hdr"></div>'
        for l in labels: mat += f'<div class="cm-cell cm-hdr">场2={l}</div>'
        for i, l in enumerate(labels):
            mat += f'<div class="cm-cell cm-hdr">场1={l}</div>'
            for j in range(3):
                v = joint[i][j]; cls = "cm-hi" if v > 0.15 else ""
                mat += f'<div class="cm-cell {cls}">{v:.1%}</div>'
        mat += '</div>'
        dec = "✅ KEEP BOTH" if g["keep_both"] else f"❌ DROP {g.get('dropped', '')}"
        render_html(f"""<div class="corr-group-card">
          <div class="cgc-title">Group {g['group']} · {', '.join(g['matches'])}</div>{mat}
          <div class="cgc-stat"><span>bet 协方差</span><span class="cgc-val">{g['bet_covariance']:+.4f}</span></div>
          <div class="cgc-stat"><span>P(双注中奖)</span><span class="cgc-val">{g['bet_joint_win_prob']:.1%}</span></div>
          <div class="cgc-stat"><span>晋级概率</span><span class="cgc-val">{adv_s}</span></div>
          <div class="cgc-stat"><span>决策</span><span class="cgc-val">{dec}</span></div>
          <div style="font-size:0.72rem;color:var(--ink-on-dark-4);margin-top:4px">{g.get('reason', '')}</div></div>""")


def _render_risk_rules(final_bets: dict) -> None:
    rows = ""
    for key, desc in final_bets.get("risk_rules", {}).items():
        icon = "✅" if ("optimizer" in desc or "P4" in desc) else ("⚠️" if ("manual" in desc or "operational" in desc) else "•")
        rows += f"<tr><td>{icon} {key}</td><td>{desc}</td></tr>"
    render_html(f'<table class="risk-table"><thead><tr><th>规则</th><th>说明</th></tr></thead><tbody>{rows}</tbody></table>')
    # Dynamic OOS calibration summary from the baseline-vs-improved comparison.
    cmp = _load_model_comparison()
    if cmp:
        b = cmp["baseline"]; ip = cmp["improved_platt"]
        home_note = ("低估" if b["home_pred"] < b["home_actual"] else "高估")
        draw_note = ("低估" if b["draw_pred"] < b["draw_actual"] else "高估")
        away_note = ("高估" if b["away_pred"] > b["away_actual"] else "低估")
        # xG fit status line.
        if cmp.get("xg_enabled"):
            cov = cmp.get("xg_coverage", {})
            xg_status_str = (f"✅ {cov.get('with_xg', 0)}/{cov.get('total', 0)} = "
                             f"{cov.get('pct', 0.0)}% 场次有 xG 数据 → attack/defense 信号提升"
                             f" (无 xG 时 fallback 到进球数)")
            xg_block = cmp.get("improved_xg")
            if xg_block is not None:
                xg_status_str += (f" → Brier home {ip['brier_home']:.4f} → "
                                  f"{xg_block['brier_home']:.4f}")
        else:
            xg_status_str = "❌ 未启用 (运行 fetch_xg 抓取 FBref xG 数据)"
        render_html(f"""<div style="margin-top:12px;font-size:0.78rem;color:var(--ink-on-dark-3);line-height:1.6">
          <strong style="color:var(--ink-on-dark)">OOS 校准偏差 ({cmp['n_matches']}场已赛) — 校准前后对比</strong><br>
          • 主胜: baseline pred {b['home_pred']:.1%} vs actual {b['home_actual']:.1%} → Poisson <span style="color:var(--{'green-best' if home_note=='低估' else 'red-live'})">{home_note}</span>
            → 校准后 {ip['home_pred']:.1%}<br>
          • 平局: baseline pred {b['draw_pred']:.1%} vs actual {b['draw_actual']:.1%} → <span style="color:var(--{'green-best' if draw_note=='低估' else 'red-live'})">{draw_note}</span>
            → 校准后 {ip['draw_pred']:.1%}<br>
          • 客胜: baseline pred {b['away_pred']:.1%} vs actual {b['away_actual']:.1%} → <span style="color:var(--{'red-live' if away_note=='高估' else 'green-best'})">{away_note}</span>
            → 校准后 {ip['away_pred']:.1%}<br>
          • Brier home: {b['brier_home']:.4f} → {ip['brier_home']:.4f}
            {'✅ 改进' if ip['brier_home'] < b['brier_home'] else '⚠️ 未改进'}<br>
          • xG 拟合: {xg_status_str}<br>
          <em>draw_inflate={cmp['draw_inflate']:.2f} deflate_away={cmp['deflate_away']:.2f} (跨洲 {cmp['n_cross_conf']}/{cmp['n_matches']} 场)</em></div>""")
    else:
        render_html("""<div style="margin-top:12px;font-size:0.78rem;color:var(--ink-on-dark-3);line-height:1.6">
          <strong style="color:var(--ink-on-dark)">OOS 校准偏差</strong><br>
          运行 <code>python -m wc_betting.backtest.calibrate compare</code> 生成校准对比数据。</div>""")


def _render_calibration_curve() -> None:
    """Calibration bucket table: baseline vs improved pred vs actual per bucket."""
    cmp = _load_model_comparison()
    if not cmp:
        return
    b = cmp["baseline"]["calib_buckets"]
    ip = cmp["improved_platt"]["calib_buckets"]
    rows = ""
    for (lo, hi, cnt, bp, ap), (_, _, _, ip_mp, _) in zip(b, ip):
        if cnt == 0:
            continue
        bp_s = f"{bp:.3f}" if bp == bp else "—"
        ip_s = f"{ip_mp:.3f}" if ip_mp == ip_mp else "—"
        ap_s = f"{ap:.3f}" if ap == ap else "—"
        # Highlight buckets where improved is closer to actual than baseline.
        base_gap = abs(bp - ap) if bp == bp and ap == ap else 9
        impr_gap = abs(ip_mp - ap) if ip_mp == ip_mp and ap == ap else 9
        cls = "calib-bucket-good" if impr_gap < base_gap else (
            "calib-bucket-bad" if impr_gap > base_gap else "")
        rows += (f'<tr class="{cls}"><td>[{lo:.2f}, {hi:.2f})</td><td class="num">{cnt}</td>'
                 f'<td class="num">{bp_s}</td><td class="num">{ip_s}</td>'
                 f'<td class="num">{ap_s}</td></tr>')
    render_html(f"""<table class="bet-table calib-table"><thead><tr>
      <th>校准桶 (主胜P)</th><th class="num">样本</th>
      <th class="num">baseline pred</th><th class="num">校准后 pred</th>
      <th class="num">actual</th></tr></thead><tbody>{rows}</tbody></table>""")
    render_html('<div style="font-size:0.72rem;color:var(--ink-on-dark-3);'
                'margin-top:4px;">绿色 = 校准后更接近实际; 红色 = 更偏离。'
                'Platt 在 34 场 OOS 上拟合 (样本内), 实际 OOS 改善幅度会更小。</div>')


def _render_daily_combinations(daily: dict, tracker_by_match: dict) -> None:
    """每日下注组合: 风险/收益/对冲分析."""
    days = daily.get("days", [])
    cards = ""
    for d in days:
        n = d["n_bets"]
        g = d["global"]; k = d["kelly"]
        hedges = d.get("hedging", [])
        div_b = d.get("diversification_benefit", 0)
        today_cls = "dc-today" if d["date"] == (_now_utc_naive() + timedelta(hours=8)).strftime("%Y-%m-%d") else ""

        # Bet rows
        bet_rows = ""
        for b in d["bets"]:
            tr = tracker_by_match.get(b["match"], {})
            st_icon = {"won": "✅", "lost": "❌"}.get(tr.get("status", ""), "⏳")
            bet_rows += (f'<div class="dc-bet"><span class="dc-sel {_sel_class(b["selection"])}">'
                         f'{b["selection"]}</span><span class="dc-match">{b["match"]}</span>'
                         f'<span class="dc-odds">@{b["odds"]:.2f}</span>'
                         f'<span class="dc-ev {_ev_class(b["ev"])}">{b["ev"]:+.0%}</span>'
                         f'<span class="dc-stake">{b["global_optimal_stake"]:.1%}</span>'
                         f'<span class="dc-icon">{st_icon}</span></div>')

        # Hedging badges
        hedge_html = ""
        for h in hedges:
            ht = h["hedge_type"]
            badge = "🔗 同向" if ht == "none" else "🛡️ 部分对冲"
            hedge_html += (f'<div class="dc-hedge"><span class="hg-badge hg-{ht}">{badge}</span>'
                           f'Group {h["group"]} · {", ".join(h["matches"])}'
                           f'<span class="hg-note">{h["note"]}</span></div>')

        div_html = (f'<div class="dc-div">分散化降σ ~{div_b:.0%}</div>' if div_b > 0.01 else "")

        cards += f"""<div class="dc-card {today_cls}">
          <div class="dc-header"><span class="dc-date">{d["date"]}</span>
            <span class="dc-nbets">{n} 注</span>{div_html}</div>
          <div class="dc-bets">{bet_rows}</div>{hedge_html}
          <div class="dc-stats">
            <div class="dc-stat"><span class="dc-label">全局</span>
              <span class="dc-val">EV {g["ev"]:+.4f} · σ {g["sigma"]:.1%} · Sharpe {g["sharpe"]:.2f}</span></div>
            <div class="dc-stat"><span class="dc-label">Kelly</span>
              <span class="dc-val">EV {k["ev"]:+.4f} · σ {k["sigma"]:.1%} · Sharpe {k["sharpe"]:.2f}</span></div>
          </div></div>"""

    render_html(f'<div class="dc-grid">{cards}</div>')


def _render_approach_comparison(daily: dict) -> None:
    """方案对比表: 全局/Kelly/每日SLSQP."""
    aps = daily.get("summary", {}).get("approaches", {})
    rows = ""
    for key, ap in aps.items():
        is_best_sharpe = ap.get("sharpe", 0) == max(a.get("sharpe", 0) for a in aps.values())
        is_best_ev = ap.get("total_ev", 0) == max(a.get("total_ev", 0) for a in aps.values())
        stars = (" ★" if is_best_sharpe else "") + (" ▲" if is_best_ev else "")
        cls = "ap-best" if (is_best_sharpe or is_best_ev) else ""
        rows += (f'<tr class="{cls}"><td>{ap["label"]}{stars}</td>'
                 f'<td class="num">{ap["total_stake"]:.1%}</td>'
                 f'<td class="num">{ap["total_ev"]:+.4f}</td>'
                 f'<td class="num">{ap["sigma"]:.1%}</td>'
                 f'<td class="num">{ap["sharpe"]:.2f}</td></tr>')
    render_html(f"""<table class="bet-table approach-table"><thead><tr>
      <th>方案</th><th class="num">总仓位</th><th class="num">总EV</th>
      <th class="num">σ</th><th class="num">Sharpe</th></tr></thead><tbody>{rows}</tbody></table>""")
    rec = daily.get("summary", {}).get("recommendation", "")
    if rec:
        render_html(f'<div class="rec-box">{rec}</div>')


def _render_sporttery_summary(data: dict) -> None:
    s = data.get("summary")
    if s is None:
        from collections import defaultdict
        ops = data.get("opportunities", [])
        bp = defaultdict(int)
        for o in ops:
            bp[o.get("pool_code", "?")] += 1
        s = {
            "total_opportunities": len(ops),
            "by_pool": dict(bp),
            "total_stake": sum(o.get("recommended_stake", 0) for o in ops),
            "total_ev": sum(o.get("ev", 0) * o.get("recommended_stake", 0) for o in ops),
            "total_ev_calibrated": sum(o.get("ev_calibrated", o.get("ev", 0)) * o.get("recommended_stake", 0) for o in ops),
            "auto_review": sum(1 for o in ops if not o.get("manual_review")),
            "manual_review": sum(1 for o in ops if o.get("manual_review")),
        }
    by_pool = s.get("by_pool", {})
    badges = "".join(
        f'<span class="sp-pool-badge sp-{p}">{short} {by_pool.get(p, 0)}</span>'
        for p, short, _ in SP_POOLS
    )
    n_matches = data.get("matches_scanned", "?")
    ret = data.get("return_rate_estimated", 0.70)
    # xG fit status badge.
    if data.get("use_xg"):
        cov = data.get("xg_coverage", {})
        xg_badge = (f'<span class="sp-sum-ret" style="color:var(--green-best)">'
                    f'xG拟合: ✅ {cov.get("pct", 0.0)}% 覆盖</span>')
    else:
        xg_badge = ('<span class="sp-sum-ret" style="color:var(--ink-on-dark-3)">'
                    'xG拟合: ❌ 未启用 (运行 fetch_xg)</span>')
    render_html(f"""<div class="sp-summary">
      <div class="sp-sum-cell"><span class="sp-sum-num">{s['total_opportunities']}</span>
        <span class="sp-sum-label">正EV机会</span></div>
      <div class="sp-sum-cell"><span class="sp-sum-num">{s['total_stake']:.1%}</span>
        <span class="sp-sum-label">总仓位</span></div>
      <div class="sp-sum-cell"><span class="sp-sum-num pos">{s.get('total_ev_calibrated', s['total_ev']):+.4f}</span>
        <span class="sp-sum-label">总EV (校准)</span></div>
      <div class="sp-sum-cell"><span class="sp-sum-num">{n_matches}</span>
        <span class="sp-sum-label">扫描场次</span></div>
      <div class="sp-sum-cell sp-sum-badges">{badges}</div>
      <div class="sp-sum-cell"><span class="sp-sum-ret">返奖率 ~{ret:.0%}</span></div>
      <div class="sp-sum-cell">{xg_badge}</div>
    </div>""")


def _render_sporttery_opportunities(data: dict) -> None:
    """体彩 EV 扫描结果: 按玩法分组的机会表 + 顶部汇总条."""
    if not data or not data.get("opportunities"):
        st.info("暂无体彩正EV机会。点击下方按钮抓取最新赔率,或手动录入 JSON。")
        return
    _render_sporttery_summary(data)
    by_pool: dict[str, list] = defaultdict(list)
    for op in data["opportunities"]:
        if op.get("recommended_stake", 0) <= 0:
            continue
        by_pool[op["pool_code"]].append(op)
    for pool, short, full in SP_POOLS:
        ops = by_pool.get(pool, [])
        if not ops:
            continue
        ops.sort(key=lambda x: -x.get("ev_calibrated", x["ev"]))
        # Priority star badge: crs=★★★ ttg=★★ hhad=★ had=☆
        prio = {1: "★★★", 2: "★★", 3: "★", 4: "☆"}.get(
            ops[0].get("pool_priority", 9), "")
        rows = ""
        for op in ops:
            sel = op["selection"]
            if pool == "crs" and sel.startswith("("):
                sel = sel.strip("()").replace(",", ":")
            parts = op["match"].split(" vs ")
            h_en = parts[0] if parts else ""
            a_en = parts[1] if len(parts) > 1 else ""
            h_cn, h_iso = cn(h_en)
            a_cn, a_iso = cn(a_en)
            hc_note = (f" <span class='sp-hc'>(让{op['handicap']:+.0f})</span>"
                       if op.get("handicap") is not None else "")
            mh = (f'<div class="sp-match"><span class="flag">{flag_img(h_iso)}</span>'
                  f'{h_cn} vs {a_cn}<span class="flag">{flag_img(a_iso)}</span></div>')
            date_s = op["date"][5:] if op.get("date") else "—"
            stake_note = f' <span class="sp-stake-note">{op["stake_note"]}</span>' if op.get("stake_note") else ""
            ev_c = op.get("ev_calibrated", op["ev"])
            p_c = op.get("p_model_calibrated", op["p_model"])
            calib = op.get("calibrated", False) if isinstance(op.get("calibrated"), bool) else data.get("calibrated", False)
            # Show calibrated EV as the main badge; raw EV as sub-text when calibration is on.
            ev_cell = (f'<span class="ev-badge {_ev_class(ev_c)}">{ev_c:+.1%}</span>'
                       f'<span class="sp-ev-raw">raw {op["ev"]:+.1%}</span>'
                       if calib and abs(ev_c - op["ev"]) > 0.001
                       else f'<span class="ev-badge {_ev_class(op["ev"])}">{op["ev"]:+.1%}</span>')
            p_cell = (f'{op["p_model"]:.1%}<span class="sp-pcal">→{p_c:.1%}</span>'
                      if calib and abs(p_c - op["p_model"]) > 0.001
                      else f'{op["p_model"]:.1%}')
            rows += f"""<tr><td>{date_s}</td>
              <td><span class="badge group">{op['group']}</span></td><td>{mh}</td>
              <td><span class="sp-sel">{op['selection_cn']}{hc_note}</span></td>
              <td class="num">{op['odds']:.2f}</td><td class="num">{p_cell}</td>
              <td class="num">{ev_cell}</td>
              <td class="num">{op['recommended_stake']:.1%}{stake_note}</td></tr>"""
        render_html(f"""<div class="sp-pool-block">
          <div class="sp-pool-header"><span class="sp-pool-badge sp-{pool}">{short}</span>
            <span class="sp-pool-name">{full}</span>
            <span class="sp-pool-prio">可打性 {prio}</span>
            <span class="sp-pool-count">{len(ops)} 注</span></div>
          <table class="sp-table"><thead><tr>
            <th>日期</th><th>组</th><th>比赛</th><th>选项</th>
            <th class="num">体彩赔率</th><th class="num">模型P</th>
            <th class="num">EV (校准)</th><th class="num">建议仓位</th>
            </tr></thead><tbody>{rows}</tbody></table></div>""")
    if data.get("matches_skipped_unmatched"):
        render_html(
            f'<div class="sp-warn">⚠️ {data["matches_skipped_unmatched"]} 个玩法行因队名未匹配被跳过 '
            f'(见 JSON skipped_unmatched)</div>')


def render_value_tab() -> None:
    """Tab3: 价值下注建议 + 实时结算追踪"""
    final_bets = _load_final_bets()
    tracker = _load_tracker_data()
    corr = _load_correlation()
    daily = _load_daily_analysis()
    if final_bets is None:
        st.warning("⚠️ 未找到下注建议数据。请先运行 P4-P6 管线。")
        st.code(f"expected: {FINAL_BETS_FILE}")
        return
    tracker_by_match: dict = {}
    if tracker:
        for b in tracker.get("bets", []):
            tracker_by_match[b["match"]] = b
    today_bj = (_now_utc_naive() + timedelta(hours=8)).strftime("%Y-%m-%d")
    _render_value_kpi(final_bets)
    if tracker and tracker.get("cumulative", {}).get("settled", 0) > 0:
        _render_tracker_strip(tracker)
    rc1, _ = st.columns([1, 4])
    with rc1:
        if st.button("🔄 刷新赛果结算", use_container_width=True, key="refresh_settle"):
            from wc_betting.strategy.tracker import settle_bets
            with st.spinner("刷新 Wikipedia + 结算中..."):
                settle_bets(verbose=False)
            _load_tracker_data.clear()
            st.rerun()
    _render_compare_card(final_bets)
    _render_bet_table(final_bets, tracker_by_match, today_bj)
    _render_daily_summary(final_bets, tracker_by_match)
    if daily:
        st.markdown("### 📅 每日组合分析 + 对冲")
        _render_daily_combinations(daily, tracker_by_match)
        _render_approach_comparison(daily)
    if corr:
        with st.expander("🔗 同组相关性分析 (蒙特卡洛 N=10000)"):
            _render_correlation_analysis(corr)
    with st.expander("📋 风控规则 + 校准偏差"):
        _render_risk_rules(final_bets)
    if _load_model_comparison():
        with st.expander("📊 模型校准曲线 (baseline vs 校准后)"):
            _render_calibration_curve()


# === Tab4: 体彩购买记录 + 回测 ===

def _fmt_purchase_option(op: dict) -> str:
    """Format an opportunity for the purchase selectbox."""
    date_s = op.get("date", "")[5:] if op.get("date") else "??"
    sel = op.get("selection_cn", op.get("selection", ""))
    hc = f" 让{op['handicap']:+.0f}" if op.get("handicap") is not None else ""
    return (f"{date_s} {op.get('group', '?')} {op.get('match_cn', op.get('match', ''))} "
            f"{op.get('pool_name', op.get('pool_code', ''))}{hc} {sel} "
            f"@{op.get('odds', 0):.1f} EV{op.get('ev', 0):+.0%}")


def _render_sporttery_purchase_recorder(sporttery_data: dict | None) -> None:
    """Input UI: record a purchased single-game bet.

    Shows all opportunities sorted by date → match → pool → EV, with a text
    filter to quickly narrow down by team name, pool, or selection.
    """
    ops: list[dict] = []
    if sporttery_data and sporttery_data.get("opportunities"):
        ops = sporttery_data["opportunities"]
        # Sort: date asc → match asc → pool_priority asc → EV desc
        ops.sort(key=lambda x: (
            x.get("date", ""),
            x.get("match_cn", x.get("match", "")),
            x.get("pool_priority", 9),
            -x.get("ev_calibrated", x.get("ev", 0)),
        ))

    if ops:
        # Filter input
        fc1, fc2 = st.columns([3, 1])
        with fc1:
            filter_text = st.text_input(
                "🔍 筛选（队名/玩法/选项）", value="", key="purchase_filter",
                placeholder="如: 约旦 had H  → 留空显示全部")
        with fc2:
            st.caption(f"共 {len(ops)} 个可选")

        # Apply filter
        if filter_text.strip():
            ft = filter_text.strip().lower()
            filtered = [o for o in ops if (
                ft in o.get("match_cn", "").lower()
                or ft in o.get("match", "").lower()
                or ft in o.get("pool_name", "").lower()
                or ft in o.get("pool_code", "").lower()
                or ft in o.get("selection_cn", "").lower()
                or ft in o.get("selection", "").lower()
            )]
            if not filtered:
                st.warning(f"无匹配 '{filter_text}' 的结果")
                filtered = ops  # fallback to all
            st.caption(f"🔎 匹配 {len(filtered)}/{len(ops)} 条")
        else:
            filtered = ops

        idx = st.selectbox(
            "选择购买的竞彩", options=list(range(len(filtered))),
            format_func=lambda i: _fmt_purchase_option(filtered[i]),
            key="purchase_op_select")
        stake = st.number_input(
            "金额 (元)", min_value=2, value=100, step=10,
            key="purchase_stake")
        if st.button("📝 记录购买", key="record_purchase",
                     use_container_width=True, type="primary"):
            from wc_betting.strategy.sporttery_tracker import add_purchase
            add_purchase(filtered[idx], float(stake))
            _load_sporttery_purchases.clear()
            st.success(f"已记录购买: {_fmt_purchase_option(filtered[idx])} · {stake}元")
            st.rerun()
    else:
        st.caption("ℹ️ 暂无扫描结果,仅可手动录入 (点击下方展开)。")

    with st.expander("✍️ 手动录入 (不在扫描结果中)"):
        # Team list for selectboxes
        TEAM_NAMES_CN = sorted({cn(t)[0] for t in TEAM_CN if not t.startswith("Cura") or t == "Curacao"})
        _CN_TO_EN = {v[0]: k for k, v in TEAM_CN.items() if not k.startswith("Cura") or k == "Curacao"}

        with st.form("manual_purchase_form"):
            m_home_cn = st.selectbox("主队", TEAM_NAMES_CN, key="mp_home_cn",
                                     index=TEAM_NAMES_CN.index("西班牙") if "西班牙" in TEAM_NAMES_CN else 0)
            m_away_cn = st.selectbox("客队", TEAM_NAMES_CN, key="mp_away_cn",
                                     index=TEAM_NAMES_CN.index("沙特") if "沙特" in TEAM_NAMES_CN else 0)
            m_date = st.selectbox("比赛日期",
                ["2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26", "2026-06-27", "2026-06-28"],
                key="mp_date")
            # Pool
            pool_opts = [p[0] for p in SP_POOLS]
            _pool_full = {p[0]: p[2] for p in SP_POOLS}
            m_pool = st.selectbox("玩法", pool_opts,
                                  format_func=lambda c: f"{c} — {_pool_full.get(c, c)}",
                                  key="mp_pool")
            # Selection — dynamic based on pool
            if m_pool == "had":
                m_sel = st.selectbox("选项", ["H 主胜", "D 平", "A 客胜"], key="mp_sel")
            elif m_pool == "hhad":
                m_sel = st.selectbox("选项", ["H 让球主胜", "D 让球平", "A 让球客胜"], key="mp_sel")
            elif m_pool == "crs":
                m_sel = st.selectbox("选项 (比分)", CRS_SCORES, key="mp_sel")
            else:  # ttg
                m_sel = st.selectbox("选项 (总进球)", TTG_OPTS, key="mp_sel")

            # Auto-lookup odds from sporttery DB
            m_home_en = _CN_TO_EN.get(m_home_cn, m_home_cn)
            m_away_en = _CN_TO_EN.get(m_away_cn, m_away_cn)
            db_odds = None
            try:
                from wc_betting.data.sporttery_db import SportteryDB
                sel_lookup = m_sel[0] if m_pool in ("had", "hhad") else (
                    f"({m_sel.replace(':', ',')})" if m_pool == "crs" and "其他" not in m_sel else m_sel)
                rows = SportteryDB().query(home_cn=m_home_cn, away_cn=m_away_cn,
                                           pool_code=m_pool, selection=sel_lookup)
                if rows:
                    db_odds = rows[0]["odds"]
            except Exception:
                pass

            mc3, mc4 = st.columns(2)
            with mc3:
                if db_odds:
                    st.caption(f"📊 数据库赔率: **{db_odds:.2f}**")
                else:
                    st.caption("📊 未找到历史赔率，请手动输入")
                m_odds = st.number_input("赔率", min_value=1.01, value=db_odds or 2.00,
                                         step=0.01, key="mp_odds")
            with mc4:
                m_stake = st.number_input("金额 (元)", min_value=2, value=100, step=10, key="mp_stake")
            m_handicap = st.number_input("让球数 (仅hhad有效)", value=-1, step=1, key="mp_handicap")

            if st.form_submit_button("记录手动购买", use_container_width=True):
                from wc_betting.strategy.sporttery_tracker import (
                    add_purchase, POOL_NAMES_CN as _PN)
                pool_short = dict((p[0], p[1]) for p in SP_POOLS).get(m_pool, m_pool)
                # Parse selection
                if m_pool == "had":
                    sel_code = m_sel[0]
                    sel_cn = m_sel[2:]
                elif m_pool == "hhad":
                    sel_code = m_sel[0]
                    sel_cn = m_sel[2:]
                elif m_pool == "crs":
                    sel_code = f"({m_sel.replace(':', ',')})" if "其他" not in m_sel else {
                        "胜其他": "H_OTHER", "平其他": "D_OTHER", "负其他": "A_OTHER"}[m_sel]
                    sel_cn = m_sel
                else:  # ttg
                    sel_code = m_sel
                    sel_cn = m_sel
                # Infer group from unified data
                m_group = "?"
                try:
                    import json as _json
                    _unified = _json.loads((ROOT / "data/processed/wc_2026_unified.json").read_text())
                    for _m in _unified:
                        if _m.get("home_en") == m_home_en and _m.get("away_en") == m_away_en:
                            m_group = _m.get("group", "?")
                            break
                except Exception:
                    pass
                op = {
                    "match": f"{m_home_en} vs {m_away_en}",
                    "match_cn": f"{m_home_cn} vs {m_away_cn}",
                    "date": m_date, "group": m_group,
                    "pool_code": m_pool,
                    "pool_name": _PN.get(m_pool, pool_short),
                    "selection": sel_code,
                    "selection_cn": sel_cn,
                    "handicap": float(m_handicap) if m_pool == "hhad" else None,
                    "odds": float(m_odds),
                    "p_model": 0.0, "ev": 0.0,
                }
                add_purchase(op, float(m_stake))
                _load_sporttery_purchases.clear()
                st.success("已记录手动购买")
                st.rerun()


def _render_sporttery_purchases(purchases_data: dict | None,
                                finished: list[dict]) -> None:
    """Display purchase table + settle button + manual win/lose actions."""
    pc1, _ = st.columns([1, 4])
    with pc1:
        if st.button("🔄 结算 (从已赛比分判定)", use_container_width=True,
                     key="settle_purchases",
                     help="匹配已赛比赛比分,自动判定输赢"):
            from wc_betting.strategy.sporttery_tracker import settle_purchases
            with st.spinner("结算中..."):
                settle_purchases(finished)
            _load_sporttery_purchases.clear()
            st.rerun()

    if not purchases_data or not purchases_data.get("purchases"):
        st.info("暂无购买记录。在上方录入后,这里会显示购买明细 + 自动结算。")
        return

    purchases = purchases_data["purchases"]

    # 管理购买记录: 删除 / 改金额
    with st.expander("✏️ 管理购买记录 (删除 / 改金额)"):
        _fmt_mgr = lambda p: (f"{p['id']} · {p.get('purchase_date','')[5:]} · "
                              f"{p.get('match_cn') or p.get('match','')} · "
                              f"{p.get('pool_name','')} {p.get('selection_cn','')} · "
                              f"{p['stake_cny']:.0f}元 · {p['status']}")
        mgr_idx = st.selectbox("选择记录", list(range(len(purchases))),
                               format_func=lambda i: _fmt_mgr(purchases[i]),
                               key="mgr_purchase_select")
        target = purchases[mgr_idx]
        mc1, mc2 = st.columns([2, 1])
        with mc1:
            new_stake = st.number_input(
                "新金额 (元)", min_value=2, value=int(target["stake_cny"]),
                step=10, key="mgr_new_stake")
            if st.button("💾 更新金额", key="mgr_update_stake",
                         use_container_width=True):
                from wc_betting.strategy.sporttery_tracker import (
                    update_purchase_stake)
                update_purchase_stake(target["id"], float(new_stake))
                _load_sporttery_purchases.clear()
                st.success(f"已更新 {target['id']} 金额为 {new_stake}元")
                st.rerun()
        with mc2:
            st.write("")  # spacer to align with left column
            confirm_del = st.checkbox("我确认删除", key="mgr_confirm_del")
            if st.button("🗑️ 删除该记录", key="mgr_delete",
                         use_container_width=True,
                         type="secondary",
                         disabled=not confirm_del):
                from wc_betting.strategy.sporttery_tracker import delete_purchase
                delete_purchase(target["id"])
                _load_sporttery_purchases.clear()
                st.success(f"已删除 {target['id']}")
                st.rerun()

    # Manual-status rows need inline win/lose buttons.
    manual_rows = [p for p in purchases if p["status"] == "manual"]
    if manual_rows:
        st.markdown("##### ⚠️ 需手动确认 (比分“其他”桶)")
        for p in manual_rows:
            mcols = st.columns([4, 1, 1])
            with mcols[0]:
                st.caption(f"{p['id']} · {p['match_cn']} · {p['pool_name']} "
                           f"{p['selection_cn']} · 比分 {p.get('score') or '?'}")
            with mcols[1]:
                if st.button("✅ 赢", key=f"manual_win_{p['id']}"):
                    from wc_betting.strategy.sporttery_tracker import set_manual_result
                    set_manual_result(p["id"], True)
                    _load_sporttery_purchases.clear()
                    st.rerun()
            with mcols[2]:
                if st.button("❌ 输", key=f"manual_lose_{p['id']}"):
                    from wc_betting.strategy.sporttery_tracker import set_manual_result
                    set_manual_result(p["id"], False)
                    _load_sporttery_purchases.clear()
                    st.rerun()

    rows = ""
    for p in reversed(purchases):  # newest first
        status = p["status"]
        if status == "won":
            sb = (f'<span class="purchase-status won">✅ 赢</span>')
            pl = (f'<span class="num pos">+{p["profit_cny"]:.0f}</span>'
                  f'<span class="sp-score">{p.get("score") or ""}</span>')
        elif status == "lost":
            sb = f'<span class="purchase-status lost">❌ 输</span>'
            pl = (f'<span class="num neg">{p["profit_cny"]:.0f}</span>'
                  f'<span class="sp-score">{p.get("score") or ""}</span>')
        elif status == "manual":
            sb = f'<span class="purchase-status manual">✋ 待确认</span>'
            pl = f'<span class="sp-score">{p.get("score") or ""}</span>'
        else:
            sb = f'<span class="purchase-status pending">⏳</span>'
            pl = '<span class="sp-score">—</span>'
        hc_note = (f" <span class='sp-hc'>(让{p['handicap']:+.0f})</span>"
                   if p.get("handicap") is not None else "")
        rows += f"""<tr><td>{p['purchase_date'][5:]}</td>
          <td>{p['date'][5:] if p.get('date') else '—'}</td>
          <td><span class="badge group">{p.get('group','?')}</span></td>
          <td>{p.get('match_cn') or p.get('match','')}</td>
          <td><span class="sp-pool-badge sp-{p['pool_code']}">{p.get('pool_name','')}</span></td>
          <td><span class="sp-sel">{p.get('selection_cn','')}{hc_note}</span></td>
          <td class="num">{p['odds']:.2f}</td>
          <td class="num"><span class="ev-badge {_ev_class(p.get('ev',0))}">{p.get('ev',0):+.0%}</span></td>
          <td class="num">{p['stake_cny']:.0f}</td>
          <td>{sb}</td><td>{pl}</td></tr>"""
    render_html(f"""<table class="sp-table"><thead><tr>
      <th>购买日</th><th>比赛日</th><th>组</th><th>比赛</th>
      <th>玩法</th><th>选项</th><th class="num">赔率</th>
      <th class="num">预测EV</th><th class="num">金额</th><th>状态</th><th>比分/盈亏</th>
      </tr></thead><tbody>{rows}</tbody></table>""")


def _render_sporttery_backtest(purchases_data: dict | None) -> None:
    """Backtest: KPI strip + predicted vs realized EV calibration + by-pool table."""
    if not purchases_data or not purchases_data.get("purchases"):
        st.info("暂无购买记录。录入购买并结算后,这里会显示回测对比。")
        return

    c = purchases_data.get("cumulative", {})
    pl_cls = "pos" if c.get("total_profit", 0) >= 0 else "neg"
    roi_cls = "pos" if c.get("roi", 0) >= 0 else "neg"
    render_html(f"""<div class="tracker-strip">
      <div class="ts-cell"><div class="ts-label">已结算</div>
        <div class="ts-value">{c.get('settled',0)}注
          <span style="font-size:0.8rem;color:var(--green-best)">{c.get('won',0)}W</span>
          <span style="font-size:0.8rem;color:var(--red-live)">{c.get('lost',0)}L</span></div>
        <div class="ts-sub">待结算 {c.get('pending',0)} 注</div></div>
      <div class="ts-cell"><div class="ts-label">累计盈亏</div>
        <div class="ts-value {pl_cls}">{c.get('total_profit',0):+.0f}元</div>
        <div class="ts-sub">下注 {c.get('total_staked',0):.0f}元</div></div>
      <div class="ts-cell"><div class="ts-label">实际 ROI</div>
        <div class="ts-value {roi_cls}">{c.get('roi',0):+.1%}</div>
        <div class="ts-sub">命中率 {c.get('hit_rate',0):.0%}</div></div>
      <div class="ts-cell"><div class="ts-label">待结算</div>
        <div class="ts-value">{c.get('pending',0)}注</div>
        <div class="ts-sub">共 {c.get('total_bets',0)} 注</div></div>
    </div>""")

    # Calibration row: predicted EV vs realized ROI (core backtest metric).
    # Only meaningful when there are settled purchases with model data.
    pred = c.get("predicted_ev", 0)
    real = c.get("realized_ev", 0)
    n_settled = c.get("settled", 0)
    if n_settled == 0:
        render_html(
            '<div class="calib-row"><div class="calib-cell">'
            '<span class="calib-label">校准对比</span>'
            '<span class="calib-note">暂无已结算记录，结算后显示预测 EV vs 实际 ROI</span>'
            '</div></div>')
    elif pred == 0 and real == 0:
        render_html(
            '<div class="calib-row"><div class="calib-cell">'
            '<span class="calib-label">校准对比</span>'
            '<span class="calib-note">已结算记录均为手动录入（无模型数据），无法校准</span>'
            '</div></div>')
    else:
        gap = real - pred
        gap_cls = "calib-ok" if abs(gap) < 0.05 else "calib-warn"
        gap_note = ("模型校准良好" if abs(gap) < 0.05
                    else f"模型{'高估' if gap < 0 else '低估'} {abs(gap):.1%}")
        render_html(f"""<div class="calib-row {gap_cls}">
          <div class="calib-cell"><span class="calib-label">预测 EV (加权)</span>
            <span class="calib-value">{pred:+.1%}</span></div>
          <div class="calib-vs">vs</div>
          <div class="calib-cell"><span class="calib-label">实际 ROI (已结算)</span>
            <span class="calib-value {roi_cls}">{real:+.1%}</span></div>
          <div class="calib-gap"><span class="calib-label">差距</span>
            <span class="calib-value">{gap:+.1%}</span><span class="calib-note">{gap_note}</span></div>
        </div>""")

    # Statistical significance of the realized ROI (theory doc §4.3).
    # n<30 → noise zone; n>=30 → 95% CI via binomial approximation.
    n_settled = c.get("settled", 0)
    roi = c.get("roi", 0)
    hit = c.get("hit_rate", 0)
    settled_purchases = [p for p in purchases_data["purchases"]
                         if p.get("status") in ("won", "lost")]
    if n_settled < 30:
        render_html(
            f'<div class="sig-warn">⚠️ 样本不足 ({n_settled} 注 &lt; 30), '
            f'ROI {roi:+.1%} 不可信 (噪声区间)。需 ≥30 注才能初步判断策略有效性。</div>')
    else:
        # σ_ROI ≈ √(p(1-p)·(b-1)² / n), CI = ROI ± 1.96·σ
        avg_odds = (sum(p["odds"] for p in settled_purchases) / n_settled
                    if settled_purchases else 2.0)
        b = max(avg_odds - 1.0, 0.01)
        p = hit if 0 < hit < 1 else 0.5
        import math as _math
        sigma = _math.sqrt(p * (1 - p) * (b ** 2) / n_settled)
        ci = 1.96 * sigma
        ci_cls = "sig-ok" if (roi - ci > 0 or roi + ci < 0) else "sig-noise"
        verdict = ("✅ CI 不含 0 → 策略可能有效" if roi - ci > 0
                   else "❌ CI 不含 0 → 策略可能无效" if roi + ci < 0
                   else "CI 含 0 → 无法判定")
        render_html(f"""<div class="sig-row {ci_cls}">
          <span class="sig-label">统计显著性 (95% CI)</span>
          <span class="sig-value">ROI = {roi:+.1%} ± {ci:.1%}</span>
          <span class="sig-note">[{roi-ci:+.1%}, {roi+ci:+.1%}] · n={n_settled} · 命中{p:.0%} · 均赔{avg_odds:.2f}</span>
          <span class="sig-verdict">{verdict}</span></div>""")

    # By-pool breakdown table.
    by_pool: dict[str, list] = defaultdict(list)
    for p in purchases_data["purchases"]:
        by_pool[p["pool_code"]].append(p)
    prows = ""
    for pool, short, full in SP_POOLS:
        items = by_pool.get(pool, [])
        if not items:
            continue
        settled = [p for p in items if p["status"] in ("won", "lost")]
        won = [p for p in settled if p["status"] == "won"]
        staked = sum(p["stake_cny"] for p in settled)
        profit = sum(p.get("profit_cny", 0) for p in settled)
        roi = profit / staked if staked > 0 else 0.0
        hr = len(won) / len(settled) if settled else 0.0
        prows += (f"<tr><td><span class='sp-pool-badge sp-{pool}'>{short}</span></td>"
                  f"<td class='num'>{len(settled)}/{len(items)}</td>"
                  f"<td class='num'>{staked:.0f}</td>"
                  f"<td class='num {'pos' if profit>=0 else 'neg'}'>{profit:+.0f}</td>"
                  f"<td class='num {'pos' if roi>=0 else 'neg'}'>{roi:+.1%}</td>"
                  f"<td class='num'>{hr:.0%}</td></tr>")
    if prows:
        render_html(f"""<table class="sp-table"><thead><tr>
          <th>玩法</th><th class="num">注数</th><th class="num">下注</th>
          <th class="num">盈亏</th><th class="num">ROI</th><th class="num">命中率</th>
          </tr></thead><tbody>{prows}</tbody></table>""")


def _render_sporttery_portfolio(portfolio_data: dict | None) -> None:
    """体彩组合优化: Kelly vs SLSQP 均值-方差对比 + 同场相关性."""
    if not portfolio_data or "error" in portfolio_data:
        return
    opt = portfolio_data.get("optimization", {})
    if not opt:
        return
    st.markdown("#### 📐 组合优化 (SLSQP 均值-方差)")
    kv = opt.get("kelly_portfolio_variance", 0)
    ov = opt.get("optimal_portfolio_variance", 0)
    kw = min(kv / 0.05 * 100, 100)
    ow = min(ov / 0.05 * 100, 100)
    binding = opt.get("variance_constraint_binding", False)
    ev_red = opt.get("ev_reduction_pct", 0)
    var_red = opt.get("variance_reduction_pct", 0)
    html = f"""<div class="compare-card">
      <div class="cc-col">
        <div class="cc-title">Kelly (1/4)</div>
        <div class="cc-row"><span class="cc-label">总 EV</span><span class="cc-value pos">{opt.get('kelly_total_ev',0):+.4f}</span></div>
        <div class="cc-row"><span class="cc-label">标准差 σ</span><span class="cc-value warn">{opt.get('kelly_portfolio_std',0):.1%}</span></div>
        <div class="cc-row"><span class="cc-label">方差 σ²</span><span class="cc-value">{kv:.4f}</span></div>
        <div class="cc-varbar"><div class="fill kelly" style="width:{kw:.0f}%"></div></div>
      </div><div class="cc-col">
        <div class="cc-title">优化 (SLSQP · σ²≤0.02)</div>
        <div class="cc-row"><span class="cc-label">总 EV</span><span class="cc-value pos">{opt.get('optimal_total_ev',0):+.4f}</span></div>
        <div class="cc-row"><span class="cc-label">标准差 σ</span><span class="cc-value">{opt.get('optimal_portfolio_std',0):.1%}</span></div>
        <div class="cc-row"><span class="cc-label">方差 σ²</span><span class="cc-value">{ov:.4f}</span></div>
        <div class="cc-varbar"><div class="fill opt" style="width:{ow:.0f}%"></div></div>
      </div></div>"""
    if binding:
        html += (f'<div style="font-size:0.72rem;color:var(--ink-on-dark-3);'
                 f'margin-top:-8px;margin-bottom:16px;padding:0 18px;">'
                 f"✅ 方差约束 binding: EV 降 {ev_red:.0f}%, σ 降 {var_red:.0f}%"
                 f" | 同场协方差来自比分矩阵</div>")
    else:
        html += (f'<div style="font-size:0.72rem;color:var(--ink-on-dark-3);'
                 f'margin-top:-8px;margin-bottom:16px;padding:0 18px;">'
                 f"方差约束未 binding — Kelly 已在 σ²≤0.02 内</div>")
    render_html(html)

    # Same-match correlations.
    corr = portfolio_data.get("same_match_correlations", [])
    if corr:
        corrs = ""
        for c in sorted(corr, key=lambda x: -abs(x.get("avg_correlation", 0))):
            ac = c.get("avg_correlation", 0)
            cls = "pos" if ac > 0.05 else ("warn" if ac > 0.01 else "")
            corrs += (f"<tr><td>{c['match'][:36]}</td>"
                      f"<td class='num'>{c['n_bets']}</td>"
                      f"<td class='num {cls}'>{ac:+.3f}</td>"
                      f"<td>{', '.join(c.get('pools',[]))}</td></tr>")
        render_html(f"""<table class="sp-table" style="margin-bottom:16px"><thead><tr>
          <th>比赛</th><th class="num">注数</th><th class="num">平均相关性</th>
          <th>玩法</th></tr></thead><tbody>{corrs}</tbody></table>""")

    # Top optimized bets.
    ops = [op for op in portfolio_data.get("opportunities", [])
           if op.get("optimal_stake", 0) > 0.001]
    if ops:
        ops.sort(key=lambda x: -x["optimal_stake"])
        rows = ""
        for op in ops[:12]:
            sel = op["selection"]
            if op["pool_code"] == "crs" and sel.startswith("("):
                sel = sel.strip("()").replace(",", ":")
            kelly = op.get("kelly_stake", 0)
            opt_s = op["optimal_stake"]
            delta = (opt_s - kelly) / max(kelly, 1e-9) * 100
            delta_cls = "pos" if delta > 5 else ("neg" if delta < -5 else "")
            evc = op.get("ev_calibrated", op["ev"])
            rows += (f"<tr><td>{op['match'][:28]}</td>"
                     f"<td><span class='sp-pool-badge sp-{op['pool_code']}'>{op['pool_code']}</span></td>"
                     f"<td>{sel}</td>"
                     f"<td class='num'>{op['odds']:.2f}</td>"
                     f"<td class='num'><span class='ev-badge {_ev_class(evc)}'>{evc:+.0%}</span></td>"
                     f"<td class='num'>{kelly:.1%}</td>"
                     f"<td class='num'>{opt_s:.1%}</td>"
                     f"<td class='num {delta_cls}'>{delta:+.0f}%</td></tr>")
        render_html(f"""<table class="sp-table"><thead><tr>
          <th>比赛</th><th>玩法</th><th>选</th><th class="num">赔率</th>
          <th class="num">EV_cal</th><th class="num">Kelly</th>
          <th class="num">优化</th><th class="num">变化</th>
          </tr></thead><tbody>{rows}</tbody></table>""")


def _render_sporttery_value_crossref(finished: list[dict] | None = None) -> None:
    """交叉比对：价值下注（国际博彩）× 体彩盘口."""
    final_bets = _load_final_bets()
    sporttery_data = _load_sporttery()
    if final_bets is None:
        return
    bets = final_bets.get("final_bets", [])
    if not bets:
        return

    # Build sporttery HAD index
    sp_had = {}
    if sporttery_data and sporttery_data.get("opportunities"):
        for o in sporttery_data["opportunities"]:
            if o["pool_code"] == "had":
                key = (o["home_en"], o["away_en"], o["selection"])
                sp_had[key] = o

    # Also build index for reverse (home/away swap)
    sp_had_rev = {}
    for o in sporttery_data.get("opportunities", []):
        if o["pool_code"] == "had":
            rev_sel = {"H": "A", "A": "H", "D": "D"}.get(o["selection"])
            key = (o["away_en"], o["home_en"], rev_sel)
            sp_had_rev[key] = o

    # Categorize
    matched = []
    future = []
    past = []
    finished_matches = set()
    if finished:
        for m in finished:
            finished_matches.add((m["home_en"], m["away_en"]))

    for b in bets:
        key = (b["home"], b["away"], b["selection"])
        sp = sp_had.get(key) or sp_had_rev.get(key)
        if sp:
            matched.append((b, sp))
        elif (b["home"], b["away"]) in finished_matches or (b["away"], b["home"]) in finished_matches:
            past.append(b)
        else:
            future.append(b)

    if not (matched or future):
        return

    st.markdown("---")
    st.markdown("### 🔗 价值下注 × 体彩交叉比对")

    if matched:
        rows = ""
        for b, sp in matched:
            int_ev = b.get("ev_calibrated", b["ev"])
            sp_ev = sp.get("ev_calibrated", sp["ev"])
            ev_diff = sp_ev - int_ev
            diff_cls = "pos" if ev_diff > 0.01 else ("neg" if ev_diff < -0.01 else "")
            rows += f"""<tr>
              <td>{b["date"]}</td><td><span class="badge group">{b["group"]}</span></td>
              <td>{b["match"]}</td><td><span class="sp-sel">{b["selection"]}</span></td>
              <td class="num">{b["odds"]:.2f}</td><td class="num">{int_ev:+.1%}</td>
              <td class="num">{sp["odds"]:.2f}</td><td class="num">{sp_ev:+.1%}</td>
              <td class="num {diff_cls}">{ev_diff:+.1%}</td></tr>"""
        st.markdown(f"""<table class="sp-table" style="margin-bottom:16px"><thead><tr>
          <th>日期</th><th>组</th><th>比赛</th><th>选项</th>
          <th class="num">国际赔率</th><th class="num">国际EV</th>
          <th class="num">体彩赔率</th><th class="num">体彩EV</th>
          <th class="num">差异</th>
          </tr></thead><tbody>{rows}</tbody></table>
          <div class="sp-note">国际赔率来自博彩市场（低抽水~5%），体彩赔率来自 sporttery.cn（高抽水~30%）</div>""",
          unsafe_allow_html=True)

    if future:
        names = " · ".join(f'{b["match"]} [{b["selection"]}]' for b in future[:8])
        st.caption(f"⏳ 体彩尚未开盘: {names}" + (f" 等{len(future)}场" if len(future) > 8 else ""))


def render_smart_betting_tab() -> None:
    """智能投注：每日推荐 + 购买操作 + 战绩追踪 → 操作闭环."""
    import json as _json
    from pathlib import Path as _Path
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    now_bj = _dt.now(_tz(_td(hours=8)))
    today_str = now_bj.strftime("%Y-%m-%d")

    port_path = _Path(__file__).resolve().parent.parent / "output" / "wc_sporttery_portfolio.json"
    pur_path = _Path(__file__).resolve().parent.parent / "output" / "wc_sporttery_purchases.json"
    opp_path = _Path(__file__).resolve().parent.parent / "output" / "wc_sporttery_opportunities.json"

    portfolio = _json.loads(port_path.read_text()) if port_path.exists() else None
    purchases = _json.loads(pur_path.read_text()) if pur_path.exists() else None
    sporttery_data = _json.loads(opp_path.read_text()) if opp_path.exists() else None

    # ==========================================

    # SECTION 1: DAILY RECOMMENDATIONS
    # ==========================================
    st.markdown("### 📅 投注推荐")
    allocs_raw = portfolio.get("opportunities", []) if portfolio else []
    allocations = [a for a in allocs_raw if a.get("optimal_stake", 0) > 0.001]

    if allocations:

        rows = ""
        for a in sorted(allocations, key=lambda x: (x.get("date",""), -x.get("optimal_stake",0))):
            d = a.get("date", "")[5:] if a.get("date") else "?"
            match_cn = a.get("match_cn", a.get("match", ""))
            pool = a.get("pool_code", "")
            sel = a.get("selection_cn", str(a.get("selection", "")))
            odds = a.get("odds", 0)
            ev = a.get("ev_calibrated", a.get("ev", 0))
            stake = a.get("optimal_stake", 0)
            tag = "★" if a.get("selection") == "D" else ""
            ht = _get_elo_tiers().get(a.get("home_en",""),4); at = _get_elo_tiers().get(a.get("away_en",""),4)
            rows += f"<tr><td>{d}</td><td>T{ht}vT{at}</td><td>{tag} {match_cn[:24]}</td><td><span class='sp-pool-badge sp-{pool}'>{pool}</span></td><td>{sel}</td><td class='num'>{odds:.2f}</td><td class='num'><span class='ev-badge {_ev_class(ev)}'>{ev:+.0%}</span></td><td class='num'>{stake:.1%}</td></tr>"
        st.markdown(f"""<table class="sp-table" style="margin-bottom:8px"><thead><tr>
          <th>日期</th><th>级别</th><th>比赛</th><th>玩法</th><th>选</th><th class="num">赔率</th><th class="num">EV</th><th class="num">仓位</th>
          </tr></thead><tbody>{rows}</tbody></table>""", unsafe_allow_html=True)
    else:
        st.info("暂无组合优化结果。请先运行体彩扫描 + 组合优化。")


    # ==========================================
    # Per-match hedge combos
    # ==========================================
    st.markdown('---')
    st.markdown('### 🔀 单场对冲组合')
    if sporttery_data:
        ops = sporttery_data.get('opportunities', [])
        # Group by match
        by_match = {}
        for o in ops:
            key = (o.get('home_en',''), o.get('away_en',''))
            if key not in by_match: by_match[key] = []
            by_match[key].append(o)
        
        combos = []
        for key, match_ops in by_match.items():
            had = {o['selection']: o for o in match_ops if o['pool_code'] == 'had'}
            if set(had.keys()) != {'H', 'D', 'A'}: continue
            
            h_op = had.get('H'); d_op = had.get('D'); a_op = had.get('A')
            if not all([h_op, d_op, a_op]): continue
            
            # D+A combo: win unless extreme home upset
            p_d = d_op.get('p_model_calibrated', d_op['p_model'])
            p_a = a_op.get('p_model_calibrated', a_op['p_model'])
            ev_d = d_op.get('ev_calibrated', d_op['ev'])
            ev_a = a_op.get('ev_calibrated', a_op['ev'])
            cover_da = p_d + p_a
            
            # H+D combo: win unless away win
            p_h = h_op.get('p_model_calibrated', h_op['p_model'])
            ev_h = h_op.get('ev_calibrated', h_op['ev'])
            cover_hd = p_h + p_d
            
            if ev_d > 0 and ev_a > 0:
                combos.append((key[0][:10]+' vs '+key[1][:10], 'D+A', d_op['odds'], a_op['odds'], ev_d, ev_a, cover_da, '%.0f%%'%(cover_da*100)))
            if ev_h > 0 and ev_d > 0:
                combos.append((key[0][:10]+' vs '+key[1][:10], 'H+D', h_op['odds'], d_op['odds'], ev_h, ev_d, cover_hd, '%.0f%%'%(cover_hd*100)))
        
        hhad_crs = []
        for key, match_ops in by_match.items():
            hhad = [o for o in match_ops if o['pool_code']=='hhad' and (o.get('handicap') or 0) < 0]
            crs = [o for o in match_ops if o['pool_code']=='crs' and o.get('p_model',0)>0.01]
            if hhad and crs:
                for hh in hhad:
                    best = max(crs, key=lambda x: x.get('ev_calibrated',0))
                    cp = hh.get('p_model_calibrated',hh['p_model']) + best.get('p_model_calibrated',best['p_model'])
                    hhad_crs.append((key[0][:12], hh['selection'], hh.get('handicap',0), best['selection_cn'], hh['odds'], best['odds'], hh.get('ev_calibrated',0), best.get('ev_calibrated',0), cp))
        if hhad_crs:
            rows = ''
            for m, sel, hcap, crs_sel, o1, o2, ev1, ev2, cp in sorted(hhad_crs, key=lambda x: -x[8]):
                rows += '<tr><td>'+m+'</td><td>hhad/'+sel+'('+('%+.0f'%hcap)+')+CRS/'+crs_sel+'</td><td class=num>'+('%.1f/%.1f'%(o1,o2))+'</td><td class=num>'+('%+.0f%%/%+.0f%%'%(ev1*100,ev2*100))+'</td><td class=num>'+('%.0f%%'%(cp*100))+'</td></tr>'
            st.markdown('<table class=sp-table><thead><tr><th>Match</th><th>Combo</th><th class=num>Odds</th><th class=num>EV</th><th class=num>Cover</th></tr></thead><tbody>'+rows+'</tbody></table>', unsafe_allow_html=True)
            st.caption('hhad+CRS hedge: hhad covers non-blowout, CRS covers blowout')
        if combos:
            rows = ''
            for match, ctype, odds1, odds2, ev1, ev2, cover, cov_s in sorted(combos, key=lambda x: -float(x[6])):
                rows += f'<tr><td>{match}</td><td>{ctype}</td><td class=num>{odds1:.1f} / {odds2:.1f}</td><td class=num>{ev1:+.0%} / {ev2:+.0%}</td><td class=num>{cov_s}</td></tr>'
            st.markdown(f'<table class=sp-table><thead><tr><th>比赛</th><th>组合</th><th class=num>赔率</th><th class=num>EV</th><th class=num>覆盖率</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)
            st.caption('对冲组合：买两边，只要不出现第三种结果就赚钱。覆盖率=至少中一边的概率。')
        else:
            st.caption('当前没有符合条件的对冲组合（需要 had 三个选项全开且至少两边 EV>0）')
    # ==========================================
    # SECTION 2: PURCHASE RECORDER
    # ==========================================
    st.markdown("---")
    st.markdown("### 📝 购买记录")
    ops = sporttery_data.get("opportunities", []) if sporttery_data else []
    if ops:
        ops.sort(key=lambda x: (x.get("date",""), x.get("match_cn", x.get("match","")), x.get("pool_priority",9), -x.get("ev_calibrated", x.get("ev",0))))
        fc1, fc2 = st.columns([3, 1])
        with fc1:
            filter_text = st.text_input("🔍 筛选（队名/玩法/选项）", value="", key="smart_filter", placeholder="如: 约旦 had H  → 留空显示全部")
        with fc2:
            st.caption(f"共 {len(ops)} 个可选")
        if filter_text.strip():
            ft = filter_text.strip().lower()
            filtered = [o for o in ops if (ft in o.get("match_cn","").lower() or ft in o.get("match","").lower() or ft in o.get("pool_name","").lower() or ft in o.get("pool_code","").lower() or ft in o.get("selection_cn","").lower() or ft in o.get("selection","").lower())]
            if not filtered: filtered = ops
            st.caption(f"🔎 匹配 {len(filtered)}/{len(ops)} 条")
        else:
            filtered = ops
        idx = st.selectbox("选择购买的竞彩", options=list(range(len(filtered))), format_func=lambda i: _fmt_purchase_option(filtered[i]), key="smart_purchase_select")
        stake = st.number_input("金额 (元)", min_value=2, value=100, step=10, key="smart_stake")
        if st.button("📝 记录购买", key="smart_record", use_container_width=True, type="primary"):
            from wc_betting.strategy.sporttery_tracker import add_purchase
            add_purchase(filtered[idx], float(stake))
            _load_sporttery_purchases.clear()
            st.success(f"已记录购买: {_fmt_purchase_option(filtered[idx])} · {stake}元")
            st.rerun()
    else:
        st.caption("暂无扫描结果，请先在中国体彩Tab抓取赔率。")

    # Manual entry
    with st.expander("✍️ 手动录入"):
        TEAM_NAMES_CN = sorted({cn(t)[0] for t in TEAM_CN if not t.startswith("Cura") or t == "Curacao"})
        _CN_TO_EN = {v[0]: k for k, v in TEAM_CN.items() if not k.startswith("Cura") or k == "Curacao"}
        with st.form("smart_manual_form"):
            m_home_cn = st.selectbox("主队", TEAM_NAMES_CN, key="sm_home")
            m_away_cn = st.selectbox("客队", TEAM_NAMES_CN, key="sm_away")
            m_date = st.selectbox("比赛日期", ["2026-06-23","2026-06-24","2026-06-25","2026-06-26","2026-06-27","2026-06-28"], key="sm_date")
            pool_opts = [p[0] for p in SP_POOLS]
            _pool_full = {p[0]: p[2] for p in SP_POOLS}
            m_pool = st.selectbox("玩法", pool_opts, format_func=lambda c: f"{c} — {_pool_full.get(c, c)}", key="sm_pool")
            if m_pool == "had": m_sel = st.selectbox("选项", ["H 主胜", "D 平", "A 客胜"], key="sm_sel")
            elif m_pool == "hhad": m_sel = st.selectbox("选项", ["H 让球主胜", "D 让球平", "A 让球客胜"], key="sm_sel")
            elif m_pool == "crs": m_sel = st.selectbox("选项 (比分)", CRS_SCORES, key="sm_sel")
            else: m_sel = st.selectbox("选项 (总进球)", TTG_OPTS, key="sm_sel")
            m_home_en = _CN_TO_EN.get(m_home_cn, m_home_cn)
            m_away_en = _CN_TO_EN.get(m_away_cn, m_away_cn)
            db_odds = None
            try:
                from wc_betting.data.sporttery_db import SportteryDB
                sel_lookup = m_sel[0] if m_pool in ("had","hhad") else ({"胜其他":"OTHER_H","平其他":"OTHER_D","负其他":"OTHER_A"}.get(m_sel, m_sel) if m_pool=="crs" else m_sel)
                rows = SportteryDB().query(home_cn=m_home_cn, away_cn=m_away_cn, pool_code=m_pool, selection=sel_lookup)
                if rows: db_odds = rows[0]["odds"]
            except Exception: pass
            mc3, mc4 = st.columns(2)
            with mc3:
                if db_odds: st.caption(f"📊 DB赔率: **{db_odds:.2f}**")
                else: st.caption("📊 未找到历史赔率，请手动输入")
                m_odds = st.number_input("赔率", min_value=1.01, value=db_odds or 2.00, step=0.01, key="sm_odds")
            with mc4:
                m_stake = st.number_input("金额 (元)", min_value=2, value=100, step=10, key="sm_stake")
            m_handicap = st.number_input("让球数 (仅hhad有效)", value=-1, step=1, key="sm_handicap")
            if st.form_submit_button("记录手动购买", use_container_width=True):
                from wc_betting.strategy.sporttery_tracker import add_purchase, POOL_NAMES_CN as _PN
                pool_short = dict((p[0], p[1]) for p in SP_POOLS).get(m_pool, m_pool)
                if m_pool == "had": sel_code, sel_cn = m_sel[0], m_sel[2:]
                elif m_pool == "hhad": sel_code, sel_cn = m_sel[0], m_sel[2:]
                elif m_pool == "crs":
                    sel_code = f"({m_sel.replace(':', ',')})" if "其他" not in m_sel else {"胜其他":"H_OTHER","平其他":"D_OTHER","负其他":"A_OTHER"}[m_sel]
                    sel_cn = m_sel
                else: sel_code, sel_cn = m_sel, m_sel
                m_group = "?"
                try:
                    _unified = _json.loads((ROOT / "data/processed/wc_2026_unified.json").read_text())
                    for _m in _unified:
                        if _m.get("home_en") == m_home_en and _m.get("away_en") == m_away_en:
                            m_group = _m.get("group", "?"); break
                except Exception: pass
                op = {"match": f"{m_home_en} vs {m_away_en}", "match_cn": f"{m_home_cn} vs {m_away_cn}", "date": m_date, "group": m_group, "pool_code": m_pool, "pool_name": _PN.get(m_pool, pool_short), "selection": sel_code, "selection_cn": sel_cn, "handicap": float(m_handicap) if m_pool=="hhad" else None, "odds": float(m_odds), "p_model": 0.0, "ev": 0.0}
                add_purchase(op, float(m_stake))
                _load_sporttery_purchases.clear()
                st.success("已记录手动购买")
                st.rerun()

    # ==========================================
    # SECTION 3: RESULTS TRACKING
    # ==========================================
    st.markdown("---")
    st.markdown("### 📊 战绩追踪")
    if purchases:
        all_purchases = purchases.get("purchases", [])
        settled = [p for p in all_purchases if p.get("settled")]
        pending = [p for p in all_purchases if not p.get("settled")]
        total_pl = sum(p.get("profit_cny", 0) for p in settled)
        total_staked = sum(p.get("stake_cny", 0) for p in settled)
        roi = total_pl / total_staked if total_staked > 0 else 0
        wins = sum(1 for p in settled if p.get("result") in ("WIN","WON"))
        losses = sum(1 for p in settled if p.get("result") == "LOST")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("累计盈亏", f"{total_pl:+.0f}¥", f"ROI {roi:+.1%}")
        c2.metric("战绩", f"{wins}W {losses}L", f"命中 {wins/max(wins+losses,1):.0%}")
        c3.metric("待结算", str(len(pending)), f"{len(pending)} 注")

        if pending:
            if st.button("🔄 结算已完赛比赛", key="smart_settle"):
                from wc_betting.strategy.sporttery_tracker import settle_from_unified
                settle_from_unified()
                _load_sporttery_purchases.clear()
                st.rerun()

        if pending:
            st.caption(f"⏳ 待结算 ({len(pending)} 注):")
            rows = ""
            for p in pending:
                rows += f"<tr><td>{p.get('match_cn','')[:20]}</td><td>{p.get('pool_name','')}/{p.get('selection_cn','')}</td><td class='num'>{p['odds']:.1f}</td><td class='num'>{p['stake_cny']:.0f}¥</td><td>⏳</td></tr>"
            st.markdown(f"""<table class="sp-table"><thead><tr><th>比赛</th><th>投注</th><th class="num">赔率</th><th class="num">金额</th><th>状态</th></tr></thead><tbody>{rows}</tbody></table>""", unsafe_allow_html=True)

        if settled:
            recent = sorted(settled, key=lambda x: x.get("settled_at",""), reverse=True)[:10]
            st.caption(f"最近结算 ({len(settled)} 注):")
            rows = ""
            for p in recent:
                icon = "✅" if p.get("result") in ("WIN","WON") else "❌"
                pl = p.get("profit_cny",0)
                rows += f"<tr><td>{p.get('date','')[-5:]}</td><td>{p.get('match_cn','')[:18]}</td><td>{p.get('pool_name','')}/{p.get('selection_cn','')}</td><td class='num'>{icon} {pl:+.0f}¥</td></tr>"

            st.markdown(f"""<table class="sp-table"><thead><tr><th>日期</th><th>比赛</th><th>投注</th><th class="num">结果</th></tr></thead><tbody>{rows}</tbody></table>""", unsafe_allow_html=True)

    # ==========================================
    # Purchase history + management
    # ==========================================
    st.markdown('---')
    st.markdown('### 📋 全部购买记录')
    if purchases:
        all_p = purchases.get('purchases', [])
        rows = ''
        for p in sorted(all_p, key=lambda x: (x.get('date', ''), x.get('id', '')), reverse=True)[:20]:
            s = p.get('settled')
            if not s:
                status = '⏳'
            elif p.get('result') in ('WIN', 'WON'):
                status = '✅'
            elif p.get('result') == 'PUSH':
                status = '↩'
            else:
                status = '❌'
            pl = p.get('profit_cny', 0) if s else 0
            pl_s = f'{pl:+.0f}¥' if s else '—'
            rows += f'<tr><td>{p.get("id","")}</td><td>{p.get("date","")[-5:]}</td><td>{(p.get("match_cn","") or "")[:18]}</td><td>{p.get("pool_name","")}/{p.get("selection_cn","")}</td><td class=num>{p["odds"]:.1f}</td><td class=num>{p["stake_cny"]:.0f}¥</td><td>{status} {pl_s}</td></tr>'
        st.markdown(f'<table class=sp-table><thead><tr><th>ID</th><th>日期</th><th>比赛</th><th>投注</th><th class=num>赔率</th><th class=num>金额</th><th>状态</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)

        # Management expander
        with st.expander('✏️ 管理购买记录 (修改金额 / 删除)'):
            def _fmt(p):
                return f"{p['id']} | {p.get('purchase_date','')[-5:]} | {(p.get('match_cn','') or '')[:18]} | {p.get('pool_name','')}/{p.get('selection_cn','')} | {p['stake_cny']:.0f}¥"
            idx = st.selectbox('选择记录', list(range(len(all_p))), format_func=lambda i: _fmt(all_p[i]), key='mgmt_select')
            tgt = all_p[idx]
            c1, c2 = st.columns([2, 1])
            with c1:
                ns = st.number_input('新金额 (元)', min_value=2, value=int(tgt['stake_cny']), step=10, key='mgmt_stake')
                if st.button('💾 更新金额', key='mgmt_update', use_container_width=True):
                    from wc_betting.strategy.sporttery_tracker import update_purchase_stake
                    update_purchase_stake(tgt['id'], float(ns))
                    _load_sporttery_purchases.clear()
                    st.success(f"已更新 {tgt['id']} 金额为 {ns}元")
                    st.rerun()
            with c2:
                cf = st.checkbox('确认删除', key='mgmt_confirm')
                if st.button('🗑️ 删除', key='mgmt_delete', use_container_width=True, disabled=not cf):
                    from wc_betting.strategy.sporttery_tracker import delete_purchase
                    delete_purchase(tgt['id'])
                    _load_sporttery_purchases.clear()
                    st.success(f"已删除 {tgt['id']}")
                    st.rerun()
    else:
        st.caption("暂无购买记录")

def _render_dual_track() -> None:
    import json,re
    from pathlib import Path
    from wc_betting.models.poisson import PoissonModel,score_matrix,RHO_NEUTRAL
    from wc_betting.models.elo import EloModel
    up=Path(__file__).resolve().parent.parent/'data/processed/wc_2026_unified.json'
    mp=Path(__file__).resolve().parent.parent/'data/processed/wc_2026_model_input.json'
    if not up.exists() or not mp.exists(): return
    u=json.loads(up.read_text()); mi=json.loads(mp.read_text())
    done=[g for g in u if g.get('finished') and g.get('score')]
    if len(done)<2: return
    try:
        hp=Path(__file__).resolve().parent.parent/'data/raw/historical/intl_results_2022_2026.json'
        h=json.loads(hp.read_text())['matches']
        model=PoissonModel.fit(matches=h,competitive_only=True)
        elo=EloModel();elo.calibrate()
    except: return
    rows='';mw=0;kw=0;n=0
    for g in done:
        hc=model.name_to_code.get(g['home_en']);ac=model.name_to_code.get(g['away_en'])
        if not hc or not ac: continue
        mat=score_matrix(model.params,hc,ac,rho=RHO_NEUTRAL,max_goals=8,draw_inflate=1.01,deflate_away=0.62,cross_conf=False)
        ph=sum(mat[h,a] for h in range(8) for a in range(8) if h>a)
        pd=sum(mat[h,h] for h in range(8))
        pa=sum(mat[h,a] for h in range(8) for a in range(8) if h<a)
        try: eh,ed,ea=elo.predict(g['home_en'],g['away_en'],hfa=0)
        except: eh,ed,ea=ph,pd,pa
        fh=0.25*ph+0.75*eh;fd=0.70*pd+0.30*ed;fa=0.25*pa+0.75*ea
        mh=md=ma=None
        for mm in mi.get('matches',[]):
            if mm.get('home')==g['home_en'] and mm.get('away')==g['away_en']:
                imp=mm.get('market_implied',{});mh=imp.get('h');md=imp.get('d');ma=imp.get('a');break
        if mh is None: continue
        p=re.split(r'[-]+',g['score'].replace(chr(0x2212),'-'))
        if len(p)!=2: continue
        hg,ag=int(p[0]),int(p[1])
        act='H' if hg>ag else ('D' if hg==ag else 'A')
        bm=(fh-(1 if act=='H' else 0))**2+(fd-(1 if act=='D' else 0))**2+(fa-(1 if act=='A' else 0))**2
        bk=(mh-(1 if act=='H' else 0))**2+(md-(1 if act=='D' else 0))**2+(ma-(1 if act=='A' else 0))**2
        w='M' if bm<bk else ('K' if bk<bm else '=')
        if bm<bk: mw+=1
        elif bk<bm: kw+=1
        n+=1
        rows+=f'<tr><td>{g.get("date","")[-5:]}</td><td>{g["home_en"][:8]} vs {g["away_en"][:8]}</td><td class=num>{hg}:{ag}</td><td class=num>{fh:.1%} {fd:.1%} {fa:.1%}</td><td class=num>{mh:.1%} {md:.1%} {ma:.1%}</td><td class=num>{bm:.3f}</td><td class=num>{bk:.3f}</td><td class=num>{w}</td></tr>'
    if rows:
        st.markdown(f'<table class=sp-table><thead><tr><th>Date</th><th>Match</th><th class=num>Score</th><th class=num>Model H/D/A</th><th class=num>Market H/D/A</th><th class=num>Model Brier</th><th class=num>Mkt Brier</th><th class=num>Win</th></tr></thead><tbody>{rows}</tbody></table>',unsafe_allow_html=True)
        st.caption(f"{n} matches | Model {mw} - Market {kw} | Auto-refreshes with page")
def render_sporttery_tab(finished=None):
    """体彩 EV 扫描: 抓取/手动录入 sporttery.cn 赔率并扫描 EV。"""
    # === 体彩 EV 扫描 ===

    st.markdown("---")
    # Elo consensus toggle
    _load_sporttery.clear()
    sporttery_data = _load_sporttery()

    spc1, _ = st.columns([1, 4])
    with spc1:
        if st.button("🔄 抓取体彩赔率", use_container_width=True,
                     key="refresh_sporttery",
                     help="从 sporttery.cn 抓取 4 种玩法赔率并扫描 EV (需在中国网络环境)"):
            from wc_betting.data.fetch_sporttery import fetch_all
            from wc_betting.strategy.sporttery_scanner import run as run_scan
            with st.spinner("抓取 sporttery.cn + 扫描 EV (~3s)..."):
                rows = fetch_all()
                if not rows:
                    st.error("⚠️ 未能抓取体彩赔率 (网络不可达?)。可展开下方手动录入。")
                else:
                    run_scan(odds_rows=rows)
                    # Archive fresh odds to history DB
                    try:
                        from wc_betting.data.sporttery_db import SportteryDB
                        SportteryDB().import_odds_rows(rows)
                    except Exception:
                        pass
                    _load_sporttery.clear()
                    st.rerun()
    if sporttery_data:
        _render_sporttery_opportunities(sporttery_data)
    else:
        st.info("暂无体彩扫描结果。点击上方按钮抓取,或展开下方手动录入 JSON 赔率。")
    with st.expander("✍️ 手动录入体彩赔率 (JSON)"):
        st.caption(
            "格式: [{home_cn, away_cn, home_en, away_en, date, group, "
            "pool_code, handicap, odds: {option: price}}, ...]。"
            "pool_code ∈ had/hhad/crs/ttg。crs option 用 '(1,0)' / 'H_OTHER' 等; "
            "ttg 用 '0'..'7'。"
        )
        manual_json = st.text_area(
            "赔率 JSON", height=220, key="sporttery_manual_json",
            placeholder='[\n  {"home_cn":"荷兰","away_cn":"瑞典",'
                        '"home_en":"Netherlands","away_en":"Sweden",'
                        '"date":"2026-06-21","group":"F",'
                        '"pool_code":"crs","handicap":null,"odds":{"(2,1)":8.5}}\n]')
        if st.button("应用手动赔率并扫描", key="apply_manual_sporttery"):
            if not manual_json.strip():
                st.warning("请输入有效的 JSON 赔率数据。")
            else:
                try:
                    data = json.loads(manual_json)
                except json.JSONDecodeError as e:
                    st.error(f"JSON 解析失败: {e}")
                    data = None
                if data is not None:
                    if not isinstance(data, list):
                        st.error("JSON 必须是数组。")
                    elif not data:
                        st.warning("JSON 为空。")
                    else:
                        from pathlib import Path as _P
                        from wc_betting.strategy.sporttery_scanner import (
                            run as run_scan)
                        tmp = _P("/tmp/sporttery_manual.json")
                        tmp.write_text(
                            json.dumps(data, ensure_ascii=False),
                            encoding="utf-8")
                        rows = load_manual_odds(tmp)
                        with st.spinner("扫描 EV (~3s)..."):
                            run_scan(odds_rows=rows)
                        # Archive manual odds to history DB
                        try:
                            from wc_betting.data.sporttery_db import SportteryDB
                            SportteryDB().import_odds_rows(rows)
                        except Exception:
                            pass
                        _load_sporttery.clear()
                        st.rerun()

    # === 组合优化 ===
    if sporttery_data and sporttery_data.get("opportunities"):
        portfolio_data = _load_sporttery_portfolio()
        spc2, _ = st.columns([1, 4])
        with spc2:
            if st.button("📐 运行组合优化", use_container_width=True,
                         key="run_sporttery_portfolio",
                         help="SLSQP 均值-方差优化, 考虑同场跨玩法相关性"):
                from wc_betting.strategy.sporttery_portfolio import run as run_portfolio
                with st.spinner("SLSQP 优化中 (~5s)..."):
                    run_portfolio()
                _load_sporttery_portfolio.clear()
                st.rerun()
        if portfolio_data and "error" not in portfolio_data:
            _render_sporttery_portfolio(portfolio_data)
        elif portfolio_data and "error" in portfolio_data:
            st.caption(f"组合优化: {portfolio_data['error']}")

    # === 模型校准曲线 (baseline vs 校准后) ===
    if _load_model_comparison():
        with st.expander("📊 模型校准曲线 (baseline vs 校准后)"):
            _render_calibration_curve()
    with st.expander("Dual Track"):
        _render_dual_track()


# === Main ===
def main() -> None:
    inject_css()

    # === 自动刷新 + 手动刷新 (比赛数据每 5 分钟同步) ===
    # 每次刷新会重新 _load_unified (因为 @st.cache_data ttl=300)
    try:
        from streamlit_autorefresh import st_autorefresh
        # 5 分钟自动刷新 (300000 ms) - 不显示倒计时
        st_autorefresh(interval=300_000, key="fifa_autorefresh")
    except ImportError:
        pass  # streamlit-autorefresh 未装,降级为手动刷新

    data = _load_unified()
    if data is None:
        st.warning("⚠️ 未找到世界杯数据。请先生成 `wc_2026_unified.json`。")
        st.code(f"expected: {UNIFIED_FILE}")
        return

    finished = [m for m in data if m.get("finished")]
    upcoming = [m for m in data if not m.get("finished")]

    # 找下一场
    next_match: dict | None = None
    if upcoming:
        now = _now_utc_naive()
        for m in sorted(upcoming, key=lambda x: x.get("commence_time", "")):
            iso = m.get("commence_time")
            if not iso:
                continue
            utc = datetime.fromisoformat(iso.replace("Z", ""))
            if utc.replace(tzinfo=None) >= now:
                next_match = m
                break

    # 已开赛小组数
    groups_done = len({m.get("group", "?") for m in finished if m.get("group")})

    # === Header + KPI ===
    render_header(len(finished), len(upcoming), next_match)
    render_kpi_strip(len(finished), len(upcoming), groups_done)

    # === 统一的页面头部: 进度条 + 刷新按钮 (Tab 之外) ===
    render_season_progress(finished, upcoming)

    # === 四个 Tab 分区: 未赛 (Tab1) + 已赛 (Tab2) + 价值下注 (Tab3) + 中国体彩 (Tab4) ===
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        f"📅 未赛 ({len(upcoming)} 场)",
        f"✅ 已赛 ({len(finished)} 场 · 默认折叠)",
        "📊 价值下注",
        "🎰 中国体彩",
        "🧠 智能投注",
    ])

    with tab1:
        if upcoming:
            render_upcoming_section(upcoming)
        else:
            st.info("🎉 全部比赛已完成!")

    with tab2:
        if finished:
            render_finished_section(finished)
        else:
            st.info("暂无已赛记录")

    with tab3:
        render_value_tab()

    with tab4:
        render_sporttery_tab(finished)

    with tab5:
        render_smart_betting_tab()

    # === Legend (Tab 外面, 统一在底部) ===
    render_legend()


if __name__ == "__main__":
    main()
