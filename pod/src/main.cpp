#ifndef UNIT_TEST

#include <Arduino.h>
#include <math.h>
#include <LittleFS.h>
#include "config.h"
#include "debug.h"
#include "EventLog.h"
#include "GpsReader.h"
#include "sensors/RtcReader.h"
#include "sensors/CompassReader.h"
#include "sensors/AccelReader.h"
#include "sensors/Bmp180Reader.h"
#include "sensors/Aht10Reader.h"
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
#include "UartSync.h"
#include "BuzzerController.h"

// ── Globals ───────────────────────────────────────────────────────────────────

static EventLog      eventLog;
static RtcReader     rtc;
static GpsReader     gps;
static CompassReader compass;
static AccelReader   accel;
static Bmp180Reader  bmp180;
static Aht10Reader   aht10;

static GpsBuffer         gpsBuffer;
static WeatherBuffer     weatherBuffer;
static WeatherPrediction rainPred{};
static WeatherPrediction stormPred{};

static bool compassOk = false;
static bool accelOk   = false;
static bool bmp180Ok  = false;
static bool aht10Ok   = false;
static bool rtcSynced = false;

static UartSync          uartSync;
static BuzzerController  buzzer;
static SensorData     sensor{};
static NijntjeDisplay display{};
static int            cycleCount = 0;

// Sunrise/sunset cache (local minutes since midnight; -1 = unknown). Refreshed once
// per day at the first wake ≥ SUN_REFRESH_HOUR, with a one-shot boot bootstrap.
static int16_t  cachedSunriseMin = -1;
static int16_t  cachedSunsetMin  = -1;
static uint16_t sunCalcDoy       = 0;   // day-of-year the cache holds (0 = never computed)

// Cached readings from last 5-min cycle
static Bmp180Reading lastPressure{};
static Aht10Reading  lastEnv{};

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

static void writeLogEntry(uint32_t now, uint32_t gpsMs, NijntjeState activity) {
    File f = LittleFS.open("/data.csv", "a");
    if (!f) {
        eventLog.error("LOG_FAIL", "data.csv", now);
        return;
    }
    float pressureRate = weatherBuffer.count() > 1
        ? weatherBuffer.pressureRateHpaPerHour(3) : 0.0f;
    char buf[220];
    LogFormatter::formatEntry(buf, sizeof(buf), now, sensor,
        stormPred, rainPred, pressureRate, activity, display, gpsMs, getFreeHeap());
    f.printf("%s\n", buf);
    f.close();
    if (sensor.cyberdeckConnected) uartSync.sendEntry(buf);
}

// ── Setup ─────────────────────────────────────────────────────────────────────

void setup() {
    Serial.begin(115200);
    delay(500);
    LOG("boot");

    eventLog.begin();

    rtc.begin();
    {
        RtcTime t = rtc.now();
        if (t.year < 2024 || t.year > 2035)
            eventLog.warn("RTC_INVALID", "awaiting GPS sync", 0);
    }

    gps.begin();
    pinMode(PIN_GX16_DETECT, INPUT_PULLUP);

    // Compass + accel are an IMU pair — disable accel if compass fails
    compassOk = compass.begin();
    if (!compassOk) {
        eventLog.error("SENSOR_FAIL", "compass+accel disabled", 0);
    } else {
        accelOk = accel.begin();
        if (!accelOk) eventLog.warn("SENSOR_FAIL", "accel", 0);
    }

    bmp180Ok = bmp180.begin();
    if (!bmp180Ok) eventLog.error("SENSOR_FAIL", "bmp180", 0);

    aht10Ok = aht10.begin();
    if (!aht10Ok) eventLog.error("SENSOR_FAIL", "aht10", 0);

    uartSync.begin();

    gpsBuffer.seedFromFlash();
    weatherBuffer.seedFromFlash();

    LOG("boot complete");
}

// ── Main loop (1-min cycle) ───────────────────────────────────────────────────

