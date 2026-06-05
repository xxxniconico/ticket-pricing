"""
国安票务 V8 · H2目标执行看板
端口 8505 | 不覆盖 V7 (8504)
"""
import sys, json, math
from pathlib import Path
from collections import defaultdict
import pandas as pd, numpy as np
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.rule_engine import predict_calibrated as rule_predict, TIER_BASE
from src.csl_context import load_csl_data, get_guoan_matches, detect_ctx
from src.match_notes import get_adjusted_actual
from src.pricing_v5 import get_pricing_tier, build_price_matrix, ZONE_TIERS, ZONE_SECTIONS

st.set_page_config(page_title="国安H2目标", page_icon="🎯", layout="wide")

# ═══════════════ CSS ═══════════════
st.markdown("""
<style>
    .stApp { background: #0c0d0f; }
    section[data-testid="stSidebar"] { display: none; }
    h1 { font-weight: 510; font-size: 1.4rem; color: #f7f8f8; letter-spacing: -0.03em; }
    h2 { font-weight: 510; font-size: 1.1rem; color: #e2e4e7; }
    h3 { font-weight: 510; font-size: 0.95rem; color: #c8ccd4; }
    .stMetric { background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06);
                border-radius: 6px; padding: 8px 12px; }
    .stMetric label { font-size: 0.68rem; color: #62666d; font-weight: 400;
                      letter-spacing: 0.03em; text-transform: uppercase; }
    .stMetric [data-testid="stMetricValue"] { font-size: 1.2rem; font-weight: 510; color: #f7f8f8; }
    table { width: 100%; border-collapse: collapse; font-size: 0.78rem;
            background: rgba(255,255,255,0.015); border: 1px solid rgba(255,255,255,0.06); border-radius: 6px; }
    table thead th { background: rgba(255,255,255,0.03); color: #8a8f98; font-weight: 510;
                     font-size: 0.68rem; text-transform: uppercase; padding: 6px 10px;
                     border-bottom: 1px solid rgba(255,255,255,0.06); text-align: center; }
    table tbody td { color: #d0d6e0; padding: 5px 10px; text-align: center;
                     border-bottom: 1px solid rgba(255,255,255,0.03); }
    table tbody tr:hover { background: rgba(255,255,255,0.03); }
    .up { color: #ff6b6b; } .down { color: #51cf66; } .muted { color: #62666d; }
    .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.68rem; font-weight: 510; }
    .badge-priority { background: rgba(255,107,107,0.15); color: #ff6b6b; }
    .badge-tilt { background: rgba(240,192,64,0.15); color: #f0c040; }
    .badge-balanced { background: rgba(81,207,102,0.15); color: #51cf66; }
    .risk-tag { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 0.62rem; margin: 0 2px; }
    .risk-warn { background: rgba(240,192,64,0.12); color: #f0c040; }
    .risk-info { background: rgba(100,180,255,0.12); color: #64b4ff; }
    hr { border-color: rgba(255,255,255,0.06); margin: 0.6rem 0; }
    .status-bar { font-size: 0.75rem; color: #8a8f98; padding: 6px 12px;
                 background: rgba(255,255,255,0.015); border: 1px solid rgba(255,255,255,0.05); border-radius: 6px; }
    .status-bar strong { color: #f7f8f8; font-weight: 510; }
</style>
""", unsafe_allow_html=True)

