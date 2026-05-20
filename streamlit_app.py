"""Streamlit Cloud 入口 — 委托到 dashboard/app.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# 直接执行 dashboard/app.py
with open(ROOT / "dashboard" / "app.py") as f:
    exec(f.read())
