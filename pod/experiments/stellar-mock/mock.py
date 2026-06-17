"""Stellar-map legibility mock for the 1.54" 4-colour e-paper (200x200, B/W/R/Y).

Renders an honest, hand-placed southern-sky dome strictly in the four panel inks
(every pixel snapped to the palette at the end -> zero anti-aliasing the panel
can't show). Accuracy is irrelevant here; this exists to test density + rendering
legibility at true 200x200. Physical panel is only 27x27 mm (~7.4 px/mm).

Run:  python mock.py
Out:  sky_native.png (true 200x200), sky_x4.png (nearest-neighbour x4, pixels visible)
"""
import math, os, random
from PIL import Image, ImageDraw

random.seed(7)
W = H = 200
CX, CY, R = 100, 100, 90
HERE = os.path.dirname(os.path.abspath(__file__))

# --- panel palette (approx the Waveshare 1.54" G inks, not pure RGB) ---
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

def in_dome(x, y, margin=0):
    return (x-CX)**2 + (y-CY)**2 <= (R-margin)**2

placed = []  # for min-separation dedup
def far_enough(x, y, d_min):
    return all((x-px)**2+(y-py)**2 >= d_min*d_min for px, py in placed)

def star(x, y, mag):
    if mag <= 0.4:   r = 3
    elif mag <= 1.4: r = 2
    elif mag <= 2.4: r = 1
    else:            r = 0
    if r == 0:
        putpix(x, y, WHITE)
    else:
        disc(x, y, r, WHITE)
    placed.append((x, y))

def line(p0, p1, c=WHITE):
    d.line([p0, p1], fill=c, width=1)

# --- horizon ring + faint inner ring ---
d.ellipse([CX-R, CY-R, CX+R, CY+R], outline=WHITE)
for a in range(0, 360, 6):  # dotted inner ring at ~30deg alt
    rr = R*0.66
    putpix(CX+rr*math.cos(math.radians(a)), CY+rr*math.sin(math.radians(a)), WHITE)

# --- Milky Way band: stipple yellow within a curved swath ---
def mw_curve(t):           # t in 0..1 -> point along galactic band
    x = 40 + 120*t
    y = 45 + 130*t + 18*math.sin(t*math.pi)
    return x, y
for _ in range(900):
    t = random.random()
    bx, by = mw_curve(t)
    ox = random.gauss(0, 16); oy = random.gauss(0, 16)
    x, y = bx+ox, by+oy
    if in_dome(x, y, 2) and random.random() < 0.35:
        putpix(x, y, YELLOW)

# --- background faint stars (single px, min-separation) ---
n = 0
while n < 70:
    x = random.randint(CX-R, CX+R); y = random.randint(CY-R, CY+R)
    if in_dome(x, y, 3) and far_enough(x, y, 5):
        putpix(x, y, WHITE); placed.append((x, y)); n += 1

# --- constellations (hand-placed, lines first so star discs sit on top) ---
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

bright = [(40,96,-1.5),(60,120,-0.7),(122,158,0.0),(131,150,0.6)]  # Sirius,Canopus,Pointers
for grp in (orion.values(), crux.values(), scorpius, bright):
    for x,y,m in grp: star(x,y,m)

# --- planets (red +) ---
def plus(x,y,c=RED):
    for k in range(-2,3): putpix(x+k,y,c); putpix(x,y+k,c)
plus(112,80); plus(136,70)        # Jupiter, Saturn near ecliptic

# --- showpiece deep-sky markers (red open squares) ---
def osq(x,y,s=2,c=RED):
    d.rectangle([x-s,y-s,x+s,y+s], outline=c)
osq(150,162); osq(136,172)        # LMC, SMC (low, toward south)

# --- Moon: yellow disc, carve shadow for waxing-gibbous ---
mx,my = 76,128
disc(mx,my,7,YELLOW)
for dy in range(-8,9):
    for dx in range(-8,9):
        if (dx+9)**2+dy*dy <= 49:   # black disc offset left -> thin crescent shadow
            putpix(mx+dx,my+dy,BLACK)

# --- cardinal labels (looking-UP convention: E left, W right) ---
d.text((CX-2, 2),    "N", fill=WHITE)
d.text((CX-2, H-11), "S", fill=WHITE)
d.text((4, CY-5),    "E", fill=WHITE)
d.text((W-9, CY-5),  "W", fill=WHITE)

# --- snap every pixel to the 4-colour palette (kills any stray AA) ---
px = img.load()
for y in range(H):
    for x in range(W):
        r,g,b = px[x,y]
        px[x,y] = min(PALETTE, key=lambda c:(c[0]-r)**2+(c[1]-g)**2+(c[2]-b)**2)

img.save(os.path.join(HERE, "sky_native.png"))
img.resize((W*4, H*4), Image.NEAREST).save(os.path.join(HERE, "sky_x4.png"))
print("wrote sky_native.png + sky_x4.png to", HERE)
