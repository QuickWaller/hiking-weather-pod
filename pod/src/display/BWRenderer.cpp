#include "BWRenderer.h"
#include "CompassFrames.h"
#include <cmath>
#include <cstdint>

static constexpr float BWR_PI = 3.14159265f;

// Compass sits at top-centre of the 250×122 display.
static constexpr int CX = BW_WIDTH / 2;  // 125
static constexpr int CY = 38;
static constexpr int CR = 32;            // radius

void BWRenderer::renderCached(BWFramebuffer& fb, float headingDeg) {
    if (std::isnan(headingDeg)) { render(fb, headingDeg); return; }
    fb.loadRaw(COMPASS_FRAMES[compassIndex(headingDeg)]);
}

void BWRenderer::render(BWFramebuffer& fb, float headingDeg) {
    fb.fill(true);

    // Outer ring
    fb.drawCircle(CX, CY, CR);

    // Tick marks — long at cardinals (N/E/S/W), short at intermediates
    for (int d = 0; d < 360; d += 45) {
        float rad = d * BWR_PI / 180.0f;
        int   len = (d % 90 == 0) ? 7 : 4;
        int x0 = CX + (int)((CR - len) * sinf(rad));
        int y0 = CY - (int)((CR - len) * cosf(rad));
        int x1 = CX + (int)(CR         * sinf(rad));
        int y1 = CY - (int)(CR         * cosf(rad));
        fb.drawLine(x0, y0, x1, y1);
    }

    // Heading needle (only if valid)
    if (!std::isnan(headingDeg)) {
        float rad = headingDeg * BWR_PI / 180.0f;
        float s = sinf(rad), c = cosf(rad);

        // Forward needle — thick (3 adjacent lines)
        int nx = CX + (int)((CR - 6) * s);
        int ny = CY - (int)((CR - 6) * c);
        fb.drawLine(CX,   CY,   nx,   ny);
        fb.drawLine(CX+1, CY,   nx+1, ny);
        fb.drawLine(CX,   CY+1, nx,   ny+1);

        // Back stub
        int bx = CX - (int)((CR / 3) * s);
        int by = CY + (int)((CR / 3) * c);
        fb.drawLine(CX, CY, bx, by);
    }

    // Divider line below compass
    fb.drawLine(4, CY + CR + 8, BW_WIDTH - 4, CY + CR + 8);
}
