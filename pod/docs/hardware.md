# Pod Hardware — single source of truth

> This file is the **canonical** BOM + pin map + wiring + power reference, and **mirrors
> `src/config.h`** — change the two together. Architecture *how/why* lives in
> [architecture.md](architecture.md); it points here for pins and carries no pin tables.

## Target MCU

**Waveshare RP2350-Zero** (Cortex-M33, 2 MB flash, 520 KB SRAM, no PSRAM). Dev/testing also
runs on an ESP32 dev board — pin numbers differ per MCU (see *ESP32 dev deviations* below).

WiFi was evaluated and **deferred** (would force an ESP32-class board); the Zero has no radio.

## BOM

| Component | Part | Interface | Notes |
|-----------|------|-----------|-------|
| MCU | RP2350-Zero | — | 20 usable GPIO broken out |
| Display | Waveshare 1.54" 4-colour e-ink (Nijntje) | SPI | the **only** display |
| GPS | GY-GPS6MV2 M8N | UART0, 9600 baud | runs at **3.3 V** (VCC + logic) |
| Pressure + Temp + Humidity | **BME280** (single chip) | I²C @ 0x76 (0x77 if SDO high — verify) | |
| RTC | **DS3231** breakout (ships with coin-cell backup attached) | I²C @ 0x68 | SQW alarm → GP15 wake. ⚠️ Trickle-charge: see note below |
| microSD | XC4386 breakout (own 3V3 regulator + level shifter) | SPI (shared bus) | logs + model file(s); power via its `3V3` pin |
| Battery | 18650 2600 mAh + TP4056 USB-C charger | ADC | |
| Rotary | position switch | ADC | display input |

**Dropped (2026-06-13/14):** compass (HMC5883L), accelerometer (MPU6050), buzzer, cyberdeck
UART, and the 2.13" B/W display. The 2.13" can be re-added later (4 spare GPIO reserved).

## Physical pad layout (RP2350-Zero)

```
 LEFT (top→bottom)     BOTTOM (L→R)        RIGHT (bottom→top)
   5V                    GP13                 GP0
   GND                   GP12                 GP1
   3V3                   GP11                 GP2
   GP29                  GP10                 GP3
   GP28                  GP9                  GP4
   GP27                                       GP5
   GP26                                       GP6
   GP15                                       GP7
   GP14                                       GP8
```
GP16/GP17 are **not** broken out (GP16 = onboard WS2812 LED). ADC exists only on GP26–GP29.
The **underside** also exposes 3 pads: **CLK, GND, D10** (purpose to confirm — likely debug/clock;
not used by the current wiring). If `D10` is a usable GPIO it would be a 5th spare.

## Pin map

Grouped so each component's wires land on adjacent pads.

### LEFT — power · analog · I²C · RTC
| Pad | Function |
|-----|----------|
| 5V | 5 V in (USB / charge) |
| GND | ground |
| 3V3 | **3.3 V rail out** — powers all sensors, GPS, SD, display |
| GP29 | Battery sense (ADC3) |
| GP28 | Rotary switch (ADC2) |
| GP27 | I²C1 SCL |
| GP26 | I²C1 SDA |
| GP15 | RTC SQW (alarm wake) |
| GP14 | GX16 connection-detect (interrupt) |

### BOTTOM — GPS + spares
| Pad | Function |
|-----|----------|
| GP13 | GPS RX (UART0) |
| GP12 | GPS TX (UART0) |
| GP11 | *spare* |
| GP10 | *spare* |
| GP9 | *spare* |

### RIGHT — SPI subsystem (display + SD)
| Pad | Function |
|-----|----------|
| GP0 | *spare* |
| GP1 | SD CS |
| GP2 | SPI0 SCK (shared) |
| GP3 | SPI0 MOSI (shared) |
| GP4 | SPI0 MISO (SD read) |
| GP5 | 1.54" e-ink CS |
| GP6 | 1.54" e-ink DC |
| GP7 | 1.54" e-ink RST |
| GP8 | 1.54" e-ink BUSY |

**Usage: 16 of 20 GPIO. Spare: GP0, GP9, GP10, GP11** — exactly the 4 a re-added 2.13" B/W
panel (CS/DC/RST/BUSY on the same SPI bus) would need.

## Buses & power

- **I²C1** (SDA=GP26, SCL=GP27): DS3231 0x68, BME280 0x76. Module pull-ups assumed.
- **SPI0** (SCK=GP2, MOSI=GP3, MISO=GP4) shared by the display + SD, with **software chip-select**
  (display CS=GP5, SD CS=GP1). The display is write-only (no MISO); SD uses MISO.
- **ADC** only on GP26–GP29; GP26/27 are I²C, so the two analog users sit on GP28/GP29.
- **Power:** everything runs off the **3V3** rail (one rail — verify each module at 3.3 V before
  bus-up). 5V is charge/USB only. GPS confirmed 3.3 V.
- **Pin constraints that forced choices:** SPI0 data lines are fixed to GP2/3/4; UART0 to GP12/13;
  ADC to GP28/29; GP16/17 unavailable (so the old SQW=GP17 moved to GP15).
- **DS3231 battery / trickle-charge gotcha:** common DS3231 modules ship with a **rechargeable
  LIR2032** + an onboard charging circuit fed from VCC — that's fine, leave it (it stays topped up).
  But if a **non-rechargeable CR2032** is ever fitted, the charger will try to charge it (leak/rupture
  risk) → disable the charger (remove the series resistor/diode) first. Confirm which cell is attached.

## ESP32 dev deviations

The ESP32 dev board uses different pin numbers (and still carries the not-yet-removed
compass/accel/buzzer/UART code). `config.h` selects the map with
`#if defined(ARDUINO_ARCH_RP2040)` (RP2350) `#else` (ESP32). The table above is the RP2350
target; the ESP32 `#else` block in `config.h` is the bench wiring.