# ═══════════════ DATA LOADING ═══════════════
@st.cache_data(ttl=300)
def load_all_data():
    """加载所有数据，返回统一结构"""
    all_matches, rounds, standings = load_csl_data()
    guoan = get_guoan_matches(all_matches)
    guoan = [m for m in guoan if 'cfl_fixtures_api' in m.get('source','') or 'wikipedia' in m.get('source','')]
    
    # 正确的context数据源
    ctx_rounds = rounds
    
    # 已完成的主场比赛 (2026)
    completed = [m for m in guoan if m.get("completed") and m["date"].startswith("2026")]
    home_done = sorted([m for m in completed if m["is_home"]], key=lambda x: x["date"])
    
    # 加载目标
    targets_path = ROOT / "data/targets/h2_2026_match_targets.json"
    targets = json.load(open(targets_path)) if targets_path.exists() else {"matches": [], "meta": {}}
    
    return {
        "all_matches": all_matches,
        "guoan": guoan,
        "ctx_rounds": ctx_rounds,
        "home_done": home_done,
        "targets": targets,
        "standings": standings,
    }

@st.cache_data(ttl=300)
def get_match_actual(date_str):
    """获取某场比赛的实际数据"""
    df = pd.read_parquet(ROOT / "data/processed/all_unified.parquet")
    csl = df[(df["competition"] == "CSL") & (~df["is_partial"]) & (~df["is_bundle"])]
    for mid in csl["match_id"].unique():
        md = csl[csl["match_id"] == mid]
        if str(md["match_date"].iloc[0]).startswith(date_str):
            raw = int(md["数量"].sum())
            opp = md["opponent"].iloc[0]
            rev = int(md["实际支付价格"].sum())
            return {"qty": get_adjusted_actual(mid, raw), "rev": rev, "opp": opp}
    return None

def compute_prediction(m, guoan, ctx_rounds, home_done):
    """计算单场预测"""
    dt = pd.Timestamp(m["date"])
    opp = m["opponent"]
    ctx = detect_ctx(m, guoan, ctx_rounds)
    
    # season_opener: 2026首个主场
    first_home = home_done[0] if home_done else None
    is_opener = (first_home is not None and m["date"] == first_home["date"])
    
    pred = rule_predict(opp,
        derby=opp in {"上海申花", "山东泰山"},
        saturday=dt.weekday() == 5,
        late_season=dt.month >= 10,
        midweek=dt.weekday() in [1, 2, 3],
        summer=dt.month in [7, 8],
        season_opener=is_opener,
        match_year=m["date"][:4],
        away_winless=ctx.get("away_winless", False),
        lost_bottom=ctx.get("lost_bottom", False),
        heavy_home_loss=ctx.get("heavy_home_loss", False),
        short_rest=ctx.get("short_rest", False),
        unbeaten_3=ctx.get("unbeaten_3", False))
    return pred, ctx

# ═══════════════ MAIN ═══════════════
data = load_all_data()
home_done = data["home_done"]
targets = data["targets"]
ctx_rounds = data["ctx_rounds"]
guoan = data["guoan"]

# Header
R_2025 = 45_914_055
R_DONE = 20_583_095
Q_DONE = 59_583
R_TARGET_REMAINING = targets["summary"]["total_target_revenue"]
R_ANNUAL = R_DONE + R_TARGET_REMAINING

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("已完成", f"¥{R_DONE/1e6:.1f}M", f"{R_DONE/R_ANNUAL*100:.0f}%")
col2.metric("剩余目标", f"¥{R_TARGET_REMAINING/1e6:.1f}M")
col3.metric("全年预估", f"¥{R_ANNUAL/1e6:.1f}M", f"{R_ANNUAL/R_2025-1:+.1%} vs 2025")
col4.metric("模型", "V5.2", "MAE=300")
col5.metric("已完上座", f"{Q_DONE:,}")

st.divider()

# Progress bar
progress = R_DONE / R_ANNUAL
st.progress(progress, text=f"进度 {progress*100:.1f}% · {7}场已完成 · 剩余{len(targets['matches'])}场")

# ═══════════════ TABS ═══════════════
tab1, tab2 = st.tabs(["📊 目标总览", "🎯 逐场策略"])

