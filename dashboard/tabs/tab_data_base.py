"""数据基座 Tab — 分区库存 + 历史销量 + 定价模板"""
import streamlit as st
import pandas as pd
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent / "data" / "base"

@st.cache_data(ttl=3600)
def load_base():
    sm = pd.read_parquet(BASE / "section_master.parquet")
    pt = pd.read_parquet(BASE / "pricing_template.parquet")
    ms = pd.read_parquet(BASE / "match_summary.parquet")
    sales = pd.read_parquet(BASE / "match_section_sales.parquet")
    return sm, pt, ms, sales

def render_data_base():
    st.header("🗄️ 数据基座")
    sm, pt, ms, sales = load_base()
    
    # KPI bar
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("区域总数", len(sm))
    c2.metric("比赛记录", len(ms), f"{ms['match_date'].min()[:4]}-{ms['match_date'].max()[:4]}")
    c3.metric("累计销量", f"{ms['total_sold'].sum():,.0f}票")
    c4.metric("累计人次", f"{ms['unique_users'].sum():,}")
    
    tab1, tab2, tab3, tab4 = st.tabs(["📐 分区主表", "💰 定价模板", "📊 历史销量", "🏟️ 比赛汇总"])
    
    with tab1:
        st.caption(f"section_master — {len(sm)}区 · 静态 · 赛季固定")
        col1, col2 = st.columns(2)
        with col1:
            floor_filter = st.multiselect("楼层", sorted(sm['楼层'].unique()), key="sm_floor")
        with col2:
            stand_filter = st.multiselect("方位", sorted(sm['方位'].unique()), key="sm_stand")
        
        view = sm.copy()
        if floor_filter: view = view[view['楼层'].isin(floor_filter)]
        if stand_filter: view = view[view['方位'].isin(stand_filter)]
        
        st.dataframe(view[['区号','方位','楼层','物理容量','年卡','散票cap','B级档位','体验Q级','死忠区','描述']],
                    use_container_width=True, hide_index=True,
                    column_config={'散票cap': st.column_config.NumberColumn(format="%d"),
                                   '物理容量': st.column_config.NumberColumn(format="%d")})
    
    with tab2:
        st.caption("pricing_template — 6档 × 3级定价")
        st.dataframe(pt.rename(columns={'tier':'档位','price_b':'B级','price_c':'C级','price_sa':'S/A级','elastic_b':'弹性(B)'}),
                    use_container_width=True, hide_index=True,
                    column_config={'B级': '¥{:d}', 'C级': '¥{:d}', 'S/A级': '¥{:d}'})
    
    with tab3:
        st.caption(f"match_section_sales — {len(sales)}条 · 按比赛×区域")
        match_list = sorted(sales['match_date'].dropna().unique())
        sel_match = st.selectbox("选择比赛", match_list, key="ms_match")
        if sel_match:
            m = sales[sales['match_date']==sel_match]
            opp = m['opponent'].iloc[0]
            st.subheader(f"{opp} ({sel_match})")
            # 按区展示
            m_view = m.groupby('section').agg(销量=('qty_sold','sum'),收入=('revenue','sum')).reset_index()
            m_view['收入'] = m_view['收入'].apply(lambda x: f"¥{x:,.0f}" if x>0 else "-")
            st.dataframe(m_view, use_container_width=True, hide_index=True)
            st.caption(f"总销量: {m['qty_sold'].sum():,.0f}票")
    
    with tab4:
        st.caption(f"match_summary — {len(ms)}场比赛")
        view_ms = ms.sort_values('match_date', ascending=False).copy()
        view_ms['match_date'] = view_ms['match_date'].astype(str).str[:10]
        st.dataframe(view_ms[['match_date','opponent','total_sold','unique_users']],
                    use_container_width=True, hide_index=True,
                    column_config={'total_sold': '销量', 'unique_users': '用户数'})
