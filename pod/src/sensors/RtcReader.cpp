#include "RtcReader.h"
#include "config.h"
#include "debug.h"
#include "algorithms/MathUtils.h"
#include <Wire.h>
#include <Arduino.h>

#ifdef ARDUINO_ARCH_RP2040
  #define I2C_BUS Wire1
#else
  #define I2C_BUS Wire
#endif

static constexpr uint8_t REG_SECONDS  = 0x00;
static constexpr uint8_t REG_ALM2_MIN = 0x0B;
static constexpr uint8_t REG_CONTROL  = 0x0E;
static constexpr uint8_t REG_STATUS   = 0x0F;

static uint8_t readReg(uint8_t reg) {
    I2C_BUS.beginTransmission(I2C_ADDR_DS3231);
    I2C_BUS.write(reg);
    I2C_BUS.endTransmission(false);
    I2C_BUS.requestFrom((uint8_t)I2C_ADDR_DS3231, (uint8_t)1);
    return I2C_BUS.available() ? I2C_BUS.read() : 0;
}

static void writeReg(uint8_t reg, uint8_t val) {
    I2C_BUS.beginTransmission(I2C_ADDR_DS3231);
    I2C_BUS.write(reg);
    I2C_BUS.write(val);
    I2C_BUS.endTransmission();
}

void RtcReader::begin() {
#ifdef ARDUINO_ARCH_RP2040
    I2C_BUS.setSDA(PIN_I2C_SDA);
    I2C_BUS.setSCL(PIN_I2C_SCL);
    I2C_BUS.begin();
#else
    I2C_BUS.begin(PIN_I2C_SDA, PIN_I2C_SCL);
#endif

    // Alarm 2 every minute: A2M2=A2M3=A2M4=1 (all mask bits set)
    writeReg(REG_ALM2_MIN,     0x80);  // minutes
    writeReg(REG_ALM2_MIN + 1, 0x80);  // hours
    writeReg(REG_ALM2_MIN + 2, 0x80);  // day/date

    // INTCN=1 (interrupt mode), A2IE=1 (alarm 2 interrupt enable)
    writeReg(REG_CONTROL, 0x06);

    clearAlarm();
    pinMode(PIN_RTC_SQW, INPUT_PULLUP);
}

RtcTime RtcReader::now() {
    I2C_BUS.beginTransmission(I2C_ADDR_DS3231);
    I2C_BUS.write(REG_SECONDS);
    I2C_BUS.endTransmission(false);
    I2C_BUS.requestFrom((uint8_t)I2C_ADDR_DS3231, (uint8_t)7);

    uint8_t  sec   = bcdToDec(I2C_BUS.read() & 0x7F);
    uint8_t  min   = bcdToDec(I2C_BUS.read() & 0x7F);
    uint8_t  hour  = bcdToDec(I2C_BUS.read() & 0x3F);
    I2C_BUS.read();  // day-of-week (unused)
    uint8_t  day   = bcdToDec(I2C_BUS.read() & 0x3F);
    uint8_t  month = bcdToDec(I2C_BUS.read() & 0x1F);
    uint16_t year  = bcdToDec(I2C_BUS.read()) + 2000;

    // DS3231 registers hold UTC (set from GPS UTC). unixTime stays UTC — the
    // canonical absolute time for skew checks, staleness and logging. The civil
    // fields are converted to NZ local so all time-of-day logic reads local.
    uint32_t utc = MathUtils::unixFromDateTime(year, month, day, hour, min, sec);

    RtcTime t;
    t.unixTime = utc;
    int offsetMin = MathUtils::nzUtcOffsetMinutes(utc);  // NZST/NZDT, DST-aware
    uint32_t local = utc + (uint32_t)(offsetMin * 60);
    MathUtils::dateTimeFromUnix(local, t.year, t.month, t.day,
                                t.hour, t.minute, t.second);
    LOG("RTC now (local) %04u-%02u-%02u %02u:%02u:%02u utc_unix=%lu",
        t.year, t.month, t.day, t.hour, t.minute, t.second, t.unixTime);
    return t;
}

void RtcReader::setTime(uint32_t unix) {
    uint16_t year; uint8_t month, day, hour, minute, second;
    MathUtils::dateTimeFromUnix(unix, year, month, day, hour, minute, second);

    I2C_BUS.beginTransmission(I2C_ADDR_DS3231);
    I2C_BUS.write(REG_SECONDS);
    I2C_BUS.write(decToBcd(second));
    I2C_BUS.write(decToBcd(minute));
    I2C_BUS.write(decToBcd(hour));
    I2C_BUS.write(0x01);  // day-of-week (unused)
    I2C_BUS.write(decToBcd(day));
    I2C_BUS.write(decToBcd(month));
    I2C_BUS.write(decToBcd((uint8_t)(year - 2000)));
    I2C_BUS.endTransmission();
    LOG("RTC set unix=%lu", unix);
}

void RtcReader::clearAlarm() {
    uint8_t status = readReg(REG_STATUS);
    writeReg(REG_STATUS, status & ~0x02);  // clear A2F bit
    LOG("RTC alarm cleared");
}

bool RtcReader::alarmFired() {
    bool fired = (readReg(REG_STATUS) & 0x02) != 0;
    LOG("RTC alarmFired=%d", fired);
    return fired;
}

uint8_t RtcReader::bcdToDec(uint8_t val) {
    return (val >> 4) * 10 + (val & 0x0F);
}

uint8_t RtcReader::decToBcd(uint8_t val) {
    return ((val / 10) << 4) | (val % 10);
}
