"""Step 6 — Open-Meteo hourly observations for real-time hike validation.

Weather data by Open-Meteo.com (CC BY 4.0). See pod-ml/OPENMETEO_LICENSE.md for terms.

Fetches precipitation, pressure, temperature, humidity for the 5 probe points (NZ domain).
Stores rolling 1-year CSV per point. Cron job: hourly fetches → append → deduplicate → prune.

  data/raw/openmeteo/hokitika_westcoast.csv    time, precip_mm_hr, pressure_hPa, temp_c, humidity_pct
  data/raw/openmeteo/christchurch_lee.csv      ...
  ...

Usage:
  python -m podml.fetch_openmeteo                    # fetch + write
  python -m podml.fetch_openmeteo --dry-run          # fetch + print, no write
  python -m podml.fetch_openmeteo --points-file CSV  # custom points (lat,lon,name)
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from podml.config import DATA_RAW, load_config

OPENMETEO_API = "https://api.open-meteo.com/v1/forecast"
DATA_DIR = DATA_RAW / "openmeteo"
RETENTION_DAYS = 365
LOGGER = logging.getLogger(__name__)


def _setup_logging() -> None:
    """Configure logging to stdout + optional file."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _fetch_point(lat: float, lon: float, name: str, dry_run: bool = False) -> dict | None:
    """Fetch hourly data for one point from Open-Meteo.

    Returns dict: {"time": [...], "precipitation_mm": [...], "pressure_hpa": [...], ...}
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "precipitation,surface_pressure,temperature_2m,relative_humidity_2m",
        "past_days": 7,
        "forecast_days": 1,
        "timezone": "Pacific/Auckland",
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{OPENMETEO_API}?{query}"

    try:
        if dry_run:
            LOGGER.info(f"[DRY-RUN] {name}: {url}")
            return None

        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
        LOGGER.info(f"[{name}] Fetched {len(data['hourly']['time'])} rows")
        return data["hourly"]
    except Exception as exc:
        LOGGER.error(f"[{name}] Fetch failed: {exc}")
        return None


def _rows_from_hourly(hourly_data: dict) -> list[dict]:
    """Parse Open-Meteo hourly response into list of dicts."""
    rows = []
    times = hourly_data["time"]
    precips = hourly_data.get("precipitation", [])
    pressures = hourly_data.get("surface_pressure", [])
    temps = hourly_data.get("temperature_2m", [])
    humidities = hourly_data.get("relative_humidity_2m", [])

    for i, t in enumerate(times):
        rows.append(
            {
                "time": t,
                "precipitation_mm_hr": precips[i] if i < len(precips) else None,
                "pressure_hpa": pressures[i] if i < len(pressures) else None,
                "temp_c": temps[i] if i < len(temps) else None,
                "humidity_pct": humidities[i] if i < len(humidities) else None,
            }
        )
    return rows


def _store_point(name: str, rows: list[dict], dry_run: bool = False) -> None:
    """Append rows to CSV, deduplicate on time, prune old rows, atomic write."""
    out = DATA_DIR / f"{name}.csv"
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Read existing
    existing = {}
    if out.exists():
        df = pd.read_csv(out)
        existing = {row["time"]: row.to_dict() for _, row in df.iterrows()}

    # Merge new rows (new rows override existing on time collision)
    for row in rows:
        existing[row["time"]] = row

    # Prune old rows (>365 days)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
    kept = {t: r for t, r in existing.items() if t >= cutoff}

    if dry_run:
        LOGGER.info(f"[DRY-RUN] {name}: {len(kept)} rows (after prune), no write")
        for row in list(kept.values())[-3:]:
            LOGGER.info(f"  {row}")
        return

    # Atomic write
    part = out.with_suffix(".csv.part")
    with part.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["time", "precipitation_mm_hr", "pressure_hpa", "temp_c", "humidity_pct"],
        )
        writer.writeheader()
        for t in sorted(kept.keys()):
            writer.writerow(kept[t])
    part.replace(out)
    LOGGER.info(f"[{name}] Stored {len(kept)} rows (pruned {len(existing) - len(kept)})")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Fetch hourly Open-Meteo observations for pod validation."
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch but do not write; print sample rows instead.",
    )
    ap.add_argument(
        "--points-file",
        type=Path,
        help="Custom CSV (name,lat,lon); overrides config probe_points.",
    )
    args = ap.parse_args()

    _setup_logging()
    LOGGER.info("Open-Meteo fetch started")

    cfg = load_config()
    points = cfg.get("probe_points", {})

    if args.points_file:
        if not args.points_file.exists():
            LOGGER.error(f"Points file not found: {args.points_file}")
            return
        df = pd.read_csv(args.points_file)
        points = {row["name"]: {"lat": row["lat"], "lon": row["lon"]} for _, row in df.iterrows()}
        LOGGER.info(f"Loaded {len(points)} points from {args.points_file}")

    for name, coords in points.items():
        hourly = _fetch_point(coords["lat"], coords["lon"], name, dry_run=args.dry_run)
        if hourly:
            rows = _rows_from_hourly(hourly)
            _store_point(name, rows, dry_run=args.dry_run)

    LOGGER.info("Open-Meteo fetch completed")


if __name__ == "__main__":
    main()
