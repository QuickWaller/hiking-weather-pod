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

// ── unixFromDateTime / dateTimeFromUnix ───────────────────────────────────────

void test_unix_epoch() {
    TEST_ASSERT_EQUAL_UINT32(0, MathUtils::unixFromDateTime(1970, 1, 1, 0, 0, 0));
}

void test_unix_y2k() {
    // 2000-01-01 00:00:00 UTC = 946684800
    TEST_ASSERT_EQUAL_UINT32(946684800UL, MathUtils::unixFromDateTime(2000, 1, 1, 0, 0, 0));
}

void test_unix_known_date() {
    // 2026-05-31 00:00:00 UTC = 1780185600
    TEST_ASSERT_EQUAL_UINT32(1780185600UL, MathUtils::unixFromDateTime(2026, 5, 31, 0, 0, 0));
}

void test_unix_time_components() {
    // 2026-05-31 12:30:45
    uint32_t expected = 1780185600UL + 12*3600UL + 30*60UL + 45UL;
    TEST_ASSERT_EQUAL_UINT32(expected, MathUtils::unixFromDateTime(2026, 5, 31, 12, 30, 45));
}

void test_unix_leap_day() {
    // 2024-02-29 exists (2024 is a leap year)
    uint32_t feb28 = MathUtils::unixFromDateTime(2024, 2, 28, 0, 0, 0);
    uint32_t feb29 = MathUtils::unixFromDateTime(2024, 2, 29, 0, 0, 0);
    TEST_ASSERT_EQUAL_UINT32(86400UL, feb29 - feb28);
}

void test_unix_roundtrip() {
    uint32_t original = MathUtils::unixFromDateTime(2026, 3, 15, 8, 45, 30);
    uint16_t year; uint8_t month, day, hour, minute, second;
    MathUtils::dateTimeFromUnix(original, year, month, day, hour, minute, second);
    TEST_ASSERT_EQUAL_UINT16(2026, year);
    TEST_ASSERT_EQUAL_UINT8(3,  month);
    TEST_ASSERT_EQUAL_UINT8(15, day);
    TEST_ASSERT_EQUAL_UINT8(8,  hour);
    TEST_ASSERT_EQUAL_UINT8(45, minute);
    TEST_ASSERT_EQUAL_UINT8(30, second);
}

void test_unix_roundtrip_leap_day() {
    uint32_t ts = MathUtils::unixFromDateTime(2024, 2, 29, 0, 0, 0);
    uint16_t year; uint8_t month, day, hour, minute, second;
    MathUtils::dateTimeFromUnix(ts, year, month, day, hour, minute, second);
    TEST_ASSERT_EQUAL_UINT16(2024, year);
    TEST_ASSERT_EQUAL_UINT8(2, month);
    TEST_ASSERT_EQUAL_UINT8(29, day);
}

// ── median ────────────────────────────────────────────────────────────────────

void test_median_odd_count() {
    float v[] = {3.0f, 1.0f, 2.0f};
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 2.0f, MathUtils::median(v, 3));
}

void test_median_even_count_averages_middle() {
    float v[] = {1.0f, 2.0f, 3.0f, 4.0f};
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 2.5f, MathUtils::median(v, 4));
}

void test_median_rejects_single_spike() {
    // Four good ~100m readings + one 400m spike → median stays ~100, mean would be ~160.
    float v[] = {100.0f, 102.0f, 99.0f, 101.0f, 400.0f};
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 101.0f, MathUtils::median(v, 5));
}

void test_median_single_and_empty() {
    float v[] = {42.0f};
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 42.0f, MathUtils::median(v, 1));
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 0.0f, MathUtils::median(v, 0));
}

// ── linearRegressionSlopeXY (explicit x, for unevenly-spaced samples) ─────────

void test_regression_xy_even_matches_index() {
    // Even spacing should match the index-based regression.
    float xs[] = {0, 1, 2, 3, 4};
    float ys[] = {1, 2, 3, 4, 5};
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 1.0f, MathUtils::linearRegressionSlopeXY(xs, ys, 5));
}

