# Hiking Pod System — Project Context

## What This Is
A two-component hiking data logger for NZ backcountry/coastal hiking:
- **Pod** (RP2350-Zero): data logger, e-ink display, GPS/weather sensors, buzzer alerts
- **Cyberdeck** (CM5, Python): receives pod logs, analyses weather and activity, displays summaries

## Repo Structure
```
/pod      - Pod firmware (C++ Arduino + PlatformIO)
/deck     - Cyberdeck code (Python 3.8+)
/docs     - Shared documentation
README.md - Root overview
```

## Data Format
Pipe-delimited CSV, logged every 5 minutes:
```
timestamp|lat,lon|alt|temp|humidity|pressure|battery
2026-05-25T14:32:42|-41.2865,172.1043|847|12.3|65|980.2|64
```

## Shared Technical Decisions
- UART between pod and cyberdeck: 115200 baud, GX16-5 connector
- Tide tables: generated from LINZ data via one-time Python script on cyberdeck, baked into `tidal_tables.h` compiled into pod firmware. 5 NZ cities (Auckland, Wellington, Christchurch, Dunedin, Tauranga), 2026–2030.
- Celestial calculations: simplified algorithms (±1-2 min accuracy) — NOT full Meeus

## Nijntje Display Character
Main screen only (1.54" 4-colour display). Sprites are 2bpp XBM bitmaps rendered via Adafruit GFX drawBitmap(). Size TBD (~48×48px).

### Primary states (priority order, highest first)
1. **Connected** — syncing with cyberdeck (antenna ears)
2. **Worried** — storm imminent (pairs with Red banner)
3. **Climbing** — significant elevation gain in progress
4. **Tired** — walking without rest for extended period
5. **Sleepy** — between sunset and sunrise
6. **Walking** — default

### Modifier (applied on top of primary state)
One modifier maximum. Priority when multiple conditions true: **Foggy > Cold > Hot > None**
- **Foggy** — dew point spread <1.5°C + humidity >95%
- **Cold** — low temperature (scarf, hunched)
- **Hot** — high temperature
- **None** — default

### Banner (independent of Nijntje state)
Rendered as a coloured bar at the bottom of the display.
- **None** — white (no alert)
- **Yellow** — rain possible
- **Red** — storm coming (Worried state will almost always pair with this)

### Sprite set (18 total)
16 state+modifier combinations (Walking/Tired/Climbing/Sleepy × None/Hot/Cold/Foggy)
plus 2 standalone: Worried, Connected.

Raining and Snowing states are planned but sprites deferred.

### Architecture
`NijntjeState`, `NijntjeModifier`, `BannerState` evaluated independently.
`NijntjeDisplay` struct bundles all three. `NijntjeRenderer` renders to Framebuffer.
Sensor evaluation (thresholds, conditions) is not yet implemented.

## Weather Algorithm Ideas (Future Work)
Not yet implemented. Candidate approaches:
1. Linear regression on altitude-adjusted pressure (circular buffer, last 3-6 hours)
2. Zambretti algorithm — sea-level pressure + trend → forecast category lookup table
3. Rate → imminence lookup (empirical: >6 hPa/3hr falling = <2h to event)
4. Humidity trend as confidence modifier

Realistic accuracy: 70-80% for rain/no-rain. Time-of-arrival ±2-4 hours.
Algorithm weightings are TBD — designed to be tunable over time.
NZ Southern Alps orographic effects worth considering (GPS position could infer which side of ranges).
Always present predictions with confidence percentages, never as certainties.
