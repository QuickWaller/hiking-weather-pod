# Hiking Pod System — Project Context

## What This Is
A two-component hiking data logger for NZ backcountry/coastal hiking:
- **Pod** (RP2350-Zero): data logger, e-ink display, GPS/weather sensors, buzzer alerts
- **Cyberdeck** (CM5, Python): receives pod logs, analyses weather and activity, displays summaries

## Repo Structure
```
/pod      - Pod firmware (C++ Arduino + PlatformIO)
/deck     - Cyberdeck code (Python 3.8+)
/docs     - Shared documentation
README.md - Root overview
```

## Data Format
Pipe-delimited CSV, logged every 5 minutes:
```
timestamp|lat,lon|alt|temp|humidity|pressure_raw|pressure_adj|battery|storm_conf|rain_conf|storm_active|rain_active|pressure_rate|activity|state|modifier|banner|gps_ms|free_heap
2026-05-25T14:32:42|-41.2865,172.1043|847|12.3|65|980.2|978.1|64|58|42|0|0|-1.2|R|X|N|R|3240|198432
```

| Field | Type | Notes |
|---|---|---|
| timestamp | ISO 8601 | DS3231 |
| lat,lon | float,float | degrees |
| alt | int | metres |
| temp | float | °C, BME280 |
| humidity | int | %, BME280 |
| pressure_raw | float | hPa, BME280 as-read |
| pressure_adj | float | hPa, altitude-adjusted |
| battery | int | % estimate via ADC |
| storm_conf | int | 0–100, algorithm output |
| rain_conf | int | 0–100, algorithm output |
| storm_active | 0/1 | prediction latched |
| rain_active | 0/1 | prediction latched |
| pressure_rate | float | hPa/hr over last 3hr (negative = falling) |
| activity | char | C/W/N/R/E/T = Climbing/Walking/Night/Resting/sEepy/Tent |
| state | char | C/W/N/R/E/T/X/K = above + Worried/connected |
| modifier | char | N/H/C/F = None/Hot/Cold/Foggy |
| banner | char | N/Y/R = None/Yellow/Red |
| gps_ms | int | ms to get GPS fix (8000 = timeout) |
| free_heap | int | bytes of free RAM at cycle time |

## Shared Technical Decisions
- UART between pod and cyberdeck: 115200 baud, GX16-5 connector
- Tide tables: generated from LINZ data via one-time Python script on cyberdeck, baked into `tidal_tables.h` compiled into pod firmware. 5 NZ cities (Auckland, Wellington, Christchurch, Dunedin, Tauranga), 2026–2030.
- Celestial calculations: simplified algorithms (±1-2 min accuracy) — NOT full Meeus

