"""Real sky chart for the 1.54" 4-colour e-paper (200x200, B/W/R/Y).

Unlike mock*.py (hand-placed), this computes the ACTUAL sky:
  - Hipparcos bright stars (alt/az for the observer)
  - constellation line figures (d3-celestial, RA/Dec vertices)
  - all naked-eye planets + Sun + Moon (de421 ephemeris), Moon phase
for a given location + instant, projected onto the horizon dome.

Default scene: Auckland, 01:00 NZST 15 May 2026  ==  13:00 UTC 14 May 2026.

Render rules mirror the chosen v2 style: black sky, yellow constellation lines,
white star-dots on top (size by magnitude), red = planets/Sun (noteworthy),
yellow Moon phase disc. Every pixel snapped to the 4 panel inks (no anti-alias).
Looking-UP orientation: N top, E left, W right.

First run downloads de421.bsp (~17 MB) + hip_main.dat into this folder (cached).
Run:  python sky_real.py
Out:  sky_real_native.png (200x200), sky_real_x4.png
"""
import json, math, os
import numpy as np
from skyfield.api import load, wgs84, Star, Loader
from skyfield.data import hipparcos
from skyfield import almanac
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
loader = Loader(HERE)

# ---------------- scene ----------------
import sys
LAT, LON = -36.8485, 174.7633          # Auckland
ts = loader.timescale()
# default: 01:00 NZST 15 May = 13:00 UTC 14 May. Override: python sky_real.py Y M D H(UTC) [tag]
if len(sys.argv) >= 5:
    t = ts.utc(int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), 0, 0)
    TAG = "_" + sys.argv[5] if len(sys.argv) >= 6 else ""
else:
    t = ts.utc(2026, 5, 14, 13, 0, 0)
    TAG = ""

# ---- curation (the v1 lesson: full sky is unreadable at 200px) ----
CURATE   = True
MAG_LIMIT = 3.2 if CURATE else 4.5     # faintest star plotted
MIN_SEP   = 4                          # px; drop fainter of any too-close pair
# recognizable / bright constellations, southern-sky weighted (d3-celestial ids)
CON_WHITELIST = {
    "Ori","CMa","CMi","Tau","Gem","Leo","Sco","Sgr","Cru","Cen","Car","Vel",
    "Cas","Aqr","Cap","Lib","Vir","Boo","Crv","Lup","Ara","TrA","Gru","Pav",
    "Tuc","Eri","CrA","Pup","Aql","Cyg","Per","And","Peg","Hya",
} if CURATE else None

# ---------------- panel ----------------
W = H = 200
CX, CY, R = 100, 100, 90
BLACK, WHITE, YELLOW, RED = (0,0,0),(245,245,245),(240,205,40),(210,45,40)
PALETTE = [BLACK, WHITE, YELLOW, RED]

img = Image.new("RGB", (W, H), BLACK)
d = ImageDraw.Draw(img)
def putpix(x,y,c):
    if 0<=x<W and 0<=y<H: img.putpixel((int(round(x)),int(round(y))), c)
def disc(x,y,r,c):
    for dy in range(-r,r+1):
        for dx in range(-r,r+1):
            if dx*dx+dy*dy<=r*r+1: putpix(x+dx,y+dy,c)

# stereographic zenithal projection; looking-UP (E left). Returns None below horizon.
def project(alt_deg, az_deg):
    if alt_deg <= 0: return None
    z = math.radians(90.0 - alt_deg)           # zenith distance
    r = R * math.tan(z/2.0)                     # stereographic
    a = math.radians(az_deg)
    x = CX - r*math.sin(a)                      # E (az 90) -> left
    y = CY - r*math.cos(a)                      # N (az 0)  -> top
    return x, y

# ---------------- ephemeris + observer ----------------
eph = loader('de421.bsp')
earth = eph['earth']
here = earth + wgs84.latlon(LAT, LON)
obs = here.at(t)

def altaz_of(target):
    alt, az, _ = obs.observe(target).apparent().altaz()
    return alt.degrees, az.degrees

# ---------------- stars ----------------
with loader.open(hipparcos.URL) as f:
    df = hipparcos.load_dataframe(f)
bright = df[(df['magnitude'] <= MAG_LIMIT) & df['ra_degrees'].notnull()].copy()
star_obj = Star.from_dataframe(bright)
alt, az, _ = obs.observe(star_obj).apparent().altaz()
salt, saz, smag = alt.degrees, az.degrees, bright['magnitude'].values
# HIP -> (alt,az) for constellation-line lookup is not needed; we use RA/Dec lines.

# ---------------- constellation lines (RA/Dec vertices) ----------------
with open(os.path.join(HERE, "conlines.json")) as f:
    con = json.load(f)
