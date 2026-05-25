#include <Arduino.h>
#include "hal/ESP32DisplayHAL.h"
#include "display/EPD1in54G.h"
#include "display/Framebuffer.h"
#include "nijntje/NijntjeState.h"
#include "nijntje/NijntjeRenderer.h"

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

    NijntjeDisplay d;
    d.state    = NijntjeState::Climbing;
    d.modifier = NijntjeModifier::Cold;
    d.banner   = BannerState::Yellow;

    NijntjeRenderer::render(fb, d);
    epd.display(fb.buffer());
    epd.sleep();
    Serial.println("Done.");
}

void loop() {}
