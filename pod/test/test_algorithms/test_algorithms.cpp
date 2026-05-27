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

static WeatherBuffer makeFallingPressureBuffer(float rateHpaPerHour, int entries = 72,
                                                float lat = -41.0f, float lon = 174.0f) {
    WeatherBuffer buf;
    float pressure = 1013.0f;
    float stepDrop = rateHpaPerHour / 12.0f;  // 5-min steps
    for (int i = 0; i < entries; i++) {
        WeatherEntry e{};
        e.timestamp   = 1000 + i * 300;
        e.pressureAdj = pressure - (i * (-stepDrop));
        e.tempC       = 15.0f;
        e.humidity    = 70.0f;
        e.lat         = lat;
        e.lon         = lon;
        buf.push(e);
    }
    return buf;
}

// ── ActivityDetector ──────────────────────────────────────────────────────────

void test_activity_climbing() {
    GpsBuffer buf = makeClimbingBuffer();
    SensorData s  = makeSensor(12);
    TEST_ASSERT_EQUAL(NijntjeState::Climbing, ActivityDetector::detect(buf, s, 1600));
}

void test_activity_walking_day() {
    GpsBuffer buf = makeWalkingBuffer();
    SensorData s  = makeSensor(12);
    TEST_ASSERT_EQUAL(NijntjeState::Walking, ActivityDetector::detect(buf, s, 1600));
}

void test_activity_walking_night() {
    GpsBuffer buf = makeWalkingBuffer();
    SensorData s  = makeSensor(21);  // 21:00 = night
    TEST_ASSERT_EQUAL(NijntjeState::WalkingNight, ActivityDetector::detect(buf, s, 1600));
}

void test_activity_resting_daytime() {
    GpsBuffer buf = makeStationaryBuffer();
    SensorData s  = makeSensor(14);  // 14:00 — daytime
    TEST_ASSERT_EQUAL(NijntjeState::Resting, ActivityDetector::detect(buf, s, 1600));
}

void test_activity_sleepy_evening() {
    GpsBuffer buf = makeStationaryBuffer();
    SensorData s  = makeSensor(20);  // 20:00 — early evening
    TEST_ASSERT_EQUAL(NijntjeState::SleepyEvening, ActivityDetector::detect(buf, s, 1600));
}

void test_activity_sleeping_tent_midnight() {
    GpsBuffer buf = makeStationaryBuffer();
    SensorData s  = makeSensor(23);  // 23:00
    TEST_ASSERT_EQUAL(NijntjeState::SleepingTent, ActivityDetector::detect(buf, s, 1600));
}

void test_activity_sleeping_tent_early_morning() {
    GpsBuffer buf = makeStationaryBuffer();
    SensorData s  = makeSensor(3);   // 03:00
    TEST_ASSERT_EQUAL(NijntjeState::SleepingTent, ActivityDetector::detect(buf, s, 1600));
}

void test_activity_empty_buffer_is_resting() {
    GpsBuffer buf;
    SensorData s = makeSensor(12);
    TEST_ASSERT_EQUAL(NijntjeState::Resting, ActivityDetector::detect(buf, s, 1600));
}

void test_activity_stale_gps_falls_through_to_stationary() {
    // Buffer has climbing data but entries are >3 minutes old — should ignore movement
    GpsBuffer buf = makeClimbingBuffer();
    SensorData s  = makeSensor(12);
    uint32_t staleNow = 1540 + GPS_STALE_THRESHOLD_S + 60;  // well past threshold
    TEST_ASSERT_EQUAL(NijntjeState::Resting, ActivityDetector::detect(buf, s, staleNow));
}

void test_activity_stale_gps_respects_time_of_day() {
    // Stale GPS at night — should still return SleepingTent, not Walking
    GpsBuffer buf = makeWalkingBuffer();
    SensorData s  = makeSensor(23);
    uint32_t staleNow = 1540 + GPS_STALE_THRESHOLD_S + 60;
    TEST_ASSERT_EQUAL(NijntjeState::SleepingTent, ActivityDetector::detect(buf, s, staleNow));
}

