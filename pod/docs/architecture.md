# Pod Architecture

## Hardware

| Component | Part | Interface | Address/Pin |
|-----------|------|-----------|-------------|
| MCU | RP2350-Zero (Cortex-M33, 2MB flash) | — | — |
| Display (main) | Waveshare 2.13" e-ink V2, SSD1680, 250×122px B/W | SPI | CS=GP1 |
| Display (Nijntje) | Waveshare 1.54" 4-colour e-ink | SPI | CS=GP10 |
| GPS | GY-GPS6MV2 M8N | UART0, 9600 baud | TX=GP12, RX=GP13 |
| Pressure | BMP180 (Jaycar XC3702 — sold as BMP280, confirmed BMP180) | I2C | 0x77 |
| Temp/Humidity | AHT10 | I2C | 0x38 |
| Compass | HMC5883L (Jaycar XC4496 — confirmed, not QMC5883L) | I2C | 0x1E |
| Accelerometer | MPU6050 (AD0 → 3.3V) | I2C | 0x69 (⚠️ assumes AD0 high; module default is 0x68) |
| RTC | DS3231 (Jaycar XC9044, RPi form factor) | I2C | 0x68 |
| Buzzer | — | PWM | GP14 |
| Battery | 18650 2600mAh + TP4056 USB-C charger | ADC | GP29 |
| GX16-5 | Data + 5V to cyberdeck | UART1 | TX=GP4, RX=GP5 |

Note: BME280 probe referenced in older docs is replaced by BMP180 + AHT10 + HMC5883L.

## Pin Assignments (RP2350-Zero)

| Pin | Function |
|-----|----------|
| GP0 | 1.54" e-ink BUSY |
| GP1 | 2.13" e-ink CS |
| GP2 | SPI SCK (shared both displays) |
| GP3 | SPI MOSI (shared both displays) |
| GP4 | UART1 TX (cyberdeck) |
| GP5 | UART1 RX (cyberdeck) |
| GP6 | 2.13" e-ink DC |
| GP7 | 2.13" e-ink RST |
| GP8 | 2.13" e-ink BUSY |
| GP9 | GX16 connection detect |
| GP10 | 1.54" e-ink CS |
| GP11 | 1.54" e-ink DC |
| GP12 | UART0 TX (GPS) |
| GP13 | UART0 RX (GPS) |
| GP14 | Buzzer (PWM) |
| GP15 | 1.54" e-ink RST |
| GP16 | Compass DRDY |
| GP17 | RTC SQW (alarm interrupt) |
| GP26 | I2C1 SDA |
| GP27 | I2C1 SCL |
| GP28 | Rotary position switch (ADC) |
| GP29 | Battery voltage (ADC) |

**ESP32 dev note:** GPS TX moved to GPIO14 (GPIO12 is a strapping pin on ESP32). Fix when migrating to RP2350.

## I2C Bus

All sensors share I2C1 (SDA=GP26, SCL=GP27). Addresses: DS3231=0x68, BMP180=0x77, AHT10=0x38, HMC5883L=0x1E, MPU6050=0x69.

## Wake Cycle

MCU wakes every 1 minute via RTC alarm (DS3231 SQW → GP17).

**Every 1-min cycle:**
1. Check GX16 pin (GP9) — if cyberdeck connected, update display → sleep
2. Wake GPS, get fix (8s timeout), read NMEA + RMC
3. If first valid GPS fix: seed RTC from GPS UTC time
4. Altitude-adjust cached pressure → store raw + adjusted
5. Run activity detection → NijntjeState
6. Update buffers, check component health
7. If state/banner changed → refresh display
8. Sleep GPS, MCU → DORMANT

**Every 5th cycle (5 min), additionally:**
- Read BMP180 (pressure), AHT10 (temp, humidity)
- Run weather algorithm → update rain + storm predictions
- Write CSV log entry to LittleFS
- Persist WeatherPrediction structs to flash

## RAM Buffers (survive DORMANT sleep)

| Buffer | Struct | Entries | Size |
|--------|--------|---------|------|
| GPS history | GpsEntry {lat,lon,alt,timestamp} | 15 (15 min) | 240 bytes |
| Weather history | WeatherEntry {timestamp,pressureAdj,tempC,humidity,lat,lon} | 288 (24 hrs) | 6.9KB |
| WeatherPrediction × 2 | rain + storm | — | ~40 bytes |
| **Total** | | | **~7.2KB** |

## Flash Storage (LittleFS, 2MB)

