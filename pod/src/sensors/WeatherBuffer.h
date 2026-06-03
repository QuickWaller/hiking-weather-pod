#pragma once
#include <stdint.h>

static constexpr int WEATHER_BUFFER_SIZE = 288;  // 24 hours at 5-min intervals

// Cap on samples used for the pressure-rate regression. The algorithm uses a
// 3-hour window (36 samples at 5-min spacing); this bounds the stack arrays.
static constexpr int PRESSURE_RATE_MAX_SAMPLES = 36;

struct WeatherEntry {
    uint32_t timestamp;
    float    pressureAdj;  // hPa, altitude-adjusted
    float    tempC;
    float    humidity;
    float    lat;
    float    lon;
};

class WeatherBuffer {
public:
    WeatherBuffer();

    void  push(const WeatherEntry& e);
    int   count() const;

    // Pressure rate of change in hPa/hour over last N hours (negative = falling)
    float pressureRateHpaPerHour(int hours = 3) const;

    // Max pressure in entire buffer — used as baseline for recovery calculation
    float maxPressure() const;

    // Humidity trend in %/hour: positive = rising (over last ~3 hours).
    // Time-based regression — robust to unevenly-spaced / skipped samples.
    float humidityTrend() const;

    // Temperature trend in °C/hour over last ~3 hours (negative = falling).
    // Time-based regression — robust to unevenly-spaced / skipped samples.
    float tempTrend() const;

    // Drop oldest entries that are more than maxDistM from current position
    void  pruneByLocation(float lat, float lon, float maxDistM);

    void  seedFromFlash();  // stub

    const WeatherEntry& newest() const;

private:
    WeatherEntry _buf[WEATHER_BUFFER_SIZE];
    int          _head;
    int          _count;

    const WeatherEntry& entryAt(int age) const;  // age=0 is newest
};
