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
# - Scotland / England 用 regional indicator 序列 (无法被 OS 渲染的国旗)
TEAM_CN: dict[str, tuple[str, str]] = {
    # A
    "Mexico":               ("墨西哥", "🇲🇽"),
    "South Africa":         ("南非", "🇿🇦"),
    "South Korea":          ("韩国", "🇰🇷"),
    "Czech Republic":       ("捷克", "🇨🇿"),
    # B
    "Canada":               ("加拿大", "🇨🇦"),
    # Bosnia & Herzegovina 用 normalize_team() 归一化为 "Bosnia and Herzegovina"
    # 所以只需要一个 key, 函数会处理两种写法
    "Bosnia and Herzegovina": ("波黑", "🇧🇦"),
    "Qatar":                ("卡塔尔", "🇶🇦"),
    "Switzerland":          ("瑞士", "🇨🇭"),
    # C
    "Brazil":               ("巴西", "🇧🇷"),
    "Morocco":              ("摩洛哥", "🇲🇦"),
    "Haiti":                ("海地", "🇭🇹"),
    "Scotland":             ("苏格兰", "🏴\U000E0067\U000E0062\U000E0073\U000E0063\U000E0074\U000E007F"),
    # D
    "USA":                  ("美国", "🇺🇸"),
    "United States":        ("美国", "🇺🇸"),
    "Paraguay":             ("巴拉圭", "🇵🇾"),
    "Australia":            ("澳大利亚", "🇦🇺"),
    "Turkey":               ("土耳其", "🇹🇷"),
    # E
    "Germany":              ("德国", "🇩🇪"),
    "Curaçao":              ("库拉索", "🇨🇼"),
    "Ivory Coast":          ("科特迪瓦", "🇨🇮"),
    "Ecuador":              ("厄瓜多尔", "🇪🇨"),
    "Netherlands":          ("荷兰", "🇳🇱"),
    # F
    "Japan":                ("日本", "🇯🇵"),
    "Sweden":               ("瑞典", "🇸🇪"),
    "Tunisia":              ("突尼斯", "🇹🇳"),
    "Belgium":              ("比利时", "🇧🇪"),
    "Egypt":                ("埃及", "🇪🇬"),
    # G
    "Iran":                 ("伊朗", "🇮🇷"),
    "New Zealand":          ("新西兰", "🇳🇿"),
    "Spain":                ("西班牙", "🇪🇸"),
    "Cape Verde":           ("佛得角", "🇨🇻"),
    "Saudi Arabia":         ("沙特", "🇸🇦"),
    # H
    "Uruguay":              ("乌拉圭", "🇺🇾"),
    "France":               ("法国", "🇫🇷"),
    "Senegal":              ("塞内加尔", "🇸🇳"),
    "Iraq":                 ("伊拉克", "🇮🇶"),
    "Norway":               ("挪威", "🇳🇴"),
    # I
    "Argentina":            ("阿根廷", "🇦🇷"),
    "Algeria":              ("阿尔及利亚", "🇩🇿"),
    "Austria":              ("奥地利", "🇦🇹"),
    "Jordan":               ("约旦", "🇯🇴"),
    # J
    "Portugal":             ("葡萄牙", "🇵🇹"),
    "DR Congo":             ("刚果(金)", "🇨🇩"),
    "Uzbekistan":           ("乌兹别克斯坦", "🇺🇿"),
    "Colombia":             ("哥伦比亚", "🇨🇴"),
    # K
    "England":              ("英格兰", "🏴\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F"),
    "Croatia":              ("克罗地亚", "🇭🇷"),
    "Ghana":                ("加纳", "🇬🇭"),
    "Panama":               ("巴拿马", "🇵🇦"),
}

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
    """球队名 → (中文, 国旗).

    测试用例:
      cn("Canada men&#39;s")  -> ("加拿大", "🇨🇦")
      cn("USA")               -> ("美国",   "🇺🇸")
      cn("Bosnia & Herzegovina") -> ("波黑", "🇧🇦")
    """
    if not name:
        return ("?", "\U0001F3F3")
    # 先按原名查 (兼容 "Bosnia & Herzegovina" 直接命中 — 也会先 normalize 命中)
    if name in TEAM_CN:
        return TEAM_CN[name]
    # 归一化后再查 (处理 men's / Bosnia & Herzegovina 等变体)
    norm = normalize_team(name)
    if norm in TEAM_CN:
        return TEAM_CN[norm]
    # 已归一化但仍缺 → 返回归一化名 + 灰色旗
    return (norm or "?", "\U0001F3F3")


