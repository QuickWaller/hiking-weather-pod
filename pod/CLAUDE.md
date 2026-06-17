# Pod Firmware — Claude Context

C++ / Arduino / PlatformIO. Target MCU: RP2350-Zero. Currently dev/testing on ESP32.

> Repo-wide documentation map: [`/docs/README.md`](../docs/README.md) — what goes where, and the rules.

## Sub-documents

| File | Contents |
|------|----------|
| [docs/hardware.md](docs/hardware.md) | BOM, pin map, wiring, power — the hardware single-source-of-truth; **mirrors `src/config.h`** |
| [docs/architecture.md](docs/architecture.md) | How it works & why: wake cycle, buffers, storage, display stack, C++ conventions (**no pin tables — see hardware.md**) |
| [docs/status.md](docs/status.md) | What's implemented, test results, known hardware facts, pending work |
| [docs/plans.md](docs/plans.md) | Upcoming work: main loop, algorithm integration, fallbacks, RP2350 migration |
| [docs/testing.md](docs/testing.md) | How to run tests, what each suite covers, how to add tests |
| [docs/commands.md](docs/commands.md) | PlatformIO build/upload/test/monitor commands |
| [reference/](reference/) | Vendor datasheets, panel specs, demo code (read-only, third-party) |

## Critical rules (always apply)

- `#pragma once` on every header
- Headers declare only — implementations in .cpp
- `config.h` is the universal include for constants/pins
- After any code confirmed working: add unit + integration tests, run them before moving on
- Always update the docs above as things change