with tab1:
    # ── 已完成比赛 ──
    st.subheader("已完成比赛")
    rows_done = []
    preds = []; actuals = []
    for i, m in enumerate(home_done):
        actual = get_match_actual(m["date"][:10])
        if not actual: continue
        pred, ctx = compute_prediction(m, guoan, ctx_rounds, home_done)
        preds.append(pred); actuals.append(actual["qty"])
        err = pred - actual["qty"]
        ctx_tags = ",".join(k for k in ['away_winless','lost_bottom','heavy_home_loss','short_rest','unbeaten_3'] if ctx.get(k)) or "—"
        rows_done.append({
            "日期": m["date"][:10], "对手": actual["opp"],
            "实际": f'{actual["qty"]:,}', "预测": f'{pred:,}',
            "误差": f'{err:+,}', "APE": f'{abs(err)/actual["qty"]*100:.1f}%',
            "触发": ctx_tags, "收入": f'¥{actual["rev"]/1e6:.2f}M'
        })
    
    if rows_done:
        st.markdown(
            pd.DataFrame(rows_done).to_html(index=False, border=0, justify='center', classes='history-table'),
            unsafe_allow_html=True
        )
        mae_val = np.mean(np.abs(np.array(preds) - np.array(actuals)))
        st.caption(f"累积MAE: {mae_val:,.0f}张")
    
    st.divider()
    
    # ── 剩余目标 ──
    st.subheader("剩余8场目标")
    target_rows = []
    for m in targets["matches"]:
        strategy = m["strategy"]
        badge_class = {"revenue_priority": "badge-priority", "revenue_tilt": "badge-tilt", "balanced": "badge-balanced"}
        badge_label = {"revenue_priority": "收入优先", "revenue_tilt": "收入倾向", "balanced": "均衡"}
        badge = f'<span class="badge {badge_class.get(strategy,"")}">{badge_label.get(strategy,strategy)}</span>'
        
        risks = ""
        if m.get("is_upgraded"): risks += f'<span class="risk-tag risk-warn">⚠ 升班马→B</span>'
        if "finale" in m.get("upgrade_reason", ""): risks += f'<span class="risk-tag risk-info">⚡ 收官溢价</span>'
        
        target_rows.append({
            "#": target_rows.__len__() + 1,
            "日期": m["date"], "对手": m["opponent"],
            "策略": badge,
            "预测量": f'{m["predicted_quantity"]:,}',
            "目标均价": f'¥{m["target_avg_price"]:,.0f}',
            "弹性量": f'{m["target_quantity"]:,}',
            "目标收入": f'¥{m["target_revenue"]/1e6:.2f}M',
            "风险": risks,
        })
    
    st.markdown(
        pd.DataFrame(target_rows).to_html(index=False, border=0, justify='center', escape=False),
        unsafe_allow_html=True
    )
    
    total_q = sum(m["target_quantity"] for m in targets["matches"])
    total_r = sum(m["target_revenue"] for m in targets["matches"])
    st.caption(f"合计: {total_q:,}张 · ¥{total_r/1e6:.2f}M · 场均¥{total_r/len(targets['matches'])/1e6:.2f}M")
    
    st.divider()
    
    # ── 累计追踪 ──
    st.subheader("累计追踪")
    cumulative_target = 0
    tracking_rows = []
    for m in targets["matches"]:
        cumulative_target += m["target_revenue"]
        actual = get_match_actual(m["date"])
        actual_str = f'¥{actual["rev"]/1e6:.2f}M' if actual else "—"
        deviation_str = "—"
        if actual:
            dev = actual["rev"] - m["target_revenue"]
            cls = "up" if dev >= 0 else "down"
            deviation_str = f'<span class="{cls}">{dev:+,.0f}</span>'
        tracking_rows.append({
            "节点": m["opponent"],
            "目标单场": f'¥{m["target_revenue"]/1e6:.2f}M',
            "目标累计": f'¥{cumulative_target/1e6:.2f}M',
            "实际": actual_str,
            "偏差": deviation_str,
        })
    
    st.markdown(
        pd.DataFrame(tracking_rows).to_html(index=False, border=0, justify='center', escape=False),
        unsafe_allow_html=True
    )
    
    # Risk status
    st.divider()
    st.markdown(
        '<div class="status-bar">'
        '<strong>🚨 风险熔断:</strong> 正常 · '
        '<strong>关键验证:</strong> 辽宁(7/17) → 升班马B级假设 · '
        '<strong>ε实测:</strong> 待首场涨价后回测</div>',
        unsafe_allow_html=True
    )

