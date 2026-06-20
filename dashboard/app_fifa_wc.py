"""
FIFA 世界杯赔率 + 战绩看板 V4
==========================

独立 Streamlit app, 端口 8507 (云端: ?app=fifa)
设计语言: 参照 FIFA.com / Flashscore / SofaScore / OddsPortal
- FIFA 蓝 + 金主色
- 比赛作为"行" (CSS Grid)
- 国旗圆形锚
- 数据 mono 字体
- 状态色彩编码 (FT/LIVE/NS)

作者: Hermes Agent
日期: 2026-06-20
"""
from __future__ import annotations
import json
from datetime import datetime, timezone, timedelta
from html import unescape
from pathlib import Path

import streamlit as st
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

UNIFIED_FILE = ROOT / "data" / "processed" / "wc_2026_unified.json"
CSS_FILE = ROOT / "dashboard" / "assets" / "fifa_style.css"

# === 球队英文 → 中文 + 国旗 ===
TEAM_CN = {
    "Mexico": ("墨西哥", "🇲🇽"), "South Africa": ("南非", "🇿🇦"),
    "South Korea": ("韩国", "🇰🇷"), "Czech Republic": ("捷克", "🇨🇿"),
    "Canada": ("加拿大", "🇨🇦"), "Bosnia and Herzegovina": ("波黑", "🇧🇦"),
    "Bosnia & Herzegovina": ("波黑", "🇧🇦"), "Qatar": ("卡塔尔", "🇶🇦"),
    "Switzerland": ("瑞士", "🇨🇭"),
    "Brazil": ("巴西", "🇧🇷"), "Morocco": ("摩洛哥", "🇲🇦"),
    "Haiti": ("海地", "🇭🇹"), "Scotland": ("苏格兰", "🏴󠁧󠁢󠁳󠁣󠁴󠁿"),
    "USA": ("美国", "🇺🇸"), "United States": ("美国", "🇺🇸"),
    "Paraguay": ("巴拉圭", "🇵🇾"), "Australia": ("澳大利亚", "🇦🇺"),
    "Turkey": ("土耳其", "🇹🇷"),
    "Germany": ("德国", "🇩🇪"), "Curaçao": ("库拉索", "🇨🇼"),
    "Ivory Coast": ("科特迪瓦", "🇨🇮"), "Ecuador": ("厄瓜多尔", "🇪🇨"),
    "Netherlands": ("荷兰", "🇳🇱"), "Japan": ("日本", "🇯🇵"),
    "Sweden": ("瑞典", "🇸🇪"), "Tunisia": ("突尼斯", "🇹🇳"),
    "Belgium": ("比利时", "🇧🇪"), "Egypt": ("埃及", "🇪🇬"),
    "Iran": ("伊朗", "🇮🇷"), "New Zealand": ("新西兰", "🇳🇿"),
    "Spain": ("西班牙", "🇪🇸"), "Cape Verde": ("佛得角", "🇨🇻"),
    "Saudi Arabia": ("沙特", "🇸🇦"), "Uruguay": ("乌拉圭", "🇺🇾"),
    "France": ("法国", "🇫🇷"), "Senegal": ("塞内加尔", "🇸🇳"),
    "Iraq": ("伊拉克", "🇮🇶"), "Norway": ("挪威", "🇳🇴"),
    "Argentina": ("阿根廷", "🇦🇷"), "Algeria": ("阿尔及利亚", "🇩🇿"),
    "Austria": ("奥地利", "🇦🇹"), "Jordan": ("约旦", "🇯🇴"),
    "Portugal": ("葡萄牙", "🇵🇹"), "DR Congo": ("刚果(金)", "🇨🇩"),
    "Uzbekistan": ("乌兹别克斯坦", "🇺🇿"), "Colombia": ("哥伦比亚", "🇨🇴"),
    "England": ("英格兰", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"), "Croatia": ("克罗地亚", "🇭🇷"),
    "Ghana": ("加纳", "🇬🇭"), "Panama": ("巴拿马", "🇵🇦"),
}

def cn(name):
    """球队名 → (中文, 国旗). 自动处理 HTML 实体和 's men's 写法"""
    if not name:
        return ("?", "🏳️")
    # 1. unescape HTML entities (Wikipedia 解析后是 'Canada men&#39;s')
    clean = unescape(name)
    # 2. 归一化常见写法
    clean = clean.replace(" men's", "").replace(" men's", "")  # Canada men's → Canada
    return TEAM_CN.get(clean, TEAM_CN.get(name, (clean, "🏳️")))


# === 页面配置 ===
st.set_page_config(
    page_title="FIFA 2026 赔率看板",
    page_icon="🌍",
    layout="wide",
)


def inject_css():
    """注入 FIFA 专属 CSS"""
    if CSS_FILE.exists():
        css = CSS_FILE.read_text()
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


@st.cache_data(ttl=300)
def _load_unified():
    if not UNIFIED_FILE.exists():
        return None
    return json.loads(UNIFIED_FILE.read_text())


def render_header(finished_total, unfinished_total, next_match):
    """FIFA 蓝品牌 header + 下一场倒计时"""
    if next_match:
        utc = datetime.fromisoformat(next_match["commence_time"].replace("Z", ""))
        bj = utc + timedelta(hours=8)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        diff = utc.replace(tzinfo=None) - now
        if diff.total_seconds() > 0:
            days = int(diff.total_seconds() // 86400)
            hours = int((diff.total_seconds() % 86400) // 3600)
            mins = int((diff.total_seconds() % 3600) // 60)
            countdown = f"<strong>{days}d {hours}h {mins}m</strong>"
            countdown_label = "下一场开赛"
            home_cn, _ = cn(next_match.get("home_team") or next_match.get("home_en", ""))
            away_cn, _ = cn(next_match.get("away_team") or next_match.get("away_en", ""))
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
    st.markdown(html, unsafe_allow_html=True)


def render_kpi_strip(finished, unfinished):
    """紧凑 KPI 条 (4 列)"""
    total = finished + unfinished
    today = datetime.now(timezone.utc).date().isoformat()
    today_count = 0
    # 今日未赛 (本地)
    for m in (unfinished and []):  # placeholder, 实际由 caller 传
        pass

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
          <span class="kpi-label">已赛 FT</span>
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
          <span class="kpi-value">12</span>
          <span class="kpi-label">小组</span>
        </div>
      </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def render_match_row_finished(m):
    """已赛比赛行"""
    home_cn, home_flag = cn(m["home_en"])
    away_cn, away_flag = cn(m["away_en"])
    grp = m.get("group", "?")
    score = m.get("score", "–")

    return f"""
    <div class="match-row finished">
      <div class="m-time">FT</div>
      <div class="m-team home">
        <span class="flag">{home_flag}</span>
        <span>{home_cn}</span>
      </div>
      <div class="m-score">{score.replace('-', ' <span class="sep">–</span> ')}</div>
      <div class="m-team away">
        <span class="flag">{away_flag}</span>
        <span>{away_cn}</span>
      </div>
      <div></div>
      <div class="m-status">
        <span class="badge group">Group {grp}</span>
      </div>
    </div>
    """


def render_match_row_upcoming(m):
    """未赛比赛行"""
    home_cn, home_flag = cn(m["home_en"])
    away_cn, away_flag = cn(m["away_en"])
    grp = m.get("group", "?")

    # 时间
    utc = datetime.fromisoformat(m["commence_time"].replace("Z", ""))
    bj = utc + timedelta(hours=8)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    diff_min = (utc.replace(tzinfo=None) - now).total_seconds() / 60

    if -120 <= diff_min <= 0:
        time_html = '<div class="m-time live">LIVE</div>'
    else:
        time_html = f'<div class="m-time">{bj.strftime("%H:%M")}</div>'

    # 赔率
    metrics = m.get("metrics", {})
    if metrics:
        h = metrics.get("avg_h", 0)
        d = metrics.get("avg_d", 0)
        a = metrics.get("avg_a", 0)
        # Best odds (最高赔付对玩家最有利)
        # 主胜最低 vs 平/客胜最高 → 标注"对客胜玩家最有利"
        # 简化: 只显示 3 个赔率, 不高亮 (避免误解)
        odds_html = f"""
        <div class="m-odds">
          <div class="odd"><span class="label">主</span><span class="value">{h:.2f}</span></div>
          <div class="odd"><span class="label">平</span><span class="value">{d:.2f}</span></div>
          <div class="odd"><span class="value">{a:.2f}</span></div>
        </div>
        """
    else:
        odds_html = '<div class="m-odds"><div class="odd"><span class="value">—</span></div></div>'

    return f"""
    <div class="match-row">
      {time_html}
      <div class="m-team home">
        <span class="flag">{home_flag}</span>
        <span>{home_cn}</span>
      </div>
      <div class="m-score"><span class="vs">vs</span></div>
      <div class="m-team away">
        <span class="flag">{away_flag}</span>
        <span>{away_cn}</span>
      </div>
      {odds_html}
      <div class="m-status">
        <span class="badge group">Group {grp}</span>
      </div>
    </div>
    """


def render_finished_section(finished):
    """已赛区块"""
    st.markdown("### ✅ 已赛 32 场")

    from collections import defaultdict
    by_group = defaultdict(list)
    for m in finished:
        by_group[m["group"]].append(m)

    for grp in "ABCDEFGHIJKL":
        if grp not in by_group:
            continue
        matches = by_group[grp]
        # 收集 4 队 (从该组比赛)
        teams = []
        for m in matches:
            for t in [m["home_en"], m["away_en"]]:
                if t not in teams:
                    teams.append(t)
            if len(teams) >= 4:
                break
        flags = "".join(cn(t)[1] for t in teams[:4])

        done = len(matches)
        # 锚
        anchor = f"""
        <div class="group-anchor">
          <span class="group-chip">Group {grp}</span>
          <span class="group-flags">{flags}</span>
          <span class="group-progress"><strong>{done}</strong> / 6 已赛</span>
        </div>
        """
        st.markdown(anchor, unsafe_allow_html=True)

        # 行列表
        st.markdown('<div class="match-list finished">', unsafe_allow_html=True)
        rows_html = ""
        for m in matches:
            rows_html += render_match_row_finished(m)
        st.markdown(rows_html, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)


def render_upcoming_section(upcoming):
    """未赛区块"""
    st.markdown("### ⏳ 未赛 · 按日期排序")

    # 按日期分组
    from collections import defaultdict
    by_date = defaultdict(list)
    for m in upcoming:
        bj = datetime.fromisoformat(m["commence_time"].replace("Z", "")) + timedelta(hours=8)
        date_key = bj.strftime("%Y-%m-%d")
        by_date[date_key].append(m)

    weekday_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

    for date_key in sorted(by_date.keys()):
        matches = by_date[date_key]
        dt = datetime.strptime(date_key, "%Y-%m-%d")
        wd = weekday_cn[dt.weekday()]

        # 日期 header
        header = f"""
        <div class="date-header">
          <span class="date-label">📅 {date_key}</span>
          <span class="date-weekday">{wd}</span>
          <span class="date-count">{len(matches)} 场比赛</span>
        </div>
        """
        st.markdown(header, unsafe_allow_html=True)

        # 行列表
        st.markdown('<div class="match-list">', unsafe_allow_html=True)
        rows_html = ""
        # 按 commence_time 排序
        matches.sort(key=lambda x: x["commence_time"])
        for m in matches:
            rows_html += render_match_row_upcoming(m)
        st.markdown(rows_html, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)


def render_legend():
    """字段解读"""
    html = """
    <div class="legend">
      <strong>📐 字段解读</strong><br>
      • <span class="legend-key">主/平/客</span> 主胜/平局/客胜赔率 (去 vig 后均值)
      · <span class="legend-key">FT</span> 已完赛 (Full Time)
      · <span class="legend-key">LIVE</span> 进行中
      · <span class="legend-key">Group X</span> 所在小组<br>
      <em>设计参考: FIFA.com, Flashscore, SofaScore, OddsPortal</em>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def main():
    inject_css()

    data = _load_unified()
    if data is None:
        st.warning("⚠️ 未找到世界杯数据。运行:")
        st.code("bash scripts/fetch_csl_odds.sh")
        return

    finished = [m for m in data if m["finished"]]
    upcoming = [m for m in data if not m["finished"]]

    # 找下一场
    next_match = None
    if upcoming:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        upcoming.sort(key=lambda x: x["commence_time"])
        for m in upcoming:
            utc = datetime.fromisoformat(m["commence_time"].replace("Z", ""))
            if utc.replace(tzinfo=None) >= now:
                next_match = m
                break

    # === Header + KPI ===
    render_header(len(finished), len(upcoming), next_match)
    render_kpi_strip(len(finished), len(upcoming))

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