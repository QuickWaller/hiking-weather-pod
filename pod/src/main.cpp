#ifndef UNIT_TEST

#include <Arduino.h>
#include <math.h>
#include <LittleFS.h>
#include <SPI.h>
#include "config.h"
#include "debug.h"
#include "EventLog.h"
#include "GpsReader.h"
#include "sensors/RtcReader.h"
#include "sensors/Bme280Reader.h"
#include "sensors/GpsBuffer.h"
#include "sensors/WeatherBuffer.h"
#include "sensors/SensorData.h"
#include "sensors/WeatherPrediction.h"
#include "algorithms/ActivityDetector.h"
#include "algorithms/WeatherAlgorithm.h"
#include "algorithms/NijntjeEvaluator.h"
#include "algorithms/MathUtils.h"
#include "nijntje/NijntjeState.h"
#include "LogFormatter.h"
#include "storage/SdLogger.h"
#include "model/ModelManifest.h"
#include "model/ModelEvaluator.h"
#include "model/ModelFormat.h"

// ── Globals ───────────────────────────────────────────────────────────────────

static EventLog      eventLog;
static RtcReader     rtc;
static GpsReader     gps;
static Bme280Reader  bme280;
static SdLogger      sdLog;
static ModelEvaluator modelEval;

static GpsBuffer         gpsBuffer;
static WeatherBuffer     weatherBuffer;
static WeatherPrediction rainPred{};
static WeatherPrediction stormPred{};

static bool bme280Ok   = false;
static bool sdOk       = false;
static bool modelReady = false;
static bool rtcSynced  = false;

static SensorData    sensor{};
static NijntjeDisplay display{};

// Sunrise/sunset cache (local minutes since midnight; -1 = unknown).
// Refreshed once per day at the first wake ≥ SUN_REFRESH_HOUR.
static int16_t  cachedSunriseMin = -1;
static int16_t  cachedSunsetMin  = -1;
static uint16_t sunCalcDoy       = 0;

// Track which UTC hour we last ran the model (to run once per hour at :00 wake).
static uint32_t lastModelRunHour = 0xFFFFFFFF;

// ── Helpers ───────────────────────────────────────────────────────────────────

static uint32_t getUnixTime() {
    RtcTime t = rtc.now();
    if (t.year >= 2024 && t.year <= 2035) return t.unixTime;
    if (gps.fix().unixTime > 1700000000UL) return gps.fix().unixTime;
    return 0;
}

static uint32_t getFreeHeap() {
#ifdef ARDUINO_ARCH_RP2040
    return rp2040.getFreeHeap();
#else
    return ESP.getFreeHeap();
#endif
}

static void logRaw(uint32_t now, uint32_t gpsMs, NijntjeState activity) {
    float pressureRate = weatherBuffer.count() > 1
        ? weatherBuffer.pressureRateHpaPerHour(3) : 0.0f;
    char buf[240];
    LogFormatter::formatEntry(buf, sizeof(buf), now, sensor,
        stormPred, rainPred, pressureRate, activity, display, gpsMs, getFreeHeap());
    if (!sdLog.appendRaw(buf, now)) {
        eventLog.error("LOG_FAIL", "raw", now);
    }
}

// Build the 9-feature vector from current sensor + weather state.
// Feature order must match MODEL_FEATURE_NAMES in ModelFormat.h.
static void buildFeatureVector(float* feat) {
    // Cyclical time encodings (UTC)
    uint32_t now = sensor.unixTime;
    float hourAngle = (2.0f * 3.14159265f / 24.0f) * ((now / 3600) % 24);
    float doyAngle  = (2.0f * 3.14159265f / 365.0f) *
                      MathUtils::dayOfYear(
                          (uint16_t)(1970 + now / 31557600UL),  // approx year
                          (uint8_t)((now / 2629800UL) % 12 + 1), // approx month
                          (uint8_t)((now / 86400UL) % 30 + 1));  // approx day

    feat[0] = sensor.pressureAdj;                                   // pressure_hpa
    feat[1] = sensor.tempC;                                         // temp_c
    feat[2] = sensor.humidity;                                      // humidity_pct
    feat[3] = weatherBuffer.pressureRateHpaPerHour(1);              // pressure_rate_1h
    feat[4] = weatherBuffer.pressureRateHpaPerHour(3);              // pressure_rate_3h
    feat[5] = sinf(hourAngle);                                      // hour_sin
    feat[6] = cosf(hourAngle);                                      // hour_cos
    feat[7] = sinf(doyAngle);                                       // doy_sin
    feat[8] = cosf(doyAngle);                                       // doy_cos
}

static void formatIsoUtc(char* buf, size_t len, uint32_t unix) {
    uint16_t y; uint8_t mo, d, h, mi, s;
    MathUtils::dateTimeFromUnix(unix, y, mo, d, h, mi, s);
    snprintf(buf, len, "%04u-%02u-%02uT%02u:%02u:%02uZ", y, mo, d, h, mi, s);
}

