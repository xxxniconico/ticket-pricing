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
- data/processed/wc_2026_unified.json  (72 场: 32 已赛 + 40 未赛)

作者: Hermes Agent
日期: 2026-06-20
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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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

def flag_html(iso_code: str) -> str:
    """生成 <img> 国旗标签 (含 fallback emoji if CDN fails)"""
    return f'<img src="{FLAG_BASE_URL}/w{FLAG_WIDTH}/{iso_code}.png" class="flag-img" alt="{iso_code}" loading="lazy" onerror="this.style.display=\'none\'"/>'

# 48 个 unique 国家队 (做断言)
UNIQUE_TEAMS = {
    "Mexico", "South Africa", "South Korea", "Czech Republic",
    "Canada", "Bosnia and Herzegovina", "Qatar", "Switzerland",
    "Brazil", "Morocco", "Haiti", "Scotland",
    "USA", "Paraguay", "Australia", "Turkey",
    "Germany", "Curaçao", "Ivory Coast", "Ecuador", "Netherlands",
    "Japan", "Sweden", "Tunisia", "Belgium", "Egypt",
    "Iran", "New Zealand", "Spain", "Cape Verde", "Saudi Arabia",
    "Uruguay", "France", "Senegal", "Iraq", "Norway",
    "Argentina", "Algeria", "Austria", "Jordan",
    "Portugal", "DR Congo", "Uzbekistan", "Colombia",
    "England", "Croatia", "Ghana", "Panama",
}
assert len(UNIQUE_TEAMS) == 48, f"expected 48 unique teams, got {len(UNIQUE_TEAMS)}"

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
    用于 streamlit button label (不能用 HTML, 必须用纯文本).

    每个字母转成对应的 regional indicator symbol (A=🇦 ... Z=🇿).
    例: 'mx' → 🇲🇽, 'gb-eng' → 🏴󠁧󠁢󠁥󠁮󠁧󠁿 (fallback for non-ISO codes).
    """
    if not iso_code:
        return "🏳️"
    iso = iso_code.lower()
    # 非标准 ISO code (Scotland / England 等)
    special = {"gb-sct": "🏴󠁧󠁢󠁳󠁣󠁴󠁿", "gb-eng": "🏴󠁧󠁢󠁥󠁮󠁧󠁿"}
    if iso in special:
        return special[iso]
    # 标准 ISO 3166-1 alpha-2: 2 字母
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


def render_match_row_finished(m: dict) -> None:
    """已赛比赛行 - 用单个 st.markdown + CSS grid 完全控制响应式"""
    home_cn, home_flag = cn(m.get("home_en", ""))
    away_cn, away_flag = cn(m.get("away_en", ""))
    grp = m.get("group", "?")
    score = m.get("score") or "–"
    home_flag_img = flag_img(home_flag)
    away_flag_img = flag_img(away_flag)

    # 用单个 st.markdown 渲染整行 (CSS grid 处理响应式)
    row_html = f"""<div class="match-row finished">
      <div class="m-time">FT</div>
      <div class="m-team home"><span class="flag">{home_flag_img}</span><span>{home_cn}</span></div>
      <div class="m-score">{_format_score(score)}</div>
      <div class="m-team away"><span class="flag">{away_flag_img}</span><span>{away_cn}</span></div>
      <div></div>
      <div class="m-status"><span class="badge group">Group {grp}</span></div>
    </div>"""
    st.markdown(row_html, unsafe_allow_html=True)


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
      <div class="m-status"><span class="badge group">Group {grp}</span></div>
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
    st.markdown("### ✅ 已赛 32 场 · 按小组")
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

    # === 展开区域: 显示每个展开组的 (1) 积分榜 + (2) 比赛结果 ===
    for grp in active_groups:
        if (grp in st.session_state.expanded_groups) or ("ALL" in st.session_state.expanded_groups):
            matches = by_group[grp]
            # 算积分 + 净胜球
            standings = _compute_standings(matches)
            # 渲染积分榜
            render_standings(standings, grp)
            # 渲染比赛结果
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
    """已赛比赛行 HTML (供 render_finished_section 拼接)"""
    home_cn, home_flag = cn(m.get("home_en", ""))
    away_cn, away_flag = cn(m.get("away_en", ""))
    grp = m.get("group", "?")
    score = m.get("score") or "–"
    home_flag_img = flag_img(home_flag)
    away_flag_img = flag_img(away_flag)
    return (
        f'<div class="match-row finished">'
        f'<div class="m-time">FT</div>'
        f'<div class="m-team home"><span class="flag">{home_flag_img}</span><span>{home_cn}</span></div>'
        f'<div class="m-score">{_format_score(score)}</div>'
        f'<div class="m-team away"><span class="flag">{away_flag_img}</span><span>{away_cn}</span></div>'
        f'<div></div>'
        f'<div class="m-status"><span class="badge group">Group {grp}</span></div>'
        f'</div>'
    )


# === 未赛区块 ===
def render_upcoming_section(upcoming: list[dict]) -> None:
    """未赛区块: 按日期分组, 含赔率 3 列"""
    st.markdown("### ⏳ 未赛 40 场 · 按日期")

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

    # === 两个 Tab 分区: 未赛 (Tab1) + 已赛 (Tab2) ===
    # 用 streamlit tabs, 头部 KPI / 进度条 / Header 保持在 tabs 之外
    tab1, tab2 = st.tabs([
        f"📅 未赛 ({len(upcoming)} 场)",
        f"✅ 已赛 ({len(finished)} 场 · 默认折叠)",
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

    # === Legend (Tab 外面, 统一在底部) ===
    render_legend()


if __name__ == "__main__":
    main()