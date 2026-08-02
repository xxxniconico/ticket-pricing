"""实验追踪 Tab — H2 8场定价实验"""
import streamlit as st
import pandas as pd
from datetime import date

# H2 定价实验矩阵（2026-08-03 更新：已赛 4 场补充实际数据）
# actual_qty/actual_rev 来自 all_unified.parquet；t1-t3 为计划执行价
EXPERIMENTS = [
    {"date":"2026-06-27","opponent":"武汉三镇","tier":"B->C","group":"事后对照",
     "t1":170,"t2":230,"t3":320,"status":"✅ 已赛",
     "actual_qty":6238,"actual_rev":342.7,"q1":3243,"q2":762,"q3":1567,"q4":125,"q5":503,"q6":38},
    {"date":"2026-07-04","opponent":"山东泰山","tier":"A->A","group":"德比弹性",
     "t1":260,"t2":360,"t3":480,"status":"✅ 已赛",
     "actual_qty":12956,"actual_rev":516.8,"q1":3761,"q2":3873,"q3":3472,"q4":1170,"q5":598,"q6":82},
    {"date":"2026-07-17","opponent":"辽宁铁人","tier":"C->B","group":"升级发现",
     "t1":160,"t2":220,"t3":300,"status":"✅ 已赛",
     "actual_qty":7362,"actual_rev":383.3,"q1":3732,"q2":754,"q3":1870,"q4":493,"q5":477,"q6":36},
    {"date":"2026-08-01","opponent":"浙江","tier":"B->B","group":"对照",
     "t1":160,"t2":220,"t3":300,"status":"✅ 已赛",
     "actual_qty":9912,"actual_rev":250.5,"q1":3761,"q2":1775,"q3":2798,"q4":799,"q5":712,"q6":67},
    {"date":"2026-08-07","opponent":"深圳新鹏城","tier":"B->C","group":"降级发现",
     "t1":126,"t2":180,"t3":280,"status":"⏳ 待赛"},
    {"date":"2026-08-22","opponent":"云南玉昆","tier":"B->B","group":"对照",
     "t1":160,"t2":220,"t3":300,"status":"⏳ 待赛"},
    {"date":"2026-10-18","opponent":"青岛西海岸","tier":"B->C","group":"降级验证",
     "t1":126,"t2":180,"t3":280,"status":"⏳ 待赛"},
    {"date":"2026-11-08","opponent":"重庆铜梁龙","tier":"C->B","group":"升级验证",
     "t1":160,"t2":220,"t3":300,"status":"⏳ 待赛"},
]

def render_experiment_tab():
    st.subheader("🧪 H2 定价实验追踪")
    
    df = pd.DataFrame(EXPERIMENTS)
    
    today = date.today().isoformat()
    next_match = None
    for e in EXPERIMENTS:
        if e["status"].startswith("⏳"):
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
                     "actual_qty":"实际销量","actual_rev":"实际收入(万)",
                     "q1":"T1实售","q2":"T2实售","q3":"T3实售",
                     "q4":"T4实售","q5":"T5实售","q6":"T6实售",
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
