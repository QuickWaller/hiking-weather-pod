#pragma once
#include "sensors/WeatherPrediction.h"
#include <stdint.h>

enum class BuzzerAlert : uint8_t { None, Rain, Storm };

// Tracks prediction state transitions and fires alerts at most once per activation.
// Quiet-hour + severe-storm-override logic is in WeatherAlgorithm::shouldChirp().
// Rain never overrides quiet hours.
class BuzzerController {
public:
    BuzzerAlert evaluate(const WeatherPrediction& rain, const WeatherPrediction& storm,
                         uint8_t localHour);
    void sound(BuzzerAlert alert);

private:
    bool _prevStormActive = false;
    bool _prevRainActive  = false;
};
