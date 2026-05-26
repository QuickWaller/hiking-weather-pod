#pragma once
#include "sensors/SensorData.h"
#include "sensors/WeatherPrediction.h"
#include "nijntje/NijntjeState.h"

namespace NijntjeEvaluator {
    NijntjeDisplay evaluate(const SensorData&       s,
                             NijntjeState            activity,
                             const WeatherPrediction& rain,
                             const WeatherPrediction& storm);
}
