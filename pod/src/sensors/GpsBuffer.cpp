#include "GpsBuffer.h"
#include "algorithms/MathUtils.h"
#include <math.h>

GpsBuffer::GpsBuffer() : _head(0), _count(0) {}

void GpsBuffer::push(const GpsEntry& e) {
    _buf[_head] = e;
    _head = (_head + 1) % GPS_BUFFER_SIZE;
    if (_count < GPS_BUFFER_SIZE) _count++;
}

int GpsBuffer::count() const { return _count; }

const GpsEntry& GpsBuffer::newest() const {
    int idx = (_head - 1 + GPS_BUFFER_SIZE) % GPS_BUFFER_SIZE;
    return _buf[idx];
}

const GpsEntry& GpsBuffer::oldest() const {
    if (_count < GPS_BUFFER_SIZE)
        return _buf[0];
    return _buf[_head];
}

float GpsBuffer::averageSpeedKph(int maxEntries) const {
    if (_count < 2) return 0.0f;
    int n = (_count < maxEntries) ? _count : maxEntries;
    float totalDist = 0.0f;
    for (int i = 0; i < n - 1; i++) {
        int idxA = (_head - n + i + GPS_BUFFER_SIZE) % GPS_BUFFER_SIZE;
        int idxB = (_head - n + i + 1 + GPS_BUFFER_SIZE) % GPS_BUFFER_SIZE;
        totalDist += MathUtils::haversineM(_buf[idxA].lat, _buf[idxA].lon,
                                           _buf[idxB].lat, _buf[idxB].lon);
    }
    int oldestIdx = (_head - n + GPS_BUFFER_SIZE) % GPS_BUFFER_SIZE;
    int newestIdx = (_head - 1 + GPS_BUFFER_SIZE) % GPS_BUFFER_SIZE;
    uint32_t dt = _buf[newestIdx].timestamp - _buf[oldestIdx].timestamp;
    if (dt == 0) return 0.0f;
    return MathUtils::speedKph(totalDist, dt);
}

float GpsBuffer::averageAltGainPerMinute(int maxEntries) const {
    if (_count < 2) return 0.0f;
    int n = (_count < maxEntries) ? _count : maxEntries;
    float totalGain = 0.0f;
    for (int i = 0; i < n - 1; i++) {
        int idxA = (_head - n + i + GPS_BUFFER_SIZE) % GPS_BUFFER_SIZE;
        int idxB = (_head - n + i + 1 + GPS_BUFFER_SIZE) % GPS_BUFFER_SIZE;
        float delta = _buf[idxB].altitudeM - _buf[idxA].altitudeM;
        if (delta > 0) totalGain += delta;
    }
    int oldestIdx = (_head - n + GPS_BUFFER_SIZE) % GPS_BUFFER_SIZE;
    int newestIdx = (_head - 1 + GPS_BUFFER_SIZE) % GPS_BUFFER_SIZE;
    uint32_t dt = _buf[newestIdx].timestamp - _buf[oldestIdx].timestamp;
    if (dt == 0) return 0.0f;
    return totalGain / (dt / 60.0f);
}

bool GpsBuffer::isStationary(float radiusM) const {
    if (_count == 0) return true;
    const GpsEntry& ref = newest();
    for (int i = 0; i < _count; i++) {
        float dist = MathUtils::haversineM(ref.lat, ref.lon,
                                           _buf[i].lat, _buf[i].lon);
        if (dist > radiusM) return false;
    }
    return true;
}

void GpsBuffer::seedFromFlash() {
    // stub — populate buffer from LittleFS log on boot
}
