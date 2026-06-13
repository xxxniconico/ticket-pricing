"""队徽 / 品牌资产 HTML。"""
import base64 as _b64
from pathlib import Path

# ── Team Logo Helpers ─────────────────────────────────────
import base64 as _b64
_ASSETS = Path(__file__).resolve().parent.parent / "assets"
_TEAM_LOGOS_DIR = _ASSETS / "team_logos"

# 对手名 → logo 文件名（来自 guoan-dashboard-2026 VI 资产）
TEAM_LOGO_MAP = {
    "上海海港": "a26d9fbb0342e6d54677.png",
    "上海申花": "91469528aeb15c37728e.png",
    "云南玉昆": "e3797059ba59e4acc812.png",
    "北京国安": "fa6ea93628b5de170048.png",
    "大连英博": "f0a1a59f36d308bf4ec8.png",
    "大连英博海发": "f0a1a59f36d308bf4ec8.png",
    "天津津门虎": "ae9884f476371aa26455.png",
    "山东泰山": "41181c23e64739adc012.png",
    "成都蓉城": "a6fb6193c5ad4eaa4945.png",
    "武汉三镇": "2096512a047b9b2844a9.png",
    "河南": "55b135463002a23b35a2.png",
    "浙江": "44ff3b38e0ba2dbd39c2.png",
    "浙江队": "44ff3b38e0ba2dbd39c2.png",
    "浙江俱乐部绿城": "44ff3b38e0ba2dbd39c2.png",
    "深圳新鹏城": "c1a9b19592adae833a30.png",
    "辽宁铁人": "fd56a67c37153dbcac8f.png",
    "重庆铜梁龙": "6a1a42ad7079e24257fa.png",
    "青岛海牛": "c98835007d3801568650.png",
    "青岛西海岸": "6e61285455bb3980745d.png",
    "梅州客家": "41181c23e64739adc012.png",  # fallback
    "沧州雄狮": "c1a9b19592adae833a30.png",  # fallback
    "南通支云": "2096512a047b9b2844a9.png",   # fallback
    "长春亚泰": "ae9884f476371aa26455.png",   # fallback
}
_GUOAN_CREST_B64 = None
_CSL_LOGO_B64 = None
_LOGO_CACHE = {}

def _logo_b64(filename: str) -> str:
    """返回 PNG 文件的 base64 data URI，带缓存。"""
    if filename in _LOGO_CACHE:
        return _LOGO_CACHE[filename]
    path = _TEAM_LOGOS_DIR / filename
    if path.exists():
        with open(path, "rb") as f:
            _LOGO_CACHE[filename] = f"data:image/png;base64,{_b64.b64encode(f.read()).decode()}"
    else:
        _LOGO_CACHE[filename] = ""
    return _LOGO_CACHE[filename]

def team_crest_html(opponent: str, size: str = "sm") -> str:
    """返回对手队徽 <img> 标签，未匹配返回空字符串。size: 'sm'=18px, 'lg'=28px."""
    fname = TEAM_LOGO_MAP.get(opponent)
    if not fname:
        return ""
    b64 = _logo_b64(fname)
    if not b64:
        return ""
    cls = "team-crest-lg" if size == "lg" else "team-crest"
    return f'<img class="{cls}" src="{b64}" alt="{opponent}">'

def guoan_crest_b64() -> str:
    """国安队徽 base64，带缓存。"""
    global _GUOAN_CREST_B64
    if _GUOAN_CREST_B64 is None:
        path = _ASSETS / "guoan_crest.png"
        if path.exists():
            with open(path, "rb") as f:
                _GUOAN_CREST_B64 = f"data:image/png;base64,{_b64.b64encode(f.read()).decode()}"
        else:
            _GUOAN_CREST_B64 = ""
    return _GUOAN_CREST_B64

def csl_logo_b64() -> str:
    """CSL logo base64，带缓存。"""
    global _CSL_LOGO_B64
    if _CSL_LOGO_B64 is None:
        path = _ASSETS / "csl_logo_white.png"
        if path.exists():
            with open(path, "rb") as f:
                _CSL_LOGO_B64 = f"data:image/png;base64,{_b64.b64encode(f.read()).decode()}"
        else:
            _CSL_LOGO_B64 = ""
    return _CSL_LOGO_B64
