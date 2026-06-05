"""2026赛季国安主场预测 (V4.6)"""
import sys, json
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path("/home/xxxsuli/ticket-pricing")
sys.path.insert(0, str(ROOT))
from src.rule_engine import predict, predict_calibrated
from src.classify import classify_opponent_tier, DERBY_RIVALS
from src.csl_context import load_csl_data, get_guoan_matches, detect_ctx

# Load context
matches_data, standings, _ = load_csl_data()
guoan_all = get_guoan_matches(matches_data)

# Get all 2026国安home matches from CSL JSON
home_2026 = []
for m in guoan_all:
    if not m['is_home']: continue
    if not m['date'].startswith('2026'): continue
    home_2026.append(m)

home_2026.sort(key=lambda x: x['date'])

# Load actuals for completed matches
mf = pd.read_parquet(ROOT / "data/processed/match_features.parquet")
NON_CSL = {"河内公安", "大埔", "麦克阿瑟FC"}

print("2026赛季 国安主场预测 (V4.6)")
print("=" * 95)
print(f"{'日期':<12} {'对手':<10} {'Tier':<4} {'状态':<6} {'情境':<20} {'预测':>8} {'校准':>8} {'实际':>8} {'误差':>8}")
print("-" * 95)

season_years = set()

for m in home_2026:
    opp_raw = m['opponent']
    date = m['date']
    md = pd.Timestamp(date)
    completed = m.get('completed', False)
    
    tier = classify_opponent_tier(opp_raw)
    
    # Context
    ctx = detect_ctx({"date": date, "opponent": opp_raw, "is_home": True, "completed": True}, guoan_all, standings)
    
    is_derby = opp_raw in DERBY_RIVALS or any(d in str(opp_raw) for d in DERBY_RIVALS)
    is_sat = md.weekday() == 5
    is_late = md.month >= 10
    is_midweek = md.weekday() in (1, 2, 3)
    
    year = str(md.year)
    is_season_opener = year not in season_years
    if is_season_opener:
        season_years.add(year)
    
    pred_kwargs = {
        'derby': is_derby,
        'saturday': is_sat,
        'late_season': is_late,
        'season_opener': is_season_opener,
        'midweek': is_midweek,
        'away_winless': ctx.get('away_winless', False),
        'lost_bottom': ctx.get('lost_bottom', False),
        'heavy_home_loss': ctx.get('heavy_home_loss', False),
        'short_rest': ctx.get('short_rest', False),
        'unbeaten_3': ctx.get('unbeaten_3', False),
    }
    
    raw = predict(opp_raw, **pred_kwargs)
    calibrated = predict_calibrated(opp_raw, **pred_kwargs)
    
    # Active context flags
    active = []
    for k, v in pred_kwargs.items():
        if v and k not in ('is_home', 'completed'):
            short = {'derby':'德比','saturday':'周六','late_season':'末段',
                     'season_opener':'揭幕','midweek':'周中','away_winless':'客不赢',
                     'lost_bottom':'输弱队','heavy_home_loss':'惨败','short_rest':'短休',
                     'unbeaten_3':'3不败'}.get(k, k[:4])
            active.append(short)
    ctx_str = ','.join(active) if active else '-'
    
    status = '已赛' if completed else '未赛'
    
    # Actual
    actual_str = ''
    err_str = ''
    if completed:
        # Look up actual
        opp_match = mf[(mf['match_date'] == date) & (mf['opponent'].str.contains(opp_raw[:2], na=False))]
        if len(opp_match) == 0:
            opp_match = mf[mf['match_date'] == date]
        actual = int(opp_match['attendance'].iloc[0]) if len(opp_match) > 0 else None
        if actual:
            err = calibrated - actual
            err_pct = abs(err) / actual * 100
            actual_str = f"{actual:>8}"
            err_str = f"{err:+.0f}({err_pct:.1f}%)"
    
    print(f"{date:<12} {opp_raw:<10} {tier:<4} {status:<6} {ctx_str:<20} {raw:>8.0f} {calibrated:>8.0f} {actual_str:<8} {err_str}")

# Summary
print("\n" + "=" * 95)
completed_26 = [m for m in home_2026 if m.get('completed')]
upcoming_26 = [m for m in home_2026 if not m.get('completed')]
print(f"已赛: {len(completed_26)}场 | 未赛: {len(upcoming_26)}场 | 总计: {len(home_2026)}场")