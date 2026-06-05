# V8 新增积分榜 Tab

在 `dashboard/app_v8.py` 中新增第 5 个 Tab："积分榜"。

## 数据

main() 中已有 `standings` dict（2026-only 积分榜）和 `DEDUCTIONS` dict（CFA 扣分）。

## 实现

1. 在 `render_opponent_analysis()` 后面新增函数 `render_standings_table(standings, DEDUCTIONS)`:

```python
def render_standings_table(standings, ded):
    # 从 standings 中提取最新一轮的完整积分榜
    # 用 DEDUCTIONS 计算有效积分（pts - ded）
    # 渲染手写 HTML table
```

2. 表格列：`排名 | 球队 | 赛 | 胜 | 平 | 负 | 进球 | 失球 | 净胜 | 积分 | 扣分 | 有效`

3. 国安行高亮（用 `#ff6b6b` 左边框或加粗）

4. 表头用 `table class="compact-table"`

5. 在 main() 中:
   - 将 `tabs = st.tabs([...])` 改为 5 个 Tab（加 "积分榜"）
   - 在 tabs[4] 中调用 `render_standings_table(standings, DEDUCTIONS)`

直接修改 app_v8.py，不改其他文件。
