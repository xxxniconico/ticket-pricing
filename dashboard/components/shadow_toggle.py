
# 影子模式开关 — 添加到 tab_next_match.py 的 sidebar
import streamlit as st

def render_shadow_toggle():
    """影子模式开关：切换静态/动态对手分级"""
    if "use_dynamic_tier" not in st.session_state:
        st.session_state.use_dynamic_tier = False
    
    st.sidebar.divider()
    st.sidebar.subheader("🔬 影子模式")
    use_dynamic = st.sidebar.toggle(
        "启用动态对手分级",
        value=st.session_state.use_dynamic_tier,
        help="开启后使用 ELO+ST+AP 动态评分替代静态 S/A/B/C 分级"
    )
    st.session_state.use_dynamic_tier = use_dynamic
    
    if use_dynamic:
        st.sidebar.caption("✅ 动态评级生效中")
    else:
        st.sidebar.caption("📋 使用静态分级")
    
    return use_dynamic
