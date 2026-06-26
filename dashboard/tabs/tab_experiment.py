"""实验追踪 Tab — H2 8场定价实验"""
import streamlit as st
import pandas as pd
from datetime import date

EXPERIMENTS = [
    {"date":"2026-06-27","opponent":"武汉三镇","tier":"B->C","group":"事后对照","t1":"—","t2":"—","t3":"—","status":"✅ 已赛"},
    {"date":"2026-07-04","opponent":"山东泰山","tier":"A->A","group":"德比弹性","t1":260,"t2":374,"t3":484,"status":"⏳ 待武汉数据"},
    {"date":"2026-07-17","opponent":"辽宁铁人","tier":"C->B","group":"升级发现","t1":160,"t2":220,"t3":300,"status":"📋 已确认"},
    {"date":"2026-08-07","opponent":"深圳新鹏城","tier":"B->C","group":"降级发现","t1":126,"t2":180,"t3":280,"status":"📋 已确认"},
    {"date":"2026-08-01","opponent":"浙江","tier":"B->B","group":"对照","t1":160,"t2":220,"t3":300,"status":"📋 已确认"},
    {"date":"2026-08-22","opponent":"云南玉昆","tier":"B->B","group":"对照","t1":160,"t2":220,"t3":300,"status":"📋 已确认"},
    {"date":"2026-10-18","opponent":"青岛西海岸","tier":"B->C","group":"降级验证","t1":126,"t2":180,"t3":280,"status":"📋 已确认"},
    {"date":"2026-11-08","opponent":"重庆铜梁龙","tier":"C->B","group":"升级验证","t1":160,"t2":220,"t3":300,"status":"📋 已确认"},
]

def render_experiment_tab():
    st.subheader("🧪 H2 定价实验追踪")
    
    df = pd.DataFrame(EXPERIMENTS)
    
    today = date.today().isoformat()
    next_match = None
    for e in EXPERIMENTS:
        if e["status"].startswith("⏳") or e["status"].startswith("📋"):
            if e["date"] > today:
                next_match = e
                break
    
    if next_match:
        days_left = (pd.Timestamp(next_match["date"]) - pd.Timestamp(today)).days
        st.info(f"📅 下一场: {next_match['date']} vs {next_match['opponent']} — 还剩 {days_left} 天")
    
    st.dataframe(df, use_container_width=True, hide_index=True,
                 column_config={
                     "date":"日期","opponent":"对手","tier":"Tier变化",
                     "group":"实验组","t1":"T1","t2":"T2","t3":"T3",
                     "status":"状态"
                 })
    
    st.divider()
    st.subheader("📊 弹性数据（赛后填写）")
    
    col1, col2 = st.columns(2)
    with col1:
        match_sel = st.selectbox("选择场次", [f"{e['date']} vs {e['opponent']}" for e in EXPERIMENTS])
    with col2:
        st.text_input("实际总收入(万)")
    
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1: t1_qty = st.number_input("T1销量", 0)
    with c2: t2_qty = st.number_input("T2销量", 0)
    with c3: t3_qty = st.number_input("T3销量", 0)
    with c4: t4_qty = st.number_input("T4销量", 0)
    with c5: t5_qty = st.number_input("T5销量", 0)
    with c6: t6_qty = st.number_input("T6销量", 0)
    
    if st.button("计算弹性"):
        st.info("弹性 ε = ΔQ%/ΔP%，需对比同档历史场次")
