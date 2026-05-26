#pragma once
#include <stdint.h>

struct SensorData {
    float    tempC;
    float    humidity;
    float    pressureRaw;   // hPa, direct from BME280
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
};
