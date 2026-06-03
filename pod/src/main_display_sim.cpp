#ifdef NATIVE_DISPLAY
#include "display/NativeFramebuffer.h"
#include "display/BWFramebuffer.h"
#include "display/BWRenderer.h"
#include "display/SDL2Display.h"
#include "nijntje/NijntjeRenderer.h"
#include "nijntje/NijntjeState.h"
#include "algorithms/NijntjeEvaluator.h"
#include "sensors/SensorData.h"
#include "sensors/WeatherPrediction.h"
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <cmath>
#ifdef _WIN32
#include <windows.h>
#endif

// ---------------------------------------------------------------------------
// Test scenarios — exercise the actual NijntjeEvaluator logic
// ---------------------------------------------------------------------------
struct Scenario {
    const char*      name;
    SensorData       sensor;
    NijntjeState     activity;
    WeatherPrediction rain;
    WeatherPrediction storm;
};

static WeatherPrediction noWeather() {
    WeatherPrediction w = {};
    w.active = false;
    return w;
}

static WeatherPrediction activeWeather(uint8_t confidence) {
    WeatherPrediction w = {};
    w.active     = true;
    w.confidence = confidence;
    return w;
}

static SensorData baseSensor(float tempC, float humidity, bool connected = false) {
    SensorData s = {};
    s.tempC             = tempC;
    s.humidity          = humidity;
    s.pressureAdj       = 1013.0f;
    s.batteryPct        = 75.0f;
    s.gpsHasFix         = true;
    s.cyberdeckConnected = connected;
    s.hour              = 10;   // mid-morning
    s.sunriseMin        = 6*60; // 06:00
    s.sunsetMin         = 20*60;// 20:00
    return s;
}

static const Scenario SCENARIOS[] = {
    {
        "Walking — clear (18C)",
        baseSensor(18.0f, 60.0f),
        NijntjeState::Walking,
        noWeather(), noWeather()
    },
    {
        "Walking — hot (30C)",
        baseSensor(30.0f, 40.0f),
        NijntjeState::Walking,
        noWeather(), noWeather()
    },
    {
        "Walking — cold (5C)",
        baseSensor(5.0f, 65.0f),
        NijntjeState::Walking,
        noWeather(), noWeather()
    },
    {
        "Walking — foggy (10C, 97% RH)",
        baseSensor(10.0f, 97.0f),
        NijntjeState::Walking,
        noWeather(), noWeather()
    },
    {
        "Climbing — clear (15C)",
        baseSensor(15.0f, 55.0f),
        NijntjeState::Climbing,
        noWeather(), noWeather()
    },
    {
        "Climbing — cold (4C)",
        baseSensor(4.0f, 70.0f),
        NijntjeState::Climbing,
        noWeather(), noWeather()
    },
    {
        "Resting — hot (28C)",
        baseSensor(28.0f, 50.0f),
        NijntjeState::Resting,
        noWeather(), noWeather()
    },
    {
        "Night walk (12C)",
        baseSensor(12.0f, 70.0f),
        NijntjeState::WalkingNight,
        noWeather(), noWeather()
    },
    {
        "Sleepy evening (9C)",
        baseSensor(9.0f, 75.0f),
        NijntjeState::SleepyEvening,
        noWeather(), noWeather()
    },
    {
        "Sleeping — tent (6C)",
        baseSensor(6.0f, 80.0f),
        NijntjeState::SleepingTent,
        noWeather(), noWeather()
    },
    {
        "Rain possible — yellow banner",
        baseSensor(14.0f, 78.0f),
        NijntjeState::Walking,
        activeWeather(65), noWeather()
    },
    {
        "Storm incoming — worried + red",
        baseSensor(12.0f, 85.0f),
        NijntjeState::Walking,
        activeWeather(65), activeWeather(80)
    },
    {
        "Storm + cold — worried modifier check",
        baseSensor(5.0f, 85.0f),
        NijntjeState::Walking,
        activeWeather(65), activeWeather(80)
    },
    {
        "Connected to cyberdeck",
        baseSensor(18.0f, 60.0f, /*connected=*/true),
        NijntjeState::Walking,
        noWeather(), noWeather()
    },
};
static constexpr int SCENARIO_COUNT = sizeof(SCENARIOS) / sizeof(SCENARIOS[0]);

// ---------------------------------------------------------------------------
// CSV helpers (for --file / --port modes)
// ---------------------------------------------------------------------------
static const char* skipFields(const char* p, int n) {
    for (int i = 0; i < n; i++) {
        while (*p && *p != ',') p++;
        if (*p == ',') p++;
        else return nullptr;
    }
    return p;
}

