#!/bin/bash
# 国安票务定价看板 — 端口 8504
cd "$(dirname "$0")/.."
exec streamlit run dashboard/app.py --server.port 8504 --server.headless true --theme.base dark
