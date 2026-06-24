"""Value identification + screening (plan §4).

For each remaining match:
  1. EV(selection) = p_poisson × odds - 1   for H / D / A
  2. Apply P9 Platt calibration to raw Poisson probs → calibrated EV
  3. Pick max(EV_calibrated). If > EV_THRESHOLD (+5%):
     - inconsistent (Elo-Poisson gap >8%) OR p_h_std > 0.03 → manual review
     - else → candidate bet (Kelly stake, using calibrated probability)
  4. Daily cap 15% across candidates on the same day.
  5. Flag same-day same-group matches (correlated — P5 Monte Carlo).

Tightened from plan defaults: EV threshold 3%→5%, single-bet cap 5%→3%,
reflecting P3 calibration uncertainty (32-match Brier 0.2244, small sample).

P9 update (2026-06-22): applies Platt calibration (draw_inflate + deflate_away
are matrix-layer corrections, already in the score matrix that produced the
poisson probs in model_input.json — but that file was generated pre-P9, so
only Platt is applied here as a post-hoc 1X2 correction).
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODEL_INPUT = PROJECT_ROOT / "data/processed/wc_2026_model_input.json"
OUT_FILE = PROJECT_ROOT / "output/wc_value_opportunities.json"
CALIBRATION_FILE = PROJECT_ROOT / "data/processed/calibration_params.json"

EV_THRESHOLD = 0.05          # +5% (tightened from plan's +3%)
HIGH_DISPERSION = 0.03       # p_h_std > 3% → manual review (plan §4.3)
SELECTIONS = ("h", "d", "a")
SEL_LABEL = {"h": "H", "d": "D", "a": "A"}


def compute_evs(poisson: dict, odds: dict) -> dict[str, float]:
    return {s: poisson[s] * odds[s] - 1.0 for s in SELECTIONS}


def _load_platt():
    """Load Platt calibration params. Returns None if not available."""
    from wc_betting.models.calibration import load_params
    return load_params(CALIBRATION_FILE)


def _calibrate_probs(p: dict, platt_params) -> dict:
    """Apply Platt scaling to {h, d, a} probs. Returns calibrated dict.

    Falls back to raw probs if no params.
    """
    if not platt_params:
        return dict(p)
    from wc_betting.models.calibration import calibrate_1x2
    ch, cd, ca = calibrate_1x2(p["h"], p["d"], p["a"], platt_params)
    return {"h": ch, "d": cd, "a": ca}


def screen(model_input_path: Path = MODEL_INPUT) -> dict:
    from wc_betting.strategy.kelly import kelly_fraction, apply_daily_cap

    data = json.loads(model_input_path.read_text(encoding="utf-8"))
    matches = data["matches"]
    platt_params = _load_platt()
    calibrated = platt_params is not None

    all_rows = []
    candidates = []
    manual = []

    for m in matches:
        p = m["poisson"]
        odds = m["odds"]
        mkt = m["market_implied"]
        p_cal = _calibrate_probs(p, platt_params)
        evs = compute_evs(p, odds)
        evs_cal = compute_evs(p_cal, odds)
        # Use calibrated EV for screening decision.
        best_sel = max(evs_cal, key=lambda s: evs_cal[s])
        best_ev = evs_cal[best_sel]
        best_ev_raw = evs[best_sel]

        row = {
            "group": m["group"],
            "date": m["date"],
            "home": m["home"],
            "away": m["away"],
            "match": f"{m['home']} vs {m['away']}",
            "selection": SEL_LABEL[best_sel],
            "p_model": round(p[best_sel], 4),
            "p_model_calibrated": round(p_cal[best_sel], 4),
            "p_market": round(mkt[best_sel], 4),
            "odds": round(odds[best_sel], 3),
            "ev": round(best_ev_raw, 4),
            "ev_calibrated": round(best_ev, 4),
            "edge": round(p_cal[best_sel] - mkt[best_sel], 4),
            "elo_poisson_gap": m.get("elo_poisson_gap"),
            "inconsistent": m.get("inconsistent"),
            "p_h_std": m.get("p_h_std"),
            "n_bookmakers": m.get("n_bookmakers"),
            "all_evs": {SEL_LABEL[s]: round(evs[s], 4) for s in SELECTIONS},
            "all_evs_calibrated": {SEL_LABEL[s]: round(evs_cal[s], 4) for s in SELECTIONS},
        }

        if best_ev <= EV_THRESHOLD:
            row["status"] = "skip"
            row["kelly_fraction"] = 0.0
            row["note"] = f"EV_cal {best_ev:+.1%} <= {EV_THRESHOLD:+.0%} threshold"
        else:
            flags = []
            if m.get("inconsistent"):
                flags.append("elo-poisson inconsistent")
            if m.get("p_h_std") is not None and m["p_h_std"] > HIGH_DISPERSION:
                flags.append(f"high dispersion p_h_std={m['p_h_std']:.3f}")
            if m.get("n_bookmakers") is not None and m["n_bookmakers"] < 10:
                flags.append(f"thin market n={m['n_bookmakers']}")

            # Kelly stake uses calibrated probability (best estimate).
            f = kelly_fraction(p_cal[best_sel], odds[best_sel])
            row["kelly_fraction"] = round(f, 4)

            if flags:
                row["status"] = "manual"
                row["note"] = "; ".join(flags)
                manual.append(row)
            else:
                row["status"] = "bet"
                row["note"] = ""
                candidates.append(row)

        all_rows.append(row)

    # Daily cap across candidate bets (same date).
    by_date: dict[str, list[dict]] = defaultdict(list)
    for c in candidates:
        by_date[c["date"]].append(c)
    capped_candidates = []
    for date, group in by_date.items():
        capped = apply_daily_cap(group)
        capped_candidates.extend(capped)

    # Flag same-day same-group correlation (round 3 simultaneous matches).
    date_group: dict[tuple, list[str]] = defaultdict(list)
    for r in all_rows:
        date_group[(r["date"], r["group"])].append(r["match"])
    for r in all_rows:
        key = (r["date"], r["group"])
        if len(date_group[key]) > 1:
            r["correlated_same_day_group"] = date_group[key]

    # Final ranked list: candidates first (by EV), then manual, then skip.
    bet_rows = sorted(capped_candidates, key=lambda x: -x["ev"])
    manual_rows = sorted(manual, key=lambda x: -x["ev"])
    skip_rows = [r for r in all_rows if r["status"] == "skip"]
    ranked = bet_rows + manual_rows + skip_rows

    total_staked = sum(r["kelly_fraction"] for r in bet_rows)
    n_bets = len(bet_rows)
    n_manual = len(manual_rows)
    n_skip = len(skip_rows)

    out = {
        "as_of": data.get("as_of"),
        "model": data.get("model"),
        "calibrated": calibrated,
        "risk_params": {
            "ev_threshold": EV_THRESHOLD,
            "single_bet_cap": 0.03,
            "daily_cap": 0.15,
            "kelly_fraction": 0.5,
        },
        "summary": {
            "total_matches": len(matches),
            "bets": n_bets,
            "manual_review": n_manual,
            "skip": n_skip,
            "total_staked": round(total_staked, 4),
            "expected_value_total": round(sum(r["ev_calibrated"] * r["kelly_fraction"] for r in bet_rows), 4),
        },
        "opportunities": ranked,
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def print_table(out: dict) -> None:
    print(f"=== WC 2026 value screening ({out['summary']['total_matches']} matches) ===")
    cal = " + Platt calibration" if out.get("calibrated") else ""
    print(f"risk: EV_cal>={out['risk_params']['ev_threshold']:+.0%}  "
          f"cap={out['risk_params']['single_bet_cap']:.0%}  "
          f"daily={out['risk_params']['daily_cap']:.0%}  "
          f"kelly={out['risk_params']['kelly_fraction']:.1f}x{cal}")
    print()
    s = out["summary"]
    print(f"bets={s['bets']}  manual={s['manual_review']}  skip={s['skip']}  "
          f"total_staked={s['total_staked']:.1%}  expected_EV_cal={s['expected_value_total']:+.4f}")
    print()
    # Bet candidates
    bets = [r for r in out["opportunities"] if r["status"] == "bet"]
    if bets:
        print("--- BET candidates (1/2 Kelly, capped) ---")
        print(f"{'match':34s} sel p_mod p_cal p_mkt odds  EV    EVcal  edge  kelly  note")
        for r in bets:
            corr = " [corr]" if "correlated_same_day_group" in r else ""
            pc = r.get("p_model_calibrated", r["p_model"])
            evc = r.get("ev_calibrated", r["ev"])
            print(f"{r['match'][:34]:34s} {r['selection']}  {r['p_model']:.3f} {pc:.3f} "
                  f"{r['p_market']:.3f} {r['odds']:4.2f} {r['ev']:+.1%} {evc:+.1%} "
                  f"{r['edge']:+.3f} {r['kelly_fraction']:.3f}{corr}")
    # Manual review
    manual = [r for r in out["opportunities"] if r["status"] == "manual"]
    if manual:
        print()
        print("--- MANUAL review (EV_cal>5% but flagged) ---")
        print(f"{'match':34s} sel p_mod p_cal odds  EVcal  note")
        for r in manual:
            pc = r.get("p_model_calibrated", r["p_model"])
            evc = r.get("ev_calibrated", r["ev"])
            print(f"{r['match'][:34]:34s} {r['selection']}  {r['p_model']:.3f} {pc:.3f} "
                  f"{r['odds']:4.2f} {evc:+.1%} {r['note']}")
    # Skipped (compact)
    skips = [r for r in out["opportunities"] if r["status"] == "skip"]
    if skips:
        print()
        print(f"--- SKIP ({len(skips)} matches, EV_cal <= +5%) ---")
        for r in skips:
            evs_cal = r.get("all_evs_calibrated", r["all_evs"])
            best = max(evs_cal, key=lambda k: evs_cal[k])
            print(f"  {r['match'][:34]:34s} best={best} EV_cal={evs_cal[best]:+.1%}")


if __name__ == "__main__":
    out = screen()
    print_table(out)