void test_regression_xy_uneven_spacing() {
    // y = 10 + 2x at irregular x → slope 2 regardless of spacing.
    float xs[] = {0, 1, 3, 6};
    float ys[] = {10, 12, 16, 22};
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 2.0f, MathUtils::linearRegressionSlopeXY(xs, ys, 4));
}

void test_regression_xy_all_x_equal_returns_zero() {
    float xs[] = {5, 5, 5};
    float ys[] = {1, 9, 4};
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 0.0f, MathUtils::linearRegressionSlopeXY(xs, ys, 3));
}

void test_regression_xy_single_point_returns_zero() {
    float xs[] = {3};
    float ys[] = {7};
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 0.0f, MathUtils::linearRegressionSlopeXY(xs, ys, 1));
}

// ── Regression: dew point sensor-failure / out-of-range humidity ──────────────

void test_dew_point_zero_humidity_safe() {
    // Failed AHT10 reports humidity 0 → logf(0) would be -inf → NaN without the clamp.
    float dp = MathUtils::dewPointC(15.0f, 0.0f);
    TEST_ASSERT_TRUE(dp == dp);            // not NaN
    TEST_ASSERT_TRUE(dp <= 15.0f + 0.01f); // dew point never exceeds temperature
}

void test_dew_point_over_100_humidity_clamped() {
    // Bad reading >100% clamps to 100% → dew point ~ temperature.
    float dp = MathUtils::dewPointC(15.0f, 150.0f);
    TEST_ASSERT_TRUE(dp == dp);
    TEST_ASSERT_FLOAT_WITHIN(1.0f, 15.0f, dp);
}

// ── Regression: invalid month must not index doy[] out of bounds ──────────────

void test_unix_invalid_month_returns_zero() {
    TEST_ASSERT_EQUAL_UINT32(0, MathUtils::unixFromDateTime(2026, 0,  1, 0, 0, 0));
    TEST_ASSERT_EQUAL_UINT32(0, MathUtils::unixFromDateTime(2026, 13, 1, 0, 0, 0));
}

// ── nzUtcOffsetMinutes (DST) ──────────────────────────────────────────────────

void test_nz_offset_winter_is_nzst() {
    // Mid-July is austral winter → NZST = +720.
    uint32_t utc = MathUtils::unixFromDateTime(2026, 7, 15, 0, 0, 0);
    TEST_ASSERT_EQUAL_INT(720, MathUtils::nzUtcOffsetMinutes(utc));
}

void test_nz_offset_summer_is_nzdt() {
    // Mid-January is austral summer → NZDT = +780.
    uint32_t utc = MathUtils::unixFromDateTime(2026, 1, 15, 0, 0, 0);
    TEST_ASSERT_EQUAL_INT(780, MathUtils::nzUtcOffsetMinutes(utc));
}

void test_nz_offset_around_transitions() {
    // Well clear of the transition Sundays so the 12–13h offset can't reclassify them.
    // Early Sep = still NZST; mid-Oct = NZDT; early Mar = still NZDT; early May = NZST.
    TEST_ASSERT_EQUAL_INT(720, MathUtils::nzUtcOffsetMinutes(
        MathUtils::unixFromDateTime(2026, 9, 1, 0, 0, 0)));
    TEST_ASSERT_EQUAL_INT(780, MathUtils::nzUtcOffsetMinutes(
        MathUtils::unixFromDateTime(2026, 10, 15, 0, 0, 0)));
    TEST_ASSERT_EQUAL_INT(780, MathUtils::nzUtcOffsetMinutes(
        MathUtils::unixFromDateTime(2026, 3, 1, 0, 0, 0)));
    TEST_ASSERT_EQUAL_INT(720, MathUtils::nzUtcOffsetMinutes(
        MathUtils::unixFromDateTime(2026, 5, 1, 0, 0, 0)));
}

