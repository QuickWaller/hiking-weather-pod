#pragma once
#include "IFramebuffer.h"
#include <Adafruit_GFX.h>

class Framebuffer : public IFramebuffer, public Adafruit_GFX {
public:
    Framebuffer();

    void drawPixel(int16_t x, int16_t y, uint16_t color) override;

    void fill(EPDColour colour) override;
    void fillRect(int16_t x, int16_t y, int16_t w, int16_t h, EPDColour colour) override;
    void drawSprite(int16_t x, int16_t y, const uint8_t* data, uint16_t w, uint16_t h) override;

    void setTextSize(uint8_t size) override       { Adafruit_GFX::setTextSize(size); }
    void setTextColor(uint16_t c) override        { Adafruit_GFX::setTextColor(c); }
    void setTextWrap(bool wrap) override          { Adafruit_GFX::setTextWrap(wrap); }
    void setCursor(int16_t x, int16_t y) override { Adafruit_GFX::setCursor(x, y); }
    void print(const char* str) override          { Adafruit_GFX::print(str); }

    const uint8_t* buffer() const override { return _buf; }

private:
    uint8_t _buf[EPD_BUFFER_SIZE];
    void setPixel(int16_t x, int16_t y, EPDColour colour);
};
