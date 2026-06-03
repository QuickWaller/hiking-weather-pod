#pragma once
#include <stdint.h>
#include "AccelReader.h"

struct CompassReading {
    float   headingDeg;   // 0–360, magnetic north (flat 2D, atan2(y,x))
    int16_t rawX, rawY, rawZ;
    bool    valid;
};

class CompassReader {
public:
    bool           begin();
    CompassReading read();

    // Tilt-compensated heading using MPU6050 accel data. Returns -1 if either
    // sensor read is invalid. Uses COMPASS_HARD_IRON_OFFSET_* from config.h.
    float          readTilted(const AccelReading& accel);
};
