# Jaycar shopping list — pod build (2026-06-13)

Parts to pick up for the pod hardware build. Decisions behind each are from the
power + MCU walkthrough (2026-06-12). **Read the ⚠️ in-store checks at the bottom.**

## Power (run-while-charging tree)
- [ ] **3.3 V BUCK-BOOST regulator module**, ≥500 mA, set/fixed to 3.3 V
      — ⚠️ **must be buck-BOOST (step up/down), NOT a plain buck/step-down.**
        A step-down can't hold 3.3 V once the cell sags below ~3.5 V → early brownout.
        If Jaycar only stocks step-down modules, skip it and order a Pololu S7V8F3
        (fixed 3.3 V buck-boost) online instead.
- [ ] **2× Schottky diodes**, ~1 A (e.g. 1N5819 or similar) — the load-share OR (D1/D2)
- [ ] **1× electrolytic cap ~470 µF** (low-ESR) — buck-boost input bulk, rides GPS/SD/e-ink spikes
- [ ] **1× ceramic cap 100 nF** — buck-boost input decoupling
- [ ] **18650 holder / clip** (only if you don't already have one)
- [ ] **2× 100 kΩ resistors** + **1× 100 nF cap** — battery-voltage divider into GP29 (18650's 4.2 V is over the 3.3 V ADC limit, so halve it)

## Storage
- [ ] **microSD card module — Jaycar XC4386** (the one you mentioned)
- [ ] **microSD card, 8–32 GB** (will be formatted FAT32 — holds the model file(s) + logs)

## Input
- [ ] **Rotary encoder with integrated push switch** (EC11 type, or a KY-040 encoder module)
      — replaces the buzzer + standalone button + old rotary position switch

## Supporting / consumables (grab if you're low)
- [ ] 10 kΩ resistors ×4 — encoder pull-ups / RC filter
- [ ] 10 nF ceramic caps ×2 — encoder A/B debounce (optional, or decode in PIO)
- [ ] Protoboard / perfboard
- [ ] Hookup wire / jumper leads
- [ ] Header pins (male + female) to mount the modules

## ⚠️ In-store checks
- **Buck-BOOST, not buck** — single most important one (see note above).
- **SD module has a `3V3` pin** (XC4386 does) — we power it from 3.3 V, never 5 V.
- **Encoder has a push switch** (the SW pin) — not a plain encoder.

## You already have (don't re-buy)
- Protected TP4056 charge module (has `OUT+/OUT-`) · protected 18650
- RP2350-Zero · 1.54" 4-colour e-ink (replacement) · 2.13" B/W e-ink
- GPS M8N · **BME280** (single chip: pressure + temp + humidity; confirm chip-ID 0x60, I²C 0x76/0x77)
- **DS3231** RTC breakout (with the coin cell it shipped with). SQW alarm → GP15 wake.
  ⚠️ If that cell is a non-rechargeable CR2032, disable the module's trickle-charge first; if it's the
  usual rechargeable LIR2032, leave the charger as-is.

## NOT needed anymore (dropped from design)
- ~~Buzzer~~ · ~~HMC5883L compass~~ · ~~MPU6050 accel~~ · ~~GX16-5 / any UART parts~~
