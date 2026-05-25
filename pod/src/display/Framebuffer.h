#pragma once
#include "EPD1in54G.h"
#include <Adafruit_GFX.h>
#include <stdint.h>

// RGB565 constants mapping to EPD colours, for use with Adafruit GFX text methods
static constexpr uint16_t EPD_GFX_BLACK  = 0x0000;
static constexpr uint16_t EPD_GFX_WHITE  = 0xFFFF;
static constexpr uint16_t EPD_GFX_YELLOW = 0xFFE0;
static constexpr uint16_t EPD_GFX_RED    = 0xF800;

class Framebuffer : public Adafruit_GFX {
public:
    Framebuffer();

    void drawPixel(int16_t x, int16_t y, uint16_t color) override;

    void fill(EPDColour colour);
    void fillRect(int16_t x, int16_t y, int16_t w, int16_t h, EPDColour colour);
    void drawSprite(int16_t x, int16_t y, const uint8_t* sprite, uint16_t sw, uint16_t sh);

    const uint8_t* buffer() const { return _buf; }

private:
    uint8_t _buf[EPD_BUFFER_SIZE];
    void setPixel(int16_t x, int16_t y, EPDColour colour);
};
