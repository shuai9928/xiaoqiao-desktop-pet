"""Build the compact Live2.5D room from assets/house/witch-house-v1.png.

The v1 painting is a wide house: left alcove for the swing, right cabinet for
a permanent AI dashboard.  The user found that too wide (it blocks the desktop)
and too flat.  This tool derives a single, compact room from the same art,
then splits it into depth layers so the renderer can do real occlusion:

1. Mirror the left alcove about x=CUT.  The symmetric room gets a pointed
   (gothic) window from the mirrored round arch, drapes on both sides.
2. Repair what mirroring breaks: the two crescent halves form a lens -> fill
   it from the sky and put back one crescent; the roof gets the original
   crescent crest seated on the new gable.  The platform centre stays plain
   (the AI nameplate goes there).
3. Split into FG (front frame: roof, beam, drapes, curtains, pillars, front
   pendants, platform) and BG (room interior).  BG is filled a little under
   the frame so a few pixels of parallax never reveal holes, and gets a baked
   contact shade from the frame (light from the upper left).
4. Box-room depth map for BG (0 = front plane, 1 = back wall).

Outputs: assets/house/room-v2-bg.png, room-v2-fg.png, room-v2-depth.png and
room-v2.json (geometry the renderer and pet.py use).  Deterministic; rerun
after changing the source art or the masks below.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "house" / "witch-house-v1.png"
OUT = ROOT / "assets" / "house"
CUT = 430                       # mirror axis in v1 pixels (inside the window's centre pane)

# Room geometry in compact-room pixels (left half; the right half mirrors it)
FX, BX = 150.0, 295.0           # side wall: front edge x / back corner x
CF, CB = 172.0, 255.0           # ceiling: front (beam bottom) y / back wall top y
FF, FB = 920.0, 755.0           # floor: front edge y / back wall bottom y
# Swing placement: scene-art px -> room px.  The crossbar tucks under the beam,
# behind the drape swags, so it hangs from the ceiling instead of floating; low
# enough that the swags never cover her hat tip, high enough that her shoes stay
# above the floor line at the swing's depth.
SWING_KS = 0.518
SWING_CX, SWING_TOP = 430.0, 202.0
SCENE_BAR_CX, SCENE_BAR_TOP = 667.0, 5.0     # crossbar centre / top in scene art
# Parallax (room px at full camera offset): the frame moves against the swing,
# the back wall with it.  The swing itself is the still reference plane.
PAR_FRONT, PAR_BACK = 3.8, 7.7
PLAQUE = (176, 930, 684, 982)   # nameplate face on the platform front
# Ambient life (room_life.py), measured on the compact room.  Depths match the
# box room: window/back wall 1, shelf orbs on the side walls ~.45.
LIFE = {
    "moon": [436, 410, 36],                       # crescent centre, radius
    "glass": [                                    # window panes (pointed arches)
        [[383, 690], [383, 420], [396, 380], [430, 338], [464, 380], [477, 420], [477, 690]],
        [[313, 690], [313, 470], [322, 440], [337, 424], [352, 440], [360, 470], [360, 690]],
        [[500, 690], [500, 470], [508, 440], [523, 424], [538, 440], [547, 470], [547, 690]],
    ],
    "stars": [[400, 372, 2.6], [462, 468, 2.0], [398, 476, 1.6], [326, 456, 2.0],
              [349, 503, 1.5], [512, 458, 2.2], [537, 507, 1.6], [346, 332, 2.4],
              [513, 332, 2.4]],
    "orbs": [[212, 438, 17, .45], [647, 438, 17, .45]],
    "beam": [[312, 692], [548, 692], [640, 880], [220, 880]],
    "glints": [[372, 200, 17], [486, 200, 17], [34, 240, 22], [824, 240, 22],
               [155, 269, 14], [703, 269, 14], [182, 305, 13], [676, 305, 13],
               [154, 329, 15], [704, 329, 15], [76, 362, 15], [782, 362, 15],
               [441, 104, 16]],
}


def _blur(m, r):
    return np.asarray(Image.fromarray(np.clip(m * 255, 0, 255).astype(np.uint8))
                      .filter(ImageFilter.GaussianBlur(r))).astype(np.float32) / 255


def _dilate(m, n):
    return np.asarray(Image.fromarray(m.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(n))) > 0


def _harmonic_fill(arr, hole, iters=900):
    out = arr.copy()
    ys, xs = np.nonzero(hole)
    if not len(ys):
        return out
    y0, y1 = max(0, ys.min() - 2), min(arr.shape[0], ys.max() + 3)
    x0, x1 = max(0, xs.min() - 2), min(arr.shape[1], xs.max() + 3)
    sub = out[y0:y1, x0:x1]
    m = hole[y0:y1, x0:x1]
    ring = (~m) & (np.roll(m, 1, 0) | np.roll(m, -1, 0) | np.roll(m, 1, 1) | np.roll(m, -1, 1))
    sub[m] = sub[ring].mean(axis=0)
    for _ in range(iters):
        avg = (np.roll(sub, 1, 0) + np.roll(sub, -1, 0) + np.roll(sub, 1, 1) + np.roll(sub, -1, 1)) / 4
        sub[m] = avg[m]
    out[y0:y1, x0:x1] = sub
    return out


def compact_room(im):
    """Mirror + moon + crest repairs.  Returns the compact RGBA room (float array)."""
    W, H = im.size
    src = np.asarray(im).astype(np.float32)
    left = im.crop((0, 0, CUT, H))
    base = Image.new("RGBA", (CUT * 2, H))
    base.paste(left, (0, 0))
    base.paste(ImageOps.mirror(left), (CUT, 0))
    a = np.asarray(base).astype(np.float32)
    CW = CUT * 2
    yy, xx = np.mgrid[0:H, 0:CW]

    # moon: the mirror turns the crescent into a lens around x=CUT
    mc = (450, 412)                                   # crescent centre in v1
    lum = a[..., :3].mean(axis=2)
    near = ((xx - CUT) ** 2 / 60.0 ** 2 + (yy - mc[1]) ** 2 / 56.0 ** 2) < 1
    lens = _dilate(near & (lum > 200), 9) & near
    a = _harmonic_fill(a, lens)
    sl = src[..., :3].mean(axis=2)
    ry, rx = np.mgrid[0:H, 0:W]
    disk = ((rx - mc[0]) ** 2 + (ry - mc[1]) ** 2) < 50 ** 2
    sky = np.median(sl[disk & (sl < 190)])
    wgt = _blur(np.clip((sl - sky - 18) / 55.0, 0, 1) * disk, 0.8)
    dx = CUT + 6 - mc[0]                              # centred in the pane, opening right
    ys, xs = np.nonzero(wgt > 0.01)
    w = wgt[ys, xs][:, None]
    a[ys, xs + dx, :3] = a[ys, xs + dx, :3] * (1 - w) + src[ys, xs, :3] * w

    # crest: the crescent finial and its dome, seated on the new gable.  Below
    # the beam's top (y>=110) both images share the same beam, so blend sideways.
    cx = 757
    x0, x1, y1 = cx - 175, cx + 175, 178
    cy_, cx_ = np.mgrid[0:y1, x0:x1]
    o = src[0:y1, x0:x1]
    dome = np.clip((1.0 - (((cx_ - cx) / 150.0) ** 2 + ((cy_ - 116) / 104.0) ** 2)) / 0.04, 0, 1)
    side = np.clip(1 - (np.abs(cx_ - cx) - 140) / 32.0, 0, 1)
    wc = np.where(cy_ < 110, dome, np.maximum(dome, side * (cy_ >= 110)))
    wc = np.clip(wc, 0, 1) * (o[..., 3] / 255) * np.clip((y1 - cy_) / 6.0, 0, 1)
    tx0 = CUT - (cx - x0)
    d = a[0:y1, tx0:tx0 + (x1 - x0)]
    da = d[..., 3:4] / 255
    ww = wc[..., None]
    oa = ww + da * (1 - ww)
    rgb = (o[..., :3] * ww + d[..., :3] * da * (1 - ww)) / np.maximum(oa, 1e-6)
    d[..., :3] = np.where(oa > 0, rgb, d[..., :3])
    d[..., 3] = oa[..., 0] * 255
    a[0:y1, tx0:tx0 + (x1 - x0)] = d
    a[..., 3] = np.where(a[..., 3] < 8, 0, a[..., 3])
    return a


def split_layers(a):
    H, W = a.shape[:2]
    half = W // 2
    alpha = a[..., 3] / 255
    r, b = a[..., 0], a[..., 2]
    lum = a[..., :3].mean(axis=2)
    yy, xx = np.mgrid[0:H, 0:W]
    xm = np.where(xx < half, xx, W - 1 - xx)

    def poly(points):
        m = Image.new("L", (W, H), 0)
        d = ImageDraw.Draw(m)
        d.polygon(points, fill=255)
        d.polygon([(W - 1 - x, y) for x, y in points], fill=255)
        return np.asarray(m) > 0

    def line_y(pts):
        xs, ys = zip(*pts)
        return np.interp(xm[0], xs, ys)[None, :]

    fg = xm < 58                                                         # outer structure
    fg |= yy < line_y([(0, 236), (122, 232), (160, 218), (200, 203), (250, 188),
                       (300, 176), (340, 169), (430, 171)])              # roof, beam, crest
    fg |= poly([(112, 228), (160, 212), (250, 186), (338, 166), (342, 190), (334, 205),
                (320, 222), (280, 250), (220, 282), (150, 312), (112, 312)])   # swag
    swag_zone = poly([(100, 150), (352, 150), (352, 236), (300, 262), (230, 298),
                      (160, 330), (100, 330)])
    swag_col = np.asarray(Image.fromarray(((lum > 100) & swag_zone).astype(np.uint8) * 255)
                          .filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(5))) > 0
    fg |= swag_col & swag_zone
    fg |= poly([(48, 225), (128, 225), (128, 275), (123, 275), (123, 890), (48, 890)])    # pillar
    fg |= poly([(58, 268), (166, 268), (161, 400), (151, 520), (142, 560), (151, 650),
                (159, 720), (171, 790), (183, 850), (176, 874), (58, 874)])        # curtain
    zone = poly([(0, 170), (205, 170), (205, 300), (174, 300), (174, 470), (0, 470)])
    zone |= poly([(350, 163), (400, 163), (400, 248), (350, 248)])
    jewel = _dilate(((r - b > 30) & (lum > 105) | (lum > 165)) & zone, 5)
    fg |= jewel & zone                                                   # front pendants
    fg |= yy > line_y([(0, 858), (100, 862), (140, 876), (165, 903), (200, 917), (430, 920)])
    fg &= alpha > 0.03

    dx = np.clip((xm - FX) / (BX - FX), 0, 1)
    dy = np.minimum(np.clip((FF - yy) / (FF - FB), 0, 1), np.clip((yy - CF) / (CB - CF), 0, 1))
    # keep the true box depth under the frame too: the frame hides it, and the
    # mesh then never drags ceiling/back wall along with the frame near its edges
    depth = np.minimum(dx, dy)

    interior = (~fg) & (alpha > 0.03)
    keep = _dilate(interior, 31)
    # push-pull fill of the colour under the frame (only a thin strip ever shows)
    col = a[..., :3] * interior[..., None]
    wgt = interior.astype(np.float32)
    levels = []
    c, w_ = col, wgt
    while min(c.shape[:2]) > 4:
        levels.append((c, w_))
        h2, w2 = c.shape[0] // 2, c.shape[1] // 2
        c = c[:h2 * 2, :w2 * 2].reshape(h2, 2, w2, 2, 3).sum(axis=(1, 3))
        w_ = w_[:h2 * 2, :w2 * 2].reshape(h2, 2, w2, 2).sum(axis=(1, 3))
    fill = c / np.maximum(w_, 1e-6)[..., None]
    for c, w_ in reversed(levels):
        up = np.asarray(Image.fromarray(np.clip(fill, 0, 255).astype(np.uint8)).resize(
            (c.shape[1], c.shape[0]), Image.BILINEAR)).astype(np.float32)
        cov = np.minimum(w_, 1)[..., None]
        mean = c / np.maximum(w_, 1e-6)[..., None]
        fill = np.where((w_ > 0)[..., None], mean * cov + up * (1 - cov), up)
    full = np.zeros_like(a[..., :3])
    full[:fill.shape[0], :fill.shape[1]] = fill
    bgc = np.where(interior[..., None], a[..., :3], full)
    # baked contact shade: the frame darkens the interior right behind its edge
    occ = _blur(fg.astype(np.float32), 9)
    occ = np.roll(np.roll(occ, 4, axis=1), 5, axis=0)
    bgc = bgc * (1 - 0.30 * occ * interior)[..., None]
    bg = np.dstack([bgc, np.where(keep, alpha, 0.0) * 255])
    fgi = np.dstack([a[..., :3], alpha * 255 * fg])
    return bg, fgi, depth, fg


def plaque_band(fg):
    """x span the plaque may grow along: the platform front's opaque width on
    the plaque's lower third (the platform curves in towards its bottom),
    less a corner radius, never narrower than the authored slot."""
    y = int(PLAQUE[1] + (PLAQUE[3] - PLAQUE[1]) * .7)
    xs = np.nonzero(fg[y] & (np.arange(fg.shape[1]) > 0))[0]
    r = (PLAQUE[3] - PLAQUE[1]) // 3
    x0, x1 = (int(xs.min()) + r, int(xs.max()) - r) if len(xs) else PLAQUE[0::2]
    return [min(x0, PLAQUE[0]), max(x1, PLAQUE[2])]


def main():
    im = Image.open(SRC).convert("RGBA")
    a = compact_room(im)
    bg, fgi, depth, fg = split_layers(a)
    H, W = depth.shape
    Image.fromarray(np.clip(bg, 0, 255).astype(np.uint8), "RGBA").save(OUT / "room-v2-bg.png", optimize=True)
    Image.fromarray(np.clip(fgi, 0, 255).astype(np.uint8), "RGBA").save(OUT / "room-v2-fg.png", optimize=True)
    Image.fromarray(np.clip(depth * 255, 0, 255).astype(np.uint8)).save(OUT / "room-v2-depth.png", optimize=True)
    z0 = PAR_FRONT / (PAR_FRONT + PAR_BACK)
    meta = {
        "source": SRC.name, "size": [W, H], "mirror_cut": CUT,
        "room": {"side_front_x": FX, "side_back_x": BX, "ceil_front_y": CF,
                 "ceil_back_y": CB, "floor_front_y": FF, "floor_back_y": FB},
        "swing": {"ks": SWING_KS, "cx": SWING_CX, "top": SWING_TOP,
                  "scene_bar_cx": SCENE_BAR_CX, "scene_bar_top": SCENE_BAR_TOP,
                  "plane_depth": round(z0, 4),
                  "floor_y": round(FF - (FF - FB) * z0, 1)},
        "parallax": {"front": PAR_FRONT, "back": PAR_BACK},
        "plaque": list(PLAQUE),
        "plaque_max": plaque_band(fg),
        "life": LIFE,
    }
    (OUT / "room-v2.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"size": [W, H], "fg_px": int(fg.sum())}))


if __name__ == "__main__":
    sys.exit(main())
