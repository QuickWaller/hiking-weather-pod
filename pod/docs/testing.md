# Pod — Testing

## Test Suites

### Native (PC, no hardware)
```
test/test_math/         — MathUtils: haversine, dew point, pressure adj, regression, speed, edge guards,
                          sun times, tilt-compensated heading (incl. flat-read consistency guard)
test/test_algorithms/   — WeatherAlgorithm, ActivityDetector, GpsBuffer, WeatherBuffer, integration lifecycle
test/test_nijntje/      — NijntjeEvaluator: state priority, modifiers, banners
test/test_log/          — LogFormatter + full sensor→activity→display→CSV pipeline
test/test_display/      — BWRenderer::compassIndex heading→frame bucket map (16 buckets, 360° wrap)
```
Pure C++ — no Arduino, no Wire, no hardware dependencies. (CompassReader/AccelReader pull in `Wire.h`,
so they are covered by the embedded suite, not native — their heading math lives in MathUtils and is tested there.)

### Embedded (ESP32/RP2350, hardware required)
```
test/test_embedded/test_sensors.cpp
```
Covers:
- I2C scan (verifies all expected devices are on bus; skips device tests if absent)
- GPS: NMEA streaming, no-fix state, outdoor fix acquisition + RTC seeding
- RTC: date/time range, unix plausibility, ticks
- Compass: begin, heading 0–360, raw axes non-zero
- Accelerometer: begin, magnitude ~1g at rest, gyro near zero
- BMP180: begin, pressure 863–1163 hPa, temperature plausible
- AHT10: begin, humidity 0–100%, temperature plausible

## Rules

- After any code confirmed working: write tests before moving on
- Native tests for pure logic (algorithms, math, state machines)
- Embedded tests for hardware I/O and sensor sanity
- If a device isn't on the I2C bus, its tests auto-skip (not fail)
- `test_gps_acquires_fix` auto-ignores indoors — run outdoors for full pass

## Display Simulator

Not a test suite — a visual tool. Builds with `[env:native_display]` and opens an SDL3 window showing the Nijntje display. Calls `NijntjeEvaluator::evaluate()` for real, so modifier/banner logic is exercised.

**Prerequisite:** SDL3 MinGW dev package extracted to `pod/vendor/SDL3-x.x.x/` (gitignored). See [commands.md](commands.md).

Three modes:
- No args — cycles 14 test scenarios (walking/climbing/hot/cold/foggy/storm/rain/connected), 2 s each, console prints evaluated state
- `--file data.csv` — replays a pod log, `--delay N` ms between rows (default 5000)
- `--port COM3` — live feed from pod at 115200 baud

## Current Results

| Suite | Passing | Skipped | Notes |
|-------|---------|---------|-------|
| native | 182 | 0 | test_math 56, test_algorithms 90, test_log 14, test_nijntje 17, test_display 5 |
| embedded | — | — | hardware-gated; GPS fix skips indoors, MPU6050/accel skip until soldered |
