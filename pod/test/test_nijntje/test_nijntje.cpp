#include <unity.h>
#include "algorithms/NijntjeEvaluator.h"
#include "sensors/SensorData.h"
#include "sensors/WeatherPrediction.h"

void setUp() {}
void tearDown() {}

static SensorData makeSensor(float tempC = 15.0f, float humidity = 60.0f,
                               bool connected = false) {
    SensorData s{};
    s.tempC              = tempC;
    s.humidity           = humidity;
    s.cyberdeckConnected = connected;
    return s;
}

static WeatherPrediction activePrediction(uint8_t confidence = 75) {
    WeatherPrediction p{};
    p.active     = true;
    p.confidence = confidence;
    p.baselinePressure = 1013.0f;
    return p;
}

static WeatherPrediction inactivePrediction() {
    return WeatherPrediction{};
}

// ── State priority ────────────────────────────────────────────────────────────

void test_connected_beats_everything() {
    SensorData s        = makeSensor(15.0f, 60.0f, true);
    WeatherPrediction r = activePrediction();
    WeatherPrediction st= activePrediction(90);
    NijntjeDisplay d = NijntjeEvaluator::evaluate(s, NijntjeState::Climbing, r, st);
    TEST_ASSERT_EQUAL(NijntjeState::Connected, d.state);
    TEST_ASSERT_EQUAL(NijntjeModifier::None, d.modifier);
}

void test_worried_beats_activity() {
    SensorData s        = makeSensor();
    WeatherPrediction r = inactivePrediction();
    WeatherPrediction st= activePrediction(80);
    NijntjeDisplay d = NijntjeEvaluator::evaluate(s, NijntjeState::Walking, r, st);
    TEST_ASSERT_EQUAL(NijntjeState::Worried, d.state);
}

void test_activity_used_when_no_storm() {
    SensorData s        = makeSensor();
    WeatherPrediction r = inactivePrediction();
    WeatherPrediction st= inactivePrediction();
    NijntjeDisplay d = NijntjeEvaluator::evaluate(s, NijntjeState::Climbing, r, st);
    TEST_ASSERT_EQUAL(NijntjeState::Climbing, d.state);
}

// ── Banner priority ───────────────────────────────────────────────────────────

void test_red_banner_on_storm() {
    SensorData s = makeSensor();
    NijntjeDisplay d = NijntjeEvaluator::evaluate(s, NijntjeState::Walking,
                                                   inactivePrediction(),
                                                   activePrediction(75));
    TEST_ASSERT_EQUAL(BannerState::Red, d.banner);
}

void test_yellow_banner_on_rain_no_storm() {
    SensorData s = makeSensor();
    NijntjeDisplay d = NijntjeEvaluator::evaluate(s, NijntjeState::Walking,
                                                   activePrediction(60),
                                                   inactivePrediction());
    TEST_ASSERT_EQUAL(BannerState::Yellow, d.banner);
}

void test_red_beats_yellow() {
    SensorData s = makeSensor();
    NijntjeDisplay d = NijntjeEvaluator::evaluate(s, NijntjeState::Walking,
                                                   activePrediction(60),
                                                   activePrediction(75));
    TEST_ASSERT_EQUAL(BannerState::Red, d.banner);
}

void test_no_banner_when_clear() {
    SensorData s = makeSensor();
    NijntjeDisplay d = NijntjeEvaluator::evaluate(s, NijntjeState::Walking,
                                                   inactivePrediction(),
                                                   inactivePrediction());
    TEST_ASSERT_EQUAL(BannerState::None, d.banner);
}

// ── Modifiers ─────────────────────────────────────────────────────────────────

void test_cold_modifier_on_walking() {
    SensorData s = makeSensor(5.0f, 60.0f);  // 5°C = cold
    NijntjeDisplay d = NijntjeEvaluator::evaluate(s, NijntjeState::Walking,
                                                   inactivePrediction(),
                                                   inactivePrediction());
    TEST_ASSERT_EQUAL(NijntjeModifier::Cold, d.modifier);
}

void test_hot_modifier_on_walking() {
    SensorData s = makeSensor(30.0f, 40.0f);  // 30°C = hot
    NijntjeDisplay d = NijntjeEvaluator::evaluate(s, NijntjeState::Walking,
                                                   inactivePrediction(),
                                                   inactivePrediction());
    TEST_ASSERT_EQUAL(NijntjeModifier::Hot, d.modifier);
}

void test_foggy_modifier_on_walking() {
    // 15°C, 96% humidity → dew point ~14.2°C, spread ~0.8°C → foggy
    SensorData s = makeSensor(15.0f, 96.0f);
    NijntjeDisplay d = NijntjeEvaluator::evaluate(s, NijntjeState::Walking,
                                                   inactivePrediction(),
                                                   inactivePrediction());
    TEST_ASSERT_EQUAL(NijntjeModifier::Foggy, d.modifier);
}

