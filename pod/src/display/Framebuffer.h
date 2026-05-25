#pragma once
#include "EPD1in54G.h"
#include <stdint.h>

class Framebuffer {
public:
    Framebuffer();

    void fill(EPDColour colour);
    void fillRect(int16_t x, int16_t y, int16_t w, int16_t h, EPDColour colour);
    void drawSprite(int16_t x, int16_t y, const uint8_t* sprite, uint16_t sw, uint16_t sh);

    const uint8_t* buffer() const { return _buf; }

private:
    uint8_t _buf[EPD_BUFFER_SIZE];
    void setPixel(int16_t x, int16_t y, EPDColour colour);
};
