#include "EPD1in54G.h"

EPD1in54G::EPD1in54G(IDisplayHAL& hal) : _hal(hal) {}

void EPD1in54G::reset() {
    _hal.setReset(true);  _hal.delayMs(200);
    _hal.setReset(false); _hal.delayMs(2);
    _hal.setReset(true);  _hal.delayMs(200);
}

void EPD1in54G::sendCommand(uint8_t cmd) {
    _hal.setDC(false);
    _hal.setCS(false);
    _hal.spiWrite(cmd);
    _hal.setCS(true);
}

void EPD1in54G::sendData(uint8_t data) {
    _hal.setDC(true);
    _hal.setCS(false);
    _hal.spiWrite(data);
    _hal.setCS(true);
}

void EPD1in54G::waitReady() {
    _hal.delayMs(100);
    uint32_t elapsed = 0;
    while (!_hal.readBusy()) {
        _hal.delayMs(5);
        elapsed += 5;
        if (elapsed >= 30000) break;
    }
}

void EPD1in54G::applyBaseConfig() {
    sendCommand(0x4D); sendData(0x78);
    sendCommand(0x00); sendData(0x0F); sendData(0x29);          // PSR
    sendCommand(0x06); sendData(0x0D); sendData(0x12);          // BTST
                       sendData(0x30); sendData(0x20);
                       sendData(0x19); sendData(0x2A); sendData(0x22);
    sendCommand(0x50); sendData(0x37);                          // CDI
    sendCommand(0x61);                                          // TRES
        sendData(EPD_WIDTH  >> 8); sendData(EPD_WIDTH  & 0xFF);
        sendData(EPD_HEIGHT >> 8); sendData(EPD_HEIGHT & 0xFF);
    sendCommand(0xE9); sendData(0x01);
    sendCommand(0x30); sendData(0x08);
}

void EPD1in54G::turnOnDisplay() {
    sendCommand(0x12); sendData(0x00);
    waitReady();
}

void EPD1in54G::init() {
    reset();
    applyBaseConfig();
    sendCommand(0x04);
    waitReady();
}

void EPD1in54G::initFast() {
    reset();
    applyBaseConfig();
    sendCommand(0x04); waitReady();
    sendCommand(0xE0); sendData(0x02);
    sendCommand(0xE6); sendData(0x5D);
    sendCommand(0xA5); sendData(0x00);
    waitReady();
}

void EPD1in54G::clear(EPDColour colour) {
    uint8_t c = static_cast<uint8_t>(colour);
    uint8_t fill = (c << 6) | (c << 4) | (c << 2) | c;
    sendCommand(0x10);
    for (uint32_t i = 0; i < EPD_BUFFER_SIZE; i++) sendData(fill);
    turnOnDisplay();
}

void EPD1in54G::display(const uint8_t* buffer) {
    sendCommand(0x10);
    for (uint32_t i = 0; i < EPD_BUFFER_SIZE; i++) sendData(buffer[i]);
    turnOnDisplay();
}

void EPD1in54G::sleep() {
    sendCommand(0x02); sendData(0x00);
    waitReady();
    sendCommand(0x07); sendData(0xA5);
}
