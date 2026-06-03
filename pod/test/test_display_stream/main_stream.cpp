// Display stream firmware — for use with the native_display simulator.
// Upload with: pio run -e esp32_stream --target upload
// Then run:    program.exe --port COM4
// Streams a CSV row every ~15 seconds. Not a Unity test — no pass/fail.

#include <Arduino.h>
#include <Wire.h>
#include <math.h>
#include "config.h"
#include "GpsReader.h"
#include "sensors/RtcReader.h"
#include "sensors/Bmp180Reader.h"
#include "sensors/Aht10Reader.h"
#include "sensors/CompassReader.h"
#include "sensors/AccelReader.h"
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

static RtcReader     rtc;
static GpsReader     gps;
static Bmp180Reader  bmp180;
static Aht10Reader   aht10;
static CompassReader compass;
static AccelReader   accel;

static bool compassOk = false;
static bool accelOk   = false;

static GpsBuffer         gpsBuffer;
static WeatherBuffer     weatherBuffer;
static WeatherPrediction rainPred{};
static WeatherPrediction stormPred{};

static SensorData     sensor{};
static NijntjeDisplay display{};

static bool bmp180Ok = false;
static bool aht10Ok  = false;
static bool rtcSynced = false;

static int16_t  cachedSunriseMin = -1;
static int16_t  cachedSunsetMin  = -1;
static uint16_t sunCalcDoy       = 0;

static Bmp180Reading lastPressure{};
static Aht10Reading  lastEnv{};

void setup() {
    Serial.begin(115200);
    delay(500);

    Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
    rtc.begin();
    gps.begin();

    bmp180Ok  = bmp180.begin();
    aht10Ok   = aht10.begin();
    compassOk = compass.begin();
    if (compassOk) accelOk = accel.begin();
    // Re-init Wire: Adafruit BMP085 calls Wire.begin() internally (no pins),
    // resetting to ESP32 defaults (21/22). Re-establish the correct pins.
    Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);

    Serial.println(F("# display_stream v1"));
    Serial.print(F("# bmp180="));   Serial.print(bmp180Ok  ? "ok" : "fail");
    Serial.print(F(" aht10="));     Serial.print(aht10Ok   ? "ok" : "fail");
    Serial.print(F(" compass="));    Serial.print(compassOk ? "ok" : "fail");
    Serial.print(F(" accel="));      Serial.println(accelOk  ? "ok" : "fail");
    Serial.println(F("timestamp,lat,lon,alt,temp,humidity,pressure_raw,pressure_adj,"
                     "battery,storm_conf,rain_conf,storm_active,rain_active,"
                     "pressure_rate,activity,state,modifier,banner,gps_ms,free_heap"));
}