void test_foggy_beats_cold() {
    // Fog conditions + cold temp: Foggy takes priority
    SensorData s = makeSensor(6.0f, 96.0f);  // cold AND foggy
    NijntjeDisplay d = NijntjeEvaluator::evaluate(s, NijntjeState::Walking,
                                                   inactivePrediction(),
                                                   inactivePrediction());
    TEST_ASSERT_EQUAL(NijntjeModifier::Foggy, d.modifier);
}

void test_no_modifier_on_walking_night() {
    SensorData s = makeSensor(5.0f, 96.0f);  // cold + foggy, but WalkingNight has no modifier
    NijntjeDisplay d = NijntjeEvaluator::evaluate(s, NijntjeState::WalkingNight,
                                                   inactivePrediction(),
                                                   inactivePrediction());
    TEST_ASSERT_EQUAL(NijntjeModifier::None, d.modifier);
}

void test_no_modifier_on_sleeping_tent() {
    SensorData s = makeSensor(3.0f, 97.0f);
    NijntjeDisplay d = NijntjeEvaluator::evaluate(s, NijntjeState::SleepingTent,
                                                   inactivePrediction(),
                                                   inactivePrediction());
    TEST_ASSERT_EQUAL(NijntjeModifier::None, d.modifier);
}

void test_no_modifier_on_worried() {
    SensorData s = makeSensor(3.0f, 97.0f);
    NijntjeDisplay d = NijntjeEvaluator::evaluate(s, NijntjeState::Walking,
                                                   inactivePrediction(),
                                                   activePrediction(80));
    // Worried state (from storm) should have no modifier
    TEST_ASSERT_EQUAL(NijntjeState::Worried, d.state);
    TEST_ASSERT_EQUAL(NijntjeModifier::None, d.modifier);
}

void test_modifier_on_resting() {
    SensorData s = makeSensor(5.0f, 60.0f);  // cold
    NijntjeDisplay d = NijntjeEvaluator::evaluate(s, NijntjeState::Resting,
                                                   inactivePrediction(),
                                                   inactivePrediction());
    TEST_ASSERT_EQUAL(NijntjeModifier::Cold, d.modifier);
}

void test_modifier_on_climbing() {
    SensorData s = makeSensor(30.0f, 40.0f);  // hot
    NijntjeDisplay d = NijntjeEvaluator::evaluate(s, NijntjeState::Climbing,
                                                   inactivePrediction(),
                                                   inactivePrediction());
    TEST_ASSERT_EQUAL(NijntjeModifier::Hot, d.modifier);
}

// ── All 8 states reachable ────────────────────────────────────────────────────

void test_all_states_reachable() {
    SensorData s = makeSensor();
    WeatherPrediction none = inactivePrediction();

    auto eval = [&](NijntjeState act, bool connected, bool storm) {
        s.cyberdeckConnected = connected;
        WeatherPrediction st = storm ? activePrediction(80) : inactivePrediction();
        return NijntjeEvaluator::evaluate(s, act, none, st).state;
    };

    TEST_ASSERT_EQUAL(NijntjeState::Connected,    eval(NijntjeState::Walking, true, false));
    TEST_ASSERT_EQUAL(NijntjeState::Worried,      eval(NijntjeState::Walking, false, true));
    TEST_ASSERT_EQUAL(NijntjeState::Climbing,     eval(NijntjeState::Climbing, false, false));
    TEST_ASSERT_EQUAL(NijntjeState::Resting,      eval(NijntjeState::Resting, false, false));
    TEST_ASSERT_EQUAL(NijntjeState::WalkingNight, eval(NijntjeState::WalkingNight, false, false));
    TEST_ASSERT_EQUAL(NijntjeState::SleepyEvening,eval(NijntjeState::SleepyEvening, false, false));
    TEST_ASSERT_EQUAL(NijntjeState::SleepingTent, eval(NijntjeState::SleepingTent, false, false));
    TEST_ASSERT_EQUAL(NijntjeState::Walking,      eval(NijntjeState::Walking, false, false));
}

int main() {
    UNITY_BEGIN();

    RUN_TEST(test_connected_beats_everything);
    RUN_TEST(test_worried_beats_activity);
    RUN_TEST(test_activity_used_when_no_storm);

    RUN_TEST(test_red_banner_on_storm);
    RUN_TEST(test_yellow_banner_on_rain_no_storm);
    RUN_TEST(test_red_beats_yellow);
    RUN_TEST(test_no_banner_when_clear);

    RUN_TEST(test_cold_modifier_on_walking);
    RUN_TEST(test_hot_modifier_on_walking);
    RUN_TEST(test_foggy_modifier_on_walking);
    RUN_TEST(test_foggy_beats_cold);
    RUN_TEST(test_no_modifier_on_walking_night);
    RUN_TEST(test_no_modifier_on_sleeping_tent);
    RUN_TEST(test_no_modifier_on_worried);
    RUN_TEST(test_modifier_on_resting);
    RUN_TEST(test_modifier_on_climbing);

    RUN_TEST(test_all_states_reachable);

    return UNITY_END();
}
