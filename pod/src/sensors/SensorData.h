#pragma once
#include <stdint.h>

struct SensorData {
    float    tempC;
    float    humidity;
    float    pressureRaw;   // hPa, direct from BMP180
    float    pressureAdj;   // hPa, altitude-adjusted to sea level
    float    altitudeM;
    float    lat;
    float    lon;
    float    speedKph;
    float    batteryPct;
    bool     gpsHasFix;
    bool     cyberdeckConnected;
    uint8_t  hour;
    uint8_t  minute;
    uint32_t unixTime;
    int16_t  sunriseMin = -1;  // local minutes since midnight; -1 = unknown (fallback)
    int16_t  sunsetMin  = -1;
};
