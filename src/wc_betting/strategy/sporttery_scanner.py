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

# Backtest-based EV adjustments (25 settled bets, 6/25-26):
#   hhad: 7W 9L ROI +18% (only profitable pool)
#   had:  2W 5L ROI -25% (draws 0/3, H/A also negative)
# Apply penalty to had EV, bonus to hhad
# Motivation constants (used by _get_motivation_adjustment)
MOTIVATION_CRITICAL = 0.15
MOTIVATION_BOOST = 0.10
MOTIVATION_GROUP_WINNER = 0.05
MOTIVATION_PENALTY = -0.05

# Unified quality scoring — replaces 7 discrete rules with 1 continuous score
# Score = ev_calibrated + adjustments. Score > MIN_SCORE → recommend.
MIN_QUALITY_SCORE = 0.05   # minimum score for auto-recommendation
# === Architecture ===
# Q (Quality Score) = permanent factors: EV, pool type, handicap, elo gap, odds
# Scenario Layer = stage-specific: group 3rd round motivation → will be zeroed in knockout
# Final Score = Q + Scenario → threshold → auto/manual

POOL_DISCOUNT = {"had": -0.05, "hhad": 0.0}
CRS_TTG_MANUAL = True  # 比分/总进球：高赔低命中，回测0/2，全量manual
LARGE_HCAP_MANUAL = True  # |hcap|>=2：回测1W5L命中率17%，全量manual

# Team tier adjustment — computed from Elo ratings (dynamic, not hardcoded)
# T1=top8, T2=9-20, T3=21-36, T4=37-48
_tier_cache: dict[str, int] | None = None

def _compute_tiers() -> dict[str, int]:
    """Compute tiers from Elo model. Cached after first call."""
    global _tier_cache
    if _tier_cache is not None:
        return _tier_cache
    from wc_betting.models.elo import EloModel
    elo = EloModel()
    elo.calibrate()
    ratings = {}
    # Get all teams from ratings dict
    for code in elo.ratings:
        try:
            ratings[code] = elo.ratings[code]["elo"]
        except Exception:
            ratings[code] = 1500
    sorted_teams = sorted(ratings.items(), key=lambda x: -x[1])
    n = len(sorted_teams)
    tiers = {}
    for i, (team, _) in enumerate(sorted_teams):
        if i < 8: tiers[team] = 1
        elif i < 20: tiers[team] = 2
        elif i < 36: tiers[team] = 3
        else: tiers[team] = 4
    _tier_cache = tiers
    return tiers

TIER_MATCHUP_ADJ = {
    # (home_tier, away_tier): Q adjustment
    (1,1): 0.0,    # elite clash: model is reliable
    (1,4): -0.05,  # huge mismatch: unpredictable, had less valuable
    (4,1): -0.05,
    (4,4): -0.03,  # both weak: chaotic
    (2,3): 0.01,   # most balanced: model performs best
    (3,2): 0.01,
}
DRAW_PENALTY = -0.08       # draws are high-variance
LARGE_HCAP_PENALTY = -0.05 # |hcap|>=2 penalty per extra level
MOTIVATION_BONUS_FACTOR = 1.0   # scale motivation adjustment into score space
MAX_ODDS_AUTO = 25.0   # max odds for auto-review (extreme longshots → manual)

# Elo-Poisson gap threshold: when the model's 1X2 probs diverge from Elo-based
# probs by more than this, the match is flagged as "manual review" and excluded
# from automatic portfolio optimization. Matches value.py's threshold (plan §4).
ELO_POISSON_GAP_THRESHOLD = 0.15

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


