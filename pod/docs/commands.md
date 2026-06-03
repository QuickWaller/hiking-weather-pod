# Pod — Commands

`pio` is not on PATH. Use full path: `C:/Users/wills/.platformio/penv/Scripts/pio.exe`

All commands run from: `C:/website-projects/cyber-deck-and-weather-station/pod/`

## Build

```bash
# Build ESP32 (default)
pio.exe run -e esp32

# Build RP2350
pio.exe run -e rp2350
```

## Upload

```bash
# Upload to connected ESP32
pio.exe run -e esp32 --target upload

# Upload to connected RP2350
pio.exe run -e rp2350 --target upload
```

## Serial Monitor

```bash
pio.exe device monitor --baud 115200
```

## Tests

```bash
# Native tests (no hardware needed)
pio.exe test -e native

# Embedded tests (ESP32 must be connected)
pio.exe test -e esp32

# Verbose output
pio.exe test -e esp32 -v
```

## Clean

```bash
pio.exe run -e esp32 --target clean
```

## Display Simulator

Requires SDL3 MinGW dev package in `pod/vendor/SDL3-x.x.x/` (gitignored, not committed).
After each build, copy `vendor/SDL3-x.x.x/i686-w64-mingw32/bin/SDL3.dll` next to the exe.

```bash
# Build simulator
pio.exe run -e native_display

# Copy DLL (needed after every rebuild — gets wiped)
cp vendor/SDL3-3.4.10/i686-w64-mingw32/bin/SDL3.dll .pio/build/native_display/

# Run — scenario cycle through all 14 evaluator test cases (no hardware needed)
.pio/build/native_display/program.exe

# Run — replay a saved pod log file
.pio/build/native_display/program.exe --file path/to/data.csv --delay 3000

# Run — live feed from pod (see Live Stream section below)
.pio/build/native_display/program.exe --port COM4
```

Press Q or close the window to quit. On first run, the window may be blank for up to 15 seconds waiting for the first serial row.

## Live Stream (ESP32 connected)

A separate firmware image (`esp32_stream`) runs the full sensor → algorithm → display pipeline and streams CSV every 15 seconds. ESP32 is on COM4 (confirmed via `pio.exe device list`).

```bash
# Build and upload stream firmware
pio.exe run -e esp32_stream --target upload

# Then launch the sim (in a separate terminal)
.pio/build/native_display/program.exe --port COM4
```

**Note:** On ESP32, I2C sensors (BMP180, AHT10, RTC) may show Wire errors — these sensors are wired for RP2350 I2C pins and degrade gracefully (sensor.valid = false). GPS and activity detection work. Full sensor data requires the RP2350 target.

## Environments

| Env | Target | Purpose |
|-----|--------|---------|
| `esp32` | ESP32 dev board | Current dev/test platform |
| `rp2350` | RP2350-Zero | Final target hardware |
| `native` | PC | Native unit tests (no hardware) |
| `native_display` | PC | SDL3 display simulator (requires SDL3 in vendor/) |
| `esp32_stream` | ESP32 | Stream firmware: sensor→algorithm→CSV over USB serial (+ raw `D,mx,my,mz,ax,ay,az` axis diagnostic) |
| `esp32_i2c_scan` | ESP32 | Bus scanner — prints every responding I2C address. Use to confirm sensor addresses (e.g. MPU6050 0x68 vs 0x69) |

## Test Filters

- `esp32` runs only `test/test_embedded/`
- `native` runs `test/test_math/`, `test/test_algorithms/`, `test/test_nijntje/`, `test/test_log/`, `test/test_display/`
- `rp2350` has no test filter set yet
