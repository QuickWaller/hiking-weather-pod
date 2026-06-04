# pod-ml: Weather Prediction ML Pipeline + Real-Time Validation

ML pipeline for NZ weather prediction + real-time pod validation system.

## Validation Pipeline (Step 6) — LIVE

**Open-Meteo hourly observations (as of 2026-06-04):**
- ✅ Running: Cron job fetches hourly (top of hour)
- ✅ Data: 7-day rolling window, 5 NZ probe points (Hokitika, Christchurch, Mt. Cook, Long Bay, Milford)
- ✅ Variables: precipitation (mm/hr), pressure (hPa), temperature (°C), humidity (%)
- ✅ Storage: `data/raw/openmeteo/*.csv` (rolling 1-year retention)
- ⚖️ License: CC BY 4.0 (free tier, non-commercial) — see OPENMETEO_LICENSE.md

## Training Data Status

**GPM IMERG (ongoing):**
- Progress: 11/294 months (3.7%)
- **ETA: June 17–18, 2026** (~15 days)
- Rate: ~77 min/month (30-min rainfall, 2000–2024)

**ERA5-Land:** ✅ Complete (1991–2024, 5 probe points)

## Quick Start

```bash
bash scripts/setup-vm.sh  # Sets up cron, venv, pre-commit hook
```

Cron job runs automatically:
```
0 * * * * cd <repo>/pod-ml && source .venv/bin/activate && python -m podml.fetch_openmeteo
```

## Hike Validation Workflow

1. Pod logs during hike: GPS + predictions (rain_conf, storm_conf, activity)
2. Post-hike: compare pod predictions vs. Open-Meteo ground truth
3. Iterate: 5–10 hikes → refine model

## Key Files

- `src/podml/fetch_openmeteo.py` — Validation logger (195 lines, full logging)
- `test/test_openmeteo/` — 8 unit tests (all passing)
- `OPENMETEO_LICENSE.md` — Attribution & commercial licensing info
- `config/nz_domain.yaml` — 5 probe points, domain config
- `logs/openmeteo_cron.log` — Hourly cron output

---

See [../CLAUDE.md](../CLAUDE.md) for full project context.