static void runHourlyModel(uint32_t now) {
    if (!modelReady || !bme280Ok || !sensor.gpsHasFix) return;

    float feat[MODEL_N_FEATURES];
    buildFeatureVector(feat);

    // Write /inputs row: timestamp + feature values
    {
        char row[256]; size_t pos = 0;
        char ts[24]; formatIsoUtc(ts, sizeof(ts), now);
        pos += (size_t)snprintf(row + pos, sizeof(row) - pos, "%s", ts);
        for (uint8_t i = 0; i < MODEL_N_FEATURES && pos < sizeof(row) - 20; i++)
            pos += (size_t)snprintf(row + pos, sizeof(row) - pos, ",%.4f", feat[i]);
        sdLog.appendInputs(row, now);
    }

    auto result = modelEval.evaluate(feat, MODEL_N_FEATURES);

    if (!result.valid) {
        eventLog.error("MODEL_FAIL", "eval returned invalid", now);
        return;
    }

    // Write /pred row: timestamp + output values
    {
        char row[256]; size_t pos = 0;
        char ts[24]; formatIsoUtc(ts, sizeof(ts), now);
        pos += (size_t)snprintf(row + pos, sizeof(row) - pos, "%s", ts);
        for (uint8_t i = 0; i < result.n_outputs && pos < sizeof(row) - 20; i++)
            pos += (size_t)snprintf(row + pos, sizeof(row) - pos, ",%.4f", result.values[i]);
        sdLog.appendPred(row, now);
    }

    LOG("model: %u outputs, v[0]=%.3f", result.n_outputs, result.values[0]);
}

// ── Setup ─────────────────────────────────────────────────────────────────────

void setup() {
    Serial.begin(115200);
    delay(500);
    LOG("boot");

    eventLog.begin();

    // RTC
    rtc.begin();
    {
        RtcTime t = rtc.now();
        if (t.year < 2024 || t.year > 2035)
            eventLog.warn("RTC_INVALID", "awaiting GPS sync", 0);
    }

    // GPS
    gps.begin();

    // GX16 connection detect (interrupt, active-low)
    pinMode(PIN_GX16_DETECT, INPUT_PULLUP);

    // BME280
    bme280Ok = bme280.begin();
    if (!bme280Ok) eventLog.error("SENSOR_FAIL", "bme280", 0);

    // SD card
    SPI.begin(PIN_SPI_SCK, PIN_SPI_MISO, PIN_SPI_MOSI);
    sdOk = sdLog.begin(PIN_SD_CS);
    if (!sdOk) {
        eventLog.warn("SD_FAIL", "logging degraded", 0);
    }

    // ML model (requires SD)
    if (sdOk) {
        modelReady = modelEval.begin("/model/manifest.json", "/model/model.bin");
        if (!modelReady) {
            eventLog.warn("MODEL_SKIP", "missing or schema mismatch", 0);
        } else if (!modelEval.schemaValid()) {
            eventLog.error("MODEL_SCHEMA", "hash mismatch — using rule-based only", 0);
            modelReady = false;
        }
    }

    // Restore rolling buffers from LittleFS
    gpsBuffer.seedFromFlash();
    weatherBuffer.seedFromFlash();

    LOG("boot complete | bme280=%d sd=%d model=%d", bme280Ok, sdOk, modelReady);
}

// ── Main loop (10-min UTC-aligned wake) ──────────────────────────────────────

