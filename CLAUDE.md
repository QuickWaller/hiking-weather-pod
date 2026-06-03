# Hiking Pod System — Project Context

## What This Is
A two-component hiking data logger for NZ backcountry/coastal hiking:
- **Pod** (RP2350-Zero): data logger, e-ink display, GPS/weather sensors, buzzer alerts
- **Cyberdeck** (CM5, Python): receives pod logs, analyses weather and activity, displays summaries

## Repo Structure
```
/pod      - Pod firmware (C++ Arduino + PlatformIO) → see pod/CLAUDE.md + pod/docs/
/deck     - Cyberdeck code (Python 3.8+)
/docs     - Shared documentation
README.md - Root overview
```

## Data Format
CSV, logged every 5 minutes:
```
timestamp,lat,lon,alt,temp,humidity,pressure_raw,pressure_adj,battery,storm_conf,rain_conf,storm_active,rain_active,pressure_rate,activity,state,modifier,banner,gps_ms,free_heap
2026-05-25T14:32:42,-41.2865,172.1043,847,12.3,65,980.2,978.1,64,58,42,0,0,-1.2,R,X,N,R,3240,198432
```

| Field | Type | Notes |
|---|---|---|
| timestamp | ISO 8601 | DS3231, falls back to GPS UTC then 0 |
| lat | float | degrees |
| lon | float | degrees |
| alt | int | metres |
| temp | float | °C, AHT10 |
| humidity | int | %, AHT10 |
| pressure_raw | float | hPa, BMP180 as-read |
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
- Tide tables: generated from LINZ data via one-time Python script on cyberdeck, baked into `tidal_tables.h`. 5 NZ cities (Auckland, Wellington, Christchurch, Dunedin, Tauranga), 2026–2030.
- Celestial calculations: simplified algorithms (±1-2 min accuracy) — NOT full Meeus

## Nijntje Display Character
Main screen only (1.54" 4-colour display). Sprites are 2bpp XBM bitmaps via Adafruit GFX drawBitmap(). ~48×48px.

### Primary states (priority order)
1. **Connected** — syncing with cyberdeck
2. **Worried** — storm imminent (pairs with Red banner)
3. **Climbing** — significant elevation gain
4. **Resting** — daytime, not climbing/walking (speed below threshold)
5. **WalkingNight** — moving between sunset and sunrise
6. **SleepyEvening** — stationary, early evening
7. **SleepingTent** — stationary, midnight to sunrise
8. **Walking** — default

### Modifiers (Walking/Climbing/Resting only)
Priority: **Foggy > Cold > Hot > None**

### Banner
None (white) / Yellow (rain possible) / Red (storm coming)

### Sprite set: 17 total
Walking/Climbing/Resting × 4 modifiers each = 12. SleepyEvening, SleepingTent, WalkingNight, Worried, Connected = 5.

## Wake Cycle
1-min wake via RTC alarm. Every 5th cycle also reads sensors + runs weather algorithm + writes log.
See pod/docs/architecture.md for full detail.

## Weather Prediction
Two parallel predictions (storm/rain). Confidence scoring from pressure rate, a pressure-tendency ("Zambretti") term, humidity trend, temp drop. Latched on trigger, cleared on pressure recovery.

> **Impl note:** there is **no wind sensor** — the HMC5883L is a navigation compass only (heading/bearing), never an input to weather prediction. The "Zambretti" term now combines pressure **tendency** (rate) with absolute pressure **level** (boost below 1000 hPa, damp above 1020 hPa, on sea-level-adjusted pressure). Wind/season are still not used. NB: the level term is absolute, so BMP180 bias matters — worth a one-time offset calibration vs a known station.

## Activity Detection
From GPS buffer (15 entries). Priority: Climbing → Walking/WalkingNight → SleepingTent → SleepyEvening → Resting.

> **Impl note:** Climbing uses **net** altitude change over the window (not summed positive steps, which rectified GPS-altitude noise into phantom climbs). "Resting" is the daytime stationary fallback based on average speed below `WALKING_SPEED_KPH`; there is no 20-min dwell timer yet (`GpsBuffer::isStationary()` exists but is not yet wired in). WalkingNight now uses **computed sunrise/sunset** for the pod's location (USNO algorithm in `MathUtils::sunriseSunsetMinutes`), cached once per day (refreshed at the first wake ≥03:00 local, plus a boot bootstrap) in `main.cpp`. Falls back to a fixed 20:00–06:00 local window when sun times are unknown (no GPS fix / bad clock). Time-of-day is **NZ local**: `RtcReader::now()` keeps `unixTime` as UTC but converts the civil fields via `MathUtils::nzUtcOffsetMinutes` (NZST/NZDT, DST-aware). GPS/RTC are both UTC; once synced, GPS UTC stays authoritative and the RTC is re-synced if it drifts beyond `RTC_GPS_MAX_SKEW_S`. The stationary states are tied to the sun too: **Resting** while the sun is up, **SleepyEvening** from sunset until a fixed local bedtime (`SLEEPING_TENT_HOUR_START`), **SleepingTent** from bedtime through to sunrise. When sun times are unknown they fall back to the old fixed local windows.

## Buzzer
Quiet hours 22:00–07:00. Severe storm (≥85% confidence) overrides quiet hours.
