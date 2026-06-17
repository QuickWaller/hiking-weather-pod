#include <unity.h>
#include "LogFormatter.h"
#include "sensors/SensorData.h"
#include "sensors/WeatherPrediction.h"
#include "sensors/GpsBuffer.h"
#include "algorithms/ActivityDetector.h"
#include "algorithms/NijntjeEvaluator.h"
#include "nijntje/NijntjeState.h"
#include <string.h>

void setUp() {}
void tearDown() {}

// ── stateChar ─────────────────────────────────────────────────────────────────

void test_state_chars() {
    TEST_ASSERT_EQUAL('C', LogFormatter::stateChar(NijntjeState::Climbing));
    TEST_ASSERT_EQUAL('W', LogFormatter::stateChar(NijntjeState::Walking));
    TEST_ASSERT_EQUAL('N', LogFormatter::stateChar(NijntjeState::WalkingNight));
    TEST_ASSERT_EQUAL('R', LogFormatter::stateChar(NijntjeState::Resting));
    TEST_ASSERT_EQUAL('E', LogFormatter::stateChar(NijntjeState::SleepyEvening));
    TEST_ASSERT_EQUAL('T', LogFormatter::stateChar(NijntjeState::SleepingTent));
    TEST_ASSERT_EQUAL('X', LogFormatter::stateChar(NijntjeState::Worried));
    TEST_ASSERT_EQUAL('K', LogFormatter::stateChar(NijntjeState::Connected));
}

void test_mod_chars() {
    TEST_ASSERT_EQUAL('N', LogFormatter::modChar(NijntjeModifier::None));
    TEST_ASSERT_EQUAL('H', LogFormatter::modChar(NijntjeModifier::Hot));
    TEST_ASSERT_EQUAL('C', LogFormatter::modChar(NijntjeModifier::Cold));
    TEST_ASSERT_EQUAL('F', LogFormatter::modChar(NijntjeModifier::Foggy));
}

void test_banner_chars() {
    TEST_ASSERT_EQUAL('N', LogFormatter::bannerChar(BannerState::None));
    TEST_ASSERT_EQUAL('Y', LogFormatter::bannerChar(BannerState::Yellow));
    TEST_ASSERT_EQUAL('R', LogFormatter::bannerChar(BannerState::Red));
}

void test_activity_char_strips_worried() {
    TEST_ASSERT_EQUAL('R', LogFormatter::activityChar(NijntjeState::Worried));
}

void test_activity_char_strips_connected() {
    TEST_ASSERT_EQUAL('R', LogFormatter::activityChar(NijntjeState::Connected));
}

void test_activity_char_passes_through_normal() {
    TEST_ASSERT_EQUAL('C', LogFormatter::activityChar(NijntjeState::Climbing));
    TEST_ASSERT_EQUAL('W', LogFormatter::activityChar(NijntjeState::Walking));
    TEST_ASSERT_EQUAL('T', LogFormatter::activityChar(NijntjeState::SleepingTent));
}

// ── formatEntry ───────────────────────────────────────────────────────────────

static SensorData makeSensor() {
    SensorData s{};
    s.lat          = -41.286500f;
    s.lon          = 174.776200f;
    s.altitudeM    = 150.0f;
    s.tempC        = 14.5f;
    s.humidity     = 72.0f;
    s.pressureRaw  = 998.5f;
    s.pressureAdj  = 1016.2f;
    s.batteryPct   = 85.0f;
    s.unixTime     = 1780315200UL;  // 2026-05-31 12:00:00 UTC
    return s;
}

static WeatherPrediction makeActivePred(uint8_t conf) {
    WeatherPrediction p{};
    p.confidence = conf;
    p.active     = true;
    return p;
}

void test_format_field_count() {
    char buf[220];
    SensorData s = makeSensor();
    WeatherPrediction storm{}, rain{};
    NijntjeDisplay disp{};
    LogFormatter::formatEntry(buf, sizeof(buf), 1780315200UL,
        s, storm, rain, -1.5f, NijntjeState::Walking, disp, 3240, 198432);

    // Count commas — CSV has 19 fields = 18 commas + newline
    int commas = 0;
    for (const char* p = buf; *p; p++) if (*p == ',') commas++;
    TEST_ASSERT_EQUAL(19, commas);
}

void test_format_timestamp() {
    char buf[220];
    SensorData s = makeSensor();
    WeatherPrediction storm{}, rain{};
    NijntjeDisplay disp{};
    LogFormatter::formatEntry(buf, sizeof(buf), 1780315200UL,
        s, storm, rain, 0.0f, NijntjeState::Walking, disp, 0, 0);
    // Check date portion only — avoid time-zone assumptions
    TEST_ASSERT_EQUAL_INT(0, strncmp(buf, "2026-06-01T", 11));
    // Timestamp is UTC and must be marked with a trailing 'Z' (index 19, before the comma)
    TEST_ASSERT_EQUAL('Z', buf[19]);
    TEST_ASSERT_EQUAL(',', buf[20]);
}

void test_format_lat_lon() {
    char buf[220];
    SensorData s = makeSensor();
    WeatherPrediction storm{}, rain{};
    NijntjeDisplay disp{};
    LogFormatter::formatEntry(buf, sizeof(buf), 1780315200UL,
        s, storm, rain, 0.0f, NijntjeState::Walking, disp, 0, 0);
    // Float %.6f precision — check first 7 significant chars only
    TEST_ASSERT_NOT_NULL(strstr(buf, "-41.2864") || strstr(buf, "-41.2865"));
    TEST_ASSERT_NOT_NULL(strstr(buf, "174.776"));
}

