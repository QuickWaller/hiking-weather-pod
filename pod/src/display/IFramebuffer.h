#pragma once
#include "EPD1in54G.h"
#include <stdint.h>

static constexpr uint16_t EPD_GFX_BLACK  = 0x0000;
static constexpr uint16_t EPD_GFX_WHITE  = 0xFFFF;
static constexpr uint16_t EPD_GFX_YELLOW = 0xFFE0;
static constexpr uint16_t EPD_GFX_RED    = 0xF800;

class IFramebuffer {
public:
    virtual void fill(EPDColour colour) = 0;
    virtual void fillRect(int16_t x, int16_t y, int16_t w, int16_t h, EPDColour colour) = 0;
    virtual void drawSprite(int16_t x, int16_t y, const uint8_t* data, uint16_t w, uint16_t h) = 0;
    virtual void setTextSize(uint8_t size) = 0;
    virtual void setTextColor(uint16_t colour) = 0;
    virtual void setTextWrap(bool wrap) = 0;
    virtual void setCursor(int16_t x, int16_t y) = 0;
    virtual void print(const char* str) = 0;
    virtual const uint8_t* buffer() const = 0;
    virtual ~IFramebuffer() = default;
};
