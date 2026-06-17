# Pod — Plans

## ✅ Completed: Main Loop Wiring

main.cpp implements the full 1-min / 5-min wake cycle. All sensors integrated, GPS→RTC sync on first fix, EventLog for failures, CSV logging to LittleFS. Display calls stubbed until 1.54" replacement arrives.

## ✅ Completed: Algorithm Integration

Full pipeline wired: SensorData → ActivityDetector → NijntjeEvaluator → NijntjeDisplay → LogFormatter → CSV.
LogFormatter extracted for native testability. 14 pipeline tests added in test_log.

## ✅ Completed: Map Tile Generator — GeoPackage rewrite (2026-06-16)

`pod/tools/map_tile_gen.py` was rewritten to pull features from **local LINZ GeoPackage files**
on the VM (`~/linz-data/`) using fiona + shapely, rendering into an arbitrary 200×200 2bpp buffer
centred on any GPS coordinate (no WebMercator grid lock).

**What changed:**
- Input: fiona spatial query (bounding-box clip) over `*.gpkg` per layer, instead of HTTP MVT fetch
- Projection: linear WGS84 → pixel (equirectangular; accurate to ~0.5% at NZ latitudes)
- Polygon clip: shapely clips large polygons (coastline, lakes) to tile bbox before PIL fill
- Rendering: same PIL draw calls in the 4-colour 2bpp palette
- Output format unchanged: `tile_RR_CC.bin` (200×200 2bpp, row-major MSB-first) + `meta.json`
- `--inspect` shows per-layer feature counts + field names for a tile area
- `--demo` mode still works (no GeoPackage data needed)

**Tested on VM:** Tongariro area 3×3 grid rendered in 9 tiles, all correct. Binary output 10,000 bytes
each. Volcano contours, river casings, DOC track, peaks all visible.

**Multi-zoom strategy (decided, not yet generated):**
Four tile sets — 2km regular, 2km half-cell-offset, 4km regular, 4km half-cell-offset.
2km: all contours 40m flat, streams + major rivers.
4km: 40m flat contours, major rivers only.
Styling still being iterated — full-NZ generation (~168,000 tiles, ~1.6 GB, 2–4 days VM render)
will be kicked off once styling is finalised. See `pod/docs/map-tiles.md`.

## GPS Fix Test

Run `pio test -e esp32` outdoors to pass `test_gps_acquires_fix`. This also validates RTC seeding from GPS.

## Display Work (blocked — 1.54" fried)

- Wire NijntjeRenderer to 1.54" display once replacement arrives
- Implement all 17 sprite render paths
- Test all Nijntje states on hardware

## RP2350 Migration

When moving from ESP32 dev to RP2350-Zero:
- Revert GPS TX from GPIO14 → GP12 in config.h
- Switch `Wire` → `Wire1` (already handled by `#ifdef ARDUINO_ARCH_RP2040` in all readers)
- Test DORMANT sleep + RTC alarm wake
- Confirm LittleFS on RP2350 flash
- Run full embedded test suite on RP2350

## ✅ Completed: Celestial Calculations

Sunrise/sunset computed via USNO algorithm (`MathUtils::sunriseSunsetMinutes`). Cached once per day in `main.cpp` (refreshed at first wake ≥03:00 local, boot bootstrap). NZ-local time via DST-aware `MathUtils::nzUtcOffsetMinutes`. Falls back to fixed 20:00–06:00 window when GPS/clock unavailable. WalkingNight, SleepyEvening, SleepingTent, and Resting states all use the sun times.

## Decided — hardware & data direction

**Hardware (2026-06-13/14)**
- **MCU: RP2350-Zero.** WiFi evaluated and **deferred** (would force an ESP32-class board) — later "sync convenience" discussion. For now, no radio.
- **Single display: 1.54" 4-colour only.** 2.13" B/W is **out for now** (can be re-added later) — frees GP1/6/7/8.
- **microSD: in.** Holds CSV logs **and the model file(s)**.

