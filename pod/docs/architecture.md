# Pod Architecture

## Hardware

> **BOM, pin map, wiring, and power → [hardware.md](hardware.md)** (canonical, mirrors
> `config.h`). This section keeps only the design *rationale*; no pin tables live here.

Sensing is a single **BME280** (pressure + temperature + humidity, I²C). NB: the current
bench code still uses separate `Bmp180Reader` + `Aht10Reader` — a single `Bme280Reader`
swap is pending (see status.md / plans.md).

**Single display (2026-06-14):** the pod ships with **one** display, the 1.54" 4-colour
(Nijntje) panel. The 2.13" B/W "stats" panel is **out for now** (its reason-to-exist was
the on-demand compass, now dropped) — it can be re-added later if wanted.

**Dropped from the design (2026-06-13):** compass (HMC5883L), accelerometer (MPU6050),
buzzer, and the cyberdeck UART link. The compass/accel were navigation-only and never
fed weather prediction; the buzzer is gone (no audible alerts); sync to the VM is
SD-card sneakernet, not a live UART (cyberdeck itself is tabled — see `/docs/README.md`).
microSD is added in their place.

## Pin Assignments

**Canonical pin map → [hardware.md](hardware.md)** (and `config.h`, arch-split RP2350/ESP32).
Finalised 2026-06-14: single display + microSD, 16/20 GPIO used, spares GP0/9/10/11. Pins are
grouped by component (left = power/ADC/I²C/RTC, bottom = GPS, right = SPI for display + SD). The
RTC SQW alarm is on **GP15** (GP17 isn't broken out on this board). No pin tables live here.

## I2C Bus

All sensors share I2C1 (SDA=GP26, SCL=GP27). Addresses: DS3231=0x68, BME280=0x76.

## Wake Cycle

> **Cadence change (2026-06-14):** the old 1-min wake + every-5th-cycle split is replaced by
> a **single 10-minute wake**, phase-aligned to UTC (`:00/:10/.../:50`). 10 min divides both
> GPM's native 30-min grid and the hourly prediction grid cleanly (3 / 6 samples). The DS3231
> alarm is set to the next UTC 10-min boundary each cycle. The previous reason for a 1-min
> heartbeat (frequent GPS + connection polling) is gone: connection-detect (GX16, GP9) becomes
> a **pin interrupt**, and the display only changes at the 10-min cadence.

MCU wakes every 10 minutes via RTC alarm (DS3231 SQW → GP15), aligned to UTC.

**Every 10-min cycle:**
1. Wake GPS, get fix (≤8s timeout), read NMEA + RMC. (Keep the GPS backup rail powered so
   10-min gaps stay warm/hot-start — ephemeris stays valid, fixes stay quick.)
2. If first valid GPS fix this boot: seed RTC from GPS UTC time (GPS UTC stays authoritative).
3. Read BME280 (pressure, temp, humidity).
4. Altitude-adjust pressure (median of recent GPS alt) → store raw + adjusted.
5. Update RAM buffers; run activity detection → NijntjeState; check component health.
6. Run the rule-based weather algorithm → rain + storm confidence (cheap, every cycle).
7. Append a `raw/` telemetry row (UTC `Z` timestamp); refresh display if state/banner changed.
8. Sleep GPS, MCU → DORMANT until the next UTC 10-min boundary.

**On the UTC hour (every 6th cycle), additionally — the model path:**
- Build the model **input feature vector** from the trailing buffers (causal: data ≤ this hour),
  append to `inputs/` keyed by the UTC issue-hour.
- Run the combined coarse+fine model (streamed from SD; see *Model Inference*) → hourly forecast
  for horizons 0..24 → append to `pred/`, keyed by the same UTC issue-hour.
- Persist WeatherPrediction structs to LittleFS.

> Connection-detect (GX16) is interrupt-driven and may wake the MCU off-cadence to enter a
> docked/sync state; it is not part of the timed weather loop.

## RAM Buffers (survive DORMANT sleep)

| Buffer | Struct | Entries | Size |
|--------|--------|---------|------|
| GPS history | GpsEntry {lat,lon,alt,timestamp} | 15 | 240 bytes |
| Weather history | WeatherEntry {timestamp,pressureAdj,tempC,humidity,lat,lon} | 288 | 6.9KB |
| WeatherPrediction × 2 | rain + storm | — | ~40 bytes |
| **Total** | | | **~7.2KB** |

> ⚠️ **Entry counts predate the 10-min cadence and need re-tuning.** These windows were sized
> for 1-min spacing (GPS history = 15 min, weather = 24 hr). At 10-min spacing the *same counts*
> span 150 min / 48 hr, and the activity-detection thresholds (`CLIMBING_MIN_ENTRIES`,
> `WALKING_MIN_ENTRIES`, buffer length) must be re-derived so "10 min sustained climb" etc. still
> mean what they say. Pending task — see plans.md.

## Storage (2026-06-14)

Two tiers, split by what must survive the SD card being **removed** (sneakernet) or failing.

### microSD (FAT32, removable) — bulk logs + model

Append-only CSV, one record per line, flush per write (a half-written last line on brownout
is just dropped by the parser). **Daily files**, UTC-dated, header row + schema version. The
card is removable, so the firmware treats *missing/corrupt SD* as a normal degraded state —
keep running the rule-based algorithm + display, log a critical event, never hang.

```
/model/      <name>.bin … + manifest.json   ← model file(s) + manifest; read-only on the pod,
/raw/        2026-06-14.csv  (10-min telemetry)    copied on manually from the laptop
/inputs/     2026-06-14.csv  (hourly feature vectors, keyed by UTC issue-hour)
/pred/       2026-06-14.csv  (hourly forecasts, keyed by UTC issue-hour)
/events/     2026-06-14.log  (diagnostics)
```

- **`raw/`** is *telemetry* (sensors + device state: battery, free heap, Nijntje activity/state,
  gps_ms) — not predictions. Distinct from the old combined `data.csv`.
- **`inputs/`** logs the **exact feature vector the model consumed**, separate from `raw/` even
  though they overlap — this is the train/serve-skew guard (replay a prediction offline and it
  must reproduce). Columns are defined by the model's schema (see *Model Inference*).
- **`pred/`** is the model's hourly forecast. **Join key = UTC issue-hour** across `inputs`/`pred`
  (and, offline on the VM, the GPM labels). "Predictions" live on the pod; "labels" (GPM truth)
  exist only on the VM.

### LittleFS (internal flash, soldered) — small critical state

- `predictions.bin` — persisted WeatherPrediction structs (survive power cycles)
- calibration (BME280 pressure offset, etc.), **last-synced marker**
- a small **critical-event ring buffer** — including "SD missing/failed" (can't log an SD
  failure *to* the SD)
- Tide tables baked into firmware (~110–150KB)

> Note: the previous plan logged `data.csv`/`events.log` to LittleFS. With the SD added, bulk
> logging moves to the card; LittleFS keeps only the small can't-lose-it state above.

## Model Inference

The on-device model is the combined coarse+fine rain ensemble, kept as a **data file on SD**
(copied on manually from the laptop — manual deploy, no OTA). It is **not** compiled into
firmware: the production ensemble is far larger (~10–20 MB) than the 2 MB flash / 520 KB SRAM.

- **Streamed evaluation.** Gradient boosting is an additive sum of independent trees, so the
  evaluator streams trees from SD one at a time, runs all needed (horizon) input vectors through
  each, accumulates, and discards it — peak RAM is ~one tree (a few KB), not the whole model. One
  pass over the file yields all horizons × heads. Read all trees (do **not** early-stop — it
  breaks calibration of the probabilistic heads).
- **Schema gate (fail-safe).** `manifest.json` carries the model's feature **schema** (ordered
  names + units) and its **hash**. At load the pod compares the manifest hash against its own
  feature-builder's hash. **Mismatch → refuse the model, fall back to the rule-based algorithm,
  log a critical event** (the full schema in the manifest lets the event name the offending
  feature). Because deploy is a manual file copy, this is the only guard against running a stale
  model and logging silently-wrong predictions.