void test_format_activity_state_chars() {
    char buf[220];
    SensorData s = makeSensor();
    WeatherPrediction storm{}, rain{};
    NijntjeDisplay disp;
    disp.state    = NijntjeState::Worried;
    disp.modifier = NijntjeModifier::None;
    disp.banner   = BannerState::Red;
    // Activity passed as Walking, display state is Worried
    LogFormatter::formatEntry(buf, sizeof(buf), 1780315200UL,
        s, storm, rain, 0.0f, NijntjeState::Walking, disp, 0, 0);
    // Fields 15,16,17,18 (0-indexed) = activity,state,modifier,banner
    // Find last 4 single-char fields: should be W,X,N,R
    TEST_ASSERT_NOT_NULL(strstr(buf, ",W,X,N,R,"));
}

void test_format_storm_active() {
    char buf[220];
    SensorData s = makeSensor();
    WeatherPrediction storm = makeActivePred(78);
    WeatherPrediction rain  = makeActivePred(55);
    NijntjeDisplay disp{};
    LogFormatter::formatEntry(buf, sizeof(buf), 1780315200UL,
        s, storm, rain, -2.3f, NijntjeState::Resting, disp, 8000, 200000);
    TEST_ASSERT_NOT_NULL(strstr(buf, ",78,55,"));  // storm_conf,rain_conf
    TEST_ASSERT_NOT_NULL(strstr(buf, ",1,1,"));    // storm_active,rain_active
}

void test_format_pressure_rate() {
    char buf[220];
    SensorData s = makeSensor();
    WeatherPrediction storm{}, rain{};
    NijntjeDisplay disp{};
    LogFormatter::formatEntry(buf, sizeof(buf), 1780315200UL,
        s, storm, rain, -3.50f, NijntjeState::Walking, disp, 0, 0);
    TEST_ASSERT_NOT_NULL(strstr(buf, "-3.50,"));
}

// ── Full pipeline: sensors → activity → display → format ─────────────────────

void test_pipeline_walking_clear() {
    // Build a GPS buffer with walking-speed entries
    GpsBuffer gpsBuf;
    uint32_t t = 1780315200UL;
    // 10 entries, each 60s apart, moving ~3 kph
    float lat = -41.2865f;
    for (int i = 0; i < 10; i++) {
        lat += 0.0005f;  // ~55m per step → ~3.3 kph over 60s
        gpsBuf.push({ lat, 174.7762f, 150.0f, t + (uint32_t)(i * 60) });
    }

    SensorData sensor{};
    sensor.tempC    = 15.0f;
    sensor.humidity = 60.0f;
    sensor.hour     = 10;
    sensor.unixTime = t + 9 * 60;

    WeatherPrediction rain{}, storm{};
    NijntjeState activity = ActivityDetector::detect(gpsBuf, sensor, t + 9 * 60);
    NijntjeDisplay disp   = NijntjeEvaluator::evaluate(sensor, activity, rain, storm);

    TEST_ASSERT_EQUAL(NijntjeState::Walking, activity);
    TEST_ASSERT_EQUAL(NijntjeState::Walking, disp.state);
    TEST_ASSERT_EQUAL(BannerState::None, disp.banner);

    char buf[220];
    LogFormatter::formatEntry(buf, sizeof(buf), sensor.unixTime,
        sensor, storm, rain, 0.0f, activity, disp, 3000, 200000);
    TEST_ASSERT_NOT_NULL(strstr(buf, ",W,W,N,N,"));
}

void test_pipeline_storm_active_sets_worried_red_banner() {
    GpsBuffer gpsBuf;
    uint32_t t = 1780315200UL;
    // Stationary entries
    for (int i = 0; i < 10; i++)
        gpsBuf.push({ -41.2865f, 174.7762f, 150.0f, t + (uint32_t)(i * 60) });

    SensorData sensor{};
    sensor.tempC    = 12.0f;
    sensor.humidity = 85.0f;
    sensor.hour     = 14;
    sensor.unixTime = t + 9 * 60;

    WeatherPrediction storm = makeActivePred(70);
    WeatherPrediction rain{};
    NijntjeState activity = ActivityDetector::detect(gpsBuf, sensor, t + 9 * 60);
    NijntjeDisplay disp   = NijntjeEvaluator::evaluate(sensor, activity, rain, storm);

    TEST_ASSERT_EQUAL(NijntjeState::Worried, disp.state);
    TEST_ASSERT_EQUAL(BannerState::Red, disp.banner);

    char buf[220];
    LogFormatter::formatEntry(buf, sizeof(buf), sensor.unixTime,
        sensor, storm, rain, -2.0f, activity, disp, 3000, 200000);
    // activity=R (Resting underneath), state=X (Worried), banner=R
    TEST_ASSERT_NOT_NULL(strstr(buf, ",R,X,N,R,"));
}

int main() {
    UNITY_BEGIN();
    RUN_TEST(test_state_chars);
    RUN_TEST(test_mod_chars);
    RUN_TEST(test_banner_chars);
    RUN_TEST(test_activity_char_strips_worried);
    RUN_TEST(test_activity_char_strips_connected);
    RUN_TEST(test_activity_char_passes_through_normal);
    RUN_TEST(test_format_field_count);
    RUN_TEST(test_format_timestamp);
    RUN_TEST(test_format_lat_lon);
    RUN_TEST(test_format_activity_state_chars);
    RUN_TEST(test_format_storm_active);
    RUN_TEST(test_format_pressure_rate);
    RUN_TEST(test_pipeline_walking_clear);
    RUN_TEST(test_pipeline_storm_active_sets_worried_red_banner);
    return UNITY_END();
}
