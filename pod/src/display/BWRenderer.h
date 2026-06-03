#pragma once
#include "BWFramebuffer.h"
#include <cmath>

namespace BWRenderer {
    // heading: degrees 0–360, 0 = North. NaN = unknown (draws empty circle).
    void render(BWFramebuffer& fb, float headingDeg);

    // Look up a pre-baked frame (16 positions, 22.5° each). Falls back to
    // render() for NaN so callers don't need to special-case the unknown case.
    void renderCached(BWFramebuffer& fb, float headingDeg);

    // Map a heading to the nearest of 16 indices (0 = North, 1 = NNE, …).
    // Each bucket spans ±11.25° (= 360/32). Wraps correctly at 360°.
    inline int compassIndex(float headingDeg) {
        int i = static_cast<int>(roundf(headingDeg / 22.5f)) % 16;
        return i < 0 ? i + 16 : i;
    }
}
