#pragma once
#include <stdint.h>

struct Aht10Reading {
    float tempC;
    float humidity;
    bool  valid;
};

class Aht10Reader {
public:
    bool         begin();
    Aht10Reading read();
};
