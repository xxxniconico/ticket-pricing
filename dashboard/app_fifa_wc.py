"""
FIFA 世界杯赔率 + 战绩看板 V2
==========================

独立 Streamlit app, 端口 8507 (云端: ?app=fifa)
- 12 个小组分类展示
- 国旗 emoji 标识
- 已赛 + 未赛 72 场全显示
- 强队出场只显示均值, 不列公司明细
- 数据源: Wikipedia (已赛) + The Odds API (未赛)

作者: Hermes Agent
日期: 2026-06-20
"""
from __future__ import annotations
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

UNIFIED_FILE = ROOT / "data" / "processed" / "wc_2026_unified.json"

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
    """球队名 → (中文, 国旗)"""
    if name in TEAM_CN:
        return TEAM_CN[name]
    return (name, "🏳️")


# === 页面配置 ===
st.set_page_config(
    page_title="🌍 世界杯赔率看板",
    page_icon="🌍",
    layout="wide",
)

# === 顶部品牌 ===
st.markdown("""
<div style="background: linear-gradient(90deg, #1e3a8a 0%, #3b82f6 100%);
            padding: 16px; border-radius: 8px; margin-bottom: 16px;">
  <h2 style="color: white; margin: 0;">🌍 世界杯赔率看板 · 美加墨 2026</h2>
  <p style="color: #cbd5e1; margin: 4px 0 0 0;">
    12 个小组 · 已赛 + 未赛 72 场 · 数据源 Wikipedia + The Odds API · 仅展示
  </p>
</div>
""", unsafe_allow_html=True)


@st.cache_data(ttl=300)
def _load_unified():
    if not UNIFIED_FILE.exists():
        return None
    return json.loads(UNIFIED_FILE.read_text())


def render_match_card(m):
    """单场比赛卡片"""
    home_cn, home_flag = cn(m['home_en'])
    away_cn, away_flag = cn(m['away_en'])

    # 标题
    if m['finished']:
        title = f"{home_flag} **{home_cn}** {m['score']} **{away_cn}** {away_flag}"
        st.markdown(f"#### ✅ {title}")
    else:
        metrics = m.get('metrics', {})
        date_cn = m.get('date_cn', m.get('date', ''))
        st.markdown(f"#### ⏳ {date_cn} 北京 | {home_flag} **{home_cn}** vs {away_flag} **{away_cn}**")

        if metrics:
            c1, c2, c3, c4, c5 = st.columns(5)
            with c1:
                st.metric("主胜概率", f"{metrics.get('p_h_mean', 0):.1%}")
            with c2:
                st.metric("主胜赔率", f"{metrics.get('avg_h', 0):.2f}")
            with c3:
                st.metric("平局赔率", f"{metrics.get('avg_d', 0):.2f}")
            with c4:
                st.metric("客胜赔率", f"{metrics.get('avg_a', 0):.2f}")
            with c5:
                std = metrics.get('p_h_std', 0)
                level = "🔴 高" if std > 0.05 else ("🟡 中" if std > 0.02 else "🟢 低")
                st.metric("分歧度", f"{std:.3f} {level}")
        else:
            st.caption("暂无赔率数据")


def render_group_section(group, matches):
    """渲染单个小组"""
    matches.sort(key=lambda x: (x.get('date', ''), 0 if x['finished'] else 1))
    finished = [m for m in matches if m['finished']]
    unfinished = [m for m in matches if not m['finished']]

    # 头部: 4 支队
    teams_seen = []
    for m in matches:
        if m['home_en'] not in teams_seen:
            teams_seen.append(m['home_en'])
        if m['away_en'] not in teams_seen:
            teams_seen.append(m['away_en'])
    team_flags = " ".join(f"{cn(t)[1]} {cn(t)[0]}" for t in teams_seen[:4])

    n_total = len(matches)
    n_done = len(finished)
    st.markdown(f"### 🏆 Group {group} ({n_done}/{n_total} 已赛)")
    st.caption(team_flags)

    # 已赛
    if finished:
        st.markdown("**✅ 已赛**")
        for m in finished:
            render_match_card(m)

    # 未赛
    if unfinished:
        st.markdown("**⏳ 未赛**")
        for m in unfinished:
            render_match_card(m)

    st.divider()


def main():
    data = _load_unified()
    if data is None:
        st.warning("⚠️ 未找到世界杯数据。运行:")
        st.code("bash scripts/fetch_csl_odds.sh  # 拉赔率 + Wikipedia 解析")
        return

    finished_total = sum(1 for m in data if m['finished'])
    unfinished_total = sum(1 for m in data if not m['finished'])

    # === 顶部状态栏 ===
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("🏟️ 总场次", f"{len(data)} 场")
    with c2:
        st.metric("✅ 已赛", f"{finished_total} 场")
    with c3:
        st.metric("⏳ 未赛", f"{unfinished_total} 场")
    with c4:
        groups_with_matches = len(set(m['group'] for m in data))
        st.metric("🅰️ 小组", f"{groups_with_matches}/12")

    st.divider()

    # === 按 group 渲染 ===
    from collections import defaultdict
    by_group = defaultdict(list)
    for m in data:
        by_group[m['group']].append(m)

    for grp in 'ABCDEFGHIJKL':
        if grp in by_group:
            render_group_section(grp, by_group[grp])

    # === 底部说明 ===
    st.markdown("#### 📐 看板字段解读")
    st.markdown("""
| 字段 | 含义 |
|---|---|
| `主胜概率` | 市场对主队获胜的隐含概率(去 vig 后, 多家公司均值) |
| `分歧度` | 各家公司主胜概率的标准差 — **越大说明市场越分歧, 比赛悬念越大** |
| `✅ 已赛` | 来自 Wikipedia, 含最终比分 |
| `⏳ 未赛` | 来自 The Odds API, 含市场赔率(剔除跑偏公司) |

**国旗**: 🇲🇽 墨西哥 / 🇧🇷 巴西 / 🇩🇪 德国 ... 以 ISO 3166-1 为准

**局限**: Wikipedia 小组页面只有月份没有具体日期, 已赛比赛日期为 "TBD"。未赛比赛有精确时间 (北京时间)。
""")


if __name__ == "__main__":
    main()