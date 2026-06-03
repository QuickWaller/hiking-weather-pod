#include <unity.h>
#include "algorithms/ActivityDetector.h"
#include "algorithms/WeatherAlgorithm.h"
#include "sensors/GpsBuffer.h"
#include "sensors/WeatherBuffer.h"
#include "sensors/WeatherPrediction.h"
#include "BuzzerController.h"
#include "algorithms/NijntjeEvaluator.h"
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

static WeatherBuffer makeMultiSignalBuffer() {
    // -2 hPa/hr pressure fall + rising humidity (~2%/entry) + falling temp (~0.5°C/entry)
    // Humidity/temp contributions push rain confidence above threshold even without fast pressure fall
    WeatherBuffer buf;
    for (int i = 0; i < 72; i++) {
        WeatherEntry e{};
        e.timestamp   = 1000 + i * 300;
        e.pressureAdj = 1013.0f - i * (2.0f / 12.0f);
        e.humidity    = 30.0f + i * 2.0f;
        e.tempC       = 15.0f - i * 0.5f;
        e.lat = -41.0f; e.lon = 174.0f;
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

static SensorData makeSensorSun(uint8_t hour, uint8_t minute,
                                int16_t sunriseMin, int16_t sunsetMin) {
    SensorData s = makeSensor(hour);
    s.minute     = minute;
    s.sunriseMin = sunriseMin;
    s.sunsetMin  = sunsetMin;
    return s;
}

void test_activity_walking_night_after_winter_sunset() {
    // Winter sunset ~17:00. At 18:00 the old fixed 20:00 window would say "day",
    // but the sun is down → celestial path gives WalkingNight.
    GpsBuffer buf = makeWalkingBuffer();
    SensorData s  = makeSensorSun(18, 0, 7 * 60 + 45, 17 * 60);
    TEST_ASSERT_EQUAL(NijntjeState::WalkingNight, ActivityDetector::detect(buf, s, 1600));
}

void test_activity_walking_day_before_summer_sunset() {
    // Summer sunset ~21:00. At 20:00 the old fixed window said "night", but the sun
    // is still up → celestial path gives Walking.
    GpsBuffer buf = makeWalkingBuffer();
    SensorData s  = makeSensorSun(20, 0, 6 * 60, 21 * 60);
    TEST_ASSERT_EQUAL(NijntjeState::Walking, ActivityDetector::detect(buf, s, 1600));
}

void test_activity_walking_night_falls_back_when_sun_unknown() {
    // sunriseMin/sunsetMin default -1 (no fix yet) → fixed 20:00–06:00 window.
    GpsBuffer buf = makeWalkingBuffer();
    SensorData s  = makeSensor(21);
    TEST_ASSERT_EQUAL(NijntjeState::WalkingNight, ActivityDetector::detect(buf, s, 1600));
}

void test_activity_sleepy_evening_after_winter_sunset() {
    // Stationary 18:00, winter sunset 17:00 → sun is down → SleepyEvening.
    // The fixed fallback (sleepy starts 19:00) would call this Resting.
    GpsBuffer buf = makeStationaryBuffer();
    SensorData s  = makeSensorSun(18, 0, 7 * 60 + 45, 17 * 60);
    TEST_ASSERT_EQUAL(NijntjeState::SleepyEvening, ActivityDetector::detect(buf, s, 1600));
}

void test_activity_resting_before_summer_sunset() {
    // Stationary 19:00, summer sunset 21:00 → sun still up → Resting.
    // The fixed fallback (sleepy starts 19:00) would call this SleepyEvening.
    GpsBuffer buf = makeStationaryBuffer();
    SensorData s  = makeSensorSun(19, 0, 6 * 60, 21 * 60);
    TEST_ASSERT_EQUAL(NijntjeState::Resting, ActivityDetector::detect(buf, s, 1600));
}

void test_activity_tent_before_winter_sunrise() {
    // Stationary 06:30, winter sunrise 07:45 → pre-dawn → SleepingTent.
    // The fixed fallback (tent only before 06:00) would call this Resting.
    GpsBuffer buf = makeStationaryBuffer();
    SensorData s  = makeSensorSun(6, 30, 7 * 60 + 45, 17 * 60);
    TEST_ASSERT_EQUAL(NijntjeState::SleepingTent, ActivityDetector::detect(buf, s, 1600));
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
    TEST_ASSERT_FALSE(storm.active);
}

void test_weather_rain_and_storm_both_active() {
    // -6 hPa/hr exceeds both thresholds — both predictions should latch
    WeatherBuffer wb = makeFallingPressureBuffer(-6.0f, 72);
    WeatherPrediction rain{}, storm{};
    WeatherAlgorithm::update(wb, rain, storm, 100000);
    TEST_ASSERT_TRUE(storm.active);
    TEST_ASSERT_TRUE(rain.active);
}

void test_weather_humidity_temp_weights_contribute() {
    // Same moderate pressure fall (-2 hPa/hr): flat humidity/temp → no rain trigger
    WeatherBuffer wbFlat = makeFallingPressureBuffer(-2.0f, 72);
    WeatherPrediction rain1{}, storm1{};
    WeatherAlgorithm::update(wbFlat, rain1, storm1, 100000);
    TEST_ASSERT_FALSE(rain1.active);

    // Same pressure fall + rising humidity + falling temp → rain triggers, storm doesn't
    WeatherBuffer wbMulti = makeMultiSignalBuffer();
    WeatherPrediction rain2{}, storm2{};
    WeatherAlgorithm::update(wbMulti, rain2, storm2, 100000);
    TEST_ASSERT_TRUE(rain2.active);
    TEST_ASSERT_FALSE(storm2.active);
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

void test_buzzer_still_quiet_at_6h() {
    // Hour 6 is still within quiet window (< QUIET_HOUR_END = 7)
    WeatherPrediction storm{};
    storm.active     = true;
    storm.confidence = 70;
    TEST_ASSERT_FALSE(WeatherAlgorithm::shouldChirp(storm, 6));
}

void test_buzzer_active_at_7h() {
    // Hour 7 is the first active hour (not < 7, not >= 22)
    WeatherPrediction storm{};
    storm.active     = true;
    storm.confidence = 70;
    TEST_ASSERT_TRUE(WeatherAlgorithm::shouldChirp(storm, 7));
}

void test_buzzer_silent_when_no_storm() {
    WeatherPrediction storm{};
    storm.active = false;
    TEST_ASSERT_FALSE(WeatherAlgorithm::shouldChirp(storm, 12));
}

// ── BuzzerController transition tests ────────────────────────────────────────

static WeatherPrediction makeStormPred(bool active, uint8_t conf = 70) {
    WeatherPrediction p{};
    p.active     = active;
    p.confidence = conf;
    return p;
}

void test_buzzer_ctrl_storm_fires_on_activation() {
    BuzzerController b;
    WeatherPrediction rain{};
    WeatherPrediction storm = makeStormPred(true, 70);
    TEST_ASSERT_EQUAL(BuzzerAlert::Storm, b.evaluate(rain, storm, 12));
}

void test_buzzer_ctrl_storm_fires_only_once() {
    BuzzerController b;
    WeatherPrediction rain{};
    WeatherPrediction storm = makeStormPred(true, 70);
    b.evaluate(rain, storm, 12);
    TEST_ASSERT_EQUAL(BuzzerAlert::None, b.evaluate(rain, storm, 12));
}

void test_buzzer_ctrl_storm_refires_after_clear() {
    BuzzerController b;
    WeatherPrediction rain{};
    b.evaluate(rain, makeStormPred(true,  70), 12);
    b.evaluate(rain, makeStormPred(false,  0), 12);
    TEST_ASSERT_EQUAL(BuzzerAlert::Storm, b.evaluate(rain, makeStormPred(true, 70), 12));
}

void test_buzzer_ctrl_rain_fires_outside_quiet_hours() {
    BuzzerController b;
    WeatherPrediction storm{};
    WeatherPrediction rain = makeStormPred(true, 60);
    TEST_ASSERT_EQUAL(BuzzerAlert::Rain, b.evaluate(rain, storm, 12));
}

void test_buzzer_ctrl_rain_silent_in_quiet_hours() {
    BuzzerController b;
    WeatherPrediction storm{};
    WeatherPrediction rain = makeStormPred(true, 60);
    TEST_ASSERT_EQUAL(BuzzerAlert::None, b.evaluate(rain, storm, 23));
}

void test_buzzer_ctrl_rain_never_overrides_quiet_hours() {
    BuzzerController b;
    WeatherPrediction storm{};
    WeatherPrediction rain = makeStormPred(true, SEVERE_STORM_THRESHOLD);
    TEST_ASSERT_EQUAL(BuzzerAlert::None, b.evaluate(rain, storm, 3));
}

void test_buzzer_ctrl_storm_beats_rain_on_same_cycle() {
    BuzzerController b;
    WeatherPrediction rain  = makeStormPred(true, 60);
    WeatherPrediction storm = makeStormPred(true, 70);
    TEST_ASSERT_EQUAL(BuzzerAlert::Storm, b.evaluate(rain, storm, 12));
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

void test_gps_stationary_within_radius() {
    GpsBuffer buf;
    for (int i = 0; i < 5; i++) {
        GpsEntry e{};
        e.lat = -41.0f + i * 0.00005f;  // ~5.5m/step, 22m total spread — within 25m radius
        e.lon = 174.0f;
        e.altitudeM = 100.0f;
        e.timestamp = 1000 + i * 60;
        buf.push(e);
    }
    TEST_ASSERT_TRUE(buf.isStationary(STATIONARY_RADIUS_M));
}

void test_gps_not_stationary_outside_radius() {
    GpsBuffer buf;
    for (int i = 0; i < 5; i++) {
        GpsEntry e{};
        e.lat = -41.0f; e.lon = 174.0f;
        e.altitudeM = 100.0f;
        e.timestamp = 1000 + i * 60;
        buf.push(e);
    }
    GpsEntry outlier{};
    outlier.lat = -41.0f + 0.0003f;  // ~33m north — just outside 25m radius
    outlier.lon = 174.0f;
    outlier.altitudeM = 100.0f;
    outlier.timestamp = 1300;
    buf.push(outlier);
    TEST_ASSERT_FALSE(buf.isStationary(STATIONARY_RADIUS_M));
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

void test_max_pressure_empty_buffer() {
    WeatherBuffer wb;
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 0.0f, wb.maxPressure());
}

void test_max_pressure_returns_highest() {
    WeatherBuffer wb;
    for (int i = 0; i < 5; i++) {
        WeatherEntry e{};
        e.timestamp   = 1000 + i * 300;
        e.pressureAdj = 1010.0f + i * 2.0f;  // 1010, 1012, 1014, 1016, 1018
        e.tempC = 15.0f; e.humidity = 60.0f;
        e.lat = -41.0f; e.lon = 174.0f;
        wb.push(e);
    }
    TEST_ASSERT_FLOAT_WITHIN(0.1f, 1018.0f, wb.maxPressure());
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

// ── minPressure corruption guard (empty buffer during active storm) ───────────

void test_min_pressure_not_corrupted_by_empty_buffer() {
    // Storm active; buffer empties (location prune during GPS dropout); buffer then
    // refills with pressure still at the trough. The storm must stay active — not
    // clear due to a poisoned minPressure of 0.
    WeatherPrediction rain{}, storm{};
    storm.active           = true;
    storm.predictedAt      = 100000;
    storm.baselinePressure = 1013.0f;
    storm.minPressure      = 1001.0f;
    storm.confidence       = 70;

    // Cycle 1: buffer empty (GPS dropout / prune) — must NOT corrupt minPressure
    WeatherBuffer empty;
    WeatherAlgorithm::update(empty, rain, storm, 200000);
    TEST_ASSERT_TRUE(storm.active);
    // minPressure must not have been dragged down to 0
    TEST_ASSERT_FLOAT_WITHIN(0.1f, 1001.0f, storm.minPressure);
}

void test_storm_does_not_clear_after_empty_then_trough_refill() {
    // After the empty cycle (guard holds), refill buffer with pressure still near
    // trough (1002). Without the guard the minPressure would be 0, recovery=0.99,
    // and the storm would clear even though it hasn't passed.
    WeatherPrediction rain{}, storm{};
    storm.active           = true;
    storm.predictedAt      = 100000;
    storm.baselinePressure = 1013.0f;
    storm.minPressure      = 1001.0f;
    storm.confidence       = 70;

    // Empty buffer pass
    WeatherBuffer empty;
    WeatherAlgorithm::update(empty, rain, storm, 200000);

    // Refill with pressure still at trough — low humidity → low confidence
    WeatherBuffer trough;
    for (int i = 0; i < 36; i++) {
        WeatherEntry e{};
        e.timestamp   = 200000 + i * 300;
        e.pressureAdj = 1002.0f;  // barely above minPressure — recovery ~8%
        e.tempC = 15.0f; e.humidity = 50.0f;
        e.lat = -41.0f; e.lon = 174.0f;
        trough.push(e);
    }
    WeatherAlgorithm::update(trough, rain, storm, 300000);
    TEST_ASSERT_TRUE(storm.active);
}

// ── ActivityDetector: partially-filled buffer (below min-entries threshold) ───

void test_activity_partial_buffer_below_min_entries_is_stationary() {
    // 5 entries moving briskly — below WALKING_MIN_ENTRIES (10).
    // Detection should not fire walking/climbing; falls through to stationary.
    GpsBuffer buf;
    for (int i = 0; i < 5; i++) {
        GpsEntry e{};
        e.lat       = -41.0f + i * 0.001f;  // ~111 m/step = fast walking pace
        e.lon       = 174.0f;
        e.altitudeM = 100.0f;
        e.timestamp = 1000 + i * 60;
        buf.push(e);
    }
    SensorData s = makeSensor(12);
    NijntjeState state = ActivityDetector::detect(buf, s, 1600);
    TEST_ASSERT_NOT_EQUAL(NijntjeState::Walking,  state);
    TEST_ASSERT_NOT_EQUAL(NijntjeState::Climbing, state);
}

// ── NijntjeEvaluator: dead AHT10 (zero-initialised temp/humidity) ─────────────

void test_evaluator_dead_aht10_no_false_foggy() {
    // tempC=0, humidity=0 from an uninitialised/failed AHT10.
    // dewPointC clamps humidity to 1.0 → very negative dewpoint → large spread →
    // fog condition is NOT met.  Confirms no false Foggy from a dead sensor.
    SensorData s{};
    s.hour = 12; s.tempC = 0.0f; s.humidity = 0.0f;
    WeatherPrediction rain{}, storm{};
    NijntjeDisplay d = NijntjeEvaluator::evaluate(s, NijntjeState::Walking, rain, storm);
    TEST_ASSERT_NOT_EQUAL(NijntjeModifier::Foggy, d.modifier);
}

void test_evaluator_dead_aht10_shows_cold_modifier() {
    // tempC=0 IS below COLD_TEMP_C (8°C), so Walking gets Cold modifier.
    // This documents the known zero-init behaviour — not a bug, just a fact.
    SensorData s{};
    s.hour = 12; s.tempC = 0.0f; s.humidity = 0.0f;
    WeatherPrediction rain{}, storm{};
    NijntjeDisplay d = NijntjeEvaluator::evaluate(s, NijntjeState::Walking, rain, storm);
    TEST_ASSERT_EQUAL(NijntjeModifier::Cold, d.modifier);
}

// ── bannerLine1 path: estimatedArrival == 0 ───────────────────────────────────

void test_banner_line1_zero_arrival_returns_likely() {
    // estimatedArrival == 0 means prediction was manually seeded without a trigger
    // cycle. The function returns "<LABEL> LIKELY".  This path is unreachable in
    // production (imminenceHours ≥ 2h → estimatedArrival = nowUnix + 7200 ≠ 0),
    // but the branch exists and should be covered.
    WeatherPrediction p{};
    p.active           = true;
    p.confidence       = 70;
    p.estimatedArrival = 0;
    const char* l1 = WeatherAlgorithm::bannerLine1(p, true);
    TEST_ASSERT_NOT_NULL(l1);
    TEST_ASSERT_EQUAL_STRING("STORM LIKELY", l1);
}

// ── Regression: false Climbing from GPS-altitude noise (fix #2) ───────────────

void test_gps_alt_gain_ignores_oscillation() {
    // Altitude oscillates 100/130 m (GPS jitter) with only ~30 m net change over the
    // window. The old positive-only summation reported ~16 m/min here (false climb);
    // net change is ~3 m/min. Must stay below the Climbing threshold.
    GpsBuffer buf;
    for (int i = 0; i < 10; i++) {
        GpsEntry e{};
        e.lat = -41.0f; e.lon = 174.0f;
        e.altitudeM = (i % 2 == 0) ? 100.0f : 130.0f;
        e.timestamp = 1000 + i * 60;
        buf.push(e);
    }
    TEST_ASSERT_LESS_THAN(CLIMBING_ALT_GAIN_M_PER_MIN, buf.averageAltGainPerMinute(10));
}

void test_activity_no_false_climb_on_alt_jitter() {
    // Same jittery-but-flat profile through the detector — must NOT classify as Climbing.
    GpsBuffer buf;
    for (int i = 0; i < 10; i++) {
        GpsEntry e{};
        e.lat = -41.0f; e.lon = 174.0f;
        e.altitudeM = (i % 2 == 0) ? 100.0f : 130.0f;
        e.timestamp = 1000 + i * 60;
        buf.push(e);
    }
    SensorData s = makeSensor(12);
    TEST_ASSERT_NOT_EQUAL(NijntjeState::Climbing, ActivityDetector::detect(buf, s, 1600));
}

// ── Regression: clock edge cases in staleness (underflow / now==0) ────────────

void test_activity_zero_now_is_stale() {
    // RTC not yet synced (now == 0) — movement data must be ignored, fall to time-of-day.
    GpsBuffer buf = makeClimbingBuffer();
    SensorData s  = makeSensor(12);
    TEST_ASSERT_EQUAL(NijntjeState::Resting, ActivityDetector::detect(buf, s, 0));
}

void test_activity_future_timestamp_is_stale() {
    // Newest fix timestamp (1540) is ahead of now (1500) — clock skew. The raw
    // subtraction would underflow to a huge value; must be treated as stale.
    GpsBuffer buf = makeClimbingBuffer();
    SensorData s  = makeSensor(12);
    TEST_ASSERT_EQUAL(NijntjeState::Resting, ActivityDetector::detect(buf, s, 1500));
}

// ── Regression: GPS dropout must not wipe weather history (fix #1) ─────────────

void test_prune_ignores_invalid_origin() {
    // Mirrors the main loop's per-cycle prune. A no-fix cycle yields origin (0,0);
    // the buffer must survive intact rather than being wiped.
    WeatherBuffer wb;
    for (int i = 0; i < 50; i++) {
        WeatherEntry e{};
        e.timestamp   = 1000 + i * 300;
        e.pressureAdj = 1010.0f - i * 0.1f;
        e.tempC = 12.0f; e.humidity = 70.0f;
        e.lat = -41.2865f; e.lon = 174.7762f;  // Wellington
        wb.push(e);
    }
    int before = wb.count();
    wb.pruneByLocation(0.0f, 0.0f, WEATHER_LOCATION_RADIUS_M);
    TEST_ASSERT_EQUAL(before, wb.count());
}

// ── Banner string functions (previously untested) ─────────────────────────────

void test_banner_inactive_returns_null() {
    WeatherPrediction p{};
    p.active = false;
    TEST_ASSERT_NULL(WeatherAlgorithm::bannerLine1(p, true));
    TEST_ASSERT_NULL(WeatherAlgorithm::bannerLine2(p));
}

void test_banner_active_shows_confidence() {
    WeatherPrediction p{};
    p.active = true;
    p.confidence = 72;
    p.estimatedArrival = 12345;
    const char* l2 = WeatherAlgorithm::bannerLine2(p);
    TEST_ASSERT_NOT_NULL(l2);
    TEST_ASSERT_EQUAL_STRING("CONF 72%", l2);
}

// ── Integration: full storm lifecycle across cycles ───────────────────────────

void test_integration_storm_lifecycle() {
    WeatherPrediction rain{}, storm{};

    // Cycle A — stable high pressure: no trigger.
    WeatherBuffer stable;
    for (int i = 0; i < 72; i++) {
        WeatherEntry e{};
        e.timestamp = 1000 + i * 300; e.pressureAdj = 1013.0f;
        e.tempC = 15.0f; e.humidity = 60.0f; e.lat = -41.0f; e.lon = 174.0f;
        stable.push(e);
    }
    WeatherAlgorithm::update(stable, rain, storm, 1000 + 72 * 300);
    TEST_ASSERT_FALSE(storm.active);

    // Cycle B — rapid fall (-6 hPa/hr): storm latches, baseline captured.
    WeatherBuffer falling = makeFallingPressureBuffer(-6.0f, 72);
    WeatherAlgorithm::update(falling, rain, storm, 100000);
    TEST_ASSERT_TRUE(storm.active);
    TEST_ASSERT_FLOAT_WITHIN(1.0f, 1013.0f, storm.baselinePressure);
    TEST_ASSERT_TRUE(storm.estimatedArrival > 100000);  // set on trigger cycle

    // Cycle C — pressure recovers >50% of the drop with low confidence: storm clears.
    for (int i = 0; i < 36; i++) {
        WeatherEntry e{};
        e.timestamp   = 1000 + (72 + i) * 300;
        e.pressureAdj = 996.0f;  // trough ~977.5, baseline 1013 → ~52% recovered
        e.tempC = 15.0f; e.humidity = 55.0f; e.lat = -41.0f; e.lon = 174.0f;
        falling.push(e);
    }
    WeatherAlgorithm::update(falling, rain, storm, 200000);
    TEST_ASSERT_FALSE(storm.active);
}

// ── Integration: a hike progresses through activity states ────────────────────

void test_integration_activity_progression() {
    SensorData day   = makeSensor(12);
    SensorData night = makeSensor(23);

    // Cold start: empty buffer → Resting (daytime fallback).
    GpsBuffer empty;
    TEST_ASSERT_EQUAL(NijntjeState::Resting,
                      ActivityDetector::detect(empty, day, 1600));

    // Ascending → Climbing.
    TEST_ASSERT_EQUAL(NijntjeState::Climbing,
                      ActivityDetector::detect(makeClimbingBuffer(), day, 1600));

    // Moving on the flat by day → Walking.
    TEST_ASSERT_EQUAL(NijntjeState::Walking,
                      ActivityDetector::detect(makeWalkingBuffer(), day, 1600));

    // Stationary at night → SleepingTent.
    TEST_ASSERT_EQUAL(NijntjeState::SleepingTent,
                      ActivityDetector::detect(makeStationaryBuffer(), night, 1600));
}

// ── Zambretti absolute-pressure-level modifier (boost low / damp high) ────────

// Linear falling buffer from an explicit starting pressure (sea-level), -rate/hr.
static WeatherBuffer fallingFrom(float startP, float rateHpaPerHour, int n = 36) {
    WeatherBuffer buf;
    for (int i = 0; i < n; i++) {
        WeatherEntry e{};
        e.timestamp   = 1000 + i * 300;
        e.pressureAdj = startP + rateHpaPerHour * ((float)i * 300.0f / 3600.0f);
        e.tempC = 15.0f; e.humidity = 60.0f; e.lat = -41.0f; e.lon = 174.0f;
        buf.push(e);
    }
    return buf;
}

void test_zambretti_low_pressure_boosts_confidence() {
    // Identical -2 hPa/hr fall, but one system sits in a deep low (ends ~984) and
    // the other in a high (ends ~1029). The deepening low must score higher.
    WeatherBuffer low  = fallingFrom(990.0f,  -2.0f);
    WeatherBuffer high = fallingFrom(1035.0f, -2.0f);
    WeatherPrediction r1{}, s1{}, r2{}, s2{};
    WeatherAlgorithm::update(low,  r1, s1, 100000);
    WeatherAlgorithm::update(high, r2, s2, 100000);
    TEST_ASSERT_TRUE(s1.confidence > s2.confidence);
    TEST_ASSERT_TRUE(r1.confidence > r2.confidence);
}

void test_zambretti_neutral_band_no_change() {
    // Both ends land in the neutral band (1000–1020): level must not change the score.
    WeatherBuffer a = fallingFrom(1018.0f, -2.0f);  // ends ~1012
    WeatherBuffer b = fallingFrom(1014.0f, -2.0f);  // ends ~1008
    WeatherPrediction r1{}, s1{}, r2{}, s2{};
    WeatherAlgorithm::update(a, r1, s1, 100000);
    WeatherAlgorithm::update(b, r2, s2, 100000);
    TEST_ASSERT_EQUAL_UINT8(s1.confidence, s2.confidence);
}

void test_zambretti_deepening_low_with_humidity_reaches_storm() {
    // A deepening low (already <1000, falling -2.5/hr) WITH rising humidity is the
    // dangerous NZ frontal case. The level boost should help it reach the storm
    // trigger, where the same fall at normal pressure would not.
    WeatherBuffer wb;
    for (int i = 0; i < 36; i++) {
        WeatherEntry e{};
        e.timestamp   = 1000 + i * 300;
        e.pressureAdj = 995.0f - 2.5f * ((float)i * 300.0f / 3600.0f);  // ~995 → ~988
        e.tempC       = 15.0f;
        e.humidity    = 40.0f + 2.0f * i;   // strongly rising
        e.lat = -41.0f; e.lon = 174.0f;
        wb.push(e);
    }
    WeatherPrediction rain{}, storm{};
    WeatherAlgorithm::update(wb, rain, storm, 100000);
    TEST_ASSERT_TRUE(storm.active);
}

// ── Sensor degradation: NaN env samples skipped, pressure prediction survives ─

void test_trend_skips_nan_samples() {
    // Humidity rises a clean +12%/hr, but two cycles have NaN (dead AHT10).
    // The trend must reflect the valid samples (~12), not break or return 0.
    WeatherBuffer wb;
    for (int i = 0; i < 12; i++) {
        WeatherEntry e{};
        e.timestamp   = 1000 + i * 300;
        e.pressureAdj = 1010.0f;
        e.tempC       = 15.0f;
        e.humidity    = (i == 3 || i == 7) ? NAN : 50.0f + 1.0f * i;  // +1%/5min = 12%/hr
        e.lat = -41.0f; e.lon = 174.0f;
        wb.push(e);
    }
    TEST_ASSERT_FLOAT_WITHIN(0.5f, 12.0f, wb.humidityTrend());
}

void test_all_nan_env_trend_is_zero() {
    // Every env reading NaN (AHT10 dead whole window) → trend degrades to 0, no crash.
    WeatherBuffer wb;
    for (int i = 0; i < 12; i++) {
        WeatherEntry e{};
        e.timestamp = 1000 + i * 300; e.pressureAdj = 1010.0f;
        e.tempC = NAN; e.humidity = NAN; e.lat = -41.0f; e.lon = 174.0f;
        wb.push(e);
    }
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 0.0f, wb.humidityTrend());
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 0.0f, wb.tempTrend());
}

void test_storm_triggers_with_dead_env_sensor() {
    // AHT10 dead (all temp/humidity NaN) but pressure falling -6 hPa/hr. Storm must
    // still trigger from pressure alone — degraded, not blinded.
    WeatherBuffer wb;
    float p = 1013.0f;
    for (int i = 0; i < 36; i++) {
        WeatherEntry e{};
        e.timestamp   = 1000 + i * 300;
        e.pressureAdj = p - 6.0f * ((float)i * 300.0f / 3600.0f);  // -6 hPa/hr
        e.tempC = NAN; e.humidity = NAN; e.lat = -41.0f; e.lon = 174.0f;
        wb.push(e);
    }
    WeatherPrediction rain{}, storm{};
    WeatherAlgorithm::update(wb, rain, storm, 100000);
    TEST_ASSERT_TRUE(storm.active);
}

// ── Median altitude smoothing (fix: GPS-alt noise → pressure) ─────────────────

void test_median_altitude_rejects_spike() {
    // Steady ~800m hike with one 900m GPS glitch on the newest fix. The median over
    // the last 5 fixes must ignore the spike (≈800), where a mean would be pulled up.
    GpsBuffer buf;
    float alts[] = {798.0f, 801.0f, 799.0f, 800.0f, 900.0f};  // newest = spike
    for (int i = 0; i < 5; i++) {
        GpsEntry e{};
        e.lat = -41.0f; e.lon = 174.0f;
        e.altitudeM = alts[i];
        e.timestamp = 1000 + i * 300;
        buf.push(e);
    }
    float med = buf.medianAltitude(ALTITUDE_MEDIAN_SAMPLES);
    TEST_ASSERT_FLOAT_WITHIN(2.0f, 800.0f, med);
}

void test_median_altitude_empty_is_zero() {
    GpsBuffer buf;
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 0.0f, buf.medianAltitude(ALTITUDE_MEDIAN_SAMPLES));
}

void test_median_altitude_uses_recent_window_only() {
    // Old low entries then recent high plateau — median of last 5 reflects the
    // recent altitude (~500), not the old ~100 values.
    GpsBuffer buf;
    for (int i = 0; i < 5; i++) {  // older: 100m
        GpsEntry e{}; e.lat=-41.0f; e.lon=174.0f; e.altitudeM=100.0f; e.timestamp=1000+i*300;
        buf.push(e);
    }
    for (int i = 0; i < 5; i++) {  // recent: 500m
        GpsEntry e{}; e.lat=-41.0f; e.lon=174.0f; e.altitudeM=500.0f; e.timestamp=2500+i*300;
        buf.push(e);
    }
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 500.0f, buf.medianAltitude(5));
}

// ── Confidence rounding, not truncation (fix #3) ──────────────────────────────

void test_score_to_confidence_rounds_not_floors() {
    // 0.646 → 64.6 → rounds to 65 (truncation would give 64, missing a 65 trigger).
    TEST_ASSERT_EQUAL_UINT8(65, WeatherAlgorithm::scoreToConfidence(0.646f));
    TEST_ASSERT_EQUAL_UINT8(64, WeatherAlgorithm::scoreToConfidence(0.644f));
}

void test_score_to_confidence_clamps() {
    TEST_ASSERT_EQUAL_UINT8(100, WeatherAlgorithm::scoreToConfidence(1.0f));
    TEST_ASSERT_EQUAL_UINT8(100, WeatherAlgorithm::scoreToConfidence(1.2f));  // over-unity guard
    TEST_ASSERT_EQUAL_UINT8(0,   WeatherAlgorithm::scoreToConfidence(0.0f));
}

// ── Pressure rate: regression vs 2-point slope (fix #1) ───────────────────────

void test_pressure_rate_linear_is_exact() {
    // Perfectly linear -2 hPa/hr fall over a 3hr window → regression recovers -2.
    WeatherBuffer wb = makeFallingPressureBuffer(-2.0f, 36);
    TEST_ASSERT_FLOAT_WITHIN(0.01f, -2.0f, wb.pressureRateHpaPerHour(3));
}

void test_pressure_rate_robust_to_noisy_endpoint() {
    // A clean -2 hPa/hr fall, but the newest sample spikes up by +3 hPa (one bad
    // BMP180 read / altitude glitch). A 2-point slope (oldest vs newest) would flip
    // POSITIVE here; the regression must still report clearly falling.
    WeatherBuffer clean;
    WeatherBuffer spiked;
    for (int i = 0; i < 36; i++) {
        WeatherEntry e{};
        e.timestamp   = 1000 + i * 300;
        e.pressureAdj = 1000.0f - 2.0f * ((float)i * 300.0f / 3600.0f);  // -2 hPa/hr
        e.tempC = 15.0f; e.humidity = 60.0f; e.lat = -41.0f; e.lon = 174.0f;
        clean.push(e);
        if (i == 35) e.pressureAdj += 3.0f;  // spike on newest only
        spiked.push(e);
    }
    TEST_ASSERT_FLOAT_WITHIN(0.01f, -2.0f, clean.pressureRateHpaPerHour(3));
    // Robustness: still falling, not flipped positive by the single outlier.
    // NB: use the FLOAT assertion — TEST_ASSERT_LESS_THAN is integer-only and would
    // cast -1.84 to -1, making "-1 < -1" fail.
    TEST_ASSERT_TRUE(spiked.pressureRateHpaPerHour(3) < -1.0f);
}

// ── Humidity/temp trends: time-based, uneven-spacing robust (fix #2) ──────────

void test_humidity_trend_per_hour_even_spacing() {
    // +2%/5-min entry over even spacing == +24%/hour.
    WeatherBuffer wb;
    for (int i = 0; i < 36; i++) {
        WeatherEntry e{};
        e.timestamp = 1000 + i * 300;
        e.pressureAdj = 1013.0f; e.tempC = 15.0f;
        e.humidity = 30.0f + 2.0f * i;
        e.lat = -41.0f; e.lon = 174.0f;
        wb.push(e);
    }
    TEST_ASSERT_FLOAT_WITHIN(0.1f, 24.0f, wb.humidityTrend());
}

void test_temp_trend_per_hour_even_spacing() {
    // -0.5°C/5-min entry == -6°C/hour.
    WeatherBuffer wb;
    for (int i = 0; i < 36; i++) {
        WeatherEntry e{};
        e.timestamp = 1000 + i * 300;
        e.pressureAdj = 1013.0f; e.humidity = 60.0f;
        e.tempC = 15.0f - 0.5f * i;
        e.lat = -41.0f; e.lon = 174.0f;
        wb.push(e);
    }
    TEST_ASSERT_FLOAT_WITHIN(0.1f, -6.0f, wb.tempTrend());
}

void test_humidity_trend_robust_to_uneven_spacing() {
    // Humidity rises at a true 10%/hour, but cadence is irregular (skipped cycles).
    // Index-based regression would misread the rate; time-based recovers ~10.
    uint32_t offsets[] = {0, 300, 600, 3600, 4200, 7200, 9000, 10800};
    WeatherBuffer wb;
    for (int i = 0; i < 8; i++) {
        WeatherEntry e{};
        e.timestamp = 1000 + offsets[i];
        e.pressureAdj = 1013.0f; e.tempC = 15.0f;
        e.humidity = 50.0f + 10.0f * (offsets[i] / 3600.0f);
        e.lat = -41.0f; e.lon = 174.0f;
        wb.push(e);
    }
    TEST_ASSERT_FLOAT_WITHIN(0.1f, 10.0f, wb.humidityTrend());
}

int main() {
    UNITY_BEGIN();

    RUN_TEST(test_activity_climbing);
    RUN_TEST(test_activity_walking_day);
    RUN_TEST(test_activity_walking_night);
    RUN_TEST(test_activity_walking_night_after_winter_sunset);
    RUN_TEST(test_activity_walking_day_before_summer_sunset);
    RUN_TEST(test_activity_walking_night_falls_back_when_sun_unknown);
    RUN_TEST(test_activity_sleepy_evening_after_winter_sunset);
    RUN_TEST(test_activity_resting_before_summer_sunset);
    RUN_TEST(test_activity_tent_before_winter_sunrise);
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
    RUN_TEST(test_weather_rain_and_storm_both_active);
    RUN_TEST(test_weather_humidity_temp_weights_contribute);

    RUN_TEST(test_prune_keeps_nearby_entries);
    RUN_TEST(test_prune_drops_distant_oldest_entries);
    RUN_TEST(test_prune_empty_buffer_safe);

    RUN_TEST(test_gps_buffer_wraparound);
    RUN_TEST(test_gps_alt_gain_descending_returns_zero);
    RUN_TEST(test_gps_speed_maxentries_larger_than_count);
    RUN_TEST(test_gps_stationary_single_entry);
    RUN_TEST(test_gps_stationary_within_radius);
    RUN_TEST(test_gps_not_stationary_outside_radius);

    RUN_TEST(test_activity_night_boundary_hour_20);
    RUN_TEST(test_activity_tent_boundary_hour_22);
    RUN_TEST(test_activity_sleepy_evening_boundary_hour_19);
    RUN_TEST(test_activity_stale_exactly_at_threshold);

    RUN_TEST(test_weather_buffer_wraparound);
    RUN_TEST(test_prune_to_empty_then_push);
    RUN_TEST(test_pressure_rate_fewer_entries_than_hours_requested);
    RUN_TEST(test_max_pressure_empty_buffer);
    RUN_TEST(test_max_pressure_returns_highest);

    RUN_TEST(test_weather_storm_clears_on_partial_recovery);
    RUN_TEST(test_weather_storm_stays_latched_low_confidence_no_recovery);
    RUN_TEST(test_weather_storm_stays_latched_when_buffer_empty);

    RUN_TEST(test_buzzer_silent_at_midnight);
    RUN_TEST(test_buzzer_silent_at_23h);
    RUN_TEST(test_buzzer_still_quiet_at_6h);
    RUN_TEST(test_buzzer_active_at_7h);
    RUN_TEST(test_buzzer_active_at_noon);
    RUN_TEST(test_buzzer_severe_overrides_quiet_hours);
    RUN_TEST(test_buzzer_silent_when_no_storm);

    // ── Review-fix regression + integration tests ────────────────────────────
    RUN_TEST(test_gps_alt_gain_ignores_oscillation);
    RUN_TEST(test_activity_no_false_climb_on_alt_jitter);
    RUN_TEST(test_activity_zero_now_is_stale);
    RUN_TEST(test_activity_future_timestamp_is_stale);
    RUN_TEST(test_prune_ignores_invalid_origin);
    RUN_TEST(test_banner_inactive_returns_null);
    RUN_TEST(test_banner_active_shows_confidence);
    RUN_TEST(test_integration_storm_lifecycle);
    RUN_TEST(test_integration_activity_progression);
    RUN_TEST(test_pressure_rate_linear_is_exact);
    RUN_TEST(test_pressure_rate_robust_to_noisy_endpoint);
    RUN_TEST(test_humidity_trend_per_hour_even_spacing);
    RUN_TEST(test_temp_trend_per_hour_even_spacing);
    RUN_TEST(test_humidity_trend_robust_to_uneven_spacing);
    RUN_TEST(test_score_to_confidence_rounds_not_floors);
    RUN_TEST(test_score_to_confidence_clamps);
    RUN_TEST(test_median_altitude_rejects_spike);
    RUN_TEST(test_median_altitude_empty_is_zero);
    RUN_TEST(test_median_altitude_uses_recent_window_only);
    RUN_TEST(test_trend_skips_nan_samples);
    RUN_TEST(test_all_nan_env_trend_is_zero);
    RUN_TEST(test_storm_triggers_with_dead_env_sensor);
    RUN_TEST(test_zambretti_low_pressure_boosts_confidence);
    RUN_TEST(test_zambretti_neutral_band_no_change);
    RUN_TEST(test_zambretti_deepening_low_with_humidity_reaches_storm);

    // ── minPressure corruption guard ─────────────────────────────────────────
    RUN_TEST(test_min_pressure_not_corrupted_by_empty_buffer);
    RUN_TEST(test_storm_does_not_clear_after_empty_then_trough_refill);

    // ── ActivityDetector: partial buffer ─────────────────────────────────────
    RUN_TEST(test_activity_partial_buffer_below_min_entries_is_stationary);

    // ── NijntjeEvaluator: dead AHT10 ─────────────────────────────────────────
    RUN_TEST(test_evaluator_dead_aht10_no_false_foggy);
    RUN_TEST(test_evaluator_dead_aht10_shows_cold_modifier);

    // ── bannerLine1 estimatedArrival==0 path ─────────────────────────────────
    RUN_TEST(test_banner_line1_zero_arrival_returns_likely);

    // ── BuzzerController transition tests ────────────────────────────────────
    RUN_TEST(test_buzzer_ctrl_storm_fires_on_activation);
    RUN_TEST(test_buzzer_ctrl_storm_fires_only_once);
    RUN_TEST(test_buzzer_ctrl_storm_refires_after_clear);
    RUN_TEST(test_buzzer_ctrl_rain_fires_outside_quiet_hours);
    RUN_TEST(test_buzzer_ctrl_rain_silent_in_quiet_hours);
    RUN_TEST(test_buzzer_ctrl_rain_never_overrides_quiet_hours);
    RUN_TEST(test_buzzer_ctrl_storm_beats_rain_on_same_cycle);

    return UNITY_END();
}
