#include "LogFormatter.h"
#include "algorithms/MathUtils.h"
#include <stdio.h>

char LogFormatter::stateChar(NijntjeState s) {
    switch (s) {
        case NijntjeState::Climbing:      return 'C';
        case NijntjeState::Walking:       return 'W';
        case NijntjeState::WalkingNight:  return 'N';
        case NijntjeState::Resting:       return 'R';
        case NijntjeState::SleepyEvening: return 'E';
        case NijntjeState::SleepingTent:  return 'T';
        case NijntjeState::Worried:       return 'X';
        case NijntjeState::Connected:     return 'K';
        default:                          return '?';
    }
}

char LogFormatter::modChar(NijntjeModifier m) {
    switch (m) {
        case NijntjeModifier::Hot:   return 'H';
        case NijntjeModifier::Cold:  return 'C';
        case NijntjeModifier::Foggy: return 'F';
        default:                      return 'N';
    }
}

char LogFormatter::bannerChar(BannerState b) {
    switch (b) {
        case BannerState::Yellow: return 'Y';
        case BannerState::Red:    return 'R';
        default:                   return 'N';
    }
}

char LogFormatter::activityChar(NijntjeState s) {
    if (s == NijntjeState::Worried || s == NijntjeState::Connected)
        return 'R';
    return stateChar(s);
}

int LogFormatter::formatEntry(char* buf, size_t bufLen,
                               uint32_t unixTime,
                               const SensorData& sensor,
                               const WeatherPrediction& storm,
                               const WeatherPrediction& rain,
                               float pressureRate,
                               NijntjeState activity,
                               const NijntjeDisplay& display,
                               uint32_t gpsMs,
                               uint32_t freeHeap)
{
    uint16_t year; uint8_t month, day, hour, min, sec;
    MathUtils::dateTimeFromUnix(unixTime, year, month, day, hour, min, sec);

    return snprintf(buf, bufLen,
        "%04u-%02u-%02uT%02u:%02u:%02uZ,"
        "%.6f,%.6f,%d,"
        "%.1f,%d,"
        "%.2f,%.2f,"
        "%d,"
        "%u,%u,"
        "%u,%u,"
        "%.2f,"
        "%c,%c,%c,%c,"
        "%lu,%lu",
        year, month, day, hour, min, sec,
        sensor.lat, sensor.lon, (int)sensor.altitudeM,
        sensor.tempC, (int)sensor.humidity,
        sensor.pressureRaw, sensor.pressureAdj,
        (int)sensor.batteryPct,
        (unsigned)storm.confidence, (unsigned)rain.confidence,
        (unsigned)storm.active, (unsigned)rain.active,
        pressureRate,
        activityChar(activity), stateChar(display.state),
        modChar(display.modifier), bannerChar(display.banner),
        (unsigned long)gpsMs, (unsigned long)freeHeap
    );
}
