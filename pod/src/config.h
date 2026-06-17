#pragma once
#include <stdint.h>

// ── Pin assignments ───────────────────────────────────────────────────────────
// Target MCU = RP2350-Zero; dev/testing also runs on an ESP32 dev board. Pin numbers
// differ per MCU, so the live map is split by arch. **Authoritative wiring + rationale:
// docs/hardware.md — keep the two in sync.** The arduino-pico core defines
// ARDUINO_ARCH_RP2040 for the RP2350 too (same macro the readers use for Wire→Wire1).
#if defined(ARDUINO_ARCH_RP2040)
// ===== RP2350-Zero target (see docs/hardware.md) =====
// I2C1 bus
static constexpr uint8_t PIN_I2C_SDA          = 26;
static constexpr uint8_t PIN_I2C_SCL          = 27;
// RTC alarm wake (DS3231 SQW)
static constexpr uint8_t PIN_RTC_SQW          = 15;
// GPS — UART0
static constexpr uint8_t PIN_GPS_TX           = 12;
static constexpr uint8_t PIN_GPS_RX           = 13;
// GX16 connection detect (interrupt)
static constexpr uint8_t PIN_GX16_DETECT      = 14;
// ADC users (GP26-29 are the only ADCs; 26/27 are I2C → analog goes on 28/29)
static constexpr uint8_t PIN_ROTARY           = 28;
static constexpr uint8_t PIN_BATTERY_ADC      = 29;
// SPI0 shared bus (display + SD)
static constexpr uint8_t PIN_SPI_SCK          = 2;
static constexpr uint8_t PIN_SPI_MOSI         = 3;
static constexpr uint8_t PIN_SPI_MISO         = 4;
// microSD (chip select on the shared bus)
static constexpr uint8_t PIN_SD_CS            = 1;
// 1.54" 4-colour e-ink (Nijntje — the only display)
static constexpr uint8_t PIN_EPD154_CS        = 5;
static constexpr uint8_t PIN_EPD154_DC        = 6;
static constexpr uint8_t PIN_EPD154_RST       = 7;
static constexpr uint8_t PIN_EPD154_BUSY      = 8;
// DEAD — pins for dropped parts (compass/accel/buzzer/UART/2.13" panel). The code that
// references these is dead and slated for removal; 0xFF placeholders keep it compiling.
static constexpr uint8_t PIN_COMPASS_DRDY     = 0xFF;
static constexpr uint8_t PIN_BUZZER           = 0xFF;
static constexpr uint8_t PIN_CYBERDECK_TX     = 0xFF;
static constexpr uint8_t PIN_CYBERDECK_RX     = 0xFF;
static constexpr uint8_t PIN_EPD213_CS        = 0xFF;
static constexpr uint8_t PIN_EPD213_DC        = 0xFF;
static constexpr uint8_t PIN_EPD213_RST       = 0xFF;
static constexpr uint8_t PIN_EPD213_BUSY      = 0xFF;

#else
// ===== ESP32 dev board (current bench) — values unchanged =====
// I2C bus
static constexpr uint8_t PIN_I2C_SDA          = 26;
static constexpr uint8_t PIN_I2C_SCL          = 27;
// Sensor interrupt/control pins
static constexpr uint8_t PIN_COMPASS_DRDY     = 16;
static constexpr uint8_t PIN_RTC_SQW          = 17;
// GPS — UART0
static constexpr uint8_t PIN_GPS_TX           = 14;
static constexpr uint8_t PIN_GPS_RX           = 13;
// Cyberdeck — UART1
static constexpr uint8_t PIN_CYBERDECK_TX     = 4;
static constexpr uint8_t PIN_CYBERDECK_RX     = 5;
// Buzzer (PWM)
static constexpr uint8_t PIN_BUZZER           = 14;
// GX16 connection detect
static constexpr uint8_t PIN_GX16_DETECT      = 9;
// Rotary position switch (ADC)
static constexpr uint8_t PIN_ROTARY           = 28;
// Battery voltage (ADC)
static constexpr uint8_t PIN_BATTERY_ADC      = 29;
// Display/SD — SPI shared bus
static constexpr uint8_t PIN_SPI_SCK          = 2;
static constexpr uint8_t PIN_SPI_MOSI         = 3;
static constexpr uint8_t PIN_SPI_MISO         = 0xFF;  // SD not wired on the ESP32 bench
static constexpr uint8_t PIN_SD_CS            = 0xFF;
// 2.13" e-ink (black/white)
static constexpr uint8_t PIN_EPD213_CS        = 1;
static constexpr uint8_t PIN_EPD213_DC        = 6;
static constexpr uint8_t PIN_EPD213_RST       = 7;
static constexpr uint8_t PIN_EPD213_BUSY      = 8;
// 1.54" 4-colour e-ink
static constexpr uint8_t PIN_EPD154_CS        = 10;
static constexpr uint8_t PIN_EPD154_DC        = 11;
static constexpr uint8_t PIN_EPD154_RST       = 15;
static constexpr uint8_t PIN_EPD154_BUSY      = 0;
#endif

