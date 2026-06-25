"""EV scanner for China Sporttery (体彩) odds.

Loads the Dixon-Coles Poisson model (already fit in P2), computes the full
score probability matrix for each WC 2026 match, then derives model
probabilities for each of the 4 sporttery pool types:

  had  — 1X2 (H/D/A)
  hhad — handicap 1X2 (apply goalLine to home, then H/D/A)
  crs  — correct score (read matrix cell directly; "其他" = sum of unlisted)
  ttg  — total goals (sum cells where h+a == k, k=0..6; 7+ = h+a >= 7)

For each offered option: EV = p_model × odds - 1.  1/4 Kelly stake sizing
(sporttery vig ~30% is 3-5x international books, so we cut Kelly more).
Single-bet cap 3%, daily cap 15%.

Output: output/wc_sporttery_opportunities.json

Sign convention for hhad
------------------------
`goalLine` from sporttery is added to the home team's virtual score:
    virtual_home_goals = home_goals + goalLine
So goalLine = -1 (主队让1球, home favored) → virtual home = home - 1, which
means the home side must win by 2+ to "win" the bet. If verification against
real hhad results shows the opposite, flip HANDICAP_SIGN below.

Research only. No real betting.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import importlib, sys
if "wc_betting.models.poisson" in sys.modules:
    importlib.reload(sys.modules["wc_betting.models.poisson"])
from wc_betting.models.poisson import (PoissonModel, score_matrix,
                                       host_rho, RHO_NEUTRAL,
                                       is_cross_confederation)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODEL_INPUT = PROJECT_ROOT / "data/processed/wc_2026_model_input.json"
OUT_FILE = PROJECT_ROOT / "output/wc_sporttery_opportunities.json"

# Sporttery return rate ~70% (vig ~30%). Used only for reporting p_implied
# in the output JSON; the EV calc itself uses raw odds (EV = p_model * odds - 1).
SPORTTERY_RETURN_RATE = 0.70

# 1/4 Kelly because sporttery vig is much higher than international books.
KELLY_HALF = 0.25
SINGLE_BET_CAP = 0.03
DAILY_CAP = 0.15
# Only flag opportunities with EV > this (loose threshold — we keep all EV>0
# but tag the ones worth betting on).
EV_THRESHOLD = 0.0
MIN_P_MODEL_CRS = 0.02   # ignore CRS/TTG with model prob < 2%
MIN_P_MODEL_HAD = 0.12  # auto-review: rejects had/hhad underdog bets < 12%
MAX_ODDS_AUTO = 25.0   # max odds for auto-review (extreme longshots → manual)

# Elo-Poisson gap threshold: when the model's 1X2 probs diverge from Elo-based
# probs by more than this, the match is flagged as "manual review" and excluded
# from automatic portfolio optimization. Matches value.py's threshold (plan §4).
ELO_POISSON_GAP_THRESHOLD = 0.08

# hhad sign convention (see docstring).
HANDICAP_SIGN = 1.0  # virtual_home = home_goals + HANDICAP_SIGN * goalLine

MAX_GOALS = 10  # score matrix truncation (matches poisson.MAX_GOALS)

POOL_NAMES_CN = {
    "had":  "胜平负",
    "hhad": "让球胜平负",
    "crs":  "比分",
    "ttg":  "总进球数",
}

# Pool playability priority (1 = most playable). From the theory doc §3.2:
# crs (31 outcomes, lowest pricing efficiency) > ttg (8) > hhad (3) > had (3).
# Lower number = higher priority when EV is tied.
POOL_PRIORITY: dict[str, int] = {"crs": 1, "ttg": 2, "hhad": 3, "had": 4}

# Path to persisted Platt params (produced by backtest.calibrate.run_comparison).
CALIBRATION_FILE = PROJECT_ROOT / "data/processed/calibration_params.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _kelly(p: float, odds: float) -> float:
    """1/4 Kelly stake, capped at SINGLE_BET_CAP. Returns 0 if no edge."""
    from wc_betting.strategy.kelly import kelly_fraction
    return kelly_fraction(p, odds, half=KELLY_HALF, cap=SINGLE_BET_CAP)


def _vig_cost(odds: dict) -> float:
    """Overround (vig) for one pool's odds: Σ(1/odds) - 1.

    A fair market sums to 1.0; sporttery's ~70% return rate gives ~0.43.
    Higher = more aggressive vig for that pool/match.
    """
    s = sum(1.0 / float(o) for o in odds.values() if float(o) > 1.0)
    return round(s - 1.0, 4)


def _calibrate_had_probs(p_map: dict[str, float], platt_params) -> dict[str, float]:
    """Apply Platt scaling to had/hhad 1X2 probs. Falls back to raw if no params."""
    if not platt_params:
        return p_map
    from wc_betting.models.calibration import calibrate_1x2
    ph = p_map.get("H", 0.0); pd = p_map.get("D", 0.0); pa = p_map.get("A", 0.0)
    ch, cd, ca = calibrate_1x2(ph, pd, pa, platt_params)
    return {"H": ch, "D": cd, "A": ca}


def _load_model_and_matches():
    """Load PoissonModel + the WC 2026 match list (for group/date lookup).

    If data/processed/historical_with_xg.json exists (produced by
    fetch_xg.merge_xg_with_historical), the Poisson model is fit with
    use_xg=True (quasi-Poisson on xG matches + standard DC on the rest).
    """
    import importlib, sys
    if "wc_betting.models.poisson" in sys.modules:
        importlib.reload(sys.modules["wc_betting.models.poisson"])
    from wc_betting.models.poisson import (PoissonModel, score_matrix,
                                           host_rho, RHO_NEUTRAL,
                                           is_cross_confederation)
    from wc_betting.models.calibration import load_params as load_platt
    from wc_betting.models.elo import EloModel
    _elo = EloModel()
    _elo.calibrate()
    from wc_betting.data.fetch_xg import load_historical_with_xg, xg_coverage

    matches_xg = load_historical_with_xg()  # None if file missing
    use_xg = matches_xg is not None
    cov = xg_coverage(matches_xg) if matches_xg else {"total": 0, "with_xg": 0, "pct": 0.0}
    model = PoissonModel.fit(matches=matches_xg, use_xg=use_xg, competitive_only=True)
    # Override draw_inflate / deflate_away with OOS-calibrated values from
    # calibration_params.json meta (if present). The full-historical-fit values
    # on model.params (draw_inflate≈1.0, deflate_away≈0.56) overfit the 2135-
    # match training set; the OOS values (1.01, 0.62) generalise better on
    # WC 2026 backtest (Brier home 0.2258 → 0.2234, accuracy 52.5% → 60%).
    if CALIBRATION_FILE.exists():
        try:
            _cal = json.loads(CALIBRATION_FILE.read_text(encoding="utf-8"))
            _meta = _cal.get("meta", {})
            if "draw_inflate" in _meta:
                model.params.draw_inflate = float(_meta["draw_inflate"])
            if "deflate_away" in _meta:
                model.params.deflate_away = float(_meta["deflate_away"])
        except (json.JSONDecodeError, OSError, TypeError):
            pass
    mi = json.loads(MODEL_INPUT.read_text(encoding="utf-8"))
    # Build (home_en, away_en) -> {group, date} lookup from model_input.
    match_lookup: dict[tuple[str, str], dict] = {}
    for m in mi["matches"]:
        match_lookup[(m["home"], m["away"])] = {
            "group": m["group"], "date": m["date"],
            "elo_poisson_gap": m.get("elo_poisson_gap"),
            "inconsistent": m.get("inconsistent", False),
            "market_implied": m.get("market_implied", {}),
            "poisson_1x2": m.get("poisson", {}),
        }
    platt_params = load_platt(CALIBRATION_FILE)
    return (model, score_matrix, host_rho, RHO_NEUTRAL, match_lookup,
            is_cross_confederation, platt_params, use_xg, cov)


def _resolve_codes(model, home_en: str | None,
                   away_en: str | None) -> tuple[str, str] | None:
    """Map English team names → Poisson model team codes. None on failure."""
    if not home_en or not away_en:
        return None
    hc = model.name_to_code.get(home_en)
    ac = model.name_to_code.get(away_en)
    if hc is None or ac is None:
        return None
    return hc, ac


def _prob_had(matrix: np.ndarray) -> dict[str, float]:
    """H/D/A from full score matrix."""
    p_h = float(np.tril(matrix, -1).sum())  # i > j
    p_d = float(np.trace(matrix))
    p_a = float(np.triu(matrix, 1).sum())   # i < j
    return {"H": p_h, "D": p_d, "A": p_a}


def _prob_hhad(matrix: np.ndarray, goal_line: float | None) -> dict[str, float]:
    """Handicap 1X2: virtual_home = i + HANDICAP_SIGN * goalLine, compare to j."""
    if goal_line is None:
        goal_line = 0.0
    g = HANDICAP_SIGN * float(goal_line)
    n = matrix.shape[0]
    # Build index grids; virtual home can go negative or > max_goals, both
    # of which just contribute to one of the three buckets deterministically.
    i = np.arange(n)[:, None]
    j = np.arange(n)[None, :]
    vh = i + g
    p_h = float(matrix[(vh > j)].sum())
    p_d = float(matrix[(vh == j)].sum())
    p_a = float(matrix[(vh < j)].sum())
    return {"H": p_h, "D": p_d, "A": p_a}


def _prob_crs(matrix: np.ndarray,
              offered_keys: list[str]) -> dict[str, float]:
    """Correct score: matrix cell per offered score, "其他" = sum of unlisted.

    offered_keys uses the same encoding as fetch_sporttery:
      '(h,a)'           — specific score
      'H_OTHER'/'D_OTHER'/'A_OTHER' — fall-through buckets
    """
    out: dict[str, float] = {}
    listed_cells: set[tuple[int, int]] = set()
    n = matrix.shape[0]
    for key in offered_keys:
        if key in ("H_OTHER", "D_OTHER", "A_OTHER"):
            continue
        k = key.strip("()").split(",")
        if len(k) != 2:
            continue
        try:
            h, a = int(k[0]), int(k[1])
        except ValueError:
            continue
        if 0 <= h < n and 0 <= a < n:
            out[key] = float(matrix[h, a])
            listed_cells.add((h, a))

    if "H_OTHER" in offered_keys:
        s = 0.0
        for h in range(n):
            for a in range(n):
                if h > a and (h, a) not in listed_cells:
                    s += matrix[h, a]
        out["H_OTHER"] = float(s)
    if "D_OTHER" in offered_keys:
        s = 0.0
        for h in range(n):
            if (h, h) not in listed_cells:
                s += matrix[h, h]
        out["D_OTHER"] = float(s)
    if "A_OTHER" in offered_keys:
        s = 0.0
        for h in range(n):
            for a in range(n):
                if h < a and (h, a) not in listed_cells:
                    s += matrix[h, a]
        out["A_OTHER"] = float(s)
    return out


def _prob_ttg(matrix: np.ndarray, offered_keys: list[str]) -> dict[str, float]:
    """Total goals: sum cells where h+a == k for k in 0..6; 7+ for k>=7."""
    n = matrix.shape[0]
    # Precompute full totals 0..7+ over the full matrix.
    totals: dict[int, float] = {}
    for k in range(7):
        s = 0.0
        for h in range(n):
            for a in range(n):
                if h + a == k:
                    s += matrix[h, a]
        totals[k] = float(s)
    # 7+ = everything not yet counted.
    totals[7] = float(max(0.0, 1.0 - sum(totals[k] for k in range(7))))
    out: dict[str, float] = {}
    for key in offered_keys:
        try:
            k = int(key)
        except ValueError:
            continue
        if 0 <= k <= 7:
            out[str(k)] = totals[k]
    return out


def _model_probs(matrix: np.ndarray, pool: str,
                 handicap: float | None,
                 offered_keys: list[str]) -> dict[str, float]:
    if pool == "had":
        return _prob_had(matrix)
    if pool == "hhad":
        return _prob_hhad(matrix, handicap)
    if pool == "crs":
        return _prob_crs(matrix, offered_keys)
    if pool == "ttg":
        return _prob_ttg(matrix, offered_keys)
    raise ValueError(f"unknown pool: {pool}")


def _selection_cn(pool: str, key: str) -> str:
    """Human-readable Chinese label for an option key."""
    if pool in ("had", "hhad"):
        return {"H": "胜", "D": "平", "A": "负"}.get(key, key)
    if pool == "crs":
        if key == "H_OTHER": return "胜其他"
        if key == "D_OTHER": return "平其他"
        if key == "A_OTHER": return "负其他"
        k = key.strip("()").split(",")
        if len(k) == 2:
            return f"{k[0]}:{k[1]}"
        return key
    if pool == "ttg":
        return "7+" if key == "7" else f"{key}球"
    return key


def _apply_daily_cap(ops: list[dict],
                     daily_cap: float = DAILY_CAP) -> list[dict]:
    """Sort by calibrated EV desc (then pool priority) per date, truncate
    cumulative stake to daily cap.

    Mutates `recommended_stake` on copies. Kelly stake is preserved as-is in
    `kelly_stake` so the user can see the pre-cap value.
    """
    by_date: dict[str, list[dict]] = defaultdict(list)
    for op in ops:
        by_date[op["date"] or "?"].append(op)
    for date, group in by_date.items():
        ranked = sorted(group, key=lambda x: (-x.get("ev_calibrated", x["ev"]),
                                              x.get("pool_priority", 9)))
        cumulative = 0.0
        for op in ranked:
            remaining = daily_cap - cumulative
            if remaining <= 0:
                op["recommended_stake"] = 0.0
                op["stake_note"] = "daily cap reached"
            elif op["kelly_stake"] > remaining:
                op["recommended_stake"] = round(remaining, 4)
                op["stake_note"] = "truncated by daily cap"
                cumulative = daily_cap
            else:
                op["recommended_stake"] = op["kelly_stake"]
                op["stake_note"] = ""
                cumulative += op["kelly_stake"]
    return ops


def run(odds_rows: list[dict] | None = None,
        out_path: Path = OUT_FILE) -> dict:
    """Scan sporttery odds for +EV opportunities.

    `odds_rows` defaults to fetch_sporttery.fetch_all(cache_only=True)
    (offline dev). Pass load_manual_odds(path) for the manual workflow.
    """
    from wc_betting.data.fetch_sporttery import fetch_all
    from wc_betting.data.sporttery_db import SportteryDB

    if odds_rows is None:
        odds_rows = fetch_all(cache_only=True)

    (model, score_matrix, host_rho, RHO_NEUTRAL, match_lookup,
     is_cross_confederation, platt_params, use_xg, xg_cov) = _load_model_and_matches()
    calibrated = platt_params is not None

    # Cache score matrices per (home_en, away_en) so we don't recompute
    # for each of the 4 pools on the same match.
    matrix_cache: dict[tuple[str, str], np.ndarray] = {}
    opportunities: list[dict] = []
    matches_scanned = 0
    skipped_unmatched: list[dict] = []

    # Group rows by match (same match appears once per pool).
    by_match: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in odds_rows:
        by_match[(r.get("home_en") or "", r.get("away_en") or "")].append(r)

    for (home_en, away_en), rows in by_match.items():
        codes = _resolve_codes(model, home_en, away_en)
        if codes is None:
            for r in rows:
                skipped_unmatched.append({
                    "home_cn": r.get("home_cn"), "away_cn": r.get("away_cn"),
                    "home_en": home_en, "away_en": away_en,
                    "pool_code": r.get("pool_code"),
                    "reason": "team name not in Poisson model",
                })
            continue
        home_code, away_code = codes
        # Neutral venue unless home team is a WC 2026 host.
        rho = host_rho(model.params, home_en)
        # Cross-confederation gating for deflate_away (theory doc §8).
        # deflate_away corrects away-team travel disadvantage in cross-conf
        # home/away matches. At neutral venues (rho == RHO_NEUTRAL, e.g. WC
        # matches), there is no away disadvantage, so skip the correction.
        cross_conf = is_cross_confederation(home_en, away_en)
        if rho == RHO_NEUTRAL:
            cross_conf = False
        if (home_en, away_en) not in matrix_cache:
            matrix_cache[(home_en, away_en)] = score_matrix(
                model.params, home_code, away_code, rho=rho, max_goals=MAX_GOALS,
                cross_conf=cross_conf)
        matrix = matrix_cache[(home_en, away_en)]
        matches_scanned += 1
        meta = match_lookup.get((home_en, away_en), {})
        group = meta.get("group", "?")
        date = rows[0].get("date") or meta.get("date", "")
        elo_gap = meta.get("elo_poisson_gap")
        inconsistent = meta.get("inconsistent", False)

        for r in rows:
            pool = r["pool_code"]
            odds = r.get("odds", {})
            if not odds:
                continue
            handicap = r.get("handicap")
            p_model_map = _model_probs(matrix, pool, handicap, list(odds.keys()))
            # had: Platt-calibrate the 1X2 probs. crs/ttg: matrix probs
            # already carry the draw_inflate correction; no 1X2-level Platt.
            # hhad: Platt NOT applied — it was fitted on had 1X2 distribution
            # where D≈25-30%. For hhad, D can be 10-20% (large handicaps),
            # and Platt's D param (b=0) outputs constant 0.324, inflating D
            # and creating false positive EV on hhad D bets.
            if pool == "had" and calibrated:
                p_calib_map = _calibrate_had_probs(p_model_map, platt_params)
            else:
                p_calib_map = p_model_map
            vig = _vig_cost(odds)
            for key, price in odds.items():
                p = p_model_map.get(key)
                if p is None or p <= 0:
                    continue

                # Elo fusion: blend Poisson with Elo probabilities
                # w_H=0.25 (75% Elo), w_D=0.70 (70% Poisson) from 36-match backtest
                market_p = meta.get("market_implied", {})
                if market_p and pool in ("had", "hhad") and key in ("H", "D", "A"):
                    mp = market_p.get({"H": "h", "D": "d", "A": "a"}.get(key, key), 0)
                    if mp > 0:
                        w = 0.70 if key == "D" else 0.25
                        p = w * p + (1 - w) * mp

                # CRS/TTG: skip very low probability scores (model noise)
                if pool in ('crs', 'ttg') and p < MIN_P_MODEL_CRS:
                    continue
                # had/hhad: skip extreme underdog bets (model itself gives < 12%)
                if pool in ('had', 'hhad') and p < MIN_P_MODEL_HAD:
                    continue
                price_f = float(price)
                if price_f <= 1.0:
                    continue
                p_c = p_calib_map.get(key, p)
                ev = p * price_f - 1.0
                ev_c = p_c * price_f - 1.0
                if ev_c <= EV_THRESHOLD:
                    continue
                kelly = _kelly(p_c, price_f)
                # Mismatch detection: model significantly underestimates favorite
                # (model gives H < 65% but market gives H > 75% → cold bias)
                mismatch_cold = False
                market_imp = meta.get("market_implied", {})
                poisson_1x2 = meta.get("poisson_1x2", {})
                if market_imp and poisson_1x2:
                    po_h = poisson_1x2.get("h", 0)
                    mi_h = market_imp.get("h", 0)
                    # Model strongly underrates the favorite → cold/underdog bias
                    if mi_h > 0.70 and po_h < mi_h - 0.10:
                        mismatch_cold = True
                
                # EV discount for mismatch games: scale down cold-outcome EV
                # by a factor proportional to how much the model underrates the favorite
                ev_discount = 1.0
                if mismatch_cold and market_imp and poisson_1x2:
                    po_h = poisson_1x2.get("h", 0)
                    mi_h = market_imp.get("h", 0)
                    # discount = (1 - gap)^2, gap = mi_h - po_h
                    # e.g. gap=0.25 → discount=0.56 (EV nearly halved)
                    gap = mi_h - po_h
                    ev_discount = max(0.10, (1.0 - gap) ** 3)
                    # Apply discount to EV and EV_cal
                    ev *= ev_discount
                    ev_c *= ev_discount
                    kelly = _kelly(p_c * ev_discount, price_f)
                
                # Re-check EV threshold after discount
                if ev_c <= EV_THRESHOLD:
                    continue
                # Extreme longshot → auto-flag as manual_review (odds > 25 = hit rate < 4%)
                is_longshot = (price_f > MAX_ODDS_AUTO)
                
                # Manual review if inconsistent OR cold mismatch OR extreme longshot.
                # Draw quality checks (6/25 backtest: all draws lost when p<25%):
                # - p_model < 25% → auto-review (model too uncertain)
                # - model #1 pick != D → model prefers another outcome (weak signal)
                is_manual = (inconsistent and key != "D") or mismatch_cold or is_longshot
                # Draw-specific quality filter
                if pool == "had" and key == "D":
                    if p < 0.25:
                        is_manual = True
                        reasons.append(f"low_draw_p({p:.0%})")
                    if poisson_1x2:
                        po_h_d = poisson_1x2.get("h", 0)
                        po_d_d = poisson_1x2.get("d", 0)
                        po_a_d = poisson_1x2.get("a", 0)
                        if po_d_d <= po_h_d or po_d_d <= po_a_d:
                            is_manual = True
                            reasons.append("draw_not_top_pick")
                reasons = []
                if inconsistent:
                    reasons.append(f"elo_poisson_gap={elo_gap:.1%}" if elo_gap is not None else "inconsistent")
                if mismatch_cold:
                    reasons.append(f"mismatch_cold(gap={mi_h-po_h:.0%})" if (market_imp and poisson_1x2) else "mismatch_cold")
                if is_longshot:
                    reasons.append(f"longshot(odds={price_f:.0f})")
                
                opportunities.append({
                    "match": f"{home_en} vs {away_en}",
                    "match_cn": f"{r.get('home_cn','')} vs {r.get('away_cn','')}",
                    "home_en": home_en,
                    "away_en": away_en,
                    "date": date,
                    "group": group,
                    "pool_code": pool,
                    "pool_name": POOL_NAMES_CN.get(pool, pool),
                    "pool_priority": POOL_PRIORITY.get(pool, 9),
                    "selection": key,
                    "selection_cn": _selection_cn(pool, key),
                    "handicap": handicap if pool == "hhad" else None,
                    "offered_keys": list(odds.keys()),
                    "odds": round(price_f, 3),
                    "p_model": round(p, 5),
                    "p_model_calibrated": round(p_c, 5),
                    "p_implied": round(1.0 / price_f * SPORTTERY_RETURN_RATE, 5),
                    "ev": round(ev, 5),
                    "ev_calibrated": round(ev_c, 5),
                    "vig_cost": vig,
                    "cross_conf": cross_conf,
                    "elo_poisson_gap": round(elo_gap, 4) if elo_gap is not None else None,
                    "manual_review": is_manual,
                    "manual_review_reason": "; ".join(reasons) if reasons else "",
                    "mismatch_cold": mismatch_cold,
                    "ev_discount": round(ev_discount, 4),
                    "kelly_stake": round(kelly, 4),
                    "recommended_stake": round(kelly, 4),
                    "stake_note": f"EV打折{ev_discount:.0%}" if ev_discount < 1.0 else "",
                })

    by_pool: dict[str, int] = defaultdict(int)
    for op in opportunities:
        by_pool[op["pool_code"]] += 1
    total_stake = sum(op["recommended_stake"] for op in opportunities)
    # Total EV = Σ (p_model * odds - 1) * stake  = Σ ev * stake
    total_ev = sum(op["ev"] * op["recommended_stake"] for op in opportunities)
    total_ev_cal = sum(op.get("ev_calibrated", op["ev"]) * op["recommended_stake"]
                       for op in opportunities)
    n_manual = sum(1 for op in opportunities if op.get("manual_review"))
    n_auto = len(opportunities) - n_manual

    out = {
        "as_of": _now_iso(),
        "return_rate_estimated": SPORTTERY_RETURN_RATE,
        "kelly_half": KELLY_HALF,
        "single_bet_cap": SINGLE_BET_CAP,
        "daily_cap": DAILY_CAP,
        "calibrated": calibrated,
        "use_xg": use_xg,
        "xg_coverage": xg_cov,
        "draw_inflate": model.params.draw_inflate,
        "deflate_away": model.params.deflate_away,
        "matches_scanned": matches_scanned,
        "matches_skipped_unmatched": len(skipped_unmatched),
        "opportunities": opportunities,
        "summary": {
            "by_pool": dict(by_pool),
            "total_opportunities": len(opportunities),
            "auto_review": n_auto,
            "manual_review": n_manual,
            "total_stake": round(total_stake, 4),
            "total_ev": round(total_ev, 5),
            "total_ev_calibrated": round(total_ev_cal, 5),
        },
        "skipped_unmatched": skipped_unmatched[:20],  # cap for output size
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False),
                        encoding="utf-8")

    # Auto-archive current cache to history DB (no-op if unchanged)
    try:
        SportteryDB().import_from_cache()
    except Exception:
        pass

    return out


def print_summary(out: dict) -> None:
    s = out["summary"]
    cal = out.get("calibrated", False)
    print(f"=== Sporttery EV scan ({out['matches_scanned']} matches scanned) ===")
    print(f"return rate ~{out['return_rate_estimated']:.0%}  "
          f"Kelly=1/{int(1/out['kelly_half'])}  "
          f"single cap={out['single_bet_cap']:.0%}  daily cap={out['daily_cap']:.0%}")
    if cal:
        print(f"calibration: draw_inflate={out.get('draw_inflate',1.0):.3f} "
              f"deflate_away={out.get('deflate_away',1.0):.3f} + Platt")
    if out.get("use_xg"):
        cov = out.get("xg_coverage", {})
        print(f"xG fit: enabled ({cov.get('with_xg',0)}/{cov.get('total',0)} = "
              f"{cov.get('pct',0.0)}% coverage)")
    else:
        print(f"xG fit: disabled (run fetch_xg to enable)")
    print()
    by_pool = "  ".join(f"{k}={v}" for k, v in s["by_pool"].items())
    print(f"opportunities: {s['total_opportunities']}  ({by_pool})")
    n_manual = s.get("manual_review", 0)
    n_auto = s.get("auto_review", s["total_opportunities"])
    if n_manual:
        print(f"  auto: {n_auto}  manual_review: {n_manual} (elo_poisson_gap > {ELO_POISSON_GAP_THRESHOLD:.0%})")
    print(f"total stake: {s['total_stake']:.1%}  "
          f"total EV: {s['total_ev']:+.4f}  "
          f"calibrated EV: {s.get('total_ev_calibrated', s['total_ev']):+.4f}")
    if out.get("matches_skipped_unmatched"):
        print(f"\n[warn] {out['matches_skipped_unmatched']} match-pool rows skipped "
              f"(team name not in model)")
    print()
    # Show top 15 by calibrated EV.
    top = sorted(out["opportunities"],
                 key=lambda x: -x.get("ev_calibrated", x["ev"]))[:15]
    if top:
        print(f"{'match':28s} pool sel     odds  p_mod p_cal  EV_cal  stake  review")
        for op in top:
            sel = op["selection"]
            if op["pool_code"] == "crs" and sel.startswith("("):
                sel = sel.strip("()").replace(",", ":")
            pc = op.get("p_model_calibrated", op["p_model"])
            flag = "MANUAL" if op.get("manual_review") else ""
            print(f"{op['match'][:28]:28s} {op['pool_code']:4s} "
                  f"{sel:7s} {op['odds']:5.2f} {op['p_model']:.3f} {pc:.3f}  "
                  f"{op.get('ev_calibrated', op['ev']):+.1%}  {op['recommended_stake']:.1%}  {flag}")


if __name__ == "__main__":
    out = run()
    print_summary(out)
    print(f"\n→ {OUT_FILE}")