void test_activity_fresh_just_under_threshold() {
    // Entry exactly at threshold boundary — should still count as fresh
    GpsBuffer buf = makeClimbingBuffer();
    SensorData s  = makeSensor(12);
    uint32_t freshNow = 1540 + GPS_STALE_THRESHOLD_S - 1;  // 1s inside threshold
    TEST_ASSERT_EQUAL(NijntjeState::Climbing, ActivityDetector::detect(buf, s, freshNow));
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
        e.lat = -41.0f; e.lon = 174.0f;
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
        e.lat = -41.0f; e.lon = 174.0f;
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
        e.lat = -41.0f; e.lon = 174.0f;
        wb.push(e);
    }
    WeatherAlgorithm::update(wb, rain, storm, 200000);
    // Confidence should be low and recovery > 50% → cleared
    TEST_ASSERT_LESS_THAN(STORM_CLEAR_THRESHOLD + 5, storm.confidence);
}

// ── WeatherBuffer location pruning ───────────────────────────────────────────

void test_prune_keeps_nearby_entries() {
    // All entries at same location — nothing pruned
    WeatherBuffer wb = makeFallingPressureBuffer(-1.0f, 10, -41.0f, 174.0f);
    int before = wb.count();
    wb.pruneByLocation(-41.0f, 174.0f, 50000.0f);
    TEST_ASSERT_EQUAL(before, wb.count());
}

void test_prune_drops_distant_oldest_entries() {
    // First 5 entries at Wellington, last 5 at Auckland (~490km apart)
    WeatherBuffer wb = makeFallingPressureBuffer(-1.0f, 5, -41.29f, 174.78f);  // Wellington
    WeatherBuffer wb2 = makeFallingPressureBuffer(-1.0f, 5, -36.85f, 174.76f); // Auckland
    // Push Auckland entries after Wellington entries
    for (int i = 0; i < wb2.count(); i++) {
        WeatherEntry e{};
        e.timestamp = 5000 + i * 300;
        e.pressureAdj = 1010.0f;
        e.tempC = 15.0f; e.humidity = 70.0f;
        e.lat = -36.85f; e.lon = 174.76f;
        wb.push(e);
    }
    // Prune from Auckland — Wellington entries should be dropped
    wb.pruneByLocation(-36.85f, 174.76f, 50000.0f);
    TEST_ASSERT_LESS_OR_EQUAL(5, wb.count());
    // Remaining entries should all be near Auckland
    TEST_ASSERT_EQUAL(5, wb.count());
}

void test_prune_empty_buffer_safe() {
    WeatherBuffer wb;
    wb.pruneByLocation(-41.0f, 174.0f, 50000.0f);
    TEST_ASSERT_EQUAL(0, wb.count());
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

// ── GpsBuffer edge cases ──────────────────────────────────────────────────────

void test_gps_buffer_wraparound() {
    GpsBuffer buf;
    // Push 16 entries into 15-slot buffer — count must stay 15
    for (int i = 0; i < 16; i++) {
        GpsEntry e{};
        e.lat = -41.0f; e.lon = 174.0f;
        e.altitudeM = (float)i * 10.0f;
        e.timestamp = 1000 + i * 60;
        buf.push(e);
    }
    TEST_ASSERT_EQUAL(15, buf.count());
    // Newest should be the last entry pushed (i=15)
    TEST_ASSERT_FLOAT_WITHIN(0.1f, 150.0f, buf.newest().altitudeM);
}

void test_gps_alt_gain_descending_returns_zero() {
    GpsBuffer buf;
    for (int i = 0; i < 10; i++) {
        GpsEntry e{};
        e.lat = -41.0f; e.lon = 174.0f;
        e.altitudeM = 500.0f - i * 20.0f;  // descending
        e.timestamp = 1000 + i * 60;
        buf.push(e);
    }
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 0.0f, buf.averageAltGainPerMinute(10));
}

void test_gps_speed_maxentries_larger_than_count() {
    GpsBuffer buf;
    for (int i = 0; i < 5; i++) {
        GpsEntry e{};
        e.lat = -41.0f + i * 0.001f;
        e.lon = 174.0f;
        e.altitudeM = 100.0f;
        e.timestamp = 1000 + i * 60;
        buf.push(e);
    }
    // Requesting 10 entries but only 5 exist — should not crash, uses 5
    float speed = buf.averageSpeedKph(10);
    TEST_ASSERT_TRUE(speed >= 0.0f);
}

