# Cyberdeck — Context

> ## ⏸️ TABLED (2026-06-12)
> The cyberdeck is **shelved** and currently considered unlikely to happen — but the option is
> kept open. As a consequence **the pod has no UART**: the GX16-5 connector, UART1, `UartSync`,
> and the `PIN_CYBERDECK_*` / `PIN_GX16_DETECT` pins are dropped from the pod design. Pod logs
> reach the VM by **SD-card sneakernet**, not over a serial link to a deck.
>
> Everything below describes the *original* cyberdeck plan and is **not maintained**. To revive:
> re-add the pod UART link, then resume from this spec.

## Language & Environment
Python 3.8+, running on CM5.

## Responsibilities
- Receive pod logs via UART (115200 baud, GX16-5 connector, /dev/ttyUSB0)
- Parse, validate, and store logs to disk (CSV per trip)
- Analyse weather: pressure trends, dew point, rain/storm/frost risk
- Analyse activity: distance, elevation, rest detection, GPS coords
- Display terminal UI or web dashboard with trip summary and forecast

## UART Config
- Port: `/dev/ttyUSB0`
- Baud: 115200
- Protocol: pod streams one CSV line per entry when connected. Send `DUMP\n` to receive the full flash log; pod replies with all CSV lines then `END\n`. Send `HELLO\n` for handshake.
- Format received (CSV, 20 fields):
  ```
  timestamp,lat,lon,alt,temp,humidity,pressure_raw,pressure_adj,battery,storm_conf,rain_conf,storm_active,rain_active,pressure_rate,activity,state,modifier,banner,gps_ms,free_heap
  ```
  | Field | Type | Notes |
  |---|---|---|
  | timestamp | ISO 8601 | |
  | lat | float | degrees |
  | lon | float | degrees |
  | alt | int | metres |
  | temp | float | °C (AHT10) |
  | humidity | int | % (AHT10) |
  | pressure_raw | float | hPa as-read |
  | pressure_adj | float | hPa altitude-adjusted |
  | battery | int | % estimate |
  | storm_conf | int | 0–100 |
  | rain_conf | int | 0–100 |
  | storm_active | 0/1 | prediction latched |
  | rain_active | 0/1 | prediction latched |
  | pressure_rate | float | hPa/hr, negative = falling |
  | activity | char | C/W/N/R/E/T |
  | state | char | C/W/N/R/E/T/X/K |
  | modifier | char | N/H/C/F |
  | banner | char | N/Y/R |
  | gps_ms | int | ms to fix (8000 = timeout) |
  | free_heap | int | bytes free RAM |

## Analysis Algorithms

### Weather
- Altitude-adjusted pressure (sea-level equivalent) before all trend analysis
- Dew point: Magnus formula from temp + humidity
- Rain probability: pressure drop >1 hPa/hr = rain in 12-24h (confidence ~80%)
- Storm probability: pressure drop >3 hPa/hr = storm in 6-12h (confidence ~75%)
- Frost risk: dew point <2°C + temp dropping = frost tonight (confidence ~72%)
- Lapse rate: (temp drop / altitude gain) × 1000 = °C/km; >9.8 = unstable air

### Activity
- Distance: haversine formula on GPS deltas, summed over trip
- Elevation: sum positive/negative altitude changes separately
- Rest detection: stationary >30min = rest. Categories: brief (<35min), short (35-90min), medium (90-180min), camp (>480min)
- Pace: distance / time in km/hr

### Tidal
- 5-year tables (2026-2030) for Auckland, Wellington, Christchurch, Dunedin, Tauranga
- Generated from LINZ data via one-time script, stored as structured data
- Nearest city by haversine distance from GPS position
- Current tidal state: rising, falling, slack

## Testing Strategy

Standard pytest suite must be implemented.

```
test/
  test_weather.py   — rain/storm/frost detection, pressure trend, dew point
  test_activity.py  — haversine distance, elevation, rest detection, pace
  test_tidal.py     — city lookup, tide table queries, tidal state calculation
  test_parser.py    — UART log parsing, validation, edge cases (bad GPS, out-of-range values)
  test_models.py    — data class behaviour
```

Use known input data with verified expected outputs. No mocking of serial port needed for unit tests — test analysis functions directly with data structs.

## Key Thresholds (config.py)
- `PRESSURE_DROP_RAIN = 1.0` hPa/hr
- `PRESSURE_DROP_STORM = 3.0` hPa/hr
- `REST_MIN_DURATION = 30` min
- `DATA_DIR = "./data"`
