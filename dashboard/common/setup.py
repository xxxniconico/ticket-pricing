"""Streamlit 页面初始化：字体 + page_config + 暗色底。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import matplotlib
import matplotlib.font_manager as fm
import streamlit as st

# 注册中文字体：按优先级搜索已知路径
_CN_FONT_NAME = None
for _fp in [
    Path.home() / ".fonts" / "simhei.ttf",
    Path.home() / ".fonts" / "msyh.ttc",
    "/mnt/c/Windows/Fonts/simhei.ttf",
    "/mnt/c/Windows/Fonts/msyh.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
]:
    if Path(_fp).exists():
        fm.fontManager.addfont(str(_fp))
        _CN_FONT_NAME = fm.FontProperties(fname=str(_fp)).get_name()
        break

if _CN_FONT_NAME is None:
    for _name in [
        "WenQuanYi Micro Hei", "WenQuanYi Zen Hei", "Noto Sans CJK SC",
        "SimHei", "Microsoft YaHei", "Noto Sans SC",
    ]:
        if any(_name.lower() in str(f).lower() for f in fm.fontManager.ttflist):
            _CN_FONT_NAME = _name
            break

if _CN_FONT_NAME:
    matplotlib.rcParams["font.sans-serif"] = [_CN_FONT_NAME, "DejaVu Sans"]
    fm._load_fontmanager(try_read_cache=False)
else:
    matplotlib.rcParams["font.sans-serif"] = ["DejaVu Sans"]

matplotlib.rcParams["axes.unicode_minus"] = False

st.set_page_config(page_title="国安票务 V8", page_icon="⚽", layout="wide")

st.markdown("""
<style>
  @media (prefers-color-scheme: dark) {
    body, .stApp, .main { background-color: #0c0d0f !important; }
  }
  .stApp { background-color: #0c0d0f; }
</style>
""", unsafe_allow_html=True)
