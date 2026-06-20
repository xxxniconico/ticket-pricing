"""Streamlit Cloud 入口 — V8 看板（本地端口 8506: dashboard/serve.sh）

支持 query 参数切换:
- 默认: V8 看板 (https://...streamlit.app/)
- ?app=fifa: 世界杯赔率看板 (https://...streamlit.app/?app=fifa)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import streamlit as st

# === 路由: 根据 query param 决定加载哪个看板 ===
try:
    app_choice = st.query_params.get("app", "v8")
except Exception:
    app_choice = "v8"

if app_choice == "fifa":
    import dashboard.app_fifa_wc
    dashboard.app_fifa_wc.main()
else:
    import dashboard.app_v8
    dashboard.app_v8.main()
