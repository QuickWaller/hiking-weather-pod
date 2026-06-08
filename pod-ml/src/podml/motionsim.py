"""Motion-sim layer — turn a fixed-cell ERA5 grid into a *moving hiker's* pod signal history.

Each real pod reading carries a timestamp + GPS stamp, so the pod's ring buffer is a trajectory across
grid cells, not a single station. To train on the deployable distribution we therefore build training
rows whose feature history is sampled ALONG a feasible path: a sequence of (time, cell) where each step
pulls that cell's ERA5 value. A stationary hike is the zero-speed special case.

Composition (no signature churn): motionsim → sensorsim → build_features_from_signals.
motionsim emits the same dict shape as ``features.raw_signals`` (time, sp_hPa, t2m_C, rh), so the sensor
layer degrades it and the feature builder consumes it unchanged.

Two design points baked in (see docs/02 + project memory):
  - **Pressure is sea-level-reduced (MSLP) here, using ERA5's OWN orography** (``static_features``), not the
    DEM — else a climb reads as a fake pressure crash. The only residual motion noise is then the
    **GPS-altitude error**: we reduce ERA5 ``sp`` with the orography height perturbed by a per-fix error,
    which is exactly the pod reducing its reading with a slightly-wrong altitude. A constant part cancels
    in the tendencies (the high-trust features); the per-fix variation is the genuine motion penalty.
  - **Movement is a Markov chain over {still, walk, drive}** so runs persist (you drive for hours, camp for
    hours) instead of flipping every step; positions snap to 0.1° land cells and jumps are speed-bounded so
    paths stay physically reachable. Labels are unaffected — they stay per-cell at the endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NamedTuple

import numpy as np
import xarray as xr

from podml.features import rh_from_t_td
from podml.static_features import pressure_to_msl

REGIMES = ("still", "walk", "drive")


@dataclass
class MotionSimParams:
    """Movement + GPS-error magnitudes. Provisional GUESSES; field validation replaces them later."""

    # Steady-state time share of each regime (still / walk / drive). Slight motion-lean vs a real tramp
    # (robustness for the dangerous moving moments). Tweak freely.
    steady: tuple[float, float, float] = (0.55, 0.35, 0.10)
    # Mean run length per regime (hours) → sets how long you stay put / keep moving.
    run_hours: tuple[float, float, float] = (6.0, 4.0, 2.0)
    # Max speed per regime (km/h). still=0; walk≈tramping pace; drive≈back-country road.
    max_speed_kmh: tuple[float, float, float] = (0.0, 5.0, 100.0)
    cell_km: float = 11.0              # ~0.1° at NZ latitudes; sets cells-moved per hour
    gps_alt_err_std_m: float = 15.0    # per-fix Gaussian GPS altitude error (≈0.12 hPa/m → ~1.8 hPa)
    max_resample: int = 8             # tries to find a feasible (land, in-bounds) step before staying put


class Path(NamedTuple):
    """A trajectory as integer indices into an ERA5 grid, ordered forward in time."""

    t: np.ndarray  # valid_time index
    i: np.ndarray  # lat index
    j: np.ndarray  # lon index


def _steady(params: MotionSimParams) -> np.ndarray:
    pi = np.asarray(params.steady, dtype="float64")
    return pi / pi.sum()


def transition_matrix(params: MotionSimParams) -> np.ndarray:
    """3×3 Markov transition matrix with geometric run-lengths ``run_hours`` AND exact steady-state ``steady``.

    P(stay in i) = 1 − 1/L_i (mean run length L_i hours, hourly steps). The off-diagonals are solved so the
    chain's stationary distribution is *exactly* ``steady`` — a 3-state transport problem: the inter-regime
    flows F[i,j] = π_i·P[i,j] must have equal row and column marginals m_i = π_i/L_i (zero diagonal), which
    leaves one free parameter x; we take the midpoint of its feasible (non-negative) range.
    """
    pi = _steady(params)
    L = np.asarray(params.run_hours, dtype="float64")
    assert len(REGIMES) == 3, "exact construction is specialised to 3 regimes"
    m0, m1, m2 = pi / L  # row == column marginals of the off-diagonal flow

    lo = max(0.0, m1 - m2, m0 - m2)
    hi = min(m0, m1, m0 + m1 - m2)
    x = 0.5 * (lo + hi) if hi >= lo else max(0.0, min(lo, hi))  # feasible midpoint

    F = np.zeros((3, 3))
    F[0, 1], F[0, 2] = x, m0 - x
    F[2, 1], F[2, 0] = m1 - x, m2 - m1 + x
    F[1, 0], F[1, 2] = m0 + m1 - m2 - x, m2 - m0 + x
    F = np.clip(F, 0.0, None)  # guard tiny negatives if marginals are near-infeasible

    P = F / pi[:, None]
    np.fill_diagonal(P, 0.0)
    np.fill_diagonal(P, 1.0 - P.sum(axis=1))  # row remainder = stay prob (= 1 − 1/L_i)
    return P


def sample_regimes(n: int, params: MotionSimParams, rng: np.random.Generator) -> np.ndarray:
    """Sample ``n`` regime indices via the Markov chain, initialised from the steady-state."""
    P = transition_matrix(params)
    pi = _steady(params)
    out = np.empty(n, dtype="int64")
    out[0] = rng.choice(len(REGIMES), p=pi)
    for k in range(1, n):
        out[k] = rng.choice(len(REGIMES), p=P[out[k - 1]])
    return out


def _step_offset(regime: int, params: MotionSimParams, rng: np.random.Generator) -> tuple[int, int]:
    """A random (di, dj) cell displacement for one hour in ``regime``, speed-bounded and snapped."""
    max_cells = params.max_speed_kmh[regime] / params.cell_km   # cells reachable in 1 h
    if max_cells < 0.5:
        return 0, 0  # still / sub-cell walking: stay in the same 0.1° cell
    r = rng.uniform(0.0, max_cells)
    theta = rng.uniform(0.0, 2.0 * np.pi)
    return int(round(r * np.cos(theta))), int(round(r * np.sin(theta)))


def sample_path_backward(
    endpoint: tuple[int, int, int],
    n_hours: int,
    land: np.ndarray,
    params: MotionSimParams,
    rng: np.random.Generator,
) -> Path:
    """Build a feasible path of ``n_hours``+1 hourly steps ending at ``endpoint`` = (t, i, j).

    Generated BACKWARD from the endpoint (the cell/time the forecast is about), so endpoint coverage
    matches the sampled cells while the history is the random feasible part. Each backward step moves at
    most the regime's speed, stays on land and in-bounds (resampling, else staying put), and decrements
    the time index by one hour. Returns indices ordered FORWARD in time.
    """
    t0, i0, j0 = endpoint
    if t0 < n_hours:
        raise ValueError(f"endpoint t={t0} has < {n_hours} h of history available")
    n_lat, n_lon = land.shape
    if not land[i0, j0]:
        raise ValueError("endpoint cell is not land")

    regimes = sample_regimes(n_hours + 1, params, rng)
    ts = np.empty(n_hours + 1, dtype="int64")
    iis = np.empty(n_hours + 1, dtype="int64")
    jjs = np.empty(n_hours + 1, dtype="int64")
    t, i, j = t0, i0, j0
    for step in range(n_hours + 1):
        ts[step], iis[step], jjs[step] = t, i, j
        if step == n_hours:
            break
        # Move to the PREVIOUS hour's cell (we're walking back in time).
        for _ in range(params.max_resample):
            di, dj = _step_offset(int(regimes[step]), params, rng)
            ni, nj = i + di, j + dj
            if 0 <= ni < n_lat and 0 <= nj < n_lon and land[ni, nj]:
                i, j = ni, nj
                break
        # else: no feasible neighbour found → stay in the same cell (still)
        t -= 1
    # Reverse to forward-in-time order.
    return Path(ts[::-1].copy(), iis[::-1].copy(), jjs[::-1].copy())


def signals_along_path(
    path: Path,
    ds: xr.Dataset,
    orog: np.ndarray,
    params: MotionSimParams,
    rng: np.random.Generator,
) -> dict[str, Any]:
    """Gather a moving pod's signal history along ``path`` → raw_signals dict (pre-sensorsim).

    Args:
        path: forward-time indices into ``ds`` (and into ``orog`` for i/j).
        ds: ERA5 Dataset (valid_time, lat, lon) with sp (Pa), t2m (K), d2m (K), already loaded.
        orog: ERA5-Land orography height (m), shape (n_lat, n_lon), aligned to ds's grid.
        params: motion/GPS-error params.
        rng: RNG for the per-fix GPS-altitude error.

    Returns:
        dict {time, sp_hPa, t2m_C, rh} — sp_hPa is **MSLP** (sea-level-reduced) carrying GPS-altitude
        noise; t2m_C/rh are the cell values (sensorsim adds sensor bias/noise next).
    """
    t_idx, i_idx, j_idx = path.t, path.i, path.j
    sp = ds["sp"].values[t_idx, i_idx, j_idx] / 100.0       # Pa → hPa, at ERA5 surface (orography)
    t2m_c = ds["t2m"].values[t_idx, i_idx, j_idx] - 273.15
    d2m_k = ds["d2m"].values[t_idx, i_idx, j_idx]
    rh = rh_from_t_td(ds["t2m"].values[t_idx, i_idx, j_idx], d2m_k)

    # Reduce to MSLP using the cell's orography height perturbed by per-fix GPS-altitude error:
    # this IS the pod reducing its reading with a slightly-wrong altitude. err=0 → clean true MSLP.
    h = orog[i_idx, j_idx]
    gps_err = rng.normal(0.0, params.gps_alt_err_std_m, size=h.shape)
    sp_mslp = pressure_to_msl(sp, h + gps_err, t2m_c)

    times = ds["valid_time"].values[t_idx]
    return {"time": times, "sp_hPa": sp_mslp, "t2m_C": t2m_c, "rh": rh}
