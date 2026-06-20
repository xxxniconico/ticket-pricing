"""
FIFA 世界杯赔率 + 战绩看板 V1
==========================

独立 Streamlit app, 端口 8507
- 拉取 The Odds API 世界杯单场赔率
- (可选) 后续接入比分 API 显示实时战况
- 与 V5.6 中超赔率 tab 形成国际赛事补充

作者: Hermes Agent
日期: 2026-06-20
"""
from __future__ import annotations
import json
import statistics
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
import sys

# === 路径 ===
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WC_ODDS_DIR = ROOT / "data" / "raw" / "odds"

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
  <h2 style="color: white; margin: 0;">🌍 世界杯赔率看板 · FIFA World Cup 2026</h2>
  <p style="color: #cbd5e1; margin: 4px 0 0 0;">
    单场赔率 + 市场分歧度 + 关键比赛详情 · 数据源 The Odds API · 仅展示, 不进定价模型
  </p>
</div>
""", unsafe_allow_html=True)


def _latest_wc_file() -> Path | None:
    if not WC_ODDS_DIR.exists():
        return None
    files = sorted(WC_ODDS_DIR.glob("fifa_wc_*.json"))
    return files[-1] if files else None


@st.cache_data(ttl=300)
def _load_wc_data():
    f = _latest_wc_file()
    if f is None:
        return None, None
    return json.loads(f.read_text()), f.name


def _match_metrics(m: dict) -> dict:
    """计算比赛的隐含胜率均值/分歧度/赔率均值"""
    rows = []
    for bm in m.get("bookmakers", []):
        outcomes = bm["markets"][0].get("outcomes", [])
        odds_h = odds_d = odds_a = None
        for o in outcomes:
            if o["name"] == m["home_team"]:
                odds_h = o["price"]
            elif o["name"] == m["away_team"]:
                odds_a = o["price"]
            elif o["name"] == "Draw":
                odds_d = o["price"]
        if not (odds_h and odds_d and odds_a):
            continue
        raw = 1/odds_h + 1/odds_d + 1/odds_a
        rows.append({
            "book": bm["key"],
            "h": odds_h, "d": odds_d, "a": odds_a,
            "p_h": (1/odds_h)/raw,
            "p_d": (1/odds_d)/raw,
            "p_a": (1/odds_a)/raw,
            "vig": raw - 1,
        })
    if not rows:
        return {}
    p_h_list = [r["p_h"] for r in rows]
    # 剔除明显跑偏的(>3σ from median)
    if len(p_h_list) >= 5:
        med = statistics.median(p_h_list)
        mad = statistics.median([abs(p - med) for p in p_h_list]) or 0.001
        filtered = [r for r, p in zip(rows, p_h_list) if abs(p - med) < 3 * mad]
        if len(filtered) >= 5:
            rows = filtered
            p_h_list = [r["p_h"] for r in rows]
    return {
        "n_bookmakers": len(rows),
        "avg_h": statistics.mean(r["h"] for r in rows),
        "avg_d": statistics.mean(r["d"] for r in rows),
        "avg_a": statistics.mean(r["a"] for r in rows),
        "p_h_mean": statistics.mean(p_h_list),
        "p_h_std": statistics.stdev(p_h_list) if len(p_h_list) > 1 else 0,
        "p_h_min": min(p_h_list),
        "p_h_max": max(p_h_list),
        "avg_vig": statistics.mean(r["vig"] for r in rows),
        "rows": rows,
    }


def render_overview(matches: list, metrics: dict):
    """总览: 全部比赛按日期排序, 显示市场共识"""
    st.markdown("#### 📊 全部 40 场比赛 — 市场共识总览")
    rows = []
    for m in matches:
        m_data = metrics.get(m.get("id", m["home_team"]+m["away_team"]+m["commence_time"]), {})
        utc_dt = datetime.fromisoformat(m["commence_time"].replace("Z", ""))
        bj_dt = utc_dt + timedelta(hours=8)
        # 算 p_平局 和 p_客胜(从赔率均值反推)
        if m_data.get("avg_h") and m_data.get("avg_d") and m_data.get("avg_a"):
            raw = 1/m_data["avg_h"] + 1/m_data["avg_d"] + 1/m_data["avg_a"]
            p_d = (1/m_data["avg_d"]) / raw
            p_a = (1/m_data["avg_a"]) / raw
        else:
            p_d = p_a = None
        rows.append({
            "北京日期": bj_dt.strftime("%m-%d %H:%M"),
            "主队": m["home_team"],
            "客队": m["away_team"],
            "p_主胜": m_data.get("p_h_mean"),
            "p_平局": p_d,
            "p_客胜": p_a,
            "主胜赔率": m_data.get("avg_h"),
            "平局赔率": m_data.get("avg_d"),
            "客胜赔率": m_data.get("avg_a"),
            "分歧度": m_data.get("p_h_std"),
            "公司数": m_data.get("n_bookmakers"),
        })
    df = pd.DataFrame(rows)
    df_sorted = df.sort_values("北京日期")

    # 高亮分歧度高的(悬念大的)比赛
    if df_sorted["分歧度"].notna().any():
        threshold = df_sorted["分歧度"].quantile(0.75)
    else:
        threshold = 0

    def highlight_cell(val):
        if not val or pd.isna(val):
            return ""
        if val >= threshold:
            return "background-color: #fbbf2422"
        return ""

    st.dataframe(
        df_sorted.style
        .format({
            "p_主胜": "{:.1%}", "p_平局": "{:.1%}", "p_客胜": "{:.1%}",
            "主胜赔率": "{:.2f}", "平局赔率": "{:.2f}", "客胜赔率": "{:.2f}",
            "分歧度": "{:.3f}",
        }, na_rep="-")
        .map(highlight_cell, subset=["分歧度"]),
        hide_index=True,
        width="stretch",
    )
    st.caption(f"🟡 高亮: 分歧度 ≥ 第 75 百分位 (≥{threshold:.3f}) 的比赛 — 悬念大, 关注度高")
    return df_sorted


def render_strong_matches(matches: list, metrics: dict):
    """强队出场场次"""
    TIER1 = {"Brazil", "Argentina", "France", "England", "Germany", "Spain",
             "Netherlands", "Portugal", "Italy", "Belgium", "Uruguay"}
    strong = [m for m in matches if m["home_team"] in TIER1 or m["away_team"] in TIER1]
    strong.sort(key=lambda x: x["commence_time"])

    st.markdown(f"#### 🔥 强队出场 ({len(strong)} 场)")

    for m in strong:
        key = m.get("id", m["home_team"]+m["away_team"]+m["commence_time"])
        m_data = metrics.get(key, {})
        if not m_data:
            continue
        utc_dt = datetime.fromisoformat(m["commence_time"].replace("Z", ""))
        bj_dt = utc_dt + timedelta(hours=8)
        is_tier1_home = m["home_team"] in TIER1
        is_tier1_away = m["away_team"] in TIER1
        team1_badge = "🔥" if is_tier1_home else ""
        team2_badge = "🔥" if is_tier1_away else ""

        st.markdown(f"##### {bj_dt.strftime('%m-%d %H:%M')} 北京 | "
                    f"{team1_badge} **{m['home_team']}** vs "
                    f"{team2_badge} **{m['away_team']}**")

        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            st.metric("p_主胜", f"{m_data.get('p_h_mean', 0):.1%}")
        with c2:
            st.metric("主胜赔率", f"{m_data.get('avg_h', 0):.2f}")
        with c3:
            st.metric("平局赔率", f"{m_data.get('avg_d', 0):.2f}")
        with c4:
            st.metric("客胜赔率", f"{m_data.get('avg_a', 0):.2f}")
        with c5:
            std = m_data.get("p_h_std", 0)
            level = "🔴 高" if std > 0.05 else ("🟡 中" if std > 0.02 else "🟢 低")
            st.metric("分歧度", f"{std:.3f} {level}")

        # 公司明细(平铺,不折叠)
        rows = m_data.get("rows", [])
        if rows:
            df_bm = pd.DataFrame(rows).sort_values("p_h", ascending=False)
            st.dataframe(
                df_bm.style.format({
                    "h": "{:.2f}", "d": "{:.2f}", "a": "{:.2f}",
                    "p_h": "{:.1%}", "vig": "{:.2%}",
                }),
                hide_index=True,
                width="stretch",
            )
        st.markdown("---")


def main():
    data, fname = _load_wc_data()
    if data is None:
        st.warning("⚠️ 未找到世界杯赔率数据。请运行:")
        st.code("curl -s 'https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/odds/?regions=eu&markets=h2h&oddsFormat=decimal&apiKey=YOUR_KEY' > data/raw/odds/fifa_wc_YYYYMMDD.json")
        return

    pull_date = fname.replace("fifa_wc_", "").replace(".json", "")
    pull_dt = datetime.strptime(pull_date, "%Y%m%d")

    # === 顶部状态栏 ===
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("📅 数据拉取日", pull_dt.strftime("%Y-%m-%d"))
    with c2:
        st.metric("⚽ 总场次", f"{len(data)} 场")
    with c3:
        # 今天(假设 UTC)开打的比赛
        today_utc = "2026-06-20"
        today_count = sum(1 for m in data if m["commence_time"].startswith(today_utc))
        st.metric("🏟️ 今日(UTC)开打", f"{today_count} 场")

    # 算所有比赛指标
    metrics = {}
    for m in data:
        key = m.get("id", m["home_team"]+m["away_team"]+m["commence_time"])
        metrics[key] = _match_metrics(m)

    st.divider()

    # === Tab 1: 全部总览 ===
    df_sorted = render_overview(data, metrics)
    st.divider()

    # === Tab 2: 强队出场详情 ===
    render_strong_matches(data, metrics)

    st.divider()

    # === 解读说明 ===
    st.markdown("#### 📐 看板字段解读")
    st.markdown("""
| 字段 | 含义 |
|---|---|
| `p_主胜` | 市场对主队获胜的隐含概率(去 vig 后, 多家公司均值) |
| `分歧度` (p_h std) | 各家公司对 p_主胜 的标准差 — **越大说明市场越分歧, 比赛悬念越大** |
| `Vig` | 博彩公司利润率 (越低越好, 0% = 无利润纯市场) |
| `公司数` | 提供赔率的博彩公司数量 (越多越准) |

**关注度信号**: 黄色高亮的比赛 = 分歧度 ≥ 第 75 百分位 = **市场最不确定 = 关注度最高**

**剔除跑偏**: 任何公司 p_主胜 偏离 median > 3×MAD 的会被剔除(防止异常值污染均值)

**局限**: 当前只能拿到 2026-06-20 之后的**未来**场次赔率, 已完赛比分需另外接 API(Football-Data.org / API-FOOTBALL 免费档)。
""")


if __name__ == "__main__":
    main()