# Hiking Pod System

A two-component hiking data logger for NZ backcountry and coastal hiking.

## Components

| Component | Hardware | Role |
|---|---|---|
| **Pod** | RP2350-Zero | Data logger, e-ink display, GPS/weather sensors, microSD storage |
| **Cyberdeck** | CM5, Python | ⏸️ tabled (2026-06-12) — was to receive pod logs and analyse weather/activity |

Logs sync to the analysis VM by **SD-card sneakernet** (no live link — the cyberdeck is tabled).

---

## Hardware (Pod)

- **MCU:** RP2350-Zero (Cortex-M33, hardware FPU, 2MB flash)
- **Display:** Waveshare 1.54" 4-colour e-ink (200×200px, Black/White/Yellow/Red) — the only display
- **GPS:** NEO-M8N (UART, software sleep via UBX commands)
- **Weather:** BME280 (I2C, forced mode — temp/humidity/pressure)
- **RTC:** DS3231 (I2C, SQW wake alarm → GP15)
- **Storage:** microSD (logs + model file) + LittleFS on 2MB onboard flash for small critical state

> Full pin map + BOM: [`pod/docs/hardware.md`](pod/docs/hardware.md). No compass, accelerometer,
> or buzzer (all dropped); pod has no UART link.

---

## Wake Cycle

The pod spends most of its time in DORMANT mode. The RTC triggers a single **10-minute** wake,
phase-aligned to UTC (so samples tile GPM's 30-min / hourly grid cleanly).

```
every 10 minutes (aligned to UTC :00/:10/…):
  wake GPS (UBX command), get fix (timeout 8s)
  read BME280 (temp, humidity, pressure)
  altitude-adjust pressure → store in memory
  run activity detection + rule-based weather algorithm
  append a /raw telemetry row to SD; refresh display if state/banner changed

  on the UTC hour:
    build model input vector → /inputs
    run the combined coarse+fine model (streamed from SD) → /pred

  sleep GPS, MCU → DORMANT
```

Connection-detect (GX16) is interrupt-driven, separate from the timed loop.

---

## Activity Detection

Runs each 10-min cycle from the GPS circular buffer. (Buffer length + thresholds are being
re-tuned for the 10-min cadence — they were sized for the old 1-min wake.)

### State Priority (highest first)

| Priority | State | Condition |
|---|---|---|
| 1 | Connected | GX16 pin high |
| 2 | Worried | Storm imminent (weather algorithm) |
| 3 | Climbing | Avg altitude gain > threshold over last 10 min |
| 4 | Resting | Stationary, daytime |
| 5 | WalkingNight | Moving, between sunset and sunrise |
| 6 | SleepyEvening | Stationary, early evening |
| 7 | SleepingTent | Stationary, midnight to sunrise |
| 8 | Walking | Default |

### Modifiers

Applies to Walking, Climbing, Resting only. Priority: **Foggy > Cold > Hot > None**

| Modifier | Condition |
|---|---|
| Foggy | Dew point spread < 1.5°C AND humidity > 95% |
| Cold | Temp < 8°C |
| Hot | Temp > 25°C |

Modifier state is cached from the last 10-minute BME280 read.

---

## Weather Prediction

This rule-based algorithm is the on-device **baseline/fallback**; the primary forecast is the
combined coarse+fine ML model (streamed from SD, run hourly — see `pod/docs/architecture.md`).
The rule-based scorer runs each 10-min cycle from the 24-hour pressure history buffer.

### Confidence Scoring

Two parallel predictions — storm (Red banner) and rain (Yellow banner):

```
storm_confidence = pressure_rate_score × 0.50
                 + zambretti_score      × 0.25
                 + humidity_trend_score × 0.20
                 + temp_drop_score      × 0.05

rain_confidence  = pressure_rate_score × 0.45
                 + zambretti_score      × 0.30
                 + humidity_trend_score × 0.20
                 + temp_drop_score      × 0.05
```

Each component scored 0.0–1.0. Final confidence as a percentage (0–100).

Pressure rate is the strongest single predictor. Zambretti achieves ~90% accuracy for
12-hour forecasts but is reduced here due to lack of wind direction sensor.

### Trigger / Latch / Clear

- **Trigger:** confidence crosses threshold (storm ≥65%, rain ≥55%)
- **Latch:** warning stays active once triggered — pressure briefly stabilising does NOT clear it
- **Clear:** pressure has recovered ≥50% of original drop AND confidence drops below clear threshold (storm <30%, rain <25%)
- **Baseline pressure** is the maximum pressure recorded in the last 24 hours at trigger time — this is the pre-drop reference point

### Countdown Display

Estimated arrival is recalculated each cycle from current pressure rate:

```
< 6 hours   → "STORM ~2 HRS"    + "CONFIDENCE 73%"
6–12 hours  → "STORM TODAY"     + "CONFIDENCE 58%"
> 12 hours  → "STORM LIKELY"    + "CONFIDENCE 51%"
overdue     → "STORM ARRIVING"  + "CONFIDENCE 81%"
```

Same pattern for rain with Yellow banner. (No buzzer — alerts are display-only.)

---

## Display

### Nijntje Character

A pixel art Nijntje figure displayed on the 1.54" 4-colour e-ink screen. State and modifier
select one of 17 pre-rendered sprites (220×160px, 2bpp, Black/White/Yellow/Red).

### Banner (bottom 40px)

| Colour | Content |
|---|---|
| Red | Storm alert — two lines of text |
| Yellow | Rain alert — two lines of text |
| White | Activity label: WALKING / CLIMBING / RESTING / SLEEPING / SYNCING |

### Sprite Set (17 total)

- Walking × 4 (None/Hot/Cold/Foggy)
- Climbing × 4 (None/Hot/Cold/Foggy)
- Resting × 4 (None/Hot/Cold/Foggy)
- WalkingNight × 1
- SleepyEvening × 1
- SleepingTent × 1
- Worried × 1
- Connected × 1

---

## Data Log Format

Comma-separated CSV on **microSD**, daily UTC-dated files split by purpose: `/raw` (10-min
telemetry), `/inputs` + `/pred` (hourly model feature vectors + forecasts, joined on the UTC
issue-hour), `/events` (diagnostics). All timestamps are **UTC with a trailing `Z`**.

The `/raw` telemetry row (sensors + rule-based outputs + device state):

```
timestamp,lat,lon,alt,temp,humidity,pressure_raw,pressure_adj,battery,storm_conf,rain_conf,storm_active,rain_active,pressure_rate,activity,state,modifier,banner,gps_ms,free_heap
2026-05-25T14:32:42Z,-41.2865,172.1043,847,12.3,65,980.2,978.1,64,58,42,0,0,-1.2,R,X,N,R,3240,198432
```

`pressure_adj` is altitude-adjusted to sea-level equivalent (hypsometric formula). Full field
reference + the `/inputs`/`/pred` schemas: [`CLAUDE.md`](CLAUDE.md) and `pod/docs/architecture.md`.

---

## Repo Structure

```
/pod    — Pod firmware (C++ Arduino + PlatformIO)
/deck   — Cyberdeck code (Python 3.8+)
/docs   — Shared documentation
```
