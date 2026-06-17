"""Stellar-map mock v2 -- the "sparse + confident" version.

Drops the faint background star field, the Milky Way stipple, and the dotted
30-deg ring (all clutter that didn't survive at 27 mm). Shows only:
  - constellation lines + their member stars
  - a few very bright stars
  - planets (red +) and the Moon (yellow phase disc)
Same honest constraints as mock.py: 200x200, four panel inks, palette-snapped.

Run:  python mock_v2.py   ->   sky_v2_native.png, sky_v2_x4.png
"""
import math, os
from PIL import Image, ImageDraw

W = H = 200
CX, CY, R = 100, 100, 90
HERE = os.path.dirname(os.path.abspath(__file__))

BLACK  = (0, 0, 0)
WHITE  = (245, 245, 245)
YELLOW = (240, 205, 40)
RED    = (210, 45, 40)
PALETTE = [BLACK, WHITE, YELLOW, RED]

img = Image.new("RGB", (W, H), BLACK)
d = ImageDraw.Draw(img)

def putpix(x, y, c):
    if 0 <= x < W and 0 <= y < H:
        img.putpixel((int(x), int(y)), c)

def disc(x, y, r, c):
    for dy in range(-r, r+1):
        for dx in range(-r, r+1):
            if dx*dx + dy*dy <= r*r + 1:
                putpix(x+dx, y+dy, c)

def star(x, y, mag):
    if mag <= 0.4:   r = 3
    elif mag <= 1.4: r = 2
    elif mag <= 2.4: r = 1
    else:            r = 1   # v2: never plot sub-pixel; faintest shown is 1px
    disc(x, y, r, WHITE)

def line(p0, p1, c=YELLOW):   # v2: lines in YELLOW so white star-dots pop on top
    d.line([p0, p1], fill=c, width=1)

# --- horizon ring only ---
d.ellipse([CX-R, CY-R, CX+R, CY+R], outline=WHITE)

# --- constellations: lines first (yellow), then member stars (white) on top ---
orion = {
    "betelgeuse": (50, 45, 0.5), "bellatrix": (66, 48, 1.6),
    "alnitak": (54, 58, 1.7), "alnilam": (59, 61, 1.7), "mintaka": (64, 63, 2.2),
    "rigel": (51, 73, 0.1), "saiph": (66, 74, 2.1),
}
for a,b in [("betelgeuse","alnitak"),("bellatrix","mintaka"),
            ("alnitak","alnilam"),("alnilam","mintaka"),
            ("rigel","alnitak"),("saiph","mintaka")]:
    line(orion[a][:2], orion[b][:2])
crux = {"top":(96,132,1.3),"bot":(96,166,0.8),"left":(81,150,1.6),"right":(110,151,2.8)}
line(crux["top"][:2], crux["bot"][:2]); line(crux["left"][:2], crux["right"][:2])
scorpius = [(150,92,1.0),(158,104,2.3),(160,118,1.9),(154,131,2.5),
            (144,139,2.6),(137,149,3.0)]
for i in range(len(scorpius)-1):
    line(scorpius[i][:2], scorpius[i+1][:2])

# very bright stand-alone stars (Sirius, Canopus) + the Pointers
bright = [(40,96,-1.5),(60,120,-0.7),(122,158,0.0),(131,150,0.6)]
line((122,158),(131,150))  # join the Pointers so they read as a pair
for grp in (orion.values(), crux.values(), scorpius, bright):
    for x,y,m in grp: star(x,y,m)

# --- planets (red +) ---
def plus(x,y,c=RED):
    for k in range(-2,3): putpix(x+k,y,c); putpix(x,y+k,c)
plus(112,80); plus(136,70)        # Jupiter, Saturn near ecliptic

# --- Moon: yellow disc, carve shadow for waxing-gibbous ---
mx,my = 76,128
disc(mx,my,7,YELLOW)
for dy in range(-8,9):
    for dx in range(-8,9):
        if (dx+9)**2+dy*dy <= 49:
            putpix(mx+dx,my+dy,BLACK)

# --- cardinal labels (looking-UP: E left, W right) ---
d.text((CX-2, 2),    "N", fill=WHITE)
d.text((CX-2, H-11), "S", fill=WHITE)
d.text((4, CY-5),    "E", fill=WHITE)
d.text((W-9, CY-5),  "W", fill=WHITE)

# --- snap to palette ---
px = img.load()
for y in range(H):
    for x in range(W):
        r,g,b = px[x,y]
        px[x,y] = min(PALETTE, key=lambda c:(c[0]-r)**2+(c[1]-g)**2+(c[2]-b)**2)

img.save(os.path.join(HERE, "sky_v2_native.png"))
img.resize((W*4, H*4), Image.NEAREST).save(os.path.join(HERE, "sky_v2_x4.png"))
print("wrote sky_v2_native.png + sky_v2_x4.png to", HERE)
