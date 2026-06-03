#include "BWFramebuffer.h"
#include <cstdlib>

void BWFramebuffer::setPixel(int x, int y, bool white) {
    if (x < 0 || x >= BW_WIDTH || y < 0 || y >= BW_HEIGHT) return;
    uint32_t idx = (uint32_t)y * BW_ROW_BYTES + x / 8;
    uint8_t  bit = 7 - (x % 8);
    if (white) _buf[idx] |=  (1u << bit);
    else       _buf[idx] &= ~(1u << bit);
}

void BWFramebuffer::drawLine(int x0, int y0, int x1, int y1, bool white) {
    int dx = abs(x1 - x0), sx = x0 < x1 ? 1 : -1;
    int dy = -abs(y1 - y0), sy = y0 < y1 ? 1 : -1;
    int err = dx + dy;
    for (;;) {
        setPixel(x0, y0, white);
        if (x0 == x1 && y0 == y1) break;
        int e2 = 2 * err;
        if (e2 >= dy) { err += dy; x0 += sx; }
        if (e2 <= dx) { err += dx; y0 += sy; }
    }
}

void BWFramebuffer::drawCircle(int cx, int cy, int r, bool white) {
    int x = r, y = 0, err = 0;
    while (x >= y) {
        setPixel(cx+x, cy+y, white); setPixel(cx+y, cy+x, white);
        setPixel(cx-y, cy+x, white); setPixel(cx-x, cy+y, white);
        setPixel(cx-x, cy-y, white); setPixel(cx-y, cy-x, white);
        setPixel(cx+y, cy-x, white); setPixel(cx+x, cy-y, white);
        if (err <= 0) { y++; err += 2*y + 1; }
        else          { x--; err -= 2*x + 1; }
    }
}