// ── dayOfYear ─────────────────────────────────────────────────────────────────

void test_day_of_year_jan_first() {
    TEST_ASSERT_EQUAL_INT(1, MathUtils::dayOfYear(2026, 1, 1));
}

void test_day_of_year_dec_last_non_leap() {
    TEST_ASSERT_EQUAL_INT(365, MathUtils::dayOfYear(2026, 12, 31));
}

void test_day_of_year_leap_year() {
    TEST_ASSERT_EQUAL_INT(366, MathUtils::dayOfYear(2024, 12, 31));  // 2024 is leap
    TEST_ASSERT_EQUAL_INT(61,  MathUtils::dayOfYear(2024, 3, 1));    // 31+29+1
    TEST_ASSERT_EQUAL_INT(60,  MathUtils::dayOfYear(2026, 3, 1));    // 31+28+1 (non-leap)
}

// ── tiltCompensatedHeading ────────────────────────────────────────────────────

// Flat (level) device: formula reduces to atan2(my, mx), 0° = north, clockwise —
// the same convention as the 2D CompassReader::read() path.
void test_tilt_comp_flat_north() {
    float h = MathUtils::tiltCompensatedHeading(1000, 0, 0,  0, 0, 1.0f,  0, 0, 0);
    TEST_ASSERT_FLOAT_WITHIN(1.0f, 0.0f, h);
}

void test_tilt_comp_flat_south() {
    float h = MathUtils::tiltCompensatedHeading(-1000, 0, 0,  0, 0, 1.0f,  0, 0, 0);
    TEST_ASSERT_FLOAT_WITHIN(1.0f, 180.0f, h);
}

void test_tilt_comp_flat_east() {
    // Clockwise convention: east = my positive (atan2(1000, 0) = 90°)
    float h = MathUtils::tiltCompensatedHeading(0, 1000, 0,  0, 0, 1.0f,  0, 0, 0);
    TEST_ASSERT_FLOAT_WITHIN(1.0f, 90.0f, h);
}

void test_tilt_comp_flat_west() {
    float h = MathUtils::tiltCompensatedHeading(0, -1000, 0,  0, 0, 1.0f,  0, 0, 0);
    TEST_ASSERT_FLOAT_WITHIN(1.0f, 270.0f, h);
}

void test_tilt_comp_flat_northeast() {
    // Equal mx and my → atan2(707, 707) = 45°
    float h = MathUtils::tiltCompensatedHeading(707, 707, 0,  0, 0, 1.0f,  0, 0, 0);
    TEST_ASSERT_FLOAT_WITHIN(1.0f, 45.0f, h);
}

// Tilt stability: heading should stay at 0° when device is rolled or pitched,
// because the formula corrects for the Earth-field components that shift axes.
// Values derived from physical model: Bh=1000, Bv=577 (NZ-ish dip).

void test_tilt_comp_rolled_30_north_stable() {
    // Rolled +30°: my=-289 (≈-Bv·sin30°), mz=-500 (≈-Bv·cos30°)
    float h = MathUtils::tiltCompensatedHeading(1000, -289, -500,  0, 0.5f, 0.866f,  0, 0, 0);
    // Residual may sit just below 360° due to rounding — normalise before compare
    float n = (h > 180.0f) ? h - 360.0f : h;
    TEST_ASSERT_FLOAT_WITHIN(1.0f, 0.0f, n);
}

void test_tilt_comp_rolled_neg30_north_stable() {
    // Rolled -30°: sign of my/ay flips
    float h = MathUtils::tiltCompensatedHeading(1000, 289, -500,  0, -0.5f, 0.866f,  0, 0, 0);
    // May wrap to near 360° due to rounding — normalise before compare
    float n = (h > 180.0f) ? h - 360.0f : h;
    TEST_ASSERT_FLOAT_WITHIN(1.0f, 0.0f, n);
}

