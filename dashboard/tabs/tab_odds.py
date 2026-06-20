"""
V5.6 赔率信号 — 看板展示模块 (路径 3)

只读不写: 从 data/raw/odds/ 读最新一份 JSON, 计算隐含胜率, 展示未来场次赔率信号
不动 rule_engine — 路径 3 承诺: 仅展示, 等 8 月大场样本到 5+ 再回测

设计:
- 顶部: 拉取日期 + API 状态 + 解读说明
- 概览表: 全部 8 场未来赛事, 一行一场 (主队胜率 / 平局胜率 / 客队胜率 / 市场共识)
- 国安场卡片: 4 个 KPI + 公司明细表 (平铺, 不折叠)
- 解读: V2 信号规则, 大场高亮

作者: Hermes Agent
日期: 2026-06-20
"""
from __future__ import annotations
import json
import statistics
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

ODDS_DIR = Path("/home/xxxsuli/ticket-pricing/data/raw/odds")

# 球队英文名 -> 中文名(对接 CSL 联赛)
TEAM_MAP = {
    "Beijing FC": "北京国安",
    "Beijing Guoan FC": "北京国安",
    "Wuhan Three Towns": "武汉三镇",
    "Shanghai Shenhua FC": "上海申花",
    "Shanghai SIPG FC": "上海海港",
    "Shanghai Port FC": "上海海港",
    "Shandong Luneng Taishan FC": "山东泰山",
    "Chengdu Rongcheng FC": "成都蓉城",
    "Tianjin Jinmen Tiger FC": "天津津门虎",
    "Zhejiang FC": "浙江",
    "Zhejiang Professional FC": "浙江",
    "Henan FC": "河南",
    "Dalian Yingbo": "大连英博海发",
    "Qingdao Hainiu FC": "青岛海牛",
    "Qingdao West Coast FC": "青岛西海岸",
    "Yunnan Yukun": "云南玉昆",
    "Meizhou Hakka FC": "梅州客家",
    "Changchun Yatai FC": "长春亚泰",
    "Shenzhen Peng City FC": "深圳新鹏城",
    "Chongqing Tonglianglong FC": "重庆铜梁龙",
    "Liaoning Tieren FC": "辽宁铁人",
}

# 中文名 -> 对手分级 (用于 V2 信号判断)
TIER_MAP = {
    "上海申花": "S", "山东泰山": "S", "上海海港": "S", "成都蓉城": "S",
    "北京国安": "S",
    "武汉三镇": "B", "浙江": "B", "河南": "B", "天津津门虎": "B",
    "长春亚泰": "B", "深圳新鹏城": "B", "云南玉昆": "B", "梅州客家": "B",
    "青岛西海岸": "B",
    "大连英博海发": "C", "青岛海牛": "C", "重庆铜梁龙": "C", "辽宁铁人": "C",
}


def _latest_odds_file() -> Path | None:
    if not ODDS_DIR.exists():
        return None
    files = sorted(ODDS_DIR.glob("csl_odds_*.json"))
    return files[-1] if files else None


@st.cache_data(ttl=300)
def _load_latest_odds():
    f = _latest_odds_file()
    if f is None:
        return None, None
    data = json.loads(f.read_text())
    return data, f.name


def _compute_implied_probs(match: dict) -> list[dict]:
    """对每家博彩公司算去 vig 的隐含 p_home/p_draw/p_away"""
    rows = []
    for bm in match.get("bookmakers", []):
        outcomes = bm["markets"][0].get("outcomes", [])
        odds_h = odds_d = odds_a = None
        for o in outcomes:
            if o["name"] == match["home_team"]:
                odds_h = o["price"]
            elif o["name"] == match["away_team"]:
                odds_a = o["price"]
            elif o["name"] == "Draw":
                odds_d = o["price"]
        if not (odds_h and odds_d and odds_a):
            continue
        raw_sum = 1/odds_h + 1/odds_d + 1/odds_a
        p_h = (1/odds_h) / raw_sum
        p_d = (1/odds_d) / raw_sum
        p_a = (1/odds_a) / raw_sum
        rows.append({
            "博彩公司": bm["key"],
            "主胜赔率": odds_h,
            "平局赔率": odds_d,
            "客胜赔率": odds_a,
            "p_主胜": p_h,
            "p_平局": p_d,
            "p_客胜": p_a,
            "Vig": raw_sum - 1,
        })
    return rows