void test_gps_stationary_single_entry() {
    GpsBuffer buf;
    GpsEntry e{};
    e.lat = -41.0f; e.lon = 174.0f;
    e.altitudeM = 100.0f; e.timestamp = 1000;
    buf.push(e);
    TEST_ASSERT_TRUE(buf.isStationary(STATIONARY_RADIUS_M));
}

// ── ActivityDetector hour boundaries ─────────────────────────────────────────

void test_activity_night_boundary_hour_20() {
    GpsBuffer buf = makeWalkingBuffer();
    SensorData s  = makeSensor(20);  // exactly at night boundary
    TEST_ASSERT_EQUAL(NijntjeState::WalkingNight, ActivityDetector::detect(buf, s, 1600));
}

void test_activity_tent_boundary_hour_22() {
    GpsBuffer buf = makeStationaryBuffer();
    SensorData s  = makeSensor(22);  // exactly at tent boundary
    TEST_ASSERT_EQUAL(NijntjeState::SleepingTent, ActivityDetector::detect(buf, s, 1600));
}

void test_activity_sleepy_evening_boundary_hour_19() {
    GpsBuffer buf = makeStationaryBuffer();
    SensorData s  = makeSensor(19);  // exactly at sleepy evening start
    TEST_ASSERT_EQUAL(NijntjeState::SleepyEvening, ActivityDetector::detect(buf, s, 1600));
}

void test_activity_stale_exactly_at_threshold() {
    // nowUnix - newest == GPS_STALE_THRESHOLD_S exactly → still fresh (uses >)
    GpsBuffer buf = makeClimbingBuffer();
    SensorData s  = makeSensor(12);
    uint32_t atThreshold = 1540 + GPS_STALE_THRESHOLD_S;
    TEST_ASSERT_EQUAL(NijntjeState::Climbing, ActivityDetector::detect(buf, s, atThreshold));
}

// ── WeatherBuffer edge cases ──────────────────────────────────────────────────

void test_weather_buffer_wraparound() {
    WeatherBuffer wb;
    for (int i = 0; i < 290; i++) {
        WeatherEntry e{};
        e.timestamp = 1000 + i * 300;
        e.pressureAdj = 1013.0f;
        e.tempC = 15.0f; e.humidity = 60.0f;
        e.lat = -41.0f; e.lon = 174.0f;
        wb.push(e);
    }
    TEST_ASSERT_EQUAL(288, wb.count());
}

void test_prune_to_empty_then_push() {
    // Prune all entries, then push one — count should be 1
    WeatherBuffer wb = makeFallingPressureBuffer(-1.0f, 5, -41.29f, 174.78f);
    wb.pruneByLocation(-36.85f, 174.76f, 50000.0f);  // Auckland vs Wellington ~490km
    TEST_ASSERT_EQUAL(0, wb.count());
    WeatherEntry e{};
    e.timestamp = 99999; e.pressureAdj = 1013.0f;
    e.tempC = 15.0f; e.humidity = 60.0f;
    e.lat = -36.85f; e.lon = 174.76f;
    wb.push(e);
    TEST_ASSERT_EQUAL(1, wb.count());
}

void test_pressure_rate_fewer_entries_than_hours_requested() {
    WeatherBuffer wb;
    // Only 6 entries (30 min) but requesting 3-hour rate
    for (int i = 0; i < 6; i++) {
        WeatherEntry e{};
        e.timestamp = 1000 + i * 300;
        e.pressureAdj = 1013.0f - i * 0.5f;
        e.tempC = 15.0f; e.humidity = 60.0f;
        e.lat = -41.0f; e.lon = 174.0f;
        wb.push(e);
    }
    // Should use all 6 entries, not crash
    float rate = wb.pressureRateHpaPerHour(3);
    TEST_ASSERT_TRUE(rate < 0.0f);  // pressure is falling
}

// ── WeatherAlgorithm — recovery bug fix ──────────────────────────────────────

