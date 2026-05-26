#include <unity.h>
#include "algorithms/ActivityDetector.h"
#include "algorithms/WeatherAlgorithm.h"
#include "sensors/GpsBuffer.h"
#include "sensors/WeatherBuffer.h"
#include "sensors/WeatherPrediction.h"
#include "config.h"

void setUp() {}
void tearDown() {}

// ── Helpers ───────────────────────────────────────────────────────────────────

static SensorData makeSensor(uint8_t hour = 12, float tempC = 15.0f,
                               float humidity = 60.0f) {
    SensorData s{};
    s.hour     = hour;
    s.tempC    = tempC;
    s.humidity = humidity;
    s.gpsHasFix = true;
    return s;
}

static GpsBuffer makeClimbingBuffer() {
    GpsBuffer buf;
    for (int i = 0; i < 10; i++) {
        GpsEntry e{};
        e.lat       = -41.0f;
        e.lon       = 174.0f;
        e.altitudeM = 100.0f + i * 15.0f;  // 15m/min gain
        e.timestamp = 1000 + i * 60;
        buf.push(e);
    }
    return buf;
}

static GpsBuffer makeWalkingBuffer() {
    GpsBuffer buf;
    for (int i = 0; i < 10; i++) {
        GpsEntry e{};
        e.lat       = -41.0f + i * 0.001f;  // moving north ~111m/step
        e.lon       = 174.0f;
        e.altitudeM = 100.0f;
        e.timestamp = 1000 + i * 60;
        buf.push(e);
    }
    return buf;
}

static GpsBuffer makeStationaryBuffer() {
    GpsBuffer buf;
    for (int i = 0; i < 10; i++) {
        GpsEntry e{};
        e.lat       = -41.0f;
        e.lon       = 174.0f;
        e.altitudeM = 100.0f;
        e.timestamp = 1000 + i * 60;
        buf.push(e);
    }
    return buf;
}

static WeatherBuffer makeFallingPressureBuffer(float rateHpaPerHour, int entries = 72) {
    WeatherBuffer buf;
    float pressure = 1013.0f;
    float stepDrop = rateHpaPerHour / 12.0f;  // 5-min steps
    for (int i = 0; i < entries; i++) {
        WeatherEntry e{};
        e.timestamp   = 1000 + i * 300;
        e.pressureAdj = pressure - (i * (-stepDrop));
        e.tempC       = 15.0f;
        e.humidity    = 70.0f;
        buf.push(e);
    }
    return buf;
}

// ── ActivityDetector ──────────────────────────────────────────────────────────

void test_activity_climbing() {
    GpsBuffer buf = makeClimbingBuffer();
    SensorData s  = makeSensor(12);
    TEST_ASSERT_EQUAL(NijntjeState::Climbing, ActivityDetector::detect(buf, s));
}

void test_activity_walking_day() {
    GpsBuffer buf = makeWalkingBuffer();
    SensorData s  = makeSensor(12);
    TEST_ASSERT_EQUAL(NijntjeState::Walking, ActivityDetector::detect(buf, s));
}

void test_activity_walking_night() {
    GpsBuffer buf = makeWalkingBuffer();
    SensorData s  = makeSensor(21);  // 21:00 = night
    TEST_ASSERT_EQUAL(NijntjeState::WalkingNight, ActivityDetector::detect(buf, s));
}

void test_activity_resting_daytime() {
    GpsBuffer buf = makeStationaryBuffer();
    SensorData s  = makeSensor(14);  // 14:00 — daytime
    TEST_ASSERT_EQUAL(NijntjeState::Resting, ActivityDetector::detect(buf, s));
}

void test_activity_sleepy_evening() {
    GpsBuffer buf = makeStationaryBuffer();
    SensorData s  = makeSensor(20);  // 20:00 — early evening
    TEST_ASSERT_EQUAL(NijntjeState::SleepyEvening, ActivityDetector::detect(buf, s));
}

void test_activity_sleeping_tent_midnight() {
    GpsBuffer buf = makeStationaryBuffer();
    SensorData s  = makeSensor(23);  // 23:00
    TEST_ASSERT_EQUAL(NijntjeState::SleepingTent, ActivityDetector::detect(buf, s));
}

void test_activity_sleeping_tent_early_morning() {
    GpsBuffer buf = makeStationaryBuffer();
    SensorData s  = makeSensor(3);   // 03:00
    TEST_ASSERT_EQUAL(NijntjeState::SleepingTent, ActivityDetector::detect(buf, s));
}

void test_activity_empty_buffer_is_resting() {
    GpsBuffer buf;
    SensorData s = makeSensor(12);
    // Buffer too small for walking/climbing thresholds — falls through to stationary
    TEST_ASSERT_EQUAL(NijntjeState::Resting, ActivityDetector::detect(buf, s));
}

// ── WeatherAlgorithm — trigger/latch/clear ────────────────────────────────────

void test_weather_no_trigger_stable_pressure() {
    WeatherBuffer wb;
    // Fill with flat pressure — no drop
    for (int i = 0; i < 72; i++) {
        WeatherEntry e{};
        e.timestamp   = 1000 + i * 300;
        e.pressureAdj = 1013.0f;
        e.tempC = 15.0f; e.humidity = 60.0f;
        wb.push(e);
    }
    WeatherPrediction rain{}, storm{};
    WeatherAlgorithm::update(wb, rain, storm, 100000);
    TEST_ASSERT_FALSE(storm.active);
    TEST_ASSERT_FALSE(rain.active);
}

