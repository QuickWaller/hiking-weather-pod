#include "ActivityDetector.h"
#include "config.h"

static bool isNight(uint8_t hour) {
    // Simplified: night = 20:00–06:00. Replace with celestial calc when available.
    return hour >= 20 || hour < 6;
}

NijntjeState ActivityDetector::detect(const GpsBuffer& gps, const SensorData& s) {
    if (gps.count() >= CLIMBING_MIN_ENTRIES) {
        if (gps.averageAltGainPerMinute() >= CLIMBING_ALT_GAIN_M_PER_MIN)
            return NijntjeState::Climbing;
    }

    if (gps.count() >= WALKING_MIN_ENTRIES) {
        if (gps.averageSpeedKph() >= WALKING_SPEED_KPH) {
            return isNight(s.hour) ? NijntjeState::WalkingNight : NijntjeState::Walking;
        }
    }

    // Stationary — time-of-day determines which resting state
    uint8_t h = s.hour;
    if (h >= SLEEPING_TENT_HOUR_START || h < 6)
        return NijntjeState::SleepingTent;
    if (h >= SLEEPY_EVENING_HOUR_START && h < SLEEPY_EVENING_HOUR_END)
        return NijntjeState::SleepyEvening;
    return NijntjeState::Resting;
}
