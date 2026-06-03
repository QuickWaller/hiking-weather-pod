# Pod — Plans

## ✅ Completed: Main Loop Wiring

main.cpp implements the full 1-min / 5-min wake cycle. All sensors integrated, GPS→RTC sync on first fix, EventLog for failures, CSV logging to LittleFS. Display calls stubbed until 1.54" replacement arrives.

## ✅ Completed: Algorithm Integration

Full pipeline wired: SensorData → ActivityDetector → NijntjeEvaluator → NijntjeDisplay → LogFormatter → CSV.
LogFormatter extracted for native testability. 14 pipeline tests added in test_log.

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

## Future / Deferred

- AS3935 lightning detector (provisional — not yet confirmed)
- Pack-away mode (needs accelerometer tap detection)
- On-demand compass on the **2.13" B/W display** (fast, partial-refresh capable — NOT the 1.54" colour panel). Button-triggered only — sensors powered down otherwise. Interaction: button held → live needle via partial refresh at a few Hz → on release, one full refresh to clear ghosting, then power sensors down.
  - ✅ **Tilt compensation done:** `MathUtils::tiltCompensatedHeading()` (Honeywell app-note formula, 10 native tests). `CompassReader::readTilted(accel)` calls it using `COMPASS_HARD_IRON_OFFSET_*` stubs from config.h. 2 embedded integration tests added.
  - **Still TODO:** button wiring + main-loop compass mode, needle renderer on 2.13" display, power management (MPU6050 sleep, HMC5883L idle between reads).
  - **Calibration (stubbed):** offsets are zero constants in config.h. TODO: user-triggered routine — long-press → "rotate slowly" ~15s → collect per-axis min/max → offsets = midpoints → save to LittleFS.
  - **Gotcha:** the buzzer is a hard-iron source — calibrate with it idle, never read compass while it is sounding.
- Cyberdeck UART protocol + log sync
- Tide table integration
