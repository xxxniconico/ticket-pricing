"""
FIFA 世界杯赔率 + 战绩看板 V3
==========================

独立 Streamlit app, 端口 8507 (云端: ?app=fifa)
- **按日期排序为主** (然后按 group)
- **国旗放在国家名后面**: 墨西哥 🇲🇽 vs 南非 🇿🇦
- **每场比赛标注组别**: Group A / Group B
- 已赛 + 未赛 72 场全显示
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
    按日期排序 · 已赛 + 未赛 72 场 · 数据源 Wikipedia + The Odds API · 仅展示
  </p>
</div>
""", unsafe_allow_html=True)


@st.cache_data(ttl=300)
def _load_unified():
    if not UNIFIED_FILE.exists():
        return None
    return json.loads(UNIFIED_FILE.read_text())


def render_match_card(m, show_date_header=False):
    """单场比赛卡片 - 国旗放在国家名后面"""
    home_cn, home_flag = cn(m['home_en'])
    away_cn, away_flag = cn(m['away_en'])
    grp = m.get('group', '?')

    # 国旗放在国家名后面
    home_str = f"**{home_cn}** {home_flag}"
    away_str = f"**{away_cn}** {away_flag}"

    # 标题
    if m['finished']:
        # 已赛: 国家名 + 国旗 + 比分 + 国家名 + 国旗 + Group 标签
        st.markdown(
            f"#### ✅ {home_str} {m['score']} {away_str}  &nbsp;&nbsp; "
            f"<span style='background-color:#1f2937;color:#9ca3af;padding:2px 8px;border-radius:4px;font-size:0.7em;'>"
            f"Group {grp}</span>",
            unsafe_allow_html=True,
        )
    else:
        metrics = m.get('metrics', {})
        date_cn = m.get('date_cn', m.get('date', ''))
        st.markdown(
            f"#### ⏳ {date_cn} 北京 | {home_str} vs {away_str}  &nbsp;&nbsp; "
            f"<span style='background-color:#1f2937;color:#9ca3af;padding:2px 8px;border-radius:4px;font-size:0.7em;'>"
            f"Group {grp}</span>",
            unsafe_allow_html=True,
        )

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


def render_by_date(matches):
    """按日期排序主视图"""
    # 排序: 已赛按 (date, group), 未赛按 (commence_time, group)
    # 已赛日期统一是 "2026-06 (Wikipedia)", 用 group 当 secondary
    finished = [m for m in matches if m['finished']]
    unfinished = [m for m in matches if not m['finished']]

    # === 已赛区块 ===
    st.markdown("### ✅ 已赛 (按小组分组)")
    finished.sort(key=lambda x: (x['group'],))
    from collections import defaultdict
    by_group = defaultdict(list)
    for m in finished:
        by_group[m['group']].append(m)
    for grp in 'ABCDEFGHIJKL':
        if grp in by_group:
            st.markdown(f"**Group {grp}**")
            for m in by_group[grp]:
                render_match_card(m)

    st.divider()

    # === 未赛区块(按日期升序) ===
    st.markdown("### ⏳ 未赛 (按日期排序)")
    # 用 commence_time 排序,fallback 用 date
    def sort_key(m):
        return m.get('commence_time') or m.get('date') or '9999'
    unfinished.sort(key=sort_key)

    # 按日期分组显示,日期变化时显示日期标题
    current_date = None
    for m in unfinished:
        utc = m.get('commence_time', '')
        bj_date = utc[:10] if utc else m.get('date', '')
        if bj_date != current_date:
            current_date = bj_date
            # 把 "2026-06-25" 转成中文友好格式
            try:
                dt = datetime.strptime(bj_date, '%Y-%m-%d')
                weekday_cn = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][dt.weekday()]
                date_label = f"📅 {bj_date} {weekday_cn}"
            except Exception:
                date_label = f"📅 {bj_date}"
            st.markdown(f"#### {date_label}")

        render_match_card(m)


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
        groups_count = len(set(m['group'] for m in data))
        st.metric("🅰️ 小组", f"{groups_count}/12")

    st.divider()

    # === 主视图 ===
    render_by_date(data)

    # === 底部说明 ===
    st.divider()
    st.markdown("#### 📐 看板字段解读")
    st.markdown("""
| 字段 | 含义 |
|---|---|
| `主胜概率` | 市场对主队获胜的隐含概率(去 vig 后, 多家公司均值) |
| `分歧度` | 各家公司主胜概率的标准差 — **越大说明市场越分歧, 比赛悬念越大** |
| `✅ 已赛` | 来自 Wikipedia, 含最终比分 |
| `⏳ 未赛` | 来自 The Odds API, 含市场赔率(剔除跑偏公司) |
| `Group X` | 该场比赛所在的小组 |

**布局**: 已赛按小组分类 → 未赛按日期升序排列, 每场比赛后面附 Group 标签 + 国旗

**局限**: Wikipedia 小组页面只有月份没有具体日期, 已赛比赛日期标记为 "Wikipedia"。
""")


if __name__ == "__main__":
    main()