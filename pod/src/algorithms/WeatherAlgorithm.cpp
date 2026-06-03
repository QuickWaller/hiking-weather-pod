#include "WeatherAlgorithm.h"
#include "MathUtils.h"
#include "config.h"
#include <math.h>
#include <stdio.h>

// ── Absolute pressure level factor ────────────────────────────────────────────
// Real Zambretti uses pressure LEVEL as well as tendency: the same fall is more
// ominous when pressure is already low (deepening low) and less so when high
// (settling high). Returns a multiplier — boosts below LOW, damps above HIGH,
// neutral (1.0) between, clamped. Invalid/zero pressure → neutral.
static float pressureLevelFactor(float pHpa) {
    if (pHpa <= 0.0f) return 1.0f;
    if (pHpa < PRESSURE_LEVEL_LOW_HPA) {
        float f = 1.0f + (PRESSURE_LEVEL_LOW_HPA - pHpa) / PRESSURE_LEVEL_SPAN_HPA
                       * (PRESSURE_LEVEL_MAX_BOOST - 1.0f);
        return f > PRESSURE_LEVEL_MAX_BOOST ? PRESSURE_LEVEL_MAX_BOOST : f;
    }
    if (pHpa > PRESSURE_LEVEL_HIGH_HPA) {
        float f = 1.0f - (pHpa - PRESSURE_LEVEL_HIGH_HPA) / PRESSURE_LEVEL_SPAN_HPA
                       * (1.0f - PRESSURE_LEVEL_MIN_DAMP);
        return f < PRESSURE_LEVEL_MIN_DAMP ? PRESSURE_LEVEL_MIN_DAMP : f;
    }
    return 1.0f;
}

// ── Zambretti score (0.0–1.0) ─────────────────────────────────────────────────
// Tendency (rate) binning, modulated by absolute pressure level. No wind input.
static float zambrettiScore(float rateHpaPerHour, float currentPressureHpa) {
    float base;
    if (rateHpaPerHour < -3.0f)       base = 1.0f;   // rapid fall — certain deterioration
    else if (rateHpaPerHour < -1.5f)  base = 0.75f;
    else if (rateHpaPerHour < -0.5f)  base = 0.50f;
    else if (rateHpaPerHour < 0.0f)   base = 0.25f;
    else if (rateHpaPerHour < 0.5f)   base = 0.10f;  // steady
    else                              base = 0.0f;    // rising — improving
    float s = base * pressureLevelFactor(currentPressureHpa);
    return s > 1.0f ? 1.0f : s;
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
    // Trend is now %/hour. 24%/hr (== the old 2%/5-min-entry) → full score.
    return fminf(humidityTrend / 24.0f, 1.0f);
}

// ── Temperature drop score (0.0–1.0) ─────────────────────────────────────────
static float tempDropScore(float tempTrend) {
    if (tempTrend >= 0.0f) return 0.0f;
    // Trend is now °C/hour. 6°C/hr drop (== the old 0.5°C/5-min-entry) → full score.
    return fminf(-tempTrend / 6.0f, 1.0f);
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
            // Set arrival estimate on the trigger cycle too, so it is never left at 0
            // for the first active cycle (which would flip the banner text spuriously).
            pred.estimatedArrival = nowUnix + (uint32_t)(imminenceHours(rateHpaPerHour) * 3600.0f);
        }
    } else {
        // Track the lowest pressure seen since trigger.
        // Guard against curP==0 (empty buffer after location-prune) — that sentinel
        // would corrupt minPressure to 0, making totalDrop look enormous and causing
        // premature clearing on the next real cycle.
        if (currentPressure > 0.0f && currentPressure < pred.minPressure)
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

uint8_t WeatherAlgorithm::scoreToConfidence(float score01) {
    float pct = score01 * 100.0f + 0.5f;  // round to nearest
    if (pct > 100.0f) pct = 100.0f;
    if (pct < 0.0f)   pct = 0.0f;
    return (uint8_t)pct;
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
    float zamb  = zambrettiScore(rate, curP);
    float hum   = humidityScore(humTrend);
    float tmp   = tempDropScore(tmpTrend);

    uint8_t stormConf = scoreToConfidence(STORM_W_PRESSURE_RATE * pRate
                                        + STORM_W_ZAMBRETTI     * zamb
                                        + STORM_W_HUMIDITY      * hum
                                        + STORM_W_TEMP_DROP     * tmp);

    uint8_t rainConf  = scoreToConfidence(RAIN_W_PRESSURE_RATE  * pRate
                                        + RAIN_W_ZAMBRETTI      * zamb
                                        + RAIN_W_HUMIDITY       * hum
                                        + RAIN_W_TEMP_DROP      * tmp);

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
