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

float GpsBuffer::averageSpeedKph() const {
    if (_count < 2) return 0.0f;
    float totalDist = 0.0f;
    for (int i = 0; i < _count - 1; i++) {
        int idxA = (_head - _count + i + GPS_BUFFER_SIZE) % GPS_BUFFER_SIZE;
        int idxB = (_head - _count + i + 1 + GPS_BUFFER_SIZE) % GPS_BUFFER_SIZE;
        totalDist += MathUtils::haversineM(_buf[idxA].lat, _buf[idxA].lon,
                                           _buf[idxB].lat, _buf[idxB].lon);
    }
    uint32_t dt = newest().timestamp - oldest().timestamp;
    if (dt == 0) return 0.0f;
    return MathUtils::speedKph(totalDist, dt);
}

float GpsBuffer::averageAltGainPerMinute() const {
    if (_count < 2) return 0.0f;
    float totalGain = 0.0f;
    for (int i = 0; i < _count - 1; i++) {
        int idxA = (_head - _count + i + GPS_BUFFER_SIZE) % GPS_BUFFER_SIZE;
        int idxB = (_head - _count + i + 1 + GPS_BUFFER_SIZE) % GPS_BUFFER_SIZE;
        float delta = _buf[idxB].altitudeM - _buf[idxA].altitudeM;
        if (delta > 0) totalGain += delta;
    }
    uint32_t dt = newest().timestamp - oldest().timestamp;
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
