# Pod — Current Status

Last updated: 2026-06-16. Developing and testing on ESP32 dev board; target is RP2350-Zero.

## Sensor Readers

| Sensor | File | Status | Notes |
|--------|------|--------|-------|
| DS3231 RTC | sensors/RtcReader.cpp | ✅ Working | GPS→RTC sync wired in main.cpp |
| GPS M8N | GpsReader.cpp | ✅ Working | RMC parsing for UTC time. Fix test requires outdoors |
| BME280 (P+T+H) | sensors/Bme280Reader.cpp | ✅ Written | I²C 0x76, replaces BMP180+AHT10. Adafruit BME280 library |
| ~~BMP180~~ | sensors/Bmp180Reader.cpp | 🗑️ Dead code | Superseded by BME280 — keep for now, pending removal |
| ~~AHT10~~ | sensors/Aht10Reader.cpp | 🗑️ Dead code | Superseded by BME280 — keep for now, pending removal |
| ~~HMC5883L Compass~~ | ~~sensors/CompassReader.cpp~~ | 🗑️ Dropped 2026-06-13 | Dead code pending removal |
| ~~MPU6050 Accel~~ | ~~sensors/AccelReader.cpp~~ | 🗑️ Dropped 2026-06-13 | Dead code pending removal |
| microSD | storage/SdLogger.cpp | ✅ Written | SPI bus; daily UTC CSVs in /raw /inputs /pred /events |

## Algorithms

| Module | File | Status |
|--------|------|--------|
| MathUtils | algorithms/MathUtils.cpp | ✅ Implemented + tested |
| WeatherAlgorithm | algorithms/WeatherAlgorithm.cpp | ✅ Implemented + tested |
| ActivityDetector | algorithms/ActivityDetector.cpp | ✅ Implemented + tested |
| GpsBuffer | sensors/GpsBuffer.cpp | ✅ Implemented + tested |
| WeatherBuffer | sensors/WeatherBuffer.cpp | ✅ Implemented + tested |
| NijntjeEvaluator | — | ✅ Implemented + tested |

## Model Inference

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| Binary format spec | model/ModelFormat.h | ✅ Done | MODEL_SCHEMA_HASH = 0 (placeholder) — update after first export |
| Manifest parser | model/ModelManifest.cpp | ✅ Done | FNV-1a schema hash; hand-rolled JSON parser |
| Streaming evaluator | model/ModelEvaluator.cpp | ✅ Done | One tree at a time, peak RAM ~1 tree; schema-hash gate |
| Offline exporter | pod-ml/scripts/export_model.py | ✅ Done | LightGBM → model.bin + manifest.json |
| SD card scaffold | pod/sd_card/ | ✅ Done | Copy to SD root; raw/ inputs/ pred/ events/ model/ maps/ |

**To deploy the model:**
1. Train with pod-ml; save model as `.pkl`
2. `python pod-ml/scripts/export_model.py --model ... --features ... --output-names ... --out pod/sd_card/model/`
3. Update `MODEL_SCHEMA_HASH` in `model/ModelFormat.h` (printed by exporter)
4. Copy `pod/sd_card/model/` to SD card

## Infrastructure

| Component | File | Status |
|-----------|------|--------|
| EventLog | EventLog.cpp | ✅ Implemented |
| SD CSV logger | storage/SdLogger.cpp | ✅ Written (embedded via SD.h; native stub) |
| Main wake cycle | main.cpp | ✅ Refactored — single 10-min UTC-aligned wake |
| Hourly model run | main.cpp `runHourlyModel()` | ✅ Wired — fires when UTC hour changes |
| GPS→RTC sync | main.cpp | ✅ Implemented (first valid fix + drift correction) |
| Display calls | main.cpp | ⚠️ Stubbed (TODO comment) — 1.54" fried |
| Battery ADC | main.cpp | ⚠️ Returns 0 — needs RP2350 GP29 wiring |
| RP2350 DORMANT sleep | main.cpp | ⚠️ TODO — currently delay() on both arches |

## Display

| Component | File | Status |
|-----------|------|--------|
| NativeFramebuffer | display/NativeFramebuffer.cpp | ✅ Working |
| NijntjeRenderer | nijntje/NijntjeRenderer.cpp | ✅ Working |
| NijntjeSpriteRegistry | nijntje/NijntjeSpriteRegistry.cpp | ✅ All 17 sprites mapped |
| 1.54" 4-colour e-ink | display/EPD1in54G.h | ⚠️ BLOCKED — display fried, replacement ordered |

## Tests

| Suite | Command | Status |
|-------|---------|--------|
| Native (PC) | `pio test -e native` | **215 passing** (math, algorithms, log, nijntje, display, model, storage) |
| Embedded (ESP32) | `pio test -e esp32` | Hardware-gated: GPS fix skips indoors |

## Known Hardware Facts

- **Sensor:** BME280 (P+T+H) at I²C 0x76. Verify 0x76 vs 0x77 on first bring-up.
- **GPS TX pin:** GPIO14 on ESP32 bench (GPIO12 on RP2350) — arch-split in config.h.
- **RTC:** DS3231 + CR2032 coin cell. Must disable trickle charger (CR2032 not rechargeable).
- **1.54" display:** FRIED — replacement on order. All display work blocked.
- **I2C bus:** SDA=GPIO26, SCL=GPIO27 (config.h). Confirmed working.
- **SD card:** MISO=GP4, MOSI=GP3, SCK=GP2, CS=GP1 (RP2350). Not wired on ESP32 bench.

## Map Tile Tools

| Tool | Location | Status |
|------|----------|--------|
| `map_tile_gen.py` | `pod/tools/map_tile_gen.py` | ✅ GeoPackage rewrite done (2026-06-16) |
| LINZ download infra | `pod-ml/scripts/linz/` | ✅ All 8 layers on VM, daily cron |

See `pod/docs/map-tiles.md` for the full pipeline and SD card layout.

## What's Blocked

- Display integration in main loop (1.54" fried — replacement on order)

## What's Next

See [plans.md](plans.md).
