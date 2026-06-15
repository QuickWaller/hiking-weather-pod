"""
LINZ layer registry — verify IDs at https://data.linz.govt.nz/layer/<id>/
Each layer gets /data/linz/<key>/<name>.gpkg on the VM.
"""

import os as _os
BASE_DIR = _os.environ.get("LINZ_BASE_DIR", _os.path.expanduser("~/linz-data"))
LINZ_API = "https://data.linz.govt.nz/services/api/v1"
LINZ_WFS = "https://data.linz.govt.nz/services/wfs"

# cadence_days: how often to check for LINZ updates
# LINZ publishes quarterly changeset for topo layers; daily for roads in some regions
LAYERS = {
    "contours": {
        "linz_id": "50768",
        "name": "nz-contours",
        "cadence_days": 90,
        "description": "NZ Contours (Topo, 1:50k) — 20m interval",
    },
    "tracks": {
        "linz_id": "50364",
        "name": "nz-track-centrelines",
        "cadence_days": 30,
        "description": "NZ Track Centrelines (Topo, 1:50k)",
    },
    "roads": {
        "linz_id": "50329",
        "name": "nz-road-centrelines",
        "cadence_days": 30,
        "description": "NZ Road Centrelines (Topo, 1:50k)",
    },
    "lakes": {
        "linz_id": "50293",
        "name": "nz-lake-polygons",
        "cadence_days": 90,
        "description": "NZ Lake Polygons (Topo, 1:50k)",
    },
    "rivers": {
        "linz_id": "50327",
        "name": "nz-river-centrelines",
        "cadence_days": 90,
        "description": "NZ River Centrelines (Topo, 1:50k)",
    },
    "coastline": {
        "linz_id": "51153",
        "name": "nz-coastlines-and-islands",
        "cadence_days": 365,
        "description": "NZ Coastlines and Islands Polygons (Topo, 1:50k)",
    },
    "peaks": {
        "linz_id": "50284",
        "name": "nz-height-points",
        "cadence_days": 365,
        "description": "NZ Height Points (Topo, 1:50k) — named summits + spot heights",
    },
    "glaciers": {
        "linz_id": "50287",
        "name": "nz-ice-polygons",
        "cadence_days": 365,
        "description": "NZ Ice Polygons (Topo, 1:50k) — glaciers and snowfields",
    },
}
