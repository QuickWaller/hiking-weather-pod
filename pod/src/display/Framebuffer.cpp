#include "Framebuffer.h"
#include <string.h>

Framebuffer::Framebuffer() : Adafruit_GFX(EPD_WIDTH, EPD_HEIGHT) {
    fill(EPDColour::White);
}

void Framebuffer::drawPixel(int16_t x, int16_t y, uint16_t color) {
    EPDColour c;
    if      (color == EPD_GFX_BLACK)  c = EPDColour::Black;
    else if (color == EPD_GFX_YELLOW) c = EPDColour::Yellow;
    else if (color == EPD_GFX_RED)    c = EPDColour::Red;
    else                              c = EPDColour::White;
    setPixel(x, y, c);
}

void Framebuffer::setPixel(int16_t x, int16_t y, EPDColour colour) {
    if (x < 0 || x >= EPD_WIDTH || y < 0 || y >= EPD_HEIGHT) return;
    uint32_t idx   = (y * EPD_WIDTH + x) / 4;
    uint8_t  shift = (3 - (x % 4)) * 2;
    _buf[idx] = (_buf[idx] & ~(0x3 << shift)) | (static_cast<uint8_t>(colour) << shift);
}

void Framebuffer::fill(EPDColour colour) {
    uint8_t c    = static_cast<uint8_t>(colour);
    uint8_t fill = (c << 6) | (c << 4) | (c << 2) | c;
    memset(_buf, fill, EPD_BUFFER_SIZE);
}

void Framebuffer::fillRect(int16_t x, int16_t y, int16_t w, int16_t h, EPDColour colour) {
    for (int16_t row = y; row < y + h; row++)
        for (int16_t col = x; col < x + w; col++)
            setPixel(col, row, colour);
}

void Framebuffer::drawSprite(int16_t x, int16_t y, const uint8_t* sprite, uint16_t sw, uint16_t sh) {
    uint16_t rowBytes = (sw + 3) / 4;
    for (uint16_t row = 0; row < sh; row++) {
        for (uint16_t col = 0; col < sw; col++) {
            uint32_t idx   = row * rowBytes + col / 4;
            uint8_t  shift = (3 - (col % 4)) * 2;
            uint8_t  code  = (sprite[idx] >> shift) & 0x3;
            setPixel(x + col, y + row, static_cast<EPDColour>(code));
        }
    }
}
