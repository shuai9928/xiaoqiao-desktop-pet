"""Build assets/scene/swing_studio.png: the swing layer for the studio scene.

The studio presents her like a figure on a clean product stand (Apple-like:
one material, soft light, no ornament).  The painted swing layer carries game
ornaments the studio does not want: crossbar remnants above the rope tops (they
used to hide behind the gilded crossbar), the crystal pendant dangling under
the cushion, a gold star under the seat and a few floating sparkle specks.
This tool removes exactly those and nothing on her: the hat, face, hands,
ropes, cushion and shoes stay untouched.  Deterministic; rerun after
make_scene_layers.py.
"""
from collections import deque
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SCENE = ROOT / "assets" / "scene"


def clean(swing):
    a = np.asarray(swing.convert("RGBA")).astype(np.float32)
    H, W = a.shape[:2]
    yy, xx = np.mgrid[0:H, 0:W]
    r, b = a[..., 0], a[..., 2]
    lum = a[..., :3].mean(axis=2)
    gold = (r - b > 35) & (lum > 110)
    kill = np.zeros((H, W), bool)
    kill |= (xx < 352) & (yy < 150)                           # left crossbar remnant
    kill |= (xx > 990) & (yy < 186)                           # right crossbar remnant
    kill |= gold & (yy < 145) & (xx > 600) & (xx < 800)       # centre ornament curl
    kill |= (xx > 352) & (xx < 442) & (yy > 1012) & (yy < 1145)   # pendant under the cushion
    kill |= (xx > 500) & (xx < 548) & (yy > 1012) & (yy < 1070)   # gold star under the seat
    a[kill, 3] = 0
    # keep only the main silhouette: floating specks are separate blobs
    alpha = a[..., 3] > 20
    small = alpha[::2, ::2]
    lab = np.zeros(small.shape, np.int32)
    sizes = []
    for y0 in range(small.shape[0]):
        for x0 in np.nonzero(small[y0] & (lab[y0] == 0))[0]:
            if lab[y0, x0]:
                continue
            n = len(sizes) + 1
            lab[y0, x0] = n
            q, cnt = deque([(y0, x0)]), 0
            while q:
                cy, cx = q.popleft()
                cnt += 1
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        ny, nx = cy + dy, cx + dx
                        if (0 <= ny < small.shape[0] and 0 <= nx < small.shape[1]
                                and small[ny, nx] and not lab[ny, nx]):
                            lab[ny, nx] = n
                            q.append((ny, nx))
            sizes.append(cnt)
    main = int(np.argmax(sizes)) + 1
    keep = np.repeat(np.repeat(lab == main, 2, 0), 2, 1)[:H, :W]
    keep = np.asarray(Image.fromarray(keep.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(5))) > 0
    a[~keep, 3] = 0
    a[a[..., 3] < 8, 3] = 0
    return Image.fromarray(a.astype(np.uint8), "RGBA"), len(sizes) - 1


def main():
    swing = Image.open(SCENE / "swing.png")
    out, dropped = clean(swing)
    out.save(SCENE / "swing_studio.png", optimize=True)
    print({"dropped_blobs": dropped, "bbox": out.getchannel("A").getbbox()})


if __name__ == "__main__":
    sys.exit(main())