def _get_motivation_adjustment(home_en: str, away_en: str) -> float:
    """Return net motivation shift based on 3rd-place ranking cutoff.
    
    48-team format: 12 group winners + 12 runners-up + 8 best 3rd-place.
    Teams at 0-2pts in 3rd place have MASSIVE motivation (win = qualify).
    """
    # Standings after 2 matches:
    # (pts, gd, can_win_group, is_3rd): tuple
    # can_win_group = win makes them group 1st → faces 2nd in R32
    MOT_STANDINGS = {
        'Egypt': (4, 2, True, False), 'Iran': (2, 0, False, False),
        'Belgium': (2, 0, False, True), 'New Zealand': (1, -2, False, False),
        'Spain': (4, 4, True, False), 'Uruguay': (2, 0, False, False),
        'Cape Verde': (2, 0, False, True), 'Saudi Arabia': (1, -4, False, False),
        'France': (6, 5, True, False), 'Norway': (6, 4, True, False),
        'Senegal': (0, -3, False, True), 'Iraq': (0, -6, False, False),
        'Argentina': (6, 5, True, False), 'Austria': (3, 0, True, False),
        'Algeria': (3, -2, True, True), 'Jordan': (0, -3, False, False),
        'Colombia': (6, 3, True, False), 'Portugal': (4, 5, True, False),
        'DR Congo': (1, -1, False, True), 'Uzbekistan': (0, -7, False, False),
        'England': (4, 2, True, False), 'Ghana': (4, 1, True, False),
        'Croatia': (3, -1, True, True), 'Panama': (0, -2, False, False),
    }
    
    # Teams where draw=qualify (2pt + GD advantage over 8th place)
    _draw_is_enough = {'Iran'}  # 3pt would beat Scotland(3pt GD-3)
    
    def mot(team):
        entry = MOT_STANDINGS.get(team)
        if entry is None: return 0.0
        pts, gd, can_win_group, is_3rd = entry
        val = 0.0
        if pts >= 6:
            val = MOTIVATION_PENALTY              # qualified, may rotate
        elif pts >= 4:
            val = 0.0                              # likely through
        elif team in _draw_is_enough:
            val = 0.05                             # draw is enough to qualify
        elif pts >= 3:
            val = 0.05                             # already in top 8, just securing
        else:
            # pts 0-2: fighting for qualification
            if is_3rd:
                val = MOTIVATION_CRITICAL          # +15%: win = jump into top 8
            else:
                val = MOTIVATION_BOOST             # +10%: must fight
        # Group winner bonus: winning means facing a 2nd-place team in R32
        if can_win_group:
            val += MOTIVATION_GROUP_WINNER         # +5% extra
        return val
    
    return mot(home_en) - mot(away_en)


