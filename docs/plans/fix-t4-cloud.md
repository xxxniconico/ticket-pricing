# Fix T4 定价 & 线上同步问题

> 交给 Cursor 修复。Hermes 已多次尝试修改但未生效（模块缓存/浏览器缓存问题）。

---

## 问题 1：T4 价格不动（河南 ¥460→¥529 而非 ¥460→¥500）

### 现状
- `src/pricing_v5.py`：T4 的 `ZONE_ADJUSTMENT_BOUNDS` 从锁价 (1.00, 1.00) 改为弹性跟随 ✓
- `src/dynamic_optimizer.py`：T4 的 `tier_role` 从 `'locked'` 改为 `'elastic'` ✓
- 弹性区策略改为优化器驱动 + 软上限 ✓
- 跨级约束改为 `upper_price / 1.05` ✓

### 但看板显示仍为旧值
河南 T4 仍显示 ¥460→¥529，预期应为 ¥460→¥500。

### 排查方向
1. 清空 `__pycache__`：`find . -name "__pycache__" -exec rm -rf {} +`
2. 删除 `.streamlit/` 目录
3. 重启 Streamlit：`fuser -k 8504/tcp && streamlit run dashboard/app.py --server.port 8504`
4. 验证命令：`python -c "from src.dynamic_optimizer import DynamicPricingOptimizer; opt = DynamicPricingOptimizer(); r = opt.optimize('河南'); print('T4:', r.tiers['T4'].base_price, '->', r.tiers['T4'].optimal_price)"`
5. 预期输出：`T4: 460 -> 500`

### 如果验证输出正确但看板仍不对
- Streamlit 的 `@st.cache_resource` 可能缓存了旧 optimizer，去掉装饰器试试
- 浏览器 Ctrl+Shift+R 硬刷新

---

## 问题 2：线上版本打不开

### 现状
- GitHub 仓库 `xxxniconico/ticket-pricing` 已推送最新代码
- `streamlit_app.py` 在根目录，内容：`import dashboard.app`
- `dashboard/app.py` 数据源从本地文件改为在线 JSON
- 扣分数据硬编码到源码（避免 raw.githubusercontent 超时）
- JSON 请求超时增加到 60s
- 加了 try/except 容错

### 报错
`ValueError: invalid literal for int() with base 10: '?'`

### 排查方向
- Cloud 版本可能没 Reboot，仍用旧代码
- `load_csl_data()` 中 `standings` 的 keys 为 "第N轮" 格式，`latest_rnd = max(...)` 的 lambda 应该能正确解析
- 如果轮次推断出错（241 场比赛而非 240），修正为：每 8 场一轮，最后一轮可能不足 8 场但 `i // 8 + 1` 仍正确
- 在 Streamlit Cloud 点 "Reboot" 后等待 2-3 分钟再访问

---

## 问题 3：本地和线上数据不一致

### 原因
- 本地读 `/mnt/c/Users/xxxsu/.openclaw/workspace/csl_project_v2/data/csl_final_production_ready.json`
- 线上读 `https://xxxniconico.github.io/csl-dashboard-2026/dashboard_embed.json`
- 两个 JSON 结构不同（线上无 `round` 字段，有 `raw_data` 包装）

### 修复
线上版已处理：`raw = data.get("raw_data", data)` + 按日期推断轮次。确保本地和线上 `load_csl_data()` 逻辑一致。
