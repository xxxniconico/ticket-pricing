#!/bin/bash
# Daily sporttery scanner + portfolio optimizer
# Runs at 14:00 Beijing time via cron
LOG="/home/xxxsuli/ticket-pricing/logs/daily_scan_20260623.log"
echo "=== Tue Jun 23 01:26:23 CST 2026 ===" >> ""
cd /home/xxxsuli/ticket-pricing
export PYTHONPATH=src
~/.hermes/hermes-agent/venv/bin/python -m wc_betting.strategy.sporttery_scanner >> "" 2>&1
~/.hermes/hermes-agent/venv/bin/python -c "from wc_betting.strategy.sporttery_portfolio import run; run()" >> "" 2>&1
echo "Done." >> ""