void loop() {
    uint32_t cycleStart = millis();
    cycleCount++;

    // ── GPS fix ───────────────────────────────────────────────────────────────
    uint32_t gpsStart = millis();
    while (!gps.fix().valid && millis() - gpsStart < GPS_FIX_TIMEOUT_MS)
        gps.poll();
    // Drain remaining NMEA to keep RMC timestamp fresh
    uint32_t drainUntil = millis() + 500;
    while (millis() < drainUntil) gps.poll();
    uint32_t gpsMs = millis() - gpsStart;

    // First valid GPS fix → sync RTC
    if (!rtcSynced && gps.fix().valid && gps.fix().unixTime > 1700000000UL) {
        rtc.setTime(gps.fix().unixTime);
        rtcSynced = true;
        eventLog.warn("RTC_SYNCED", "from GPS", gps.fix().unixTime);
        LOG("RTC synced: %lu", gps.fix().unixTime);
    }
    // Ongoing reconciliation: GPS UTC stays authoritative. A drifted or jumped RTC
    // can still look plausible (valid year) and would otherwise be trusted forever,
    // so re-sync when RTC and GPS disagree beyond the threshold. Both are UTC.
    else if (rtcSynced && gps.fix().valid && gps.fix().unixTime > 1700000000UL) {
        int32_t skew = (int32_t)(rtc.now().unixTime - gps.fix().unixTime);
        if (skew < 0) skew = -skew;
        if (skew > RTC_GPS_MAX_SKEW_S) {
            rtc.setTime(gps.fix().unixTime);
            eventLog.warn("RTC_DRIFT", "resynced from GPS", (uint32_t)skew);
            LOG("RTC drift %ld s → resynced from GPS", (long)skew);
        }
    }

    uint32_t now = getUnixTime();
    RtcTime  t   = rtc.now();

    // ── Populate SensorData ───────────────────────────────────────────────────
    sensor.lat               = gps.fix().lat;
    sensor.lon               = gps.fix().lon;
    sensor.altitudeM         = gps.fix().altM;
    sensor.gpsHasFix         = gps.fix().valid;
    sensor.unixTime          = now;
    sensor.hour              = t.hour;
    sensor.minute            = t.minute;
    sensor.cyberdeckConnected = (digitalRead(PIN_GX16_DETECT) == LOW);
    sensor.batteryPct        = 0;  // TODO: ADC on RP2350 GP29

    // ── GPS buffer ────────────────────────────────────────────────────────────
    // Push before pressure adjustment so the newest fix is included in the median.
    if (gps.fix().valid) {
        GpsEntry entry{ gps.fix().lat, gps.fix().lon, gps.fix().altM, now };
        gpsBuffer.push(entry);
    }

    // Median-filtered altitude smooths GPS spikes before pressure adjustment.
    // Falls back to the raw fix altitude if the buffer is empty.
    float adjAltM = (gpsBuffer.count() > 0)
        ? gpsBuffer.medianAltitude(ALTITUDE_MEDIAN_SAMPLES)
        : sensor.altitudeM;

    if (lastPressure.valid) {
        sensor.pressureRaw = lastPressure.pressureHpa;
        sensor.pressureAdj = MathUtils::altitudeAdjustedPressure(
            lastPressure.pressureHpa, adjAltM);
    }
    if (lastEnv.valid) {
        sensor.tempC    = lastEnv.tempC;
        sensor.humidity = lastEnv.humidity;
    }

    // ── Sunrise/sunset (daily refresh ≥03:00 local, boot bootstrap) ───────────
    // Needs a real position and a trustworthy clock. t is NZ-local (RtcReader), so
    // day-of-year is right near UTC midnight; offset is DST-aware for this instant.
    if (gps.fix().valid && t.year >= 2024 && t.year <= 2035) {
        uint16_t doy = (uint16_t)MathUtils::dayOfYear(t.year, t.month, t.day);
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

    // ── Activity + display evaluation ─────────────────────────────────────────
    NijntjeState activity = ActivityDetector::detect(gpsBuffer, sensor, now);
    display = NijntjeEvaluator::evaluate(sensor, activity, rainPred, stormPred);

    // TODO: if display changed → refresh e-ink (stubbed until 1.54" replaced)

    if (sensor.cyberdeckConnected) uartSync.poll();

    buzzer.sound(buzzer.evaluate(rainPred, stormPred, t.hour));

    // ── 5-min cycle ───────────────────────────────────────────────────────────
    if (cycleCount % FULL_CYCLE_INTERVAL == 0) {

        if (bmp180Ok) lastPressure = bmp180.read();
        if (aht10Ok)  lastEnv      = aht10.read();

        if (lastPressure.valid) {
            sensor.pressureRaw = lastPressure.pressureHpa;
            sensor.pressureAdj = MathUtils::altitudeAdjustedPressure(
                lastPressure.pressureHpa, adjAltM);
        }
        if (lastEnv.valid) {
            sensor.tempC    = lastEnv.tempC;
            sensor.humidity = lastEnv.humidity;
        }

        // Only record weather when we have a real position. Location pruning needs
        // valid coords; a GPS dropout (lat/lon defaulting to 0,0) would otherwise
        // wipe the whole 24h history and blind storm prediction during bad weather.
        if (lastPressure.valid && gps.fix().valid) {
            weatherBuffer.pruneByLocation(
                sensor.lat, sensor.lon, WEATHER_LOCATION_RADIUS_M);

            // Pressure drives storm prediction (~75% of confidence). If the AHT10
            // failed this cycle, store temp/humidity as NaN rather than bogus zeros
            // — the trend functions skip NaN, so a dead env sensor degrades rather
            // than poisons the prediction (0 °C is a real alpine temp, not a sentinel).
            float entryTemp = lastEnv.valid ? sensor.tempC    : NAN;
            float entryHum  = lastEnv.valid ? sensor.humidity : NAN;
            WeatherEntry we{ now, sensor.pressureAdj, entryTemp,
                             entryHum, sensor.lat, sensor.lon };
            weatherBuffer.push(we);
        }

        WeatherAlgorithm::update(weatherBuffer, rainPred, stormPred, now);

        writeLogEntry(now, gpsMs, activity);

        LOG("5min | temp=%.1fC hum=%.0f%% pres=%.1fhPa storm=%d%% rain=%d%%",
            sensor.tempC, sensor.humidity, sensor.pressureAdj,
            stormPred.confidence, rainPred.confidence);
    }

    // On RP2350: sleep GPS via UBX, enter DORMANT until RTC alarm
    // On ESP32: simulate 1-min cycle with delay
    uint32_t elapsed = millis() - cycleStart;
    if (elapsed < 60000UL) delay(60000UL - elapsed);
}

#endif // UNIT_TEST
