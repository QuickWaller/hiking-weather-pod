#include "ActivityDetector.h"
#include "config.h"

static bool isNight(const SensorData& s) {
    // Celestial when sun times are known. sunriseMin/sunsetMin are local
    // minutes-since-midnight; -1 means not yet computed (no GPS fix / bad clock),
    // in which case fall back to a fixed local window.
    if (s.sunriseMin < 0 || s.sunsetMin < 0)
        return s.hour >= NIGHT_FALLBACK_START_HOUR || s.hour < NIGHT_FALLBACK_END_HOUR;
    int nowMin = (int)s.hour * 60 + s.minute;
    return nowMin < s.sunriseMin || nowMin >= s.sunsetMin;
}

NijntjeState ActivityDetector::detect(const GpsBuffer& gps, const SensorData& s, uint32_t nowUnix) {
    uint32_t newestTs = (gps.count() > 0) ? gps.newest().timestamp : 0;
    bool gpsStale = (gps.count() == 0) ||
                    (nowUnix == 0) || (newestTs == 0) ||  // no trustworthy clock yet
                    (newestTs > nowUnix) ||               // clock skew — avoid uint underflow
                    (nowUnix - newestTs > GPS_STALE_THRESHOLD_S);

    if (!gpsStale && gps.count() >= CLIMBING_MIN_ENTRIES) {
        if (gps.averageAltGainPerMinute(CLIMBING_MIN_ENTRIES) >= CLIMBING_ALT_GAIN_M_PER_MIN)
            return NijntjeState::Climbing;
    }

    if (!gpsStale && gps.count() >= WALKING_MIN_ENTRIES) {
        if (gps.averageSpeedKph(WALKING_MIN_ENTRIES) >= WALKING_SPEED_KPH) {
            return isNight(s) ? NijntjeState::WalkingNight : NijntjeState::Walking;
        }
    }

    // Stationary — time-of-day picks the resting state. When sun times are known,
    // the sunset/sunrise edges drive it (evening starts at sunset, tent ends at
    // sunrise); the evening→tent split stays a fixed local bedtime hour.
    if (s.sunriseMin >= 0 && s.sunsetMin >= 0) {
        int nowMin = (int)s.hour * 60 + s.minute;
        if (nowMin >= s.sunriseMin && nowMin < s.sunsetMin)
            return NijntjeState::Resting;                 // sun up → daytime rest
        if (s.hour >= SLEEPING_TENT_HOUR_START || nowMin < s.sunriseMin)
            return NijntjeState::SleepingTent;            // bedtime … through to sunrise
        return NijntjeState::SleepyEvening;               // sunset … until bedtime
    }

    // Fallback (sun times unknown — no GPS fix / bad clock): fixed local windows.
    uint8_t h = s.hour;
    if (h >= SLEEPING_TENT_HOUR_START || h < NIGHT_FALLBACK_END_HOUR)
        return NijntjeState::SleepingTent;
    if (h >= SLEEPY_EVENING_HOUR_START && h < SLEEPY_EVENING_HOUR_END)
        return NijntjeState::SleepyEvening;
    return NijntjeState::Resting;
}
