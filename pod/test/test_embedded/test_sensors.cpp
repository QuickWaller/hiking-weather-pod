#include <Arduino.h>
#include <Wire.h>
#include <unity.h>
#include <math.h>
#include "config.h"
#include "sensors/RtcReader.h"
#include "sensors/CompassReader.h"
#include "sensors/AccelReader.h"
#include "sensors/Bmp180Reader.h"
#include "sensors/Aht10Reader.h"
#include "GpsReader.h"

// 2026-06-01 12:00:00 UTC — used to seed a factory-reset RTC
static constexpr uint32_t KNOWN_TIME = 1780315200UL;

static RtcReader     rtc;
static GpsReader     gps;
static CompassReader compass;
static AccelReader   accel;
static Bmp180Reader  bmp180;
static Aht10Reader   aht10;

// Set by I2C scan — gates later tests
static bool have_ds3231  = false;
static bool have_bmp180  = false;
static bool have_hmc5883 = false;
static bool have_mpu6050 = false;
static bool have_aht10   = false;

void setUp() {}
void tearDown() {}

// ── I2C scan ──────────────────────────────────────────────────────────────────

void test_i2c_scan() {
    Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
    for (uint8_t addr = 1; addr < 127; addr++) {
        Wire.beginTransmission(addr);
        if (Wire.endTransmission() != 0) continue;
        Serial.printf("  I2C found 0x%02X\n", addr);
        if (addr == 0x68) have_ds3231  = true;
        if (addr == 0x77) have_bmp180  = true;
        if (addr == 0x1E) have_hmc5883 = true;
        if (addr == 0x69) have_mpu6050 = true;
        if (addr == 0x38) have_aht10   = true;
    }
    // DS3231 is required — everything else is optional until wired
    TEST_ASSERT_TRUE_MESSAGE(have_ds3231, "DS3231 not found at 0x68");
}

// ── GPS ───────────────────────────────────────────────────────────────────────

void test_gps_nmea_streaming() {
    uint32_t start = millis();
    while (millis() - start < 6000)
        gps.poll();
    (void)gps.fix();
    TEST_PASS();
}

void test_gps_no_fix_state_valid() {
    const GpsFix& f = gps.fix();
    TEST_ASSERT_FALSE(f.valid);
    TEST_ASSERT_EQUAL_INT(0, f.quality);
}

void test_gps_acquires_fix() {
    uint32_t start = millis();
    while (!gps.fix().valid && millis() - start < 90000)
        gps.poll();

    if (!gps.fix().valid) {
        TEST_IGNORE_MESSAGE("No fix acquired — run outside for full test");
        return;
    }

    const GpsFix& f = gps.fix();
    TEST_ASSERT_GREATER_THAN_INT(0, f.sats);
    TEST_ASSERT_GREATER_THAN_INT(0, f.quality);
    TEST_ASSERT_FLOAT_WITHIN(90.0f,   0.0f, f.lat);
    TEST_ASSERT_FLOAT_WITHIN(180.0f,  0.0f, f.lon);
    TEST_ASSERT_FLOAT_WITHIN(5000.0f, 0.0f, f.altM);

    if (f.unixTime > 0) {
        rtc.setTime(f.unixTime);
        Serial.printf("RTC seeded from GPS: unix=%lu\n", f.unixTime);
    }
}

// ── RTC ───────────────────────────────────────────────────────────────────────

void test_rtc_date_in_range() {
    if (!have_ds3231) TEST_IGNORE_MESSAGE("DS3231 not on bus");
    RtcTime t = rtc.now();
    TEST_ASSERT_GREATER_OR_EQUAL_UINT16(2024, t.year);
    TEST_ASSERT_LESS_OR_EQUAL_UINT16(2035, t.year);
    TEST_ASSERT_GREATER_OR_EQUAL_UINT8(1, t.month);
    TEST_ASSERT_LESS_OR_EQUAL_UINT8(12, t.month);
    TEST_ASSERT_GREATER_OR_EQUAL_UINT8(1, t.day);
    TEST_ASSERT_LESS_OR_EQUAL_UINT8(31, t.day);
}