void test_weather_storm_triggers_on_rapid_fall() {
    // -6 hPa/hr: pRate=1.0, zamb=1.0 → confidence=(0.50+0.25)×100=75% > 65% threshold
    WeatherBuffer wb = makeFallingPressureBuffer(-6.0f, 72);
    WeatherPrediction rain{}, storm{};
    WeatherAlgorithm::update(wb, rain, storm, 100000);
    TEST_ASSERT_TRUE(storm.active);
    TEST_ASSERT_GREATER_OR_EQUAL(STORM_TRIGGER_THRESHOLD, storm.confidence);
}

void test_weather_rain_triggers_before_storm() {
    // -3.5 hPa/hr: rain=(0.45×0.583+0.30×1.0)×100=56%>55%, storm=54%<65%
    WeatherBuffer wb = makeFallingPressureBuffer(-3.5f, 72);
    WeatherPrediction rain{}, storm{};
    WeatherAlgorithm::update(wb, rain, storm, 100000);
    TEST_ASSERT_TRUE(rain.active);
    TEST_ASSERT_FALSE(storm.active);
}

void test_weather_storm_latches_after_trigger() {
    WeatherBuffer wb = makeFallingPressureBuffer(-6.0f, 72);
    WeatherPrediction rain{}, storm{};
    WeatherAlgorithm::update(wb, rain, storm, 100000);
    TEST_ASSERT_TRUE(storm.active);

    // Simulate pressure stabilising — fill with flat pressure after the drop
    WeatherBuffer wb2;
    float baseP = wb.newest().pressureAdj;
    for (int i = 0; i < 12; i++) {  // 1 hour of flat pressure
        WeatherEntry e{};
        e.timestamp   = 200000 + i * 300;
        e.pressureAdj = baseP;  // flat — not rising
        e.tempC = 15.0f; e.humidity = 60.0f;
        wb2.push(e);
    }
    WeatherAlgorithm::update(wb2, rain, storm, 200000 + 12 * 300);
    // Storm should still be active — latch not cleared (no recovery)
    TEST_ASSERT_TRUE(storm.active);
}

void test_weather_storm_clears_on_recovery() {
    // Set up an active storm prediction
    WeatherPrediction rain{}, storm{};
    storm.active           = true;
    storm.predictedAt      = 100000;
    storm.baselinePressure = 1013.0f;
    storm.confidence       = 70;

    // Fill buffer with recovering pressure (rise back above 50% of drop)
    // Drop was 1013 - 1005 = 8 hPa, need to recover 4+ hPa
    WeatherBuffer wb;
    for (int i = 0; i < 24; i++) {
        WeatherEntry e{};
        e.timestamp   = 100000 + i * 300;
        e.pressureAdj = 1005.0f + i * 0.5f;  // rising steadily
        e.tempC = 15.0f; e.humidity = 55.0f;  // low humidity → low confidence
        wb.push(e);
    }
    WeatherAlgorithm::update(wb, rain, storm, 200000);
    // Confidence should be low and recovery > 50% → cleared
    TEST_ASSERT_LESS_THAN(STORM_CLEAR_THRESHOLD + 5, storm.confidence);
}

// ── Buzzer quiet hours ────────────────────────────────────────────────────────

void test_buzzer_silent_at_midnight() {
    WeatherPrediction storm{};
    storm.active     = true;
    storm.confidence = 70;  // not severe
    TEST_ASSERT_FALSE(WeatherAlgorithm::shouldChirp(storm, 0));
}

void test_buzzer_silent_at_23h() {
    WeatherPrediction storm{};
    storm.active     = true;
    storm.confidence = 70;
    TEST_ASSERT_FALSE(WeatherAlgorithm::shouldChirp(storm, 23));
}

void test_buzzer_active_at_noon() {
    WeatherPrediction storm{};
    storm.active     = true;
    storm.confidence = 70;
    TEST_ASSERT_TRUE(WeatherAlgorithm::shouldChirp(storm, 12));
}

void test_buzzer_severe_overrides_quiet_hours() {
    WeatherPrediction storm{};
    storm.active     = true;
    storm.confidence = SEVERE_STORM_THRESHOLD;
    TEST_ASSERT_TRUE(WeatherAlgorithm::shouldChirp(storm, 2));  // 02:00
}

void test_buzzer_silent_when_no_storm() {
    WeatherPrediction storm{};
    storm.active = false;
    TEST_ASSERT_FALSE(WeatherAlgorithm::shouldChirp(storm, 12));
}

int main() {
    UNITY_BEGIN();

    RUN_TEST(test_activity_climbing);
    RUN_TEST(test_activity_walking_day);
    RUN_TEST(test_activity_walking_night);
    RUN_TEST(test_activity_resting_daytime);
    RUN_TEST(test_activity_sleepy_evening);
    RUN_TEST(test_activity_sleeping_tent_midnight);
    RUN_TEST(test_activity_sleeping_tent_early_morning);
    RUN_TEST(test_activity_empty_buffer_is_resting);

    RUN_TEST(test_weather_no_trigger_stable_pressure);
    RUN_TEST(test_weather_storm_triggers_on_rapid_fall);
    RUN_TEST(test_weather_rain_triggers_before_storm);
    RUN_TEST(test_weather_storm_latches_after_trigger);
    RUN_TEST(test_weather_storm_clears_on_recovery);

    RUN_TEST(test_buzzer_silent_at_midnight);
    RUN_TEST(test_buzzer_silent_at_23h);
    RUN_TEST(test_buzzer_active_at_noon);
    RUN_TEST(test_buzzer_severe_overrides_quiet_hours);
    RUN_TEST(test_buzzer_silent_when_no_storm);

    return UNITY_END();
}
