# 工体座位图 — 看板集成

## 目标
读取工体票价分区图，生成高还原度 SVG 座位图，嵌入 Streamlit 看板（`:8504`），包含分区着色 + 各档销量预测 + 价格标签。

## 图片
- **路径**: `/mnt/c/Users/xxxsu/OneDrive/图片/微信图片_20251010163606_11_6.jpg`
- **格式**: 1908×1280 JPEG
- **内容**: 工体鸟瞰图，4-5 种颜色分区 + 底部图例

## 集成位置
看板文件：`/home/xxxsuli/ticket-pricing/dashboard/app.py`

当前已有一个占位的 `render_seating_chart(tier, pred, r)` 函数（定义行 147，调用行 510），在 `render_home_card` 末尾通过 expander 调用。需要**替换**这个函数实现。

调用方式不变：
```python
with st.expander("🏟️ 座位图 & 分区预测", expanded=True):
    render_seating_chart(tier, pred, r)
```

参数：
- `tier`: 对手等级（S/A/B/C1/C2）
- `pred`: 总预测销量（张）
- `r`: DynamicPricingOptimizer 的 optimize() 返回值，含 `r.tiers[zt].base_price` / `.optimal_price` / `.is_frozen`

## 数据
### 6 档分区（`data/processed/zone_tier_map.json`）
| 档位 | 标签 | 颜色建议(⚠️待图片验证) | 2025 销量占比 | 基准价(S/A级) | 基准价(B/C级) |
|------|------|---------|-------------|-------------|-------------|
| T1 | 四层低价 | 蓝 | 33.7% | ¥260 | ¥160 |
| T2 | 四层中价 | 绿 | 21.7% | ¥340 | ¥220 |
| T3 | 混合区 | 橙黄 | 30.8% | ¥440 | ¥300 |
| T4 | 四层中间 | 粉红 | 2.7% | ¥580 | ¥460 |
| T5 | 一层边+二层好位 | 橙 | 10.4% | ¥780 | ¥540 |
| T6 | 死忠/VIP | 金 | 0.8% | ¥1,380 | ¥1,080 |

> ⚠️ 颜色映射是像素分析猜测的，Cursor 需用视觉模型直接读图确认。

### 对手等级 → 价格档位
- S/A 级对手 → 用 S_A 价格列
- B/C1/C2 级对手 → 用 B_C 价格列
- **实际开发直接用 `r.tiers[zt].optimal_price`**，已含弹性调整

### Optimizer 返回结构 (`r`)
```python
r.tiers["T1"].base_price     # 基准价
r.tiers["T1"].optimal_price  # 优化后价格
r.tiers["T1"].is_frozen      # 是否锁价（T6 必锁）
r.base_revenue               # 基准总收入
r.total_revenue              # 优化后总收入

### 销量拆分
总预测 `pred` 按 2025 销量占比拆分到各档：
```python
vshare = {"T1": 0.337, "T2": 0.217, "T3": 0.308, "T4": 0.027, "T5": 0.104, "T6": 0.008}
tpred[zt] = int(pred * vshare[zt])
```

## 座位图要求
1. **SVG 格式** — 鸟瞰视角，中央绿色草坪，看台围绕
2. **看台分区** — 按图片的实际分区着色（需要先用视觉模型读图确定颜色映射）
3. **分区标注** — 每个区块标注档位（T1-T6）+ 预测销量 + 价格
4. **底部图例** — 6 档颜色 + 标签 + 销量 + 价格
5. **暗色主题** — 背景 `#0c0d0f`，与看板 Linear 暗色一致
6. **自适应宽度** — `viewBox="0 0 720 500"` 左右

## 输出
修改 `dashboard/app.py` 中的 `render_seating_chart` 函数，替换 SVG 生成逻辑。

## 约束
- 只改 `render_seating_chart` 函数，不动其他代码
- SVG 用 `st.markdown(svg, unsafe_allow_html=True)` 渲染
- Python 语法检查：`py_compile.compile('dashboard/app.py', doraise=True)`
- 完成后 `fuser -k 8504/tcp` 再重启 streamlit 看效果
