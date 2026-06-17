#pragma once
#include <stdint.h>

struct Bme280Reading {
    float pressureHpa;
    float tempC;
    float humidity;   // % RH
    bool  valid;
};

class Bme280Reader {
public:
    bool         begin();
    Bme280Reading read();
};