void loop() {
    uint32_t cycleStart = millis();

    // ── GPS fix ───────────────────────────────────────────────────────────────
    uint32_t gpsStart = millis();
    while (!gps.fix().valid && millis() - gpsStart < GPS_FIX_TIMEOUT_MS)
        gps.poll();
    uint32_t drainUntil = millis() + 500;
    while (millis() < drainUntil) gps.poll();
    uint32_t gpsMs = millis() - gpsStart;

    // ── RTC sync from GPS ─────────────────────────────────────────────────────
    if (!rtcSynced && gps.fix().valid && gps.fix().unixTime > 1700000000UL) {
        rtc.setTime(gps.fix().unixTime);
        rtcSynced = true;
        eventLog.warn("RTC_SYNCED", "from GPS", gps.fix().unixTime);
        LOG("RTC synced: %lu", gps.fix().unixTime);
    } else if (rtcSynced && gps.fix().valid && gps.fix().unixTime > 1700000000UL) {
        int32_t skew = (int32_t)(rtc.now().unixTime - gps.fix().unixTime);
        if (skew < 0) skew = -skew;
        if (skew > RTC_GPS_MAX_SKEW_S) {
            rtc.setTime(gps.fix().unixTime);
            eventLog.warn("RTC_DRIFT", "resynced from GPS", (uint32_t)skew);
        }
    }

    uint32_t now = getUnixTime();
    RtcTime  t   = rtc.now();

    // ── BME280 read ───────────────────────────────────────────────────────────
    Bme280Reading bmeRead{};
    if (bme280Ok) {
        bmeRead = bme280.read();
        if (!bmeRead.valid) eventLog.warn("SENSOR_WARN", "bme280 bad read", now);
    }

    // ── Populate SensorData ───────────────────────────────────────────────────
    sensor.lat       = gps.fix().lat;
    sensor.lon       = gps.fix().lon;
    sensor.altitudeM = gps.fix().altM;
    sensor.gpsHasFix = gps.fix().valid;
    sensor.unixTime  = now;
    sensor.hour      = t.hour;
    sensor.minute    = t.minute;
    sensor.cyberdeckConnected = (digitalRead(PIN_GX16_DETECT) == LOW);
    sensor.batteryPct         = 0;  // TODO: ADC on RP2350 GP29

    // ── GPS buffer ────────────────────────────────────────────────────────────
    if (gps.fix().valid) {
        GpsEntry entry{ gps.fix().lat, gps.fix().lon, gps.fix().altM, now };
        gpsBuffer.push(entry);
    }

    float adjAltM = (gpsBuffer.count() > 0)
        ? gpsBuffer.medianAltitude(ALTITUDE_MEDIAN_SAMPLES)
        : sensor.altitudeM;

    if (bmeRead.valid) {
        sensor.pressureRaw = bmeRead.pressureHpa;
        sensor.pressureAdj = MathUtils::altitudeAdjustedPressure(
            bmeRead.pressureHpa, adjAltM);
        sensor.tempC    = bmeRead.tempC;
        sensor.humidity = bmeRead.humidity;
    }

    // ── Sunrise/sunset (daily refresh ≥03:00 local, boot bootstrap) ──────────
    if (gps.fix().valid && t.year >= 2024 && t.year <= 2035) {
        uint16_t doy      = (uint16_t)MathUtils::dayOfYear(t.year, t.month, t.day);
        bool bootstrap    = (sunCalcDoy == 0);
        bool dailyRefresh = (t.hour >= SUN_REFRESH_HOUR && doy != sunCalcDoy);
        if (bootstrap || dailyRefresh) {
            int offMin = MathUtils::nzUtcOffsetMinutes(now);
            MathUtils::sunriseSunsetMinutes(sensor.lat, sensor.lon, doy, offMin,
                                            cachedSunriseMin, cachedSunsetMin);
            sunCalcDoy = doy;
        }
    }
    sensor.sunriseMin = cachedSunriseMin;
    sensor.sunsetMin  = cachedSunsetMin;

    // ── Weather buffer + algorithm ────────────────────────────────────────────
    if (bmeRead.valid && gps.fix().valid) {
        weatherBuffer.pruneByLocation(sensor.lat, sensor.lon, WEATHER_LOCATION_RADIUS_M);
        float entryHum = bmeRead.valid ? sensor.humidity : NAN;
        float entryTemp = bmeRead.valid ? sensor.tempC : NAN;
        WeatherEntry we{ now, sensor.pressureAdj, entryTemp, entryHum,
                         sensor.lat, sensor.lon };
        weatherBuffer.push(we);
    }
    WeatherAlgorithm::update(weatherBuffer, rainPred, stormPred, now);

    // ── Activity + display evaluation ─────────────────────────────────────────
    NijntjeState activity = ActivityDetector::detect(gpsBuffer, sensor, now);
    display = NijntjeEvaluator::evaluate(sensor, activity, rainPred, stormPred);

    // TODO: refresh e-ink display (1.54" 4-colour) when display state changes

    // ── Log raw telemetry to SD ───────────────────────────────────────────────
    logRaw(now, gpsMs, activity);

    LOG("10min | temp=%.1fC hum=%.0f%% pres=%.1fhPa storm=%d%% rain=%d%%",
        sensor.tempC, sensor.humidity, sensor.pressureAdj,
        stormPred.confidence, rainPred.confidence);

    // ── Hourly model run (at UTC :00 minute) ─────────────────────────────────
    uint32_t utcHour = now / 3600;
    if (utcHour != lastModelRunHour) {
        lastModelRunHour = utcHour;
        runHourlyModel(now);
    }

    // ── Sleep until next 10-min UTC boundary ─────────────────────────────────
    // RP2350: configure DS3231 alarm for next 10-min mark, enter DORMANT.
    // ESP32 bench: busy-delay to simulate 10-min cycle.
#ifndef ARDUINO_ARCH_RP2040
    uint32_t elapsed = millis() - cycleStart;
    if (elapsed < WAKE_INTERVAL_S * 1000UL)
        delay(WAKE_INTERVAL_S * 1000UL - elapsed);
#else
    // TODO: configure DS3231 SQW alarm for next 10-min UTC boundary,
    //       power-down GPS, then enter rp2040.dormant() / DORMANT sleep.
    //       Wake on PIN_RTC_SQW interrupt.
    uint32_t elapsed = millis() - cycleStart;
    if (elapsed < WAKE_INTERVAL_S * 1000UL)
        delay(WAKE_INTERVAL_S * 1000UL - elapsed);
#endif
}

#endif // UNIT_TEST
