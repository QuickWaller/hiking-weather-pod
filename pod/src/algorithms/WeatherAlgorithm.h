#pragma once
#include "sensors/WeatherBuffer.h"
#include "sensors/WeatherPrediction.h"

namespace WeatherAlgorithm {
    void update(const WeatherBuffer& wb,
                WeatherPrediction&   rain,
                WeatherPrediction&   storm,
                uint32_t             nowUnix);

    // Banner display strings derived from a prediction
    const char* bannerLine1(const WeatherPrediction& p, bool isStorm);
    const char* bannerLine2(const WeatherPrediction& p);

    // True if chirp should sound given quiet-hour rules
    bool shouldChirp(const WeatherPrediction& storm, uint8_t hour);

    // Convert a 0.0–1.0 weighted score to a 0–100 confidence, rounding to nearest
    // (not truncating) and clamping. Truncation meant 64.99 never tripped a 65
    // threshold.
    uint8_t scoreToConfidence(float score01);
}
