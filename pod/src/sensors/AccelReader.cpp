#include "AccelReader.h"
#include "config.h"
#include <Wire.h>

#ifdef ARDUINO_ARCH_RP2040
  #define I2C_BUS Wire1
#else
  #define I2C_BUS Wire
#endif

static constexpr uint8_t REG_PWR_MGMT  = 0x6B;
static constexpr uint8_t REG_ACCEL_CFG = 0x1C;
static constexpr uint8_t REG_GYRO_CFG  = 0x1B;
static constexpr uint8_t REG_ACCEL_OUT = 0x3B;

static constexpr float ACCEL_SCALE = 16384.0f;  // LSB/g at ±2g
static constexpr float GYRO_SCALE  = 131.0f;    // LSB/(°/s) at ±250°/s

bool AccelReader::begin() {
#ifdef ARDUINO_ARCH_RP2040
    I2C_BUS.setSDA(PIN_I2C_SDA);
    I2C_BUS.setSCL(PIN_I2C_SCL);
    I2C_BUS.begin();
#else
    I2C_BUS.begin(PIN_I2C_SDA, PIN_I2C_SCL);
#endif

    // Wake from sleep
    I2C_BUS.beginTransmission(I2C_ADDR_MPU6050);
    I2C_BUS.write(REG_PWR_MGMT);
    I2C_BUS.write(0x00);
    if (I2C_BUS.endTransmission() != 0) return false;

    // ±2g accel range
    I2C_BUS.beginTransmission(I2C_ADDR_MPU6050);
    I2C_BUS.write(REG_ACCEL_CFG);
    I2C_BUS.write(0x00);
    I2C_BUS.endTransmission();

    // ±250°/s gyro range
    I2C_BUS.beginTransmission(I2C_ADDR_MPU6050);
    I2C_BUS.write(REG_GYRO_CFG);
    I2C_BUS.write(0x00);
    I2C_BUS.endTransmission();

    return true;
}

AccelReading AccelReader::read() {
    I2C_BUS.beginTransmission(I2C_ADDR_MPU6050);
    I2C_BUS.write(REG_ACCEL_OUT);
    if (I2C_BUS.endTransmission(false) != 0) return {};

    // 14 bytes: accel XYZ (6) + temp (2) + gyro XYZ (6)
    I2C_BUS.requestFrom((uint8_t)I2C_ADDR_MPU6050, (uint8_t)14);
    if (I2C_BUS.available() < 14) return {};

    // Hi byte must be read before Lo; the operands of `|` are unsequenced, so a
    // single `read() << 8 | read()` expression could swap them. Sequence via locals.
    auto readWord = [&]() -> int16_t {
        uint8_t hi = I2C_BUS.read();
        uint8_t lo = I2C_BUS.read();
        return (int16_t)((hi << 8) | lo);
    };

    float ax = readWord() / ACCEL_SCALE;
    float ay = readWord() / ACCEL_SCALE;
    float az = readWord() / ACCEL_SCALE;
    readWord();  // temp (unused)
    float gx = readWord() / GYRO_SCALE;
    float gy = readWord() / GYRO_SCALE;
    float gz = readWord() / GYRO_SCALE;

    return { ax, ay, az, gx, gy, gz, true };
}
