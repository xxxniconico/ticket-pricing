"""Streamlit 页面初始化与 matplotlib 中文字体。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

"""
国安票务动态定价看板 V8 — 决策工作台
Linear暗色风格 · Tab分区 · What-If沙盒 · 不确定性可视化
"""
import sys, json, math
from pathlib import Path
from datetime import datetime
from collections import defaultdict
# Ensure ticket-pricing root is on path for 'dashboard' package imports
sys.path.insert(0, str(ROOT))
import pandas as pd, numpy as np
import streamlit as st
import streamlit.components.v1 as components
from dashboard.seating_heatmap import norm_section_id, show_heatmap_in_streamlit
from dashboard.components.ctx_builder import build_pred_args, build_rule_labels, ctx_kwargs
import matplotlib, matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# 注册中文字体：按优先级搜索已知路径
_CN_FONT_NAME = None
for _fp in [
    Path.home() / '.fonts' / 'simhei.ttf',
    Path.home() / '.fonts' / 'msyh.ttc',
    '/mnt/c/Windows/Fonts/simhei.ttf',
    '/mnt/c/Windows/Fonts/msyh.ttc',
    '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
    '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc',
]:
    if Path(_fp).exists():
        fm.fontManager.addfont(str(_fp))
        _CN_FONT_NAME = fm.FontProperties(fname=str(_fp)).get_name()
        break

if _CN_FONT_NAME is None:
    # 尝试已安装的系统字体
    for _name in ['WenQuanYi Micro Hei', 'WenQuanYi Zen Hei', 'Noto Sans CJK SC',
                   'SimHei', 'Microsoft YaHei', 'Noto Sans SC']:
        if any(_name.lower() in str(f).lower() for f in fm.fontManager.ttflist):
            _CN_FONT_NAME = _name
            break

if _CN_FONT_NAME:
    matplotlib.rcParams["font.sans-serif"] = [_CN_FONT_NAME, "DejaVu Sans"]
    # 强制重建字体缓存
    fm._load_fontmanager(try_read_cache=False)
else:
    matplotlib.rcParams["font.sans-serif"] = ["DejaVu Sans"]

matplotlib.rcParams["axes.unicode_minus"] = False

ROOT = ROOT
sys.path.insert(0, str(ROOT))

from src.rule_engine import predict_calibrated as rule_predict, TIER_BASE, MULTIPLIERS, PENALTY_FLOOR, get_calibration, get_effective_calibration, update as rule_update
from src.dynamic_optimizer import DynamicPricingOptimizer
from src.pricing_v5 import ZONE_TIERS, ZONE_SECTIONS, get_pricing_tier, build_price_matrix, build_elasticity_matrix, get_zone_bounds, get_zone_sections
from src.classify import classify_opponent_tier, DERBY_RIVALS
from src.csl_context import load_csl_data, get_guoan_matches, detect_ctx

st.set_page_config(page_title="国安票务 V8", page_icon="⚽", layout="wide")

# 防白屏闪烁: Streamlit 加载 dark CSS 前抢先设黑底
st.markdown("""
<style>
  @media (prefers-color-scheme: dark) {
    body, .stApp, .main { background-color: #0c0d0f !important; }
  }
  .stApp { background-color: #0c0d0f; }
</style>
""", unsafe_allow_html=True)
