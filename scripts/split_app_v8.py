#!/usr/bin/env python3
"""将 dashboard/app_v8.py 拆分为 common / components / tabs 模块。"""
from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "dashboard" / "app_v8.py"
OUT_LOG = ROOT / "split_log.txt"

# (start_line, end_line) — 1-based inclusive
SLICES = {
    "dashboard/common/setup.py": (1, 73),
    "dashboard/common/constants.py": (75, 97),
    "dashboard/common/brand.py": (99, 179),
    "dashboard/common/data_cache.py": (180, 313),
    "dashboard/components/pricing_ui.py": (319, 776),
    "dashboard/tabs/tab_next_match.py": (777, 919),
    "dashboard/tabs/tab_history.py": (921, 1196),
    "dashboard/tabs/tab_opponent.py": (1198, 1315),
    "dashboard/components/waterfall.py": (1311, 2083),
    "dashboard/tabs/tab_h2_strategy.py": (2085, 2327),
    "dashboard/tabs/tab_standings.py": (2328, 2363),
    "dashboard/tabs/tab_heatmap.py": (2393, 2535),
    "dashboard/tabs/tab_validation.py": (2537, 2761),
}

MODULE_HEADERS = {
    "dashboard/common/setup.py": '''"""Streamlit 页面初始化与 matplotlib 中文字体。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

''',
    "dashboard/common/constants.py": '''"""看板常量。"""
from src.rule_engine import MULTIPLIERS

''',
    "dashboard/common/brand.py": '''"""队徽 / 品牌资产 HTML。"""
import base64 as _b64
from pathlib import Path

''',
    "dashboard/common/data_cache.py": '''"""数据缓存与预测计算。"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from dashboard.common.constants import DEDUCTIONS
from dashboard.components.ctx_builder import ctx_kwargs
from src.classify import DERBY_RIVALS
from src.csl_context import detect_ctx, get_guoan_matches, load_csl_data
from src.dynamic_optimizer import DynamicPricingOptimizer
from src.rule_engine import predict_calibrated as rule_predict

ROOT = Path(__file__).resolve().parent.parent.parent

''',
    "dashboard/components/pricing_ui.py": '''"""定价 UI 组件（策略卡 / 定价表 / What-If）。"""
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard.common.brand import team_crest_html
from dashboard.common.constants import PT_LABELS, TIER_COLORS, TIER_LABELS, WEEKDAYS, WHATIF_SCENARIOS
from dashboard.common.data_cache import get_optimizer
from dashboard.components.ctx_builder import build_rule_labels
from src.classify import DERBY_RIVALS, classify_opponent_tier
from src.pricing_v5 import ZONE_TIERS, get_pricing_tier

ROOT = Path(__file__).resolve().parent.parent.parent

''',
    "dashboard/tabs/tab_next_match.py": '''"""Tab: 下一场预测。"""
import pandas as pd
import streamlit as st

from dashboard.common.brand import team_crest_html
from dashboard.common.constants import PT_LABELS, TIER_COLORS, TIER_LABELS, WEEKDAYS
from dashboard.common.data_cache import get_optimizer
from dashboard.components.ctx_builder import build_pred_args
from dashboard.components.pricing_ui import (
    render_confidence_bar,
    render_cumulative_bar,
    render_pricing_confirm,
    render_pricing_table,
    render_recent_results,
    render_rule_pills,
    render_strategy_card,
    render_what_if,
)
from src.classify import DERBY_RIVALS, classify_opponent_tier
from src.csl_context import detect_ctx
from src.pricing_v5 import get_pricing_tier
from src.rule_engine import MULTIPLIERS, PENALTY_FLOOR, TIER_BASE, get_effective_calibration

''',
    "dashboard/tabs/tab_history.py": '''"""Tab: 历史定价。"""
import pandas as pd
import streamlit as st

from dashboard.common.brand import team_crest_html
from dashboard.common.constants import TIER_COLORS
from dashboard.common.data_cache import _get_zone_actual_revenue, get_optimizer
from dashboard.components.ctx_builder import build_pred_args
from dashboard.components.pricing_ui import render_pricing_table, render_strategy_card
from src.classify import classify_opponent_tier
from src.csl_context import detect_ctx
from src.pricing_v5 import get_pricing_tier

''',
    "dashboard/tabs/tab_opponent.py": '''"""Tab: 对手分析。"""
import pandas as pd
import streamlit as st

from dashboard.common.brand import team_crest_html
from dashboard.common.constants import TIER_COLORS
from src.classify import classify_opponent_tier
from src.csl_context import get_guoan_matches

''',
    "dashboard/components/waterfall.py": '''"""H1/H2 瀑布图计算与绘制。"""
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

from dashboard.common.data_cache import _get_csl_parquet, get_optimizer
from src.csl_context import detect_ctx

ROOT = Path(__file__).resolve().parent.parent.parent

''',
    "dashboard/tabs/tab_h2_strategy.py": '''"""Tab: H2 策略。"""
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard.common.brand import team_crest_html
from dashboard.common.constants import DEDUCTIONS
from dashboard.common.data_cache import get_optimizer
from dashboard.components.ctx_builder import build_pred_args
from dashboard.components.pricing_ui import render_strategy_card
from dashboard.components.waterfall import compute_h1_waterfall, compute_h2_waterfall, compute_waterfall_decomposition, draw_waterfall
from src.classify import DERBY_RIVALS, classify_opponent_tier
from src.csl_context import detect_ctx

ROOT = Path(__file__).resolve().parent.parent.parent

''',
    "dashboard/tabs/tab_standings.py": '''"""Tab: 积分榜。"""
import streamlit as st

from dashboard.common.data_cache import _round_num

''',
    "dashboard/tabs/tab_heatmap.py": '''"""Tab: 座位热力图。"""
import streamlit as st

from dashboard.seating_heatmap import show_heatmap_in_streamlit

''',
    "dashboard/tabs/tab_validation.py": '''"""Tab: 模型验证。"""
import pandas as pd
import streamlit as st

from dashboard.common.data_cache import _get_csl_parquet, get_optimizer
from src.classify import classify_opponent_tier

''',
}