void loop() {
    uint32_t cycleStart = millis();

    // ── GPS ───────────────────────────────────────────────────────────────────
    uint32_t gpsStart = millis();
    while (!gps.fix().valid && millis() - gpsStart < GPS_FIX_TIMEOUT_MS)
        gps.poll();
    uint32_t drainUntil = millis() + 500;
    while (millis() < drainUntil) gps.poll();
    uint32_t gpsMs = millis() - gpsStart;

    if (!rtcSynced && gps.fix().valid && gps.fix().unixTime > 1700000000UL) {
        rtc.setTime(gps.fix().unixTime);
        rtcSynced = true;
    }

    uint32_t now = rtc.now().unixTime;
    RtcTime  t   = rtc.now();

    // ── Sensors (only read if begin() succeeded) ──────────────────────────────
    if (bmp180Ok) lastPressure = bmp180.read();
    if (aht10Ok)  lastEnv      = aht10.read();

    sensor.lat               = gps.fix().lat;
    sensor.lon               = gps.fix().lon;
    sensor.altitudeM         = gps.fix().altM;
    sensor.gpsHasFix         = gps.fix().valid;
    sensor.unixTime          = now;
    sensor.hour              = t.hour;
    sensor.minute            = t.minute;
    sensor.batteryPct        = 0;
    sensor.cyberdeckConnected = false;

    if (lastPressure.valid) {
        sensor.pressureRaw = lastPressure.pressureHpa;
        sensor.pressureAdj = MathUtils::altitudeAdjustedPressure(
            lastPressure.pressureHpa, sensor.altitudeM);
    }
    if (lastEnv.valid) {
        sensor.tempC    = lastEnv.tempC;
        sensor.humidity = lastEnv.humidity;
    }

    // ── GPS buffer ────────────────────────────────────────────────────────────
    if (gps.fix().valid) {
        GpsEntry entry{ gps.fix().lat, gps.fix().lon, gps.fix().altM, now };
        gpsBuffer.push(entry);
    }

    // ── Sunrise/sunset ────────────────────────────────────────────────────────
    if (gps.fix().valid && t.year >= 2024 && t.year <= 2035) {
        uint16_t doy = (uint16_t)MathUtils::dayOfYear(t.year, t.month, t.day);
        if (sunCalcDoy == 0 || (t.hour >= SUN_REFRESH_HOUR && doy != sunCalcDoy)) {
            int offMin = MathUtils::nzUtcOffsetMinutes(now);
            MathUtils::sunriseSunsetMinutes(sensor.lat, sensor.lon, doy, offMin,
                                            cachedSunriseMin, cachedSunsetMin);
            sunCalcDoy = doy;
        }
    }
    sensor.sunriseMin = cachedSunriseMin;
    sensor.sunsetMin  = cachedSunsetMin;

    // ── Weather buffer + algorithm ────────────────────────────────────────────
    if (lastPressure.valid && gps.fix().valid) {
        weatherBuffer.pruneByLocation(sensor.lat, sensor.lon, WEATHER_LOCATION_RADIUS_M);
        float entryTemp = lastEnv.valid ? sensor.tempC    : NAN;
        float entryHum  = lastEnv.valid ? sensor.humidity : NAN;
        WeatherEntry we{ now, sensor.pressureAdj, entryTemp, entryHum,
                         sensor.lat, sensor.lon };
        weatherBuffer.push(we);
    }
    WeatherAlgorithm::update(weatherBuffer, rainPred, stormPred, now);

    // ── Activity + display ────────────────────────────────────────────────────
    NijntjeState activity = ActivityDetector::detect(gpsBuffer, sensor, now);
    display = NijntjeEvaluator::evaluate(sensor, activity, rainPred, stormPred);

    // ── Stream CSV ────────────────────────────────────────────────────────────
    float pressureRate = weatherBuffer.count() > 1
        ? weatherBuffer.pressureRateHpaPerHour(3) : 0.0f;
    char buf[256];
    LogFormatter::formatEntry(buf, sizeof(buf), now, sensor,
        stormPred, rainPred, pressureRate, activity, display, gpsMs,
        (uint32_t)ESP.getFreeHeap());

    // Append compass heading as col 20 (stream-only, not in main log format)
    if (compassOk) {
        float h = accelOk
            ? compass.readTilted(accel.read())
            : compass.read().headingDeg;
        char hbuf[16];
        snprintf(hbuf, sizeof(hbuf), ",%.1f", h);
        strncat(buf, hbuf, sizeof(buf) - strlen(buf) - 1);
    }
    Serial.println(buf);

    // 0.5-second compass ticks for the remainder of the 15-second cycle
    uint32_t elapsed = millis() - cycleStart;
    while (elapsed < 15000UL) {
        delay(500);
        elapsed = millis() - cycleStart;
        if (compassOk) {
            CompassReading mag = compass.read();
            AccelReading   a   = accelOk ? accel.read() : AccelReading{};
            float h = accelOk ? compass.readTilted(a) : mag.headingDeg;
            Serial.printf("C,%.1f\n", h);
            // TEMP axis-confirmation diagnostic — remove once orientation verified.
            // D,<mag x>,<mag y>,<mag z>,<accel x>,<accel y>,<accel z>
            Serial.printf("D,%d,%d,%d,%.3f,%.3f,%.3f\n",
                mag.rawX, mag.rawY, mag.rawZ, a.ax, a.ay, a.az);
        }
    }
}
