"""Streamlit Cloud 入口 — V8 看板"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import dashboard.app_v8
dashboard.app_v8.main()
