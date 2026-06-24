"""Elo rating system → 1X2 probability.

Uses eloratings.net ratings directly (no history rebuild needed, per plan §3.1).
The Elo expected score E_home encodes P(home win) + 0.5*P(draw). We decompose it
into 1X2 using a parabolic draw model whose peak c is calibrated from history.

Draw model:
    p_draw = c * (1 - (2*E - 1)**2)        # peaks at E=0.5, zero at E in {0,1}
    p_home = E - 0.5 * p_draw
    p_away = 1 - E - 0.5 * p_draw

HFA (home field advantage) in Elo points:
    2026 WC co-hosts Mexico / USA / Canada: 65 (per plan §3.1)
    neutral matches: 0
"""

from __future__ import annotations

import json
import math
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ELO_FILE = PROJECT_ROOT / "data/raw/elo/elo_ratings_20260620.json"
HIST_FILE = PROJECT_ROOT / "data/raw/historical/intl_results_2022_2026.json"

# Elo rating points equivalent to a factor-of-10 in expected score.
ELO_SCALE = 400.0
# Home-field advantage in Elo points (eloratings.net convention).
HFA_HOST = 65.0
HFA_NEUTRAL = 0.0
# 2026 WC co-hosts (by canonical team name).
WC_2026_HOSTS = {"Mexico", "United States", "Canada"}

# Default draw peak coefficient; overwritten by calibrate_draw_coefficient().
DEFAULT_DRAW_C = 0.30


def load_ratings(path: Path = ELO_FILE) -> dict[str, dict]:
    """Return {team_name: {code, elo, rank, ...}}."""
    return json.loads(path.read_text(encoding="utf-8"))["teams"]


def _code_to_name(ratings: dict[str, dict]) -> dict[str, str]:
    return {v["code"]: name for name, v in ratings.items()}


def expected_score(home_elo: float, away_elo: float, hfa: float = HFA_NEUTRAL) -> float:
    """Elo expected points for home team: P(win) + 0.5*P(draw)."""
    exponent = (away_elo - home_elo - hfa) / ELO_SCALE
    return 1.0 / (1.0 + 10.0 ** exponent)


def predict_1x2(home_elo: float, away_elo: float, hfa: float = HFA_NEUTRAL,
                draw_c: float = DEFAULT_DRAW_C) -> tuple[float, float, float]:
    """Return (p_home_win, p_draw, p_away_win)."""
    e = expected_score(home_elo, away_elo, hfa)
    d = draw_c * (1.0 - (2.0 * e - 1.0) ** 2)
    p_home = e - 0.5 * d
    p_away = 1.0 - e - 0.5 * d
    # Numerical guard against tiny negatives from float roundoff.
    p_home = max(p_home, 0.0)
    p_away = max(p_away, 0.0)
    s = p_home + d + p_away
    return p_home / s, d / s, p_away / s


def host_hfa(home_team: str) -> float:
    """HFA for a WC 2026 match given the home team's canonical name."""
    return HFA_HOST if home_team in WC_2026_HOSTS else HFA_NEUTRAL


def calibrate_draw_coefficient(history_path: Path = HIST_FILE) -> float:
    """Fit draw peak c by maximizing 1X2 log-likelihood over history.

    Elo before each match is recovered from elo_after + rating change.
    eloratings.net updates are zero-sum (E1+E2=1, S1+S2=1 → ΔR1+ΔR2=0),
    so team2's change = -team1's change.
    """
    data = json.loads(history_path.read_text(encoding="utf-8"))
    matches = data["matches"]
    # Precompute (elo_home_before, elo_away_before, outcome) where
    # outcome in {1=home win, 0.5=draw, 0=away win}.
    samples: list[tuple[float, float, float]] = []
    for m in matches:
        g1, g2 = m["team1_goals"], m["team2_goals"]
        if g1 is None or g2 is None:
            continue
        r1_after = m["team1_elo_after"]
        r2_after = m["team2_elo_after"]
        rchg1 = m.get("team1_rating_change")
        if r1_after is None or r2_after is None or rchg1 is None:
            continue
        r1_before = r1_after - rchg1
        r2_before = r2_after + rchg1  # zero-sum: rchg2 = -rchg1
        # HFA: team1 is home unless venue is a third country (neutral).
        venue = m.get("venue", "")
        hfa = HFA_HOST if not venue else HFA_NEUTRAL
        outcome = 1.0 if g1 > g2 else (0.5 if g1 == g2 else 0.0)
        samples.append((r1_before, r2_before, hfa, outcome))

    def neg_ll(c: float) -> float:
        ll = 0.0
        for r1, r2, hfa, outcome in samples:
            ph, pd, pa = predict_1x2(r1, r2, hfa, draw_c=c)
            # outcome maps to the realized result's probability.
            if outcome == 1.0:
                p = ph
            elif outcome == 0.5:
                p = pd
            else:
                p = pa
            if p <= 0:
                return 1e9
            ll += math.log(p)
        return -ll

    # Grid search (1-D, cheap) then refine.
    best_c, best_nll = DEFAULT_DRAW_C, neg_ll(DEFAULT_DRAW_C)
    c = 0.10
    while c <= 0.60:
        nll = neg_ll(c)
        if nll < best_nll:
            best_nll, best_c = nll, c
        c += 0.005
    return round(best_c, 3)


class EloModel:
    """Stateful wrapper: ratings + calibrated draw coefficient."""

    def __init__(self, draw_c: float | None = None, ratings_path: Path = ELO_FILE,
                 history_path: Path = HIST_FILE):
        self.ratings = load_ratings(ratings_path)
        self.code_to_name = _code_to_name(self.ratings)
        if draw_c is None:
            self.draw_c = DEFAULT_DRAW_C  # calibrate() to fit
        else:
            self.draw_c = draw_c
        self._history_path = history_path

    def calibrate(self) -> float:
        self.draw_c = calibrate_draw_coefficient(self._history_path)
        return self.draw_c

    def elo_of(self, team: str) -> int:
        """team may be a canonical name or a 2-letter code."""
        if team in self.ratings:
            return self.ratings[team]["elo"]
        name = self.code_to_name.get(team)
        if name is None:
            raise KeyError(f"unknown team: {team}")
        return self.ratings[name]["elo"]

    def predict(self, home: str, away: str, hfa: float | None = None) -> tuple[float, float, float]:
        """1X2 probabilities. If hfa is None, infer from home team (WC hosts only)."""
        if hfa is None:
            hfa = host_hfa(home) if home in self.ratings else HFA_NEUTRAL
        return predict_1x2(self.elo_of(home), self.elo_of(away), hfa, self.draw_c)
