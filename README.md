# Hiking Pod System

A two-component hiking data logger for NZ backcountry and coastal hiking.

## Components

| Component | Hardware | Role |
|---|---|---|
| **Pod** | RP2350-Zero | Data logger, e-ink display, GPS/weather sensors, buzzer alerts |
| **Cyberdeck** | CM5, Python | Receives pod logs, analyses weather and activity, displays summaries |

Pod and cyberdeck communicate over UART at 115200 baud via a GX16-5 connector.

---

## Hardware (Pod)

- **MCU:** RP2350-Zero (Cortex-M33, hardware FPU, 2MB flash)
- **Display:** Waveshare 1.54" 4-colour e-ink (200×200px, Black/White/Yellow/Red)
- **GPS:** NEO-M8N (UART, software sleep via UBX commands)
- **Weather:** BME280 (I2C, forced mode — temp/humidity/pressure)
- **RTC:** DS3231 (I2C, wake alarm source)
- **Buzzer:** GP14 (PWM)
- **Flash:** LittleFS on 2MB onboard flash (~14KB/day at 5-min log intervals)

---

## Wake Cycle

The pod spends most of its time in DORMANT mode. The RTC triggers a wake every minute.

```
every 1 minute:
  check GX16 pin
    if connected and not showing Connected → update display, sleep

  wake GPS (UBX command)
  get fix (timeout 8s)
  altitude-adjust cached pressure → store both in memory

  run activity detection
  if state or banner changed → refresh display

  sleep GPS, MCU → DORMANT

  if this is the 5th cycle (every 5 minutes):
    read BME280 (temp, humidity, pressure)
    run weather algorithm
    write log entry to flash
```

**Estimated average draw:** ~13mA → 8+ days on 2600mAh 18650.

---

## Activity Detection

Runs every minute from the GPS circular buffer (last 30 entries = 30 minutes).

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

Modifier state is cached from the last 5-minute BME280 read.

---

## Weather Prediction

Runs every 5 minutes from the 24-hour pressure history buffer (288 entries).

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

Estimated arrival is recalculated every 5 minutes from current pressure rate:

```
< 6 hours   → "STORM ~2 HRS"    + "CONFIDENCE 73%"
6–12 hours  → "STORM TODAY"     + "CONFIDENCE 58%"
> 12 hours  → "STORM LIKELY"    + "CONFIDENCE 51%"
overdue     → "STORM ARRIVING"  + "CONFIDENCE 81%"
```

Same pattern for rain with Yellow banner.

### Buzzer

Chirps on new alert. Suppressed between 22:00–07:00 unless storm confidence ≥85% (severe override).

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

Pipe-delimited CSV, written to LittleFS every 5 minutes:

```
timestamp|lat,lon|alt|temp|humidity|pressure_raw|pressure_adj|battery
2026-05-25T14:32:42|-41.2865,172.1043|847|12.3|65|980.2|978.1|64
```

`pressure_adj` is altitude-adjusted to sea-level equivalent (hypsometric formula).

---

## Repo Structure

```
/pod    — Pod firmware (C++ Arduino + PlatformIO)
/deck   — Cyberdeck code (Python 3.8+)
/docs   — Shared documentation
```
