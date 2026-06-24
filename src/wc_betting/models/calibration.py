"""Platt scaling calibration for 1X2 probabilities.

Corrects the S-shaped miscalibration observed in OOS WC 2026 matches:
  * mid-range home-win probabilities (0.30-0.60) are under-estimated
  * extreme home-win probabilities (>0.80) are over-estimated

Platt scaling fits a sigmoid ``p_calib = 1/(1+exp(a + b*p_raw))`` per class.
With the constraint ``b < 0`` the map is monotone increasing in ``p_raw`` (higher
raw probability -> higher calibrated probability), so the probability ordering
is preserved while the S-shape is corrected.

Three-class (1X2) extension: fit (a, b) independently for H/D/A on the OOS
matches, then renormalize so p_h + p_d + p_a = 1.

This is a post-hoc probability-layer correction; it is complementary to the
matrix-layer corrections (draw_inflate, deflate_away) in poisson.py. See
``docs/research/betting_model_theory.md`` §7 for the math.

Parameters are persisted to ``data/processed/calibration_params.json`` so the
sporttery scanner and dashboard can apply the same calibration without refitting.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PARAMS_FILE = PROJECT_ROOT / "data/processed/calibration_params.json"

# L2 regularisation strength (small — prevents extreme transforms on the
# 34-match OOS sample without materially shrinking the fit).
_REG_LAMBDA = 0.01
# Bounds on (a, b): a in [-10, 10], b in [-5, -0.1].
# b < 0 strictly (not 0) ensures the calibration is responsive to the input
# probability. b=0 makes p_cal = sigmoid(-a) = constant, which is useless
# (e.g., D class fitted to b=0 → all draw probs become 0.324 regardless of
# the model's raw estimate).
_A_BOUNDS = (-10.0, 10.0)
_B_BOUNDS = (-5.0, -0.1)


def _sigmoid(z: float) -> float:
    """Numerically stable sigmoid."""
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


def _sigmoid_arr(z: np.ndarray) -> np.ndarray:
    """Vectorised numerically-stable sigmoid."""
    out = np.empty_like(z, dtype=float)
    pos = z >= 0
    out[pos] = 1.0 / (1.0 + np.exp(-z[pos]))
    ez = np.exp(z[~pos])
    out[~pos] = ez / (1.0 + ez)
    return out


def apply_platt(p_raw: float, a: float, b: float) -> float:
    """Apply Platt scaling: p_calib = 1/(1+exp(a + b*p_raw)).

    With b < 0 this is monotone increasing in p_raw.
    """
    return _sigmoid(-(a + b * p_raw))


def fit_platt_single(probs_raw: np.ndarray, outcomes: np.ndarray,
                     a0: float = 0.0, b0: float = -1.0) -> tuple[float, float]:
    """Fit (a, b) for one binary outcome via L-BFGS-B with b<0 constraint.

    Convention (matches apply_platt):  p_calib = 1/(1+exp(a + b*p_raw))
    which is monotone increasing in p_raw when b < 0.

    ``probs_raw`` — model probabilities for this class (shape [N]).
    ``outcomes``  — 0/1 indicator for this class (shape [N]).

    Minimises cross-entropy + L2 reg:
        L = -Σ [y*log(pc) + (1-y)*log(1-pc)] + λ*(a²+b²),  pc = 1/(1+exp(a+b*p))
    """
    p = np.asarray(probs_raw, dtype=float)
    y = np.asarray(outcomes, dtype=float)
    n = len(p)
    if n == 0:
        return 0.0, -1.0

    def _pc(theta: np.ndarray) -> np.ndarray:
        a, b = float(theta[0]), float(theta[1])
        # pc = 1/(1+exp(a+bp)) = sigmoid(-(a+bp)); use stable sigmoid.
        return _sigmoid_arr(-(a + b * p))

    def neg_ll(theta: np.ndarray) -> float:
        pc = np.clip(_pc(theta), 1e-12, 1.0 - 1e-12)
        ce = -float(np.sum(y * np.log(pc) + (1.0 - y) * np.log(1.0 - pc)))
        reg = _REG_LAMBDA * (float(theta[0]) ** 2 + float(theta[1]) ** 2)
        return ce + reg

    def grad(theta: np.ndarray) -> np.ndarray:
        a, b = float(theta[0]), float(theta[1])
        pc = _pc(theta)
        # dL/da = Σ (y - pc); dL/db = Σ p*(y - pc)  for pc = 1/(1+exp(a+bp)).
        diff = y - pc
        ga = float(np.sum(diff)) + 2.0 * _REG_LAMBDA * a
        gb = float(np.sum(diff * p)) + 2.0 * _REG_LAMBDA * b
        return np.array([ga, gb])

    res = minimize(neg_ll, np.array([a0, b0]), jac=grad, method="L-BFGS-B",
                   bounds=[_A_BOUNDS, _B_BOUNDS],
                   options={"maxiter": 200, "ftol": 1e-10, "gtol": 1e-8})
    return float(res.x[0]), float(res.x[1])


def fit_platt(probs_raw: list[tuple[float, float, float]],
              outcomes: list[tuple[int, int, int]]
              ) -> dict[str, tuple[float, float]]:
    """Fit Platt (a, b) for each of H/D/A classes.

    ``probs_raw``  — list of (p_h, p_d, p_a) raw model probabilities.
    ``outcomes``   — list of (h, d, a) one-hot actual outcomes.

    Returns ``{"H": (a_h, b_h), "D": (a_d, b_d), "A": (a_a, b_a)}``.
    """
    arr = np.array(probs_raw, dtype=float)  # [N, 3]
    out = np.array(outcomes, dtype=float)   # [N, 3]
    classes = ["H", "D", "A"]
    params: dict[str, tuple[float, float]] = {}
    for i, cls in enumerate(classes):
        a, b = fit_platt_single(arr[:, i], out[:, i])
        params[cls] = (a, b)
    return params


def calibrate_1x2(p_h: float, p_d: float, p_a: float,
                  params: dict[str, tuple[float, float]]
                  ) -> tuple[float, float, float]:
    """Apply Platt scaling to (p_h, p_d, p_a) and renormalize.

    ``params`` is the dict returned by fit_platt: {"H": (a,b), "D": (a,b), "A": (a,b)}.
    Returns calibrated (p_h', p_d', p_a') summing to 1.0.
    """
    ph = apply_platt(p_h, *params["H"])
    pd = apply_platt(p_d, *params["D"])
    pa = apply_platt(p_a, *params["A"])
    s = ph + pd + pa
    if s <= 0:
        return p_h, p_d, p_a
    return ph / s, pd / s, pa / s


def save_params(params: dict[str, tuple[float, float]],
                path: Path = PARAMS_FILE, meta: dict | None = None) -> None:
    """Persist Platt params to JSON. Tuples become [a, b] lists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    out: dict = {
        "method": "platt_scaling",
        "classes": {k: list(v) for k, v in params.items()},
    }
    if meta:
        out["meta"] = meta
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")


def load_params(path: Path = PARAMS_FILE) -> dict[str, tuple[float, float]] | None:
    """Load Platt params from JSON. Returns None if file missing/invalid."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    classes = data.get("classes") or data
    out: dict[str, tuple[float, float]] = {}
    for k in ("H", "D", "A"):
        v = classes.get(k)
        if isinstance(v, list) and len(v) == 2:
            out[k] = (float(v[0]), float(v[1]))
    if len(out) != 3:
        return None
    return out


def is_monotone(params: dict[str, tuple[float, float]]) -> bool:
    """Sanity check: each class's b < 0 (so apply_platt is monotone increasing)."""
    return all(b < 0 for (a, b) in params.values())


if __name__ == "__main__":
    # Self-test: simulate an over-confident model (probabilities spread too
    # wide), which is the real OOS pattern (tails over-estimated). Platt should
    # compress them back toward 0.5, i.e. b in (-4, 0) (flatter than identity).
    rng = np.random.default_rng(42)
    n = 500
    p_true = rng.uniform(0.1, 0.9, n)
    # Expand away from 0.5 to simulate over-confidence.
    p_raw = np.clip(0.5 + 1.35 * (p_true - 0.5), 0.01, 0.99)
    y = (rng.uniform(size=n) < p_true).astype(float)
    a, b = fit_platt_single(p_raw, y)
    print(f"synthetic fit: a={a:.3f} b={b:.3f} (expect b<0, |b|<4 for compression)")
    print(f"  monotone increasing: {b < 0}")
    # Check the compression: extremes should move toward 0.5.
    for pr in [0.1, 0.3, 0.5, 0.7, 0.9]:
        print(f"  p_raw={pr:.2f} -> p_calib={apply_platt(pr, a, b):.3f}")
    # Renormalization sanity for 1X2.
    params = {"H": (a, b), "D": (0.0, -2.0), "A": (-0.5, -1.5)}
    ph, pd, pa = calibrate_1x2(0.5, 0.3, 0.2, params)
    print(f"  calibrate_1x2(0.5,0.3,0.2) -> ({ph:.3f},{pd:.3f},{pa:.3f}) sum={ph+pd+pa:.4f}")
