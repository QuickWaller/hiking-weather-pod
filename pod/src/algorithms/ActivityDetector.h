#pragma once
#include "sensors/GpsBuffer.h"
#include "sensors/SensorData.h"
#include "nijntje/NijntjeState.h"

namespace ActivityDetector {
    NijntjeState detect(const GpsBuffer& gps, const SensorData& s);
}
