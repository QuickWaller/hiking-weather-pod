#pragma once
#include "IDisplayHAL.h"
#include <stdint.h>

class ESP32DisplayHAL : public IDisplayHAL {
public:
    ESP32DisplayHAL(uint8_t pinCS, uint8_t pinDC, uint8_t pinReset, uint8_t pinBusy,
                    uint8_t pinSCK, uint8_t pinMOSI);
    void begin();

    void spiWrite(uint8_t byte) override;
    void setCS(bool high) override;
    void setDC(bool high) override;
    void setReset(bool high) override;
    bool readBusy() override;
    void delayMs(uint32_t ms) override;

private:
    uint8_t _pinCS, _pinDC, _pinReset, _pinBusy, _pinSCK, _pinMOSI;
};
