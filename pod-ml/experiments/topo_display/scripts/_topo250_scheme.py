from PIL import Image, ImageDraw
import numpy as np
Image.MAX_IMAGE_PIXELS = None
arr = np.asarray(Image.open('250-05.tif').convert('RGB')).astype(np.int16)
H, W, _ = arr.shape
S = 200


def classify(a):
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    mx = np.maximum(np.maximum(R, G), B)
    black = mx < 90
    water = (B > R + 8) & (B >= G - 5) & (mx > 120)
    brown = (R >= G) & (G >= B) & (R - B > 20) & (mx >= 90) & (mx < 245)
    bush = (G >= R) & (G >= B) & (mx < 235) & (mx > 110)
    out = np.full(a.shape, (255, 255, 0), 'uint8')   # open = yellow
    out[bush] = (255, 255, 255)                       # bush = white
    out[brown] = (0, 0, 0)                            # contours+roads = black
    out[water] = (255, 0, 0)                          # water = red
    out[black] = (0, 0, 0)                            # text/features = black
    return out


# pick a few content-rich windows (land + roads + some water), spread vertically
picks = []
for y0 in range(0, H - S, (H - S) // 4):
    best = None
    for y in range(y0, min(y0 + (H - S) // 4, H - S), 150):
        for x in range(0, W - S, 300):
            a = arr[y:y + S, x:x + S]
            R, G, B = a[..., 0], a[..., 1], a[..., 2]
            mx = np.maximum(np.maximum(R, G), B)
            fblack = ((R >= G) & (G >= B) & (R - B > 20)).mean() + (mx < 90).mean()
            fwater = ((B > R + 8) & (B >= G - 5) & (mx > 120)).mean()
            score = (0.05 < fblack < 0.5) * (fblack + 0.3 * (0.05 < fwater < 0.5))
            if best is None or score > best[0]:
                best = (score, x, y)
    if best and best[0] > 0:
        picks.append((best[1], best[2]))
picks = picks[:3]

cell = 360
M = Image.new('RGB', (cell * 3 + 30, cell + 40), (210, 210, 210))
d = ImageDraw.Draw(M)
for i, (x, y) in enumerate(picks):
    p = Image.fromarray(classify(arr[y:y + S, x:x + S])).resize((cell, cell), Image.NEAREST)
    cx = i * (cell + 10) + 5
    M.paste(p, (cx, 25))
    d.text((cx + 4, 6), f"x={x} y={y}  (~4.2km)", fill=(0, 0, 0))
M.save('outputs/topo_sample/topo250_scheme.png')
print('picks', picks)
print('wrote outputs/topo_sample/topo250_scheme.png')
