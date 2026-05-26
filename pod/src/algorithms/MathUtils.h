#pragma once
#include <stdint.h>

namespace MathUtils {
    // Hypsometric formula: adjust station pressure to sea-level equivalent
    float altitudeAdjustedPressure(float rawHpa, float altitudeM);

    // Magnus formula: dew point in °C
    float dewPointC(float tempC, float humidity);

    // Haversine distance between two GPS coordinates, in metres
    float haversineM(float lat1, float lon1, float lat2, float lon2);

    // Speed in kph from distance (metres) and time delta (seconds)
    float speedKph(float distM, uint32_t dtSeconds);

    // Slope of least-squares linear regression (positive = rising trend)
    float linearRegressionSlope(const float* values, int n);
}