NEW_APP = '''"""
国安票务动态定价看板 V8 — 决策工作台（模块化入口）
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dashboard.common import setup  # noqa: F401 — 副作用：page_config + 字体
from dashboard.common.brand import csl_logo_b64, guoan_crest_b64
from dashboard.common.constants import DEDUCTIONS
from dashboard.common.data_cache import (
    build_standings_2026,
    compute_home_predictions,
    load_css,
    load_data,
    set_ctx_rounds,
    _round_num,
)
from dashboard.components.ctx_builder import build_pred_args
from dashboard.common.data_cache import get_optimizer, _get_zone_actual_revenue
from dashboard.tabs.tab_next_match import render_tab1
from dashboard.tabs.tab_history import render_history_expanders, render_mae_chart
from dashboard.tabs.tab_opponent import render_opponent_analysis
from dashboard.tabs.tab_standings import render_standings_table
from dashboard.tabs.tab_h2_strategy import render_h2_strategy
from dashboard.tabs.tab_heatmap import render_heatmap_tab
from dashboard.tabs.tab_validation import render_validation_tab

import numpy as np
import pandas as pd
import streamlit as st
from src.pricing_v5 import ZONE_TIERS


def main():
    load_css()

    with st.spinner("加载 CSL 数据..."):
        all_matches, rounds, guoan_matches = load_data()
    if not guoan_matches:
        if not all_matches:
            st.error("无法加载 CSL 数据：数据文件缺失或网络不可用")
        else:
            st.error("国安赛程为空：2026 赛季尚未开赛或数据源未更新")
        st.error("请刷新重试")
        if st.button("🔄 刷新重试"):
            st.rerun()
        st.stop()

    set_ctx_rounds(rounds)
    standings = build_standings_2026(all_matches)

    home_matches = [m for m in guoan_matches if m.get("is_home")]
    home_done = [m for m in home_matches if m.get("completed")]
    completed = [m for m in guoan_matches if m.get("completed") and m["date"].startswith("2026")]

    total_pts = sum(
        3 if (m["is_home"] and m["hg"] > m["ag"]) or (not m["is_home"] and m["ag"] > m["hg"])
        else 1 if m["hg"] == m["ag"] else 0
        for m in completed
    )
    guoan_ded = DEDUCTIONS.get("北京国安", 0)
    latest_rnd = max(standings.keys(), key=_round_num, default=None)
    guoan_rank = standings.get(latest_rnd, {}).get("北京国安", "?") if latest_rnd else "?"
    home_w = sum(1 for m in home_done if m["hg"] > m["ag"])
    home_d = sum(1 for m in home_done if m["hg"] == m["ag"])
    home_l = sum(1 for m in home_done if m["hg"] < m["ag"])

    crest = guoan_crest_b64()
    csl = csl_logo_b64()
    crest_img = f\'<img class="crest" src="{crest}" alt="国安">\' if crest else ""
    csl_img = f\'<img class="csl-logo" src="{csl}" alt="CSL">\' if csl else ""
    st.markdown(f"""<div class="brand-header">
      <div style="display:flex;align-items:center;gap:10px">
        {crest_img}
        <h1>北京国安 · 动态定价</h1>
        {csl_img}
      </div>
      <div class="state-bar" style="margin-left:auto">
        <strong>#{guoan_rank}</strong> {total_pts}分
        <span style="color:#62666d">(扣{guoan_ded}分)</span>
        | 主场 {home_w}-{home_d}-{home_l}
        | 已赛{len(completed)}/30轮
      </div>
    </div>""", unsafe_allow_html=True)

    recent5 = completed[-5:]
    form_icons = []
    for m in recent5:
        res = "W" if (m["is_home"] and m["hg"] > m["ag"]) or (not m["is_home"] and m["ag"] > m["hg"]) else "D" if m["hg"] == m["ag"] else "L"
        form_icons.append(f\'<span class="result-{res}">{res}</span>\')
    if form_icons:
        st.caption("近5场: " + " · ".join(form_icons), unsafe_allow_html=True)

    enable_ema = st.toggle(
        "启用 EMA 校准（实验）",
        value=st.session_state.get("enable_ema_calibration", False),
        key="enable_ema_calibration",
        help="默认关闭。开启后仅当该级别 2026 已赛 ≥8 场才应用 EMA 因子，防止小样本恶化 MAE。",
    )

    home_preds = compute_home_predictions(home_done, guoan_matches, enable_ema=enable_ema)
    next_match = next((m for m in guoan_matches if not m["completed"] and m["date"].startswith("2026")), None)
    next_home = next((m for m in guoan_matches if not m["completed"] and m["is_home"] and m["date"].startswith("2026")), None)

    if next_match and next_match["is_home"]:
        target_match = next_match
    elif next_home:
        target_match = next_home
    else:
        target_match = None

    preds_arr = np.array([p for _, p, _, _ in home_preds])
    actuals_arr = np.array([a for _, _, a, _ in home_preds])
    mae = np.mean(np.abs(preds_arr - actuals_arr)) if len(preds_arr) > 0 else 0
    pct = len(home_preds) / 15 * 100
    st.markdown(f"""<div class="progress-line">
      <div class="progress-label"><span>赛季主场进度</span><span>{len(home_preds)}/15</span></div>
      <div class="progress-track"><div class="progress-fill" style="width:{pct}%"></div></div>
    </div>""", unsafe_allow_html=True)

    tab_names = ["🎯 下一场预测", "📋 历史定价", "🔍 对手分析", "🏆 积分榜", "📊 H2策略", "🔥 座位热力图", "📐 模型验证"]
    active_tab = st.radio("导航", tab_names, horizontal=True, label_visibility="collapsed", key="main_tab")

    if active_tab == tab_names[0]:
        if next_match and not next_match["is_home"]:
            st.info(f"📅 下一场 {next_match[\'date\']} @ {next_match[\'opponent\']} 为客场")
            if next_home:
                st.caption(f"最近主场：{next_home[\'date\']} vs {next_home[\'opponent\']}")
        if target_match:
            render_tab1(target_match, home_preds, guoan_matches, standings, mae)
        else:
            st.info("无未来主场")
        st.caption("💡 详细场景切换 + 瀑布图 → **H2策略** TAB")

    if active_tab == tab_names[1]:
        opt_kpi = get_optimizer()
        cum_scene_qty = cum_delta_qty = cum_scene_rev = cum_delta_rev = 0
        for m, pred, actual, ctx in home_preds:
            dt_m = pd.Timestamp(m["date"])
            is_first = (m == home_preds[0][0])
            pred_args = build_pred_args(m, ctx, {"season_opener": is_first, "summer": dt_m.month in [7, 8], "match_year": m["date"][:4]})
            r_h = opt_kpi.optimize(m["opponent"], **pred_args)
            zone_rev = _get_zone_actual_revenue(m)
            total_actual_rev = sum(zone_rev.values())
            cum_scene_qty += r_h.total_attendance
            cum_delta_qty += r_h.total_attendance - actual
            cum_scene_rev += r_h.total_revenue
            cum_delta_rev += r_h.total_revenue - total_actual_rev
        kc1, kc2, kc3, kc4 = st.columns(4)
        with kc1:
            st.markdown(f\'\'\'<div class="kpi-card"><div class="kpi-label">累计场景量</div><div class="kpi-value">{cum_scene_qty:,.0f}张</div></div>\'\'\', unsafe_allow_html=True)
        with kc2:
            qty_color = "#ff6b6b" if cum_delta_qty > 0 else "#51cf66"
            st.markdown(f\'\'\'<div class="kpi-card"><div class="kpi-label">累计Δ量</div><div class="kpi-value" style="color:{qty_color}">{cum_delta_qty:+,.0f}张</div></div>\'\'\', unsafe_allow_html=True)
        with kc3:
            st.markdown(f\'\'\'<div class="kpi-card"><div class="kpi-label">累计场景收入</div><div class="kpi-value">¥{cum_scene_rev/1e4:.1f}万</div></div>\'\'\', unsafe_allow_html=True)
        with kc4:
            rev_color = "#ff6b6b" if cum_delta_rev > 0 else "#51cf66"
            st.markdown(f\'\'\'<div class="kpi-card"><div class="kpi-label">累计Δ收入</div><div class="kpi-value" style="color:{rev_color}">¥{cum_delta_rev/1e4:+.1f}万</div></div>\'\'\', unsafe_allow_html=True)
        render_mae_chart(home_preds)
        render_history_expanders(home_preds, guoan_matches)

    if active_tab == tab_names[2]:
        render_opponent_analysis(all_matches)
    if active_tab == tab_names[3]:
        render_standings_table(guoan_matches, standings, guoan_ded)
    if active_tab == tab_names[4]:
        render_h2_strategy(guoan_matches, standings)
    if active_tab == tab_names[5]:
        render_heatmap_tab(guoan_matches)
    if active_tab == tab_names[6]:
        render_validation_tab(home_preds, guoan_matches, all_matches)

    st.caption("V8.1 · 国安绿品牌 · 决策工作台")


if __name__ == "__main__":
    main()
'''


