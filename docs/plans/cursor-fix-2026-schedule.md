# Cursor 修复 — 2026赛程不显示

> 问题: Tab1 展开区域"国安2026赛季战绩"显示为空或"暂无2026赛程"。
> 原因排查: schedule 数据可能未正确加载，或 expander 内条件判断失败。

---

## 修复: `dashboard/app.py` — 替换 Tab1 的2026战绩 expander 块

找到 `with tab1:` 下的 `st.expander("📅 国安2026赛季战绩")` 整个块（约行258-320），**完整替换**为：

```python
    with st.expander("📅 国安2026赛季战绩", expanded=True):
        # 积分榜位置
        if not standings.empty:
            guoan_row = standings[standings["team"].str.contains("国安", na=False)]
            if not guoan_row.empty:
                gr = guoan_row.iloc[0]
                rk = int(gr["rank"])
                pts = int(gr["points"])
                ded = int(gr.get("deduction", 0))
                mp = int(gr.get("match_points", pts + ded))
                pos_color = "#51cf66" if rk <= 3 else "#ff6b6b" if rk >= 14 else "#c2ef4e"
                st.markdown(
                    f"**排名**: <span style='color:{pos_color};font-size:1.5em'>第{rk}名</span> "
                    f"| 赛场{mp}分 | 扣{ded}分 | 有效{pts}分",
                    unsafe_allow_html=True,
                )
            else:
                st.caption("积分榜中暂无国安数据")
        
        # 2026已完成比赛
        if not schedule.empty and "result" in schedule.columns:
            completed = schedule[schedule["result"].notna() & (schedule["result"] != "")].copy()
            if not completed.empty:
                st.caption(f"已赛{len(completed)}场")
                completed["date_str"] = completed["date"].dt.strftime("%m/%d")
                for _, r in completed.sort_values("date").iterrows():
                    emoji = {"W": "🟢", "D": "🟡", "L": "🔴"}.get(str(r["result"]).strip(), "⚪")
                    venue_label = "主场" if str(r["venue"]).strip().upper() in ("H", "HOME") else "客场"
                    gg = int(r["guoan_goals"]) if pd.notna(r.get("guoan_goals")) else "?"
                    og = int(r["opp_goals"]) if pd.notna(r.get("opp_goals")) else "?"
                    st.markdown(
                        f"{r['date_str']} {emoji} {'vs' if '主' in venue_label else '@'} "
                        f"{r['opponent']} {gg}-{og}  "
                        f"<small style='color:#9b8fb8'>{venue_label}</small>",
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("暂无已完成的2026比赛数据")
        else:
            st.caption("2026赛程数据未加载，请检查网络连接后刷新页面")
```

## 验证

```bash
pkill -f streamlit
cd ~/ticket-pricing && bash dashboard/serve.sh
```

打开 http://localhost:8504，Tab1 顶部应显示国安排名+11场已赛结果。
