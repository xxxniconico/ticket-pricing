"""Tab: 积分榜。"""
import streamlit as st

from dashboard.common.brand import team_crest_html
from dashboard.common.data_cache import _round_num

def render_standings_table(guoan_matches, standings, guoan_ded):
    """渲染国安赛季全览 — 每轮赛果+累计积分+排名变化（同步 V7 右栏）"""
    completed_2026 = sum(1 for m in guoan_matches if m.get("completed") and m["date"].startswith("2026"))
    pct = completed_2026 / 30 * 100
    st.markdown(f"""<div class="progress-line">
      <div class="progress-label"><span>2026 赛季进度</span><span>{completed_2026}/30 轮</span></div>
      <div class="progress-track"><div class="progress-fill" style="width:{pct}%"></div></div>
    </div>""", unsafe_allow_html=True)
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
                f'<span class="result-{res}" style="width:20px;text-align:center">{res}</span>'
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


