# Open-Meteo License & Attribution

## Summary
This project uses **Open-Meteo** weather API for real-time validation of pod predictions.

## License
- **API Data:** CC BY 4.0 (Creative Commons Attribution 4.0 International)
- **Source Code (self-hosted):** AGPLv3 (if you deploy the server)

## Commercial Use

### Free Tier (Non-Commercial)
- **Limit:** 10,000 calls/day (600/min)
- **Cost:** Free
- **Use case:** Personal projects, research, non-profit
- **Attribution:** Required — must credit "Weather data by Open-Meteo.com"

### Paid Tier (Commercial)
- **Cost:** $29+/month (Standard tier, 1M calls/month)
- **Use case:** Commercial products, integrated services
- **Attribution:** Still required

### Current Status
**This pod validation pipeline is non-commercial research.** Using free tier with attribution.

**If the pod/cyberdeck becomes a commercial product:** Upgrade to paid subscription ($29+/month) or self-host the AGPLv3 server.

## Attribution
When displaying weather data in any user-facing interface, include:
```
Weather data by Open-Meteo.com
```

For this project (validation logs, stored CSVs), attribution in code comments is sufficient:
```python
# Open-Meteo API data (CC BY 4.0)
# https://open-meteo.com/
```

## Data Sources
Open-Meteo aggregates from:
- ERA5-Land (Copernicus, ECMWF) — reanalysis, 1940–present
- NOAA, DWD, Météo-France — observational data
All underlying sources are open-access (CC BY or CC BY-SA).

## Terms
- **Liability:** Capped at subscription fees paid (free = no liability claims)
- **Availability:** Data provided as-is; no uptime SLA on free tier
- **Rate limits:** Non-negotiable; enforced per-IP

See [Open-Meteo Terms of Service](https://open-meteo.com/en/terms) for details.

---

**Last updated:** 2026-06-04
