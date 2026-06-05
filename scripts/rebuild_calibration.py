#!/usr/bin/env python3
"""
Backtest V4.5: 正确的情境检测（derby/saturday/season_opener 等单独计算）
"""
import sys, json, os
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path("/home/xxxsuli/ticket-pricing")
sys.path.insert(0, str(ROOT))

from src.rule_engine import predict, _load_cal, _save_cal, _ALPHA
from src.classify import classify_opponent_tier, DERBY_RIVALS
from src.csl_context import load_csl_data, get_guoan_matches, detect_ctx
from src.match_notes import get_adjusted_actual, get_note

NON_CSL = {"河内公安", "大埔", "麦克阿瑟FC"}

# 1. Load
mf = pd.read_parquet(ROOT / "data/processed/match_features.parquet")
csl = mf[
    (mf['competition'] == 'CSL') & 
    (mf['match_date'].str.startswith(('2025', '2026'))) &
    (~mf['opponent'].isin(NON_CSL))
].sort_values('match_date').copy()

matches_data, standings, _ = load_csl_data()
guoan_all = get_guoan_matches(matches_data)

print(f"待校准: {len(csl)} 场\n")

# 2. Reset
cal = {"tier": {"S": 1.0, "A": 1.0, "B": 1.0, "C": 1.0}, "history": []}
_save_cal(cal)

# Track season openers
season_years = set()
home_matches_seen = set()

print("逐场 EMA 校准:")
print(f"{'日期':<12} {'对手':<10} {'T':<3} {'实际':>8} {'预测':>8} {'比率':>7} {'S':>7} {'A':>7} {'B':>7} {'C':>7} | 情境")
print("-" * 105)

errors = []

for _, m in csl.iterrows():
    opp = m['opponent']
    actual = get_adjusted_actual(m['match_id'], int(m['attendance']))
    note = get_note(m['match_id'])
    date = m['match_date']
    md = pd.Timestamp(date)
    year = str(md.year)
    
    # detect_ctx for dynamic flags only
    match_obj = {"date": date, "opponent": opp, "is_home": True, "completed": True}
    ctx_dynamic = detect_ctx(match_obj, guoan_all, standings)
    
    # Compute simple date-based flags (like predict_with_context does)
    is_derby = opp in DERBY_RIVALS or any(d in opp for d in DERBY_RIVALS)
    is_sat = md.weekday() == 5
    is_late = md.month >= 10
    is_midweek = md.weekday() in (1, 2, 3)
    
    # season_opener: first home match of each season
    is_season_opener = False
    if year not in season_years:
        is_season_opener = True
        season_years.add(year)
    
    pred_kwargs = {
        'derby': is_derby,
        'saturday': is_sat,
        'late_season': is_late,
        'season_opener': is_season_opener,
        'midweek': is_midweek,
        'away_winless': ctx_dynamic.get('away_winless', False),
        'lost_bottom': ctx_dynamic.get('lost_bottom', False),
        'heavy_home_loss': ctx_dynamic.get('heavy_home_loss', False),
        'short_rest': ctx_dynamic.get('short_rest', False),
        'unbeaten_3': ctx_dynamic.get('unbeaten_3', False),
    }
    
    raw = predict(opp, **pred_kwargs)
    tier = classify_opponent_tier(opp)
    
    cal_data = _load_cal()
    factor = cal_data["tier"][tier]
    calibrated = raw * factor
    ratio = actual / raw if raw > 0 else 1.0
    
    old_cal = cal_data["tier"][tier]
    new_cal = round(_ALPHA * ratio + (1 - _ALPHA) * old_cal, 4)
    new_cal = max(0.3, min(2.0, new_cal))
    cal_data["tier"][tier] = new_cal
    
    cal_data["history"].append({
        "match_id": m['match_id'], "date": date, "opponent": opp, "tier": tier,
        "raw_pred": round(raw, 0), "calibrated_pred": round(calibrated, 0),
        "actual": actual, "ratio": round(ratio, 4),
        f"cal_{tier}_before": round(old_cal, 4),
        f"cal_{tier}_after": new_cal,
        "context": {k: v for k, v in pred_kwargs.items() if v},
    })
    _save_cal(cal_data)
    
    err = calibrated - actual
    ape = abs(err) / actual * 100
    errors.append(abs(err))
    
    active_ctx = [k[:3] for k, v in pred_kwargs.items() if v and k not in ('is_home','completed')]
    ctx_str = ','.join(active_ctx) if active_ctx else '-'
    
    print(f"{date:<12} {opp:<10} {tier:<3} {actual:>8} {raw:>8.0f} {ratio:>7.3f} "
          f"{cal_data['tier']['S']:>7.4f} {cal_data['tier']['A']:>7.4f} "
          f"{cal_data['tier']['B']:>7.4f} {cal_data['tier']['C']:>7.4f} | {ctx_str}"
          f"{' *'+note[:20] if note else ''}")

mae_final = np.mean(errors)
print(f"\n最终校准因子: S={cal_data['tier']['S']:.4f} A={cal_data['tier']['A']:.4f} B={cal_data['tier']['B']:.4f} C={cal_data['tier']['C']:.4f}")
print(f"MAE(calibrated): {mae_final:.0f}")

# Also compute raw MAE
raw_errors = [abs(h['raw_pred'] - h['actual']) for h in cal_data['history']]
raw_mae = np.mean(raw_errors)
raw_mape = np.mean([abs(h['raw_pred'] - h['actual']) / h['actual'] * 100 for h in cal_data['history']])
print(f"MAE(raw): {raw_mae:.0f}")
print(f"MAPE(raw): {raw_mape:.1f}%")

# Show 2026-only stats
hist_26 = [h for h in cal_data['history'] if h['date'].startswith('2026')]
if hist_26:
    err_26 = [abs(h['raw_pred'] - h['actual']) for h in hist_26]
    mae_26 = np.mean(err_26)
    mape_26 = np.mean([abs(h['raw_pred'] - h['actual']) / h['actual'] * 100 for h in hist_26])
    print(f"\n2026-only: MAE={mae_26:.0f}, MAPE={mape_26:.1f}%")