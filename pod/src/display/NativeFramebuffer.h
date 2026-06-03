#pragma once
#include "IFramebuffer.h"

class NativeFramebuffer : public IFramebuffer {
public:
    NativeFramebuffer();

    void fill(EPDColour colour) override;
    void fillRect(int16_t x, int16_t y, int16_t w, int16_t h, EPDColour colour) override;
    void drawSprite(int16_t x, int16_t y, const uint8_t* data, uint16_t w, uint16_t h) override;

    void setTextSize(uint8_t) override  {}
    void setTextColor(uint16_t) override {}
    void setTextWrap(bool) override     {}
    void setCursor(int16_t, int16_t) override {}
    void print(const char*) override    {}

    const uint8_t* buffer() const override { return _buf; }

private:
    uint8_t _buf[EPD_BUFFER_SIZE];
    void setPixel(int16_t x, int16_t y, EPDColour colour);
};
