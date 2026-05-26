#include "NijntjeRenderer.h"
#include "display/Framebuffer.h"
#include <string.h>

static constexpr int16_t SPRITE_AREA_H = 160;
static constexpr int16_t BANNER_Y      = 160;
static constexpr int16_t BANNER_H      =  40;

static const char* stateLabel(NijntjeState s) {
    switch (s) {
        case NijntjeState::Walking:      return "WALKING";
        case NijntjeState::WalkingNight: return "NIGHT";
        case NijntjeState::Climbing:     return "CLIMBING";
        case NijntjeState::Resting:      return "RESTING";
        case NijntjeState::SleepyEvening:return "SLEEPY";
        case NijntjeState::SleepingTent: return "SLEEPING";
        case NijntjeState::Worried:      return "WORRIED";
        case NijntjeState::Connected:    return "CONNECTED";
        default:                         return "?";
    }
}

static const char* modifierLabel(NijntjeModifier m) {
    switch (m) {
        case NijntjeModifier::Hot:   return "HOT";
        case NijntjeModifier::Cold:  return "COLD";
        case NijntjeModifier::Foggy: return "FOGGY";
        default:                     return nullptr;
    }
}

// Centre a string horizontally. At textSize 2, each char is 12px wide.
static int16_t centreX(const char* str, uint8_t textSize) {
    return (EPD_WIDTH - (int16_t)(strlen(str) * 6 * textSize)) / 2;
}

void NijntjeRenderer::render(Framebuffer& fb, const NijntjeDisplay& d) {
    fb.fill(EPDColour::White);

    const char* state = stateLabel(d.state);
    const char* mod   = modifierLabel(d.modifier);

    fb.setTextSize(2);
    fb.setTextColor(EPD_GFX_BLACK);
    fb.setTextWrap(false);

    if (mod) {
        // Two lines: centre both vertically together (each line 16px, 4px gap)
        int16_t blockTop = (SPRITE_AREA_H - 36) / 2;
        fb.setCursor(centreX(state, 2), blockTop);
        fb.print(state);
        fb.setCursor(centreX(mod, 2), blockTop + 20);
        fb.print(mod);
    } else {
        int16_t y = (SPRITE_AREA_H - 16) / 2;
        fb.setCursor(centreX(state, 2), y);
        fb.print(state);
    }

    // Banner
    EPDColour     bannerColour = EPDColour::White;
    const char*   bannerText   = nullptr;
    uint16_t      bannerTextColour = EPD_GFX_BLACK;

    switch (d.banner) {
        case BannerState::Yellow:
            bannerColour     = EPDColour::Yellow;
            bannerText       = "RAIN POSSIBLE";
            bannerTextColour = EPD_GFX_BLACK;
            break;
        case BannerState::Red:
            bannerColour     = EPDColour::Red;
            bannerText       = "STORM WARNING";
            bannerTextColour = EPD_GFX_WHITE;
            break;
        default: break;
    }

    fb.fillRect(0, BANNER_Y, EPD_WIDTH, BANNER_H, bannerColour);

    if (bannerText) {
        fb.setTextSize(1);
        fb.setTextColor(bannerTextColour);
        // At size 1: chars are 8px tall, centre in 40px banner
        fb.setCursor(centreX(bannerText, 1), BANNER_Y + (BANNER_H - 8) / 2);
        fb.print(bannerText);
    }
}
