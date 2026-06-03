#pragma once
#include "NijntjeState.h"

class IFramebuffer;

class NijntjeRenderer {
public:
    static void render(IFramebuffer& fb, const NijntjeDisplay& d);
};
