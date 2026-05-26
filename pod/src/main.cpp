#include <Arduino.h>
#include <Fonts/FreeSansBold9pt7b.h>
#include "hal/ESP32DisplayHAL.h"
#include "display/EPD1in54G.h"
#include "display/Framebuffer.h"

#include "sprites/NijntjeWalking.h"
#include "sprites/NijntjeWalkingHot.h"
#include "sprites/NijntjeWalkingCold.h"
#include "sprites/NijntjeWalkingFoggy.h"
#include "sprites/NijntjeClimbing.h"
#include "sprites/NijntjeClimbingHot.h"
#include "sprites/NijntjeClimbingCold.h"
#include "sprites/NijntjeClimbingFoggy.h"
#include "sprites/NijntjeResting.h"
#include "sprites/NijntjeRestingHot.h"
#include "sprites/NijntjeRestingCold.h"
#include "sprites/NijntjeRestingFoggy.h"
#include "sprites/NijntjeSleepyEvening.h"
#include "sprites/NijntjeSleepingTent.h"
#include "sprites/NijntjeWalkingNight.h"
#include "sprites/NijntjeWorried.h"
#include "sprites/NijntjeConnected.h"

static constexpr uint16_t BANNER_Y = 160;
static constexpr uint16_t BANNER_H =  40;

static ESP32DisplayHAL hal(
    /* CS    */ 15,
    /* DC    */ 27,
    /* Reset */ 26,
    /* Busy  */ 25,
    /* SCK   */ 13,
    /* MOSI  */ 14
);
static EPD1in54G   epd(hal);
static Framebuffer fb;

// bannerColor: EPD_GFX_WHITE = activity label only
//              EPD_GFX_YELLOW/RED = weather alert (line1 + line2)
struct TestFrame {
    const uint8_t* sprite;
    uint16_t       w;
    uint16_t       h;
    const char*    activity;   // always shown on white banner
    const char*    line1;      // weather alert line 1 (null = white banner)
    const char*    line2;      // weather alert line 2
    uint16_t       bannerColor;
};

static const TestFrame frames[] = {
    { NijntjeWalking,       NijntjeWalking_WIDTH,       NijntjeWalking_HEIGHT,
      "WALKING",   nullptr,         nullptr,        EPD_GFX_WHITE  },
    { NijntjeWalkingHot,    NijntjeWalkingHot_WIDTH,    NijntjeWalkingHot_HEIGHT,
      "WALKING",   nullptr,         nullptr,        EPD_GFX_WHITE  },
    { NijntjeWalkingCold,   NijntjeWalkingCold_WIDTH,   NijntjeWalkingCold_HEIGHT,
      "WALKING",   nullptr,         nullptr,        EPD_GFX_WHITE  },
    { NijntjeWalkingFoggy,  NijntjeWalkingFoggy_WIDTH,  NijntjeWalkingFoggy_HEIGHT,
      "WALKING",   nullptr,         nullptr,        EPD_GFX_WHITE  },
    { NijntjeClimbing,      NijntjeClimbing_WIDTH,      NijntjeClimbing_HEIGHT,
      "CLIMBING",  nullptr,         nullptr,        EPD_GFX_WHITE  },
    { NijntjeClimbingHot,   NijntjeClimbingHot_WIDTH,   NijntjeClimbingHot_HEIGHT,
      "CLIMBING",  nullptr,         nullptr,        EPD_GFX_WHITE  },
    { NijntjeClimbingCold,  NijntjeClimbingCold_WIDTH,  NijntjeClimbingCold_HEIGHT,
      "CLIMBING",  nullptr,         nullptr,        EPD_GFX_WHITE  },
    { NijntjeClimbingFoggy, NijntjeClimbingFoggy_WIDTH, NijntjeClimbingFoggy_HEIGHT,
      "CLIMBING",  nullptr,         nullptr,        EPD_GFX_WHITE  },
    { NijntjeResting,       NijntjeResting_WIDTH,       NijntjeResting_HEIGHT,
      "RESTING",   nullptr,         nullptr,        EPD_GFX_WHITE  },
    { NijntjeRestingHot,    NijntjeRestingHot_WIDTH,    NijntjeRestingHot_HEIGHT,
      "RESTING",   nullptr,         nullptr,        EPD_GFX_WHITE  },
    { NijntjeRestingCold,   NijntjeRestingCold_WIDTH,   NijntjeRestingCold_HEIGHT,
      "RESTING",   nullptr,         nullptr,        EPD_GFX_WHITE  },
    { NijntjeRestingFoggy,  NijntjeRestingFoggy_WIDTH,  NijntjeRestingFoggy_HEIGHT,
      "RESTING",   nullptr,         nullptr,        EPD_GFX_WHITE  },
    { NijntjeSleepyEvening, NijntjeSleepyEvening_WIDTH, NijntjeSleepyEvening_HEIGHT,
      "SLEEPING",  nullptr,         nullptr,        EPD_GFX_WHITE  },
    { NijntjeSleepingTent,  NijntjeSleepingTent_WIDTH,  NijntjeSleepingTent_HEIGHT,
      "SLEEPING",  nullptr,         nullptr,        EPD_GFX_WHITE  },
    { NijntjeWalkingNight,  NijntjeWalkingNight_WIDTH,  NijntjeWalkingNight_HEIGHT,
      "WALKING",   nullptr,         nullptr,        EPD_GFX_WHITE  },
    { NijntjeWorried,       NijntjeWorried_WIDTH,       NijntjeWorried_HEIGHT,
      "WALKING",   "STORM INBOUND", "80% 6 HOURS",  EPD_GFX_RED    },
    { NijntjeConnected,     NijntjeConnected_WIDTH,     NijntjeConnected_HEIGHT,
      "CONNECTED", "SYNCING",       "CYBERDECK",    EPD_GFX_YELLOW },
};
static constexpr int NUM_FRAMES = sizeof(frames) / sizeof(frames[0]);

