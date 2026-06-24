
# === 动态评级集成 ===
# 在 app_v8.py 顶部添加:
from dashboard.tabs.tab_team_ratings import render_team_ratings
from dashboard.tabs.tab_guoan_monitor import render_guoan_monitor
from dashboard.components.shadow_toggle import render_shadow_toggle

# 在 main() 中, Tab 定义处改为:
use_dynamic = render_shadow_toggle()

tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9 = st.tabs([
    "📅 下一场", "📊 历史", "📈 积分榜", "🎯 H2策略",
    "🔥 热力图", "✅ 验证", "🎲 赔率",
    "📊 球队评级", "📈 国安监控"
])

# 在对应位置:
with tab8:
    render_team_ratings(all_matches, standings, use_dynamic)

with tab9:
    render_guoan_monitor(all_matches, standings)

# 在 tab1 (下一场) 中, 根据 use_dynamic 切换 tier:
if use_dynamic:
    from src.opponent_rating import get_opponent_scorecard, load_elo_history
    elo = load_elo_history()
    card = get_opponent_scorecard(opponent, match_date, elo_history=elo,
                                   standings_by_round=standings, matches=all_matches)
    opponent_tier_override = card["tier"]
else:
    opponent_tier_override = None
