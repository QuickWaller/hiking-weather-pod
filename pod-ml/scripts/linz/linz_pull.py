#!/usr/bin/env python3
"""
linz_pull.py — Download and update LINZ NZ Topo50 vector layers as GeoPackage files.

Strategy:
  First run:    paginated WFS GetFeature → write GeoPackage via fiona (all WGS84)
  Later runs:   if LINZ published a newer revision, fetch WFS changeset and apply.
  Fallback:     --full forces a fresh full download regardless.

Auth: LINZ WFS uses a matrix parameter in the URL path:
  https://data.linz.govt.nz/services;key=<KEY>/wfs/layer-<ID>/

Usage:
  python linz_pull.py --all                   # download/update all layers that are due
  python linz_pull.py --layer contours        # one specific layer
  python linz_pull.py --all --force           # ignore cadence, process all now
  python linz_pull.py --layer roads --full    # force full re-download for one layer
  python linz_pull.py --list                  # show status of all layers

Env:  LINZ_KEY   (required; matches key at data.linz.govt.nz)
Output: ~/linz-data/<layer>/<name>.gpkg  + status.json per layer
"""

from __future__ import annotations

import argparse
try:
    import fcntl as _fcntl
    def _flock(fh, flags): _fcntl.flock(fh, flags)
    _LOCK_EX_NB = _fcntl.LOCK_EX | _fcntl.LOCK_NB
    _LOCK_UN = _fcntl.LOCK_UN
except ImportError:
    # Windows — no-op locking (file-based locking not needed in tests)
    def _flock(fh, flags): pass
    _LOCK_EX_NB = 0
    _LOCK_UN = 0
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from layer_config import LAYERS, BASE_DIR, LINZ_API

def _load_key() -> str:
    k = os.environ.get("LINZ_KEY", "")
    if k:
        return k
    # Fallback: read from /home/claude/.linz_key (written by install_cron.sh)
    p = Path.home() / ".linz_key"
    if p.exists():
        return p.read_text().strip()
    sys.exit("LINZ_KEY not set — set env var or write to ~/.linz_key")

LINZ_KEY = _load_key()
TIMEOUT = 30


def _get(url: str, timeout: int = TIMEOUT, **kwargs) -> requests.Response:
    """GET with LINZ key as URL parameter (Authorization header rejected by some endpoints)."""
    params = dict(kwargs.pop("params", {}))
    params["key"] = LINZ_KEY
    return requests.get(url, params=params, timeout=timeout, **kwargs)


def _post(url: str, timeout: int = TIMEOUT, **kwargs) -> requests.Response:
    params = dict(kwargs.pop("params", {}))
    params["key"] = LINZ_KEY
    return requests.post(url, params=params, timeout=timeout, **kwargs)


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------

def layer_dir(name: str) -> Path:
    return Path(BASE_DIR) / name


def read_status(name: str) -> dict:
    p = layer_dir(name) / "status.json"
    return json.loads(p.read_text()) if p.exists() else {}


def write_status(name: str, data: dict) -> None:
    d = layer_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    (d / "status.json").write_text(json.dumps(data, indent=2))


def is_due(name: str, force: bool = False) -> bool:
    if force:
        return True
    st = read_status(name)
    if st.get("state") != "complete":
        return True
    last = st.get("last_updated")
    if not last:
        return True
    last_dt = datetime.fromisoformat(last)
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=timezone.utc)
    age_days = (datetime.now(timezone.utc) - last_dt).days
    return age_days >= LAYERS[name]["cadence_days"]


# ---------------------------------------------------------------------------
# LINZ API helpers
# ---------------------------------------------------------------------------

WFS_PAGE = 5000  # features per WFS request


def _wfs_url(layer_id: str) -> str:
    """Layer-specific WFS endpoint with matrix-parameter auth."""
    return f"https://data.linz.govt.nz/services;key={LINZ_KEY}/wfs/layer-{layer_id}/"


def _wfs_params(layer_id: str, extra: dict | None = None) -> dict:
    base = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": f"data.linz.govt.nz:layer-{layer_id}",
        "srsName": "EPSG:4326",
        "outputFormat": "application/json",
    }
    if extra:
        base.update(extra)
    return base