def _signal_recommendation(p_home_mean: float, tier: str | None) -> dict:
    """V2 设计: 仅在 big match 或极端赔率时推荐加价"""
    is_big = tier in ("S", "A")
    if is_big:
        if p_home_mean >= 0.55:
            return {"signal": 1.05, "reason": f"大场 + 市场看好 (p_home≥0.55)"}
        if p_home_mean <= 0.35:
            return {"signal": 0.92, "reason": f"大场 + 市场看低 (p_home≤0.35)"}
    if p_home_mean >= 0.65:
        return {"signal": 1.03, "reason": f"极端看好 (p_home≥0.65)"}
    if p_home_mean <= 0.30:
        return {"signal": 0.95, "reason": f"极端看低 (p_home≤0.30)"}
    return {"signal": 1.00, "reason": "中性 — 不触发赔率乘数"}


def _format_v2_rule() -> str:
    return """**V2 信号规则** (路径 3 实验性, 不进 rule_engine):

| 条件 | 建议乘数 | 解读 |
|---|---|---|
| 大场(S/A级) + p_home ≥ 0.55 | 🟢 1.05 | 市场看好 → +5% |
| 大场(S/A级) + p_home ≤ 0.35 | 🔴 0.92 | 市场看低 → -8% |
| 任意场次 + p_home ≥ 0.65 | 🟢 1.03 | 极端看好 → +3% |
| 任意场次 + p_home ≤ 0.30 | 🔴 0.95 | 极端看低 → -5% |
| 其他 | ⚪ 1.00 | 不触发 |

**铁律**: 仅展示, 不进 rule_engine. 等 8 月大场样本到 5+ 场再做回测."""


def render_odds_tab():
    """V5.6 赔率看板主入口"""
    st.markdown("### 🎲 赔率信号 — V5.6 实验性展示")

    data, fname = _load_latest_odds()
    if data is None:
        st.warning(
            f"未找到赔率数据。请先跑 `bash scripts/fetch_csl_odds.sh`"
        )
        return

    pull_time = datetime.strptime(fname.replace("csl_odds_", "").replace(".json", ""), "%Y%m%d")
    n_matches = len(data)

    # ---- 顶部状态栏 ----
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("📅 数据拉取日", pull_time.strftime("%Y-%m-%d"))
    with c2:
        st.metric("⚽ 未来场次", f"{n_matches} 场")
    with c3:
        next_guoan = [m for m in data
                      if TEAM_MAP.get(m.get("home_team","")) == "北京国安"
                      or TEAM_MAP.get(m.get("away_team","")) == "北京国安"]
        if next_guoan:
            nm = min(next_guoan, key=lambda x: x["commence_time"])
            home_cn = TEAM_MAP.get(nm["home_team"], nm["home_team"])
            away_cn = TEAM_MAP.get(nm["away_team"], nm["away_team"])
            st.metric("🏟️ 下一场国安", f"{nm['commence_time'][:10]}")
            st.caption(f"{home_cn} vs {away_cn}")
        else:
            st.metric("🏟️ 下一场国安", "本快照无")
            st.caption("需等周一重新拉取")

    st.divider()

    # ---- 全部 8 场概览 ----
    st.markdown("#### 📊 全部未来场次 — 市场共识概览")
    overview_rows = []
    for m in sorted(data, key=lambda x: x["commence_time"]):
        rows = _compute_implied_probs(m)
        home_cn = TEAM_MAP.get(m["home_team"], m["home_team"])
        away_cn = TEAM_MAP.get(m["away_team"], m["away_team"])
        if not rows:
            overview_rows.append({
                "日期": m["commence_time"][:10],
                "主队": home_cn, "客队": away_cn,
                "p_主胜": None, "p_平局": None, "p_客胜": None,
                "博彩公司": 0,
                "国安相关": "⭐" if (home_cn == "北京国安" or away_cn == "北京国安") else "",
            })
            continue
        df_m = pd.DataFrame(rows)
        overview_rows.append({
            "日期": m["commence_time"][:10],
            "主队": home_cn, "客队": away_cn,
            "p_主胜": df_m["p_主胜"].mean(),
            "p_平局": df_m["p_平局"].mean(),
            "p_客胜": df_m["p_客胜"].mean(),
            "博彩公司": len(df_m),
            "国安相关": "⭐" if (home_cn == "北京国安" or away_cn == "北京国安") else "",
        })
    overview_df = pd.DataFrame(overview_rows)

    # 高亮国安场(用 Styler) - 新版 pandas 用 map 替代 apply
    def highlight_guoan_row(row):
        if row.get("国安相关") == "⭐":
            return ["background-color: #00A86B22"] * len(row)
        return [""] * len(row)

    def highlight_guoan_cell(val):
        if val == "⭐":
            return "background-color: #00A86B22"
        return ""

    st.dataframe(
        overview_df.style
        .format({
            "p_主胜": "{:.1%}",
            "p_平局": "{:.1%}",
            "p_客胜": "{:.1%}",
        }, na_rep="-")
        .map(highlight_guoan_cell),
        hide_index=True,
        width="stretch",
    )

    st.caption("⭐ = 国安相关场次 (主或客). 颜色: 浅绿底. p_主胜 + p_平局 + p_客胜 = 100% (去 vig 后).")

    st.divider()

    # ---- 国安场逐场详情 (平铺, 无折叠) ----
    st.markdown("#### 🏟️ 国安场详情 — 公司明细")

    guoan_matches = []
    for m in data:
        home_cn = TEAM_MAP.get(m["home_team"])
        away_cn = TEAM_MAP.get(m["away_team"])
        if home_cn == "北京国安":
            guoan_matches.append({**m, "home_cn": "北京国安", "away_cn": away_cn, "is_home_guoan": True})
        elif away_cn == "北京国安":
            guoan_matches.append({**m, "home_cn": home_cn, "away_cn": "北京国安", "is_home_guoan": False})

    if not guoan_matches:
        st.info("当前赔率快照中没有国安场次。")
    else:
        for idx, m in enumerate(sorted(guoan_matches, key=lambda x: x["commence_time"])):
            if idx > 0:
                st.markdown("---")  # 场次间分隔线 (用 markdown 而非 divider,避免高度问题)
            _render_match_detail(m)

    st.divider()

    # ---- V2 规则说明 (平铺, 不用 expander) ----
    st.markdown("#### 📐 V2 信号规则 (实验性)")
    st.markdown(_format_v2_rule())

    st.caption("V5.6 路径 3: 仅展示, 不进 rule_engine. 等 8 月大场样本到 5+ 场再决定.")


