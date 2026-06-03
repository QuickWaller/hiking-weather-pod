// Native unit tests for the B/W compass display helpers.
// Currently covers BWRenderer::compassIndex — the heading→frame bucket map that
// the live stream uses to pick one of 16 pre-baked compass frames. Pure logic,
// no Arduino/Wire deps, so it runs in the `native` env.

#include <unity.h>
#include "display/BWRenderer.h"

void setUp() {}
void tearDown() {}

// ── compassIndex: 16 buckets, 22.5° each, 0 = North, clockwise ────────────────

void test_index_cardinals() {
    TEST_ASSERT_EQUAL_INT(0,  BWRenderer::compassIndex(0.0f));    // N
    TEST_ASSERT_EQUAL_INT(4,  BWRenderer::compassIndex(90.0f));   // E
    TEST_ASSERT_EQUAL_INT(8,  BWRenderer::compassIndex(180.0f));  // S
    TEST_ASSERT_EQUAL_INT(12, BWRenderer::compassIndex(270.0f));  // W
}

void test_index_intercardinals() {
    TEST_ASSERT_EQUAL_INT(1, BWRenderer::compassIndex(22.5f));   // NNE
    TEST_ASSERT_EQUAL_INT(2, BWRenderer::compassIndex(45.0f));   // NE
    TEST_ASSERT_EQUAL_INT(6, BWRenderer::compassIndex(135.0f));  // SE
}

void test_index_wraps_at_360() {
    TEST_ASSERT_EQUAL_INT(0, BWRenderer::compassIndex(360.0f));
    TEST_ASSERT_EQUAL_INT(0, BWRenderer::compassIndex(359.0f));   // rounds to 16 → 0
    TEST_ASSERT_EQUAL_INT(0, BWRenderer::compassIndex(348.75f));  // NNW boundary back to N
}

void test_index_rounds_to_nearest_bucket() {
    TEST_ASSERT_EQUAL_INT(0, BWRenderer::compassIndex(11.0f));   // just below the N/NNE split
    TEST_ASSERT_EQUAL_INT(1, BWRenderer::compassIndex(12.0f));   // just above it
}

void test_index_negative_headings_normalise() {
    TEST_ASSERT_EQUAL_INT(15, BWRenderer::compassIndex(-22.5f));  // = 337.5 → NNW
    TEST_ASSERT_EQUAL_INT(0,  BWRenderer::compassIndex(-1.0f));   // ≈ 359 → N
}

int main() {
    UNITY_BEGIN();
    RUN_TEST(test_index_cardinals);
    RUN_TEST(test_index_intercardinals);
    RUN_TEST(test_index_wraps_at_360);
    RUN_TEST(test_index_rounds_to_nearest_bucket);
    RUN_TEST(test_index_negative_headings_normalise);
    return UNITY_END();
}
