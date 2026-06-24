"""Portfolio optimization for sporttery (体彩) EV scan results.

Extends P6's mean-variance optimization to the sporttery channel. The key
insight: bets across different pool types (had/hhad/crs/ttg) on the **same
match** are correlated through the shared score outcome. The scanner's naive
daily-cap truncation ignores this correlation; the optimizer accounts for it.

Same-match covariance (from score probability matrix P):
  For bets i, j on match M:
    win_i = boolean mask (n×n) where bet i wins
    P(both win) = Σ P[h,a] for (h,a) in win_i ∩ win_j
    Cov[return_i, return_j] = odds_i × odds_j × (P(both) - p_i × p_j)

  Diagonal: Var[return_i] = odds_i² × p_i × (1 - p_i)

Different-match covariance ≈ 0 (Poisson independence, same assumption as P5).

Optimization (SLSQP):
  maximize  Σ EV_calibrated_i × x_i
  subject to:
    0 ≤ x_i ≤ SINGLE_BET_CAP      (3%)
    Σ_{date d} x_i ≤ DAILY_CAP    (15%)
    x^T Σ x ≤ σ²_target           (0.02, std ≤ 14.1%)

Research only. No real betting.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

import importlib, sys
if "wc_betting.models.poisson" in sys.modules:
    importlib.reload(sys.modules["wc_betting.models.poisson"])
from wc_betting.models.poisson import (PoissonModel, score_matrix,
                                       host_rho, RHO_NEUTRAL,
                                       is_cross_confederation)
from wc_betting.data.fetch_xg import load_historical_with_xg

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCANNER_FILE = PROJECT_ROOT / "output/wc_sporttery_opportunities.json"
OUT_FILE = PROJECT_ROOT / "output/wc_sporttery_portfolio.json"
CALIBRATION_FILE = PROJECT_ROOT / "data/processed/calibration_params.json"

SINGLE_BET_CAP = 0.03
DAILY_CAP = 0.15
SIGMA2_TARGET = 0.02  # portfolio variance cap (~14.1% std)
MAX_GOALS = 10  # matches poisson.MAX_GOALS

# hhad sign convention (must match sporttery_scanner.HANDICAP_SIGN).
HANDICAP_SIGN = 1.0


# ---- Win masks -----------------------------------------------------------

def compute_win_mask(pool: str, key: str, handicap: float | None,
                     offered_keys: list[str] | None = None,
                     n: int = MAX_GOALS) -> np.ndarray:
    """Boolean n×n mask where True means this bet wins.

    For crs "其他" (H_OTHER/D_OTHER/A_OTHER), `offered_keys` is needed to
    determine which specific scores are listed (and thus excluded from the
    "other" bucket).
    """
    mask = np.zeros((n, n), dtype=bool)

    if pool == "had":
        if key == "H":
            for i in range(n):
                for j in range(i):
                    mask[i, j] = True
        elif key == "D":
            for i in range(n):
                mask[i, i] = True
        elif key == "A":
            for j in range(n):
                for i in range(j):
                    mask[i, j] = True

    elif pool == "hhad":
        g = HANDICAP_SIGN * float(handicap or 0.0)
        for i in range(n):
            for j in range(n):
                vh = i + g
                if key == "H" and vh > j:
                    mask[i, j] = True
                elif key == "D" and vh == j:
                    mask[i, j] = True
                elif key == "A" and vh < j:
                    mask[i, j] = True

    elif pool == "crs":
        if key in ("H_OTHER", "D_OTHER", "A_OTHER"):
            # Determine which specific score cells are listed.
            listed: set[tuple[int, int]] = set()
            for k in (offered_keys or []):
                if k in ("H_OTHER", "D_OTHER", "A_OTHER"):
                    continue
                parts = k.strip("()").split(",")
                if len(parts) == 2:
                    try:
                        listed.add((int(parts[0]), int(parts[1])))
                    except ValueError:
                        pass
            for i in range(n):
                for j in range(n):
                    if (i, j) in listed:
                        continue
                    if key == "H_OTHER" and i > j:
                        mask[i, j] = True
                    elif key == "D_OTHER" and i == j:
                        mask[i, j] = True
                    elif key == "A_OTHER" and i < j:
                        mask[i, j] = True
        else:
            parts = key.strip("()").split(",")
            if len(parts) == 2:
                try:
                    h, a = int(parts[0]), int(parts[1])
                    if 0 <= h < n and 0 <= a < n:
                        mask[h, a] = True
                except ValueError:
                    pass

    elif pool == "ttg":
        try:
            k = int(key)
        except ValueError:
            return mask
        if k >= 7:  # "7+" bucket
            for i in range(n):
                for j in range(n):
                    if i + j >= 7:
                        mask[i, j] = True
        elif 0 <= k <= 6:
            for i in range(n):
                for j in range(n):
                    if i + j == k:
                        mask[i, j] = True

    return mask


# ---- Covariance ----------------------------------------------------------

def _same_match_covariance(bets: list[dict],
                           matrix: np.ndarray) -> np.ndarray:
    """Covariance matrix for bets on the same match.

    Uses the score probability matrix to compute joint win probabilities.
    """
    n_bets = len(bets)
    masks = []
    probs = []
    for b in bets:
        m = compute_win_mask(b["pool_code"], b["selection"],
                             b.get("handicap"), b.get("offered_keys"))
        masks.append(m)
        probs.append(float(matrix[m].sum()))

    odds = [b["odds"] for b in bets]
    cov = np.zeros((n_bets, n_bets))
    for i in range(n_bets):
        for j in range(n_bets):
            p_both = float(matrix[masks[i] & masks[j]].sum())
            cov[i, j] = odds[i] * odds[j] * (p_both - probs[i] * probs[j])
    return cov


def build_covariance(opportunities: list[dict],
                     matrices: dict[tuple[str, str], np.ndarray]) -> np.ndarray:
    """Full n×n covariance matrix. Block-diagonal: one block per match.

    `matrices` maps (home_en, away_en) → score probability matrix.
    """
    n = len(opportunities)
    cov = np.zeros((n, n))

    # Group opportunity indices by match.
    by_match: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, op in enumerate(opportunities):
        key = (op.get("home_en", ""), op.get("away_en", ""))
        by_match[key].append(i)

    for (home, away), indices in by_match.items():
        matrix = matrices.get((home, away))
        if matrix is None:
            # No matrix available — use diagonal-only (independent) fallback
            # with calibrated probability (best available estimate).
            for i in indices:
                p = opportunities[i].get("p_model_calibrated",
                                         opportunities[i]["p_model"])
                o = opportunities[i]["odds"]
                cov[i, i] = o * o * p * (1.0 - p)
            continue

        # Always use _same_match_covariance for consistency: it computes
        # probabilities from the score matrix (raw model belief), which is
        # correct for the covariance structure. Platt calibration only affects
        # EV, not the joint score distribution.
        bets = [opportunities[i] for i in indices]
        local_cov = _same_match_covariance(bets, matrix)
        for a, i in enumerate(indices):
            for b, j in enumerate(indices):
                cov[i, j] = local_cov[a, b]

    return cov


# ---- Optimization --------------------------------------------------------

def _daily_cap_constraints(bets: list[dict], daily_cap: float):
    dates = sorted({b["date"] for b in bets})
    constraints = []
    for d in dates:
        mask = np.array([1.0 if b["date"] == d else 0.0 for b in bets])
        constraints.append({
            "type": "ineq",
            "fun": lambda x, m=mask, dc=daily_cap: dc - m @ x,
            "jac": lambda x, m=mask: -m,
        })
    return constraints


def _variance_constraint(cov: np.ndarray, sigma2: float):
    return {
        "type": "ineq",
        "fun": lambda x: sigma2 - x @ cov @ x,
        "jac": lambda x: -2.0 * cov @ x,
    }


def optimize(opportunities: list[dict], cov: np.ndarray,
             sigma2: float = SIGMA2_TARGET) -> np.ndarray:
    """SLSQP: maximize Σ EV_calibrated × x_i subject to caps + variance."""
    n = len(opportunities)
    if n == 0:
        return np.array([])

    evs = np.array([op.get("ev_calibrated", op["ev"]) for op in opportunities])

    constraints = _daily_cap_constraints(opportunities, DAILY_CAP)
    constraints.append(_variance_constraint(cov, sigma2))

    bounds = [(0.0, SINGLE_BET_CAP)] * n
    # Initial guess: Kelly stake (already capped at SINGLE_BET_CAP by scanner).
    x0 = np.array([min(op.get("kelly_stake", 0.0), SINGLE_BET_CAP)
                   for op in opportunities])

    result = minimize(
        fun=lambda x: -evs @ x,
        x0=x0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        jac=lambda x: -evs,
        options={"maxiter": 500, "ftol": 1e-9},
    )

    if not result.success:
        print(f"WARNING: SLSQP did not converge: {result.message}", file=sys.stderr)
    return result.x


# ---- Main pipeline -------------------------------------------------------

def _load_score_matrices(opportunities: list[dict]):
    """Load Poisson model + compute score matrix for each unique match.

    Returns (matrices_dict, model_info_dict).
    """
    matches_xg = load_historical_with_xg()
    use_xg = matches_xg is not None
    model = PoissonModel.fit(matches=matches_xg, use_xg=use_xg, competitive_only=True)
    # Override draw_inflate / deflate_away with OOS-calibrated values from
    # calibration_params.json meta (P12 fix — same as sporttery_scanner).
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

    # Load match lookup for group/date.
    mi = json.loads((PROJECT_ROOT / "data/processed/wc_2026_model_input.json")
                    .read_text(encoding="utf-8"))
    match_lookup: dict[tuple[str, str], dict] = {}
    for m in mi["matches"]:
        match_lookup[(m["home"], m["away"])] = {"group": m["group"],
                                                 "date": m["date"]}

    matrices: dict[tuple[str, str], np.ndarray] = {}
    seen: set[tuple[str, str]] = set()
    for op in opportunities:
        home = op.get("home_en", "")
        away = op.get("away_en", "")
        key = (home, away)
        if key in seen or not home or not away:
            continue
        seen.add(key)
        hc = model.name_to_code.get(home)
        ac = model.name_to_code.get(away)
        if hc is None or ac is None:
            continue
        rho = host_rho(model.params, home)
        cross_conf = is_cross_confederation(home, away)
        if rho == RHO_NEUTRAL:
            cross_conf = False
        matrices[key] = score_matrix(model.params, hc, ac, rho=rho,
                                     max_goals=MAX_GOALS,
                                     cross_conf=cross_conf)

    info = {
        "draw_inflate": model.params.draw_inflate,
        "deflate_away": model.params.deflate_away,
        "use_xg": use_xg,
    }
    return matrices, info


def run(scanner_path: Path = SCANNER_FILE, out_path: Path = OUT_FILE) -> dict:
    """Load scanner output, build covariance, optimize stakes, write result."""
    data = json.loads(scanner_path.read_text(encoding="utf-8"))
    opportunities = data.get("opportunities", [])
    if not opportunities:
        print("[sporttery_portfolio] No opportunities in scanner output.")
        return {"error": "no_opportunities", "opportunities": []}

    # Only optimize bets with positive calibrated EV and nonzero Kelly stake.
    # Exclude manual_review (elo_poisson_gap > 8%) — model is unreliable for
    # these matches and should not enter automatic portfolio optimization.
    candidates = [op for op in opportunities
                  if op.get("ev_calibrated", op["ev"]) > 0
                  and op.get("kelly_stake", 0) > 0
                  and not op.get("manual_review", False)]
    n_excluded = sum(1 for op in opportunities
                     if op.get("ev_calibrated", op["ev"]) > 0
                     and op.get("kelly_stake", 0) > 0
                     and op.get("manual_review", False))

    if not candidates:
        print("[sporttery_portfolio] No positive-EV candidates to optimize.")
        return {"error": "no_candidates", "opportunities": opportunities}

    print(f"[sporttery_portfolio] Optimizing {len(candidates)} candidates "
          f"across {len({(op.get('home_en',''), op.get('away_en','')) for op in candidates})} matches...")
    if n_excluded:
        print(f"[sporttery_portfolio] {n_excluded} opportunities excluded (manual_review: elo_poisson_gap > 8%)")

    matrices, model_info = _load_score_matrices(candidates)
    cov = build_covariance(candidates, matrices)

    # Kelly solution statistics (for comparison).
    kelly_x = np.array([min(op.get("kelly_stake", 0.0), SINGLE_BET_CAP)
                        for op in candidates])
    kelly_var = float(kelly_x @ cov @ kelly_x) if len(candidates) > 0 else 0.0
    evs = np.array([op.get("ev_calibrated", op["ev"]) for op in candidates])
    kelly_ev = float(evs @ kelly_x) if len(candidates) > 0 else 0.0

    # SLSQP optimized stakes.
    opt_x = optimize(candidates, cov, SIGMA2_TARGET)
    opt_var = float(opt_x @ cov @ opt_x) if len(candidates) > 0 else 0.0
    opt_ev = float(evs @ opt_x) if len(candidates) > 0 else 0.0

    # Build output: merge optimized stakes back into full opportunity list.
    opt_map: dict[int, float] = {}
    for i, op in enumerate(candidates):
        # Find index in original list.
        orig_idx = opportunities.index(op)
        opt_map[orig_idx] = float(opt_x[i])

    final_ops = []
    for i, op in enumerate(opportunities):
        op = dict(op)
        if i in opt_map:
            stake = opt_map[i]
            op["optimal_stake"] = round(stake, 4)
            op["recommended_stake"] = round(stake, 4)
            op["stake_note"] = "portfolio-optimized"
        else:
            op["optimal_stake"] = 0.0
            op["stake_note"] = op.get("stake_note", "") or "filtered (EV<=0 or no Kelly)"
        final_ops.append(op)

    # Same-match correlation summary.
    by_match: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for op in candidates:
        key = (op.get("home_en", ""), op.get("away_en", ""))
        by_match[key].append(op)
    corr_summary = []
    for (home, away), bets in by_match.items():
        if len(bets) < 2:
            continue
        # Average off-diagonal correlation.
        n_bets = len(bets)
        indices = [candidates.index(b) for b in bets]
        local_cov = cov[np.ix_(indices, indices)]
        stds = np.sqrt(np.diag(local_cov))
        corrs = []
        for a in range(n_bets):
            for b in range(a + 1, n_bets):
                if stds[a] > 0 and stds[b] > 0:
                    corrs.append(local_cov[a, b] / (stds[a] * stds[b]))
        avg_corr = float(np.mean(corrs)) if corrs else 0.0
        corr_summary.append({
            "match": bets[0]["match"],
            "n_bets": n_bets,
            "avg_correlation": round(avg_corr, 4),
            "pools": [b["pool_code"] for b in bets],
        })

    # Daily summary.
    dates = sorted({op["date"] for op in candidates if op.get("date")})
    daily = []
    for d in dates:
        day_ops = [op for op in final_ops if op.get("date") == d and op.get("optimal_stake", 0) > 0]
        daily.append({
            "date": d,
            "n_bets": len(day_ops),
            "total_stake": round(sum(op["optimal_stake"] for op in day_ops), 4),
            "total_ev": round(sum(op.get("ev_calibrated", op["ev"]) * op["optimal_stake"]
                                  for op in day_ops), 5),
        })

    out = {
        "as_of": data.get("as_of"),
        "source": str(scanner_path),
        "model_info": model_info,
        "risk_params": {
            "single_bet_cap": SINGLE_BET_CAP,
            "daily_cap": DAILY_CAP,
            "sigma2_target": SIGMA2_TARGET,
        },
        "optimization": {
            "method": "SLSQP",
            "n_candidates": len(candidates),
            "kelly_portfolio_variance": round(kelly_var, 6),
            "kelly_portfolio_std": round(kelly_var ** 0.5, 4),
            "optimal_portfolio_variance": round(opt_var, 6),
            "optimal_portfolio_std": round(opt_var ** 0.5, 4),
            "kelly_total_ev": round(kelly_ev, 6),
            "optimal_total_ev": round(opt_ev, 6),
            "variance_constraint_binding": kelly_var > SIGMA2_TARGET,
            "ev_reduction_pct": round((1 - opt_ev / max(kelly_ev, 1e-9)) * 100, 1)
                                if kelly_ev > 0 else 0.0,
            "variance_reduction_pct": round((1 - opt_var / max(kelly_var, 1e-9)) * 100, 1)
                                      if kelly_var > 0 else 0.0,
        },
        "same_match_correlations": corr_summary,
        "daily_summary": daily,
        "summary": {
            "total_opportunities": len(opportunities),
            "total_optimized": sum(1 for op in final_ops if op.get("optimal_stake", 0) > 0.001),
            "total_stake": round(sum(op.get("optimal_stake", 0) for op in final_ops), 4),
            "total_ev": round(sum(op.get("ev_calibrated", op["ev"]) * op.get("optimal_stake", 0)
                                   for op in final_ops), 5),
        },
        "opportunities": final_ops,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    _print_results(out)
    return out


def _print_results(out: dict) -> None:
    opt = out["optimization"]
    print("=== Sporttery Portfolio Optimization (SLSQP) ===")
    print(f"risk: cap={SINGLE_BET_CAP:.0%}  daily={DAILY_CAP:.0%}  "
          f"σ²≤{SIGMA2_TARGET} (std≤{SIGMA2_TARGET**0.5:.1%})")
    print()
    print(f"candidates: {opt['n_candidates']}")
    print(f"Kelly:    EV={opt['kelly_total_ev']:+.4f}  "
          f"var={opt['kelly_portfolio_variance']:.6f}  "
          f"std={opt['kelly_portfolio_std']:.1%}")
    print(f"Optimized: EV={opt['optimal_total_ev']:+.4f}  "
          f"var={opt['optimal_portfolio_variance']:.6f}  "
          f"std={opt['optimal_portfolio_std']:.1%}")
    binding = "YES" if opt["variance_constraint_binding"] else "NO"
    print(f"variance constraint binding: {binding}")
    print(f"EV reduction: {opt['ev_reduction_pct']:.1f}%  "
          f"variance reduction: {opt['variance_reduction_pct']:.1f}%")
    print()

    # Same-match correlations.
    corr = out.get("same_match_correlations", [])
    if corr:
        print("--- Same-match correlations ---")
        for c in corr:
            print(f"  {c['match'][:36]:36s} {c['n_bets']} bets  "
                  f"avg_corr={c['avg_correlation']:+.3f}  "
                  f"pools={','.join(c['pools'])}")
        print()

    # Top bets by optimal stake.
    top = sorted([op for op in out["opportunities"]
                  if op.get("optimal_stake", 0) > 0.001],
                 key=lambda x: -x["optimal_stake"])[:15]
    if top:
        print(f"{'match':28s} pool sel     odds  EV_cal  kelly  opt   note")
        for op in top:
            sel = op["selection"]
            if op["pool_code"] == "crs" and sel.startswith("("):
                sel = sel.strip("()").replace(",", ":")
            print(f"{op['match'][:28]:28s} {op['pool_code']:4s} "
                  f"{sel:7s} {op['odds']:5.2f}  "
                  f"{op.get('ev_calibrated', op['ev']):+5.1%}  "
                  f"{op.get('kelly_stake',0):.3f}  "
                  f"{op['optimal_stake']:.3f}")
    print()
    s = out["summary"]
    print(f"total: {s['total_optimized']} bets, "
          f"stake={s['total_stake']:.1%}, EV={s['total_ev']:+.4f}")
    print(f"output: {OUT_FILE}")


if __name__ == "__main__":
    run()