void test_tilt_comp_pitched_45_north_stable() {
    // Nose-down 45°: mz picks up a vertical field component.
    // From physical model: mx=1115 (≈Bh·cos45°+Bv·sin45°), mz=299 (≈(Bh-Bv)·cos45°).
    // ax=-0.707 (nose down), az=0.707.
    float h = MathUtils::tiltCompensatedHeading(1115, 0, 299,  -0.707f, 0, 0.707f,  0, 0, 0);
    TEST_ASSERT_FLOAT_WITHIN(1.0f, 0.0f, h);
}

// Hard-iron offset: a constant magnetic bias (e.g. from the buzzer) shifts the
// raw reading. Providing the correct offset should restore the true heading.
void test_tilt_comp_offset_corrects_bias() {
    // True north (cx=1000, cy=0) but raw reading biased: mx=1000+0, my=0+200=200
    // Without offset: cx=1000, cy=200 → heading ≈ 11° off north
    // With offset (0, 200, 0): cx=1000, cy=0 → heading = 0°
    float h_uncal = MathUtils::tiltCompensatedHeading(1000, 200, 0,  0, 0, 1.0f,  0, 0, 0);
    float h_cal   = MathUtils::tiltCompensatedHeading(1000, 200, 0,  0, 0, 1.0f,  0, 200, 0);
    TEST_ASSERT_FALSE(h_uncal < 1.0f);       // uncalibrated is not north
    TEST_ASSERT_FLOAT_WITHIN(1.0f, 0.0f, h_cal);
}

void test_tilt_comp_zero_offsets_passthrough() {
    // Zero offsets must not alter the reading
    float h1 = MathUtils::tiltCompensatedHeading(500, -300, 0,  0, 0, 1.0f,  0, 0, 0);
    float h2 = MathUtils::tiltCompensatedHeading(500, -300, 0,  0, 0, 1.0f,  0, 0, 0);
    TEST_ASSERT_FLOAT_WITHIN(0.001f, h1, h2);
}

// Regression: tilt comp is sensitive to the accel→compass axis remap that
// CompassReader::readTilted applies (ACCEL_YAW_QUADRANT, the two breakouts are
// mounted yawed). Feeding mis-rotated accel throws the heading ~70° off; the
// remapped accel lands near the true value. Field sample: tilted ~14°,
// mag(-119,179,636); negated-X/Y accel → ≈146° vs raw accel → ≈79°.
void test_tilt_comp_180yaw_accel_remap() {
    float raw      = MathUtils::tiltCompensatedHeading(-119, 179, 636,  0.264f, 0.0f, 1.08f,  0, 0, 0);
    float remapped = MathUtils::tiltCompensatedHeading(-119, 179, 636, -0.264f, 0.0f, 1.08f,  0, 0, 0);
    TEST_ASSERT_FLOAT_WITHIN(8.0f, 146.0f, remapped);       // remap restores true heading
    TEST_ASSERT_TRUE(fabsf(raw - remapped) > 40.0f);        // raw is wildly off
}

// Regression guard: when level, tiltCompensatedHeading() must agree with the 2D
// CompassReader::read() formula atan2(y, x). A sign mismatch here previously
// mirrored E/W between the two paths (compass turned the wrong way).
void test_tilt_comp_matches_flat_read_convention() {
    const int16_t pts[][2] = { {1000, 0}, {0, 1000}, {-1000, 0}, {0, -1000},
                               {707, 707}, {707, -707}, {500, -300} };
    for (auto& p : pts) {
        float flat = atan2f((float)p[1], (float)p[0]) * 180.0f / 3.14159265358979f;
        if (flat < 0.0f) flat += 360.0f;
        float tilt = MathUtils::tiltCompensatedHeading(p[0], p[1], 0,  0, 0, 1.0f,  0, 0, 0);
        TEST_ASSERT_FLOAT_WITHIN(0.5f, flat, tilt);
    }
}

// ── sunriseSunsetMinutes ──────────────────────────────────────────────────────

