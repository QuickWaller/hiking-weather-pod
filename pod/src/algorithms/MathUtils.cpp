#include "MathUtils.h"
#include <math.h>

static constexpr float DEG2RAD = 3.14159265358979f / 180.0f;
static constexpr float EARTH_R_M = 6371000.0f;

float MathUtils::altitudeAdjustedPressure(float rawHpa, float altitudeM) {
    // Hypsometric formula: P0 = P * exp(alt / (29.3 * T_virtual))
    // Simplified with standard temperature lapse rate, T_virtual ≈ 288K at sea level
    return rawHpa * expf(altitudeM / 8434.0f);
}

float MathUtils::dewPointC(float tempC, float humidity) {
    // Magnus formula
    const float a = 17.27f;
    const float b = 237.7f;
    float gamma = (a * tempC / (b + tempC)) + logf(humidity / 100.0f);
    return (b * gamma) / (a - gamma);
}

float MathUtils::haversineM(float lat1, float lon1, float lat2, float lon2) {
    float dLat = (lat2 - lat1) * DEG2RAD;
    float dLon = (lon2 - lon1) * DEG2RAD;
    float a = sinf(dLat / 2) * sinf(dLat / 2)
            + cosf(lat1 * DEG2RAD) * cosf(lat2 * DEG2RAD)
            * sinf(dLon / 2) * sinf(dLon / 2);
    return EARTH_R_M * 2.0f * atan2f(sqrtf(a), sqrtf(1.0f - a));
}

float MathUtils::speedKph(float distM, uint32_t dtSeconds) {
    if (dtSeconds == 0) return 0.0f;
    return (distM / dtSeconds) * 3.6f;
}

float MathUtils::linearRegressionSlope(const float* values, int n) {
    if (n < 2) return 0.0f;
    float sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0;
    for (int i = 0; i < n; i++) {
        sumX  += i;
        sumY  += values[i];
        sumXY += i * values[i];
        sumX2 += i * i;
    }
    float denom = n * sumX2 - sumX * sumX;
    if (fabsf(denom) < 1e-9f) return 0.0f;
    return (n * sumXY - sumX * sumY) / denom;
}
