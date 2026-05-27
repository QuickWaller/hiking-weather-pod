# Pod Firmware — Context

## Language & Toolchain
C++ with Arduino framework via PlatformIO. Not C#.

## Hardware
- **MCU:** RP2350-Zero (Cortex-M33, hardware FPU, 2MB onboard flash)
- **Display:** Waveshare 2.13" e-ink V2, SSD1680 controller, 250×122px, black/white
- **GPS:** GY-GPS6MV2 M8N (UART0, 9600 baud)
- **Sensors:** BME280 I2C (temp/humidity/pressure), DS3231 I2C (RTC)
- **Power:** 18650 2600mAh + TP4056 USB-C charger + Waveshare UPS HAT E
- **Enclosure:** AD/ATD-171390 junction box (165×117×84mm internal, IP67)
- **Connectors:** GX16-5 (data+5V to cyberdeck), IP67 USB-C bulkhead, SMA bulkhead (GPS antenna), Gore-Tex vent (pressure equalisation on alpine routes)
- **Perfboard:** Two 30×70mm boards stacked on nylon M2 standoffs
  - Board 1 (top): RP2350, e-ink, GX16
  - Board 2 (bottom): TP4056, GPS, DS3231, BME280 probe

## Pin Assignments
| Pin | Function |
|-----|----------|
| GP1 | 2.13" e-ink CS |
| GP2 | SPI SCK (shared — both displays) |
| GP3 | SPI MOSI (shared — both displays) |
| GP6 | 2.13" e-ink DC |
| GP7 | 2.13" e-ink RST |
| GP8 | 2.13" e-ink BUSY |
| GP10 | 1.54" e-ink CS |
| GP11 | 1.54" e-ink DC |
| GP15 | 1.54" e-ink RST |
| GP0 | 1.54" e-ink BUSY |
| GP4 | UART1 TX (cyberdeck) |
| GP5 | UART1 RX (cyberdeck) |
| GP12 | UART0 TX (GPS) |
| GP13 | UART0 RX (GPS) |
| GP14 | Buzzer (PWM) |
| GP9 | GX16 connection detect |
| GP26 | I2C1 SDA (BME280, DS3231) |
| GP27 | I2C1 SCL (BME280, DS3231) |
| GP28 | Rotary position switch (ADC, voltage divider) |
| GP29 | Spare (ADC) |

Both displays share the SPI bus (GP2/GP3). Each has its own CS, DC, RST, BUSY.

## Additional Sensors (Provisional)
- **AS3935** (lightning detector, I2C): detects RF from lightning up to 40km. Works inside plastic enclosure — no external mounting needed. Not yet confirmed.

BME280 is in an external waterproof probe, not inside the enclosure. Humidity readings are valid.

## Power Design
- **Battery:** 18650 2600mAh connected directly to RP2350-Zero VSYS (3.0–4.2V, within 1.8–5.5V input range)
- **Charging:** TP4056 USB-C module — charges 18650 via IP67 USB-C bulkhead
- **Battery monitoring:** voltage divider on VSYS → GP29 (ADC), reported as % estimate in logs
- No UPS HAT — TP4056 + direct VSYS connection is sufficient
- GPS duty-cycled: on ~5s per minute for hot start fix (~4mA average vs 45mA continuous)
  - GPS VBAT pin always connected (maintains almanac/time at microamps)
  - GPS main power switched via GPIO-controlled transistor/MOSFET
- BME280: forced mode — read then sleep immediately
- RP2350: DORMANT/sleep between readings, wake on RTC alarm
- Estimated average draw: ~13mA → 8+ days on 2600mAh (target was 5 days)
- Pack-away mode: deferred — no accelerometer on board

## Flash Storage
LittleFS on RP2350 onboard 2MB flash. No SD card. Log entries ~100 bytes each, ~29KB/day at 5-min intervals. Tide tables ~110-150KB baked into firmware. Plenty of headroom.

See root CLAUDE.md for full log format — includes sensor data, algorithm outputs (confidence, active state, pressure rate), display state (activity/state/modifier/banner), and MCU diagnostics (gps_ms, free_heap).

## Display Graphics Stack
1. GxEPD2 library (SSD1680 driver)
2. Adafruit GFX (primitives: lines, rects, text, bitmaps)
3. EInkDisplay.cpp (screen state, render functions, refresh logic)

Refresh strategy:
- Partial refresh (0.3s) on rotary dial input
- Full refresh (2s) every 60s auto-rotate, or after every 5 partial refreshes
- Long-term damage not a concern at these rates

## Testing Strategy

Both test suites must be implemented.

**test_native (runs on PC, no hardware needed):**
```
test/test_native/
  test_math.cpp        — haversine, dew point, pressure adjustment, Magnus formula
  test_algorithms.cpp  — Zambretti, rest detection, lapse rate, linear regression
  test_nijntje.cpp     — state priority logic, all 11 states, edge cases
  test_parser.cpp      — log format parsing and validation
```
Uses PlatformIO native environment. Pure functions only — no hardware calls.

**test_embedded (runs on actual RP2350, hardware required):**
```
test/test_embedded/
  test_sensors.cpp  — BME280/GPS/DS3231 sanity checks, reasonable value ranges
  test_display.cpp  — each screen layout renders without crash, partial + full refresh
```
Display tests must cover: Main screen, Section 1 (Celestial/Tidal), Section 2 (Weather), Section 3 (Activity). Also test all Nijntje states render correctly.

PlatformIO captures results via serial. Device must be connected.

## C++ Header/Implementation Conventions
- `#pragma once` on every header file
- Headers declare only — no implementations in .h files (except templates/inline)
- Implementations in .cpp files only
- Forward declarations preferred over #include in headers — include in .cpp instead
- Each .cpp includes its own .h and only what it directly needs
- No circular includes — dependencies flow one way
- `config.h` is the universal include (macros/constants used everywhere)
- Class member variables are private, exposed via methods
- `extern` for shared global state — declare in .h, define in one .cpp
