"""I-36 acceptance probe (supplements tools/fx2_harness.py measure).

Three measurements on the exact I-30 calibers (outputs/fx2/after_selfcheck/
selfcheck_color2.py + design_spec.md E/C tables):

  share   strict-gold share of the gold/purple/white-core "triplet"
          (gold_spec = HSV h 40~55 & S>=0.45; purple_spec = h 255~275 &
          S 0.25~0.60; white_core = V>=0.95 & S<=0.25; fx region = paired
          on/off max-channel diff > 8), per state over 12 frames.
  diff    girl-opaque pixel diff between two frame sets (before/after a
          change); must be 0. Compares only pixels where the pasted girl
          alpha==255.
  timing  fx-on vs fx-off composite median (30 samples, ot=11 frame).

Usage:
  py _plan_fx2_gold_share.py share  <outdir>          # render+save+share.json
  py _plan_fx2_gold_share.py diff    <dirA> <dirB>    # girl-opaque diff
"""
import json
import os
import statistics
import sys
import time

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join("tools"))
import fx2_harness as H  # noqa: E402

DIFF_T = 8


def strict_gold(p):
    """Strict-gold blob predicate (I-30 验收官口径), shared by probes."""
    r, g, b = p[0], p[1], p[2]
    return r >= 200 and 140 <= g <= 235 and b <= 130 and (r - b) >= 90


def rgb_to_hsv(a):
    x = a / 255.0
    r, g, b = x[..., 0], x[..., 1], x[..., 2]
    maxc = np.max(x, axis=-1)
    minc = np.min(x, axis=-1)
    delta = maxc - minc
    s = np.where(maxc > 0, delta / np.maximum(maxc, 1e-9), 0.0)
    dz = np.where(delta == 0, 1e-9, delta)
    rc, gc, bc = (maxc - r) / dz, (maxc - g) / dz, (maxc - b) / dz
    h = np.where(maxc == r, bc - gc, np.where(maxc == g, 2.0 + rc - bc, 4.0 + gc - rc))
    h = (h / 6.0) % 1.0 * 360.0
    return h, s, maxc


def families(h, s, v):
    return {
        "gold_spec": (h >= 40) & (h <= 55) & (s >= 0.45),
        "purple_spec": (h >= 255) & (h <= 275) & (s >= 0.25) & (s <= 0.60),
        "white_core": (v >= 0.95) & (s <= 0.25),
    }


def frames_dir(out, scene, fxc, back, save=True):
    """Render 12 paired frames per state; save fx-on frames; return shares."""
    shares = {}
    for name, thinking, fast, moving in H.STATES:
        acc = {"gold_spec": 0, "purple_spec": 0, "white_core": 0}
        sdir = os.path.join(out, name)
        os.makedirs(sdir, exist_ok=True)
        for i in range(12):
            ot = (i / 11) * 11.0
            now = H.warm_state(fxc, scene, ot, thinking, fast, moving)
            items = H.items_at_screen(scene, ot)
            on = H.render_frame(scene, fxc, back, items, now, hat_on=True)
            if save:
                on.save(os.path.join(sdir, "%s_%02d.png" % (name, i)))
            off = H.render_frame(scene, fxc, back, items, now, hat_on=False)
            m = np.abs(np.asarray(on.convert("RGB"), np.int16)
                       - np.asarray(off.convert("RGB"), np.int16)).max(axis=2) > DIFF_T
            px = np.asarray(on.convert("RGB"), np.float64)[m]
            h, s, v = rgb_to_hsv(px)
            fam = families(h, s, v)
            for k in acc:
                acc[k] += int(fam[k].sum())
        tri = max(1, acc["gold_spec"] + acc["purple_spec"] + acc["white_core"])
        shares[name] = {"gold_spec": acc["gold_spec"],
                        "purple_spec": acc["purple_spec"],
                        "white_core": acc["white_core"],
                        "gold_share_of_triplet_strict_pct":
                            round(100 * acc["gold_spec"] / tri, 2)}
        print(f"{name:<22} strict-gold share {shares[name]['gold_share_of_triplet_strict_pct']:5.2f}%")
    return shares


def timing(scene, fxc, back):
    out = {}
    for name, thinking, fast, moving in H.STATES:
        now = H.warm_state(fxc, scene, 11.0, thinking, fast, moving)
        items = H.items_at_screen(scene, 11.0)
        for _ in range(3):
            H.render_frame(scene, fxc, back, items, now, hat_on=True)
        t_on, t_off = [], []
        for _ in range(30):
            t0 = time.perf_counter()
            H.render_frame(scene, fxc, back, items, now, hat_on=True)
            t_on.append((time.perf_counter() - t0) * 1000.0)
            t0 = time.perf_counter()
            H.render_frame(scene, fxc, back, items, now, hat_on=False)
            t_off.append((time.perf_counter() - t0) * 1000.0)
        out[name] = {"fx_on_median_ms": round(statistics.median(t_on), 3),
                     "fx_off_median_ms": round(statistics.median(t_off), 3),
                     "delta_ms": round(statistics.median(t_on)
                                       - statistics.median(t_off), 3)}
        print(f"{name:<22} dt {out[name]['delta_ms']:+.2f}ms")
    return out


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "share"
    scene = H.Scene()
    fxc = H.fx.FX(H.FX_SCALE, H.SS, defer=True, assets_dir=str(H.ASSETS))
    back = Image.new("RGBA", scene.bg.size, (0, 0, 0, 0))
    if cmd == "share":
        out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
            "outputs", "fx2", "_diag_probe")
        os.makedirs(out, exist_ok=True)
        shares = frames_dir(out, scene, fxc, back)
        tim = timing(scene, fxc, back)
        doc = {"tool": "_plan_fx2_gold_share.py share",
               "note": "girl-opaque before/after diff: run `diff` against the "
                       "saved fx-on frames of two builds",
               "strict_gold_share": shares, "timing": tim}
        with open(os.path.join(out, "gold_share.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        print("wrote", os.path.join(out, "gold_share.json"))
    elif cmd == "diff":
        da, db = sys.argv[2], sys.argv[3]
        # saved frames are 1x composites: bring the girl alpha mask to 1x
        gw, gh = scene.girl.size
        gx, gy = scene.girl_pos
        g1x = round(gw / 2.0)
        h1x = round(gh / 2.0)
        mask = np.asarray(scene.girl.getchannel("A").resize(
            (g1x, h1x), Image.NEAREST), np.uint8) == 255
        ox, oy = gx // 2, gy // 2
        total = 0
        for name, *_ in H.STATES:
            n = 0
            for i in range(12):
                a = np.asarray(Image.open(os.path.join(
                    da, name, "%s_%02d.png" % (name, i))).convert("RGB"), np.int16)
                b = np.asarray(Image.open(os.path.join(
                    db, name, "%s_%02d.png" % (name, i))).convert("RGB"), np.int16)
                n += int((np.abs(a - b).max(axis=2) > 0)[oy:oy + h1x, ox:ox + g1x][mask].sum())
            total += n
            print(f"{name:<22} girl_opaque_diff {n}")
        print("girl_opaque_diff_total:", total)
    else:
        raise SystemExit("unknown subcommand: %s" % cmd)


if __name__ == "__main__":
    main()
