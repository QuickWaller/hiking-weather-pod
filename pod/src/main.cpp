#include <Arduino.h>
#include "hal/ESP32DisplayHAL.h"
#include "display/EPD1in54G.h"
#include "display/Framebuffer.h"
#include "sprites/NijntjeWalking.h"

static constexpr uint16_t SPRITE_AREA_H = 160;
static constexpr uint16_t STATUS_BAR_Y  = 160;
static constexpr uint16_t STATUS_BAR_H  =  40;

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

    int16_t x = (EPD_WIDTH  - NijntjeWalking_WIDTH)  / 2;
    int16_t y = (SPRITE_AREA_H - NijntjeWalking_HEIGHT) / 2;
    fb.drawSprite(x, y, NijntjeWalking, NijntjeWalking_WIDTH, NijntjeWalking_HEIGHT);
    fb.fillRect(0, STATUS_BAR_Y, EPD_WIDTH, STATUS_BAR_H, EPDColour::Red);

    epd.display(fb.buffer());
    epd.sleep();
    Serial.println("Done.");
}

void loop() {}
