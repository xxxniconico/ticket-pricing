"""Kelly criterion stake sizing (plan §5).

f* = (b*p - q) / b    where b = odds-1, p = model prob, q = 1-p
f  = f* / 2           (1/2 Kelly — plan §5.1, reduces variance)
f  = min(f, cap)      (single-bet hard cap — plan §5.2)

Caps tightened from plan defaults (5% → 3%) after P3 calibration showed
the model is only marginally calibrated on 32 matches.
"""

from __future__ import annotations

HALF_KELLY = 0.5
SINGLE_BET_CAP = 0.03   # tightened from plan's 0.05
DAILY_CAP = 0.15        # plan §5.3


def kelly_fraction(p: float, odds: float, half: float = HALF_KELLY,
                   cap: float = SINGLE_BET_CAP) -> float:
    """1/2 Kelly stake fraction, capped. Returns 0 if no edge or odds invalid."""
    if odds <= 1.0 or p <= 0.0 or p >= 1.0:
        return 0.0
    b = odds - 1.0
    q = 1.0 - p
    f_star = (b * p - q) / b
    f = f_star * half
    if f <= 0.0:
        return 0.0
    return min(f, cap)


def apply_daily_cap(bets: list[dict], daily_cap: float = DAILY_CAP) -> list[dict]:
    """Sort by EV desc, truncate cumulative stake to daily cap. Mutates copies."""
    ranked = sorted(bets, key=lambda x: -x["ev"])
    cumulative = 0.0
    result = []
    for bet in ranked:
        remaining = daily_cap - cumulative
        if remaining <= 0:
            bet = {**bet, "kelly_fraction": 0.0, "stake": 0.0,
                   "note": "daily cap reached"}
        elif bet["kelly_fraction"] > remaining:
            bet = {**bet, "kelly_fraction": remaining, "stake": remaining,
                   "note": "truncated by daily cap"}
            cumulative = daily_cap
        else:
            cumulative += bet["kelly_fraction"]
        result.append(bet)
    return result