// I2C device addresses (arch-independent)
static constexpr uint8_t I2C_ADDR_DS3231      = 0x68;
static constexpr uint8_t I2C_ADDR_BME280      = 0x76;  // pod sensor: pressure+temp+humidity. 0x77 if SDO high — VERIFY

// ── Activity detection ────────────────────────────────────────────────────────
static constexpr float   CLIMBING_ALT_GAIN_M_PER_MIN = 10.0f;  // m/min sustained
static constexpr int     CLIMBING_MIN_ENTRIES         = 10;     // entries (~10 min)
static constexpr float   WALKING_SPEED_KPH            = 2.0f;   // min avg speed
static constexpr int     WALKING_MIN_ENTRIES          = 10;
static constexpr float   STATIONARY_RADIUS_M          = 25.0f;  // GPS noise tolerance (bush/valley)

// ── Modifier thresholds ───────────────────────────────────────────────────────
static constexpr float   HOT_TEMP_C           = 25.0f;
static constexpr float   COLD_TEMP_C          =  8.0f;
static constexpr float   FOG_DEWPOINT_SPREAD_C =  1.5f;  // temp - dewpoint < this
static constexpr float   FOG_HUMIDITY_PCT     = 95.0f;

// ── Timezone ──────────────────────────────────────────────────────────────────
// The DS3231 holds UTC (synced from GPS UTC). RtcReader::now() keeps unixTime as
// UTC but converts the civil fields (year..second) to NZ local, so all time-of-day
// logic (isNight, sleepy/tent windows, sun-time refresh) is local. The active offset
// (incl. DST) is computed by MathUtils::nzUtcOffsetMinutes() — these are the bounds.
// DST: NZDT (UTC+13) from last Sunday of Sep 02:00 to first Sunday of Apr 03:00.
static constexpr int NZ_STD_OFFSET_MIN = 12 * 60;  // +720 NZST (winter)
static constexpr int NZ_DST_OFFSET_MIN = 13 * 60;  // +780 NZDT (summer)

// Once the RTC is synced from GPS, GPS UTC stays authoritative. If RTC and GPS
// (both UTC) disagree by more than this, the RTC has drifted/jumped → re-sync it.
static constexpr int32_t RTC_GPS_MAX_SKEW_S = 120;

// ── Time-of-day (24h hours, NZ local) ─────────────────────────────────────────
static constexpr uint8_t SLEEPY_EVENING_HOUR_START =  19;
static constexpr uint8_t SLEEPY_EVENING_HOUR_END   =  22;
static constexpr uint8_t SLEEPING_TENT_HOUR_START  =  22;  // wraps through midnight

// ── Sunrise/sunset (celestial isNight) ───────────────────────────────────────
// Sun times are computed once per day for the pod's current location and cached;
// isNight compares local time against them. SUN_ZENITH_DEG 90.833° = official
// sunrise (geometric horizon + atmospheric refraction). When sun times are unknown
// (no GPS fix / bad clock) isNight falls back to this fixed local window.
static constexpr float   SUN_ZENITH_DEG          = 90.833f;
static constexpr uint8_t SUN_REFRESH_HOUR        =  3;   // recompute at first wake ≥03:00 local
static constexpr uint8_t NIGHT_FALLBACK_START_HOUR = 20; // fallback night = ≥20:00 …
static constexpr uint8_t NIGHT_FALLBACK_END_HOUR   =  6; // … or <06:00

// ── Weather prediction — thresholds ──────────────────────────────────────────
static constexpr uint8_t STORM_TRIGGER_THRESHOLD  = 65;   // % confidence to activate
static constexpr uint8_t STORM_CLEAR_THRESHOLD    = 30;   // % confidence to clear
static constexpr uint8_t SEVERE_STORM_THRESHOLD   = 85;   // % to override quiet hours
static constexpr uint8_t RAIN_TRIGGER_THRESHOLD   = 55;
static constexpr uint8_t RAIN_CLEAR_THRESHOLD     = 25;
static constexpr float   PRESSURE_RECOVERY_RATIO  = 0.50f; // 50% of drop must recover

