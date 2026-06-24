#!/bin/bash
# 国安票务定价看板 — 端口 8506
cd "$(dirname "$0")/.."
exec streamlit run dashboard/app_v8.py --server.port 8506 --server.headless true --theme.base dark
