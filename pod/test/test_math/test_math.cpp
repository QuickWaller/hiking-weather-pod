#include <unity.h>
#include "algorithms/MathUtils.h"

void setUp() {}
void tearDown() {}

// ── altitudeAdjustedPressure ──────────────────────────────────────────────────

void test_pressure_adj_sea_level() {
    // At 0m altitude, pressure should be unchanged
    float result = MathUtils::altitudeAdjustedPressure(1013.25f, 0.0f);
    TEST_ASSERT_FLOAT_WITHIN(0.5f, 1013.25f, result);
}

void test_pressure_adj_1000m() {
    // 1000m: ~898 hPa raw → adjusted should be close to sea level (~1013)
    float result = MathUtils::altitudeAdjustedPressure(898.0f, 1000.0f);
    TEST_ASSERT_FLOAT_WITHIN(5.0f, 1013.0f, result);
}

void test_pressure_adj_increases_with_altitude() {
    float low  = MathUtils::altitudeAdjustedPressure(900.0f, 500.0f);
    float high = MathUtils::altitudeAdjustedPressure(900.0f, 1500.0f);
    TEST_ASSERT_GREATER_THAN(low, high);
}

// ── dewPointC ─────────────────────────────────────────────────────────────────

void test_dew_point_50pct_20c() {
    // 20°C, 50% humidity → ~9.3°C dew point
    float result = MathUtils::dewPointC(20.0f, 50.0f);
    TEST_ASSERT_FLOAT_WITHIN(0.5f, 9.3f, result);
}

void test_dew_point_fog_condition() {
    // 15°C, 95% humidity → dew point ~14.1°C, spread ~0.9°C (triggers fog)
    float dp = MathUtils::dewPointC(15.0f, 95.0f);
    float spread = 15.0f - dp;
    TEST_ASSERT_FLOAT_WITHIN(0.5f, 14.1f, dp);
    TEST_ASSERT_LESS_THAN(1.5f, spread);
}

void test_dew_point_dry_condition() {
    // 25°C, 30% humidity → large spread (no fog)
    float dp = MathUtils::dewPointC(25.0f, 30.0f);
    float spread = 25.0f - dp;
    TEST_ASSERT_GREATER_THAN(1.5f, spread);
}

void test_dew_point_equals_temp_at_100pct() {
    // At 100% humidity, dew point equals temperature
    float result = MathUtils::dewPointC(15.0f, 100.0f);
    TEST_ASSERT_FLOAT_WITHIN(0.5f, 15.0f, result);
}

// ── haversineM ────────────────────────────────────────────────────────────────

void test_haversine_same_point() {
    float result = MathUtils::haversineM(-36.8485f, 174.7633f,
                                          -36.8485f, 174.7633f);
    TEST_ASSERT_FLOAT_WITHIN(0.1f, 0.0f, result);
}

void test_haversine_auckland_wellington() {
    // Auckland (-36.85, 174.76) to Wellington (-41.29, 174.78) ≈ 493km
    float result = MathUtils::haversineM(-36.8485f, 174.7633f,
                                          -41.2865f, 174.7762f);
    TEST_ASSERT_FLOAT_WITHIN(5000.0f, 493000.0f, result);
}

void test_haversine_short_distance() {
    // ~111m north (0.001 degree latitude)
    float result = MathUtils::haversineM(-41.0f, 174.0f, -40.999f, 174.0f);
    TEST_ASSERT_FLOAT_WITHIN(20.0f, 111.0f, result);
}

// ── linearRegressionSlope ─────────────────────────────────────────────────────

void test_regression_flat() {
    float values[] = {10.0f, 10.0f, 10.0f, 10.0f, 10.0f};
    float slope = MathUtils::linearRegressionSlope(values, 5);
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 0.0f, slope);
}

void test_regression_rising() {
    float values[] = {1.0f, 2.0f, 3.0f, 4.0f, 5.0f};
    float slope = MathUtils::linearRegressionSlope(values, 5);
    TEST_ASSERT_GREATER_THAN(0.0f, slope);
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 1.0f, slope);
}

void test_regression_falling() {
    float values[] = {5.0f, 4.0f, 3.0f, 2.0f, 1.0f};
    float slope = MathUtils::linearRegressionSlope(values, 5);
    TEST_ASSERT_LESS_THAN(0.0f, slope);
    TEST_ASSERT_FLOAT_WITHIN(0.01f, -1.0f, slope);
}

void test_regression_single_value() {
    float values[] = {42.0f};
    float slope = MathUtils::linearRegressionSlope(values, 1);
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 0.0f, slope);
}

// ── speedKph ──────────────────────────────────────────────────────────────────

void test_speed_zero_distance() {
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 0.0f, MathUtils::speedKph(0.0f, 60));
}

void test_speed_zero_time() {
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 0.0f, MathUtils::speedKph(100.0f, 0));
}

void test_speed_1000m_in_1min() {
    // 1000m in 60s = 60kph
    TEST_ASSERT_FLOAT_WITHIN(0.1f, 60.0f, MathUtils::speedKph(1000.0f, 60));
}

void test_speed_walking_pace() {
    // 4kph = ~67m/min = ~1.11m/s
    // 67m in 60s
    float speed = MathUtils::speedKph(67.0f, 60);
    TEST_ASSERT_FLOAT_WITHIN(0.2f, 4.02f, speed);
}

int main() {
    UNITY_BEGIN();

    RUN_TEST(test_pressure_adj_sea_level);
    RUN_TEST(test_pressure_adj_1000m);
    RUN_TEST(test_pressure_adj_increases_with_altitude);

    RUN_TEST(test_dew_point_50pct_20c);
    RUN_TEST(test_dew_point_fog_condition);
    RUN_TEST(test_dew_point_dry_condition);
    RUN_TEST(test_dew_point_equals_temp_at_100pct);

    RUN_TEST(test_haversine_same_point);
    RUN_TEST(test_haversine_auckland_wellington);
    RUN_TEST(test_haversine_short_distance);

    RUN_TEST(test_regression_flat);
    RUN_TEST(test_regression_rising);
    RUN_TEST(test_regression_falling);
    RUN_TEST(test_regression_single_value);

    RUN_TEST(test_speed_zero_distance);
    RUN_TEST(test_speed_zero_time);
    RUN_TEST(test_speed_1000m_in_1min);
    RUN_TEST(test_speed_walking_pace);

    return UNITY_END();
}
