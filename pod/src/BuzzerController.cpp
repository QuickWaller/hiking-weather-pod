#include "BuzzerController.h"
#include "algorithms/WeatherAlgorithm.h"
#include "config.h"

BuzzerAlert BuzzerController::evaluate(const WeatherPrediction& rain,
                                        const WeatherPrediction& storm,
                                        uint8_t localHour) {
    bool stormJust = storm.active && !_prevStormActive;
    bool rainJust  = rain.active  && !_prevRainActive;
    _prevStormActive = storm.active;
    _prevRainActive  = rain.active;

    if (stormJust && WeatherAlgorithm::shouldChirp(storm, localHour))
        return BuzzerAlert::Storm;

    // Rain never overrides quiet hours
    bool quiet = (localHour >= QUIET_HOUR_START || localHour < QUIET_HOUR_END);
    if (rainJust && !quiet)
        return BuzzerAlert::Rain;

    return BuzzerAlert::None;
}

#ifndef NATIVE_TEST
#include <Arduino.h>

void BuzzerController::sound(BuzzerAlert alert) {
    if (alert == BuzzerAlert::None) return;
    // PIN_BUZZER = GP14 on RP2350. On ESP32 dev, GPIO14 = GPS TX — buzzer is
    // non-functional on the dev board but the logic still runs.
    if (alert == BuzzerAlert::Storm) {
        for (int i = 0; i < 3; i++) { tone(PIN_BUZZER, 1200, 80); delay(180); }
    } else {
        for (int i = 0; i < 2; i++) { tone(PIN_BUZZER, 880, 120); delay(280); }
    }
}

#else
void BuzzerController::sound(BuzzerAlert) {}
#endif