static bool parseDisplayState(const char* line, NijntjeDisplay& out, float& heading) {
    if (!*line || line[0] == '#') return false;
    if (strncmp(line, "timestamp", 9) == 0) return false;

    const char* p = skipFields(line, 15);
    if (!p || !*p) return false;
    char stateChar = *p;

    p = skipFields(p, 1);
    if (!p || !*p) return false;
    char modChar = *p;

    p = skipFields(p, 1);
    if (!p || !*p) return false;
    char bannerChar = *p;

    switch (stateChar) {
        case 'C': out.state = NijntjeState::Climbing;      break;
        case 'W': out.state = NijntjeState::Walking;       break;
        case 'N': out.state = NijntjeState::WalkingNight;  break;
        case 'R': out.state = NijntjeState::Resting;       break;
        case 'E': out.state = NijntjeState::SleepyEvening; break;
        case 'T': out.state = NijntjeState::SleepingTent;  break;
        case 'X': out.state = NijntjeState::Worried;       break;
        case 'K': out.state = NijntjeState::Connected;     break;
        default:  return false;
    }
    switch (modChar) {
        case 'N': out.modifier = NijntjeModifier::None;  break;
        case 'H': out.modifier = NijntjeModifier::Hot;   break;
        case 'C': out.modifier = NijntjeModifier::Cold;  break;
        case 'F': out.modifier = NijntjeModifier::Foggy; break;
        default:  return false;
    }
    switch (bannerChar) {
        case 'N': out.banner = BannerState::None;   break;
        case 'Y': out.banner = BannerState::Yellow; break;
        case 'R': out.banner = BannerState::Red;    break;
        default:  return false;
    }

    // Col 20: compass heading (appended by esp32_stream, optional)
    p = skipFields(p, 3);  // skip gps_ms, free_heap, then heading
    if (p && *p) heading = (float)atof(p);

    return true;
}

