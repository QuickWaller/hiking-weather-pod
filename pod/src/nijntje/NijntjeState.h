#pragma once
#include <stdint.h>

enum class NijntjeState : uint8_t {
    Walking,
    WalkingNight,
    Climbing,
    Resting,
    SleepyEvening,
    SleepingTent,
    Worried,
    Connected
};

enum class NijntjeModifier : uint8_t {
    None,
    Hot,
    Cold,
    Foggy
};

// Not all states use modifiers:
// Walking, Climbing, Resting: all 4 modifiers
// WalkingNight, SleepyEvening, SleepingTent, Worried, Connected: None only

enum class BannerState : uint8_t {
    None,
    Yellow,  // rain possible
    Red      // storm coming
};

struct NijntjeDisplay {
    NijntjeState    state    = NijntjeState::Walking;
    NijntjeModifier modifier = NijntjeModifier::None;
    BannerState     banner   = BannerState::None;
};
