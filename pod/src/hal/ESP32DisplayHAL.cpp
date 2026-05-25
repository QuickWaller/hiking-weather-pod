#include "ESP32DisplayHAL.h"
#include <Arduino.h>

ESP32DisplayHAL::ESP32DisplayHAL(uint8_t pinCS, uint8_t pinDC, uint8_t pinReset, uint8_t pinBusy,
                                  uint8_t pinSCK, uint8_t pinMOSI)
    : _pinCS(pinCS), _pinDC(pinDC), _pinReset(pinReset), _pinBusy(pinBusy),
      _pinSCK(pinSCK), _pinMOSI(pinMOSI) {}

void ESP32DisplayHAL::begin() {
    pinMode(_pinCS,    OUTPUT); digitalWrite(_pinCS,    HIGH);
    pinMode(_pinDC,    OUTPUT); digitalWrite(_pinDC,    HIGH);
    pinMode(_pinReset, OUTPUT); digitalWrite(_pinReset, HIGH);
    pinMode(_pinBusy,  INPUT_PULLUP);
    pinMode(_pinSCK,   OUTPUT); digitalWrite(_pinSCK,   LOW);
    pinMode(_pinMOSI,  OUTPUT); digitalWrite(_pinMOSI,  LOW);
}

void ESP32DisplayHAL::spiWrite(uint8_t byte) {
    for (int i = 0; i < 8; i++) {
        digitalWrite(_pinMOSI, (byte & 0x80) ? HIGH : LOW);
        byte <<= 1;
        digitalWrite(_pinSCK, HIGH);
        digitalWrite(_pinSCK, LOW);
    }
}

void ESP32DisplayHAL::setCS(bool high) {
    digitalWrite(_pinCS, high ? HIGH : LOW);
}

void ESP32DisplayHAL::setDC(bool high) {
    digitalWrite(_pinDC, high ? HIGH : LOW);
}

void ESP32DisplayHAL::setReset(bool high) {
    digitalWrite(_pinReset, high ? HIGH : LOW);
}

bool ESP32DisplayHAL::readBusy() {
    return digitalRead(_pinBusy) == HIGH;
}

void ESP32DisplayHAL::delayMs(uint32_t ms) {
    delay(ms);
}
