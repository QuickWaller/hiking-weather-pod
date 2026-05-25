#include <Arduino.h>
#include <Fonts/FreeSansBold9pt7b.h>
#include "hal/ESP32DisplayHAL.h"
#include "display/EPD1in54G.h"
#include "display/Framebuffer.h"
#include "sprites/NijntjeWalkingCold.h"

static constexpr uint16_t SPRITE_AREA_H = 160;
static constexpr uint16_t BANNER_Y      = 160;
static constexpr uint16_t BANNER_H      =  40;

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

void setup() {
    Serial.begin(115200);
    hal.begin();
    epd.init();

    int16_t x = (EPD_WIDTH     - NijntjeWalkingCold_WIDTH)  / 2;
    int16_t y = (SPRITE_AREA_H - NijntjeWalkingCold_HEIGHT) / 2;
    fb.drawSprite(x, y, NijntjeWalkingCold, NijntjeWalkingCold_WIDTH, NijntjeWalkingCold_HEIGHT);

    fb.fillRect(0, BANNER_Y, EPD_WIDTH, BANNER_H, EPDColour::Red);
    fb.setFont(&FreeSansBold9pt7b);
    fb.setTextColor(EPD_GFX_WHITE);
    fb.setTextSize(1);
    fb.setTextWrap(false);

    int16_t x1, y1; uint16_t tw, th;

    fb.getTextBounds("STORM INBOUND", 0, 0, &x1, &y1, &tw, &th);
    fb.setCursor((EPD_WIDTH - tw) / 2, BANNER_Y + 16);
    fb.print("STORM INBOUND");

    fb.getTextBounds("80% 6 HOURS", 0, 0, &x1, &y1, &tw, &th);
    fb.setCursor((EPD_WIDTH - tw) / 2, BANNER_Y + 34);
    fb.print("80% 6 HOURS");

    fb.setFont(nullptr); // restore default font

    epd.display(fb.buffer());
    epd.sleep();
    Serial.println("Done.");
}

void loop() {}
