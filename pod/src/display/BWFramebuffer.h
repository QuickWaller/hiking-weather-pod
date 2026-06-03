#pragma once
#include <stdint.h>
#include <cstring>

static constexpr uint16_t BW_WIDTH     = 250;
static constexpr uint16_t BW_HEIGHT    = 122;
static constexpr uint16_t BW_ROW_BYTES = (BW_WIDTH + 7) / 8;   // 32
static constexpr uint32_t BW_BUF_SIZE  = BW_ROW_BYTES * BW_HEIGHT; // 3904

// 1bpp packed framebuffer for the 2.13" B/W e-ink panel.
// MSB = leftmost pixel in each byte. White = 1, Black = 0.
class BWFramebuffer {
public:
    BWFramebuffer() { fill(true); }

    void fill(bool white) { memset(_buf, white ? 0xFF : 0x00, BW_BUF_SIZE); }
    void setPixel(int x, int y, bool white);
    void drawLine(int x0, int y0, int x1, int y1, bool white = false);
    void drawCircle(int cx, int cy, int r, bool white = false);

    void loadRaw(const uint8_t* src) { memcpy(_buf, src, BW_BUF_SIZE); }
    const uint8_t* buffer() const { return _buf; }

private:
    uint8_t _buf[BW_BUF_SIZE];
};
