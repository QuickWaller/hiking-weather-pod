#pragma once
#include <stdint.h>

struct RtcTime {
    uint16_t year;
    uint8_t  month;
    uint8_t  day;
    uint8_t  hour;
    uint8_t  minute;
    uint8_t  second;
    uint32_t unixTime;
};

class RtcReader {
public:
    void    begin();
    RtcTime now();
    void    setTime(uint32_t unixTime);
    void    clearAlarm();
    bool    alarmFired();

private:
    static uint8_t bcdToDec(uint8_t val);
    static uint8_t decToBcd(uint8_t val);
};
