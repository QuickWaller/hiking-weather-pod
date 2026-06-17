from PIL import Image, ImageDraw
import numpy as np
Image.MAX_IMAGE_PIXELS = None
arr = np.asarray(Image.open('BK34.tif').convert('RGB')).astype(np.int16)
H, W, _ = arr.shape
S = 200


def classify_G(a):
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    mx = np.maximum(np.maximum(R, G), B)
    black = mx < 90
    water = (B > R + 8) & (B >= G - 5) & (mx > 120)
    brown = (R >= G) & (G >= B) & (R - B > 20) & (mx >= 90) & (mx < 245)
    bush = (G >= R) & (G >= B) & (mx < 235) & (mx > 110)
    out = np.full(a.shape, (255, 255, 255), 'uint8')
    out[bush] = (255, 255, 0)
    out[brown] = (0, 0, 0)
    out[water] = (255, 0, 0)
    out[black] = (0, 0, 0)
    return out, water.mean(), bush.mean(), (black | brown).mean()


# bin the width into 6, pick the most feature-rich window in each bin (spatial spread + content)
picks = []
nbins = 6
binw = (W - S) // nbins
for bi in range(nbins):
    best = None
    x0 = bi * binw
    for x in range(x0, x0 + binw, 120):
        for y in range(0, H - S, 120):
            a = arr[y:y + S, x:x + S]
            _, fw, fb, fl = classify_G(a)
            score = (0.04 < fl < 0.4) * (fl + 2 * fw + 0.5 * fb)  # contour detail + reward water/bush
            if best is None or score > best[0]:
                best = (score, x, y)
    picks.append((best[1], best[2]))

# montage 3x2
cell = 300
M = Image.new('RGB', (cell * 3 + 30, cell * 2 + 70), (210, 210, 210))
draw = ImageDraw.Draw(M)
for i, (x, y) in enumerate(picks):
    img, fw, fb, fl = classify_G(arr[y:y + S, x:x + S])
    p = Image.fromarray(img).resize((cell, cell), Image.NEAREST)
    cx = (i % 3) * (cell + 10) + 5
    cy = (i // 3) * (cell + 30) + 25
    M.paste(p, (cx, cy))
    draw.text((cx + 4, cy - 18), f"x={x} y={y}  water={fw:.2f} bush={fb:.2f}", fill=(0, 0, 0))
M.save('outputs/topo_sample/G_locations.png')
print('picks:', picks)
print('wrote outputs/topo_sample/G_locations.png')
