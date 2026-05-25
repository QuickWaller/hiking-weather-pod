#pragma once
#include <stdint.h>

enum class NijntjeState : uint8_t {
    Walking,
    Tired,
    Climbing,
    Sleepy,
    Worried,
    Connected
};

enum class NijntjeModifier : uint8_t {
    None,
    Hot,
    Cold,
    Foggy
};

enum class BannerState : uint8_t {
    None,
    Yellow,
    Red
};

struct NijntjeDisplay {
    NijntjeState    state    = NijntjeState::Walking;
    NijntjeModifier modifier = NijntjeModifier::None;
    BannerState     banner   = BannerState::None;
};
