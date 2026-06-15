#!/usr/bin/env python3
"""
linz_pull.py — Download and update LINZ NZ Topo50 vector layers as GeoPackage files.

Strategy:
  First run:    POST export job to LINZ API → poll until complete → download .gpkg
  Later runs:   if LINZ published a newer revision, fetch WFS changeset and apply.
  Fallback:     --full forces a fresh full download regardless.

Usage:
  python linz_pull.py --all                   # download/update all layers that are due
  python linz_pull.py --layer contours        # one specific layer
  python linz_pull.py --all --force           # ignore cadence, process all now
  python linz_pull.py --layer roads --full    # force full re-download for one layer
  python linz_pull.py --list                  # show status of all layers

Env:  LINZ_KEY   (required; matches key at data.linz.govt.nz)
Output: /data/linz/<layer>/<name>.gpkg  + status.json per layer
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
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from layer_config import LAYERS, BASE_DIR, LINZ_API, LINZ_WFS

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

def get_layer_revision(layer_id: str) -> int | None:
    """Return the current published revision number for a layer."""
    r = _get(f"{LINZ_API}/layers/{layer_id}/")
    r.raise_for_status()
    data = r.json()
    return data.get("data", {}).get("revision") or data.get("revision")


def full_export(name: str, layer_id: str, out_path: Path) -> float:
    """
    Trigger an async LINZ Export API job, poll until done, then download the
    GeoPackage. Returns file size in MB.
    """
    print(f"  [{name}] Creating export job for layer {layer_id}...")
    payload = {
        "items": [{"item": f"/services/api/v1/layers/{layer_id}/"}],
        "formats": {"vector": "application/x-ogc-gpkg"},
        "projection": "EPSG:4326",
        "name": name,
    }
    r = _post(f"{LINZ_API}/exports/", json=payload)
    r.raise_for_status()
    job = r.json()
    job_id = job["id"]
    poll_url = f"{LINZ_API}/exports/{job_id}/"
    print(f"  [{name}] Job {job_id} — polling every 60s (may take hours for large layers)...")

    for attempt in range(720):  # up to 12 hours
        time.sleep(60)
        r = _get(poll_url)
        r.raise_for_status()
        job = r.json()
        state = job.get("state", "processing")
        elapsed = (attempt + 1) * 60
        print(f"  [{name}] {state} ({elapsed//60}m)")
        if state == "complete":
            break
        if state in ("cancelled", "error", "failed"):
            raise RuntimeError(f"Export job {job_id} failed: {state}")
    else:
        raise TimeoutError(f"Export job {job_id} did not complete within 12 hours")

    # Find download URL — LINZ wraps it in items[].download_url or items[].file
    download_url = job.get("download_url")
    if not download_url:
        for item in job.get("items", []):
            download_url = item.get("download_url") or item.get("file")
            if download_url:
                break
    if not download_url:
        raise RuntimeError(f"No download URL in job response: {job}")

    print(f"  [{name}] Downloading...")
    tmp = out_path.with_suffix(".tmp")
    with _get(download_url, stream=True, timeout=300) as r:
        r.raise_for_status()
        total = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                total += len(chunk)
                print(f"\r  [{name}] {total / 1024 / 1024:.1f} MB", end="", flush=True)
    print()

    # Unzip if LINZ wrapped the gpkg
    if zipfile.is_zipfile(tmp):
        with zipfile.ZipFile(tmp) as z:
            gpkg_names = [n for n in z.namelist() if n.endswith(".gpkg")]
            if not gpkg_names:
                raise RuntimeError(f"No .gpkg inside zip from {download_url}")
            member = gpkg_names[0]
            with z.open(member) as src, open(out_path, "wb") as dst:
                dst.write(src.read())
        tmp.unlink()
    else:
        tmp.rename(out_path)

    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"  [{name}] Saved {size_mb:.1f} MB → {out_path}")
    return size_mb


def apply_changeset(name: str, layer_id: str, gpkg_path: Path, from_rev: int) -> int:
    """
    Fetch WFS changeset from from_rev to head and apply to the local GeoPackage.
    Returns number of features changed.

    The LINZ WFS changeset stream includes a __change__ property per feature:
      "insert", "update", "delete"
    """
    import sqlite3

    print(f"  [{name}] Fetching changeset from revision {from_rev} to head...")
    r = _get(LINZ_WFS, params={
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": f"layer-{layer_id}",
        "viewparams": f"from:{from_rev};to:head",
        "outputFormat": "application/json",
    }, timeout=600)
    r.raise_for_status()
    data = r.json()
    features = data.get("features", [])

    if not features:
        print(f"  [{name}] No changes")
        return 0

    print(f"  [{name}] Applying {len(features)} changes...")

    # Resolve table name from GeoPackage contents table
    with sqlite3.connect(str(gpkg_path)) as con:
        tables = [
            row[0]
            for row in con.execute(
                "SELECT table_name FROM gpkg_contents WHERE data_type='features'"
            ).fetchall()
        ]
        if not tables:
            raise RuntimeError(f"No feature tables in {gpkg_path}")
        table = tables[0]

        inserts = updates = deletes = 0
        for feat in features:
            props = feat.get("properties") or {}
            action = props.pop("__change__", props.pop("__action__", "insert"))
            fid = feat.get("id") or props.get("id")

            if action == "delete":
                if fid is not None:
                    con.execute(f'DELETE FROM "{table}" WHERE id = ?', (fid,))
                    deletes += 1
            else:
                # DELETE the old version first (for updates), then write via fiona below
                if action == "update" and fid is not None:
                    con.execute(f'DELETE FROM "{table}" WHERE id = ?', (fid,))
                    updates += 1
                else:
                    inserts += 1

        con.commit()

    # Write new/updated geometries via fiona (append mode)
    insert_feats = [
        f for f in features
        if f.get("properties", {}).get("__change__", "insert") != "delete"
    ]
    if insert_feats:
        try:
            import fiona
            with fiona.open(str(gpkg_path), "a") as dst:
                for feat in insert_feats:
                    props = dict(feat.get("properties") or {})
                    props.pop("__change__", None)
                    props.pop("__action__", None)
                    try:
                        dst.write({
                            "type": "Feature",
                            "geometry": feat.get("geometry"),
                            "properties": props,
                        })
                    except Exception as exc:
                        print(f"    warning: skipped feature: {exc}")
        except ImportError:
            print(f"  [{name}] WARNING: fiona not installed — deletes applied, inserts/updates skipped")
            print(f"  [{name}]   Run: pip install fiona  (or use --full next time)")

    print(f"  [{name}] Done: {inserts} inserted, {updates} updated, {deletes} deleted")
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
            size_mb = full_export(name, layer_id, gpkg)
        elif need_changeset:
            n = apply_changeset(name, layer_id, gpkg, local_rev)
            size_mb = gpkg.stat().st_size / 1024 / 1024
            print(f"  [{name}] {size_mb:.1f} MB on disk after {n} changes")
        else:
            # force=True but no revision change — just redo full
            size_mb = full_export(name, layer_id, gpkg)

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
