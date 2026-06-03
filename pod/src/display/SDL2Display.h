#pragma once
#ifdef NATIVE_DISPLAY
#include "EPD1in54G.h"
#include "BWFramebuffer.h"
#include <SDL3/SDL.h>
#include <stdint.h>

// Logical canvas: colour panel (200×200) | 10px gap | B/W panel (250×122 centred)
static constexpr int SDL_LOGICAL_W = EPD_WIDTH + 10 + BW_WIDTH;   // 460
static constexpr int SDL_LOGICAL_H = EPD_HEIGHT;                   // 200

class SDL2Display {
public:
    bool init(int scale = 3);
    void renderColour(const uint8_t* buf, uint16_t w, uint16_t h); // 2bpp, clears frame
    void renderBW(const uint8_t* buf, uint16_t w, uint16_t h);     // 1bpp
    bool pollEvents();
    void present();
    void shutdown();

private:
    SDL_Window*   _window     = nullptr;
    SDL_Renderer* _renderer   = nullptr;
    SDL_Texture*  _colTex     = nullptr;
    SDL_Texture*  _bwTex      = nullptr;
    uint16_t _ctw = 0, _cth = 0;
    uint16_t _btw = 0, _bth = 0;
};
#endif // NATIVE_DISPLAY