void test_sun_sunrise_before_sunset() {
    int16_t rise, set;
    MathUtils::sunriseSunsetMinutes(-41.29f, 174.78f, 172, 720, rise, set);  // Wellington, ~Jun 21
    TEST_ASSERT_TRUE(rise >= 0 && set >= 0);
    TEST_ASSERT_TRUE(rise < set);
}

void test_sun_summer_day_longer_than_winter() {
    int16_t wRise, wSet, sRise, sSet;
    MathUtils::sunriseSunsetMinutes(-41.29f, 174.78f, 172, 720, wRise, wSet);  // winter solstice
    MathUtils::sunriseSunsetMinutes(-41.29f, 174.78f, 355, 780, sRise, sSet);  // summer solstice
    // Day length is independent of the UTC offset (both ends shift equally).
    TEST_ASSERT_TRUE((sSet - sRise) > (wSet - wRise));
}

void test_sun_wellington_winter_reasonable() {
    // Wellington winter solstice (NZST): sunrise ~07:45, sunset ~17:00 in reality.
    int16_t rise, set;
    MathUtils::sunriseSunsetMinutes(-41.29f, 174.78f, 172, 720, rise, set);
    TEST_ASSERT_INT_WITHIN(60, 7 * 60 + 45, rise);
    TEST_ASSERT_INT_WITHIN(60, 17 * 60,     set);
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

    RUN_TEST(test_unix_epoch);
    RUN_TEST(test_unix_y2k);
    RUN_TEST(test_unix_known_date);
    RUN_TEST(test_unix_time_components);
    RUN_TEST(test_unix_leap_day);
    RUN_TEST(test_unix_roundtrip);
    RUN_TEST(test_unix_roundtrip_leap_day);

    RUN_TEST(test_median_odd_count);
    RUN_TEST(test_median_even_count_averages_middle);
    RUN_TEST(test_median_rejects_single_spike);
    RUN_TEST(test_median_single_and_empty);

    RUN_TEST(test_regression_xy_even_matches_index);
    RUN_TEST(test_regression_xy_uneven_spacing);
    RUN_TEST(test_regression_xy_all_x_equal_returns_zero);
    RUN_TEST(test_regression_xy_single_point_returns_zero);

    RUN_TEST(test_dew_point_zero_humidity_safe);
    RUN_TEST(test_dew_point_over_100_humidity_clamped);
    RUN_TEST(test_unix_invalid_month_returns_zero);

    RUN_TEST(test_nz_offset_winter_is_nzst);
    RUN_TEST(test_nz_offset_summer_is_nzdt);
    RUN_TEST(test_nz_offset_around_transitions);

    RUN_TEST(test_day_of_year_jan_first);
    RUN_TEST(test_day_of_year_dec_last_non_leap);
    RUN_TEST(test_day_of_year_leap_year);

    RUN_TEST(test_sun_sunrise_before_sunset);
    RUN_TEST(test_sun_summer_day_longer_than_winter);
    RUN_TEST(test_sun_wellington_winter_reasonable);

    RUN_TEST(test_tilt_comp_flat_north);
    RUN_TEST(test_tilt_comp_flat_south);
    RUN_TEST(test_tilt_comp_flat_east);
    RUN_TEST(test_tilt_comp_flat_west);
    RUN_TEST(test_tilt_comp_flat_northeast);
    RUN_TEST(test_tilt_comp_rolled_30_north_stable);
    RUN_TEST(test_tilt_comp_rolled_neg30_north_stable);
    RUN_TEST(test_tilt_comp_pitched_45_north_stable);
    RUN_TEST(test_tilt_comp_offset_corrects_bias);
    RUN_TEST(test_tilt_comp_zero_offsets_passthrough);
    RUN_TEST(test_tilt_comp_matches_flat_read_convention);
    RUN_TEST(test_tilt_comp_180yaw_accel_remap);

    return UNITY_END();
}
