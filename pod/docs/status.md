# Pod — Current Status

Last updated: 2026-06-01. Currently developing and testing on ESP32 dev board.

## Sensor Readers

| Sensor | File | Status | Notes |
|--------|------|--------|-------|
| DS3231 RTC | sensors/RtcReader.cpp | ✅ Working | GPS→RTC sync designed, not yet in main loop |
| GPS M8N | GpsReader.cpp | ✅ Working | RMC parsing for UTC time. Fix test requires outdoors |
| HMC5883L Compass | sensors/CompassReader.cpp | ✅ Working | Confirmed HMC5883L, not QMC5883L. Flat `read()` + tilt-compensated `readTilted()` both implemented; both use `atan2(y,x)`, 0°=N clockwise (see architecture.md → Compass heading). Magnetic north only — **declination not yet applied** (~+23° in NZ). Hard-iron offsets in config = 0 (uncalibrated). Target display: 2.13" B/W (partial refresh), button-triggered |
| MPU6050 Accel | sensors/AccelReader.cpp | ❌ Blocked: unsoldered headers | **2026-06-01:** I2C scan shows 0x1E/0x38/0x68/0x77 but **no 0x69** (AD0 *is* wired to 3.3V). Root cause is mechanical: the MPU6050 breakout's header pins aren't soldered and the bare male jumpers don't seat tightly in its holes, so it doesn't make reliable bus contact. Firmware/address (0x69) are correct — **solder headers and re-test**. Compass tilt comp blocked until accel ACKs; flat heading works fine |
| BMP180 Pressure | sensors/Bmp180Reader.cpp | ✅ Working | Adafruit BMP085 library. Confirmed BMP180 (sold as BMP280) |
| AHT10 Temp/Humidity | sensors/Aht10Reader.cpp | ✅ Working | Raw I2C. If it fails, weather record stores temp/humidity as NaN (trends skip it) so pressure prediction survives |

## Algorithms

| Module | File | Status |
|--------|------|--------|
| MathUtils | algorithms/MathUtils.cpp | ✅ Implemented + tested |
| WeatherAlgorithm | algorithms/WeatherAlgorithm.cpp | ✅ Implemented + tested |
| ActivityDetector | algorithms/ActivityDetector.cpp | ✅ Implemented + tested |
| GpsBuffer | sensors/GpsBuffer.cpp | ✅ Implemented + tested |
| WeatherBuffer | sensors/WeatherBuffer.cpp | ✅ Implemented + tested |
| NijntjeEvaluator | — | ✅ Implemented + tested |

## Infrastructure

| Component | File | Status |
|-----------|------|--------|
| EventLog | EventLog.cpp | ✅ Implemented, integrated in main loop |
| LittleFS CSV log writer | main.cpp `writeLogEntry()` | ✅ Implemented |
| Main wake cycle loop | main.cpp | ✅ Implemented (1-min + 5-min cycles) |
| GPS→RTC sync | main.cpp | ✅ Implemented (first valid fix per boot) |
| Component fallback logic | main.cpp setup() | ✅ Implemented |
| Display calls | main.cpp | ⚠️ Stubbed (TODO comment) — 1.54" fried |
| Battery ADC | main.cpp | ⚠️ Returns 0 — needs RP2350 GP29 wiring |

## Display Simulator

| Component | File | Status |
|-----------|------|--------|
| IFramebuffer | display/IFramebuffer.h | ✅ Abstract interface (decouples renderer from Adafruit_GFX) |
| NativeFramebuffer | display/NativeFramebuffer.cpp | ✅ Pure-C++ 2bpp framebuffer, no Arduino deps |
| SDL2Display | display/SDL2Display.cpp | ✅ SDL3-backed window, decodes 2bpp → RGBA |
| NijntjeRenderer | nijntje/NijntjeRenderer.cpp | ✅ Renders sprites + banner via IFramebuffer |
| NijntjeSpriteRegistry | nijntje/NijntjeSpriteRegistry.cpp | ✅ Implemented — all 17 sprites mapped |
| native_display env | platformio.ini | ✅ Working — calls NijntjeEvaluator for real logic |
| esp32_stream env | test/test_display_stream/main_stream.cpp | ✅ Working — streams CSV from live sensors every 15s |

Requires SDL3 in `vendor/SDL3-x.x.x/`. See [commands.md](commands.md).

## Tests

| Suite | Command | Result |
|-------|---------|--------|
| Native (PC) | `pio test -e native` | 182 passing (56 math, 90 algorithms, 14 log, 17 nijntje, 5 display). Includes tilt-comp ↔ flat-read consistency guard (test_math) and compassIndex bucket map (test_display) |
| Embedded (ESP32) | `pio test -e esp32` | hardware-gated: GPS fix skips indoors; MPU6050/accel tests skip until soldered |

## Known Hardware Facts

- **Compass:** HMC5883L at 0x1E (NOT QMC5883L at 0x0D as originally suspected)
- **Pressure sensor:** BMP180 at 0x77 (Jaycar XC3702 sold as BMP280 but chip is BMP180)
- **GPS TX pin:** Changed to GPIO14 for ESP32 dev (GPIO12 is strapping pin on ESP32). **Must revert to GP12 for RP2350.**
- **RTC coin cell:** Must be installed — RTC loses time on power loss without it
- **1.54" display:** FRIED — replacement on order. All display work blocked until replacement arrives.
- **I2C bus:** SDA=GPIO26, SCL=GPIO27 (config.h). Confirmed working.

## What's Blocked

- Display integration in main loop (1.54" fried — replacement on order)
- Display tests against hardware

## What's Next

See [plans.md](plans.md).
