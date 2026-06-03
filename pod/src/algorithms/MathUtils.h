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

    // Median of up to 15 values (copies internally, does not modify input).
    // Even n → mean of the two middle values. Returns 0 for n <= 0.
    float median(const float* values, int n);

    // Slope of least-squares linear regression (positive = rising trend).
    // Uses the sample index (0,1,2,...) as x — assumes evenly-spaced samples.
    float linearRegressionSlope(const float* values, int n);

    // Slope (dy/dx) of least-squares regression over explicit x values.
    // Use when samples are unevenly spaced (e.g. x = time). Returns 0 if n < 2
    // or all x are equal (degenerate).
    float linearRegressionSlopeXY(const float* xs, const float* ys, int n);

    // Unix timestamp (seconds since 1970-01-01 UTC) from date/time components
    uint32_t unixFromDateTime(uint16_t year, uint8_t month, uint8_t day,
                              uint8_t hour, uint8_t minute, uint8_t second);

    // Date/time components from Unix timestamp
    void dateTimeFromUnix(uint32_t unix, uint16_t& year, uint8_t& month,
                          uint8_t& day, uint8_t& hour, uint8_t& minute,
                          uint8_t& second);

    // NZ timezone offset (minutes east of UTC) for a given UTC instant, with DST.
    // Returns +720 (NZST) or +780 (NZDT). DST runs last Sunday of Sep 02:00 NZST
    // through first Sunday of Apr 03:00 NZDT (the austral summer, crosses new year).
    int nzUtcOffsetMinutes(uint32_t utcUnix);

    // Day of year (1..366) for a calendar date. Accounts for leap years.
    int dayOfYear(uint16_t year, uint8_t month, uint8_t day);

    // Tilt-compensated magnetic heading in degrees (0=north, clockwise, 0–360).
    // Applies hard-iron offsets to raw HMC5883L values, then uses MPU6050 accel
    // roll/pitch to project the field onto the horizontal plane.
    // Formula: Honeywell HMC5883L application note (Xh/Yh, atan2(-Yh, Xh)).
    // Returns a heading in [0, 360). Accel should be unit-normalised (g units).
    float tiltCompensatedHeading(int16_t mx, int16_t my, int16_t mz,
                                  float ax, float ay, float az,
                                  float offsetX, float offsetY, float offsetZ);

    // Sunrise and sunset for a date/location, as minutes since LOCAL midnight.
    // utcOffsetMin shifts the computed UTC times to local. Each output is -1 if the
    // sun does not rise/set that day (polar — not reachable in NZ). USNO algorithm,
    // ~few-minute accuracy, ample for a day/night gate.
    void sunriseSunsetMinutes(float lat, float lon, int dayOfYear, int utcOffsetMin,
                              int16_t& sunriseMin, int16_t& sunsetMin);
}
