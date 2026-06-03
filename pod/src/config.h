#pragma once
#include <stdint.h>

// ── Pin assignments ───────────────────────────────────────────────────────────
// I2C bus
static constexpr uint8_t PIN_I2C_SDA          = 26;
static constexpr uint8_t PIN_I2C_SCL          = 27;

// I2C device addresses
static constexpr uint8_t I2C_ADDR_DS3231      = 0x68;
static constexpr uint8_t I2C_ADDR_MPU6050     = 0x69;  // AD0 wired to 3.3V
static constexpr uint8_t I2C_ADDR_BMP180      = 0x77;
static constexpr uint8_t I2C_ADDR_AHT10       = 0x38;
static constexpr uint8_t I2C_ADDR_HMC5883L    = 0x1E;  // confirmed XC4496

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

// Display — SPI shared bus
static constexpr uint8_t PIN_SPI_SCK          = 2;
static constexpr uint8_t PIN_SPI_MOSI         = 3;

// 2.13" e-ink (black/white)
static constexpr uint8_t PIN_EPD213_CS        = 1;
static constexpr uint8_t PIN_EPD213_DC        = 6;
static constexpr uint8_t PIN_EPD213_RST       = 7;
static constexpr uint8_t PIN_EPD213_BUSY      = 8;

// 1.54" 4-colour e-ink — FRIED, awaiting replacement
static constexpr uint8_t PIN_EPD154_CS        = 10;
static constexpr uint8_t PIN_EPD154_DC        = 11;
static constexpr uint8_t PIN_EPD154_RST       = 15;
static constexpr uint8_t PIN_EPD154_BUSY      = 0;

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

// ── Compass calibration ───────────────────────────────────────────────────────
// Hard-iron offsets (HMC5883L raw LSB units). The buzzer is a hard-iron source
// and must be idle during calibration. Zero = uncalibrated.
// TODO: implement user-triggered calibration routine that collects per-axis
// min/max over ~15s of rotation and stores midpoints to LittleFS.
static constexpr float COMPASS_HARD_IRON_OFFSET_X = 0.0f;
static constexpr float COMPASS_HARD_IRON_OFFSET_Y = 0.0f;
static constexpr float COMPASS_HARD_IRON_OFFSET_Z = 0.0f;

// Accel→compass axis remap (yaw about the shared +Z). Tilt compensation needs the
// MPU6050 accel axes expressed in the HMC5883L frame; the two breakouts are mounted
// rotated in-plane. Quadrant = CCW rotation viewed from +Z (top):
//   0 → ( ax,  ay)   1 → (-ay,  ax)   2 → (-ax, -ay)   3 → ( ay, -ax)
// Z is shared (both +Z up), so az passes through. Set 0 if remounted aligned.
// Confirmed 2026-06-01 via axis tilt tests: compass -Y down → accel +X,
// compass +X down → accel +Y, so rx=ay, ry=-ax → quadrant 3.
static constexpr int ACCEL_YAW_QUADRANT = 3;

// ── BMP180 calibration ───────────────────────────────────────────────────────
// Added to every valid raw BMP180 pressure reading (hPa) before any downstream use.
// The Zambretti LEVEL term above reads ABSOLUTE (sea-level) pressure, so a fixed
// sensor bias shifts boost/damp directly — the rate/tendency term cancels a constant
// bias, the level term does NOT. Set via a one-time offset cal: park the pod at a
// known elevation and compare pressureAdj against a nearby station's QNH. 0 = uncal.
static constexpr float BMP180_PRESSURE_OFFSET_HPA = 0.0f;

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

// ── Buzzer ────────────────────────────────────────────────────────────────────
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
static constexpr int     FULL_CYCLE_INTERVAL = 5;     // every Nth 1-min wake = full cycle
static constexpr uint32_t GPS_FIX_TIMEOUT_MS = 8000;
