#pragma once
#include <stdint.h>

struct Bmp180Reading {
    float pressureHpa;
    float tempC;
    bool  valid;
};

class Bmp180Reader {
public:
    bool          begin();
    Bmp180Reading read();
};