# === 页面配置 ===
st.set_page_config(
    page_title="FIFA 2026 赔率看板",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="collapsed",
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
    """已赛比赛行 - 用 st.columns + 每段单独 st.markdown"""
    home_cn, home_flag = cn(m.get("home_en", ""))
    away_cn, away_flag = cn(m.get("away_en", ""))
    grp = m.get("group", "?")
    score = m.get("score") or "–"

    # 用 streamlit columns 强制布局 (6 列), 然后每列内独立 st.markdown
    cols = st.columns([1, 3, 1.2, 3, 0.5, 1.4], gap="small")
    with cols[0]:
        st.markdown('<div class="m-time">FT</div>', unsafe_allow_html=True)
    with cols[1]:
        st.markdown(
            f'<div class="m-team home"><span class="flag">{home_flag}</span><span>{home_cn}</span></div>',
            unsafe_allow_html=True,
        )
    with cols[2]:
        st.markdown(f'<div class="m-score">{_format_score(score)}</div>', unsafe_allow_html=True)
    with cols[3]:
        st.markdown(
            f'<div class="m-team away"><span class="flag">{away_flag}</span><span>{away_cn}</span></div>',
            unsafe_allow_html=True,
        )
    with cols[4]:
        st.markdown("<div></div>", unsafe_allow_html=True)
    with cols[5]:
        st.markdown(
            f'<div class="m-status"><span class="badge group">Group {grp}</span></div>',
            unsafe_allow_html=True,
        )
    # 加底部分隔线 (CSS 已用 border-bottom, 但用 st.empty 占位让 streamlit 渲染 row)
    st.markdown("", unsafe_allow_html=False)


def render_match_row_upcoming(m: dict) -> None:
    """未赛比赛行 - 用 st.columns + 每段单独 st.markdown"""
    home_cn, home_flag = cn(m.get("home_en", ""))
    away_cn, away_flag = cn(m.get("away_en", ""))
    grp = m.get("group", "?")
    time_html = _match_time_html(m)

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

    # 6 列布局: 时间 | 主队 | vs | 客队 | 赔率3列 | Group
    cols = st.columns([1, 3, 0.6, 3, 3, 1.4], gap="small")
    with cols[0]:
        st.markdown(time_html, unsafe_allow_html=True)
    with cols[1]:
        st.markdown(
            f'<div class="m-team home"><span class="flag">{home_flag}</span><span>{home_cn}</span></div>',
            unsafe_allow_html=True,
        )
    with cols[2]:
        st.markdown('<div class="m-score"><span class="vs">vs</span></div>', unsafe_allow_html=True)
    with cols[3]:
        st.markdown(
            f'<div class="m-team away"><span class="flag">{away_flag}</span><span>{away_cn}</span></div>',
            unsafe_allow_html=True,
        )
    # 赔率区: 嵌套 3 列 + 概率行
    with cols[4]:
        if best_val is None:
            # 没数据, 显示占位
            st.markdown('<div class="m-odds"><div class="odd"><span class="value">—</span></div></div>', unsafe_allow_html=True)
        else:
            odd_cols = st.columns(3, gap="small")
            for i, (val, label) in enumerate(odds):
                cls = "odd best" if val == best_val else "odd"
                with odd_cols[i]:
                    st.markdown(
                        f'<div class="{cls}"><span class="label">{label}</span><span class="value">{val:.2f}</span></div>',
                        unsafe_allow_html=True,
                    )
            # 主/平/客 隐含胜率 (从赔率反推)
            p_h = float(metrics.get("p_h_mean") or 0)
            if p_h > 0 and h > 0 and d > 0 and a > 0:
                raw = 1/h + 1/d + 1/a  # 去 vig 前的隐含概率之和
                p_h_nv = (1/h) / raw
                p_d_nv = (1/d) / raw
                p_a_nv = (1/a) / raw
                # 最高概率高亮 (跟 best odds 一致)
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
                st.markdown(p_html, unsafe_allow_html=True)
    with cols[5]:
        st.markdown(
            f'<div class="m-status"><span class="badge group">Group {grp}</span></div>',
            unsafe_allow_html=True,
        )
    # 分隔
    st.markdown("", unsafe_allow_html=False)


# === 已赛区块 ===
def render_finished_section(finished: list[dict]) -> None:
    """已赛区块: 按 Group A-L, 每组 4 国旗 + match-list"""
    st.markdown("### ✅ 已赛 32 场 · 按小组")

    by_group: dict[str, list[dict]] = defaultdict(list)
    for m in finished:
        by_group[m.get("group", "?")].append(m)

    for grp in "ABCDEFGHIJKL":
        if grp not in by_group:
            continue
        matches = by_group[grp]
        # 收集该组 4 队 (从比赛 dedup)
        teams: list[str] = []
        for m in matches:
            for t in [m.get("home_en", ""), m.get("away_en", "")]:
                if t and t not in teams:
                    teams.append(t)
            if len(teams) >= 4:
                break
        flags = "".join(cn(t)[1] for t in teams[:4])

        done = len(matches)
        anchor = f"""
        <div class="group-anchor">
          <span class="group-chip">Group {grp}</span>
          <span class="group-flags">{flags}</span>
          <span class="group-progress"><strong>{done}</strong> / 6 已赛</span>
        </div>
        """
        render_html(anchor)

        # 行列表 - 直接循环调 render_match_row_finished (内部用 st.columns 渲染)
        for m in matches:
            render_match_row_finished(m)


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

    # === 已赛 ===
    if finished:
        render_finished_section(finished)

    # === 未赛 ===
    if upcoming:
        render_upcoming_section(upcoming)

    # === Legend ===
    render_legend()


if __name__ == "__main__":
    main()