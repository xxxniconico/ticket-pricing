#!/usr/bin/env python3
"""阶段4一致性验证：废弃规则已从 detect_ctx / H2 / backtest 清除。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEPRECATED = {"lost_bottom", "unbeaten_3"}
ACTIVE_CTX = {
    "away_winless", "consecutive_home_losses", "heavy_home_loss",
    "short_rest", "midseason_restart", "season_opener", "top3_form",
}


def check_h2_json():
    path = ROOT / "data/targets/h2_2026_match_targets.json"
    if not path.exists():
        print("h2_json SKIP (file missing)")
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    bad = []
    for m in data.get("matches", []):
        for flag in m.get("context", []):
            if flag in DEPRECATED:
                bad.append(f"{m['date']} context={flag}")
    if bad:
        raise AssertionError("h2 json deprecated flags: " + "; ".join(bad))
    print(f"h2_json OK ({len(data.get('matches', []))} matches, no deprecated context)")


def check_detect_ctx():
    from src.csl_context import detect_ctx, get_guoan_matches, load_csl_data

    matches, rounds, _ = load_csl_data()
    guoan = [m for m in get_guoan_matches(matches)
             if "cfl_fixtures_api" in m.get("source", "") or "wikipedia" in m.get("source", "")]
    target = next((m for m in guoan if m["date"] == "2026-05-06" and m.get("is_home")), None)
    if not target:
        print("detect_ctx SKIP (2026-05-06 not found)")
        return
    ctx = detect_ctx(target, guoan, rounds)
    assert not DEPRECATED & set(ctx.keys()), f"detect_ctx returned deprecated: {ctx}"
    assert ctx.get("consecutive_home_losses") is True
    print("detect_ctx OK (consecutive_home_losses, no deprecated keys)")


def check_live_calibrate():
    text = (ROOT / "src/live_calibrate.py").read_text(encoding="utf-8")
    assert "lost_bottom" not in text
    assert "consecutive_home_losses" in text
    print("live_calibrate OK (no lost_bottom, has consecutive_home_losses)")


def check_backtest_source():
    text = (ROOT / "backtest_rule_engine.py").read_text(encoding="utf-8")
    assert '"lost_bottom": ctx.get("lost_bottom"' not in text
    assert "csl_detect_ctx" in text
    assert "consecutive_home_losses" in text
    print("backtest_rule_engine OK (uses csl_detect_ctx)")


def main():
    check_h2_json()
    check_detect_ctx()
    check_live_calibrate()
    check_backtest_source()
    print("PHASE4_VERIFY_PASS")


if __name__ == "__main__":
    main()