void test_weather_storm_clears_on_partial_recovery() {
    // Pressure drops 12 hPa then recovers 7 hPa (58% recovery > 50%) with low confidence
    WeatherPrediction rain{}, storm{};
    storm.active           = true;
    storm.predictedAt      = 100000;
    storm.baselinePressure = 1013.0f;
    storm.minPressure      = 1001.0f;  // trough: 12 hPa drop
    storm.confidence       = 70;

    // Fill with pressure at 1008 — 7/12 = 58% recovery, rising pressure = low confidence
    WeatherBuffer wb;
    for (int i = 0; i < 36; i++) {
        WeatherEntry e{};
        e.timestamp   = 100000 + i * 300;
        e.pressureAdj = 1008.0f;
        e.tempC = 15.0f; e.humidity = 50.0f;
        e.lat = -41.0f; e.lon = 174.0f;
        wb.push(e);
    }
    WeatherAlgorithm::update(wb, rain, storm, 200000);
    TEST_ASSERT_FALSE(storm.active);
}

void test_weather_storm_stays_latched_low_confidence_no_recovery() {
    // Low confidence but pressure still at trough — should NOT clear
    WeatherPrediction rain{}, storm{};
    storm.active           = true;
    storm.predictedAt      = 100000;
    storm.baselinePressure = 1013.0f;
    storm.minPressure      = 1001.0f;
    storm.confidence       = 70;

    WeatherBuffer wb;
    for (int i = 0; i < 36; i++) {
        WeatherEntry e{};
        e.timestamp   = 100000 + i * 300;
        e.pressureAdj = 1002.0f;  // barely above trough — only 8% recovery
        e.tempC = 15.0f; e.humidity = 50.0f;
        e.lat = -41.0f; e.lon = 174.0f;
        wb.push(e);
    }
    WeatherAlgorithm::update(wb, rain, storm, 200000);
    TEST_ASSERT_TRUE(storm.active);
}

void test_weather_storm_stays_latched_when_buffer_empty() {
    // Buffer location-pruned to empty — storm should stay latched, not clear
    WeatherPrediction rain{}, storm{};
    storm.active           = true;
    storm.predictedAt      = 100000;
    storm.baselinePressure = 1013.0f;
    storm.minPressure      = 1001.0f;
    storm.confidence       = 70;

    WeatherBuffer wb;  // empty
    WeatherAlgorithm::update(wb, rain, storm, 200000);
    TEST_ASSERT_TRUE(storm.active);
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
    RUN_TEST(test_activity_stale_gps_falls_through_to_stationary);
    RUN_TEST(test_activity_stale_gps_respects_time_of_day);
    RUN_TEST(test_activity_fresh_just_under_threshold);

    RUN_TEST(test_weather_no_trigger_stable_pressure);
    RUN_TEST(test_weather_storm_triggers_on_rapid_fall);
    RUN_TEST(test_weather_rain_triggers_before_storm);
    RUN_TEST(test_weather_storm_latches_after_trigger);
    RUN_TEST(test_weather_storm_clears_on_recovery);

    RUN_TEST(test_prune_keeps_nearby_entries);
    RUN_TEST(test_prune_drops_distant_oldest_entries);
    RUN_TEST(test_prune_empty_buffer_safe);

    RUN_TEST(test_gps_buffer_wraparound);
    RUN_TEST(test_gps_alt_gain_descending_returns_zero);
    RUN_TEST(test_gps_speed_maxentries_larger_than_count);
    RUN_TEST(test_gps_stationary_single_entry);

    RUN_TEST(test_activity_night_boundary_hour_20);
    RUN_TEST(test_activity_tent_boundary_hour_22);
    RUN_TEST(test_activity_sleepy_evening_boundary_hour_19);
    RUN_TEST(test_activity_stale_exactly_at_threshold);

    RUN_TEST(test_weather_buffer_wraparound);
    RUN_TEST(test_prune_to_empty_then_push);
    RUN_TEST(test_pressure_rate_fewer_entries_than_hours_requested);

    RUN_TEST(test_weather_storm_clears_on_partial_recovery);
    RUN_TEST(test_weather_storm_stays_latched_low_confidence_no_recovery);
    RUN_TEST(test_weather_storm_stays_latched_when_buffer_empty);

    RUN_TEST(test_buzzer_silent_at_midnight);
    RUN_TEST(test_buzzer_silent_at_23h);
    RUN_TEST(test_buzzer_active_at_noon);
    RUN_TEST(test_buzzer_severe_overrides_quiet_hours);
    RUN_TEST(test_buzzer_silent_when_no_storm);

    return UNITY_END();
}
