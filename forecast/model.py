"""Ridge regression on standardised features, plus the bootstrap prior.

Deliberately boring — see DESIGN.md §6.3. On weekly data gradient boosting beat
ridge by 0.003 skill, which is noise, and cost the coefficient inspectability
that matters when explaining a bad call.

Bumping MODEL_VERSION is how you change the model. Old forecast rows stay
exactly as written (§3 invariant 1); the version string is what lets the
scorer keep the populations apart.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Re-exported so callers that already import model keep working; the single
# definition lives in thresholds.py, which needs it without pulling in numpy.
from thresholds import prob_greater_than  # noqa: F401

MODEL_VERSION = "ridge-a5-v1"

# Below this many complete training pairs, forecast from the prior instead.
MIN_TRAIN = 30

ALPHA = 5.0

# --- Prior constants -------------------------------------------------------
# Both of these are guesses, and are labelled as such deliberately.
#
# PRIOR_SIGMA_C comes from weekly EIA variance, which pins the daily figure
# only loosely: roughly 0.9-1.5 cents depending on the assumed daily
# autocorrelation rho. **Rho has never been measured on daily data.** Measuring
# it is the main scientific output of the first two months — DESIGN.md §9, M5.
PRIOR_SIGMA_C = 1.0

# Pure placeholder. Shrinks the recent-mean-change toward zero because a naive
# 7-day mean overreacts during the bootstrap. It has no empirical basis and
# should die at M5.
PRIOR_SHRINK = 0.35

# sigma can never sensibly be zero — a degenerate predictive distribution
# scores infinitely badly the first time it is wrong.
MIN_SIGMA_C = 0.25


@dataclass
class Prediction:
    mu_cents: float
    sigma_cents: float
    n_train: int
    mode: str  # 'prior' | 'model'


@dataclass
class _Fit:
    mean_x: np.ndarray
    scale_x: np.ndarray
    mean_y: float
    weights: np.ndarray

    def predict(self, x: np.ndarray) -> float:
        z = (np.asarray(x, dtype=float) - self.mean_x) / self.scale_x
        return float(self.mean_y + z @ self.weights)


def _fit_ridge(X: np.ndarray, y: np.ndarray, alpha: float = ALPHA) -> _Fit:
    mean_x = X.mean(axis=0)
    scale_x = X.std(axis=0)
    # A constant column carries no information; scaling it by 1 leaves it at
    # zero after centring, so its weight is irrelevant rather than infinite.
    scale_x = np.where(scale_x < 1e-12, 1.0, scale_x)

    Z = (X - mean_x) / scale_x
    mean_y = float(y.mean())
    gram = Z.T @ Z + alpha * np.eye(Z.shape[1])
    weights = np.linalg.solve(gram, Z.T @ (y - mean_y))
    return _Fit(mean_x=mean_x, scale_x=scale_x, mean_y=mean_y, weights=weights)


def _out_of_sample_sigma(X: np.ndarray, y: np.ndarray) -> float | None:
    """Predictive sd from an expanding-window backtest.

    §10 rejected quantile GBM intervals (80% nominal realised 66.8%) in favour
    of conformal intervals from rolling empirical out-of-sample errors (77.3%).
    This is the Gaussian analogue: refit at each step on strictly prior data,
    collect the honest one-step errors, take their spread. In-sample residuals
    would understate sigma and manufacture overconfidence, which §7's
    overconfidence check would then dutifully flag on our own model.
    """
    residuals = []
    for cut in range(MIN_TRAIN, len(y)):
        fit = _fit_ridge(X[:cut], y[:cut])
        residuals.append(y[cut] - fit.predict(X[cut]))

    if len(residuals) < 10:
        return None
    return float(np.std(residuals, ddof=1))


def predict_from_prior(recent: list[float]) -> Prediction:
    """Bootstrap forecast: a shrunk mean of recent daily changes."""
    mu = PRIOR_SHRINK * (sum(recent) / len(recent)) if recent else 0.0
    return Prediction(
        mu_cents=mu,
        sigma_cents=PRIOR_SIGMA_C,
        n_train=len(recent),
        mode="prior",
    )


def predict(
    rows: list[list[float]], targets: list[float], x_now: list[float]
) -> Prediction:
    """Fitted forecast. Callers must have checked len(targets) >= MIN_TRAIN."""
    X = np.asarray(rows, dtype=float)
    y = np.asarray(targets, dtype=float)

    fit = _fit_ridge(X, y)
    mu = fit.predict(np.asarray(x_now, dtype=float))

    sigma = _out_of_sample_sigma(X, y)
    if sigma is None:
        # Not enough backtest points yet. In-sample residuals understate the
        # true spread, so inflate rather than quote them straight.
        in_sample = [y[i] - fit.predict(X[i]) for i in range(len(y))]
        sigma = float(np.std(in_sample, ddof=1)) * 1.25

    return Prediction(
        mu_cents=float(mu),
        sigma_cents=max(float(sigma), MIN_SIGMA_C),
        n_train=len(y),
        mode="model",
    )


def coefficients(rows: list[list[float]], targets: list[float]) -> list[float]:
    """Standardised coefficients, for explaining a call after the fact."""
    fit = _fit_ridge(np.asarray(rows, dtype=float), np.asarray(targets, dtype=float))
    return [float(w) for w in fit.weights]
