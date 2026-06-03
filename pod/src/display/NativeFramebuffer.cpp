#include "NativeFramebuffer.h"
#include <cstring>

NativeFramebuffer::NativeFramebuffer() {
    fill(EPDColour::White);
}

void NativeFramebuffer::setPixel(int16_t x, int16_t y, EPDColour colour) {
    if (x < 0 || x >= EPD_WIDTH || y < 0 || y >= EPD_HEIGHT) return;
    uint32_t idx   = ((uint32_t)y * EPD_WIDTH + x) / 4;
    uint8_t  shift = (3 - (x % 4)) * 2;
    _buf[idx] = (_buf[idx] & ~(0x3 << shift)) | (static_cast<uint8_t>(colour) << shift);
}

void NativeFramebuffer::fill(EPDColour colour) {
    uint8_t c = static_cast<uint8_t>(colour);
    uint8_t v = (c << 6) | (c << 4) | (c << 2) | c;
    memset(_buf, v, EPD_BUFFER_SIZE);
}

void NativeFramebuffer::fillRect(int16_t x, int16_t y, int16_t w, int16_t h, EPDColour colour) {
    for (int16_t row = y; row < y + h; row++)
        for (int16_t col = x; col < x + w; col++)
            setPixel(col, row, colour);
}

void NativeFramebuffer::drawSprite(int16_t x, int16_t y, const uint8_t* data, uint16_t w, uint16_t h) {
    uint16_t rowBytes = (w + 3) / 4;
    for (uint16_t row = 0; row < h; row++) {
        for (uint16_t col = 0; col < w; col++) {
            uint32_t idx   = (uint32_t)row * rowBytes + col / 4;
            uint8_t  shift = (3 - (col % 4)) * 2;
            uint8_t  code  = (data[idx] >> shift) & 0x3;
            setPixel(x + (int16_t)col, y + (int16_t)row, static_cast<EPDColour>(code));
        }
    }
}
