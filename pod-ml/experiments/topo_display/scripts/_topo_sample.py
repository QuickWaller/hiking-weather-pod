from PIL import Image
import numpy as np, os
Image.MAX_IMAGE_PIXELS = None
os.makedirs('outputs/topo_sample', exist_ok=True)
im = Image.open('250-05.tif').convert('RGB')
arr = np.asarray(im)[1400:2100, 1400:2100].astype(np.int16)
Image.fromarray(arr.astype('uint8')).save('outputs/topo_sample/0_original.png')

R, G, B = arr[..., 0], arr[..., 1], arr[..., 2]
PAL = {'K': (0, 0, 0), 'W': (255, 255, 255), 'R': (255, 0, 0), 'Y': (255, 255, 0)}

# --- naive nearest-colour to BWRY, no dither ---
pal = np.array(list(PAL.values()))
flat = arr.reshape(-1, 3)
d = ((flat[:, None, :] - pal[None, :, :]) ** 2).sum(2)
naive = pal[d.argmin(1)].reshape(arr.shape).astype('uint8')
Image.fromarray(naive).save('outputs/topo_sample/1_naive4.png')

# --- feature-aware ---
dark = np.maximum(np.maximum(R, G), B) < 100
blue = (B > R + 10) & (B >= G)
orange = (R > G) & (G > B) & (R - B > 60)
out = np.full(arr.shape, 255, 'uint8')   # default white
out[orange] = PAL['Y']                    # roads -> yellow
out[blue] = PAL['R']                      # water -> red
out[dark] = PAL['K']                      # contours/text -> black (wins)
Image.fromarray(out).save('outputs/topo_sample/2_feature4.png')

# --- on-device realism ---
Image.fromarray(out).resize((200, 200), Image.NEAREST).save('outputs/topo_sample/3_feature_200_scaled.png')
tile = out[250:450, 250:450]   # tight native 200x200 window, true pixel fidelity
Image.fromarray(tile).resize((400, 400), Image.NEAREST).save('outputs/topo_sample/4_feature_200_native_2x.png')
print('class fractions: dark', round(float(dark.mean()), 3), 'water', round(float(blue.mean()), 3), 'road', round(float(orange.mean()), 3))
print('wrote outputs/topo_sample/')
