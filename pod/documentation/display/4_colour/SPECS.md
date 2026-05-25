# Waveshare 1.54inch e-Paper (G) — Firmware Reference

**Full datasheet:** `../1.54inch_e-Paper_(G).pdf` (Waveshare, v1.0, 2025-02-12)

## Key Identifiers

| Field | Value |
|-------|-------|
| Product | Waveshare 1.54inch e-Paper Module (G) |
| Driver IC | JD79660AA |
| Resolution | 200 × 200 px |
| Colours | Black / White / Red / Yellow (2-bit per pixel) |
| Active area | 27.00 × 27.00 mm |
| Outline | 31.80 × 37.32 × 1.00 mm |
| DPI | 189 |
| FPC connector | 24-pin, 0.5mm pitch |

## Electrical

| Parameter | Min | Typ | Max | Unit |
|-----------|-----|-----|-----|------|
| Logic supply (VCI) | 2.3 | 3.0 | 3.6 | V |
| Operating temp | 0 | — | +40 | °C |
| Full refresh time | — | 20 | — | s |
| Fast refresh time | — | 12 | — | s |
| Operating current | — | 3 | — | mA |
| Typical power | — | 9 | — | mW |
| Deep sleep current | — | 0.4 | 1 | µA |

> **Warning:** Operating temp max is +40°C. No partial refresh supported — full refresh only.

## MCU-Facing SPI Pins

Use **4-wire SPI** (BS pin tied LOW on the module).

| Signal | Direction | Description |
|--------|-----------|-------------|
| SCL | MCU → EPD | SPI clock |
| SDA | MCU → EPD | SPI data (MOSI) |
| CS# | MCU → EPD | Chip select, active LOW |
| D/C# | MCU → EPD | HIGH = data, LOW = command |
| RES# | MCU → EPD | Hardware reset, active LOW |
| BUSY_N | EPD → MCU | LOW = busy, do not send commands |

**SPI mode:** CPOL=0, CPHA=0 (Mode 0). Data latched on rising SCL edge.

> BUSY_N goes LOW during waveform output and temperature sensor reads. Poll until HIGH before each command.

## BUSY Pin Behaviour

**BUSY HIGH = idle/ready. BUSY LOW = busy (operation in progress).**

Poll BUSY until HIGH before sending the next command. From the sample code, the correct wait pattern is:
```cpp
while (!readBusy()) delay(5);  // wait while LOW, proceed when HIGH
```

The raw chip has `BUSY_N` (active-low), but the Waveshare module does **not** invert it — the signal on the module header pin behaves the same way: LOW = busy, HIGH = done.

## Typical Initialisation + Refresh Sequence

Verified against `ESP32/EPD_1in54g.cpp` from Waveshare demo code (2024-08-07).

```cpp
// 1. Hardware reset
//    RST HIGH 200ms → LOW 2ms → HIGH 200ms

// 2. Init registers
sendCmd(0x4D); sendData(0x78);
sendCmd(0x00); sendData(0x0F); sendData(0x29);          // PSR
sendCmd(0x06); sendData(0x0D); sendData(0x12);          // BTST
               sendData(0x30); sendData(0x20);
               sendData(0x19); sendData(0x2A); sendData(0x22);
sendCmd(0x50); sendData(0x37);                          // CDI
sendCmd(0x61); sendData(0x00); sendData(0xC8);          // TRES 200x200
               sendData(0x00); sendData(0xC8);
sendCmd(0xE9); sendData(0x01);
sendCmd(0x30); sendData(0x08);

// 3. Power on — wait until BUSY HIGH
sendCmd(0x04);
waitBusyHigh();

// 4. Load image data
sendCmd(0x10);
// Send 10000 bytes (200 * 200 / 4 pixels per byte)

// 5. Refresh — wait until BUSY HIGH
sendCmd(0x12); sendData(0x00);
waitBusyHigh();

// 6. Power off — wait until BUSY HIGH
sendCmd(0x02); sendData(0x00);
waitBusyHigh();

// 7. Deep sleep (~0.4µA)
sendCmd(0x07); sendData(0xA5);
```

### Fast Mode (12s vs 20s)

Add these three commands after step 3 (power on + waitBusyHigh):
```cpp
sendCmd(0xE0); sendData(0x02);
sendCmd(0xE6); sendData(0x5D);
sendCmd(0xA5); sendData(0x00);
waitBusyHigh();
```

## Key Command Reference

| Code | Name | Notes |
|------|------|-------|
| 0x00 | PSR | Panel Setting Register |
| 0x01 | PWR | Power Setting |
| 0x02 | POF | Power OFF |
| 0x04 | PON | Power ON |
| 0x06 | BTST | Booster Soft Start |
| 0x07 | DSLP | Deep Sleep — send 0xA5 to enter |
| 0x10 | DTM | Data Start Transmission |
| 0x12 | DRF | Display Refresh |
| 0x50 | CDI | VCOM and Data Interval |
| 0x61 | TRES | Resolution Setting |

## Pixel Data Format

2 bits per pixel, packed MSB-first per byte (4 pixels/byte). Confirmed from `EPD_1in54g.h`:

| 2-bit value | Colour |
|-------------|--------|
| 0x0 (00) | Black |
| 0x1 (01) | White |
| 0x2 (10) | Yellow |
| 0x3 (11) | Red |

Packing (from `EPD_1IN54G_Clear`):
```cpp
byte = (p0 << 6) | (p1 << 4) | (p2 << 2) | p3;
```
Pixel 0 in bits 7-6 (MSB), pixel 3 in bits 1-0 (LSB). Row-major order, left to right.

Total image buffer: 200 × 200 / 4 = **10,000 bytes**.

## Abstraction Layer (RP2350-Zero substitutable)

All driver code must be MCU-agnostic. The HAL interface injected via constructor — **no pin numbers or Arduino/ESP32 APIs inside the driver**. This allows drop-in substitution of the ESP32-WROOM for the RP2350-Zero (target MCU per `/pod/CLAUDE.md`) with only a new HAL implementation.

```cpp
struct DisplayHAL {
    void (*spiWrite)(uint8_t byte);
    void (*setCS)(bool high);
    void (*setDC)(bool high);    // true = data, false = command
    void (*setReset)(bool high);
    bool (*readBusy)();          // returns true when BUSY is HIGH (idle/ready)
    void (*delayMs)(uint32_t ms);
};
```

Concrete HAL implementations live in `hal/esp32_hal.cpp` and `hal/rp2350_hal.cpp`. The driver (`EPD1in54G.cpp`) only calls through the struct — never touches hardware directly.
