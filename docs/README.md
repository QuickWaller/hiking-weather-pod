# Documentation map — Hiking Pod System

Where every kind of documentation lives. **Start here**, then follow the pointers.

The repo is several components; **each owns its own docs**, and nothing is duplicated
across them. If you find the same fact in two places, one is stale — fix it at the
canonical home and point the other at it.

## Top level

| Path | Holds |
|---|---|
| `/CLAUDE.md` | Shared cross-component context (system vision, CSV data format, conventions) |
| `/README.md` | Human-facing project overview |
| `/docs/README.md` | **This file** — the documentation map |

## Components

| Component | Status | Docs home |
|---|---|---|
| **`/pod`** | Active — firmware (RP2350-Zero, C++/PlatformIO) | `pod/CLAUDE.md` → `pod/docs/` |
| **`/pod/tools`** | Active — offline tooling: map tile generator, SD card prep | `pod/docs/map-tiles.md` |
| **`/pod-ml`** | Active — rain/weather model + data pipeline (Python) | `pod-ml/docs/` (numbered research logs) |
| **`/pod-ml/scripts/linz`** | Active — LINZ NZ Topo50 GeoPackage download + cron | `pod/docs/map-tiles.md` → LINZ section |
| **`/pcb`** | ⚠️ Stale — KiCad board design, predates the no-compass/no-accel decision | `pcb/` |
| **`/deck`** | ⏸️ **Tabled** (2026-06-12) — cyberdeck (CM5). Option open, not maintained | `deck/CLAUDE.md` |

## Document kinds — the "what goes where" contract

Every component follows the same separation of concerns:

| Kind | Lives in | Volatility |
|---|---|---|
| **Orientation / index** | `CLAUDE.md` — pointers + critical rules, **never content** | low |
| **Hardware truth** | `docs/hardware.md` — BOM, pin map, wiring, power; **mirrors `src/config.h`** | medium |
| **Architecture** | `docs/architecture.md` — how it works & why; **no pin tables** | medium |
| **Status** | `docs/status.md` — what's built/tested *now* | high |
| **Plans** | `docs/plans.md` — what's next | high |
| **Runbooks** | `docs/commands.md`, `docs/testing.md` | low |
| **External reference** | `reference/` — vendor datasheets, panel specs, demo code (read-only) | static |

**Rules**
1. `CLAUDE.md` is a signpost, never a content store.
2. Hardware truth = `docs/hardware.md` ↔ `config.h`. Change them together.
3. *how/why* → architecture · *what's done* → status · *what's next* → plans. Keep them from bleeding into each other.
4. Vendor/third-party material → `reference/`, never `docs/`.
5. A tabled component gets one stub stating it's shelved + what would revive it.

## Note on `/pod-ml`

`pod-ml` deliberately uses a **different doc style**: numbered, append-only
research/decision logs (`docs/NN-*.md`) plus figures, because it's a research
journal, not a stable system. Don't impose the pod's typed-doc structure on it.

## Current architecture facts (2026-06-14)

- Compass (HMC5883L), accelerometer (MPU6050), and the **buzzer** are **dropped** — no audible alerts, warnings are display-only.
- Sensing is a single **BME280** (P+T+H, I²C 0x76) — *not* BMP180+AHT10 (docs were wrong; bench code still uses the two readers, a `Bme280Reader` swap is pending).
- **Single display:** 1.54" 4-colour only. The 2.13" B/W panel is **out for now** (re-addable later).
- Target MCU is the **RP2350-Zero** (~29 GPIO); the QT Py ESP32 (~13 pins) can't fit the set. **WiFi deferred** (would force an ESP32-class board).
- Pod has **no UART** — cyberdeck tabled; sync to the VM is SD-card sneakernet.
- **microSD added** — daily UTC CSVs: `/raw` (10-min), `/inputs` + `/pred` (hourly, joined on UTC issue-hour), `/events`; plus `/model` + `manifest.json`. Small critical state on LittleFS. Graceful degradation if SD missing.
- **Cadence:** single **10-min UTC-aligned wake**; hourly predictions on UTC-hour boundaries (matches GPM aggregated 30-min→hourly). All timestamps **UTC + `Z`**; display is NZ-local.
- **On-device model = data file on SD, copied manually**, run by a **streaming tree evaluator** (ensemble too big to compile in: ~10–20 MB vs 2 MB flash). **Schema-hash gate, fail-safe** → mismatch falls back to the rule-based algorithm.
- **Pin map done (2026-06-14):** canonical in `pod/docs/hardware.md`; `config.h` arch-split (RP2350 target / ESP32 bench). 16/20 GPIO used, spares GP0/9/10/11. SD on shared SPI0; ADC on GP28/29.
