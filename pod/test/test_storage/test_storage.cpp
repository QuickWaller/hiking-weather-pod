#include <unity.h>
#include <string.h>
#include "storage/SdLogger.h"
#include "algorithms/MathUtils.h"

void setUp() {}
void tearDown() {}

// ── SdLogger::buildPath ───────────────────────────────────────────────────────

void test_build_path_known_date() {
    // 2026-06-15 12:00:00 UTC = 1781496000
    uint32_t t = MathUtils::unixFromDateTime(2026, 6, 15, 12, 0, 0);
    char buf[40];
    SdLogger::buildPath(buf, sizeof(buf), "raw", t);
    TEST_ASSERT_EQUAL_STRING("/raw/2026-06-15.csv", buf);
}

void test_build_path_midnight_utc() {
    // Exactly midnight on 2026-01-01 UTC
    uint32_t t = MathUtils::unixFromDateTime(2026, 1, 1, 0, 0, 0);
    char buf[40];
    SdLogger::buildPath(buf, sizeof(buf), "inputs", t);
    TEST_ASSERT_EQUAL_STRING("/inputs/2026-01-01.csv", buf);
}

void test_build_path_end_of_day() {
    // 2026-12-31 23:59:59 UTC stays on Dec 31
    uint32_t t = MathUtils::unixFromDateTime(2026, 12, 31, 23, 59, 59);
    char buf[40];
    SdLogger::buildPath(buf, sizeof(buf), "pred", t);
    TEST_ASSERT_EQUAL_STRING("/pred/2026-12-31.csv", buf);
}

void test_build_path_events_dir() {
    uint32_t t = MathUtils::unixFromDateTime(2026, 6, 15, 0, 0, 0);
    char buf[40];
    SdLogger::buildPath(buf, sizeof(buf), "events", t);
    TEST_ASSERT_EQUAL_STRING("/events/2026-06-15.csv", buf);
}

void test_build_path_different_times_same_utc_day() {
    uint32_t t1 = MathUtils::unixFromDateTime(2026, 6, 15,  0, 0, 0);
    uint32_t t2 = MathUtils::unixFromDateTime(2026, 6, 15, 23, 59, 59);
    char buf1[40], buf2[40];
    SdLogger::buildPath(buf1, sizeof(buf1), "raw", t1);
    SdLogger::buildPath(buf2, sizeof(buf2), "raw", t2);
    TEST_ASSERT_EQUAL_STRING(buf1, buf2);  // same day → same file
}

// ── SdLogger::rawHeader ───────────────────────────────────────────────────────

void test_raw_header_contains_timestamp() {
    const char* h = SdLogger::rawHeader();
    TEST_ASSERT_NOT_NULL(strstr(h, "timestamp"));
}

void test_raw_header_contains_pressure() {
    const char* h = SdLogger::rawHeader();
    TEST_ASSERT_NOT_NULL(strstr(h, "pressure_adj"));
}

void test_raw_header_starts_with_timestamp() {
    const char* h = SdLogger::rawHeader();
    TEST_ASSERT_EQUAL_INT(0, strncmp(h, "timestamp", 9));
}

// ── SdLogger::inputsHeader ────────────────────────────────────────────────────

void test_inputs_header_timestamp_first() {
    const char* names[] = {"pressure_hpa", "temp_c"};
    char buf[128];
    const char* h = SdLogger::inputsHeader(names, 2, buf, sizeof(buf));
    TEST_ASSERT_EQUAL_INT(0, strncmp(h, "timestamp", 9));
}

void test_inputs_header_includes_feature_names() {
    const char* names[] = {"pressure_hpa", "temp_c"};
    char buf[128];
    const char* h = SdLogger::inputsHeader(names, 2, buf, sizeof(buf));
    TEST_ASSERT_NOT_NULL(strstr(h, "pressure_hpa"));
    TEST_ASSERT_NOT_NULL(strstr(h, "temp_c"));
}

void test_inputs_header_empty_names() {
    char buf[64];
    const char* h = SdLogger::inputsHeader(nullptr, 0, buf, sizeof(buf));
    TEST_ASSERT_EQUAL_STRING("timestamp", h);
}

// ── SdLogger::eventHeader ─────────────────────────────────────────────────────

void test_event_header_fields() {
    const char* h = SdLogger::eventHeader();
    TEST_ASSERT_NOT_NULL(strstr(h, "timestamp"));
    TEST_ASSERT_NOT_NULL(strstr(h, "level"));
    TEST_ASSERT_NOT_NULL(strstr(h, "code"));
}

// ── main ─────────────────────────────────────────────────────────────────────

int main() {
    UNITY_BEGIN();

    RUN_TEST(test_build_path_known_date);
    RUN_TEST(test_build_path_midnight_utc);
    RUN_TEST(test_build_path_end_of_day);
    RUN_TEST(test_build_path_events_dir);
    RUN_TEST(test_build_path_different_times_same_utc_day);

    RUN_TEST(test_raw_header_contains_timestamp);
    RUN_TEST(test_raw_header_contains_pressure);
    RUN_TEST(test_raw_header_starts_with_timestamp);

    RUN_TEST(test_inputs_header_timestamp_first);
    RUN_TEST(test_inputs_header_includes_feature_names);
    RUN_TEST(test_inputs_header_empty_names);

    RUN_TEST(test_event_header_fields);

    return UNITY_END();
}