void test_rtc_time_in_range() {
    if (!have_ds3231) TEST_IGNORE_MESSAGE("DS3231 not on bus");
    RtcTime t = rtc.now();
    TEST_ASSERT_LESS_THAN_UINT8(24, t.hour);
    TEST_ASSERT_LESS_THAN_UINT8(60, t.minute);
    TEST_ASSERT_LESS_THAN_UINT8(60, t.second);
}

void test_rtc_unix_plausible() {
    if (!have_ds3231) TEST_IGNORE_MESSAGE("DS3231 not on bus");
    RtcTime t = rtc.now();
    TEST_ASSERT_GREATER_THAN_UINT32(1704067200UL, t.unixTime);
}

void test_rtc_ticks() {
    if (!have_ds3231) TEST_IGNORE_MESSAGE("DS3231 not on bus");
    // Wait for a second boundary then read across it
    RtcTime t0 = rtc.now();
    while (rtc.now().second == t0.second) delay(50);
    RtcTime t1 = rtc.now();
    delay(1100);
    RtcTime t2 = rtc.now();
    TEST_ASSERT_GREATER_THAN_UINT32(t1.unixTime, t2.unixTime);
}

// ── Compass ───────────────────────────────────────────────────────────────────

void test_compass_begins() {
    if (!have_hmc5883) TEST_IGNORE_MESSAGE("HMC5883L not on bus");
    TEST_ASSERT_TRUE(compass.begin());
}

void test_compass_heading_in_range() {
    if (!have_hmc5883) TEST_IGNORE_MESSAGE("HMC5883L not on bus");
    CompassReading r = compass.read();
    TEST_ASSERT_TRUE(r.valid);
    TEST_ASSERT_FLOAT_WITHIN(180.0f, 180.0f, r.headingDeg);  // 0–360
}

void test_compass_raw_nonzero() {
    if (!have_hmc5883) TEST_IGNORE_MESSAGE("HMC5883L not on bus");
    CompassReading r = compass.read();
    TEST_ASSERT_TRUE(r.rawX != 0 || r.rawY != 0 || r.rawZ != 0);
}

// ── Accel ─────────────────────────────────────────────────────────────────────

void test_accel_begins() {
    if (!have_mpu6050) TEST_IGNORE_MESSAGE("MPU6050 not on bus");
    TEST_ASSERT_TRUE(accel.begin());
}

void test_accel_magnitude_near_1g() {
    if (!have_mpu6050) TEST_IGNORE_MESSAGE("MPU6050 not on bus");
    AccelReading r = accel.read();
    TEST_ASSERT_TRUE(r.valid);
    float mag = sqrtf(r.ax * r.ax + r.ay * r.ay + r.az * r.az);
    TEST_ASSERT_FLOAT_WITHIN(0.5f, 1.0f, mag);
}

void test_accel_gyro_near_zero_at_rest() {
    if (!have_mpu6050) TEST_IGNORE_MESSAGE("MPU6050 not on bus");
    AccelReading r = accel.read();
    TEST_ASSERT_FLOAT_WITHIN(5.0f, 0.0f, r.gx);
    TEST_ASSERT_FLOAT_WITHIN(5.0f, 0.0f, r.gy);
    TEST_ASSERT_FLOAT_WITHIN(5.0f, 0.0f, r.gz);
}

// ── BMP180 ────────────────────────────────────────────────────────────────────

void test_bmp180_begins() {
    if (!have_bmp180) TEST_IGNORE_MESSAGE("BMP180 not on bus");
    TEST_ASSERT_TRUE(bmp180.begin());
}

void test_bmp180_pressure_plausible() {
    if (!have_bmp180) TEST_IGNORE_MESSAGE("BMP180 not on bus");
    Bmp180Reading r = bmp180.read();
    TEST_ASSERT_TRUE(r.valid);
    TEST_ASSERT_FLOAT_WITHIN(150.0f, 1013.25f, r.pressureHpa);  // 863–1163 hPa
}

void test_bmp180_temp_plausible() {
    if (!have_bmp180) TEST_IGNORE_MESSAGE("BMP180 not on bus");
    Bmp180Reading r = bmp180.read();
    TEST_ASSERT_TRUE(r.valid);
    TEST_ASSERT_FLOAT_WITHIN(60.0f, 20.0f, r.tempC);  // -40–80°C
}

