#!/usr/bin/env python3
"""
linz_status.py — Aggregate per-layer LINZ status into dashboard JSON.

Reads /data/linz/<layer>/status.json for every configured layer and writes
a summary to the Nepter dashboard status path.

Run directly or from cron.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from layer_config import LAYERS, BASE_DIR

REPO = Path(__file__).parent.parent.parent  # scripts/linz/../../ = pod-ml/
DASHBOARD_STATUS = REPO / "data" / "linz_status.json"


def layer_summary(name: str) -> dict:
    p = Path(BASE_DIR) / name / "status.json"
    if not p.exists():
        return {"state": "not started", "name": name}
    st = json.loads(p.read_text())
    return {
        "name": name,
        "state": st.get("state", "unknown"),
        "last_revision": st.get("last_revision"),
        "last_updated": st.get("last_updated"),
        "file_size_mb": st.get("file_size_mb"),
        "cadence_days": st.get("cadence_days", LAYERS[name]["cadence_days"]),
        "description": LAYERS[name]["description"],
        "error": st.get("error"),
    }


def main() -> None:
    layers = {name: layer_summary(name) for name in LAYERS}

    total_mb = sum(v.get("file_size_mb") or 0 for v in layers.values())
    n_complete = sum(1 for v in layers.values() if v.get("state") == "complete")
    n_error = sum(1 for v in layers.values() if v.get("state") == "error")

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_layers": len(LAYERS),
            "complete": n_complete,
            "error": n_error,
            "total_size_mb": round(total_mb, 1),
        },
        "layers": layers,
    }

    DASHBOARD_STATUS.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD_STATUS.write_text(json.dumps(out, indent=2))
    print(f"LINZ status → {DASHBOARD_STATUS}  ({n_complete}/{len(LAYERS)} complete, {total_mb:.0f} MB)")


if __name__ == "__main__":
    main()