with tab2:
    # ── 逐场策略详情 ──
    pm = build_price_matrix()
    
    selected_idx = st.selectbox(
        "选择比赛", 
        range(len(targets["matches"])),
        format_func=lambda i: f'{targets["matches"][i]["date"]} {targets["matches"][i]["opponent"]} · {targets["matches"][i]["strategy"]}'
    )
    
    m = targets["matches"][selected_idx]
    
    col_a, col_b = st.columns([3, 2])
    
    with col_a:
        st.subheader(f'{m["opponent"]} · {m["date"]}')
        
        strategy_label = {"revenue_priority": "收入优先 (rw=0.80)", "revenue_tilt": "收入倾向 (rw=0.60)", "balanced": "均衡 (rw=0.50)"}
        st.caption(f'策略: {strategy_label.get(m["strategy"], m["strategy"])} | 级别: {m["tier"]}')
        
        if m.get("is_upgraded"):
            st.info(f'⚠ 分级升级: {m.get("upgrade_reason","")}')
        
        # Pricing table
        pa = m.get("pricing_actions", {})
        if pa:
            price_rows = []
            for zt in ZONE_TIERS:
                if zt in pa:
                    action = pa[zt]
                    mult_str = f'{action["multiplier"]:.2f}x'
                    cls = "up" if action["multiplier"] > 1.02 else ("down" if action["multiplier"] < 0.98 else "")
                    price_rows.append({
                        "档位": zt,
                        "基准": f'¥{action["base"]}',
                        "目标": f'¥{action["target"]}',
                        "倍数": f'<span class="{cls}">{mult_str}</span>',
                    })
            st.markdown(
                pd.DataFrame(price_rows).to_html(index=False, border=0, justify='center', escape=False),
                unsafe_allow_html=True
            )
        
        # Summary stats
        st.markdown(f"""
        <div class="status-bar">
        <strong>预测量:</strong> {m['predicted_quantity']:,}张 · 
        <strong>目标均价:</strong> ¥{m['target_avg_price']:,} · 
        <strong>弹性量:</strong> {m['target_quantity']:,}张 · 
        <strong>目标收入:</strong> ¥{m['target_revenue']/1e6:.2f}M
        </div>
        """, unsafe_allow_html=True)
    
    with col_b:
        st.subheader("盯盘触发")
        
        # Context risks
        risks = m.get("context_risks", [])
        if risks:
            for r in risks:
                st.caption(f"• {r}")
        
        # 2025 benchmark
        bench = m.get("2025_benchmark")
        if bench:
            st.caption(f'2025参照: {bench["opponent"]} ¥{bench["revenue"]/1e6:.2f}M · {bench["quantity"]:,}张 · ¥{bench["avg_price"]:,}均价')
        
        st.divider()
        
        # Specific triggers based on strategy
        if m["strategy"] == "revenue_priority":
            st.caption("💡 盯死收入底线，量可牺牲")
            st.caption("📉 预售<预测60% → 下调均价5%")
            st.caption("📈 预售>预测80% → 可推均价+5%")
        elif m["strategy"] == "revenue_tilt":
            st.caption("💡 收入优先，允许±5%偏差")
            st.caption("📉 预售<预测50% → 降至balanced策略")
        else:
            st.caption("💡 量价均衡，优先保上座")
            st.caption("📈 预售>预测90% → 可升为revenue_tilt")