def _infer_fiona_schema(features: list) -> dict:
    """Derive fiona property schema from a sample of features."""
    prop_types: dict = {}
    geom_type = "Unknown"
    for feat in features:
        if feat.get("geometry"):
            geom_type = feat["geometry"]["type"]
        for k, v in (feat.get("properties") or {}).items():
            if k in prop_types or v is None:
                continue
            if isinstance(v, bool):
                prop_types[k] = "str"
            elif isinstance(v, int):
                prop_types[k] = "int"
            elif isinstance(v, float):
                prop_types[k] = "float"
            else:
                prop_types[k] = "str"
    # Fall back to str for any key seen only with None values
    if features and features[0].get("properties"):
        for k in features[0]["properties"]:
            prop_types.setdefault(k, "str")
    return {"geometry": geom_type, "properties": prop_types}


def get_layer_revision(layer_id: str) -> int | None:
    """Return the current published revision number for a layer (REST API)."""
    r = _get(f"{LINZ_API}/layers/{layer_id}/")
    r.raise_for_status()
    data = r.json()
    return data.get("data", {}).get("revision") or data.get("revision")


def full_wfs_download(name: str, layer_id: str, out_path: Path) -> float:
    """
    Download all features via paginated WFS GetFeature and write to a GeoPackage.
    Coordinates are reprojected to WGS84 (EPSG:4326) by the server.
    Returns file size in MB.
    """
    import fiona
    from fiona.crs import CRS

    url = _wfs_url(layer_id)
    print(f"  [{name}] Starting WFS download (layer {layer_id}, page={WFS_PAGE})...")

    # Fetch first page to get schema
    r = requests.get(url, params=_wfs_params(layer_id, {"count": WFS_PAGE, "startIndex": 0}),
                     timeout=300)
    r.raise_for_status()
    page = r.json()
    features = page.get("features", [])
    if not features:
        raise RuntimeError(f"No features on first WFS page for layer {layer_id}")

    schema = _infer_fiona_schema(features)
    crs = CRS.from_epsg(4326)
    tmp = out_path.with_suffix(".tmp.gpkg")
    tmp.unlink(missing_ok=True)

    total = 0
    with fiona.open(str(tmp), "w", driver="GPKG", schema=schema, crs=crs) as dst:
        while True:
            for feat in features:
                # Coerce properties to declared types
                props = {}
                for k, declared in schema["properties"].items():
                    v = (feat.get("properties") or {}).get(k)
                    if v is None:
                        props[k] = None
                    elif declared == "int":
                        props[k] = int(v)
                    elif declared == "float":
                        props[k] = float(v)
                    else:
                        props[k] = str(v) if v is not None else None
                try:
                    dst.write({"type": "Feature",
                               "geometry": feat.get("geometry"),
                               "properties": props})
                except Exception as exc:
                    print(f"\n    warning: skipped feature: {exc}")
            total += len(features)
            print(f"\r  [{name}] {total:,} features written", end="", flush=True)

            if len(features) < WFS_PAGE:
                break  # last page

            time.sleep(0.5)  # be gentle
            r = requests.get(url, params=_wfs_params(layer_id, {"count": WFS_PAGE, "startIndex": total}),
                             timeout=300)
            r.raise_for_status()
            features = r.json().get("features", [])

    print()
    tmp.rename(out_path)
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"  [{name}] Saved {total:,} features → {size_mb:.1f} MB")
    return size_mb


def apply_changeset(name: str, layer_id: str, gpkg_path: Path, from_rev: int) -> int:
    """
    Fetch WFS changeset from from_rev to head and apply to the local GeoPackage.
    Deletions use SQLite directly; insertions/updates use fiona append mode.
    Returns number of features changed.
    """
    import sqlite3
    import fiona

    url = _wfs_url(layer_id)
    print(f"  [{name}] Fetching changeset from revision {from_rev} to head...")
    r = requests.get(url, params=_wfs_params(layer_id, {
        "viewparams": f"from:{from_rev};to:head",
    }), timeout=600)
    r.raise_for_status()
    data = r.json()
    features = data.get("features", [])

    if not features:
        print(f"  [{name}] No changes since revision {from_rev}")
        return 0

    print(f"  [{name}] Applying {len(features)} changes...")

    # Get GeoPackage table name from gpkg_contents
    with sqlite3.connect(str(gpkg_path)) as con:
        tables = [row[0] for row in con.execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type='features'"
        ).fetchall()]
        if not tables:
            raise RuntimeError(f"No feature tables in {gpkg_path}")
        table = tables[0]

        deletes = 0
        to_upsert = []
        for feat in features:
            props = dict(feat.get("properties") or {})
            action = props.pop("__change__", props.pop("__action__", "insert"))
            fid = feat.get("id") or props.get("t50_fid") or props.get("id")

            if action == "delete":
                if fid is not None:
                    con.execute(f'DELETE FROM "{table}" WHERE t50_fid = ?', (fid,))
                    deletes += 1
            else:
                if action == "update" and fid is not None:
                    con.execute(f'DELETE FROM "{table}" WHERE t50_fid = ?', (fid,))
                feat["properties"] = props
                to_upsert.append(feat)
        con.commit()

    inserts = 0
    if to_upsert:
        with fiona.open(str(gpkg_path), "a") as dst:
            for feat in to_upsert:
                try:
                    dst.write({"type": "Feature",
                               "geometry": feat.get("geometry"),
                               "properties": feat.get("properties", {})})
                    inserts += 1
                except Exception as exc:
                    print(f"    warning: skipped feature: {exc}")

    print(f"  [{name}] Done: {inserts} upserted, {deletes} deleted")
    return len(features)


