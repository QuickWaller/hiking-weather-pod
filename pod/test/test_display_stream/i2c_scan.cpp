#ifdef I2C_SCAN
#include <Arduino.h>
#include <Wire.h>
#include "config.h"

void setup() {
    Serial.begin(115200);
    delay(500);
    Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
    Serial.printf("I2C scan on SDA=GPIO%d SCL=GPIO%d\n", PIN_I2C_SDA, PIN_I2C_SCL);

    int found = 0;
    for (uint8_t addr = 1; addr < 127; addr++) {
        Wire.beginTransmission(addr);
        uint8_t err = Wire.endTransmission();
        if (err == 0) {
            Serial.printf("  0x%02X — device found\n", addr);
            found++;
        }
    }
    if (found == 0) Serial.println("  no devices found");
    Serial.printf("scan complete (%d found)\n", found);
}

void loop() {}
#endif
