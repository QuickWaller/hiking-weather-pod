#include "CompassReader.h"
#include "AccelReader.h"
#include "algorithms/MathUtils.h"
#include "config.h"
#include <Wire.h>
#include <math.h>

#ifdef ARDUINO_ARCH_RP2040
  #define I2C_BUS Wire1
#else
  #define I2C_BUS Wire
#endif

static constexpr uint8_t REG_CONFIG_A = 0x00;
static constexpr uint8_t REG_CONFIG_B = 0x01;
static constexpr uint8_t REG_MODE     = 0x02;
static constexpr uint8_t REG_DATA     = 0x03;

bool CompassReader::begin() {
#ifdef ARDUINO_ARCH_RP2040
    I2C_BUS.setSDA(PIN_I2C_SDA);
    I2C_BUS.setSCL(PIN_I2C_SCL);
    I2C_BUS.begin();
#else
    I2C_BUS.begin(PIN_I2C_SDA, PIN_I2C_SCL);
#endif

    // 8 samples averaged, 15 Hz, normal measurement
    I2C_BUS.beginTransmission(I2C_ADDR_HMC5883L);
    I2C_BUS.write(REG_CONFIG_A);
    I2C_BUS.write(0x70);
    if (I2C_BUS.endTransmission() != 0) return false;

    // Gain ±1.3 Ga — 1090 LSB/Gauss
    I2C_BUS.beginTransmission(I2C_ADDR_HMC5883L);
    I2C_BUS.write(REG_CONFIG_B);
    I2C_BUS.write(0x20);
    I2C_BUS.endTransmission();

    // Continuous measurement mode
    I2C_BUS.beginTransmission(I2C_ADDR_HMC5883L);
    I2C_BUS.write(REG_MODE);
    I2C_BUS.write(0x00);
    I2C_BUS.endTransmission();

    return true;
}

CompassReading CompassReader::read() {
    I2C_BUS.beginTransmission(I2C_ADDR_HMC5883L);
    I2C_BUS.write(REG_DATA);
    if (I2C_BUS.endTransmission(false) != 0) return { 0, 0, 0, 0, false };

    // Register order: X_MSB, X_LSB, Z_MSB, Z_LSB, Y_MSB, Y_LSB
    I2C_BUS.requestFrom((uint8_t)I2C_ADDR_HMC5883L, (uint8_t)6);
    if (I2C_BUS.available() < 6) return { 0, 0, 0, 0, false };

    // Read each byte into its own variable: the operands of `|` are unsequenced,
    // so `read() << 8 | read()` could pull the LSB off the wire first.
    uint8_t xHi = I2C_BUS.read(), xLo = I2C_BUS.read();
    uint8_t zHi = I2C_BUS.read(), zLo = I2C_BUS.read();
    uint8_t yHi = I2C_BUS.read(), yLo = I2C_BUS.read();
    int16_t x = (int16_t)((xHi << 8) | xLo);
    int16_t z = (int16_t)((zHi << 8) | zLo);
    int16_t y = (int16_t)((yHi << 8) | yLo);

    // -4096 means overflow
    if (x == -4096 || y == -4096 || z == -4096) return { 0, x, y, z, false };

    float heading = atan2f((float)y, (float)x) * 180.0f / M_PI;
    if (heading < 0.0f) heading += 360.0f;

    return { heading, x, y, z, true };
}

float CompassReader::readTilted(const AccelReading& accel) {
    CompassReading mag = read();
    if (!mag.valid || !accel.valid) return -1.0f;

    // Remap accel into the compass frame before tilt comp — the two breakouts are
    // mounted yawed in-plane (ACCEL_YAW_QUADRANT in config.h). az passes through.
    float rx, ry;
    switch (ACCEL_YAW_QUADRANT) {
        case 1:  rx = -accel.ay; ry =  accel.ax; break;  // 90° CCW
        case 2:  rx = -accel.ax; ry = -accel.ay; break;  // 180°
        case 3:  rx =  accel.ay; ry = -accel.ax; break;  // 270° CCW
        default: rx =  accel.ax; ry =  accel.ay; break;  // 0°
    }

    return MathUtils::tiltCompensatedHeading(
        mag.rawX, mag.rawY, mag.rawZ,
        rx, ry, accel.az,
        COMPASS_HARD_IRON_OFFSET_X,
        COMPASS_HARD_IRON_OFFSET_Y,
        COMPASS_HARD_IRON_OFFSET_Z);
}
