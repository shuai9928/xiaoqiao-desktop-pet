"""Plan-stage probe #2: count strict-gold blobs on the SS(=2) back layer
(the layer the smoke is drawn into) for the a2_smoke_only_full state,
replicating tools/fx2_harness.py cmd_offline's loop for that one state.
"""
import os
import sys
sys.path.insert(0, os.path.join("tools"))
import fx2_harness as H
from PIL import Image

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join("outputs", "fx2", "_diag_ss")

def strict_gold(p):
    r, g, b = p[0], p[1], p[2]
    return r >= 200 and 140 <= g <= 235 and b <= 130 and (r - b) >= 90

def blobs_of(im, min_px=8):
    w, h = im.size
    px = im.load()
    pts = set()
    for y in range(h):
        for x in range(w):
            if strict_gold(px[x, y][:3]):
                pts.add((x, y))
    seen, out = set(), []
    for p0 in pts:
        if p0 in seen:
            continue
        stack, comp = [p0], []
        seen.add(p0)
        while stack:
            x, y = stack.pop()
            comp.append((x, y))
            for dx in (-2, -1, 0, 1, 2):
                for dy in (-2, -1, 0, 1, 2):
                    q = (x + dx, y + dy)
                    if q in pts and q not in seen:
                        seen.add(q)
                        stack.append(q)
        if len(comp) >= min_px:
            xs = [c[0] for c in comp]; ys = [c[1] for c in comp]
            out.append((len(comp), min(xs), max(xs), min(ys), max(ys)))
    out.sort(reverse=True)
    return out

scene = H.Scene()
fxc = fx2_fxc = H.fx.FX(H.FX_SCALE, H.SS, defer=True, assets_dir=str(H.ASSETS))
os.makedirs(OUT, exist_ok=True)
# 烟柱判定区:帽尖上方的背层(人物包围盒顶以上)。B3 金萤火是 I-30 已验收
# 的常驻元素,不在烟柱区,单独排除以便按「烟柱顶部恰 1 星」口径计数。
SMOKE_TOP = scene.girl_bbox[1]
frames, multi, bad_smoke = 12, 0, 0
for i in range(frames):
    ot = (i / max(1, frames - 1)) * 11.0
    now = H.warm_state(fxc, scene, ot, thinking=True, fast=True, moving=False)
    items = H.items_at_screen(scene, ot)
    frame = scene.bg.copy()
    back = Image.new("RGBA", scene.bg.size, (0, 0, 0, 0))
    fxc.hat.draw(back)
    H._draw_orbit_side(back, fxc, items, False, True)
    back.save(os.path.join(OUT, "ss_%02d.png" % i))
    bl = blobs_of(back)
    n = len(bl)
    if n >= 2:
        multi += 1
    smoke_blobs = [b for b in bl if (b[3] + b[4]) / 2 < SMOKE_TOP]
    if len(smoke_blobs) != 1:
        bad_smoke += 1
    print("ss_%02d: gold_blobs=%d smoke_region=%d %s" % (
        i, n, len(smoke_blobs),
        "; ".join("n=%d x[%d-%d] y[%d-%d]" % b for b in bl[:4])))
print("frames_with_2plus_distinct_gold_blobs:", multi, "/", frames)
print("frames_where_smoke_region_is_not_exactly_1_gold_blob:", bad_smoke, "/", frames)