- Until a model is present + passes the gate, the pod runs the **rule-based weather algorithm
  only** (below).

## Component Fallbacks

| Component | Failure behaviour |
|-----------|------------------|
| GPS | Positions = 0, activity falls back to stationary, RTC provides timestamp |
| RTC | Timestamp priority: GPS unixTime → millis() → 0 |
| BME280 | No fallback — weather algorithm degrades silently |

## Display Stack

**1.54" 4-colour (Nijntje display):**
```
NijntjeEvaluator  →  NijntjeDisplay struct
NijntjeRenderer   →  IFramebuffer (abstract)
    [hardware]  Framebuffer : Adafruit_GFX  →  EPD1in54G  →  IDisplayHAL  →  SPI
    [native]    NativeFramebuffer (pure C++)  →  SDL2Display  →  SDL3 window
NijntjeSpriteRegistry  →  lookupSprite(state, modifier)  →  17 2bpp XBM headers in src/sprites/
```

**Single display (2026-06-14):** the 1.54" 4-colour panel is the only display. The 2.13" B/W
"stats" panel is **out for now** (can be re-added later); its pins (GP1/6/7/8) are freed.

**Native display simulator** (`[env:native_display]`): calls `NijntjeEvaluator::evaluate()` with test scenarios, renders via SDL3 window. SDL3 dev package lives in `vendor/` (gitignored). See [commands.md](commands.md).

Refresh: partial (0.3s) on rotary input / state change; full (2s) periodically to clear ghosting
(every Nth update or after a few partials — exact policy TBD with the 10-min cadence).

## Weather Algorithm

`storm = pressure_rate×0.50 + zambretti×0.25 + humidity_trend×0.20 + temp_drop×0.05`
`rain  = pressure_rate×0.45 + zambretti×0.30 + humidity_trend×0.20 + temp_drop×0.05`

There is no wind sensor and no compass — weather prediction is pressure/temp/humidity only. The Zambretti term uses pressure tendency + level (see CLAUDE.md).
Trigger: storm≥65%, rain≥55%. Clear: pressure recovered ≥50% AND confidence drops below 30%/25%.

## Activity Detection

Priority: Climbing → Walking/WalkingNight → SleepingTent → SleepyEvening → Resting.
Stationary = all GPS buffer entries within 25m of newest fix.
Modifiers (Walking/Climbing/Resting only): Foggy > Cold > Hot > None.

## Nijntje Display States

Priority: Connected → Worried → Climbing → Resting → WalkingNight → SleepyEvening → SleepingTent → Walking.
17 sprites total (4 states × 4 modifiers for Walking/Climbing/Resting, 5 single sprites).

## C++ Conventions

- `#pragma once` on every header
- Headers declare only; implementations in .cpp
- Forward declarations preferred over #include in headers
- Each .cpp includes its own .h and only what it directly needs
- `config.h` is universal include for all constants/pins
- Class members private, exposed via methods
