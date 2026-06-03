#include "Aht10Reader.h"
#include "config.h"
#include <Wire.h>
#include <Arduino.h>

#ifdef ARDUINO_ARCH_RP2040
  #define I2C_BUS Wire1
#else
  #define I2C_BUS Wire
#endif

static constexpr uint8_t CMD_INIT[]    = { 0xE1, 0x08, 0x00 };
static constexpr uint8_t CMD_TRIGGER[] = { 0xAC, 0x33, 0x00 };
static constexpr uint8_t CMD_RESET     = 0xBA;

bool Aht10Reader::begin() {
#ifdef ARDUINO_ARCH_RP2040
    I2C_BUS.setSDA(PIN_I2C_SDA);
    I2C_BUS.setSCL(PIN_I2C_SCL);
    I2C_BUS.begin();
#else
    I2C_BUS.begin(PIN_I2C_SDA, PIN_I2C_SCL);
#endif

    // Soft reset
    I2C_BUS.beginTransmission(I2C_ADDR_AHT10);
    I2C_BUS.write(CMD_RESET);
    if (I2C_BUS.endTransmission() != 0) return false;
    delay(20);

    // Init
    I2C_BUS.beginTransmission(I2C_ADDR_AHT10);
    I2C_BUS.write(CMD_INIT, 3);
    I2C_BUS.endTransmission();
    delay(10);

    return true;
}

Aht10Reading Aht10Reader::read() {
    // Trigger measurement
    I2C_BUS.beginTransmission(I2C_ADDR_AHT10);
    I2C_BUS.write(CMD_TRIGGER, 3);
    if (I2C_BUS.endTransmission() != 0) return { 0, 0, false };
    delay(80);

    // Read 6 bytes
    I2C_BUS.requestFrom((uint8_t)I2C_ADDR_AHT10, (uint8_t)6);
    if (I2C_BUS.available() < 6) return { 0, 0, false };

    uint8_t d[6];
    for (auto& b : d) b = I2C_BUS.read();

    if (d[0] & 0x80) return { 0, 0, false };  // busy

    uint32_t rawHum  = ((uint32_t)d[1] << 12) | ((uint32_t)d[2] << 4) | (d[3] >> 4);
    uint32_t rawTemp = (((uint32_t)d[3] & 0x0F) << 16) | ((uint32_t)d[4] << 8) | d[5];

    float humidity = (float)rawHum  / 1048576.0f * 100.0f;
    float tempC    = (float)rawTemp / 1048576.0f * 200.0f - 50.0f;

    return { tempC, humidity, true };
}
