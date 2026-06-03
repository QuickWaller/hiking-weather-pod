#include "UartSync.h"
#include "config.h"

#ifndef NATIVE_TEST
#include <Arduino.h>
#include <LittleFS.h>
#include <string.h>

#ifdef ARDUINO_ARCH_RP2040
  #define DECK_SERIAL Serial1
#else
  #define DECK_SERIAL Serial1
#endif

void UartSync::begin() {
#ifdef ARDUINO_ARCH_RP2040
    Serial1.setTX(PIN_CYBERDECK_TX);
    Serial1.setRX(PIN_CYBERDECK_RX);
    Serial1.begin(115200);
#else
    Serial1.begin(115200, SERIAL_8N1, PIN_CYBERDECK_RX, PIN_CYBERDECK_TX);
#endif
}

void UartSync::sendEntry(const char* csvLine) {
    DECK_SERIAL.println(csvLine);
}

void UartSync::poll() {
    while (DECK_SERIAL.available()) {
        char c = (char)DECK_SERIAL.read();
        if (c == '\n' || c == '\r') {
            if (_cmdLen > 0) {
                _cmdBuf[_cmdLen] = '\0';
                processCommand(_cmdBuf);
                _cmdLen = 0;
            }
        } else if (_cmdLen < sizeof(_cmdBuf) - 1) {
            _cmdBuf[_cmdLen++] = c;
        } else {
            _cmdLen = 0;  // overflow — discard and start over
        }
    }
}

void UartSync::processCommand(const char* cmd) {
    if (strcmp(cmd, "HELLO") == 0) {
        DECK_SERIAL.println("HELLO");
    } else if (strcmp(cmd, "DUMP") == 0) {
        handleDump();
    }
}

void UartSync::handleDump() {
    File f = LittleFS.open("/data.csv", "r");
    if (!f) {
        DECK_SERIAL.println("ERR:NO_LOG");
        return;
    }
    char line[240];
    while (f.available()) {
        int len = f.readBytesUntil('\n', line, sizeof(line) - 1);
        if (len > 0) {
            line[len] = '\0';
            DECK_SERIAL.println(line);
        }
    }
    f.close();
    DECK_SERIAL.println("END");
}

#else  // NATIVE_TEST stubs

void UartSync::begin() {}
void UartSync::sendEntry(const char*) {}
void UartSync::poll() {}
void UartSync::processCommand(const char*) {}
void UartSync::handleDump() {}

#endif
