#!/bin/bash
# scripts/fetch_csl_odds.sh
# 周一上午 9 点拉取 The Odds API 中超未来场次赔率
# 覆盖 1-2 周窗口, 给路径 3 看板 tab_odds.py 提供最新数据
#
# 配置: API key 写在 .env (推荐) 或此处明文 (低安全场景)
# 用法: bash scripts/fetch_csl_odds.sh

set -euo pipefail

# 加载 .env (如果存在)
ENV_FILE="/home/xxxsuli/ticket-pricing/.env"
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    set -a; source "$ENV_FILE"; set +a
fi

API_KEY="${ODDS_API_KEY:-}"
if [ -z "$API_KEY" ]; then
    echo "[fetch_csl_odds] ERROR: ODDS_API_KEY not set. Export or add to .env" >&2
    exit 1
fi

PROJECT_DIR="/home/xxxsuli/ticket-pricing"
OUT_DIR="$PROJECT_DIR/data/raw/odds"
OUT_FILE="$OUT_DIR/csl_odds_$(date +%Y%m%d).json"

mkdir -p "$OUT_DIR"

URL="https://api.the-odds-api.com/v4/sports/soccer_china_superleague/odds/?regions=eu&markets=h2h&oddsFormat=decimal&apiKey=$API_KEY"

HTTP_CODE=$(curl -s -o "$OUT_FILE.tmp" -w "%{http_code}" --max-time 30 "$URL")
if [ "$HTTP_CODE" != "200" ]; then
    echo "[fetch_csl_odds] ERROR: HTTP $HTTP_CODE" >&2
    cat "$OUT_FILE.tmp" | head -c 500 >&2
    rm -f "$OUT_FILE.tmp"
    exit 2
fi

# 检查是否真的拿到赔率(不是错误响应)
if grep -q '"error_code"' "$OUT_FILE.tmp"; then
    echo "[fetch_csl_odds] ERROR: API returned error" >&2
    cat "$OUT_FILE.tmp" | head -c 500 >&2
    rm -f "$OUT_FILE.tmp"
    exit 3
fi

mv "$OUT_FILE.tmp" "$OUT_FILE"
N_MATCHES=$(python3 -c "import json; print(len(json.load(open('$OUT_FILE'))))")
echo "[fetch_csl_odds] OK: $N_MATCHES matches saved to $OUT_FILE"

# 保留最近 8 份,删旧的(避免 data/raw/odds 膨胀)
cd "$OUT_DIR"
ls -1t csl_odds_*.json | tail -n +9 | xargs -r rm -f
echo "[fetch_csl_odds] cleaned old files, kept latest 8"
# ── 拉 FIFA 世界杯赔率 (独立看板, 不进 CSL/V5.5) ──
echo "[fetch_csl_odds] also pulling FIFA World Cup odds..."
WC_OUT="$OUT_DIR/fifa_wc_$(date +%Y%m%d).json"
WC_URL="https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/odds/?regions=eu&markets=h2h&oddsFormat=decimal&apiKey=$API_KEY"
HTTP_CODE=$(curl -s -o "$WC_OUT.tmp" -w "%{http_code}" --max-time 30 "$WC_URL")
if [ "$HTTP_CODE" = "200" ] && ! grep -q '"error_code"' "$WC_OUT.tmp"; then
    mv "$WC_OUT.tmp" "$WC_OUT"
    N_WC=$(python3 -c "import json; print(len(json.load(open('$WC_OUT'))))")
    echo "[fetch_csl_odds] FIFA WC: $N_WC matches saved to $WC_OUT"
else
    rm -f "$WC_OUT.tmp"
    echo "[fetch_csl_odds] FIFA WC pull skipped (HTTP $HTTP_CODE or error)"
fi
