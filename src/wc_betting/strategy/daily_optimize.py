"""Per-day bet combination analysis + optimization + hedging detection.

Compares three approaches:
  A. Global optimization (P6, σ²≤0.02 across all 12 bets)
  B. Per-day Kelly (1/2 Kelly, only single-bet 3% + daily 15% caps, no variance constraint)
  C. Per-day SLSQP (single-bet 3% + daily 15% + per-day σ cap)

Also identifies same-group same-day bet pairs (3rd-round hedging opportunities).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FINAL_BETS_FILE = PROJECT_ROOT / "output" / "wc_final_bets.json"
CORR_FILE = PROJECT_ROOT / "output" / "wc_correlation_analysis.json"
OUTPUT_FILE = PROJECT_ROOT / "output" / "wc_daily_analysis.json"

SINGLE_BET_CAP = 0.03
DAILY_CAP = 0.15
# Per-day sigma caps to evaluate
SIGMA_CAPS = [0.06, 0.08, 0.10, 0.12]


def _bet_var(b: dict) -> float:
    return b.get("bet_variance", b["p_model"] * (1 - b["p_model"]) * (b["odds"] - 1) ** 2)


def _day_ev_var(stakes: np.ndarray, day_bets: list[dict]) -> tuple[float, float]:
    ev = float(sum(s * b["ev"] for s, b in zip(stakes, day_bets)))
    var = float(sum(s**2 * _bet_var(b) for s, b in zip(stakes, day_bets)))
    return ev, var


def _optimize_day(day_bets: list[dict], sigma2_target: float | None = None) -> np.ndarray:
    """SLSQP: maximize daily EV subject to caps + optional per-day variance."""
    n = len(day_bets)
    evs = np.array([b["ev"] for b in day_bets])
    vars_ = np.array([_bet_var(b) for b in day_bets])

    def neg_ev(x: np.ndarray) -> float:
        return -float(np.dot(evs, x))

    def neg_ev_jac(x: np.ndarray) -> np.ndarray:
        return -evs

    constraints: list[dict] = [
        {"type": "ineq", "fun": lambda x: DAILY_CAP - float(sum(x))},
    ]
    if sigma2_target is not None:
        constraints.append(
            {"type": "ineq", "fun": lambda x: sigma2_target - float(np.dot(vars_, x**2))}
        )

    bounds = [(0.0, SINGLE_BET_CAP)] * n
    x0 = np.array([min(b.get("kelly_stake", 0.015), SINGLE_BET_CAP) for b in day_bets])

    res = minimize(
        neg_ev, x0, jac=neg_ev_jac, method="SLSQP",
        bounds=bounds, constraints=constraints,
        options={"maxiter": 200, "ftol": 1e-9},
    )
    return res.x


def _kelly_stakes(day_bets: list[dict]) -> np.ndarray:
    """1/2 Kelly capped at single-bet cap, then daily cap."""
    stakes = np.array([min(b.get("kelly_stake", 0.0), SINGLE_BET_CAP) for b in day_bets])
    total = float(sum(stakes))
    if total > DAILY_CAP:
        stakes = stakes * (DAILY_CAP / total)
    return stakes


def _detect_hedging(day_bets: list[dict], corr_groups: set[str]) -> list[dict]:
    """Identify same-group same-day bet pairs (3rd-round hedging opportunities)."""
    groups: dict[str, list[dict]] = {}
    for b in day_bets:
        groups.setdefault(b["group"], []).append(b)
    hedges = []
    for g, bs in groups.items():
        if len(bs) < 2:
            continue
        is_corr = g in corr_groups
        selections = [(b["match"], b["selection"]) for b in bs]
        # Check if bets are on same selection type (no natural hedge) or different
        sels = [b["selection"] for b in bs]
        hedge_type = "none"  # no natural hedge — both same direction
        if len(set(sels)) > 1:
            hedge_type = "partial"  # different selections → some hedge potential
        hedges.append({
            "group": g,
            "matches": [b["match"] for b in bs],
            "selections": sels,
            "hedge_type": hedge_type,
            "model_correlation": "analyzed" if is_corr else "not_analyzed",
            "note": "同组第三轮同时开赛, 战术相关性 > 模型 cov≈0" if is_corr
                    else "同组同日, 未做蒙特卡洛分析",
        })
    return hedges


def run(verbose: bool = True) -> dict:
    fb = json.loads(FINAL_BETS_FILE.read_text(encoding="utf-8"))
    corr = json.loads(CORR_FILE.read_text(encoding="utf-8"))
    bets = fb["final_bets"]

    corr_groups = {g["group"] for g in corr.get("groups", [])}

    by_day: dict[str, list[dict]] = {}
    for b in bets:
        by_day.setdefault(b["date"], []).append(b)

    days: list[dict] = []
    # Approach A: global optimal (from P6)
    glob_total_stake = fb["total_stake"]
    glob_total_ev = fb["total_ev"]
    glob_sigma = fb["optimization"]["optimal_portfolio_std"]

    # Approach B: per-day Kelly
    b_total_stake = b_total_ev = b_total_var = 0.0
    # Approach C: per-day SLSQP at different sigma caps
    c_totals: dict[float, dict] = {}

    for date in sorted(by_day):
        db = by_day[date]
        n = len(db)
        bet_vars = [_bet_var(b) for b in db]

        # --- Global optimal stakes (from P6) ---
        glob_stakes = np.array([b["optimal_stake"] for b in db])
        g_ev, g_var = _day_ev_var(glob_stakes, db)

        # --- Kelly stakes ---
        k_stakes = _kelly_stakes(db)
        k_ev, k_var = _day_ev_var(k_stakes, db)
        b_total_stake += float(sum(k_stakes))
        b_total_ev += k_ev
        b_total_var += k_var

        # --- Per-day SLSQP at each sigma cap ---
        c_day: dict[float, dict] = {}
        for sc in SIGMA_CAPS:
            s = _optimize_day(db, sigma2_target=sc**2)
            ev, var = _day_ev_var(s, db)
            if sc not in c_totals:
                c_totals[sc] = {"stake": 0.0, "ev": 0.0, "var": 0.0}
            c_totals[sc]["stake"] += float(sum(s))
            c_totals[sc]["ev"] += ev
            c_totals[sc]["var"] += var
            c_day[sc] = {
                "stakes": [round(float(x), 6) for x in s],
                "stake": round(float(sum(s)), 6),
                "ev": round(ev, 6),
                "sigma": round(var**0.5, 6),
                "sharpe": round(ev / var**0.5, 4) if var > 0 else 0.0,
            }

        # --- Hedging detection ---
        hedges = _detect_hedging(db, corr_groups)

        # --- Diversification benefit ---
        div_benefit = 0.0
        if n > 1:
            avg_var = float(np.mean(bet_vars))
            avg_stake = float(np.mean(glob_stakes))
            single_sigma = avg_stake * avg_var**0.5
            if single_sigma > 0:
                portfolio_sigma = g_var**0.5
                div_benefit = max(0.0, 1.0 - (portfolio_sigma / (single_sigma * n**0.5))**2)

        day_result = {
            "date": date,
            "n_bets": n,
            "bets": [
                {
                    "match": b["match"],
                    "group": b["group"],
                    "selection": b["selection"],
                    "odds": b["odds"],
                    "p_model": b["p_model"],
                    "ev": b["ev"],
                    "bet_variance": round(_bet_var(b), 4),
                    "kelly_stake": b.get("kelly_stake", 0),
                    "global_optimal_stake": b["optimal_stake"],
                }
                for b in db
            ],
            "global": {
                "stakes": [round(float(x), 6) for x in glob_stakes],
                "stake": round(float(sum(glob_stakes)), 6),
                "ev": round(g_ev, 6),
                "sigma": round(g_var**0.5, 6),
                "sharpe": round(g_ev / g_var**0.5, 4) if g_var > 0 else 0.0,
            },
            "kelly": {
                "stakes": [round(float(x), 6) for x in k_stakes],
                "stake": round(float(sum(k_stakes)), 6),
                "ev": round(k_ev, 6),
                "sigma": round(k_var**0.5, 6),
                "sharpe": round(k_ev / k_var**0.5, 4) if k_var > 0 else 0.0,
            },
            "per_day_slsqp": c_day,
            "hedging": hedges,
            "diversification_benefit": round(div_benefit, 4),
        }
        days.append(day_result)

    # --- Summary comparison ---
    b_sigma = b_total_var**0.5
    summary = {
        "approaches": {
            "A_global": {
                "label": "全局优化 (σ²≤0.02)",
                "total_stake": round(glob_total_stake, 6),
                "total_ev": round(glob_total_ev, 6),
                "sigma": round(glob_sigma, 6),
                "sharpe": round(glob_total_ev / glob_sigma, 4) if glob_sigma > 0 else 0.0,
            },
            "B_kelly": {
                "label": "每日 Kelly (仅3%/注+15%/日上限)",
                "total_stake": round(b_total_stake, 6),
                "total_ev": round(b_total_ev, 6),
                "sigma": round(b_sigma, 6),
                "sharpe": round(b_total_ev / b_sigma, 4) if b_sigma > 0 else 0.0,
            },
        },
    }
    for sc in SIGMA_CAPS:
        t = c_totals[sc]
        sig = t["var"]**0.5
        summary["approaches"][f"C_slsqp_{sc:.0%}"] = {
            "label": f"每日 SLSQP (σ≤{sc:.0%}/日)",
            "total_stake": round(t["stake"], 6),
            "total_ev": round(t["ev"], 6),
            "sigma": round(sig, 6),
            "sharpe": round(t["ev"] / sig, 4) if sig > 0 else 0.0,
        }

    # Find best Sharpe and best EV
    best_sharpe = max(summary["approaches"].values(), key=lambda x: x["sharpe"])
    best_ev = max(summary["approaches"].values(), key=lambda x: x["total_ev"])
    summary["best_sharpe"] = best_sharpe["label"]
    summary["best_ev"] = best_ev["label"]
    summary["recommendation"] = (
        f"风险调整最优: {best_sharpe['label']} (Sharpe={best_sharpe['sharpe']:.2f}). "
        f"绝对收益最高: {best_ev['label']} (EV={best_ev['total_ev']:+.4f}, σ={best_ev['sigma']:.1%}). "
        f"对冲: 同组同日下注 (6-26 Group E, 6-28 Group K) 有战术相关性, "
        f"但模型 cov≈0 无法量化; 分散化是主要降险手段."
    )

    result = {
        "as_of": fb.get("as_of", ""),
        "n_bets": len(bets),
        "n_days": len(days),
        "days": days,
        "summary": summary,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    if verbose:
        print(f"=== 每日组合分析 ({len(bets)} 注, {len(days)} 日) ===\n")
        for d in days:
            print(f"--- {d['date']} ({d['n_bets']} 注) ---")
            for b in d["bets"]:
                print(f"  [{b['selection']}] {b['match'][:38]:38s} G{b['group']} "
                      f"@{b['odds']:.2f} EV={b['ev']:+.1%} var={b['bet_variance']:.2f}")
            g = d["global"]
            k = d["kelly"]
            print(f"  全局优化: 仓位={g['stake']:.1%} EV={g['ev']:+.4f} "
                  f"σ={g['sigma']:.1%} Sharpe={g['sharpe']:.2f}")
            print(f"  Kelly:    仓位={k['stake']:.1%} EV={k['ev']:+.4f} "
                  f"σ={k['sigma']:.1%} Sharpe={k['sharpe']:.2f}")
            for sc in SIGMA_CAPS:
                c = d["per_day_slsqp"][sc]
                print(f"  SLSQP σ≤{sc:.0%}: 仓位={c['stake']:.1%} EV={c['ev']:+.4f} "
                      f"σ={c['sigma']:.1%} Sharpe={c['sharpe']:.2f}")
            if d["hedging"]:
                for h in d["hedging"]:
                    print(f"  🔗 同组对冲: Group {h['group']} {h['matches']} "
                          f"选={h['selections']} hedge={h['hedge_type']}")
            if d["diversification_benefit"] > 0:
                print(f"  分散化: σ降低 ~{d['diversification_benefit']:.0%}")
            print()

        print("=== 方案对比 ===")
        for key, ap in summary["approaches"].items():
            print(f"  {ap['label']:30s} 仓位={ap['total_stake']:.1%} "
                  f"EV={ap['total_ev']:+.4f} σ={ap['sigma']:.1%} "
                  f"Sharpe={ap['sharpe']:.2f}")
        print()
        print(f"推荐: {summary['recommendation']}")
        print(f"\n输出: {OUTPUT_FILE}")

    return result


if __name__ == "__main__":
    run()