**Cadence & time (2026-06-14)**
- **Single 10-min wake**, UTC phase-aligned (`:00/:10/…`); drops the old 1-min/5-min split. Connection-detect → **pin interrupt**, not polled.
- **Hourly predictions** on UTC-hour boundaries, horizons hourly; GPM (native 30-min) aggregated to hourly for labels. 10 min tiles both grids (3/6 samples).
- **UTC logging + `Z` suffix** — ✅ done (`LogFormatter` + test). Display stays NZ-local.
- **Track resolution = 10-min** (≈650 m while walking) accepted for now; revisit a finer GPS-only cadence if post-hike maps look blocky.

**Filesystem & model safety (2026-06-14)** — see architecture.md → Storage / Model Inference
- SD daily CSVs: `/raw` (10-min), `/inputs` + `/pred` (hourly, joined on UTC issue-hour), `/events`; `/model` + `manifest.json`. Critical state on LittleFS. Graceful degradation if SD missing.
- **Model = data file on SD, copied manually from the laptop** (no OTA). Executed by a **streaming tree evaluator** (peak RAM ~one tree; full ensemble feasible this way; read all trees, no early-stop).
- **Schema-hash gate, fail-safe:** manifest carries feature schema + hash; on mismatch the pod refuses the model, falls back to the rule-based algorithm, and logs a critical event (full schema → names the offending feature).

## ✅ Completed: Firmware refactor (2026-06-16)

1. **Cadence refactor** ✅ — `main.cpp` now runs a single 10-min wake loop. DORMANT sleep is still `delay()` on both arches (TODO: RP2350-specific DORMANT + DS3231 alarm wiring).
2. **Filesystem layer** ✅ — `storage/SdLogger.cpp` writes daily UTC CSVs to `/raw`, `/inputs`, `/pred`, `/events`. Missing SD degrades gracefully. SD card scaffold at `pod/sd_card/` (copy to SD root).
3. **Model evaluator** ✅ — `model/ModelEvaluator.cpp` streams trees one at a time (peak RAM ~1 tree). `model/ModelManifest.cpp` parses `manifest.json` + validates FNV-1a schema hash. Offline exporter at `pod-ml/scripts/export_model.py`. 20 native tests added.
4. **Pin map finalisation** ✅ — `docs/hardware.md` + `config.h` (arch-split RP2350/ESP32).
5. **BME280 reader** ✅ — `sensors/Bme280Reader.cpp` replaces BMP180+AHT10. `lib_deps` updated to Adafruit BME280.

## Pending

1. **RP2350 DORMANT sleep** — configure DS3231 SQW alarm for next 10-min UTC boundary, power-down GPS, then enter `rp2040.dormant()`. Wake on PIN_RTC_SQW interrupt. Currently uses `delay()` on both arches.
2. **Activity-detection re-tune** — re-derive `CLIMBING_MIN_ENTRIES`/`WALKING_MIN_ENTRIES` for 10-min spacing (buffer entries now represent 10-min cycles, not 1-min). See architecture.md → RAM Buffers.
3. **Battery ADC** — wire `sensor.batteryPct` to RP2350 GP29 ADC. Currently returns 0.
4. **MODEL_SCHEMA_HASH** — update the placeholder `0x0000000000000000ULL` in `model/ModelFormat.h` after the first real export from `export_model.py`. Value is printed by the exporter.
5. **Dead code removal** — `CompassReader`, `AccelReader`, `Bmp180Reader`, `Aht10Reader`, `UartSync`, `BuzzerController` (except for native tests), `BWFramebuffer`, `BWRenderer` are all dead. Remove once tests referencing BuzzerController are migrated or dropped.

## Future / Deferred

- AS3935 lightning detector (provisional — not yet confirmed)
- WiFi-at-home log sync (→ would require an ESP32-class board; see "Decided" above)
- Tide table integration

> **Dropped 2026-06-13** (was previously listed here): on-demand compass on the 2.13" display, accelerometer pack-away/tap mode, and the cyberdeck UART protocol — compass, accelerometer, and the UART link are all out of the design. The tilt-comp math + `CompassReader`/`AccelReader` code remain in-tree as dead code pending removal.
