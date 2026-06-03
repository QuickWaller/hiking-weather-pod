#pragma once
#include <stdint.h>

struct AccelReading {
    float ax, ay, az;   // g  (±2g range)
    float gx, gy, gz;   // deg/s  (±250°/s range)
    bool  valid;
};

class AccelReader {
public:
    bool         begin();
    AccelReading read();
};