// ── Weather prediction — absolute pressure level (Zambretti modifier) ────────
// The same falling tendency means MORE at already-low pressure (a deepening low)
// and LESS at high pressure (a settling high). These bound a multiplier applied to
// the Zambretti score. Uses sea-level-adjusted pressure (pressureAdj), so altitude
// does not contaminate the level reading. Tunable after field calibration.
static constexpr float PRESSURE_LEVEL_LOW_HPA   = 1000.0f;  // below this → boost
static constexpr float PRESSURE_LEVEL_HIGH_HPA  = 1020.0f;  // above this → damp
static constexpr float PRESSURE_LEVEL_SPAN_HPA  = 15.0f;    // hPa to reach max boost/damp
static constexpr float PRESSURE_LEVEL_MAX_BOOST = 1.40f;    // factor at LOW-SPAN and below
static constexpr float PRESSURE_LEVEL_MIN_DAMP  = 0.70f;    // factor at HIGH+SPAN and above

// ── BME280 calibration ────────────────────────────────────────────────────────
// Added to every valid raw BME280 pressure reading (hPa) before any downstream use.
// The Zambretti LEVEL term reads ABSOLUTE (sea-level) pressure, so a fixed sensor
// bias shifts boost/damp directly. Set via a one-time offset cal: park the pod at a
// known elevation and compare pressureAdj against a nearby station's QNH. 0 = uncal.
static constexpr float BME280_PRESSURE_OFFSET_HPA = 0.0f;

// ── Weather prediction — storm weights (must sum to 1.0) ─────────────────────
static constexpr float STORM_W_PRESSURE_RATE  = 0.50f;
static constexpr float STORM_W_ZAMBRETTI      = 0.25f;
static constexpr float STORM_W_HUMIDITY       = 0.20f;
static constexpr float STORM_W_TEMP_DROP      = 0.05f;

// ── Weather prediction — rain weights (must sum to 1.0) ──────────────────────
static constexpr float RAIN_W_PRESSURE_RATE   = 0.45f;
static constexpr float RAIN_W_ZAMBRETTI       = 0.30f;
static constexpr float RAIN_W_HUMIDITY        = 0.20f;
static constexpr float RAIN_W_TEMP_DROP       = 0.05f;

// Weights must sum to 1.0 or the 0–100 confidence scaling breaks. Guard at compile
// time (tolerance for float rounding). Edit a weight without fixing the others → build fails.
static_assert(STORM_W_PRESSURE_RATE + STORM_W_ZAMBRETTI + STORM_W_HUMIDITY + STORM_W_TEMP_DROP > 0.999f &&
              STORM_W_PRESSURE_RATE + STORM_W_ZAMBRETTI + STORM_W_HUMIDITY + STORM_W_TEMP_DROP < 1.001f,
              "Storm weights must sum to 1.0");
static_assert(RAIN_W_PRESSURE_RATE + RAIN_W_ZAMBRETTI + RAIN_W_HUMIDITY + RAIN_W_TEMP_DROP > 0.999f &&
              RAIN_W_PRESSURE_RATE + RAIN_W_ZAMBRETTI + RAIN_W_HUMIDITY + RAIN_W_TEMP_DROP < 1.001f,
              "Rain weights must sum to 1.0");

// ── Alert quiet hours ─────────────────────────────────────────────────────────
// No audible buzzer in the design (removed 2026-06-13); used by
// WeatherAlgorithm::shouldChirp() which remains for algorithm testing.
static constexpr uint8_t QUIET_HOUR_START = 22;
static constexpr uint8_t QUIET_HOUR_END   =  7;

// ── Location-based weather pruning ───────────────────────────────────────────
static constexpr float WEATHER_LOCATION_RADIUS_M = 50000.0f;  // 50km

// ── GPS staleness ─────────────────────────────────────────────────────────────
static constexpr uint32_t GPS_STALE_THRESHOLD_S = 180;  // 3 missed fixes → treat as no data

// Number of recent GPS fixes to median-filter altitude over before pressure
// adjustment. GPS altitude is the noisiest axis (±10-30 m); a ±30 m spike on the
// raw value injects ~3.5 hPa of false swing into the storm signal. 5 ≈ last 5 min.
static constexpr int ALTITUDE_MEDIAN_SAMPLES = 5;

// ── Timing ────────────────────────────────────────────────────────────────────
static constexpr uint32_t GPS_FIX_TIMEOUT_MS  = 8000;
static constexpr uint32_t WAKE_INTERVAL_S     = 600;  // 10-min UTC-aligned wake
