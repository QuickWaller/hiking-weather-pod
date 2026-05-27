#include "WeatherAlgorithm.h"
#include "MathUtils.h"
#include "config.h"
#include <math.h>
#include <stdio.h>

// ── Zambretti score (0.0–1.0) ─────────────────────────────────────────────────
// Simplified without wind direction. Maps pressure rate to Zambretti tendency.
static float zambrettiScore(float rateHpaPerHour) {
    if (rateHpaPerHour < -3.0f)  return 1.0f;   // rapid fall — certain deterioration
    if (rateHpaPerHour < -1.5f)  return 0.75f;
    if (rateHpaPerHour < -0.5f)  return 0.50f;
    if (rateHpaPerHour < 0.0f)   return 0.25f;
    if (rateHpaPerHour < 0.5f)   return 0.10f;  // steady
    return 0.0f;                                  // rising — improving
}

// ── Pressure rate score (0.0–1.0) ─────────────────────────────────────────────
static float pressureRateScore(float rateHpaPerHour) {
    if (rateHpaPerHour >= 0.0f) return 0.0f;
    float rate = -rateHpaPerHour;
    if (rate >= 6.0f) return 1.0f;   // >6 hPa/hr = extreme
    return rate / 6.0f;
}

// ── Humidity trend score (0.0–1.0) ────────────────────────────────────────────
static float humidityScore(float humidityTrend) {
    if (humidityTrend <= 0.0f) return 0.0f;
    return fminf(humidityTrend / 2.0f, 1.0f);  // 2%/entry trend → full score
}

// ── Temperature drop score (0.0–1.0) ─────────────────────────────────────────
static float tempDropScore(float tempTrend) {
    if (tempTrend >= 0.0f) return 0.0f;
    return fminf(-tempTrend / 0.5f, 1.0f);  // 0.5°C/entry drop → full score
}

// ── Imminence: hours until event from pressure rate ───────────────────────────
// Based on empirical rule: >6 hPa/3hr falling = <2hr to event
static float imminenceHours(float rateHpaPerHour) {
    if (rateHpaPerHour >= 0.0f) return 24.0f;
    float rate3hr = -rateHpaPerHour * 3.0f;
    if (rate3hr >= 6.0f) return 2.0f;
    if (rate3hr >= 3.0f) return 4.0f;
    if (rate3hr >= 1.5f) return 8.0f;
    return 16.0f;
}

// ── Core update logic for one prediction ─────────────────────────────────────
static void updatePrediction(WeatherPrediction& pred,
                              uint8_t confidence,
                              uint8_t triggerThreshold,
                              uint8_t clearThreshold,
                              float   currentPressure,
                              float   maxPressure,
                              float   rateHpaPerHour,
                              uint32_t nowUnix) {
    pred.confidence = confidence;

    if (!pred.active) {
        if (confidence >= triggerThreshold) {
            pred.active           = true;
            pred.predictedAt      = nowUnix;
            pred.baselinePressure = maxPressure;
            pred.minPressure      = currentPressure;
        }
    } else {
        // Track the lowest pressure seen since trigger
        if (currentPressure < pred.minPressure)
            pred.minPressure = currentPressure;

        // Recovery = how much pressure has risen from the trough, relative to total drop
        float totalDrop = pred.baselinePressure - pred.minPressure;
        float recovery  = (totalDrop > 0.1f)
                        ? (currentPressure - pred.minPressure) / totalDrop
                        : 1.0f;
        if (confidence < clearThreshold && recovery >= PRESSURE_RECOVERY_RATIO) {
            pred.active = false;
            return;
        }

        // Recalculate estimated arrival (Option B — continuously updated)
        float hoursAway = imminenceHours(rateHpaPerHour);
        pred.estimatedArrival = nowUnix + (uint32_t)(hoursAway * 3600.0f);
    }
}

void WeatherAlgorithm::update(const WeatherBuffer& wb,
                               WeatherPrediction&   rain,
                               WeatherPrediction&   storm,
                               uint32_t             nowUnix) {
    float rate     = wb.pressureRateHpaPerHour(3);
    float maxP     = wb.maxPressure();
    float curP     = (wb.count() > 0) ? wb.newest().pressureAdj : maxP;
    float humTrend = wb.humidityTrend();
    float tmpTrend = wb.tempTrend();

    float pRate = pressureRateScore(rate);
    float zamb  = zambrettiScore(rate);
    float hum   = humidityScore(humTrend);
    float tmp   = tempDropScore(tmpTrend);

    uint8_t stormConf = (uint8_t)((STORM_W_PRESSURE_RATE * pRate
                                 + STORM_W_ZAMBRETTI     * zamb
                                 + STORM_W_HUMIDITY      * hum
                                 + STORM_W_TEMP_DROP     * tmp) * 100.0f);

    uint8_t rainConf  = (uint8_t)((RAIN_W_PRESSURE_RATE  * pRate
                                 + RAIN_W_ZAMBRETTI      * zamb
                                 + RAIN_W_HUMIDITY       * hum
                                 + RAIN_W_TEMP_DROP      * tmp) * 100.0f);

    updatePrediction(storm, stormConf, STORM_TRIGGER_THRESHOLD, STORM_CLEAR_THRESHOLD,
                     curP, maxP, rate, nowUnix);
    updatePrediction(rain,  rainConf,  RAIN_TRIGGER_THRESHOLD,  RAIN_CLEAR_THRESHOLD,
                     curP, maxP, rate, nowUnix);
}

const char* WeatherAlgorithm::bannerLine1(const WeatherPrediction& p, bool isStorm) {
    if (!p.active) return nullptr;
    // static buffer — sufficient for single-threaded embedded use
    static char buf[20];
    const char* label = isStorm ? "STORM" : "RAIN";

    if (p.estimatedArrival == 0) {
        snprintf(buf, sizeof(buf), "%s LIKELY", label);
        return buf;
    }
    // estimatedArrival is a unix timestamp — caller must pass current time separately
    // Here we store hours-away in estimatedArrival directly for display
    // (WeatherAlgorithm::update sets estimatedArrival = nowUnix + seconds)
    // This function receives the raw struct; caller computes remaining seconds
    snprintf(buf, sizeof(buf), "%s", label);
    return buf;
}

const char* WeatherAlgorithm::bannerLine2(const WeatherPrediction& p) {
    if (!p.active) return nullptr;
    static char buf[20];
    snprintf(buf, sizeof(buf), "CONF %d%%", p.confidence);
    return buf;
}

bool WeatherAlgorithm::shouldChirp(const WeatherPrediction& storm, uint8_t hour) {
    if (!storm.active) return false;
    bool quietHours = (hour >= QUIET_HOUR_START || hour < QUIET_HOUR_END);
    bool severe     = storm.confidence >= SEVERE_STORM_THRESHOLD;
    return !quietHours || severe;
}
