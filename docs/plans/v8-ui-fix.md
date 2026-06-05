# V8 UI 修复 + 优化规格

## 扫描发现的 Bug

### Bug 1: `st.caption` 不支持 `unsafe_allow_html`
- L737: `st.caption(f"...<span>...</span>", unsafe_allow_html=True)` → HTML 会被当纯文本显示
- L886: `st.caption("近5场: " + " · ".join(form_icons), unsafe_allow_html=True)` → form_icons 包含 `<span class="W">W</span>` 等HTML，全显示为原始文本
- **修复**: 改为 `st.markdown(..., unsafe_allow_html=True)`

### Bug 2: `.mul` / `.mul-neg` CSS 类只在 `.rule-line` 作用域内
- style.css 中定义: `.rule-line .mul { color: #ff6b6b; }` `.rule-line .mul-neg { color: #51cf66; }`
- 但 `render_recent_results` 中的近期赛果使用 `class="{cls}"` 其中 cls 可以是 "mul" 或 "mul-neg"
- **修复**: 在 style.css 添加全局作用域的 `.mul` 和 `.mul-neg` 类

## UI 排版优化

### 优化 1: 卡片样式统一
Linear 参考 — KPI 卡片应该:
- 背景: `rgba(255,255,255,0.02)` ✓
- 边框: 从 `1px solid rgba(255,255,255,0.06)` 改为更微妙的 `1px solid rgba(255,255,255,0.05)`
- 标签文字：`font-size: 0.62rem; color: #62666d; text-transform: uppercase; letter-spacing: 0.04em` ✓
- 主值: `font-size: 1.15rem; font-weight: 590; color: #f7f8f8`
- 副值: `font-size: 0.65rem; color: #8a8f98`

### 优化 2: 行间距收紧
- 两行 KPI 卡片之间的 gap 改为 8px
- 标题和卡片之间减少空隙

### 优化 3: expander 样式统一
- 所有 `st.expander` 使用一致的标签格式
- 标签中不使用 emoji（避免不同平台显示异常）
- 标签用 `|` 分隔（不用 `—` em-dash）

### 优化 4: 配色微调
- 规则 pill 标签的 up/down 背景透明度调整，让它更接近 Linear pill 风格
- 所有 border 统一用 `rgba(255,255,255,0.05)` 到 `0.08` 范围

### 优化 5: 表格间距
- `.compact-table` 和 `.history-table` 的 padding 略微增加提高可读性
- 表头字号从 0.58rem 调整到 0.62rem

## 执行

请直接修改文件：
1. `dashboard/app_v8.py` — 修复 L737 和 L886 的 st.caption 问题
2. `dashboard/style.css` — 添加全局 .mul/.mul-neg 类，微调配色和间距

不改 src/ 任何文件。