def _read_lines() -> list[str]:
    return APP.read_text(encoding="utf-8").splitlines(keepends=True)


def _patch_body(rel_path: str, body: str) -> str:
    body = re.sub(r"Path\(__file__\)\.resolve\(\)\.parent\.parent", "ROOT", body)
    body = re.sub(r"Path\(__file__\)\.parent", "Path(__file__).resolve().parent.parent", body)
    body = body.replace("_ctx_rounds", "ctx_rounds")
    if "data_cache.py" in rel_path:
        body = body.replace(
            "# Global: cross-season rounds dict for detect_ctx\nctx_rounds = {}\n\n",
            "_ctx_rounds: dict = {}\n\n\ndef set_ctx_rounds(rounds):\n    global _ctx_rounds\n    _ctx_rounds = rounds\n\n\ndef get_ctx_rounds():\n    return _ctx_rounds\n\n",
        )
        body = body.replace("ctx_rounds", "_ctx_rounds")
        body = body.replace(
            'css_path = Path(__file__).resolve().parent.parent / "style.css"',
            'css_path = Path(__file__).resolve().parent.parent / "style.css"',
        )
    if "tab_next_match.py" in rel_path:
        body = body.replace("detect_ctx(target_match, guoan_matches, _ctx_rounds)", "detect_ctx(target_match, guoan_matches, get_ctx_rounds())")
        body += "\nfrom dashboard.common.data_cache import get_ctx_rounds\n"
    if "tab_history.py" in rel_path:
        body = re.sub(r"detect_ctx\([^)]+_ctx_rounds\)", lambda m: m.group(0).replace("_ctx_rounds", "get_ctx_rounds()"), body)
        body += "\nfrom dashboard.common.data_cache import get_ctx_rounds\n"
    if "brand.py" in rel_path:
        body = body.replace('_ASSETS = Path(__file__).resolve().parent.parent / "assets"', '_ASSETS = Path(__file__).resolve().parent.parent / "assets"')
    if "setup.py" in rel_path:
        body = body.replace(
            'ROOT = Path(__file__).resolve().parent.parent\nsys.path.insert(0, str(ROOT))',
            "",
        )
    if "constants.py" in rel_path:
        body = body.replace("from src.rule_engine import predict_calibrated as rule_predict, TIER_BASE, MULTIPLIERS, PENALTY_FLOOR, get_calibration, get_effective_calibration, update as rule_update\n", "")
    return body


def main():
    lines = _read_lines()
    log = [f"split_app_v8 @ {datetime.now().isoformat()}"]

    if not APP.exists():
        raise SystemExit(f"missing {APP}")

    bak = APP.with_suffix(f".py.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(APP, bak)
    log.append(f"backup -> {bak.name}")

    for rel, (start, end) in SLICES.items():
        out = ROOT / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        body = "".join(lines[start - 1 : end])
        body = _patch_body(rel, body)
        header = MODULE_HEADERS.get(rel, "")
        if not (out.parent / "__init__.py").exists():
            (out.parent / "__init__.py").write_text('"""Dashboard package."""\n', encoding="utf-8")
        out.write_text(header + body, encoding="utf-8")
        log.append(f"wrote {rel} ({end - start + 1} lines)")

    APP.write_text(NEW_APP, encoding="utf-8")
    log.append(f"new app_v8.py ({len(NEW_APP.splitlines())} lines)")

    OUT_LOG.write_text("\n".join(log), encoding="utf-8")
    print("\n".join(log))


if __name__ == "__main__":
    main()
