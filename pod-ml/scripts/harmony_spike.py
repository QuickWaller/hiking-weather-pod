"""Harmony spike — confirm we can bbox-subset GPM daily precip at a point for one month.

Throwaway exploration: GPM_3IMERGDF v07 (daily final), small box around the Hokitika foothills point,
June 2022. Verifies (a) Harmony accepts the request, (b) returns subsetted files, (c) the precip
variable/units/time look right. If this works, we generalise to all 5 points + the full range.
"""

import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore")

import xarray as xr  # noqa: E402
from harmony import BBox, Client, Collection, Request  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "data" / "raw" / "harmony_spike"
OUT.mkdir(parents=True, exist_ok=True)

client = Client()
req = Request(
    collection=Collection(id="C2723754864-GES_DISC"),   # GPM_3IMERGDF v07 (daily)
    spatial=BBox(170.9, -42.9, 171.3, -42.5),           # small box around Hokitika foothills
    temporal={"start": datetime(2022, 6, 1), "stop": datetime(2022, 6, 30, 23, 59)},
)
print("request valid:", req.is_valid(), "| errors:", req.error_messages())

job_id = client.submit(req)
print("submitted job:", job_id)
client.wait_for_processing(job_id, show_progress=False)

files = [f.result() for f in client.download_all(job_id, directory=str(OUT), overwrite=True)]
print(f"downloaded {len(files)} file(s)")
for f in files[:3]:
    print("  ", Path(f).name)

if files:
    try:
        ds = xr.open_dataset(files[0])
    except Exception:  # noqa: BLE001
        ds = xr.open_dataset(files[0], group="Grid")
    print("\n--- first file ---")
    print("dims:", dict(ds.sizes))
    print("coords:", list(ds.coords))
    for n, v in ds.data_vars.items():
        print(f"  {n}: dims={v.dims} units={v.attrs.get('units', '?')}")
