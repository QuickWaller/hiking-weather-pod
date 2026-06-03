#pragma once
#include <stdint.h>

// Handles UART1 communication with the cyberdeck over the GX16-5 connector.
// Real-time: every new CSV entry is forwarded when the cyberdeck is connected.
// On-demand: cyberdeck sends "DUMP\n" to receive the full log from flash.
//
// Commands from cyberdeck:  HELLO, DUMP
// Responses from pod:       HELLO, <csv lines>, END, ERR:<code>

class UartSync {
public:
    void begin();
    void sendEntry(const char* csvLine);
    void poll();

private:
    char    _cmdBuf[16] = {};
    uint8_t _cmdLen     = 0;

    void processCommand(const char* cmd);
    void handleDump();
};
