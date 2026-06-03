#pragma once
#include <Arduino.h>

// Live GPS data from most recent valid fix
struct GpsFix {
    float    lat;
    float    lon;
    float    altM;
    int      sats;
    int      quality;    // 0=none, 1=GPS, 2=DGPS
    uint32_t fixMs;      // millis() at which fix was received
    uint32_t unixTime;   // UTC unix timestamp from RMC, 0 if not yet received
    bool     valid;
};

class GpsReader {
public:
    void begin();
    void poll();           // call every loop() — non-blocking
    const GpsFix& fix() const { return _fix; }

private:
    bool parseGGA(const char* line);
    bool parseRMC(const char* line);
    void parseGSV(const char* line);
    void logStatus();

    GpsFix   _fix{};
    char     _buf[128];
    int      _len         = 0;
    bool     _gotFirstFix = false;
    uint32_t _startMs     = 0;
    uint32_t _lastStatusMs = 0;
    int      _satsInView  = 0;  // total across all constellations from GSV
};
