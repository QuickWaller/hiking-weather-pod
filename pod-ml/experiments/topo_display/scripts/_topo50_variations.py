from PIL import Image, ImageDraw
import numpy as np
Image.MAX_IMAGE_PIXELS = None

im = Image.open('BK34.tif').convert('RGB')
arr = np.asarray(im).astype(np.int16)
a = arr[300:500, 200:400]                     # pick 0: track + spot height + river + contours
R, G, B = a[..., 0], a[..., 1], a[..., 2]
mx = np.maximum(np.maximum(R, G), B)

# shared feature detection
feat    = mx < 90                              # track casing, text, spot heights
water   = (B > R + 8) & (B >= G - 5) & (mx > 120)
contour = (R >= G) & (G >= B) & (R - B > 20) & (mx >= 90) & (mx < 240)

K, W, Rd, Y = (0, 0, 0), (255, 255, 255), (255, 0, 0), (255, 255, 0)


def render(bg, c_contour, c_water, c_feat):
    out = np.full(a.shape, bg, 'uint8')
    if c_contour is not None:
        out[contour] = c_contour
    out[water] = c_water
    out[feat] = c_feat
    return out


variants = [
    ("A baseline: water=red", render(W, Y, Rd, K)),
    ("B route-hero: track=red", render(W, Y, K, Rd)),
    ("C clean: no contours", render(W, None, Rd, K)),
    ("D night: black bg", render(K, Y, Rd, W)),
]

# 2x2 montage, each 400px, with a label strip
cell = 400
pad = 24
M = Image.new('RGB', (cell * 2 + pad, cell * 2 + pad + 60), (200, 200, 200))
draw = ImageDraw.Draw(M)
for i, (name, img) in enumerate(variants):
    p = Image.fromarray(img).resize((cell, cell), Image.NEAREST)
    cx = (i % 2) * (cell + pad)
    cy = (i // 2) * (cell + pad) + 30
    M.paste(p, (cx, cy))
    draw.text((cx + 6, cy - 22), name, fill=(0, 0, 0))
M.save('outputs/topo_sample/variations.png')
print('wrote outputs/topo_sample/variations.png')
