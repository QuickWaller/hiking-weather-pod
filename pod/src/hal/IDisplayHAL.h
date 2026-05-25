#pragma once
#include <stdint.h>

class IDisplayHAL {
public:
    virtual ~IDisplayHAL() = default;
    virtual void spiWrite(uint8_t byte) = 0;
    virtual void setCS(bool high) = 0;
    virtual void setDC(bool high) = 0;    // true = data, false = command
    virtual void setReset(bool high) = 0;
    virtual bool readBusy() = 0;          // true = HIGH = display ready
    virtual void delayMs(uint32_t ms) = 0;
};