# gather all vertices, compute altaz in one batch
verts, segs = [], []   # segs: list of (i0,i1) index pairs into verts
for feat in con["features"]:
    if CON_WHITELIST is not None and feat.get("id") not in CON_WHITELIST:
        continue
    for linestr in feat["geometry"]["coordinates"]:
        prev = None
        for ra, dec in linestr:
            ra = ra + 360.0 if ra < 0 else ra
            idx = len(verts); verts.append((ra/15.0, dec))   # ra in hours
            if prev is not None: segs.append((prev, idx))
            prev = idx
vra = np.array([v[0] for v in verts]); vdec = np.array([v[1] for v in verts])
line_stars = Star(ra_hours=vra, dec_degrees=vdec)
lalt, laz, _ = obs.observe(line_stars).apparent().altaz()
lalt, laz = lalt.degrees, laz.degrees

# ---------------- draw: horizon ring ----------------
d.ellipse([CX-R,CY-R,CX+R,CY+R], outline=WHITE)

# constellation lines (yellow), only segments with both ends above horizon
nlines = 0
for i0,i1 in segs:
    p0 = project(lalt[i0], laz[i0]); p1 = project(lalt[i1], laz[i1])
    if p0 and p1:
        d.line([p0,p1], fill=YELLOW, width=1); nlines += 1

# stars (white dots on top), magnitude -> size
def star_radius(m):
    if m <= 0.5: return 3
    if m <= 1.5: return 2
    if m <= 2.5: return 1
    return 0
nstars = 0
placed = []   # min-separation dedup, brightest first
order = np.argsort(smag)   # ascending magnitude = brightest first
for i in order:
    a_, z_, m_ = salt[i], saz[i], smag[i]
    p = project(a_, z_)
    if not p: continue
    if any((p[0]-qx)**2 + (p[1]-qy)**2 < MIN_SEP*MIN_SEP for qx,qy in placed):
        continue
    r = star_radius(m_)
    if r == 0: putpix(*p, WHITE)
    else: disc(p[0], p[1], r, WHITE)
    placed.append(p); nstars += 1

# ---------------- Sun, Moon, planets ----------------
def plus(x,y,c=RED,s=2):
    for k in range(-s,s+1): putpix(x+k,y,c); putpix(x,y+k,c)
def label(x,y,txt,c=RED): d.text((x+3,y-3), txt, fill=c)

summary = []
planets = {"Me":"mercury","V":"venus","Ma":"mars","J":"jupiter barycenter","Sa":"saturn barycenter"}
for tag,name in planets.items():
    a_,z_ = altaz_of(eph[name]); p = project(a_,z_)
    summary.append(f"{name:18s} alt={a_:6.1f} az={z_:6.1f} {'UP' if a_>0 else 'down'}")
    if p: plus(*p); label(p[0],p[1],tag)

# Sun (red, larger ring) -- below horizon at 1am but report it
sa, sz = altaz_of(eph['sun'])
summary.append(f"{'sun':18s} alt={sa:6.1f} az={sz:6.1f} {'UP' if sa>0 else 'down'}")
ps = project(sa,sz)
if ps:
    disc(ps[0],ps[1],3,RED)

# Moon: yellow disc with phase (illuminated fraction + bright-limb direction)
ma, maz = altaz_of(eph['moon'])
frac = almanac.fraction_illuminated(eph, 'moon', t)
summary.append(f"{'moon':18s} alt={ma:6.1f} az={maz:6.1f} illum={frac*100:4.0f}%")
pm = project(ma, maz)
if pm:
    mx,my = int(round(pm[0])), int(round(pm[1])); mr = 7
    disc(mx,my,mr,YELLOW)
    # carve shadow: offset a black disc to leave `frac` illuminated (simple gibbous/crescent)
    off = int(round((1 - frac) * 2 * mr))      # 0=full, 2r=new
    for dy in range(-mr-2,mr+3):
        for dx in range(-mr-2,mr+3):
            if (dx+ (mr+off))**2 + dy*dy <= mr*mr:
                putpix(mx+dx,my+dy,BLACK)

# ---------------- cardinal labels ----------------
d.text((CX-2,2),"N",fill=WHITE); d.text((CX-2,H-11),"S",fill=WHITE)
d.text((4,CY-5),"E",fill=WHITE); d.text((W-9,CY-5),"W",fill=WHITE)

# ---------------- snap to palette ----------------
px = img.load()
for y in range(H):
    for x in range(W):
        r,g,b = px[x,y]
        px[x,y] = min(PALETTE, key=lambda c:(c[0]-r)**2+(c[1]-g)**2+(c[2]-b)**2)

img.save(os.path.join(HERE,f"sky_real{TAG}_native.png"))
img.resize((W*4,H*4), Image.NEAREST).save(os.path.join(HERE,f"sky_real{TAG}_x4.png"))
print(f"Auckland {t.utc_iso()} UTC | stars drawn={nstars} lines={nlines}")
print("\n".join(summary))
print("wrote sky_real_native.png + sky_real_x4.png")
