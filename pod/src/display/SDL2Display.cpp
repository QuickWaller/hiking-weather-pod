#ifdef NATIVE_DISPLAY
#include "SDL2Display.h"
#include <cstdio>

static const SDL_Color COLOUR_TABLE[4] = {
    {  0,   0,   0, 255},  // 0 = Black
    {255, 255, 255, 255},  // 1 = White
    {255, 200,   0, 255},  // 2 = Yellow
    {210,   0,   0, 255},  // 3 = Red
};

bool SDL2Display::init(int scale) {
    if (!SDL_Init(SDL_INIT_VIDEO)) {
        printf("SDL_Init error: %s\n", SDL_GetError());
        return false;
    }
    _window = SDL_CreateWindow(
        "Pod Displays \xe2\x80\x94 1.54\" colour | 2.13\" B/W",
        SDL_LOGICAL_W * scale, SDL_LOGICAL_H * scale,
        0
    );
    if (!_window) { printf("SDL_CreateWindow: %s\n", SDL_GetError()); return false; }

    _renderer = SDL_CreateRenderer(_window, nullptr);
    if (!_renderer) { printf("SDL_CreateRenderer: %s\n", SDL_GetError()); return false; }

    SDL_SetRenderVSync(_renderer, 1);
    SDL_SetRenderLogicalPresentation(_renderer,
        SDL_LOGICAL_W, SDL_LOGICAL_H,
        SDL_LOGICAL_PRESENTATION_INTEGER_SCALE);
    return true;
}

// ── Colour panel (2bpp) ──────────────────────────────────────────────────────

void SDL2Display::renderColour(const uint8_t* buf, uint16_t w, uint16_t h) {
    if (!_colTex || _ctw != w || _cth != h) {
        if (_colTex) SDL_DestroyTexture(_colTex);
        _colTex = SDL_CreateTexture(_renderer,
            SDL_PIXELFORMAT_ARGB8888, SDL_TEXTUREACCESS_STREAMING, w, h);
        SDL_SetTextureScaleMode(_colTex, SDL_SCALEMODE_NEAREST);
        _ctw = w; _cth = h;
    }

    void* pixels; int pitch;
    SDL_LockTexture(_colTex, nullptr, &pixels, &pitch);
    uint32_t* dst      = static_cast<uint32_t*>(pixels);
    int       stride   = pitch / 4;
    uint16_t  rowBytes = (w + 3) / 4;

    for (uint16_t y = 0; y < h; y++) {
        for (uint16_t x = 0; x < w; x++) {
            uint32_t  idx   = (uint32_t)y * rowBytes + x / 4;
            uint8_t   shift = (3 - (x % 4)) * 2;
            uint8_t   code  = (buf[idx] >> shift) & 0x3;
            SDL_Color c     = COLOUR_TABLE[code];
            dst[y * stride + x] =
                ((uint32_t)0xFF << 24) | ((uint32_t)c.r << 16) |
                ((uint32_t)c.g  <<  8) |  (uint32_t)c.b;
        }
    }
    SDL_UnlockTexture(_colTex);

    SDL_RenderClear(_renderer);
    SDL_FRect dest = {0.0f, 0.0f, (float)w, (float)h};
    SDL_RenderTexture(_renderer, _colTex, nullptr, &dest);
}

// ── B/W panel (1bpp packed) ──────────────────────────────────────────────────

void SDL2Display::renderBW(const uint8_t* buf, uint16_t w, uint16_t h) {
    if (!_bwTex || _btw != w || _bth != h) {
        if (_bwTex) SDL_DestroyTexture(_bwTex);
        _bwTex = SDL_CreateTexture(_renderer,
            SDL_PIXELFORMAT_ARGB8888, SDL_TEXTUREACCESS_STREAMING, w, h);
        SDL_SetTextureScaleMode(_bwTex, SDL_SCALEMODE_NEAREST);
        _btw = w; _bth = h;
    }

    void* pixels; int pitch;
    SDL_LockTexture(_bwTex, nullptr, &pixels, &pitch);
    uint32_t* dst      = static_cast<uint32_t*>(pixels);
    int       stride   = pitch / 4;
    uint16_t  rowBytes = (w + 7) / 8;

    for (uint16_t y = 0; y < h; y++) {
        for (uint16_t x = 0; x < w; x++) {
            uint32_t idx   = (uint32_t)y * rowBytes + x / 8;
            uint8_t  bit   = 7 - (x % 8);
            bool     white = (buf[idx] >> bit) & 1;
            uint8_t  v     = white ? 255 : 0;
            dst[y * stride + x] =
                (0xFF << 24) | ((uint32_t)v << 16) | ((uint32_t)v << 8) | v;
        }
    }
    SDL_UnlockTexture(_bwTex);

    // Position: right of colour panel, vertically centred
    float xOff = (float)(EPD_WIDTH + 10);
    float yOff = (float)((SDL_LOGICAL_H - h) / 2);
    SDL_FRect dest = {xOff, yOff, (float)w, (float)h};
    SDL_RenderTexture(_renderer, _bwTex, nullptr, &dest);
}

// ── Common ───────────────────────────────────────────────────────────────────

bool SDL2Display::pollEvents() {
    SDL_Event e;
    while (SDL_PollEvent(&e)) {
        if (e.type == SDL_EVENT_QUIT) return false;
        if (e.type == SDL_EVENT_KEY_DOWN && e.key.scancode == SDL_SCANCODE_Q) return false;
    }
    return true;
}

void SDL2Display::present() { SDL_RenderPresent(_renderer); }

void SDL2Display::shutdown() {
    if (_colTex)  { SDL_DestroyTexture(_colTex);   _colTex   = nullptr; }
    if (_bwTex)   { SDL_DestroyTexture(_bwTex);    _bwTex    = nullptr; }
    if (_renderer){ SDL_DestroyRenderer(_renderer); _renderer = nullptr; }
    if (_window)  { SDL_DestroyWindow(_window);     _window   = nullptr; }
    SDL_Quit();
}
#endif // NATIVE_DISPLAY
