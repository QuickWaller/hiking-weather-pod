## Session Start
Read `/WORKING.md` before your first response. Summarise what's listed and confirm with the user which items are still active.

# Hiking Pod System — Project Context

## What This Is
A two-component hiking data logger for NZ backcountry/coastal hiking:
- **Pod** (RP2350-Zero): data logger, e-ink display, GPS/weather sensors, microSD storage
- **Cyberdeck** (CM5, Python): ⏸️ **tabled (2026-06-12)**. Was to receive pod logs and analyse weather/activity. Sync is now SD-card sneakernet (no live link).

> **Hardware change (2026-06-13/14):** compass (HMC5883L), accelerometer (MPU6050), the buzzer, and the cyberdeck UART link are **dropped**. Sensing is a single **BME280** (P+T+H), not BMP180+AHT10. A **microSD** breakout is added (carries the model file(s) + logs). Single display (1.54" only). Weather prediction is pressure/temp/humidity only; there is no audible alert. See `/docs/README.md`, `pod/docs/hardware.md`, `pod/docs/architecture.md`.

## Repo Structure
```
/pod      - Pod firmware (C++ Arduino + PlatformIO) → see pod/CLAUDE.md + pod/docs/
/deck     - Cyberdeck code (Python 3.8+)
/docs     - Shared documentation
README.md - Root overview
```

## Data Format

> **Storage layout (2026-06-14):** logs live on the **microSD** card in daily UTC-dated CSV files,
> split by purpose: `/raw` (10-min telemetry, below), `/inputs` (hourly model feature vectors),
> `/pred` (hourly model forecasts), `/events` (diagnostics). `inputs`/`pred` join on the UTC
> issue-hour; their columns are defined by the model manifest. Small can't-lose-it state stays on
> internal LittleFS. All timestamps are **UTC with a trailing `Z`**. See `pod/docs/architecture.md`
> → Storage.

The `/raw` telemetry stream (sensors + rule-based algorithm outputs + device state), one row per
10-min cycle:
```
timestamp,lat,lon,alt,temp,humidity,pressure_raw,pressure_adj,battery,storm_conf,rain_conf,storm_active,rain_active,pressure_rate,activity,state,modifier,banner,gps_ms,free_heap
2026-05-25T14:32:42Z,-41.2865,172.1043,847,12.3,65,980.2,978.1,64,58,42,0,0,-1.2,R,X,N,R,3240,198432
```

| Field | Type | Notes |
|---|---|---|
| timestamp | ISO 8601 **UTC** (`…Z`) | DS3231 (holds UTC), falls back to GPS UTC then 0. Display uses NZ-local; data/predictions/GPM are always UTC |
| lat | float | degrees |
| lon | float | degrees |
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
- Pod↔cyberdeck sync: **SD-card sneakernet** (no live UART — cyberdeck tabled). GX16-5 connector remains as a dock/connection-detect + 5V.
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
**Single 10-min wake** via RTC alarm, phase-aligned to UTC (`:00/:10/…`). Each cycle reads GPS +
sensors, runs the rule-based weather algorithm, and appends a `/raw` row. **On the UTC hour** it
also builds the model input vector and runs the combined coarse+fine model → `/inputs` + `/pred`
(10 min divides both GPM's 30-min grid and the hourly prediction grid cleanly). Connection-detect
is interrupt-driven. See pod/docs/architecture.md for full detail.

## Weather Prediction
Two parallel predictions (storm/rain). Confidence scoring from pressure rate, a pressure-tendency ("Zambretti") term, humidity trend, temp drop. Latched on trigger, cleared on pressure recovery.

> **Impl note:** there is **no wind sensor and no compass** — prediction is pressure/temp/humidity only. The "Zambretti" term now combines pressure **tendency** (rate) with absolute pressure **level** (boost below 1000 hPa, damp above 1020 hPa, on sea-level-adjusted pressure). Wind/season are still not used. NB: the level term is absolute, so BME280 pressure bias matters — worth a one-time offset calibration vs a known station.

## Activity Detection
From GPS buffer (15 entries). Priority: Climbing → Walking/WalkingNight → SleepingTent → SleepyEvening → Resting.

> **Impl note:** Climbing uses **net** altitude change over the window (not summed positive steps, which rectified GPS-altitude noise into phantom climbs). "Resting" is the daytime stationary fallback based on average speed below `WALKING_SPEED_KPH`; there is no 20-min dwell timer yet (`GpsBuffer::isStationary()` exists but is not yet wired in). WalkingNight now uses **computed sunrise/sunset** for the pod's location (USNO algorithm in `MathUtils::sunriseSunsetMinutes`), cached once per day (refreshed at the first wake ≥03:00 local, plus a boot bootstrap) in `main.cpp`. Falls back to a fixed 20:00–06:00 local window when sun times are unknown (no GPS fix / bad clock). Time-of-day is **NZ local**: `RtcReader::now()` keeps `unixTime` as UTC but converts the civil fields via `MathUtils::nzUtcOffsetMinutes` (NZST/NZDT, DST-aware). GPS/RTC are both UTC; once synced, GPS UTC stays authoritative and the RTC is re-synced if it drifts beyond `RTC_GPS_MAX_SKEW_S`. The stationary states are tied to the sun too: **Resting** while the sun is up, **SleepyEvening** from sunset until a fixed local bedtime (`SLEEPING_TENT_HOUR_START`), **SleepingTent** from bedtime through to sunrise. When sun times are unknown they fall back to the old fixed local windows.

## Buzzer
**Removed (2026-06-13)** — no buzzer in the design; no audible alerts. Warnings are display-only (banner + Worried Nijntje). Quiet-hours config/`BuzzerController` is dead code pending removal.