- `data.csv` — sensor + algorithm log, ~100 bytes/entry, ~29KB/day
- `events.log` — diagnostic log (sensor failures, brownouts, RTC fallbacks). Max 100KB. Compacts by dropping W entries when full; seals with LOG_FULL if still full after compaction.
- `predictions.bin` — persisted WeatherPrediction structs (survive power cycles)
- Tide tables baked into firmware (~110–150KB)

## Component Fallbacks

| Component | Failure behaviour |
|-----------|------------------|
| GPS | Positions = 0, activity falls back to stationary, RTC provides timestamp |
| RTC | Timestamp priority: GPS unixTime → millis() → 0 |
| Compass | Log error; accel is **not** initialised either — they're separate chips, but the accel is only useful for compass tilt comp, so it's skipped when the compass is absent |
| Accelerometer alone | Log warning; compass falls back to flat (non-tilt-compensated) heading |
| BMP180 / AHT10 | No fallback — weather algorithm degrades silently |

## Display Stack

**1.54" 4-colour (Nijntje display):**
```
NijntjeEvaluator  →  NijntjeDisplay struct
NijntjeRenderer   →  IFramebuffer (abstract)
    [hardware]  Framebuffer : Adafruit_GFX  →  EPD1in54G  →  IDisplayHAL  →  SPI
    [native]    NativeFramebuffer (pure C++)  →  SDL2Display  →  SDL3 window
NijntjeSpriteRegistry  →  lookupSprite(state, modifier)  →  17 2bpp XBM headers in src/sprites/
```

**2.13" B/W (stats display):** not yet implemented; deferred.

**Native display simulator** (`[env:native_display]`): calls `NijntjeEvaluator::evaluate()` with test scenarios, renders via SDL3 window. SDL3 dev package lives in `vendor/` (gitignored). See [commands.md](commands.md).

Refresh: partial (0.3s) on rotary input; full (2s) every 60s or after 5 partials.

## Weather Algorithm

`storm = pressure_rate×0.50 + zambretti×0.25 + humidity_trend×0.20 + temp_drop×0.05`
`rain  = pressure_rate×0.45 + zambretti×0.30 + humidity_trend×0.20 + temp_drop×0.05`

HMC5883L provides navigation heading only — it is NOT a weather input. The Zambretti term uses pressure tendency + level (see CLAUDE.md).
Trigger: storm≥65%, rain≥55%. Clear: pressure recovered ≥50% AND confidence drops below 30%/25%.

## Activity Detection

Priority: Climbing → Walking/WalkingNight → SleepingTent → SleepyEvening → Resting.
Stationary = all GPS buffer entries within 25m of newest fix.
Modifiers (Walking/Climbing/Resting only): Foggy > Cold > Hot > None.

## Compass Heading

HMC5883L magnetometer, navigation only (never a weather input). Two read paths in `CompassReader`, both producing **0° = magnetic north, increasing clockwise**:

- `read()` — flat 2D heading, `atan2(y, x)`. Uses X/Y only.
- `readTilted(accel)` — tilt-compensated using MPU6050 gravity vector (`MathUtils::tiltCompensatedHeading`, Honeywell AN-203 projection), `atan2(By, Bx)`. Reduces to the flat formula when level, so the two paths agree at every cardinal (guarded by `test_tilt_comp_matches_flat_read_convention`).

**Axis convention** (board flat, **+Z up**):
- **X, Y** lie in the board plane → the heading components. Heading = the bearing the module's **+X** axis points at; **+Y** is 90° CCW from +X.
- **Z** is perpendicular to the board (vertical) → only used for tilt comp. On a flat board Z carries NZ's steep magnetic dip (large reading), X/Y carry the small horizontal field.
- Mounting hazards: **+Z down** (module upside-down) reverses the rotation sense; **X/Y swapped or negated** gives a constant offset / E–W swap. For tilt comp the MPU6050 axes must be physically aligned with the magnetometer's (same X/Y/Z, +Z up, `az≈+1g` level).

**Hard-iron / declination:** raw axes have `COMPASS_HARD_IRON_OFFSET_*` (config, currently 0) subtracted before the heading. No magnetic **declination** is applied yet, so the heading is magnetic north — ~+23° off true north in NZ. Byte reads from the sensor are sequenced explicitly (the operands of `|` are unsequenced in C++, so `read()<<8 | read()` could swap MSB/LSB).

Display: `BWRenderer::compassIndex()` maps the heading to one of 16 pre-baked frames (22.5° buckets, wraps at 360°) for the 2.13" B/W panel.

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
