#pragma once
#include "hal/IDisplayHAL.h"
#include <stdint.h>

static constexpr uint16_t EPD_WIDTH       = 200;
static constexpr uint16_t EPD_HEIGHT      = 200;
static constexpr uint32_t EPD_BUFFER_SIZE = (EPD_WIDTH * EPD_HEIGHT) / 4;

enum class EPDColour : uint8_t {
    Black  = 0x0,
    White  = 0x1,
    Yellow = 0x2,
    Red    = 0x3,
};

class EPD1in54G {
public:
    explicit EPD1in54G(IDisplayHAL& hal);

    void init();
    void initFast();
    void clear(EPDColour colour);
    void display(const uint8_t* buffer);  // must be EPD_BUFFER_SIZE bytes
    void sleep();

private:
    IDisplayHAL& _hal;

    void reset();
    void sendCommand(uint8_t cmd);
    void sendData(uint8_t data);
    void waitReady();
    void applyBaseConfig();
    void turnOnDisplay();
};
