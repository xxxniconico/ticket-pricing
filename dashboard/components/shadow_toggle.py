"""影子模式开关"
import streamlit as st

def render_shadow_toggle():
    """在主区域显示，确保可见"
    if "use_dynamic_tier" not in st.session_state:
        st.session_state.use_dynamic_tier = False
    
    col1, col2 = st.columns([1, 4])
    with col1:
        use_dynamic = st.checkbox(
            "🔬 动态评级",
            value=st.session_state.use_dynamic_tier,
            help="开启后使用 ELO+ST+AP 动态评分"
        )
    with col2:
        if use_dynamic:
            st.caption("✅ 动态评级生效 — 对手分级基于实时 ST/AP 计算")
        else:
            st.caption("📋 静态分级 — 使用传统 S/A/B/C 固定分级")
    
    st.session_state.use_dynamic_tier = use_dynamic
    return use_dynamic