## Nijntje Display Character
Main screen only (1.54" 4-colour display). Sprites are 2bpp XBM bitmaps rendered via Adafruit GFX drawBitmap(). Size TBD (~48×48px).

### Primary states (priority order, highest first)
1. **Connected** — syncing with cyberdeck
2. **Worried** — storm imminent (pairs with Red banner)
3. **Climbing** — significant elevation gain in progress
4. **Resting** — GPS stationary 20+ minutes during day
5. **WalkingNight** — moving between sunset and sunrise
6. **SleepyEvening** — stationary, early evening (campfire)
7. **SleepingTent** — stationary, midnight to sunrise (tent)
8. **Walking** — default

### Modifier (applied on top of primary state)
One modifier maximum. Priority when multiple conditions true: **Foggy > Cold > Hot > None**
- **Foggy** — dew point spread <1.5°C + humidity >95%
- **Cold** — low temperature
- **Hot** — high temperature
- **None** — default

Modifiers apply to: Walking, Climbing, Resting.
No modifier variants for: WalkingNight, SleepyEvening, SleepingTent, Worried, Connected.

### Banner (independent of Nijntje state)
- **None** — white (no alert)
- **Yellow** — rain possible
- **Red** — storm coming (Worried state will almost always pair with this)

### Sprite set (17 total)
- Walking × 4 (None/Hot/Cold/Foggy)
- Climbing × 4 (None/Hot/Cold/Foggy)
- Resting × 4 (None/Hot/Cold/Foggy)
- SleepyEvening × 1
- SleepingTent × 1
- WalkingNight × 1
- Worried × 1
- Connected × 1

Tired state deferred — reskin of Walking later.

### Architecture
`NijntjeState`, `NijntjeModifier`, `BannerState` evaluated independently.
`NijntjeDisplay` struct bundles all three. `NijntjeRenderer` renders to Framebuffer.
Sensor evaluation (thresholds, conditions) is not yet implemented.

## Wake Cycle

MCU wakes every 1 minute via RTC alarm.

**Every 1-min cycle:**
1. Check GX16 pin (GP9) — if connected and not currently showing Connected state, update display and sleep
2. Wake GPS via UBX command, get fix (timeout 8s), read NMEA
3. Altitude-adjust cached pressure (hypsometric formula) — store both raw and adjusted in memory
4. Run activity detection algorithm → NijntjeState
5. If state or banner changed → refresh display
6. Sleep GPS via UBX command, MCU back to DORMANT

**Every 5th cycle (5 minutes), additionally:**
- Read BME280 (temp, humidity, pressure)
- Run weather algorithm → update rain + storm predictions
- Write log entry to flash

**Log format:**
```
timestamp|lat,lon|alt|temp|humidity|pressure_raw|pressure_adj|battery
2026-05-25T14:32:42|-41.2865,172.1043|847|12.3|65|980.2|978.1|64
```

## RAM Buffers

All buffers survive DORMANT sleep. Seeded from flash on boot.

| Buffer | Struct | Entries | Size |
|---|---|---|---|
| GPS history | `GpsEntry` {lat,lon,alt,timestamp} | 30 (30 min) | 480 bytes |
| Weather history | `WeatherEntry` {timestamp,pressureAdj,tempC,humidity} | 288 (24 hrs) | 4.6KB |
| WeatherPrediction × 2 | rain + storm | — | ~40 bytes |
| **Total** | | | **~5KB** |

## Activity Detection

Runs every 1-min cycle from `GpsBuffer` (last 30 entries).

Priority order:
1. **Climbing** — avg altitude gain > `CLIMBING_ALT_GAIN_M_PER_MIN` over last 10 entries
2. **Walking / WalkingNight** — avg speed > `WALKING_SPEED_KPH` over last 10 entries; night = between sunset and sunrise
3. **SleepingTent** — stationary, 00:00–sunrise
4. **SleepyEvening** — stationary, `SLEEPY_EVENING_HOUR_START`–`SLEEPY_EVENING_HOUR_END`
5. **Resting** — stationary (default daytime)

Modifier (Walking/Climbing/Resting only — not Night/Evening/Tent/Worried/Connected):
- **Foggy**: dew point spread < `FOG_DEWPOINT_SPREAD_C` AND humidity > `FOG_HUMIDITY_PCT`
- **Cold**: temp < `COLD_TEMP_C`
- **Hot**: temp > `HOT_TEMP_C`

## Weather Prediction

Runs every 5-min cycle from `WeatherBuffer` (last 288 entries).

Two parallel predictions — same latch/clear logic, different weights:

**Confidence scoring:**
```
storm = pressure_rate×0.50 + zambretti×0.25 + humidity_trend×0.20 + temp_drop×0.05
rain  = pressure_rate×0.45 + zambretti×0.30 + humidity_trend×0.20 + temp_drop×0.05
```
Zambretti accuracy reduced without wind direction sensor.

**Trigger:** confidence >= threshold (storm 65%, rain 55%)
**Latch:** warning stays active once triggered
**Clear:** pressure recovered >= 50% of original drop AND confidence < clear threshold (storm 30%, rain 25%)
  - "Original drop" = `baselinePressure` (max pressure in last 24hrs when prediction triggered)
  - Rate of recovery must be gradual — fast bounce does not clear warning

**Countdown:** recalculated each 5-min cycle from current pressure rate (Option B — continuously updated)
```
< 6 hours  → "STORM ~N HRS"
6-12 hours → "STORM TODAY"
> 12 hours → "STORM LIKELY"
overdue    → "STORM ARRIVING"
```
Same pattern for rain with Yellow banner.

**WeatherPrediction struct:**
```cpp
struct WeatherPrediction {
    uint32_t predictedAt;       // unix timestamp when triggered
    uint32_t estimatedArrival;  // recalculated each cycle
    uint8_t  confidence;        // 0-100
    float    baselinePressure;  // max pressure at trigger time
    bool     active;
};
```

## Buzzer

- **Quiet hours:** 22:00–07:00, no chirps
- **Severe storm override:** if `storm.confidence >= SEVERE_STORM_THRESHOLD` (85%), chirp regardless of hour

## Weather Algorithm Ideas (Future Work)
Not yet implemented. Candidate approaches:
1. Linear regression on altitude-adjusted pressure (circular buffer, last 3-6 hours)
2. Zambretti algorithm — sea-level pressure + trend → forecast category lookup table
3. Rate → imminence lookup (empirical: >6 hPa/3hr falling = <2h to event)
4. Humidity trend as confidence modifier

Realistic accuracy: 70-80% for rain/no-rain. Time-of-arrival ±2-4 hours.
Algorithm weightings are TBD — designed to be tunable over time.
NZ Southern Alps orographic effects worth considering (GPS position could infer which side of ranges).
Always present predictions with confidence percentages, never as certainties.
