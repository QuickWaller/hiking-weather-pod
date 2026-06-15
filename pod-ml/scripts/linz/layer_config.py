"""
LINZ layer registry — verify IDs at https://data.linz.govt.nz/layer/<id>/
Each layer gets /data/linz/<key>/<name>.gpkg on the VM.
"""

BASE_DIR = "/data/linz"
LINZ_API = "https://data.linz.govt.nz/services/api/v1"
LINZ_WFS = "https://data.linz.govt.nz/services/wfs"

# cadence_days: how often to check for LINZ updates
# LINZ publishes quarterly changeset for topo layers; daily for roads in some regions
LAYERS = {
    "contours": {
        "linz_id": "50767",
        "name": "nz-contours",
        "cadence_days": 90,
        "description": "NZ Contours (Topo, 1:50k) — 20m interval",
    },
    "tracks": {
        "linz_id": "50149",
        "name": "nz-walking-and-tramping-tracks",
        "cadence_days": 30,
        "description": "NZ Walking and Tramping Tracks",
    },
    "roads": {
        "linz_id": "50329",
        "name": "nz-road-centrelines",
        "cadence_days": 30,
        "description": "NZ Road Centrelines",
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
        "description": "NZ River Centrelines",
    },
    "coastline": {
        "linz_id": "51153",
        "name": "nz-coastlines-and-islands",
        "cadence_days": 365,
        "description": "NZ Coastlines and Islands Polygons",
    },
    "peaks": {
        "linz_id": "50308",
        "name": "nz-spot-heights",
        "cadence_days": 365,
        "description": "NZ Spot Heights (Topo, 1:50k)",
    },
    "glaciers": {
        "linz_id": "50209",
        "name": "nz-glacier-polygons",
        "cadence_days": 365,
        "description": "NZ Glacier Polygons",
    },
}
