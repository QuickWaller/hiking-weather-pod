#include "NijntjeEvaluator.h"
#include "MathUtils.h"
#include "config.h"

static NijntjeModifier computeModifier(const SensorData& s, NijntjeState state) {
    // Modifier only applies to Walking, Climbing, Resting
    if (state != NijntjeState::Walking  &&
        state != NijntjeState::Climbing &&
        state != NijntjeState::Resting)
        return NijntjeModifier::None;

    // Priority: Foggy > Cold > Hot > None
    float dewPoint = MathUtils::dewPointC(s.tempC, s.humidity);
    float spread   = s.tempC - dewPoint;
    if (spread < FOG_DEWPOINT_SPREAD_C && s.humidity > FOG_HUMIDITY_PCT)
        return NijntjeModifier::Foggy;
    if (s.tempC < COLD_TEMP_C)
        return NijntjeModifier::Cold;
    if (s.tempC > HOT_TEMP_C)
        return NijntjeModifier::Hot;
    return NijntjeModifier::None;
}

NijntjeDisplay NijntjeEvaluator::evaluate(const SensorData&        s,
                                           NijntjeState             activity,
                                           const WeatherPrediction& rain,
                                           const WeatherPrediction& storm) {
    NijntjeDisplay d;

    // ── State priority ────────────────────────────────────────────────────────
    if (s.cyberdeckConnected) {
        d.state    = NijntjeState::Connected;
        d.modifier = NijntjeModifier::None;
        d.banner   = BannerState::None;
        return d;
    }

    if (storm.active) {
        d.state = NijntjeState::Worried;
    } else {
        d.state = activity;
    }

    // ── Modifier ──────────────────────────────────────────────────────────────
    d.modifier = computeModifier(s, d.state);

    // ── Banner: Red > Yellow > None ───────────────────────────────────────────
    if (storm.active)
        d.banner = BannerState::Red;
    else if (rain.active)
        d.banner = BannerState::Yellow;
    else
        d.banner = BannerState::None;

    return d;
}
