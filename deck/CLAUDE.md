# Cyberdeck — Context

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
- Format received: `timestamp|lat,lon|alt|temp|humidity|pressure|battery`

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
