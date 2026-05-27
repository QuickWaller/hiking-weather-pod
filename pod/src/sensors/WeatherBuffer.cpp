#include "WeatherBuffer.h"
#include "algorithms/MathUtils.h"

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
    const WeatherEntry& now  = entryAt(0);
    const WeatherEntry& then = entryAt(n - 1);
    uint32_t dt = now.timestamp - then.timestamp;
    if (dt == 0) return 0.0f;
    return (now.pressureAdj - then.pressureAdj) / (dt / 3600.0f);
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
    int entries = 36;  // last 3 hours
    if (_count < 2) return 0.0f;
    int n = (_count < entries) ? _count : entries;

    float values[36];
    for (int i = 0; i < n; i++)
        values[i] = entryAt(n - 1 - i).humidity;
    return MathUtils::linearRegressionSlope(values, n);
}

float WeatherBuffer::tempTrend() const {
    int entries = 36;
    if (_count < 2) return 0.0f;
    int n = (_count < entries) ? _count : entries;

    float values[36];
    for (int i = 0; i < n; i++)
        values[i] = entryAt(n - 1 - i).tempC;
    return MathUtils::linearRegressionSlope(values, n);
}

void WeatherBuffer::pruneByLocation(float lat, float lon, float maxDistM) {
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