def _get_context_rules(home_en: str, away_en: str) -> dict:
    """Return context rules for a specific match based on qualification dynamics.
    
    Rules are match-specific and change per round.
    Group 3rd round rules (6/27-28):
    - draw_is_enough: team needs only a draw to qualify → prefer hhad
    - must_win: team must win to qualify → prefer had
    - both_qualified: both teams already through → reduce stakes
    - win_group_winner: win = group 1st = easier R32 opponent
    """
    # Iran: 2pt, draw = 3pt GD0 > Scotland(3pt GD-3) → qualify
    DRAW_IS_ENOUGH = {'Iran'}
    # Uruguay: must beat Spain to have chance
    MUST_WIN = {'Uruguay'}  
    # Both qualified, playing for group position
    BOTH_QUALIFIED = {('Norway','France'), ('France','Norway'),
                      ('Colombia','Portugal'), ('Portugal','Colombia')}
    # Win = group winner → easier knockout path
    WIN_GROUP_WINNER = {'Egypt', 'Spain', 'Norway', 'France', 'Argentina',
                        'Colombia', 'Portugal', 'England', 'Ghana'}
    
    rules = {}
    if home_en in DRAW_IS_ENOUGH:
        rules['draw_is_enough'] = True
    if home_en in MUST_WIN:
        rules['must_win'] = True
    if (home_en, away_en) in BOTH_QUALIFIED:
        rules['both_qualified'] = True
    if home_en in WIN_GROUP_WINNER:
        rules['win_group_winner'] = True
    
    return rules


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
                # Final-round motivation adjustment
                # Adjust probability based on qualification stakes
                mot_adj = _get_motivation_adjustment(home_en, away_en)
                if mot_adj != 0:
                    if key == 'H':
                        p = max(0.02, p + mot_adj)
                        p_c = max(0.02, p_c + mot_adj * 1.5)
                    elif key == 'A':
                        p = max(0.02, p - mot_adj)
                        p_c = max(0.02, p_c - mot_adj * 1.5)
                    # D unchanged (both sides cancel)
                
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
                
                # Motivation adjustment to probabilities
                mot_adj = _get_motivation_adjustment(home_en, away_en)
                if mot_adj != 0:
                    if key == 'H':
                        p = max(0.02, p + mot_adj * 0.5)
                        p_c = max(0.02, p_c + mot_adj * 0.75)
                    elif key == 'A':
                        p = max(0.02, p - mot_adj * 0.5)
                        p_c = max(0.02, p_c - mot_adj * 0.75)
                
                # Recompute EV with adjusted probabilities
                ev = p * price_f - 1.0
                ev_c = p_c * price_f - 1.0
                
                if ev_c <= EV_THRESHOLD:
                    continue
                
                # === Unified Quality Score (after final EV) ===
                quality = ev_c
                reasons = []
                
                # Team tier adjustment (permanent: team strength from Elo)
                tiers = _compute_tiers()
                ht = tiers.get(home_en, 3)
                at = tiers.get(away_en, 3)
                tier_adj = TIER_MATCHUP_ADJ.get((ht, at), 0.0)
                if tier_adj != 0:
                    quality += tier_adj
                    reasons.append(f"T{ht}vT{at}({tier_adj:+.0%})")
                
                # Pool discount (had is less reliable: 2W5L vs hhad 7W9L)
                quality += POOL_DISCOUNT.get(pool, 0)
                
                # Draw penalty (high variance, 0/3 in user backtest)
                if pool == "had" and key == "D":
                    quality += DRAW_PENALTY
                    if p < 0.25:
                        quality -= 0.01
                        reasons.append(f"low_draw_p({p:.0%})")
                    if poisson_1x2:
                        po_d = poisson_1x2.get("d", 0)
                        if po_d <= max(poisson_1x2.get("h",0), poisson_1x2.get("a",0)):
                            quality -= 0.01
                            reasons.append("draw_not_top")
                
                # Large handicap penalty
                if pool == "hhad" and handicap is not None and abs(handicap) >= 2:
                    quality += LARGE_HCAP_PENALTY * (abs(handicap) - 1)
                    reasons.append(f"large_hcap({handicap:+.0f})")
                
                # Cold mismatch
                if mismatch_cold:
                    quality -= 0.02
                    reasons.append("mismatch_cold")
                
                # Longshot
                if price_f > MAX_ODDS_AUTO:
                    quality -= 0.02
                    reasons.append(f"longshot({price_f:.0f})")
                
                # Scenario layer: group-stage final-round motivation
                # Applied OUTSIDE Q so it can be zeroed in knockout stage
                scenario_bonus = 0.0
                if mot_adj != 0:
                    if (key == 'H' and mot_adj > 0) or (key == 'A' and mot_adj < 0):
                        scenario_bonus = abs(mot_adj) * MOTIVATION_BONUS_FACTOR
                    elif (key == 'H' and mot_adj < 0) or (key == 'A' and mot_adj > 0):
                        scenario_bonus = -abs(mot_adj) * MOTIVATION_BONUS_FACTOR
                quality += scenario_bonus  # add to final score (will be configurable per stage)
                
                # === Context Rules (Scenario layer) ===
                # Check BOTH teams' context — match dynamics are two-sided
                ctx_h = _get_context_rules(home_en, away_en)
                ctx_a = _get_context_rules(away_en, home_en)
                
                def _apply_ctx(ctx, side):
                    nonlocal scenario_bonus
                    if not ctx: return
                    tag = f'[{side}]'
                    if ctx.get('draw_is_enough'):
                        if pool == 'hhad':
                            scenario_bonus += 0.03; reasons.append(f'ctx{tag}draw=qualify→hhad')
                        elif pool == 'had':
                            scenario_bonus -= 0.02; reasons.append(f'ctx{tag}draw=qualify→no_had')
                    if ctx.get('must_win'):
                        if pool == 'had':
                            scenario_bonus += 0.02; reasons.append(f'ctx{tag}must_win→had')
                    if ctx.get('both_qualified'):
                        scenario_bonus -= 0.03; reasons.append(f'ctx{tag}both_qualified→reduce')
                    if ctx.get('win_group_winner'):
                        if pool == 'hhad':
                            scenario_bonus += 0.02; reasons.append(f'ctx{tag}group_winner→hhad')
                
                _apply_ctx(ctx_h, 'H')
                _apply_ctx(ctx_a, 'A')
                
                # Threshold check
                is_manual = quality < MIN_QUALITY_SCORE
                
                # CRS/TTG override: always manual (high odds, low hit rate, 0/2 backtest)
                if pool in ('crs', 'ttg') and CRS_TTG_MANUAL:
                    is_manual = True
                    reasons.insert(0, f"{pool}_manual")
                
                # Large handicap override: |hcap|>=2 always manual (1W5L, 17% hit rate)
                if pool == 'hhad' and handicap is not None and abs(handicap) >= 2 and LARGE_HCAP_MANUAL:
                    is_manual = True
                    reasons.insert(0, f"large_hcap({handicap:+.0f})")
                
                reasons.append(f"score={quality:+.0%}")
                
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
                    "quality_score": round(quality, 4),
                    "scenario_bonus": round(scenario_bonus, 4),
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
