"""Dixon-Coles simplified Poisson goal model.

Model (per plan §3.2):
    lam_home = mu * attack[home] * defense[away] * rho
    lam_away = mu * attack[away] * defense[home] / rho
    P(i, j) = tau(i, j) * Poisson(i; lam_home) * Poisson(j; lam_away)

Dixon-Coles low-score correction tau:
    tau(0,0) = 1 - lam_h*lam_a*rho_dc
    tau(0,1) = 1 + lam_h*rho_dc
    tau(1,0) = 1 + lam_a*rho_dc
    tau(1,1) = 1 - rho_dc
    tau(i,j) = 1  otherwise

Identifiability: sum(log attack) = sum(log defense) = 0 (mu carries the scale).

Teams with < MIN_MATCHES historical matches are bucketed into a single "ROW"
(rest-of-world) team; matches between two ROW teams are excluded (no info about
WC team params).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HIST_FILE = PROJECT_ROOT / "data/raw/historical/intl_results_2022_2026.json"
ELO_FILE = PROJECT_ROOT / "data/raw/elo/elo_ratings_20260620.json"

MIN_MATCHES = 8
ROW_CODE = "ROW"
MAX_GOALS = 10  # score matrix truncation for 1X2 sum

WC_2026_HOSTS = {"Mexico", "United States", "Canada"}
RHO_NEUTRAL = 1.0  # no home advantage at neutral WC venues

# FIFA confederation mapping for the 48 WC 2026 teams. Used by the
# cross-confederation away-win deflation (see fit_deflate_away / score_matrix).
# Australia moved from OFC to AFC in 2006.
FEDERATIONS: dict[str, str] = {
    # UEFA (Europe) — 16
    "Spain": "UEFA", "France": "UEFA", "England": "UEFA", "Germany": "UEFA",
    "Netherlands": "UEFA", "Portugal": "UEFA", "Croatia": "UEFA",
    "Belgium": "UEFA", "Switzerland": "UEFA", "Austria": "UEFA",
    "Sweden": "UEFA", "Norway": "UEFA", "Turkey": "UEFA", "Scotland": "UEFA",
    "Czech Republic": "UEFA", "Bosnia and Herzegovina": "UEFA",
    # CONMEBOL (South America) — 6
    "Argentina": "CONMEBOL", "Brazil": "CONMEBOL", "Colombia": "CONMEBOL",
    "Ecuador": "CONMEBOL", "Paraguay": "CONMEBOL", "Uruguay": "CONMEBOL",
    # CONCACAF (North/Central America + Caribbean) — 6
    "Mexico": "CONCACAF", "United States": "CONCACAF", "Canada": "CONCACAF",
    "Panama": "CONCACAF", "Haiti": "CONCACAF", "Curacao": "CONCACAF",
    # CAF (Africa) — 10
    "Morocco": "CAF", "Senegal": "CAF", "Egypt": "CAF", "Algeria": "CAF",
    "Tunisia": "CAF", "Ivory Coast": "CAF", "Ghana": "CAF",
    "South Africa": "CAF", "DR Congo": "CAF", "Cape Verde": "CAF",
    # AFC (Asia) — 9
    "Japan": "AFC", "South Korea": "AFC", "Iran": "AFC", "Saudi Arabia": "AFC",
    "Qatar": "AFC", "Iraq": "AFC", "Jordan": "AFC", "Uzbekistan": "AFC",
    "Australia": "AFC",
    # OFC (Oceania) — 1
    "New Zealand": "OFC",
}


_NAME_ALIASES: dict[str, str] = {
    "USA": "United States",
    "Czechia": "Czech Republic",
    "Côte d'Ivoire": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "Republic of Ireland": "Ireland",
    "Bosnia": "Bosnia and Herzegovina",
    "IR Iran": "Iran",
    "Korea Republic": "South Korea",
    "Korea Republic (South Korea)": "South Korea",
}


def _norm_team_name(name: str) -> str:
    """Normalize a team name for federation lookup (inline to avoid circular import)."""
    if not name:
        return ""
    from html import unescape
    s = unescape(name).strip()
    # Strip " men's" / " men&#39;s" suffix (Canada/USA/Australia/Sweden/NZ).
    for suffix in (" men's", " mens"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return _NAME_ALIASES.get(s, s)


def federation_of(team_name: str) -> str | None:
    """Return the FIFA confederation for a team name, or None if unknown."""
    if not team_name:
        return None
    s = _norm_team_name(team_name)
    return FEDERATIONS.get(s) or FEDERATIONS.get(team_name)


def is_cross_confederation(home_name: str, away_name: str) -> bool:
    """True iff both teams have known federations and they differ.

    Used to gate the deflate_away correction: only cross-confederation matches
    get the away-win deflation (UEFA/CONMEBOL vs CONCACAF/CAF/AFC/OFC).
    """
    fh = federation_of(home_name)
    fa = federation_of(away_name)
    if fh is None or fa is None:
        return False
    return fh != fa


@dataclass
class DCParams:
    """Fitted Dixon-Coles parameters."""
    team_codes: list[str]            # index i -> team code
    code_index: dict[str, int]       # team code -> index
    log_attack: np.ndarray
    log_defense: np.ndarray
    log_mu: float
    log_rho: float
    rho_dc: float
    # Post-hoc corrections (fit separately after MLE — see fit_draw_inflate /
    # fit_deflate_away). Defaults of 1.0 mean "no correction".
    draw_inflate: float = 1.0
    deflate_away: float = 1.0
    n_matches_used: int = 0
    nll: float = math.inf

    @property
    def attack(self) -> np.ndarray:
        return np.exp(self.log_attack)

    @property
    def defense(self) -> np.ndarray:
        return np.exp(self.log_defense)

    @property
    def mu(self) -> float:
        return math.exp(self.log_mu)

    @property
    def rho(self) -> float:
        return math.exp(self.log_rho)

    def lam(self, home_idx: int, away_idx: int, rho: float | None = None) -> tuple[float, float]:
        r = self.rho if rho is None else rho
        lam_h = self.mu * self.attack[home_idx] * self.defense[away_idx] * r
        lam_a = self.mu * self.attack[away_idx] * self.defense[home_idx] / r
        return lam_h, lam_a


def _dc_tau(i: int, j: int, lam_h: float, lam_a: float, rho_dc: float) -> float:
    if i == 0 and j == 0:
        return 1.0 - lam_h * lam_a * rho_dc
    if i == 0 and j == 1:
        return 1.0 + lam_h * rho_dc
    if i == 1 and j == 0:
        return 1.0 + lam_a * rho_dc
    if i == 1 and j == 1:
        return 1.0 - rho_dc
    return 1.0


def _dc_tau_vec(i: np.ndarray, j: np.ndarray, lam_h: np.ndarray,
                lam_a: np.ndarray, rho_dc: float) -> np.ndarray:
    tau = np.ones_like(lam_h)
    m00 = (i == 0) & (j == 0)
    m01 = (i == 0) & (j == 1)
    m10 = (i == 1) & (j == 0)
    m11 = (i == 1) & (j == 1)
    tau[m00] = 1.0 - lam_h[m00] * lam_a[m00] * rho_dc
    tau[m01] = 1.0 + lam_h[m01] * rho_dc
    tau[m10] = 1.0 + lam_a[m10] * rho_dc
    tau[m11] = 1.0 - rho_dc
    return tau


def build_team_index(matches: list[dict], min_matches: int = MIN_MATCHES,
                     keep_codes: set[str] | None = None) -> dict[str, int]:
    """Map team code -> index. Teams with >= min_matches (or in keep_codes) get
    their own index; the rest collapse into ROW."""
    from collections import Counter
    counts: Counter[str] = Counter()
    for m in matches:
        if m["team1_goals"] is None or m["team2_goals"] is None:
            continue
        counts[m["team1_code"]] += 1
        counts[m["team2_code"]] += 1
    keep = {c for c, n in counts.items() if n >= min_matches}
    if keep_codes:
        keep |= keep_codes
    codes = sorted(keep) + [ROW_CODE]
    return {c: i for i, c in enumerate(codes)}


def _prepare_arrays(matches: list[dict], code_index: dict[str, int],
                    use_xg: bool = False):
    """Extract index/feature arrays from match dicts.

    When ``use_xg`` is True, also collects ``team1_xg`` / ``team2_xg`` (float,
    NaN when missing) and a boolean ``has_xg`` mask. xG is only used for
    matches that have it AND when use_xg is requested; matches without xG
    fall through to the standard goals-based DC likelihood.
    """
    home_idx, away_idx, gh, ga, dates = [], [], [], [], []
    xg_h: list[float] = []
    xg_a: list[float] = []
    for m in matches:
        if m["team1_goals"] is None or m["team2_goals"] is None:
            continue
        h = m["team1_code"] if m["team1_code"] in code_index else ROW_CODE
        a = m["team2_code"] if m["team2_code"] in code_index else ROW_CODE
        if h == ROW_CODE and a == ROW_CODE:
            continue  # both minor: no info
        home_idx.append(code_index[h])
        away_idx.append(code_index[a])
        gh.append(m["team1_goals"])
        ga.append(m["team2_goals"])
        dates.append(m.get("date", ""))
        xh = m.get("team1_xg")
        xa = m.get("team2_xg")
        xg_h.append(float(xh) if xh is not None else float("nan"))
        xg_a.append(float(xa) if xa is not None else float("nan"))
    xg_h_arr = np.array(xg_h, dtype=float)
    xg_a_arr = np.array(xg_a, dtype=float)
    has_xg = (~np.isnan(xg_h_arr)) & (~np.isnan(xg_a_arr)) if use_xg else (
        np.zeros(len(xg_h_arr), dtype=bool))
    return (np.array(home_idx, dtype=np.int64),
            np.array(away_idx, dtype=np.int64),
            np.array(gh, dtype=np.int64),
            np.array(ga, dtype=np.int64),
            xg_h_arr, xg_a_arr, has_xg,
            dates)


def recency_weights(dates: list[str], reference_date: str,
                    half_life_days: float) -> np.ndarray:
    """Exponential recency weights: w = exp(-ln2 * days_old / half_life).
    Matches on/after reference_date get weight 1."""
    from datetime import date
    ref = date.fromisoformat(reference_date)
    xi = math.log(2) / half_life_days
    w = np.ones(len(dates))
    for i, ds in enumerate(dates):
        if not ds:
            continue
        try:
            d = date.fromisoformat(ds)
        except ValueError:
            continue
        delta = (ref - d).days
        if delta > 0:
            w[i] = math.exp(-xi * delta)
    return w


def fit(matches: list[dict] | None = None, min_matches: int = MIN_MATCHES,
        keep_codes: set[str] | None = None,
        reference_date: str | None = None,
        half_life_days: float | None = None,
        fit_corrections: bool = False,
        use_xg: bool = False,
        competitive_only: bool = False) -> DCParams:
    """Fit Dixon-Coles by MLE. Returns DCParams.

    If reference_date and half_life_days are given, apply exponential recency
    weighting (standard DC) so recent matches count more.

    If ``fit_corrections`` is True, also fit the two post-hoc corrections on the
    same ``matches``: ``draw_inflate`` (diagonal inflation) and ``deflate_away``
    (cross-confederation away-win deflation). These are stored on the returned
    DCParams and applied by score_matrix / predict_1x2. Disabled by default to
    keep the base MLE fast; PoissonModel.fit() enables it.

    If ``use_xg`` is True and the match dicts carry ``team1_xg`` / ``team2_xg``
    fields, the likelihood blends two channels:

      * Matches with xG  → quasi-Poisson NLL ``xG·log(λ) - λ`` (the
        ``log(Γ(xG+1))`` term is parameter-free and dropped). xG is a
        continuous expectation, so the Dixon-Coles low-score tau correction
        does NOT apply (tau is a discrete-goal dependency fix).
      * Matches without xG → standard DC Poisson with tau (integer goals).

    rho_dc is estimated ONLY from the non-xG matches (correct: tau operates on
    discrete goal counts). When use_xg=False (default), behavior is identical
    to the original goals-only fit.
    """
    if matches is None:
        matches = json.loads(HIST_FILE.read_text(encoding="utf-8"))["matches"]
    if competitive_only:
        matches = [m for m in matches if m.get("tournament", "") != "F"]
    code_index = build_team_index(matches, min_matches, keep_codes)
    T = len(code_index)
    home_idx, away_idx, gh, ga, xg_h, xg_a, has_xg, dates = _prepare_arrays(
        matches, code_index, use_xg=use_xg)
    N = len(gh)

    if reference_date and half_life_days:
        weights = recency_weights(dates, reference_date, half_life_days)
    else:
        weights = np.ones(N)

    # Theta layout:
    #   [0:T-1]            log_attack (free; last = -sum)
    #   [T-1:2T-2]         log_defense (free; last = -sum)
    #   [2T-2]             log_mu
    #   [2T-1]             log_rho
    #   [2T]               rho_dc
    n_free = 2 * (T - 1) + 3

    def unpack(theta: np.ndarray):
        la = np.empty(T)
        la[:T - 1] = theta[:T - 1]
        la[T - 1] = -theta[:T - 1].sum()
        ld = np.empty(T)
        ld[:T - 1] = theta[T - 1:2 * T - 2]
        ld[T - 1] = -theta[T - 1:2 * T - 2].sum()
        log_mu = theta[2 * T - 2]
        log_rho = theta[2 * T - 1]
        rho_dc = theta[2 * T]
        return la, ld, log_mu, log_rho, rho_dc

    def neg_ll(theta: np.ndarray) -> float:
        la, ld, log_mu, log_rho, rho_dc = unpack(theta)
        mu = math.exp(log_mu); rho = math.exp(log_rho)
        attack = np.exp(la); defense = np.exp(ld)
        lam_h = mu * attack[home_idx] * defense[away_idx] * rho
        lam_a = mu * attack[away_idx] * defense[home_idx] / rho

        total = 0.0
        # xG channel: quasi-Poisson (xG·log(λ) - λ; gammaln term is
        # parameter-free and dropped). No tau — xG is continuous.
        if use_xg and has_xg.any():
            ix = has_xg
            log_lam_h = np.log(np.clip(lam_h[ix], 1e-10, None))
            log_lam_a = np.log(np.clip(lam_a[ix], 1e-10, None))
            log_p_xg = (xg_h[ix] * log_lam_h - lam_h[ix] +
                        xg_a[ix] * log_lam_a - lam_a[ix])
            total = total - float(np.sum(weights[ix] * log_p_xg))
        # Goals channel: standard DC Poisson with tau. rho_dc is estimated
        # from this channel only (tau is a discrete-goal correction).
        no_xg = ~has_xg if use_xg else np.ones(N, dtype=bool)
        if no_xg.any():
            tau = _dc_tau_vec(gh[no_xg], ga[no_xg], lam_h[no_xg],
                              lam_a[no_xg], rho_dc)
            if np.any(tau <= 0):
                return 1e9
            pmf_h = poisson.pmf(gh[no_xg], lam_h[no_xg])
            pmf_a = poisson.pmf(ga[no_xg], lam_a[no_xg])
            p = np.clip(tau * pmf_h * pmf_a, 1e-300, None)
            total = total - float(np.sum(weights[no_xg] * np.log(p)))
        return total

    # Initial guess: mu = mean goals, rho ~ 1.35 (home boost), rho_dc = 0.
    mean_goals = float(np.mean(np.concatenate([gh, ga])))
    x0 = np.zeros(n_free)
    x0[2 * T - 2] = math.log(mean_goals)
    x0[2 * T - 1] = math.log(1.35)
    x0[2 * T] = 0.0

    res = minimize(neg_ll, x0, method="L-BFGS-B",
                   options={"maxiter": 500, "ftol": 1e-7, "gtol": 1e-5})
    la, ld, log_mu, log_rho, rho_dc = unpack(res.x)
    team_codes = [c for c, _ in sorted(code_index.items(), key=lambda kv: kv[1])]
    params = DCParams(
        team_codes=team_codes, code_index=code_index,
        log_attack=la, log_defense=ld,
        log_mu=float(log_mu), log_rho=float(log_rho), rho_dc=float(rho_dc),
        n_matches_used=N, nll=float(res.fun),
    )
    if fit_corrections:
        params.draw_inflate = fit_draw_inflate(matches, params)
        params.deflate_away = fit_deflate_away(matches, params)
    return params


def score_matrix(params: DCParams, home: str, away: str,
                 rho: float | None = None, max_goals: int = MAX_GOALS,
                 draw_inflate: float | None = None,
                 deflate_away: float | None = None,
                 cross_conf: bool = False) -> np.ndarray:
    """P(home=i, away=j) matrix [max_goals x max_goals]. `home`/`away` are codes.

    Two optional post-hoc corrections (applied after DC tau, before renormalize):
      * draw_inflate  — multiply all diagonal cells (P(i,i)) by this factor.
        Defaults to ``params.draw_inflate``. Inflates every draw score, not just
        0:0/1:1 (which tau already handles). Fixes the independence-assumption
        under-estimation of 2:2, 3:3, ...
      * deflate_away  — when ``cross_conf`` is True, multiply away-win cells
        (i<j) by this factor. Defaults to ``params.deflate_away``. Corrects the
        cross-confederation away-win over-estimation (strong vs weak federation).
    """
    di = params.draw_inflate if draw_inflate is None else float(draw_inflate)
    da = params.deflate_away if deflate_away is None else float(deflate_away)
    hi = params.code_index[home]
    ai = params.code_index[away]
    lam_h, lam_a = params.lam(hi, ai, rho=rho)
    i = np.arange(max_goals)[:, None]
    j = np.arange(max_goals)[None, :]
    pmf = poisson.pmf(i, lam_h) * poisson.pmf(j, lam_a)
    # Apply DC tau to the four low-score cells.
    pmf[0, 0] *= _dc_tau(0, 0, lam_h, lam_a, params.rho_dc)
    pmf[0, 1] *= _dc_tau(0, 1, lam_h, lam_a, params.rho_dc)
    pmf[1, 0] *= _dc_tau(1, 0, lam_h, lam_a, params.rho_dc)
    pmf[1, 1] *= _dc_tau(1, 1, lam_h, lam_a, params.rho_dc)
    # Diagonal inflation: lift all draw scores (fixes 2:2/3:3 under-estimation).
    if di != 1.0:
        pmf[np.diag_indices(max_goals)] *= di
    # Cross-confederation away-win deflation: lower P(i<j) for inter-conf matches.
    if cross_conf and da != 1.0:
        pmf[np.triu_indices(max_goals, k=1)] *= da
    # Renormalize (truncation + tau + corrections all perturb the sum).
    s = pmf.sum()
    return pmf / s


def predict_1x2(params: DCParams, home: str, away: str,
                rho: float | None = None,
                cross_conf: bool = False) -> tuple[float, float, float]:
    """Return (p_home, p_draw, p_away). rho=None → use fitted (home advantage).
    Pass rho=RHO_NEUTRAL for neutral matches. Pass cross_conf=True for
    cross-confederation matches (applies params.deflate_away)."""
    sm = score_matrix(params, home, away, rho=rho, cross_conf=cross_conf)
    p_home = float(np.tril(sm, -1).sum())  # i > j
    p_draw = float(np.trace(sm))
    p_away = float(np.triu(sm, 1).sum())   # i < j
    return p_home, p_draw, p_away


def fit_draw_inflate(matches: list[dict], params: DCParams,
                     rho: float | None = None, max_goals: int = MAX_GOALS,
                     lam_min: float = 1.0, lam_max: float = 1.5,
                     step: float = 0.01) -> float:
    """Grid-search the diagonal inflation factor maximizing draw log-likelihood.

    For each match the base score matrix (draw_inflate=1.0, deflate_away=1.0)
    is computed once; then a 1-D grid search over ``lam`` maximizes::

        f(lam) = N_draws * log(lam) - Σ_m log(1 + (lam-1) * D0_m)

    where D0_m is the base draw probability of match m. Returns 1.0 if there
    are no draws or no usable matches.
    """
    n_draws = 0
    d0_list: list[float] = []
    for m in matches:
        g1, g2 = m.get("team1_goals"), m.get("team2_goals")
        if g1 is None or g2 is None:
            continue
        h = m["team1_code"] if m["team1_code"] in params.code_index else ROW_CODE
        a = m["team2_code"] if m["team2_code"] in params.code_index else ROW_CODE
        if h == ROW_CODE and a == ROW_CODE:
            continue
        base = score_matrix(params, h, a, rho=rho, max_goals=max_goals,
                            draw_inflate=1.0, deflate_away=1.0, cross_conf=False)
        d0_list.append(float(np.trace(base)))
        if g1 == g2:
            n_draws += 1
    if not d0_list or n_draws == 0:
        return 1.0
    best_lam, best_f = 1.0, 0.0  # f(1.0) = 0 by construction
    k = 0
    while True:
        lam = lam_min + k * step
        if lam > lam_max + 1e-9:
            break
        if lam <= 0:
            k += 1
            continue
        f = n_draws * math.log(lam)
        for d0 in d0_list:
            f -= math.log(1.0 + (lam - 1.0) * d0)
        if f > best_f:
            best_f, best_lam = f, lam
        k += 1
    return best_lam


def fit_deflate_away(matches: list[dict], params: DCParams,
                     draw_inflate: float | None = None, rho: float | None = None,
                     max_goals: int = MAX_GOALS, delta_min: float = 0.5,
                     delta_max: float = 1.0, step: float = 0.01) -> float:
    """Grid-search the cross-confederation away-win deflation factor.

    Only matches where the two teams belong to different FIFA confederations
    (per FEDERATIONS) contribute. For each such match the base matrix with
    ``draw_inflate`` applied (but deflate_away=1.0) is computed, then a 1-D
    grid search over ``delta`` maximizes::

        f(delta) = N_away_wins * log(delta) - Σ_m log(1 + (delta-1) * A0_m)

    where A0_m is the base away-win probability of match m. Returns 1.0 if
    there are no usable cross-confederation matches or no away wins.
    """
    di = params.draw_inflate if draw_inflate is None else float(draw_inflate)
    n_away = 0
    a0_list: list[float] = []
    for m in matches:
        g1, g2 = m.get("team1_goals"), m.get("team2_goals")
        if g1 is None or g2 is None:
            continue
        if not is_cross_confederation(m.get("team1_name", ""), m.get("team2_name", "")):
            continue
        h = m["team1_code"] if m["team1_code"] in params.code_index else ROW_CODE
        a = m["team2_code"] if m["team2_code"] in params.code_index else ROW_CODE
        if h == ROW_CODE and a == ROW_CODE:
            continue
        base = score_matrix(params, h, a, rho=rho, max_goals=max_goals,
                            draw_inflate=di, deflate_away=1.0, cross_conf=False)
        a0_list.append(float(np.triu(base, 1).sum()))
        if g1 < g2:
            n_away += 1
    if not a0_list or n_away == 0:
        return 1.0
    best_delta, best_f = 1.0, 0.0  # f(1.0) = 0
    k = 0
    while True:
        delta = delta_min + k * step
        if delta > delta_max + 1e-9:
            break
        if delta <= 0:
            k += 1
            continue
        f = n_away * math.log(delta)
        for a0 in a0_list:
            f -= math.log(1.0 + (delta - 1.0) * a0)
        if f > best_f:
            best_f, best_delta = f, delta
        k += 1
    return best_delta


def host_rho(params: DCParams, home_team: str) -> float:
    """WC 2026: hosts get fitted rho, others neutral."""
    if home_team in WC_2026_HOSTS:
        return params.rho
    return RHO_NEUTRAL


@dataclass
class PoissonModel:
    params: DCParams
    name_to_code: dict[str, str] = field(default_factory=dict)

    @classmethod
    def fit(cls, matches: list[dict] | None = None,
            reference_date: str | None = None,
            half_life_days: float | None = None,
            fit_corrections: bool = True,
            use_xg: bool = False,
            competitive_only: bool = False) -> "PoissonModel":
        elo = json.loads(ELO_FILE.read_text(encoding="utf-8"))["teams"]
        keep_codes = {v["code"] for v in elo.values()}
        params = fit(matches=matches, keep_codes=keep_codes,
                     reference_date=reference_date, half_life_days=half_life_days,
                     fit_corrections=fit_corrections, use_xg=use_xg,
                     competitive_only=competitive_only)
        name_to_code = {name: v["code"] for name, v in elo.items()}
        return cls(params=params, name_to_code=name_to_code)

    def predict(self, home: str, away: str, neutral: bool = False,
                cross_conf: bool | None = None) -> tuple[float, float, float]:
        h = self.name_to_code.get(home, home)
        a = self.name_to_code.get(away, away)
        rho = RHO_NEUTRAL if neutral else host_rho(self.params, home)
        if cross_conf is None:
            cross_conf = is_cross_confederation(home, away)
        return predict_1x2(self.params, h, a, rho=rho, cross_conf=cross_conf)
