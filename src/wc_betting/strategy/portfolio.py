"""Portfolio optimization + risk control (plan §6.3, §7).

Mean-variance optimization via SLSQP:
  maximize  Σ EV_i × x_i          (total expected value)
  subject to:
    0 ≤ x_i ≤ SINGLE_BET_CAP      (3%, tightened from plan's 5%)
    Σ_{date d} x_i ≤ DAILY_CAP    (15% per day)
    x^T Σ x ≤ σ²_target           (variance constraint)

Covariance matrix Σ from P5 Monte Carlo. Under Poisson independence,
off-diagonal terms ≈ 0, so the variance constraint mainly limits
high-odds (high-variance) bets.

Risk control rules (§7):
  - Model inconsistency / high dispersion → already filtered in P4
  - Drawdown stop (20% peak) → operational rule, documented
  - Consecutive losses (6) → operational rule, documented
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

PROJECT_ROOT = Path(__file__).resolve().parents[3]
VALUE_FILE = PROJECT_ROOT / "output/wc_value_opportunities.json"
CORR_FILE = PROJECT_ROOT / "output/wc_correlation_analysis.json"
OUT_FILE = PROJECT_ROOT / "output/wc_final_bets.json"

SINGLE_BET_CAP = 0.03    # tightened from plan's 0.05
DAILY_CAP = 0.15
SIGMA2_TARGET = 0.02     # portfolio variance cap (~14% std dev)


def _bet_variance(p: float, odds: float) -> float:
    """Variance of return per unit stake: odds² × p × (1-p)."""
    return odds * odds * p * (1.0 - p)


def _bet_prob(b: dict) -> float:
    """Best available probability for bet b (calibrated preferred)."""
    return b.get("p_model_calibrated", b["p_model"])


def _bet_ev(b: dict) -> float:
    """Best available EV for bet b (calibrated preferred)."""
    return b.get("ev_calibrated", b["ev"])


def _build_covariance(bets: list[dict], corr_data: dict) -> np.ndarray:
    """Build n×n covariance matrix for bet returns.

    Diagonal: odds² × p × (1-p) per bet (uses calibrated p if available).
    Off-diagonal: odds_i × odds_j × Cov[b_i, b_j] for same-group pairs
    (from Monte Carlo), 0 otherwise.
    """
    n = len(bets)
    cov = np.zeros((n, n))

    for i in range(n):
        cov[i, i] = _bet_variance(_bet_prob(bets[i]), bets[i]["odds"])

    # Map same-group pairs to bet indices.
    match_to_idx = {b["match"]: i for i, b in enumerate(bets)}
    for g in corr_data.get("groups", []):
        matches = g["matches"]
        if len(matches) != 2:
            continue
        i = match_to_idx.get(matches[0])
        j = match_to_idx.get(matches[1])
        if i is None or j is None:
            continue
        bet_cov = g.get("bet_covariance")
        if bet_cov is None:
            continue
        # Cov[return_i, return_j] = odds_i × odds_j × Cov[indicator_i, indicator_j]
        oi, oj = bets[i]["odds"], bets[j]["odds"]
        cov[i, j] = oi * oj * bet_cov
        cov[j, i] = cov[i, j]

    return cov


def _daily_cap_constraints(bets: list[dict], daily_cap: float):
    """Build linear inequality constraints: Σ_{date d} x_i ≤ daily_cap."""
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
    """x^T Σ x ≤ σ²_target  →  σ² - x^T Σ x ≥ 0."""
    return {
        "type": "ineq",
        "fun": lambda x: sigma2 - x @ cov @ x,
        "jac": lambda x: -2.0 * cov @ x,
    }


def optimize(bets: list[dict], cov: np.ndarray,
             sigma2: float = SIGMA2_TARGET) -> np.ndarray:
    """SLSQP: maximize Σ EV_calibrated_i × x_i subject to caps + variance."""
    n = len(bets)
    evs = np.array([_bet_ev(b) for b in bets])

    constraints = _daily_cap_constraints(bets, DAILY_CAP)
    constraints.append(_variance_constraint(cov, sigma2))

    bounds = [(0.0, SINGLE_BET_CAP)] * n
    x0 = np.array([min(b["kelly_fraction"], SINGLE_BET_CAP) for b in bets])

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
        print(f"WARNING: SLSQP did not converge: {result.message}")
    return result.x


def run(verbose: bool = True) -> dict:
    value_data = json.loads(VALUE_FILE.read_text(encoding="utf-8"))
    corr_data = json.loads(CORR_FILE.read_text(encoding="utf-8"))

    bets = [r for r in value_data["opportunities"] if r["status"] == "bet"]
    n = len(bets)

    cov = _build_covariance(bets, corr_data)

    # Kelly solution variance (for reference).
    kelly_x = np.array([min(b["kelly_fraction"], SINGLE_BET_CAP) for b in bets])
    kelly_var = float(kelly_x @ cov @ kelly_x)

    # SLSQP optimized stakes.
    opt_x = optimize(bets, cov, SIGMA2_TARGET)
    opt_var = float(opt_x @ cov @ opt_x)
    evs = np.array([_bet_ev(b) for b in bets])
    opt_ev = float(evs @ opt_x)
    kelly_ev = float(evs @ kelly_x)

    # Build final bet table.
    final_bets = []
    for i, b in enumerate(bets):
        fb = dict(b)
        fb["optimal_stake"] = round(float(opt_x[i]), 4)
        fb["kelly_stake"] = round(float(kelly_x[i]), 4)
        fb["stake"] = fb["optimal_stake"]
        fb["bet_variance"] = round(float(cov[i, i]), 4)
        fb["status"] = "bet" if opt_x[i] > 0.001 else "skip_zero"
        final_bets.append(fb)

    # Sort by date then calibrated EV.
    final_bets.sort(key=lambda x: (x["date"], -_bet_ev(x)))

    # Daily summary.
    dates = sorted({b["date"] for b in bets})
    daily = []
    for d in dates:
        day_bets = [b for b in final_bets if b["date"] == d]
        daily.append({
            "date": d,
            "n_bets": len(day_bets),
            "total_stake": round(sum(b["optimal_stake"] for b in day_bets), 4),
            "total_ev": round(sum(_bet_ev(b) * b["optimal_stake"] for b in day_bets), 4),
        })

    out = {
        "as_of": value_data.get("as_of"),
        "calibrated": value_data.get("calibrated", False),
        "risk_params": {
            "single_bet_cap": SINGLE_BET_CAP,
            "daily_cap": DAILY_CAP,
            "sigma2_target": SIGMA2_TARGET,
            "kelly_fraction": 0.5,
        },
        "optimization": {
            "method": "SLSQP",
            "kelly_portfolio_variance": round(kelly_var, 6),
            "kelly_portfolio_std": round(kelly_var ** 0.5, 4),
            "optimal_portfolio_variance": round(opt_var, 6),
            "optimal_portfolio_std": round(opt_var ** 0.5, 4),
            "kelly_total_ev": round(kelly_ev, 6),
            "optimal_total_ev": round(opt_ev, 6),
            "variance_constraint_binding": kelly_var > SIGMA2_TARGET,
        },
        "risk_rules": {
            "single_bet_cap": f"{SINGLE_BET_CAP:.0%} — enforced in optimizer",
            "daily_cap": f"{DAILY_CAP:.0%} — enforced in optimizer",
            "variance_cap": f"σ² ≤ {SIGMA2_TARGET} (std ≤ {SIGMA2_TARGET**0.5:.1%}) — enforced in optimizer",
            "drawdown_stop": "20% peak drawdown → pause 1 round (operational, manual)",
            "consecutive_losses": "6 consecutive losses → pause, calibration check (operational, manual)",
            "model_inconsistency": "Elo-Poisson gap >8% → manual review (applied in P4)",
            "high_dispersion": "p_h_std >3% → manual review (applied in P4)",
        },
        "daily_summary": daily,
        "final_bets": final_bets,
        "n_bets": sum(1 for b in final_bets if b["status"] == "bet"),
        "total_stake": round(sum(b["optimal_stake"] for b in final_bets), 4),
        "total_ev": round(sum(_bet_ev(b) * b["optimal_stake"] for b in final_bets), 6),
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    if verbose:
        _print_results(out, kelly_var, opt_var, kelly_ev, opt_ev)

    return out


def _print_results(out: dict, kelly_var: float, opt_var: float,
                   kelly_ev: float, opt_ev: float) -> None:
    print("=== Portfolio Optimization (SLSQP) ===")
    print(f"risk: cap={SINGLE_BET_CAP:.0%}  daily={DAILY_CAP:.0%}  σ²≤{SIGMA2_TARGET} (std≤{SIGMA2_TARGET**0.5:.1%})")
    print()
    print(f"Kelly solution:    EV={kelly_ev:+.4f}  var={kelly_var:.6f}  std={kelly_var**0.5:.1%}")
    print(f"Optimized solution: EV={opt_ev:+.4f}  var={opt_var:.6f}  std={opt_var**0.5:.1%}")
    binding = "YES" if kelly_var > SIGMA2_TARGET else "NO"
    print(f"variance constraint binding: {binding}")
    print()

    print("--- Final Bet Recommendations ---")
    print(f"{'date':10s} {'grp':3s} {'match':34s} {'sel':3s} {'p_cal':5s} {'odds':5s} {'EVcal':6s} "
          f"{'kelly':5s} {'opt':5s} {'var':7s}")
    for b in out["final_bets"]:
        pc = b.get("p_model_calibrated", b["p_model"])
        evc = _bet_ev(b)
        print(f"{b['date']:10s} {b['group']:3s} {b['match'][:34]:34s} {b['selection']:3s} "
              f"{pc:.3f} {b['odds']:5.2f} {evc:+5.1%} "
              f"{b['kelly_stake']:.3f} {b['optimal_stake']:.3f} {b['bet_variance']:7.2f}")

    print()
    print("--- Daily Summary ---")
    for d in out["daily_summary"]:
        print(f"  {d['date']}: {d['n_bets']} bets, stake={d['total_stake']:.1%}, EV={d['total_ev']:+.4f}")

    print()
    print(f"total: {out['n_bets']} bets, stake={out['total_stake']:.1%}, EV={out['total_ev']:+.4f}")
    print(f"output: {OUT_FILE}")


if __name__ == "__main__":
    run()
