#include "Bme280Reader.h"

#ifndef NATIVE_TEST

#include "config.h"
#include <Wire.h>
#include <Adafruit_BME280.h>

#ifdef ARDUINO_ARCH_RP2040
  #define I2C_BUS Wire1
#else
  #define I2C_BUS Wire
#endif

static Adafruit_BME280 bme;

bool Bme280Reader::begin() {
#ifdef ARDUINO_ARCH_RP2040
    I2C_BUS.setSDA(PIN_I2C_SDA);
    I2C_BUS.setSCL(PIN_I2C_SCL);
    I2C_BUS.begin();
#else
    I2C_BUS.begin(PIN_I2C_SDA, PIN_I2C_SCL);
#endif
    return bme.begin(I2C_ADDR_BME280, &I2C_BUS);
}

Bme280Reading Bme280Reader::read() {
    float p = bme.readPressure() / 100.0f;  // Pa → hPa
    float t = bme.readTemperature();
    float h = bme.readHumidity();
    if (p == 0.0f) return {0, 0, 0, false};
    return {p + BME280_PRESSURE_OFFSET_HPA, t, h, true};
}

#else  // native stub — not called in tests but needed for linking

bool Bme280Reader::begin() { return false; }
Bme280Reading Bme280Reader::read() { return {0, 0, 0, false}; }

#endif
