#!/usr/bin/env python3
"""
Convert a PNG to a 2bpp C header for the EPD1in54G display.

Colour mapping (nearest match by Euclidean distance in RGB):
  Black  #000000 -> 0x0
  White  #FFFFFF -> 0x1
  Yellow #FFFF00 -> 0x2
  Red    #FF0000 -> 0x3

Usage:
  python img_to_epd.py nijntje_normal.png NijntjeNormal
  -> outputs NijntjeNormal.h in the same directory

Pixel packing: 4 pixels per byte, MSB = leftmost pixel.

Optional third argument resizes before conversion:
  python img_to_epd.py nijntje_normal.png NijntjeNormal 128
"""

import sys
import os
from PIL import Image

PALETTE = {
    (0,   0,   0):   0x0,  # Black
    (255, 255, 255): 0x1,  # White
    (255, 255, 0):   0x2,  # Yellow
    (255, 0,   0):   0x3,  # Red
}

def nearest_colour(r, g, b):
    best, best_dist = 0x1, float('inf')
    for (pr, pg, pb), code in PALETTE.items():
        d = (r - pr)**2 + (g - pg)**2 + (b - pb)**2
        if d < best_dist:
            best_dist, best = d, code
    return best

def convert(png_path, var_name, target_size=None):
    img = Image.open(png_path).convert('RGB')
    if target_size:
        img = img.resize((target_size, target_size), Image.NEAREST)
    w, h = img.size
    pixels = list(img.getdata())

    # Pack 4 pixels per byte, row-major, MSB first
    row_bytes = (w + 3) // 4
    buf = []
    for row in range(h):
        for col in range(0, w, 4):
            byte = 0
            for bit in range(4):
                px_idx = row * w + col + bit
                if col + bit < w:
                    r, g, b = pixels[px_idx]
                    code = nearest_colour(r, g, b)
                else:
                    code = 0x1  # pad with white
                byte |= (code << (6 - bit * 2))
            buf.append(byte)

    total = len(buf)
    header = f"""\
#pragma once
#include <stdint.h>

// Generated from {os.path.basename(png_path)}
// Size: {w}x{h}px, {total} bytes (2bpp, 4px/byte)
// Colours: 0x0=Black 0x1=White 0x2=Yellow 0x3=Red

static constexpr uint16_t {var_name}_WIDTH  = {w};
static constexpr uint16_t {var_name}_HEIGHT = {h};

static const uint8_t {var_name}[] = {{
"""
    rows = []
    for i in range(0, total, 16):
        chunk = buf[i:i+16]
        rows.append('    ' + ', '.join(f'0x{b:02X}' for b in chunk))
    header += ',\n'.join(rows)
    header += '\n};\n'

    out_path = os.path.join(os.path.dirname(png_path), f'{var_name}.h')
    with open(out_path, 'w') as f:
        f.write(header)
    print(f'Written {total} bytes to {out_path}  ({w}x{h})')

if __name__ == '__main__':
    if len(sys.argv) not in (3, 4):
        print('Usage: img_to_epd.py <input.png> <VarName> [size]')
        sys.exit(1)
    size = int(sys.argv[3]) if len(sys.argv) == 4 else None
    convert(sys.argv[1], sys.argv[2], size)
