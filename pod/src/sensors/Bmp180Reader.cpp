#include "Bmp180Reader.h"
#include "config.h"
#include <Wire.h>
#include <Adafruit_BMP085.h>

#ifdef ARDUINO_ARCH_RP2040
  #define I2C_BUS Wire1
#else
  #define I2C_BUS Wire
#endif

static Adafruit_BMP085 bmp;

bool Bmp180Reader::begin() {
#ifdef ARDUINO_ARCH_RP2040
    I2C_BUS.setSDA(PIN_I2C_SDA);
    I2C_BUS.setSCL(PIN_I2C_SCL);
    I2C_BUS.begin();
#else
    I2C_BUS.begin(PIN_I2C_SDA, PIN_I2C_SCL);
#endif
    return bmp.begin(BMP085_ULTRAHIGHRES, &I2C_BUS);
}

Bmp180Reading Bmp180Reader::read() {
    float p = bmp.readPressure() / 100.0f;  // Pa → hPa
    float t = bmp.readTemperature();
    if (p == 0.0f) return { 0, 0, false };  // sentinel: check raw BEFORE offset
    return { p + BMP180_PRESSURE_OFFSET_HPA, t, true };
}