# ---------------------------------------------------------------------------
# Main per-layer orchestrator
# ---------------------------------------------------------------------------

def pull_layer(name: str, force: bool = False, full: bool = False) -> None:
    cfg = LAYERS[name]
    layer_id = cfg["linz_id"]
    d = layer_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    gpkg = d / f"{cfg['name']}.gpkg"

    lock_path = d / "download.lock"
    lock_fh = open(lock_path, "w")
    try:
        _flock(lock_fh, _LOCK_EX_NB)
    except BlockingIOError:
        print(f"  [{name}] Already running — skipping")
        lock_fh.close()
        return

    try:
        st = read_status(name)
        local_rev = st.get("last_revision")
        write_status(name, {**st, "state": "downloading"})

        # Check what revision LINZ currently has
        try:
            latest_rev = get_layer_revision(layer_id)
        except Exception as exc:
            print(f"  [{name}] Could not fetch revision info: {exc}")
            latest_rev = None

        need_full = full or not gpkg.exists() or not local_rev
        need_changeset = (
            not need_full
            and latest_rev is not None
            and local_rev is not None
            and latest_rev != local_rev
        )
        already_current = (
            not need_full
            and not need_changeset
            and gpkg.exists()
        )

        if already_current and not force:
            print(f"  [{name}] Already at revision {local_rev} — nothing to do")
            write_status(name, {**st, "state": "complete"})
            return

        if need_full:
            size_mb = full_wfs_download(name, layer_id, gpkg)
        elif need_changeset:
            n = apply_changeset(name, layer_id, gpkg, local_rev)
            size_mb = gpkg.stat().st_size / 1024 / 1024
            print(f"  [{name}] {size_mb:.1f} MB on disk after {n} changes")
        else:
            # force=True but no revision change — just redo full
            size_mb = full_wfs_download(name, layer_id, gpkg)

        write_status(name, {
            "state": "complete",
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "last_revision": latest_rev,
            "file_size_mb": round(size_mb, 1),
            "cadence_days": cfg["cadence_days"],
            "description": cfg["description"],
        })
        print(f"  [{name}] Complete (revision {latest_rev})")

    except Exception as exc:
        write_status(name, {**read_status(name), "state": "error", "error": str(exc)})
        print(f"  [{name}] ERROR: {exc}")
        raise

    finally:
        _flock(lock_fh, _LOCK_UN)
        lock_fh.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_status_table() -> None:
    print(f"{'Layer':<12} {'State':<12} {'Rev':<10} {'Size MB':<10} {'Last updated'}")
    print("-" * 70)
    for name in LAYERS:
        st = read_status(name)
        state = st.get("state", "not started")
        rev = str(st.get("last_revision", "—"))
        size = f"{st.get('file_size_mb', 0):.1f}" if st.get("file_size_mb") else "—"
        last = (st.get("last_updated") or "never")[:19]
        print(f"{name:<12} {state:<12} {rev:<10} {size:<10} {last}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="Process all layers that are due")
    ap.add_argument("--layer", choices=list(LAYERS), help="Process a single layer")
    ap.add_argument("--force", action="store_true", help="Ignore cadence — run even if not due")
    ap.add_argument("--full", action="store_true", help="Force full re-download (no changeset)")
    ap.add_argument("--list", action="store_true", help="Print status table and exit")
    args = ap.parse_args()

    if args.list:
        _print_status_table()
        return

    targets = list(LAYERS) if args.all else ([args.layer] if args.layer else [])
    if not targets:
        ap.error("Specify --all or --layer <name> (or --list)")

    for name in targets:
        if args.force or is_due(name):
            print(f"\n=== {name} ===")
            pull_layer(name, force=args.force, full=args.full)
        else:
            st = read_status(name)
            last = (st.get("last_updated") or "never")[:19]
            print(f"[{name}] up to date (last: {last})")


if __name__ == "__main__":
    main()
