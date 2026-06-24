# Agent 指南 — ticket-pricing

## 项目结构

```
ticket-pricing/
├── data/raw/              # 原始 Excel（gitignore）
├── data/processed/        # Parquet / JSON（Hermes 产出，Cursor 只读）
├── src/
│   ├── ingest.py          # 数据摄入
│   ├── classify.py        # S/A/B/C 对手分级
│   ├── calibrate.py       # 上座模型 v2/v3/v4/live
│   ├── elasticity.py      # 需求弹性
│   ├── pricing_matrix.py  # 10档×4级调价矩阵
│   ├── optimize.py        # 6档/10档优化器
│   ├── csl_context.py     # detect_ctx 情境检测（与 rule_engine 对齐）
│   ├── data_feeds.py      # 2026 实时积分榜/赛程（勿改拉取逻辑）
│   └── cli.py
├── dashboard/app_v8.py    # Streamlit 看板 V8（唯一看板，:8506）
├── tests/
└── docs/plans/            # 任务单与计划
```

## 约定

- 执行 Cursor 任务前读 `docs/plans/cursor-tasks.md`
- 不改 `data/processed/` 数据文件、`data_feeds.py` 拉取逻辑
- 只改任务指定文件；不删文件
- 旧 API（`classify_match` A/B、`build_attendance_model_v2` 等）保持可调用

## v4.2 核心

- 对手：**S / A / B / C**（`classify_opponent_tier`）
- 上座：**V4** 六特征 OLS（2025-only），**live** 含 2026 已赛
- 定价：**10档** + `PRICING_MATRIX` + `optimize_10tier`