// ---------------------------------------------------------------------------
// Serial line reader (Windows)
// ---------------------------------------------------------------------------
#ifdef _WIN32
static bool openSerial(const char* portName, HANDLE& hOut) {
    char path[32];
    snprintf(path, sizeof(path), "\\\\.\\%s", portName);
    hOut = CreateFileA(path, GENERIC_READ, 0, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (hOut == INVALID_HANDLE_VALUE) {
        printf("Cannot open %s (error %lu)\n", portName, GetLastError());
        return false;
    }
    DCB dcb = {};
    dcb.DCBlength = sizeof(dcb);
    GetCommState(hOut, &dcb);
    dcb.BaudRate = CBR_115200;
    dcb.ByteSize = 8;
    dcb.StopBits = ONESTOPBIT;
    dcb.Parity   = NOPARITY;
    SetCommState(hOut, &dcb);
    COMMTIMEOUTS to = {};
    to.ReadIntervalTimeout        = 100;
    to.ReadTotalTimeoutConstant   = 200;
    to.ReadTotalTimeoutMultiplier = 1;
    SetCommTimeouts(hOut, &to);
    return true;
}

static bool readLineSerial(HANDLE h, char* buf, int buflen) {
    int  pos = 0;
    char c;
    DWORD nr;
    while (pos < buflen - 1) {
        if (!ReadFile(h, &c, 1, &nr, nullptr) || nr == 0) {
            if (pos > 0) break;
            return false;
        }
        if (c == '\n') break;
        if (c != '\r') buf[pos++] = c;
    }
    buf[pos] = '\0';
    return pos > 0;
}
#endif

// ---------------------------------------------------------------------------
// Compass helpers
// ---------------------------------------------------------------------------
static bool parseCompassLine(const char* line, float& heading) {
    if (strncmp(line, "C,", 2) != 0) return false;
    heading = (float)atof(line + 2);
    return true;
}

// ---------------------------------------------------------------------------
// Render helpers
// ---------------------------------------------------------------------------
static void renderAndShow(NativeFramebuffer& fb, BWFramebuffer& bwfb,
                          SDL2Display& disp,
                          const NijntjeDisplay& d, float heading) {
    NijntjeRenderer::render(fb, d);
    disp.renderColour(fb.buffer(), EPD_WIDTH, EPD_HEIGHT);
    BWRenderer::renderCached(bwfb, heading);
    disp.renderBW(bwfb.buffer(), BW_WIDTH, BW_HEIGHT);
    disp.present();
}

static void updateCompass(NativeFramebuffer& fb, BWFramebuffer& bwfb,
                          SDL2Display& disp, float heading) {
    BWRenderer::renderCached(bwfb, heading);
    disp.renderColour(fb.buffer(), EPD_WIDTH, EPD_HEIGHT);  // re-blit, no recompute
    disp.renderBW(bwfb.buffer(), BW_WIDTH, BW_HEIGHT);
    disp.present();
}

static bool waitMs(SDL2Display& disp, int ms) {
    Uint64 deadline = SDL_GetTicks() + (Uint64)ms;
    while (SDL_GetTicks() < deadline) {
        if (!disp.pollEvents()) return false;
        SDL_Delay(50);
    }
    return true;
}

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------
int main(int argc, char* argv[]) {
    const char* portArg = nullptr;
    const char* fileArg = nullptr;
    int         delayMs = 5000;

    for (int i = 1; i < argc; i++) {
        if      (strcmp(argv[i], "--port")  == 0 && i + 1 < argc) portArg = argv[++i];
        else if (strcmp(argv[i], "--file")  == 0 && i + 1 < argc) fileArg = argv[++i];
        else if (strcmp(argv[i], "--delay") == 0 && i + 1 < argc) delayMs = atoi(argv[++i]);
    }

    NativeFramebuffer fb;
    BWFramebuffer     bwfb;
    SDL2Display       disp;
    float             heading = NAN;
    if (!disp.init(3)) return 1;

    // -----------------------------------------------------------------------
    // Mode A: live serial
    // -----------------------------------------------------------------------
#ifdef _WIN32
    if (portArg) {
        HANDLE hSerial;
        if (!openSerial(portArg, hSerial)) { disp.shutdown(); return 1; }
        printf("Reading from %s at 115200 baud. Press Q or close window to quit.\n", portArg);
        char  line[256];
        bool  running   = true;
        int   lastIdx   = -1;  // last rendered 16-position index (-1 = none)
        while (running) {
            if (!disp.pollEvents()) break;
            if (readLineSerial(hSerial, line, sizeof(line))) {
                NijntjeDisplay d;
                float          h;
                if (parseDisplayState(line, d, heading)) {
                    // Full sensor cycle — update both panels
                    lastIdx = std::isnan(heading) ? -1 : BWRenderer::compassIndex(heading);
                    renderAndShow(fb, bwfb, disp, d, heading);
                } else if (parseCompassLine(line, h)) {
                    // 0.5s compass tick — only redraw if 16-position bucket changed
                    int idx = BWRenderer::compassIndex(h);
                    if (idx != lastIdx) {
                        lastIdx = idx;
                        updateCompass(fb, bwfb, disp, h);
                    }
                }
            }
        }
        CloseHandle(hSerial);
        disp.shutdown();
        return 0;
    }
#else
    if (portArg) {
        printf("Serial port mode is Windows-only in this build.\n");
        disp.shutdown();
        return 1;
    }
#endif

    // -----------------------------------------------------------------------
    // Mode B: CSV file replay
    // -----------------------------------------------------------------------
    if (fileArg) {
        FILE* f = fopen(fileArg, "r");
        if (!f) { printf("Cannot open %s\n", fileArg); disp.shutdown(); return 1; }
        printf("Replaying %s (--delay %dms between rows). Q to quit.\n", fileArg, delayMs);
        char line[256];
        bool running = true;
        while (running && fgets(line, sizeof(line), f)) {
            line[strcspn(line, "\r\n")] = '\0';
            NijntjeDisplay d;
            if (parseDisplayState(line, d, heading)) {
                renderAndShow(fb, bwfb, disp, d, heading);
                if (!waitMs(disp, delayMs)) running = false;
            }
        }
        fclose(f);
        disp.shutdown();
        return 0;
    }

    // -----------------------------------------------------------------------
    // Mode C: scenario cycle — calls NijntjeEvaluator::evaluate() for each
    // -----------------------------------------------------------------------
    printf("Cycling %d scenarios via NijntjeEvaluator. Q to quit.\n", SCENARIO_COUNT);
    int  idx     = 0;
    bool running = true;
    while (running) {
        const Scenario& sc = SCENARIOS[idx];
        NijntjeDisplay d = NijntjeEvaluator::evaluate(
            sc.sensor, sc.activity, sc.rain, sc.storm);
        printf("[%2d/%d] %s  →  state=%d mod=%d banner=%d\n",
               idx + 1, SCENARIO_COUNT, sc.name,
               (int)d.state, (int)d.modifier, (int)d.banner);
        renderAndShow(fb, bwfb, disp, d, NAN);
        if (!waitMs(disp, 2000)) break;
        idx = (idx + 1) % SCENARIO_COUNT;
    }
    disp.shutdown();
    return 0;
}
#endif // NATIVE_DISPLAY
