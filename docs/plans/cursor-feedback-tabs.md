# Cursor 修复 — 看板 Tab 分工重构

> 两个 Tab 职责混了。清理：Tab1=2026定价预测，Tab2=2025历史回测。

---

## Tab1 "2026赛季定价" — 只保留以下内容

1. **国安2026战绩**（展开区）：排名 + 11场胜负 + 比分（已有，保留）
2. **参数面板**（已有，保留）：对手选择、周末/赛程自动判断、slider
3. **定价建议表** + KPI卡片（已有，保留）
4. **原因分析**（已有，保留）：弹性曲线 + 乘数分解
5. **CSV导出**（已有，保留）

**删除**：Tab1 中的「2025回测」柱状图和交叉验证区 → 移到 Tab2

---

## Tab2 "2025赛季回测" — 三层结构

### 第一层：2025胜负记录
```
对手 | 日期 | 主/客 | 比分 | 结果
成都蓉城 | 03/29 | 主 | 1-2 | L
浙江俱乐部 | 04/06 | 主 | ? | ?
...
```

从 `2025散票数据.xlsx` 中解析（`比赛` 字段含对手+日期）。

### 第二层：实际销售数据
```
对手 | 散票销量 | 上座率 | A/B级 | 均价
...
```

### 第三层：模型回测对比
```
对手 | 实际销量 | 预测销量 | 偏差% | 预测收入
...
+ KPI卡片: MAE / RMSE / 总量偏差
+ 误差分布条形图
```

---

## 具体修改

### 1. 从 Tab1 删除的内容（行号约462-500）
删除 `# === 交叉验证：回测 ===` 整个 block。

### 2. Tab2 重写

在文件末尾 `with tab2:` 块中，替换为：

```python
with tab2:
    st.subheader("📋 2025赛季 — 历史数据 & 模型回测")
    
    if demand_df is None or base_lookup is None:
        st.warning("核心数据未就绪。")
    else:
        # === 第一层：2025胜负记录 ===
        st.markdown("### 📅 2025赛季战绩")
        from src.ingest import load_seat_data
        seats = load_seat_data(f"{DATA_DIR}/2025散票数据.xlsx")
        
        # 从座位数据提取每场信息
        match_info = seats.groupby("match_id").agg(
            对手=("opponent", "first"),
            日期=("match_date", "first"),
            散票=("match_id", "size"),
        ).reset_index(drop=True)
        match_info["日期"] = pd.to_datetime(match_info["日期"]).dt.strftime("%m/%d")
        match_info = match_info.sort_values("日期")
        
        # 判断主客场（座位数据只有主场）
        match_info["主客"] = "主"
        
        # 从2026赛程匹配比分（如果有的话，否则留空）
        # 简化：直接显示销量
        st.dataframe(
            match_info[["日期", "对手", "主客", "散票"]],
            use_container_width=True, hide_index=True,
            column_config={"散票": st.column_config.NumberColumn(format="%d")}
        )
        
        st.divider()
        
        # === 第二层：模型回测 ===
        st.markdown("### 📊 模型回测")
        
        bt = run_backtest(demand_df, base_lookup, txn_el, DATA_DIR)
        if bt.empty:
            st.info("回测无数据。")
        else:
            bt = bt.copy()
            bt["error"] = bt["predicted"] - bt["actual"]
            bt["error_pct"] = bt["error"] / bt["actual"] * 100
            
            mae = abs(bt["error_pct"]).mean()
            rmse = np.sqrt((bt["error"] ** 2).mean())
            
            c1, c2, c3 = st.columns(3)
            c1.metric("MAE", f"{mae:.0f}%")
            c2.metric("RMSE", f"{rmse:,.0f}张")
            c3.metric("总量偏差", f"{(bt['predicted'].sum()-bt['actual'].sum())/bt['actual'].sum()*100:+.1f}%")
            
            # 回测柱状图
            fig, ax = plt.subplots(figsize=(10, 4))
            fig.patch.set_facecolor("#1f1633")
            ax.set_facecolor("#1f1633")
            x = range(len(bt))
            ax.bar(x, bt["actual"], width=0.35, label="实际", color="#c2ef4e", alpha=0.8)
            ax.bar([i+0.35 for i in x], bt["predicted"], width=0.35, label="预测", color="#ff6b6b", alpha=0.8)
            ax.set_xticks([i+0.175 for i in x])
            ax.set_xticklabels(bt["opponent"].str.slice(0,4), rotation=45, color="#9b8fb8", fontsize=8)
            ax.set_ylabel("散票", color="#9b8fb8")
            ax.set_title("预测 vs 实际", color="#c2ef4e")
            ax.legend(facecolor="#2a1f3d", edgecolor="#3a2f55", labelcolor="#e0dce8")
            ax.tick_params(colors="#9b8fb8")
            for s in ax.spines.values(): s.set_color("#3a2f55")
            ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
            ax.grid(alpha=0.15, color="#9b8fb8", axis="y")
            st.pyplot(fig, clear_figure=True)
            plt.close(fig)
            
            # 误差分布
            fig2, ax2 = plt.subplots(figsize=(6, 4))
            fig2.patch.set_facecolor("#1f1633")
            ax2.set_facecolor("#1f1633")
            colors = ["#ff6b6b" if v>0 else "#51cf66" for v in bt["error_pct"]]
            ax2.barh(range(len(bt)), bt["error_pct"], color=colors)
            ax2.set_yticks(range(len(bt)))
            ax2.set_yticklabels(bt["opponent"].str.slice(0,4), color="#9b8fb8", fontsize=8)
            ax2.axvline(0, color="#9b8fb8", linewidth=0.5)
            ax2.set_xlabel("误差%", color="#9b8fb8")
            ax2.set_title("每场预测偏差", color="#c2ef4e")
            ax2.tick_params(colors="#9b8fb8")
            for s in ax2.spines.values(): s.set_color("#3a2f55")
            ax2.spines["top"].set_visible(False); ax2.spines["right"].set_visible(False)
            ax2.grid(alpha=0.15, color="#9b8fb8", axis="x")
            st.pyplot(fig2, clear_figure=True)
            plt.close(fig2)
            
            # 逐场对比表
            disp = bt[["opponent", "tier", "actual", "predicted", "error_pct", "revenue_pred"]].copy()
            disp.columns = ["对手", "级别", "实际", "预测", "误差%", "预测收入"]
            disp["误差%"] = disp["误差%"].apply(lambda x: f"{x:+.0f}%")
            disp["预测收入"] = disp["预测收入"].apply(lambda x: f"¥{x:,.0f}")
            st.dataframe(disp, use_container_width=True, hide_index=True)
```

### 3. 验证

```bash
pkill -f streamlit; cd ~/ticket-pricing
bash dashboard/serve.sh
# 打开 http://localhost:8504
```

Tab1 应该是纯2026（战绩+定价预测），Tab2 是纯2025（战绩+回测）。
