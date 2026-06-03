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

    // Median altitude over the most recent maxEntries fixes (metres). Smooths out
    // GPS-altitude spikes, the noisiest GPS axis, before pressure adjustment.
    // Returns 0 if the buffer is empty.
    float medianAltitude(int maxEntries) const;

    void  seedFromFlash();  // stub — implemented when LittleFS logging exists

    const GpsEntry& newest() const;
    const GpsEntry& oldest() const;

private:
    GpsEntry _buf[GPS_BUFFER_SIZE];
    int      _head;
    int      _count;
};
