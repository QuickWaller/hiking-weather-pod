#pragma once
#include "nijntje/NijntjeState.h"
#include "sensors/WeatherPrediction.h"
#include "sensors/SensorData.h"
#include <stdint.h>
#include <stddef.h>

namespace LogFormatter {
    char stateChar(NijntjeState s);
    char modChar(NijntjeModifier m);
    char bannerChar(BannerState b);
    char activityChar(NijntjeState s);  // strips Worried/Connected → Resting

    // Format one CSV line into buf (must be >= 200 bytes). Returns chars written.
    int formatEntry(char* buf, size_t bufLen,
                    uint32_t       unixTime,
                    const SensorData&        sensor,
                    const WeatherPrediction& storm,
                    const WeatherPrediction& rain,
                    float          pressureRate,
                    NijntjeState   activity,
                    const NijntjeDisplay&    display,
                    uint32_t       gpsMs,
                    uint32_t       freeHeap);
}
