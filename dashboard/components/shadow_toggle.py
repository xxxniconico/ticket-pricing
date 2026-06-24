"""Shadow mode toggle for dynamic tier system"""
import streamlit as st

def render_shadow_toggle():
    if "use_dynamic_tier" not in st.session_state:
        st.session_state.use_dynamic_tier = False

    col1, col2 = st.columns([1, 4])
    with col1:
        use_dynamic = st.checkbox(
            "Dynamic Rating",
            value=st.session_state.use_dynamic_tier,
            help="Enable ELO+ST+AP dynamic opponent tier"
        )
    with col2:
        if use_dynamic:
            st.caption("Dynamic rating ON - opponent tiers based on real-time ST/AP")
        else:
            st.caption("Static rating - using fixed S/A/B/C tiers")

    st.session_state.use_dynamic_tier = use_dynamic
    return use_dynamic
