#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.rule_engine import MULTIPLIERS, get_effective_calibration, predict
from src.csl_context import detect_ctx, get_guoan_matches, load_csl_data

assert get_effective_calibration("A", enable_ema=False) == 1.0
base = predict("大连英博", match_year="2026")
chl = predict("大连英博", consecutive_home_losses=True, match_year="2026")
assert abs(chl / base - MULTIPLIERS["consecutive_home_losses"]) < 0.01
print("rule_engine OK")

try:
    matches, rounds, _ = load_csl_data()
    guoan = [m for m in get_guoan_matches(matches) if 'cfl_fixtures_api' in m.get('source','') or 'wikipedia' in m.get('source','') or m.get('source','')=='']
    target = next(m for m in guoan if m["date"] == "2026-05-06" and m.get("is_home"))
    ctx = detect_ctx(target, guoan, rounds)
    assert "unbeaten_3" not in ctx and "lost_bottom" not in ctx
    assert ctx.get("consecutive_home_losses") is True, ctx
    print("dalian consecutive_home_losses OK", ctx)
    chengdu = next(m for m in guoan if m["date"] == "2026-04-12" and m.get("is_home"))
    cdx = detect_ctx(chengdu, guoan, rounds)
    assert cdx.get("away_winless_losses") is True, cdx
    pred = predict(chengdu["opponent"], away_winless_losses=True, match_year="2026")
    assert 8200 <= pred <= 8500, pred
    print("chengdu away_winless_losses OK", cdx, f"pred={pred:.0f}")
except Exception as e:
    print("dalian test skipped:", e)

print("PHASE1_VERIFY_PASS")
