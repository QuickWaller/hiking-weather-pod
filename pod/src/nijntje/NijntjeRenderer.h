#pragma once
#include "NijntjeState.h"

class Framebuffer;

class NijntjeRenderer {
public:
    static void render(Framebuffer& fb, const NijntjeDisplay& d);
};
