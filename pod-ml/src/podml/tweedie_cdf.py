"""Read quantiles off the Tweedie predictive CDF — the cheap alternative to training quantile heads.

The Tweedie mean head already gives μ per endpoint; with a global dispersion φ (Pearson MoM on the
validation year) and fixed power p=1.5, the whole predictive distribution is determined. So q50/q75/q90
(and any percentile) come from one fit — coherent, monotone, no quantile-crossing, and no single-threaded
per-leaf percentile sort. See docs/10 §1c and the NGBoost/Tweedie discussion.

Implementation: q_τ is a monotone function of μ for fixed (φ, p), so we build a (rain-value × μ) grid of
the survival function once and read q_τ(μ) off it, then interpolate to each endpoint's μ. Vectorised and
fast for millions of rows. The Tweedie point mass at 0 is handled: when 1−τ ≥ P(Y>0), q_τ = 0.
"""
import numpy as np

from podml.display_check import tweedie_sf, TWEEDIE_POWER  # reuse the validated SF


def tweedie_quantiles(mu: np.ndarray, phi: float, levels, power: float = TWEEDIE_POWER,
                      x_max: float = 60.0, n_x: int = 240, n_mu: int = 200) -> dict:
    """q_τ per row from the Tweedie CDF. Returns {f'q{int(τ*100):02d}': array(len(mu))}."""
    mu = np.maximum(np.asarray(mu, dtype=float), 1e-6)
    mu_hi = max(float(np.quantile(mu, 0.9995)), 1e-3)
    mu_grid = np.unique(np.geomspace(1e-4, mu_hi, n_mu))
    x_grid = np.geomspace(1e-3, x_max, n_x)                 # rain values; ~0 lower edge ⇒ SF≈P(Y>0)

    # SF[i, j] = P(Y >= x_grid[i] | mu_grid[j]); each row is one tweedie_sf call (vectorised over μ).
    sf = np.empty((n_x, len(mu_grid)))
    for i, x in enumerate(x_grid):
        sf[i] = tweedie_sf(float(x), mu_grid, phi, power)

    out: dict = {}
    for t in levels:
        target = 1.0 - t
        qg = np.empty(len(mu_grid))
        for j in range(len(mu_grid)):
            col = sf[:, j]                                  # decreasing in x
            if target >= col[0]:                            # in the dry mass (P(Y>0) ≤ target) → q=0
                qg[j] = 0.0
            elif target <= col[-1]:
                qg[j] = x_grid[-1]
            else:
                qg[j] = float(np.interp(target, col[::-1], x_grid[::-1]))  # x where SF = target
        out[f"q{int(round(t * 100)):02d}"] = np.interp(mu, mu_grid, qg)
    return out
