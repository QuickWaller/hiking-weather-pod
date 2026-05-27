#pragma once
#include <stdint.h>

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

// ── Time-of-day (24h hours) ───────────────────────────────────────────────────
static constexpr uint8_t SLEEPY_EVENING_HOUR_START =  19;
static constexpr uint8_t SLEEPY_EVENING_HOUR_END   =  22;
static constexpr uint8_t SLEEPING_TENT_HOUR_START  =  22;  // wraps through midnight

// ── Weather prediction — thresholds ──────────────────────────────────────────
static constexpr uint8_t STORM_TRIGGER_THRESHOLD  = 65;   // % confidence to activate
static constexpr uint8_t STORM_CLEAR_THRESHOLD    = 30;   // % confidence to clear
static constexpr uint8_t SEVERE_STORM_THRESHOLD   = 85;   // % to override quiet hours
static constexpr uint8_t RAIN_TRIGGER_THRESHOLD   = 55;
static constexpr uint8_t RAIN_CLEAR_THRESHOLD     = 25;
static constexpr float   PRESSURE_RECOVERY_RATIO  = 0.50f; // 50% of drop must recover

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

// ── Buzzer ────────────────────────────────────────────────────────────────────
static constexpr uint8_t QUIET_HOUR_START = 22;
static constexpr uint8_t QUIET_HOUR_END   =  7;

// ── Location-based weather pruning ───────────────────────────────────────────
static constexpr float WEATHER_LOCATION_RADIUS_M = 50000.0f;  // 50km

// ── GPS staleness ─────────────────────────────────────────────────────────────
static constexpr uint32_t GPS_STALE_THRESHOLD_S = 180;  // 3 missed fixes → treat as no data

// ── Timing ────────────────────────────────────────────────────────────────────
static constexpr int     FULL_CYCLE_INTERVAL = 5;     // every Nth 1-min wake = full cycle
static constexpr uint32_t GPS_FIX_TIMEOUT_MS = 8000;
