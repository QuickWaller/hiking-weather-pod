#pragma once
#include <stdint.h>

struct WeatherPrediction {
    uint32_t predictedAt;       // unix time when confidence first crossed threshold
    uint32_t estimatedArrival;  // unix time of predicted event — recalculated each cycle
    uint8_t  confidence;        // 0–100
    float    baselinePressure;  // max pressure in last 24hrs at trigger time
    float    minPressure;       // lowest pressure seen since trigger — used for recovery calc
    bool     active;
};
