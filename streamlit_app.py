"""Streamlit Cloud 入口"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Import and run the dashboard module
import dashboard.app
