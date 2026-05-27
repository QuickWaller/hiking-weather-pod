#pragma once
#include <stdint.h>

static constexpr int GPS_BUFFER_SIZE = 15;

struct GpsEntry {
    float    lat;
    float    lon;
    float    altitudeM;
    uint32_t timestamp;
};

class GpsBuffer {
public:
    GpsBuffer();

    void  push(const GpsEntry& e);
    int   count() const;

    float averageSpeedKph(int maxEntries) const;
    float averageAltGainPerMinute(int maxEntries) const;
    bool  isStationary(float radiusM) const;

    void  seedFromFlash();  // stub — implemented when LittleFS logging exists

    const GpsEntry& newest() const;
    const GpsEntry& oldest() const;

private:
    GpsEntry _buf[GPS_BUFFER_SIZE];
    int      _head;
    int      _count;
};
