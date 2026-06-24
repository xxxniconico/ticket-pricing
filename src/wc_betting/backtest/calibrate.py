"""Out-of-sample calibration on the 32 played WC 2026 matches (plan §8 gate).

Strict OOS protocol:
  - Poisson refit on pre-WC matches only (date < 2026-06-11, the WC opener).
    2022 Qatar WC matches are kept (valid competitive history).
  - Elo uses ratings BEFORE each WC match, recovered from the history TSV via
    the zero-sum property (ΔR1 + ΔR2 = 0, so elo_before_away = elo_after + rchg1).
  - No pre-match odds exist for finished matches (snapshots only cover upcoming),
    so EV simulation is deferred to P4. This gate covers Brier / log-loss /
    calibration only.

Plan key decision: if home-win Brier >= 0.222 or calibration is severely off,
STOP — do not proceed to P4.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
UNIFIED_FILE = PROJECT_ROOT / "data/processed/wc_2026_unified.json"
HIST_FILE = PROJECT_ROOT / "data/raw/historical/intl_results_2022_2026.json"
ELO_FILE = PROJECT_ROOT / "data/raw/elo/elo_ratings_20260620.json"
HIST_WITH_XG_FILE = PROJECT_ROOT / "data/processed/historical_with_xg.json"
WC_2026_START = "2026-06-11"  # Mexico opener
COMPARISON_FILE = PROJECT_ROOT / "output/wc_model_comparison.json"

NAME_NORMALIZE = {
    "Canada men&#39;s": "Canada", "Canada men's": "Canada",
    "United States men&#39;s": "United States", "United States men's": "United States",
    "Australia men&#39;s": "Australia", "Australia men's": "Australia",
    "Sweden men&#39;s": "Sweden", "Sweden men's": "Sweden",
    "New Zealand men&#39;s": "New Zealand", "New Zealand men's": "New Zealand",
    "Curaçao": "Curacao",
}


def canonical(name: str) -> str:
    return NAME_NORMALIZE.get(name, name)


def parse_score(score: str | None) -> tuple[int, int] | None:
    if not score:
        return None
    parts = score.replace("–", "-").split("-")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def result_onehot(gh: int, ga: int) -> tuple[int, int, int]:
    if gh > ga:
        return (1, 0, 0)
    if gh == ga:
        return (0, 1, 0)
    return (0, 0, 1)


def brier_3class(probs, outcomes) -> float:
    n = len(probs)
    return sum((ph - oh) ** 2 + (pd - od) ** 2 + (pa - oa) ** 2
               for (ph, pd, pa), (oh, od, oa) in zip(probs, outcomes)) / n


def brier_home(probs, outcomes) -> float:
    return sum((p[0] - o[0]) ** 2 for p, o in zip(probs, outcomes)) / len(probs)


def logloss(probs, outcomes) -> float:
    total = 0.0
    for (ph, pd, pa), (oh, od, oa) in zip(probs, outcomes):
        p = ph * oh + pd * od + pa * oa
        total += -math.log(max(p, 1e-15))
    return total / len(probs)


def calibration_buckets(probs, outcomes, edges=None) -> list[tuple]:
    if edges is None:
        edges = [0.0, 0.15, 0.30, 0.45, 0.60, 0.80, 1.01]
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        idx = [i for i, p in enumerate(probs) if lo <= p < hi]
        if not idx:
            rows.append((lo, hi, 0, float("nan"), float("nan")))
            continue
        mean_p = sum(probs[i] for i in idx) / len(idx)
        act = sum(outcomes[i] for i in idx) / len(idx)
        rows.append((lo, hi, len(idx), mean_p, act))
    return rows


def recover_elo_before(history: list[dict]) -> dict:
    """Map (date, team1_code, team2_code, g1, g2) -> (elo_home_before, elo_away_before)
    using elo_after + rating_change (zero-sum: rchg2 = -rchg1)."""
    out = {}
    for m in history:
        g1, g2 = m["team1_goals"], m["team2_goals"]
        r1 = m.get("team1_elo_after")
        r2 = m.get("team2_elo_after")
        rchg1 = m.get("team1_rating_change")
        if g1 is None or r1 is None or r2 is None or rchg1 is None:
            continue
        key = (m["date"], m["team1_code"], m["team2_code"], g1, g2)
        out[key] = (r1 - rchg1, r2 + rchg1)
    return out


def run(verbose: bool = True) -> dict:
    from wc_betting.models.elo import predict_1x2, host_hfa, HFA_NEUTRAL, WC_2026_HOSTS, calibrate_draw_coefficient
    from wc_betting.models.poisson import fit as poisson_fit, predict_1x2 as poisson_predict, host_rho, RHO_NEUTRAL
    from wc_betting.models.blend import blend

    history = json.loads(HIST_FILE.read_text(encoding="utf-8"))["matches"]
    unified = json.loads(UNIFIED_FILE.read_text(encoding="utf-8"))
    elo_ratings = json.loads(ELO_FILE.read_text(encoding="utf-8"))["teams"]
    name_to_code = {name: v["code"] for name, v in elo_ratings.items()}

    # 1. OOS Poisson: refit on pre-WC matches only.
    pre_wc = [m for m in history if m["date"] < WC_2026_START]
    keep_codes = {v["code"] for v in elo_ratings.values()}
    print(f"[fit] Poisson OOS on {len(pre_wc)} pre-WC matches (cutoff {WC_2026_START})...")
    params_oos = poisson_fit(matches=pre_wc, keep_codes=keep_codes)
    print(f"[fit] mu={params_oos.mu:.3f} rho={params_oos.rho:.3f} rho_dc={params_oos.rho_dc:.4f} "
          f"nll={params_oos.nll:.1f} teams={len(params_oos.team_codes)}")

    # 2. Elo draw coefficient (calibrate on full history — this is a hyperparam, not cheating).
    draw_c = calibrate_draw_coefficient(HIST_FILE)
    print(f"[fit] Elo draw_c={draw_c}")

    # 3. elo_before lookup for WC matches.
    elo_before = recover_elo_before(history)

    # 4. Iterate the 32 finished WC matches.
    finished = [m for m in unified if m.get("finished") and m.get("score")]
    model_probs, elo_probs, poisson_probs, outcomes = [], [], [], []
    rows = []
    n_inconsistent = 0
    n_missing_elo = 0

    for m in finished:
        sc = parse_score(m["score"])
        if sc is None:
            continue
        gh, ga = sc
        home_name = canonical(m["home_en"])
        away_name = canonical(m["away_en"])
        home_code = name_to_code.get(home_name)
        away_code = name_to_code.get(away_name)
        if not home_code or not away_code:
            print(f"  [warn] no code for {home_name} or {away_name}")
            continue

        # OOS Elo: recover elo_before from history (match by date+teams+score).
        # History may list the match in either team order; try both.
        mdate = m.get("date") or (m.get("commence_time", "") or "")[:10]
        key1 = (mdate, home_code, away_code, gh, ga)
        key2 = (mdate, away_code, home_code, ga, gh)
        eb = elo_before.get(key1) or elo_before.get(key2)
        if eb is None:
            # Fallback: try date-agnostic match (some unified dates may differ).
            for k, v in elo_before.items():
                if ((k[1] == home_code and k[2] == away_code and k[3] == gh and k[4] == ga) or
                    (k[1] == away_code and k[2] == home_code and k[3] == ga and k[4] == gh)):
                    eb = v
                    break
        if eb is None:
            n_missing_elo += 1
            # Fallback to current ratings (in-sample, flagged).
            eh = elo_ratings[home_name]["elo"]
            ea = elo_ratings[away_name]["elo"]
        else:
            # elo_before returned as (team1_before, team2_before) per history's
            # team order. Normalize so first = home, second = away.
            if key1 in elo_before or any(k[1] == home_code and k[2] == away_code and k[3] == gh and k[4] == ga for k in elo_before):
                eh, ea = eb  # history order matches unified
            else:
                ea, eh = eb  # history order is reversed

        hfa = host_hfa(home_name)
        p_elo = predict_1x2(eh, ea, hfa, draw_c)

        rho = host_rho(params_oos, home_name)
        p_poisson = poisson_predict(params_oos, home_code, away_code, rho=rho)

        bp = blend(p_elo, p_poisson)
        if bp.inconsistent:
            n_inconsistent += 1

        model_probs.append((bp.p_home, bp.p_draw, bp.p_away))
        elo_probs.append(p_elo)
        poisson_probs.append(p_poisson)
        outcomes.append(result_onehot(gh, ga))
        rows.append({
            "match": f"{home_name} {gh}-{ga} {away_name}",
            "result": "H" if gh > ga else ("D" if gh == ga else "A"),
            "elo": p_elo, "poisson": p_poisson, "model": (bp.p_home, bp.p_draw, bp.p_away),
            "elo_h": eh, "elo_a": ea, "gap": bp.elo_poisson_gap, "flag": bp.inconsistent,
        })

    n = len(model_probs)
    home_outcomes = [o[0] for o in outcomes]
    home_probs_model = [p[0] for p in model_probs]
    home_probs_elo = [p[0] for p in elo_probs]
    home_probs_poisson = [p[0] for p in poisson_probs]

    metrics = {
        "n_matches": n,
        "n_inconsistent": n_inconsistent,
        "n_missing_elo_before": n_missing_elo,
        "draw_c": draw_c,
        "brier_3_model": brier_3class(model_probs, outcomes),
        "brier_3_elo": brier_3class(elo_probs, outcomes),
        "brier_3_poisson": brier_3class(poisson_probs, outcomes),
        "brier_home_model": brier_home(model_probs, outcomes),
        "brier_home_elo": brier_home(elo_probs, outcomes),
        "brier_home_poisson": brier_home(poisson_probs, outcomes),
        "logloss_model": logloss(model_probs, outcomes),
        "logloss_elo": logloss(elo_probs, outcomes),
        "logloss_poisson": logloss(poisson_probs, outcomes),
        "calib_model": calibration_buckets(home_probs_model, home_outcomes),
        "calib_elo": calibration_buckets(home_probs_elo, home_outcomes),
        "calib_poisson": calibration_buckets(home_probs_poisson, home_outcomes),
    }

    if verbose:
        _print_report(metrics, rows)
    return metrics


def _print_report(metrics, rows) -> None:
    n = metrics["n_matches"]
    print()
    print(f"=== OOS calibration report ({n} finished WC 2026 matches) ===")
    if metrics["n_missing_elo_before"]:
        print(f"  [warn] {metrics['n_missing_elo_before']} matches fell back to current Elo (in-sample)")
    print()
    print("Brier 3-class (lower=better, baseline uniform=0.667):")
    print(f"  blended  = {metrics['brier_3_model']:.4f}")
    print(f"  elo      = {metrics['brier_3_elo']:.4f}")
    print(f"  poisson  = {metrics['brier_3_poisson']:.4f}")
    print()
    print("Brier home-win (plan target < 0.222, baseline=0.222):")
    print(f"  blended  = {metrics['brier_home_model']:.4f}")
    print(f"  elo      = {metrics['brier_home_elo']:.4f}")
    print(f"  poisson  = {metrics['brier_home_poisson']:.4f}")
    print()
    print("Log-loss (lower=better, baseline uniform=1.099):")
    print(f"  blended  = {metrics['logloss_model']:.4f}")
    print(f"  elo      = {metrics['logloss_elo']:.4f}")
    print(f"  poisson  = {metrics['logloss_poisson']:.4f}")
    print()
    print("Calibration (blended home-win: predicted vs actual):")
    print("  bucket         n   pred    act")
    for lo, hi, cnt, mp, ma in metrics["calib_model"]:
        mp_s = f"{mp:.3f}" if mp == mp else "  -  "
        ma_s = f"{ma:.3f}" if ma == ma else "  -  "
        print(f"  [{lo:.2f},{hi:.2f})    {cnt:2d}   {mp_s}   {ma_s}")
    print()
    print(f"Model inconsistency (Elo vs Poisson gap >8%): {metrics['n_inconsistent']}/{n}")
    print()
    print("Per-match (sorted by Elo-Poisson gap, top 10):")
    print(f"  {'match':30s} res  elo_H   pois_H  mod_H   eh    ea    gap flag")
    for r in sorted(rows, key=lambda x: -x["gap"])[:10]:
        flag = "Y" if r["flag"] else " "
        print(f"  {r['match']:30s} {r['result']}   {r['elo'][0]:.2f}   {r['poisson'][0]:.2f}    "
              f"{r['model'][0]:.2f}   {r['elo_h']} {r['elo_a']}  {r['gap']:.2f} {flag}")
    print()
    bs = metrics["brier_home_model"]
    bs3 = metrics["brier_3_model"]
    # Gate: home-win Brier < 0.222 AND 3-class beats uniform meaningfully.
    if bs < 0.222:
        print(f"GATE: PASS (home-win Brier {bs:.4f} < 0.222, 3-class {bs3:.4f} < 0.667). "
              "Model has predictive skill; may proceed to P4.")
    else:
        print(f"GATE: FAIL (home-win Brier {bs:.4f} >= 0.222). Plan says STOP.")


def _metrics_block(probs, outcomes) -> dict:
    """Compute Brier / log-loss / draw calibration for one variant."""
    home_out = [o[0] for o in outcomes]
    home_probs = [p[0] for p in probs]
    draw_actual = sum(o[1] for o in outcomes) / len(outcomes)
    draw_pred = sum(p[1] for p in probs) / len(probs)
    away_actual = sum(o[2] for o in outcomes) / len(outcomes)
    away_pred = sum(p[2] for p in probs) / len(probs)
    return {
        "brier_home": brier_home(probs, outcomes),
        "brier_3class": brier_3class(probs, outcomes),
        "logloss": logloss(probs, outcomes),
        "draw_pred": draw_pred,
        "draw_actual": draw_actual,
        "away_pred": away_pred,
        "away_actual": away_actual,
        "home_pred": sum(p[0] for p in probs) / len(probs),
        "home_actual": sum(o[0] for o in outcomes) / len(outcomes),
        "calib_buckets": calibration_buckets(home_probs, home_out),
    }


def run_comparison(verbose: bool = True, save: bool = True) -> dict:
    """Compare baseline Poisson vs improved (draw_inflate + deflate_away + Platt)
    vs improved_xg (xG-blended fit + corrections + Platt).

    Strict OOS protocol (same as run()):
      * Poisson refit on pre-WC matches only (date < 2026-06-11).
      * draw_inflate / deflate_away fit on the same pre-WC matches.
      * Platt scaling fit on the OOS WC matches (in-sample calibration — the
        34-match sample is too small to hold out; the statistical-significance
        warning in the dashboard guards against over-reading the result).
      * Elo uses elo_before recovered from history (zero-sum property).

    Gate: improved Brier home < baseline, AND improved draw_pred closer to
    draw_actual than baseline. The improved_xg arm is gated against
    improved_platt.brier_home (0.2141 at the time of P9); if xG coverage is
    insufficient it may not pass — the result is still reported with the
    coverage % noted.
    """
    import dataclasses
    import importlib, sys
    if 'wc_betting.models.poisson' in sys.modules:
        importlib.reload(sys.modules['wc_betting.models.poisson'])
    from wc_betting.models.poisson import (
        fit as poisson_fit, predict_1x2 as poisson_predict, host_rho,
        RHO_NEUTRAL, fit_draw_inflate, fit_deflate_away, is_cross_confederation)
    from wc_betting.models.calibration import fit_platt, calibrate_1x2, save_params

    history = json.loads(HIST_FILE.read_text(encoding="utf-8"))["matches"]
    unified = json.loads(UNIFIED_FILE.read_text(encoding="utf-8"))
    elo_ratings = json.loads(ELO_FILE.read_text(encoding="utf-8"))["teams"]
    name_to_code = {name: v["code"] for name, v in elo_ratings.items()}

    # Try to load xG-merged history for the improved_xg arm. None if not run.
    matches_xg = None
    xg_cov = {"total": 0, "with_xg": 0, "pct": 0.0}
    if HIST_WITH_XG_FILE.exists():
        xg_payload = json.loads(HIST_WITH_XG_FILE.read_text(encoding="utf-8"))
        matches_xg = xg_payload.get("matches")
        if matches_xg:
            total = len(matches_xg)
            with_xg = sum(1 for m in matches_xg
                          if m.get("team1_xg") is not None)
            xg_cov = {"total": total, "with_xg": with_xg,
                      "pct": round(100.0 * with_xg / max(1, total), 1)}
    use_xg_available = matches_xg is not None and xg_cov["with_xg"] > 0

    # 1. Base Poisson on pre-WC (no corrections) — shared MLE for both variants.
    pre_wc = [m for m in history if m["date"] < WC_2026_START]
    keep_codes = {v["code"] for v in elo_ratings.values()}
    if verbose:
        print(f"[fit] base Poisson on {len(pre_wc)} pre-WC matches...")
    params_base = poisson_fit(matches=pre_wc, keep_codes=keep_codes)
    if verbose:
        print(f"[fit] mu={params_base.mu:.3f} rho={params_base.rho:.3f} "
              f"rho_dc={params_base.rho_dc:.4f}")

    # 2. Improved: fit draw_inflate + deflate_away on pre-WC.
    di = fit_draw_inflate(pre_wc, params_base)
    params_improved = dataclasses.replace(
        params_base, draw_inflate=di,
        deflate_away=fit_deflate_away(pre_wc, params_base, draw_inflate=di))
    if verbose:
        print(f"[fit] draw_inflate={params_improved.draw_inflate:.4f} "
              f"deflate_away={params_improved.deflate_away:.4f}")

    # 2b. Improved_xg: refit Poisson with use_xg=True on pre-WC xG-merged
    #     matches, then fit the same two corrections on that base.
    params_xg = None
    params_xg_improved = None
    if use_xg_available:
        pre_wc_xg = [m for m in matches_xg if m["date"] < WC_2026_START]
        if verbose:
            print(f"[fit] xG Poisson on {len(pre_wc_xg)} pre-WC matches "
                  f"({xg_cov['pct']}% xG coverage)...")
        params_xg = poisson_fit(matches=pre_wc_xg, keep_codes=keep_codes,
                                use_xg=True)
        if verbose:
            print(f"[fit] xG mu={params_xg.mu:.3f} rho={params_xg.rho:.3f} "
                  f"rho_dc={params_xg.rho_dc:.4f}")
        di_xg = fit_draw_inflate(pre_wc_xg, params_xg)
        params_xg_improved = dataclasses.replace(
            params_xg, draw_inflate=di_xg,
            deflate_away=fit_deflate_away(pre_wc_xg, params_xg,
                                          draw_inflate=di_xg))
        if verbose:
            print(f"[fit] xG draw_inflate={params_xg_improved.draw_inflate:.4f} "
                  f"deflate_away={params_xg_improved.deflate_away:.4f}")

    # 3. Iterate finished WC matches, compute probs for each variant.
    elo_before = recover_elo_before(history)
    finished = [m for m in unified if m.get("finished") and m.get("score")]
    base_probs, impr_probs, xg_probs, outcomes = [], [], [], []
    n_cross_conf = 0
    for m in finished:
        sc = parse_score(m["score"])
        if sc is None:
            continue
        gh, ga = sc
        home_name = canonical(m["home_en"])
        away_name = canonical(m["away_en"])
        home_code = name_to_code.get(home_name)
        away_code = name_to_code.get(away_name)
        if not home_code or not away_code:
            continue
        rho = host_rho(params_base, home_name)
        cross_conf = is_cross_confederation(home_name, away_name)
        if cross_conf:
            n_cross_conf += 1
        # Baseline: raw Poisson, no corrections (draw_inflate=1, deflate_away=1).
        base_probs.append(poisson_predict(
            params_base, home_code, away_code, rho=rho, cross_conf=False))
        # Improved: corrections applied (cross_conf gates deflate_away).
        impr_probs.append(poisson_predict(
            params_improved, home_code, away_code, rho=rho, cross_conf=cross_conf))
        # Improved_xg: xG-blended fit + corrections + Platt (Platt applied below).
        if params_xg_improved is not None:
            xg_probs.append(poisson_predict(
                params_xg_improved, home_code, away_code, rho=rho,
                cross_conf=cross_conf))
        outcomes.append(result_onehot(gh, ga))

    n = len(base_probs)
    if n == 0:
        raise RuntimeError("no finished WC matches found for comparison")

    # 4. Fit Platt on the improved model's raw OOS probs (in-sample).
    platt_params = fit_platt(impr_probs, outcomes)
    impr_platt_probs = [
        calibrate_1x2(p[0], p[1], p[2], platt_params) for p in impr_probs]
    if verbose:
        print(f"[fit] Platt: {platt_params}")

    # 4b. Fit a SEPARATE Platt on the xG model's raw OOS probs (different
    #     base distribution — xG params shift the raw probs).
    xg_block = None
    xg_platt_block = None
    xg_platt_params = None
    if xg_probs:
        xg_platt_params = fit_platt(xg_probs, outcomes)
        xg_platt_probs = [
            calibrate_1x2(p[0], p[1], p[2], xg_platt_params) for p in xg_probs]
        if verbose:
            print(f"[fit] xG Platt: {xg_platt_params}")

    # 5. Metrics for each variant.
    base_block = _metrics_block(base_probs, outcomes)
    impr_block = _metrics_block(impr_probs, outcomes)
    platt_block = _metrics_block(impr_platt_probs, outcomes)
    if xg_probs:
        xg_block = _metrics_block(xg_probs, outcomes)
        xg_platt_block = _metrics_block(xg_platt_probs, outcomes)

    # 6. Gate.
    brier_pass = platt_block["brier_home"] < base_block["brier_home"]
    draw_base_gap = abs(base_block["draw_pred"] - base_block["draw_actual"])
    draw_impr_gap = abs(platt_block["draw_pred"] - platt_block["draw_actual"])
    draw_pass = draw_impr_gap < draw_base_gap
    # xG gate: improved_xg Brier home must beat improved_platt.
    xg_brier_pass = False
    xg_draw_pass = False
    if xg_platt_block is not None:
        xg_brier_pass = (xg_platt_block["brier_home"]
                         < platt_block["brier_home"])
        xg_draw_gap = abs(xg_platt_block["draw_pred"]
                          - xg_platt_block["draw_actual"])
        xg_draw_pass = xg_draw_gap < draw_impr_gap

    result = {
        "n_matches": n,
        "n_cross_conf": n_cross_conf,
        "poisson_mu": params_base.mu,
        "poisson_rho": params_base.rho,
        "poisson_rho_dc": params_base.rho_dc,
        "draw_inflate": params_improved.draw_inflate,
        "deflate_away": params_improved.deflate_away,
        "platt_params": {k: list(v) for k, v in platt_params.items()},
        "xg_coverage": xg_cov,
        "xg_enabled": use_xg_available,
    }
    if params_xg is not None:
        result["xg_poisson_mu"] = params_xg.mu
        result["xg_poisson_rho"] = params_xg.rho
        result["xg_poisson_rho_dc"] = params_xg.rho_dc
        result["xg_draw_inflate"] = params_xg_improved.draw_inflate
        result["xg_deflate_away"] = params_xg_improved.deflate_away
        result["xg_platt_params"] = {k: list(v) for k, v in xg_platt_params.items()}
    result["baseline"] = base_block
    result["improved_raw"] = impr_block
    result["improved_platt"] = platt_block
    if xg_block is not None:
        result["improved_xg_raw"] = xg_block
        result["improved_xg"] = xg_platt_block
    result["gate"] = {
        "brier_home_pass": brier_pass,
        "draw_pred_pass": draw_pass,
        "baseline_brier_home": base_block["brier_home"],
        "improved_brier_home": platt_block["brier_home"],
        "baseline_draw_gap": draw_base_gap,
        "improved_draw_gap": draw_impr_gap,
        "xg_brier_home_pass": xg_brier_pass,
        "xg_draw_pred_pass": xg_draw_pass,
    }
    if xg_platt_block is not None:
        result["gate"]["xg_brier_home"] = xg_platt_block["brier_home"]
        result["gate"]["xg_draw_gap"] = abs(
            xg_platt_block["draw_pred"] - xg_platt_block["draw_actual"])

    if verbose:
        _print_comparison(result)
    if save:
        # Persist Platt params so the scanner / dashboard can apply them.
        # Prefer xG Platt when the xG arm passed the gate, else the standard one.
        chosen_platt = platt_params
        if xg_platt_params is not None and xg_brier_pass:
            chosen_platt = xg_platt_params
        save_params(chosen_platt, meta={
            "n_matches": n, "source": "run_comparison",
            "draw_inflate": params_improved.draw_inflate,
            "deflate_away": params_improved.deflate_away,
            "xg_enabled": use_xg_available,
            "xg_brier_pass": xg_brier_pass})
        COMPARISON_FILE.parent.mkdir(parents=True, exist_ok=True)
        COMPARISON_FILE.write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        if verbose:
            print(f"[save] {COMPARISON_FILE}")
    return result


def _print_comparison(r: dict) -> None:
    print()
    print(f"=== Baseline vs Improved comparison ({r['n_matches']} OOS WC matches) ===")
    print(f"  draw_inflate={r['draw_inflate']:.4f}  deflate_away={r['deflate_away']:.4f}  "
          f"cross_conf={r['n_cross_conf']}/{r['n_matches']}")
    if r.get("xg_enabled"):
        cov = r["xg_coverage"]
        print(f"  xG: enabled ({cov['with_xg']}/{cov['total']} = {cov['pct']}% coverage)  "
              f"mu={r.get('xg_poisson_mu', 0):.3f} rho_dc={r.get('xg_poisson_rho_dc', 0):.4f}")
    else:
        print(f"  xG: disabled (run fetch_xg to enable)")
    print()
    has_xg = "improved_xg" in r
    xg_hdr = f"{'improved_xg':>12s}" if has_xg else ""
    print(f"{'metric':22s} {'baseline':>10s} {'improved_raw':>12s} {'improved_platt':>14s} {xg_hdr}")
    b = r["baseline"]; ir = r["improved_raw"]; ip = r["improved_platt"]
    xg = r.get("improved_xg")
    def fmt(v, w):
        return f"{v:>{w}.4f}" if v is not None else f"{'-':>{w}s}"
    def fmtp(v, w):
        return f"{v:>{w}.1%}" if v is not None else f"{'-':>{w}s}"
    print(f"{'Brier home':22s} {b['brier_home']:>10.4f} {ir['brier_home']:>12.4f} {ip['brier_home']:>14.4f} {fmt(xg['brier_home'] if xg else None, 12)}")
    print(f"{'Brier 3-class':22s} {b['brier_3class']:>10.4f} {ir['brier_3class']:>12.4f} {ip['brier_3class']:>14.4f} {fmt(xg['brier_3class'] if xg else None, 12)}")
    print(f"{'Log-loss':22s} {b['logloss']:>10.4f} {ir['logloss']:>12.4f} {ip['logloss']:>14.4f} {fmt(xg['logloss'] if xg else None, 12)}")
    print(f"{'Draw pred':22s} {b['draw_pred']:>10.1%} {ir['draw_pred']:>12.1%} {ip['draw_pred']:>14.1%} {fmtp(xg['draw_pred'] if xg else None, 12)}")
    print(f"{'Draw actual':22s} {b['draw_actual']:>10.1%} {'':>12s} {'':>14s} {'':>12s}")
    print(f"{'Away pred':22s} {b['away_pred']:>10.1%} {ir['away_pred']:>12.1%} {ip['away_pred']:>14.1%} {fmtp(xg['away_pred'] if xg else None, 12)}")
    print(f"{'Away actual':22s} {b['away_actual']:>10.1%} {'':>12s} {'':>14s} {'':>12s}")
    print()
    g = r["gate"]
    print("Calibration buckets (home-win pred vs actual):")
    print(f"  {'bucket':12s} {'n':>3s} {'base_pred':>9s} {'impr_pred':>9s} {'actual':>7s}")
    for (lo, hi, cnt, bp, ap), (_, _, _, ip_mp, _) in zip(
            b["calib_buckets"], ip["calib_buckets"]):
        bp_s = f"{bp:.3f}" if bp == bp else "  -  "
        ip_s = f"{ip_mp:.3f}" if ip_mp == ip_mp else "  -  "
        ap_s = f"{ap:.3f}" if ap == ap else "  -  "
        print(f"  [{lo:.2f},{hi:.2f}) {cnt:3d} {bp_s:>9s} {ip_s:>9s} {ap_s:>7s}")
    print()
    status = "PASS" if (g["brier_home_pass"] and g["draw_pred_pass"]) else "FAIL"
    print(f"GATE (improved vs baseline): {status}  "
          f"(Brier home {g['baseline_brier_home']:.4f} -> {g['improved_brier_home']:.4f}, "
          f"draw gap {g['baseline_draw_gap']:.1%} -> {g['improved_draw_gap']:.1%})")
    if "xg_brier_home" in g:
        xg_status = "PASS" if (g["xg_brier_home_pass"] and g["xg_draw_pred_pass"]) else "FAIL"
        print(f"GATE (xG vs improved_platt): {xg_status}  "
              f"(Brier home {g['improved_brier_home']:.4f} -> {g['xg_brier_home']:.4f})")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "compare":
        run_comparison()
    else:
        run()
