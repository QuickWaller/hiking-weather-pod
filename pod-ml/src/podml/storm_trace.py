"""Storm trace — dense forecast evolution around peak rain events.

Builds hourly endpoint predictions for 2-3 storm cells, using saved ensemble
models, and plots how the 24h plume fan evolves as a storm approaches.

Workflow:
    # Step 1: train and save models (--save-models is on by default)
    python -m podml.train_ensemble --from-cache --save-plumes

    # Step 2: find best storms, build dense cache, predict, plot (all in one):
    python -m podml.storm_trace --all

    # Or step-by-step:
    python -m podml.storm_trace --find-storms            # print candidates
    python -m podml.storm_trace --build-dense            # hourly cache for top 3 cells
    python -m podml.storm_trace --predict                # predictions → storm_traces.json
    python -m podml.storm_trace --plot                   # figures

    # Override which cells/storms to use:
    python -m podml.storm_trace --all --storm-cells g-36p2_174p1,g-37p3_175p0
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.cm as cm
import numpy as np
import pandas as pd

from podml.train_ensemble import (
    OUT, CACHE_DIR, ENSEMBLE_FEATURES,
    SAMPLED_CSV, MotionSimParams,
    build_ensemble_dataset, load_ensemble_state, to_long_format,
    blend, predict,
)
from podml.labels_gpm import load_gpm_cells_hourly

TRACE_DIR = OUT / "storm_trace"
FIG_DIR = OUT.parent.parent / "docs" / "figures" / "ensemble"


# ─────────────────────────────────────────────── storm finder ────────────────────────────────────

def find_best_storms(
    cache_dir: Path = CACHE_DIR,
    n_storms: int = 3,
    test_year: int = 2024,
    min_rain_mm: float = 3.0,
) -> list[dict]:
    """Find the N most intense rain events in the k=4 test cache.

    Returns list of dicts with cell, endpoint_time, horizon, storm_time, peak_rain_mm.
    Picks one storm per cell, de-duplicated so nearby events don't crowd out one cell.
    """
    y_path = cache_dir / f"y_{test_year}.parquet"
    m_path = cache_dir / f"meta_{test_year}.parquet"
    if not y_path.exists() or not m_path.exists():
        raise FileNotFoundError(f"Test cache not found at {cache_dir}")

    y = pd.read_parquet(y_path)
    meta = pd.read_parquet(m_path)

    h_cols = [c for c in y.columns if c.startswith("amount_h")]
    y_max = y[h_cols].max(axis=1)
    h_peak_col = y[h_cols].idxmax(axis=1).fillna("amount_h0")
    h_peak = h_peak_col.str.replace("amount_h", "", regex=False).astype(int)

    meta2 = meta.copy()
    meta2["peak_rain"] = y_max.to_numpy()
    meta2["peak_h"] = h_peak.to_numpy()
    meta2["storm_time"] = pd.to_datetime(meta["time"]) + pd.to_timedelta(h_peak, unit="h")
    meta2 = meta2[meta2["peak_rain"] >= min_rain_mm].sort_values("peak_rain", ascending=False)

    seen: dict[str, pd.Timestamp] = {}
    storms: list[dict] = []
    for _, row in meta2.iterrows():
        cell = str(row["cell"])
        st = pd.Timestamp(row["storm_time"])
        if cell in seen and abs((st - seen[cell]).total_seconds()) < 72 * 3600:
            continue
        seen[cell] = st
        storms.append({
            "cell": cell,
            "endpoint_time": str(row["time"]),
            "endpoint_month": int(row["month"]),
            "peak_h": int(row["peak_h"]),
            "storm_time": str(st),
            "peak_rain_mm": float(row["peak_rain"]),
        })
        if len(storms) >= n_storms:
            break

    return storms


# ─────────────────────────────────────────────── dense cache ─────────────────────────────────────

def build_dense_trace_cache(
    cell_ids: list[str],
    year: int = 2024,
    out_dir: Path = TRACE_DIR,
    seed: int = 42,
) -> Path:
    """Build a near-hourly endpoint cache for specific cells in one year.

    Uses k_per_cell_month=1000 so every valid ERA5 hour in each month gets sampled
    (valid_pos caps it at ~700/month in practice).  Only processes the requested cells,
    so this is fast: 3 cells × 12 months × ~700 endpoints × 25 horizons ≈ 630 K rows.
    """
    all_cells = pd.read_csv(SAMPLED_CSV)
    cells = all_cells[all_cells["name"].isin(cell_ids)].reset_index(drop=True)
    if cells.empty:
        raise ValueError(f"No SAMPLED_CSV rows for: {cell_ids}")
    print(f"build_dense_trace_cache: {len(cells)} cells, year={year}", flush=True)

    gpm_times, precip = load_gpm_cells_hourly(
        cells["lat"].to_numpy(), cells["lon"].to_numpy(), year, year,
    )
    precip = precip.astype("float32")
    out_dir.mkdir(parents=True, exist_ok=True)
    cells.to_parquet(out_dir / "cells.parquet")

    build_ensemble_dataset(
        cells, gpm_times, precip,
        k_per_cell_month=1000,   # > any monthly count → gets all hours
        years=[year],
        params=MotionSimParams(),
        seed=seed,
        flush_dir=out_dir,
    )
    parts = sorted(out_dir.glob("X_*.parquet"))
    n = sum(len(pd.read_parquet(p, columns=["sp_hPa"])) for p in parts)
    print(f"dense cache: {n:,} endpoint rows → {out_dir}", flush=True)
    return out_dir


# ─────────────────────────────────────────────── predict ─────────────────────────────────────────

def _load_dense_long(trace_dir: Path) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    """Load and long-expand the dense trace cache."""
    X = pd.concat(
        [pd.read_parquet(p) for p in sorted(trace_dir.glob("X_*.parquet"))],
        ignore_index=True,
    )
    y = pd.concat(
        [pd.read_parquet(p) for p in sorted(trace_dir.glob("y_*.parquet"))],
        ignore_index=True,
    )
    meta = pd.concat(
        [pd.read_parquet(p) for p in sorted(trace_dir.glob("meta_*.parquet"))],
        ignore_index=True,
    )
    return to_long_format(X, y, meta)


def predict_storm_traces(
    storms: list[dict],
    trace_dir: Path = TRACE_DIR,
    hours_before: int = 30,
    hours_after: int = 6,
    step_h: int = 2,            # show a plume every N hours
) -> list[dict]:
    """Run saved models on the dense trace cache; returns per-storm trace records.

    For each storm, selects endpoint start-times every `step_h` hours from
    storm_time - hours_before to storm_time + hours_after, then collects the
    full 0-24h blended plume at each start time.

    Returns a list of trace dicts ready for fig_storm_trace().
    """
    models, clim_table, global_stats, weights = load_ensemble_state()
    avail_feats = [f for f in ENSEMBLE_FEATURES if True]   # lgb.Booster ignores extras

    X_long, y_long, meta_long = _load_dense_long(trace_dir)
    avail_feats = [f for f in ENSEMBLE_FEATURES if f in X_long.columns]

    # Precompute predictions for all rows (one forward pass per model head)
    preds_all = predict(models, X_long, avail_feats)
    blended_all = blend(preds_all, clim_table, global_stats, weights, meta_long)

    traces = []
    for storm in storms:
        cell = storm["cell"]
        storm_time = pd.Timestamp(storm["storm_time"])

        cell_mask = meta_long["cell"].to_numpy() == cell
        meta_c = meta_long[cell_mask].reset_index(drop=True)
        y_c = y_long.to_numpy()[cell_mask]
        bl_c = {k: v[cell_mask] for k, v in blended_all.items()}

        # Unique endpoint start-times in the window
        t_lo = storm_time - pd.Timedelta(hours=hours_before)
        t_hi = storm_time + pd.Timedelta(hours=hours_after)
        ep_times = pd.to_datetime(meta_c["time"]).values

        # Select start-times at step_h spacing
        target_starts = pd.date_range(t_lo, t_hi, freq=f"{step_h}h")
        ep_ts_arr = pd.DatetimeIndex(ep_times)
        chosen_eps = []
        for ts in target_starts:
            # nearest available endpoint within ±(step_h/2) hours
            diffs = np.abs((ep_ts_arr - ts).total_seconds())
            idx_min = int(np.argmin(diffs))
            if diffs[idx_min] <= step_h * 3600 / 2:
                ep_val = ep_ts_arr[idx_min]
                if not chosen_eps or chosen_eps[-1] != ep_val:
                    chosen_eps.append(ep_val)

        endpoints = []
        for ep_t in chosen_eps:
            ep_mask = ep_ts_arr == ep_t
            if ep_mask.sum() == 0:
                continue
            rows_idx = np.where(ep_mask)[0]
            # Sort by horizon
            h_vals = meta_c["horizon_h"].to_numpy()[rows_idx]
            order = np.argsort(h_vals)
            rows_sorted = rows_idx[order]
            h_sorted = h_vals[order].tolist()

            endpoints.append({
                "start_time": str(ep_t),
                "hours_before_storm": float(
                    (storm_time - ep_t).total_seconds() / 3600
                ),
                "horizons": [int(h) for h in h_sorted],
                "mean":  [float(bl_c["mean"][i])  for i in rows_sorted],
                "q10":   [float(bl_c["q10"][i])   for i in rows_sorted],
                "q25":   [float(bl_c["q25"][i])   for i in rows_sorted],
                "q75":   [float(bl_c["q75"][i])   for i in rows_sorted],
                "q90":   [float(bl_c["q90"][i])   for i in rows_sorted],
                "observed": [float(y_c[i])        for i in rows_sorted],
            })

        traces.append({
            "cell": storm["cell"],
            "storm_time": storm["storm_time"],
            "peak_rain_mm": storm["peak_rain_mm"],
            "endpoints": endpoints,
        })
        print(f"  storm {cell} @ {storm['storm_time']}: {len(endpoints)} endpoint plumes",
              flush=True)

    return traces


# ─────────────────────────────────────────────── figure ──────────────────────────────────────────

def fig_storm_trace(traces: list[dict], out_dir: Path = FIG_DIR) -> None:
    """Spaghetti-fan figure: per storm, overlaid 24h plumes coloured by hours-before-storm.

    Each row = one storm.  X = absolute UTC valid time.  Y = rain mm/hr.
    Plumes range from pale blue (oldest, farthest from storm) to deep red (most recent).
    Observed GPM rain plotted as black circles at each valid hour.

    Works well for 2-3 storms — up to 4 per figure before panels get cramped.
    """
    n = len(traces)
    if n == 0:
        print("fig_storm_trace: no traces to plot", flush=True)
        return

    fig, axes = plt.subplots(n, 1, figsize=(14, 4 * n), squeeze=False)
    cmap = cm.RdYlBu_r   # blue (far) → yellow (mid) → red (near)

    for row_i, (storm, ax) in enumerate(zip(traces, axes[:, 0])):
        storm_t = pd.Timestamp(storm["storm_time"])
        peak = storm["peak_rain_mm"]
        cell = storm["cell"]
        eps = storm["endpoints"]
        if not eps:
            ax.set_title(f"{cell}  storm {storm_t:%Y-%m-%d %H:%M} — no endpoint data")
            continue

        # Colour scale: 0h-before = red, hours_before_max = blue
        hb_vals = [ep["hours_before_storm"] for ep in eps]
        hb_max = max(hb_vals) if hb_vals else 30.0

        # Plot plumes oldest → newest so recent lines sit on top
        for ep in sorted(eps, key=lambda e: e["hours_before_storm"], reverse=True):
            hb = ep["hours_before_storm"]
            t0 = pd.Timestamp(ep["start_time"])
            hs = ep["horizons"]
            valid_times = [t0 + pd.Timedelta(hours=int(h)) for h in hs]

            c_frac = 1.0 - (hb / hb_max)   # 0 = oldest (blue), 1 = newest (red)
            colour = cmap(c_frac)
            alpha_band = 0.06 + 0.12 * c_frac
            lw = 0.6 + 1.0 * c_frac

            ax.fill_between(valid_times, ep["q10"], ep["q90"],
                            color=colour, alpha=alpha_band)
            ax.fill_between(valid_times, ep["q25"], ep["q75"],
                            color=colour, alpha=alpha_band * 1.5)
            ax.plot(valid_times, ep["mean"], color=colour, lw=lw, alpha=0.8)

        # Observed rain dots: use the innermost plume's observed column (all epochs same GPM)
        innermost = min(eps, key=lambda e: e["hours_before_storm"])
        t0_in = pd.Timestamp(innermost["start_time"])
        obs_times = [t0_in + pd.Timedelta(hours=int(h)) for h in innermost["horizons"]]
        ax.scatter(obs_times, innermost["observed"], c="black", s=8, zorder=5,
                   label="GPM observed", alpha=0.7)

        # Storm peak marker
        ax.axvline(storm_t, color="crimson", lw=1.5, ls="--", alpha=0.8,
                   label=f"Storm peak ({peak:.1f} mm/hr)")

        # Colourbar (hours before storm → colour)
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(0, hb_max))
        sm.set_array([])
        cbar = fig.colorbar(sm, ax=ax, fraction=0.015, pad=0.01)
        cbar.set_label("Forecast lead (h before storm)", fontsize=8)

        # Axes decoration
        ax.set_ylabel("Rain (mm/hr)", fontsize=9)
        ax.set_title(
            f"Storm trace: {cell}  |  peak {peak:.1f} mm/hr @ {storm_t:%Y-%m-%d %H:%M UTC}",
            fontsize=10,
        )
        ax.legend(fontsize=8, loc="upper left")
        ax.set_ylim(bottom=0)
        ax.tick_params(axis="x", labelsize=8)
        ax.tick_params(axis="y", labelsize=8)
        fig.autofmt_xdate(rotation=30)

    fig.suptitle(
        "Forecast fan evolution — plume colour = forecast lead time before storm peak\n"
        "Blue = issued 30h before storm · Red = issued at storm time · Black dots = GPM observed",
        fontsize=9, y=1.01,
    )
    fig.tight_layout()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "storm_trace.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"fig_storm_trace → {out_path}", flush=True)


# ─────────────────────────────────────────────── CLI ────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Storm forecast evolution trace")
    ap.add_argument("--find-storms", action="store_true",
                    help="scan test cache for top storm events and print candidates")
    ap.add_argument("--build-dense", action="store_true",
                    help="build near-hourly endpoint cache for storm cells")
    ap.add_argument("--predict", action="store_true",
                    help="predict on dense cache using saved models → storm_traces.json")
    ap.add_argument("--plot", action="store_true",
                    help="generate storm_trace.png from storm_traces.json")
    ap.add_argument("--all", action="store_true",
                    help="run find-storms → build-dense → predict → plot in one shot")
    ap.add_argument("--storm-cells", type=str, default=None,
                    help="comma-separated cell IDs to use (overrides auto-find)")
    ap.add_argument("--n-storms", type=int, default=3,
                    help="number of storm events to trace (default 3)")
    ap.add_argument("--hours-before", type=int, default=30,
                    help="hours of forecast evolution before storm peak (default 30)")
    ap.add_argument("--step-h", type=int, default=2,
                    help="spacing between displayed forecast snapshots in hours (default 2)")
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    storms_file = TRACE_DIR / "storms.json"
    traces_file = TRACE_DIR / "storm_traces.json"

    do_find  = args.find_storms  or args.all
    do_build = args.build_dense  or args.all
    do_pred  = args.predict      or args.all
    do_plot  = args.plot         or args.all

    storms: list[dict] = []

    if do_find:
        print("── Finding best storm events… ──", flush=True)
        storms = find_best_storms(n_storms=args.n_storms)
        if args.storm_cells:
            # Override: user specified cells — create stub storm records
            override = [c.strip() for c in args.storm_cells.split(",")]
            # Reuse auto-found storms for those cells, or create minimal stubs
            cell_map = {s["cell"]: s for s in storms}
            storms = [cell_map.get(c, {"cell": c, "storm_time": f"{args.year}-01-01 00:00",
                                       "peak_rain_mm": 0.0, "endpoint_month": 1,
                                       "peak_h": 0}) for c in override]
        TRACE_DIR.mkdir(parents=True, exist_ok=True)
        with open(storms_file, "w") as f:
            json.dump(storms, f, indent=2, default=str)
        for s in storms:
            print(f"  {s['cell']:20s}  peak={s['peak_rain_mm']:.1f} mm/hr"
                  f"  storm_time={s['storm_time']}", flush=True)

    if do_build:
        if not storms and storms_file.exists():
            with open(storms_file) as f:
                storms = json.load(f)
        cell_ids = [s["cell"] for s in storms]
        print(f"── Building dense cache for {cell_ids} … ──", flush=True)
        build_dense_trace_cache(cell_ids=cell_ids, year=args.year, seed=args.seed)

    if do_pred:
        if not storms and storms_file.exists():
            with open(storms_file) as f:
                storms = json.load(f)
        print("── Running predictions on dense cache… ──", flush=True)
        traces = predict_storm_traces(
            storms,
            hours_before=args.hours_before,
            step_h=args.step_h,
        )
        with open(traces_file, "w") as f:
            json.dump(traces, f, indent=2, default=str)
        print(f"storm_traces.json → {traces_file}", flush=True)

    if do_plot:
        if not (TRACE_DIR / "storm_traces.json").exists():
            print("No storm_traces.json found — run --predict first", flush=True)
        else:
            with open(traces_file) as f:
                traces = json.load(f)
            fig_storm_trace(traces)

    if not any([do_find, do_build, do_pred, do_plot]):
        ap.print_help()
