"""Blend Elo + Poisson 1X2 probabilities (plan §3.4).

Final model probability is a weighted average:
    p_model = w_elo * p_elo + w_poisson * p_poisson
with w_elo=0.4, w_poisson=0.6 (Poisson is finer-grained).

If the two models disagree by more than INCONSISTENCY_THRESHOLD on the home-win
probability, the match is flagged for lower confidence (the plan recommends
down-sizing or skipping).
"""

from __future__ import annotations

from dataclasses import dataclass

W_ELO_DEFAULT = 0.4
W_POISSON_DEFAULT = 0.6
INCONSISTENCY_THRESHOLD = 0.15  # plan §3.4: flag if |p_elo - p_poisson| > 15% (relaxed from 8%)


@dataclass
class BlendedProb:
    p_home: float
    p_draw: float
    p_away: float
    p_elo_home: float
    p_poisson_home: float
    inconsistent: bool
    elo_poisson_gap: float

    @property
    def max_prob(self) -> float:
        return max(self.p_home, self.p_draw, self.p_away)


def blend(p_elo: tuple[float, float, float],
          p_poisson: tuple[float, float, float],
          w_elo: float = W_ELO_DEFAULT,
          w_poisson: float = W_POISSON_DEFAULT,
          threshold: float = INCONSISTENCY_THRESHOLD) -> BlendedProb:
    """Blend two 1X2 distributions and flag inconsistency."""
    s = w_elo + w_poisson
    w_elo /= s
    w_poisson /= s
    ph = w_elo * p_elo[0] + w_poisson * p_poisson[0]
    pd = w_elo * p_elo[1] + w_poisson * p_poisson[1]
    pa = w_elo * p_elo[2] + w_poisson * p_poisson[2]
    # Renormalize (guard against float drift).
    n = ph + pd + pa
    ph, pd, pa = ph / n, pd / n, pa / n
    gap = abs(p_elo[0] - p_poisson[0])
    return BlendedProb(
        p_home=ph, p_draw=pd, p_away=pa,
        p_elo_home=p_elo[0], p_poisson_home=p_poisson[0],
        inconsistent=gap > threshold, elo_poisson_gap=gap,
    )


def blended_predict(elo_model, poisson_model, home: str, away: str,
                    neutral: bool = False) -> BlendedProb:
    """Convenience: predict from both sub-models and blend.

    `neutral` applies to Poisson (rho=1). Elo HFA is inferred from home team
    (WC hosts only); pass neutral=False for host matches, True otherwise.
    """
    import wc_betting.models.elo as elo_mod
    hfa = elo_mod.HFA_NEUTRAL if neutral else None  # None → infer from home team
    p_elo = elo_model.predict(home, away, hfa=hfa)
    p_poisson = poisson_model.predict(home, away, neutral=neutral)
    return blend(p_elo, p_poisson)
