"""Plan-stage probe: count distinct strict-gold blobs per a2_smoke_only_full frame.

Strict gold definition mirrors the baked star fill (255,215,40) with soft edge:
r>=200, 140<=g<=230, b<=130, (r-b)>=90. BFS over the gold-pixel set only.
"""

from pathlib import Path
import sys
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "tests"))

import os
from PIL import Image

D = os.path.join("outputs", "fx2", "_diag_offline", "a2_smoke_only_full")
frames = sorted(f for f in os.listdir(D) if f.endswith(".png"))
print("frames:", len(frames))

def strict_gold(p):
    r, g, b = p[0], p[1], p[2]
    return r >= 200 and 140 <= g <= 235 and b <= 130 and (r - b) >= 90

multi = 0
for fn in frames:
    im = Image.open(os.path.join(D, fn)).convert("RGB")
    w, h = im.size
    px = im.load()
    pts = set()
    for y in range(0, h, 1):
        for x in range(0, w, 1):
            if strict_gold(px[x, y]):
                pts.add((x, y))
    seen = set()
    blobs = []
    for p0 in pts:
        if p0 in seen:
            continue
        stack = [p0]
        seen.add(p0)
        comp = []
        while stack:
            x, y = stack.pop()
            comp.append((x, y))
            for dx in (-2, -1, 0, 1, 2):
                for dy in (-2, -1, 0, 1, 2):
                    q = (x + dx, y + dy)
                    if q in pts and q not in seen:
                        seen.add(q)
                        stack.append(q)
        if len(comp) >= 8:  # ignore specks
            xs = [c[0] for c in comp]
            ys = [c[1] for c in comp]
            blobs.append((len(comp), min(xs), max(xs), min(ys), max(ys)))
    blobs.sort(reverse=True)
    tops = [b for b in blobs if b[1] < w * 0.55]  # smoke column is above hat tip
    n = len(tops)
    if n >= 2:
        multi += 1
    summary = "; ".join("n=%d x[%d-%d] y[%d-%d]" % b for b in tops[:4])
    print("%s: gold_blobs=%d %s" % (fn, n, summary))
print("frames_with_2plus_blobs:", multi, "/", len(frames))