static void showFrame(const TestFrame& f) {
    fb.fill(EPDColour::White);

    // sprites are exactly 220×160 — centre horizontally, sit flush at top
    int16_t x = (EPD_WIDTH - f.w) / 2;
    fb.drawSprite(x, 0, f.sprite, f.w, f.h);

    fb.setFont(&FreeSansBold9pt7b);
    fb.setTextSize(1);
    fb.setTextWrap(false);

    int16_t x1, y1; uint16_t tw, th;

    if (f.bannerColor == EPD_GFX_WHITE) {
        fb.fillRect(0, BANNER_Y, EPD_WIDTH, BANNER_H, EPDColour::White);
        fb.setTextColor(EPD_GFX_BLACK);
        fb.getTextBounds(f.activity, 0, 0, &x1, &y1, &tw, &th);
        fb.setCursor((EPD_WIDTH - tw) / 2, BANNER_Y + 26);
        fb.print(f.activity);
    } else {
        EPDColour bc = (f.bannerColor == EPD_GFX_RED) ? EPDColour::Red : EPDColour::Yellow;
        fb.fillRect(0, BANNER_Y, EPD_WIDTH, BANNER_H, bc);
        fb.setTextColor(f.bannerColor == EPD_GFX_RED ? EPD_GFX_WHITE : EPD_GFX_BLACK);
        if (f.line1) {
            fb.getTextBounds(f.line1, 0, 0, &x1, &y1, &tw, &th);
            fb.setCursor((EPD_WIDTH - tw) / 2, BANNER_Y + 16);
            fb.print(f.line1);
        }
        if (f.line2) {
            fb.getTextBounds(f.line2, 0, 0, &x1, &y1, &tw, &th);
            fb.setCursor((EPD_WIDTH - tw) / 2, BANNER_Y + 34);
            fb.print(f.line2);
        }
    }

    fb.setFont(nullptr);
    epd.display(fb.buffer());
}

void setup() {
    Serial.begin(115200);
    hal.begin();
    epd.init();
}

static int currentFrame = 0;

void loop() {
    Serial.printf("Frame %d/%d — %s\n", currentFrame + 1, NUM_FRAMES, frames[currentFrame].activity);
    showFrame(frames[currentFrame]);
    currentFrame = (currentFrame + 1) % NUM_FRAMES;
    delay(5000);
}