def _render_match_detail(m: dict):
    """单场比赛赔率信号详情 - 平铺显示"""
    home_cn = m["home_cn"]
    away_cn = m["away_cn"]
    is_home = m["is_home_guoan"]
    opponent_cn = away_cn if is_home else home_cn
    opponent_tier = TIER_MAP.get(opponent_cn, "?")

    rows = _compute_implied_probs(m)
    if not rows:
        st.warning(f"{m['commence_time'][:10]} | {home_cn} vs {away_cn}: 赔率数据缺失")
        return

    df = pd.DataFrame(rows).sort_values("p_主胜", ascending=False).reset_index(drop=True)
    p_home_mean = float(df["p_主胜"].mean())
    p_home_median = float(df["p_主胜"].median())
    p_home_min = float(df["p_主胜"].min())
    p_home_max = float(df["p_主胜"].max())
    vig_mean = float(df["Vig"].mean())
    rec = _signal_recommendation(p_home_mean, opponent_tier)

    # ---- 比赛标题 ----
    tier_badge = ""
    if opponent_tier == "S":
        tier_badge = " 🔥 **S 级大场**"
    elif opponent_tier == "A":
        tier_badge = " (A 级)"
    home_away_badge = "🏠 主场" if is_home else "✈️ 客场"
    title = f"{home_away_badge} {m['commence_time'][:10]} | **{home_cn}** vs **{away_cn}**{tier_badge}"
    st.markdown(f"##### {title}")

    # ---- 4 个 KPI ----
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("博彩公司数", len(df))
    with c2:
        st.metric("p_主胜 均值", f"{p_home_mean:.1%}")
    with c3:
        st.metric("p_主胜 中位", f"{p_home_median:.1%}")
    with c4:
        st.metric("p_主胜 区间", f"{p_home_min:.1%} ~ {p_home_max:.1%}")
    with c5:
        signal_color = "🟢" if rec["signal"] > 1.0 else "🔴" if rec["signal"] < 1.0 else "⚪"
        st.metric(
            "建议乘数",
            f"{signal_color} {rec['signal']:.3f}",
            help=rec["reason"],
        )

    # 触发原因 + 平均 vig
    st.caption(f"📝 {rec['reason']} · 平均 Vig={vig_mean:.2%} (Vig = 博彩公司利润, 越低越好)")

    # ---- 公司明细表 (平铺, 不折叠) ----
    st.markdown("**公司明细** (按 p_主胜 降序):")
    st.dataframe(
        df.style.format({
            "主胜赔率": "{:.2f}",
            "平局赔率": "{:.2f}",
            "客胜赔率": "{:.2f}",
            "p_主胜": "{:.1%}",
            "p_平局": "{:.1%}",
            "p_客胜": "{:.1%}",
            "Vig": "{:.2%}",
        }),
        hide_index=True,
        width="stretch",
    )

    # ---- 补充解读 ----
    if is_home and opponent_tier == "S":
        st.info("💡 这是大场,S 级对手。等历史样本到 5+ 场再固化系数。")
    elif not is_home:
        st.caption("客场场次: 赔率信号对主场定价无直接影响(本模型仅主场动态定价)")