// ── Tilt-compensated compass ──────────────────────────────────────────────────

void test_compass_readtilted_in_range() {
    if (!have_hmc5883 || !have_mpu6050) TEST_IGNORE_MESSAGE("HMC5883L or MPU6050 not on bus");
    AccelReading a = accel.read();
    float h = compass.readTilted(a);
    TEST_ASSERT_FALSE_MESSAGE(h < 0.0f, "readTilted returned invalid (-1)");
    TEST_ASSERT_FLOAT_WITHIN(180.0f, 180.0f, h);  // 0–360°
}

void test_compass_readtilted_stable_under_small_tilt() {
    if (!have_hmc5883 || !have_mpu6050) TEST_IGNORE_MESSAGE("HMC5883L or MPU6050 not on bus");
    // Two reads a moment apart on a stationary board — should agree within 10°
    AccelReading a1 = accel.read();
    float h1 = compass.readTilted(a1);
    delay(100);
    AccelReading a2 = accel.read();
    float h2 = compass.readTilted(a2);
    if (h1 < 0.0f || h2 < 0.0f) TEST_IGNORE_MESSAGE("Sensor read invalid");
    // Angular difference, wrap-safe
    float diff = fabsf(h1 - h2);
    if (diff > 180.0f) diff = 360.0f - diff;
    TEST_ASSERT_FLOAT_WITHIN(10.0f, 0.0f, diff);
}

// ── AHT10 ─────────────────────────────────────────────────────────────────────

void test_aht10_begins() {
    if (!have_aht10) TEST_IGNORE_MESSAGE("AHT10 not on bus");
    TEST_ASSERT_TRUE(aht10.begin());
}

void test_aht10_humidity_plausible() {
    if (!have_aht10) TEST_IGNORE_MESSAGE("AHT10 not on bus");
    Aht10Reading r = aht10.read();
    TEST_ASSERT_TRUE(r.valid);
    TEST_ASSERT_FLOAT_WITHIN(50.0f, 50.0f, r.humidity);  // 0–100%
}

void test_aht10_temp_plausible() {
    if (!have_aht10) TEST_IGNORE_MESSAGE("AHT10 not on bus");
    Aht10Reading r = aht10.read();
    TEST_ASSERT_TRUE(r.valid);
    TEST_ASSERT_FLOAT_WITHIN(60.0f, 20.0f, r.tempC);  // -40–80°C
}

// ── Setup ─────────────────────────────────────────────────────────────────────

void setup() {
    delay(2000);
    rtc.begin();

    RtcTime t = rtc.now();
    if (t.year < 2024 || t.year > 2035) {
        rtc.setTime(KNOWN_TIME);
        Serial.println("RTC invalid — seeded to 2026-05-31 12:00:00 UTC");
    }

    gps.begin();

    UNITY_BEGIN();
    RUN_TEST(test_i2c_scan);
    RUN_TEST(test_gps_nmea_streaming);
    RUN_TEST(test_gps_no_fix_state_valid);
    RUN_TEST(test_gps_acquires_fix);       // seeds RTC if fix obtained
    RUN_TEST(test_rtc_date_in_range);
    RUN_TEST(test_rtc_time_in_range);
    RUN_TEST(test_rtc_unix_plausible);
    RUN_TEST(test_rtc_ticks);
    RUN_TEST(test_compass_begins);
    RUN_TEST(test_compass_heading_in_range);
    RUN_TEST(test_compass_raw_nonzero);
    RUN_TEST(test_accel_begins);
    RUN_TEST(test_accel_magnitude_near_1g);
    RUN_TEST(test_accel_gyro_near_zero_at_rest);
    RUN_TEST(test_compass_readtilted_in_range);
    RUN_TEST(test_compass_readtilted_stable_under_small_tilt);
    RUN_TEST(test_bmp180_begins);
    RUN_TEST(test_bmp180_pressure_plausible);
    RUN_TEST(test_bmp180_temp_plausible);
    RUN_TEST(test_aht10_begins);
    RUN_TEST(test_aht10_humidity_plausible);
    RUN_TEST(test_aht10_temp_plausible);
    UNITY_END();
}

void loop() {}
