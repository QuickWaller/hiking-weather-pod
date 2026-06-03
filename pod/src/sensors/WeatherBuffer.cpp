#include "WeatherBuffer.h"
#include "algorithms/MathUtils.h"
#include <math.h>

WeatherBuffer::WeatherBuffer() : _head(0), _count(0) {}

void WeatherBuffer::push(const WeatherEntry& e) {
    _buf[_head] = e;
    _head = (_head + 1) % WEATHER_BUFFER_SIZE;
    if (_count < WEATHER_BUFFER_SIZE) _count++;
}

int WeatherBuffer::count() const { return _count; }

const WeatherEntry& WeatherBuffer::newest() const {
    int idx = (_head - 1 + WEATHER_BUFFER_SIZE) % WEATHER_BUFFER_SIZE;
    return _buf[idx];
}

const WeatherEntry& WeatherBuffer::entryAt(int age) const {
    int idx = (_head - 1 - age + WEATHER_BUFFER_SIZE * 2) % WEATHER_BUFFER_SIZE;
    return _buf[idx];
}

float WeatherBuffer::pressureRateHpaPerHour(int hours) const {
    int entries = hours * 12;  // 12 entries per hour at 5-min intervals
    if (_count < 2) return 0.0f;
    int n = (_count < entries) ? _count : entries;
    if (n > PRESSURE_RATE_MAX_SAMPLES) n = PRESSURE_RATE_MAX_SAMPLES;

    // Least-squares slope of pressure vs time (hPa/hour). Using a regression over
    // all samples in the window — rather than a 2-point slope between the oldest
    // and newest — makes the rate robust to a single noisy endpoint and to uneven
    // sample spacing (skipped cycles). x is hours since the window's oldest entry.
    float xs[PRESSURE_RATE_MAX_SAMPLES];
    float ys[PRESSURE_RATE_MAX_SAMPLES];
    uint32_t t0 = entryAt(n - 1).timestamp;  // oldest in window
    for (int i = 0; i < n; i++) {
        const WeatherEntry& e = entryAt(n - 1 - i);  // oldest → newest
        xs[i] = (float)(e.timestamp - t0) / 3600.0f;
        ys[i] = e.pressureAdj;
    }
    return MathUtils::linearRegressionSlopeXY(xs, ys, n);
}

float WeatherBuffer::maxPressure() const {
    if (_count == 0) return 0.0f;
    float maxP = _buf[0].pressureAdj;
    for (int i = 1; i < _count; i++) {
        if (_buf[i].pressureAdj > maxP) maxP = _buf[i].pressureAdj;
    }
    return maxP;
}

float WeatherBuffer::humidityTrend() const {
    int entries = 36;  // last 3 hours nominal
    if (_count < 2) return 0.0f;
    int n = (_count < entries) ? _count : entries;

    // Regress against actual time (hours) rather than sample index, so skipped
    // cycles don't distort the trend. Returns %/hour. NaN samples (env sensor was
    // dead that cycle) are skipped so a failed AHT10 doesn't poison the trend.
    float xs[36], ys[36];
    int m = 0;
    uint32_t t0 = entryAt(n - 1).timestamp;
    for (int i = 0; i < n; i++) {
        const WeatherEntry& e = entryAt(n - 1 - i);
        if (e.humidity != e.humidity) continue;  // NaN check
        xs[m] = (float)(e.timestamp - t0) / 3600.0f;
        ys[m] = e.humidity;
        m++;
    }
    return MathUtils::linearRegressionSlopeXY(xs, ys, m);
}

float WeatherBuffer::tempTrend() const {
    int entries = 36;
    if (_count < 2) return 0.0f;
    int n = (_count < entries) ? _count : entries;

    // Time-based slope (°C/hour) — robust to uneven sample spacing. NaN samples
    // (dead env sensor) are skipped.
    float xs[36], ys[36];
    int m = 0;
    uint32_t t0 = entryAt(n - 1).timestamp;
    for (int i = 0; i < n; i++) {
        const WeatherEntry& e = entryAt(n - 1 - i);
        if (e.tempC != e.tempC) continue;  // NaN check
        xs[m] = (float)(e.timestamp - t0) / 3600.0f;
        ys[m] = e.tempC;
        m++;
    }
    return MathUtils::linearRegressionSlopeXY(xs, ys, m);
}

void WeatherBuffer::pruneByLocation(float lat, float lon, float maxDistM) {
    // A near-(0,0) reference means we have no valid GPS fix this cycle. Pruning
    // against it would measure thousands of km to every real entry and wipe the
    // entire history — exactly when GPS struggles, i.e. during bad weather. Skip.
    if (fabsf(lat) < 0.5f && fabsf(lon) < 0.5f) return;
    while (_count > 0) {
        const WeatherEntry& old = entryAt(_count - 1);
        float dist = MathUtils::haversineM(lat, lon, old.lat, old.lon);
        if (dist <= maxDistM) break;
        _count--;
    }
}

void WeatherBuffer::seedFromFlash() {
    // stub — populate buffer from LittleFS log on boot
}
