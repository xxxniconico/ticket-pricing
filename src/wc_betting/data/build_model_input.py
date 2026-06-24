"""Build wc_2026_model_input.json: merge odds + model probs for P4 value screening.

For each of the 40 remaining (unfinished) WC 2026 matches:
  - market odds (avg_h/d/a) + de-vigged implied probabilities
  - Poisson 1X2 probabilities (Dixon-Coles, fit on all 2135 historical matches)
  - Elo 1X2 probabilities (for inconsistency flagging only)
  - inconsistency flag (|p_elo_home - p_poisson_home| > 8%)

Calibration finding (P3): pure Poisson (w_elo=0) is optimal. Elo is retained
only for the inconsistency flag, not for the probability blend. See
docs/plans/wc-betting-strategy-20260620.md §8 calibration results.
"""

from __future__ import annotations

import json
import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
UNIFIED_FILE = PROJECT_ROOT / "data/processed/wc_2026_unified.json"
HIST_FILE = PROJECT_ROOT / "data/raw/historical/intl_results_2022_2026.json"
ELO_FILE = PROJECT_ROOT / "data/raw/elo/elo_ratings_20260620.json"
OUT_FILE = PROJECT_ROOT / "data/processed/wc_2026_model_input.json"

NAME_NORMALIZE = {
    "Canada men&#39;s": "Canada", "Canada men's": "Canada",
    "United States men&#39;s": "United States", "United States men's": "United States",
    "USA": "United States",
    "Australia men&#39;s": "Australia", "Australia men's": "Australia",
    "Sweden men&#39;s": "Sweden", "Sweden men's": "Sweden",
    "New Zealand men&#39;s": "New Zealand", "New Zealand men's": "New Zealand",
    "Curaçao": "Curacao",
    "Bosnia & Herzegovina": "Bosnia and Herzegovina",
}


def canonical(name: str) -> str:
    return NAME_NORMALIZE.get(name, name)


def market_implied(h: float, d: float, a: float) -> tuple[float, float, float]:
    ih, idd, ia = 1 / h, 1 / d, 1 / a
    s = ih + idd + ia
    return ih / s, idd / s, ia / s


def build() -> dict:
    from wc_betting.models.elo import EloModel, host_hfa
    from wc_betting.models.poisson import PoissonModel, host_rho, RHO_NEUTRAL
    from wc_betting.models.blend import INCONSISTENCY_THRESHOLD

    unified = json.loads(UNIFIED_FILE.read_text(encoding="utf-8"))
    history = json.loads(HIST_FILE.read_text(encoding="utf-8"))["matches"]

    # Fit Poisson on ALL history (includes 32 played WC matches — use latest data).
    poisson = PoissonModel.fit(matches=history)
    pp = poisson.params
    elo = EloModel()
    elo.calibrate()

    remaining = [m for m in unified if not m.get("finished")]
    matches_out = []
    for m in remaining:
        mx = m.get("metrics")
        if not mx or not mx.get("avg_h"):
            continue
        home = canonical(m["home_en"])
        away = canonical(m["away_en"])
        odds = (mx["avg_h"], mx["avg_d"], mx["avg_a"])
        mkt = market_implied(*odds)

        # Poisson (the model).
        rho = host_rho(pp, home)
        p_poisson = poisson.predict(home, away, neutral=(rho == RHO_NEUTRAL))

        # Elo (for inconsistency flag only — not blended, per calibration finding).
        try:
            p_elo = elo.predict(home, away, hfa=host_hfa(home))
            gap = abs(p_elo[0] - p_poisson[0])
            inconsistent = gap > INCONSISTENCY_THRESHOLD
        except KeyError:
            p_elo, gap, inconsistent = None, None, None

        matches_out.append({
            "group": m["group"],
            "date": m.get("date") or (m.get("commence_time", "") or "")[:10],
            "home": home, "away": away,
            "odds": {"h": odds[0], "d": odds[1], "a": odds[2]},
            "market_implied": {"h": mkt[0], "d": mkt[1], "a": mkt[2]},
            "poisson": {"h": p_poisson[0], "d": p_poisson[1], "a": p_poisson[2]},
            "elo": {"h": p_elo[0], "d": p_elo[1], "a": p_elo[2]} if p_elo else None,
            "elo_poisson_gap": round(gap, 4) if gap is not None else None,
            "inconsistent": inconsistent,
            "p_h_std": mx.get("p_h_std"),
            "n_bookmakers": mx.get("n_bookmakers"),
            "avg_vig": mx.get("avg_vig"),
        })

    out = {
        "as_of": datetime.date.today().isoformat(),
        "model": "pure_poisson_dc",
        "blend_w_elo": 0.0,
        "note": "Pure Poisson (Dixon-Coles). Elo dropped from blend after OOS "
                "calibration showed it hurts (confederation misalignment). Elo "
                "retained only for inconsistency flagging. See plan §8.",
        "poisson_params": {
            "mu": pp.mu, "rho": pp.rho, "rho_dc": pp.rho_dc,
            "n_matches": pp.n_matches_used, "n_teams": len(pp.team_codes),
        },
        "calibration": {
            "n_test_matches": 32,
            "brier_home_poisson": 0.2244,
            "base_rate_baseline": 0.2490,
            "plan_threshold": 0.2222,
            "note": "Beats proper base-rate baseline; marginally above plan threshold "
                    "(within 32-match noise). Recency weighting did not help.",
        },
        "matches": matches_out,
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


if __name__ == "__main__":
    out = build()
    n = len(out["matches"])
    n_inc = sum(1 for m in out["matches"] if m["inconsistent"])
    print(f"wrote {OUT_FILE}")
    print(f"matches: {n}  inconsistent: {n_inc}")
    print(f"poisson: mu={out['poisson_params']['mu']:.3f} rho={out['poisson_params']['rho']:.3f} "
          f"rho_dc={out['poisson_params']['rho_dc']:.4f} teams={out['poisson_params']['n_teams']}")
