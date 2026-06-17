from PIL import Image
import numpy as np, os
Image.MAX_IMAGE_PIXELS = None
os.makedirs('outputs/topo_sample', exist_ok=True)
im = Image.open('BK34.tif').convert('RGB')
arr = np.asarray(im).astype(np.int16)
H, W, _ = arr.shape


def classify(a):
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    mx = np.maximum(np.maximum(R, G), B)
    dark = mx < 110
    brown = (R > G) & (G > B) & (R - B > 25) & (mx < 200)   # brown contours -> black
    blue = (B > R + 8) & (B >= G - 5) & (mx > 120)           # water -> red
    orange = (R > G) & (G >= B) & (R - B > 70) & (mx >= 200)  # roads -> yellow
    out = np.full(a.shape, 255, 'uint8')
    out[orange] = (255, 255, 0)
    out[blue] = (255, 0, 0)
    out[dark | brown] = (0, 0, 0)
    return out


# scan 200px windows; score by black/contour density (want detail, not blank bush)
best = []
S = 200
for y in range(0, H - S, 100):
    for x in range(0, W - S, 200):
        a = arr[y:y + S, x:x + S]
        mx = np.maximum(np.maximum(a[..., 0], a[..., 1]), a[..., 2])
        fdark = (mx < 110).mean()
        if 0.04 < fdark < 0.35:          # some detail, not solid black town
            best.append((fdark, x, y))
best.sort(reverse=True)
picks = best[:3]
for i, (fd, x, y) in enumerate(picks):
    a = arr[y:y + S, x:x + S]
    Image.fromarray(a.astype('uint8')).resize((400, 400), Image.NEAREST).save(f'outputs/topo_sample/t50_{i}_orig.png')
    Image.fromarray(classify(a)).resize((400, 400), Image.NEAREST).save(f'outputs/topo_sample/t50_{i}_4col.png')
    print(f'pick {i}: x={x} y={y} dark_frac={fd:.3f}')
print('done')
