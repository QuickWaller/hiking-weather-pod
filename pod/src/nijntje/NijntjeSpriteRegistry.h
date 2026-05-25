#pragma once
#include "NijntjeState.h"
#include <stdint.h>

struct NijntjeSprite {
    const uint8_t* data;
    uint16_t       width;
    uint16_t       height;
};

NijntjeSprite lookupSprite(NijntjeState state, NijntjeModifier modifier);
