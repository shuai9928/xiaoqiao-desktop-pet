# -*- coding: utf-8 -*-
"""fx2 harness: hat FX (A1 orbit dust trail + A2 thinking smoke) render/measurement rig.

Reusable baseline tool for the next FX engineer. Three subcommands:

  py tools/fx2_harness.py offline  [--out DIR] [--frames N]
      Deterministic offline renders of the "swing scene frame" per state
      (thinking on/off, orbit phase swept over a full revolution, quality
      full/reduced). No live window, no pet process, no saved-state access.

  py tools/fx2_harness.py measure  [--out DIR]
      Renders offline (same code path, PNGs included) and writes
      baseline.json: per-state composite time (median of 30), particle
      counts, fx pixel coverage vs the girl bbox, fx palette top-8 and
      fx-vs-background luminance contrast. The "after" pass must reuse
      this exact command so numbers stay comparable.

  py tools/fx2_harness.py live     [--out DIR] [--idle 8] [--thinking 10]
      Real-desktop captures of the running pet window (title
      "小乔 · 时之魔女", class TkTopLevel) via EnumWindows + GetWindowRect +
      ImageGrab. Optionally triggers the thinking demo through pet_cmd.json
      {"op":"demo","hat_fx":{...}} (requires the pet to run with
      --debug-state; the harness only writes pet_cmd.json, never starts or
      kills the pet).

What it does NOT do: it never modifies fx.py / pet.py / settings, never
touches pet_state writing, never terminates processes.

Coordinate conventions (mirrors production, pet.py):
  - FX sprites live in the SS-supersampled frame (SS = 2), like pet.py render().
  - Orbit geometry constants are copied verbatim from pet.py (HAT_ORBIT*,
    lines ~189-200); keep in sync when pet.py changes.
  - Production draw order replicated per frame:
      back layer  <- hat.draw() (A1 dust + A2 smoke) + far-side orbit items
      girl sprite <- composited over the back layer
      front       <- near-side orbit items
      downscale   <- frame.resize((W, H), BILINEAR), same as pet.py:11119
"""
from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import fx  # noqa: E402  (project root)
from hat_fx import tip_anchor  # noqa: E402

# ---- production constants, copied from pet.py (do not edit here; sync both) ----
SS = 2                       # pet.py:134 supersample factor
FX_SCALE = 0.8               # pet_settings.json "scale": FX(scale, SS, assets_dir)
ASSETS = ROOT / "assets"
GIRL_SRC = ASSETS / "scene" / "girl.png"

# pet.py:189-200 — hat orbit geometry, art-canvas pixels
HAT_ORBIT_ART = (730.0, 750.0)
HAT_ORBIT = (400.0, 190.0, 380.0, 92.0, 27.0)   # cx, cy, semi-major, semi-minor, tilt(deg)
HAT_ORBIT_BODIES = (("moon", 0.84, 11.0, 0.4),
                    ("crystal", 0.92, 15.0, 4.6),
                    ("planet", 1.0, 20.0, 2.6))
HAT_ORBIT_TRAIL = 6
HAT_ORBIT_PATH = 32
HAT_ORBIT_TRAIL_GAP = 0.085

# Offline swing-scene frame: matches the live window's aspect (~455x326 logical).
W_LOGICAL, H_LOGICAL = 455, 326
GIRL_FRAC = 0.86             # girl height as fraction of frame height (SS px)
GIRL_BOTTOM_MARGIN = 18      # SS px above the bottom edge

T0 = 1000.0                  # deterministic epoch for simulated clock (seconds)
WARMUP_STEPS_FAST = 10       # hat_fx.TRAIL_SAMPLES; sub-steps that build a trail
WARMUP_STEPS_REDUCED = 6     # hat draw keep=6 when quality is reduced
TIMING_SAMPLES = 30
DIFF_THRESHOLD = 8           # max-channel delta vs no-fx render that counts as fx pixel

# fx-on / fx-off scene states. moving=False isolates A2 (no new trail samples).
STATES = (
    # (name,            thinking, fast,   moving)
    ("a1_orbit_full",     False,  True,   True),
    ("a1_orbit_reduced",  False,  False,  True),
    ("a2_thinking_full",  True,   True,   True),
    ("a2_thinking_reduced", True, False,  True),
    ("a2_smoke_only_full", True,  True,   False),
)


# --------------------------------------------------------------------------- #
# Scene construction
# --------------------------------------------------------------------------- #
class Scene:
    """Static parts of the offline swing frame (bg + girl), built once."""

    def __init__(self):
        self.w = W_LOGICAL * SS
        self.h = H_LOGICAL * SS
        self.bg = self._build_bg()
        girl = Image.open(GIRL_SRC).convert("RGBA")
        target_h = round(self.h * GIRL_FRAC)
        f = target_h / girl.height
        self.girl = girl.resize((max(1, round(girl.width * f)), target_h),
                                Image.Resampling.LANCZOS)
        self.girl_pos = ((self.w - self.girl.width) // 2,
                         self.h - target_h - GIRL_BOTTOM_MARGIN)
        bb = self.girl.getchannel("A").getbbox()          # alpha bbox in girl-local px
        gx, gy = self.girl_pos
        self.girl_bbox = (gx + bb[0], gy + bb[1], gx + bb[2], gy + bb[3])
        self.girl_bbox_area = (bb[2] - bb[0]) * (bb[3] - bb[1])
        # Metrics are taken on the 1x output frame (what gets displayed and
        # saved), so the coverage denominator is the bbox at 1x.
        f1 = 1.0 / SS
        self.girl_bbox_1x = tuple(round(v * f1) for v in self.girl_bbox)
        self.girl_bbox_area_1x = ((self.girl_bbox_1x[2] - self.girl_bbox_1x[0])
                                  * (self.girl_bbox_1x[3] - self.girl_bbox_1x[1]))
        # Hat apex via the same one-shot function production uses at scale
        # rebuild (hat_fx.tip_anchor). Production anchors it on assets/main.png
        # and maps it through the swing scene geo; here it is anchored on the
        # pasted girl directly, which lands on the same hat apex.
        uvx, uvy = tip_anchor(self.girl)
        self.tip = (gx + uvx * self.girl.width, gy + uvy * self.girl.height)

    @staticmethod
    def _build_bg() -> Image.Image:
        """Simple deterministic night-sky stand-in for the swing scene."""
        w, h = W_LOGICAL * SS, H_LOGICAL * SS
        im = Image.new("RGB", (1, h))
        top, bottom = (16, 18, 40), (44, 34, 78)
        im.putdata([tuple(round(a + (b - a) * y / (h - 1)) for a, b in zip(top, bottom))
                    for y in range(h)])
        im = im.resize((w, h))
        d = ImageDraw.Draw(im, "RGBA")
        for i in range(40):                      # fixed pseudo-random starfield
            a = (i * 2654435761) % 1000 / 1000
            x = (i * 48271) % w
            y = (i * 104729) % (h * 2 // 3)
            d.ellipse([x, y, x + 2, y + 2], fill=(220, 226, 255, int(60 + 140 * a)))
        d.ellipse([w - 150, 40, w - 90, 100], fill=(240, 238, 210, 235))   # moon
        return im.convert("RGBA")


def hat_orbit_layout(orbit_t):
    """Replica of pet.py Pet._hat_orbit_layout (normalized art coords).

    Returns [(name|None|'path', nx, ny, depth 0..1, near(bool), level)]."""
    cx, cy, a, b, tilt = HAT_ORBIT
    aw, ah = HAT_ORBIT_ART
    ct, st = math.cos(math.radians(tilt)), math.sin(math.radians(tilt))
    out = []
    for i in range(HAT_ORBIT_PATH):
        ang = 2 * math.pi * i / HAT_ORBIT_PATH
        lx, ly = a * math.cos(ang), b * math.sin(ang)
        sn = math.sin(ang)
        out.append(("path", (cx + lx * ct - ly * st) / aw,
                    (cy + lx * st + ly * ct) / ah, (sn + 1) / 2, sn > 0, 0.0))
    for name, k, period, phase in HAT_ORBIT_BODIES:
        ang0 = phase + orbit_t * 2 * math.pi / period
        for j in range(HAT_ORBIT_TRAIL + 1):
            ang = ang0 - j * HAT_ORBIT_TRAIL_GAP
            lx, ly = a * k * math.cos(ang), b * k * math.sin(ang)
            x, y = cx + lx * ct - ly * st, cy + lx * st + ly * ct
            sn = math.sin(ang)
            out.append((name if j == 0 else None, x / aw, y / ah, (sn + 1) / 2,
                        sn > 0, 1.0 - j / (HAT_ORBIT_TRAIL + 1)))
    return out


def items_at_screen(scene, orbit_t):
    """Map layout (normalized) onto the SS frame, like _hat_orbit_screen."""
    gx, gy = scene.girl_pos
    w, h = scene.girl.width, scene.girl.height
    out = []
    for name, nx, ny, depth, near, level in hat_orbit_layout(orbit_t):
        out.append((name, gx + nx * w, gy + ny * h, depth, near, level))
    return out


# --------------------------------------------------------------------------- #
# Frame rendering (mirrors pet.py render() hat-fx path)
# --------------------------------------------------------------------------- #
def _draw_orbit_side(frame, fxc, items, near_side, hat_on):
    """Replica of pet.py Pet._draw_hat_orbit for one side.

    hat_on=True: name-None dots are REPLACED by the A1 trail (pet.py:11434-11441).
    hat_on=False keeps only bodies + path dots so the paired no-fx render
    cancels everything except A1/A2."""
    dots = fxc.orbit_dots
    nd = fxc.ORBIT_DOT_STEPS
    paste = frame.paste
    for name, X, Y, depth, near, level in items:
        if near != near_side:
            continue
        if name is None:
            if hat_on:
                continue
            lv = level * (0.45 + 0.55 * depth)
            i = int(lv * nd) - 1
            if i < 0:
                continue
            sp = dots[min(i, nd - 1)]
            paste(sp, (int(X - sp.width / 2), int(Y - sp.height / 2)), sp)
        elif name == "path":
            lv = 0.28 + 0.22 * depth
            i = int(lv * nd) - 1
            if i < 0:
                continue
            sp = dots[min(i, nd - 1)]
            paste(sp, (int(X - sp.width / 2), int(Y - sp.height / 2)), sp)
        else:
            fxc.orbit_body(frame, X, Y, name, depth)


def render_frame(scene, fxc, back, items, now, hat_on):
    """One full composite. hat.draw() reads state only -> safe to repeat."""
    frame = scene.bg.copy()
    back.paste((0, 0, 0, 0), (0, 0, back.width, back.height))
    if hat_on and getattr(fxc, "hat", None) is not None:
        fxc.hat.draw(back)                     # A1 dust trail + A2 smoke
    _draw_orbit_side(back, fxc, items, False, hat_on)   # far side behind girl
    frame.alpha_composite(back)
    frame.alpha_composite(scene.girl, scene.girl_pos)
    _draw_orbit_side(frame, fxc, items, True, hat_on)   # near side in front
    return frame.resize((W_LOGICAL, H_LOGICAL), Image.BILINEAR)


def simulate_step(fxc, now, items, tip, thinking, fast, moving):
    """Production gateway: pet.py gain_star(hat_fx=True) -> layer.update/set_thinking."""
    hat = fxc.hat
    if hat is None:
        return
    hat.update(now, items, tip[0], tip[1], fast=fast, moving=moving)
    hat.set_thinking(now, thinking, tip[0], tip[1])


def warm_state(fxc, scene, target_orbit_t, thinking, fast, moving):
    """Rebuild a production-realistic trail ending exactly at target_orbit_t.

    Real orbit_t advances 1 unit per second (HAT_ORBIT_BODIES periods), so the
    sub-step dt below yields production-like trail arc spacing. Each rendered
    frame starts from a cleared layer -> frames are independent and the phase
    sweep can jump freely without tripping the trail teleport-reset.

    Returns the layer clock `now` the warmed state is valid at (the layer's
    own self.now); render_frame must be called with the same value or the
    trail ages shift and reduced-quality trails would fall out of their
    0.82 s window."""
    hat = fxc.hat
    if hat is None:
        return None
    hat.clear()
    steps = WARMUP_STEPS_FAST if fast else WARMUP_STEPS_REDUCED
    dt = 0.075 if fast else 0.125              # hat_fx.update sampling interval
    now = 0.0
    for j in range(steps):
        ot = target_orbit_t - (steps - 1 - j) * dt
        now = T0 + j * dt
        items = items_at_screen(scene, ot)
        simulate_step(fxc, now, items, scene.tip, thinking, fast, moving)
    return now


# --------------------------------------------------------------------------- #
# Subcommand: offline
# --------------------------------------------------------------------------- #
def cmd_offline(out_dir: Path, frames: int) -> dict:
    scene = Scene()
    fxc = fx.FX(FX_SCALE, SS, defer=True, assets_dir=str(ASSETS))
    if getattr(fxc, "hat", None) is None:
        raise SystemExit("hat_fx sprites failed to bake (assets/hat_fx_v1 missing?)")
    back = Image.new("RGBA", scene.bg.size, (0, 0, 0, 0))
    out_dir.mkdir(parents=True, exist_ok=True)

    # one no-fx reference frame (full-orbit layout, no A1/A2)
    items = items_at_screen(scene, 2.0)
    ref = render_frame(scene, fxc, back, items, T0, hat_on=False)
    ref_path = out_dir / "reference_nofx.png"
    ref.save(ref_path)

    saved = {"reference_nofx.png": str(ref_path.resolve().relative_to(ROOT))}
    t0 = time.perf_counter()
    for name, thinking, fast, moving in STATES:
        sdir = out_dir / name
        sdir.mkdir(exist_ok=True)
        steps = WARMUP_STEPS_FAST if fast else WARMUP_STEPS_REDUCED
        dt = 0.075 if fast else 0.125
        for i in range(frames):
            ot = (i / max(1, frames - 1)) * 11.0   # sweep one full moon revolution
            now = warm_state(fxc, scene, ot, thinking, fast, moving)
            items = items_at_screen(scene, ot)
            im = render_frame(scene, fxc, back, items, now, hat_on=True)
            rel = f"{name}/{name}_{i:02d}.png"
            im.save(out_dir / rel)
            saved[rel] = str((out_dir / rel).resolve().relative_to(ROOT))
    render_s = time.perf_counter() - t0
    print(f"offline: {frames * len(STATES)} frames + 1 reference -> {out_dir} "
          f"({render_s:.1f}s)")
    return {"saved": saved, "scene": scene_meta(scene)}


def scene_meta(scene: Scene) -> dict:
    return {
        "frame_ss": [scene.w, scene.h],
        "frame_logical": [W_LOGICAL, H_LOGICAL],
        "ss": SS,
        "fx_scale": FX_SCALE,
        "hat_layer_scale": FX_SCALE * SS,
        "girl_src": str(GIRL_SRC.resolve().relative_to(ROOT)),
        "girl_paste_pos_ss": list(scene.girl_pos),
        "girl_bbox_ss": list(scene.girl_bbox),
        "girl_bbox_area_px": scene.girl_bbox_area,
        "girl_bbox_1x": list(scene.girl_bbox_1x),
        "girl_bbox_area_1x_px": scene.girl_bbox_area_1x,
        "hat_tip_ss": [round(v, 1) for v in scene.tip],
        "orbit_center_norm": [HAT_ORBIT[0] / HAT_ORBIT_ART[0],
                              HAT_ORBIT[1] / HAT_ORBIT_ART[1]],
    }


# --------------------------------------------------------------------------- #
# Subcommand: measure
# --------------------------------------------------------------------------- #
def _luma(px):
    return 0.2126 * px[0] + 0.7152 * px[1] + 0.0722 * px[2]


def _fx_mask(on: Image.Image, off: Image.Image):
    """fx pixels = max-channel delta vs the paired no-fx render (RGB channels)."""
    diff = ImageChops.difference(on, off)
    return [max(r, g, b) > DIFF_THRESHOLD
            for r, g, b, _a in diff.getdata()]


def _is_gold_glow(px) -> bool:
    r, g, b = px[:3]
    gold = r >= 110 and r >= g >= b and (r - b) >= 40          # 金色系
    glow = max(r, g, b) >= 205                                  # 发光系(高亮芯)
    return gold or glow


def measure_state(scene, fxc, back, name, thinking, fast, moving, frames, out_dir):
    """Render `frames` fx-on/fx-off pairs for one state, collect metrics."""
    sdir = out_dir / name
    sdir.mkdir(exist_ok=True)
    dt = 0.075 if fast else 0.125
    steps = WARMUP_STEPS_FAST if fast else WARMUP_STEPS_REDUCED
    per_frame = []
    palette_bins = {}
    bright_bins = {}
    fx_luma_sum = fx_luma_n = bg_luma_sum = 0
    fx_px_total = gold_glow_total = 0

    on_img = None
    for i in range(frames):
        ot = (i / max(1, frames - 1)) * 11.0
        now = warm_state(fxc, scene, ot, thinking, fast, moving)
        items = items_at_screen(scene, ot)
        on_img = render_frame(scene, fxc, back, items, now, hat_on=True)
        off_img = render_frame(scene, fxc, back, items, now, hat_on=False)
        stats = fxc.hat.stats() if getattr(fxc, "hat", None) is not None else {}
        mask = _fx_mask(on_img, off_img)
        on_px = on_img.convert("RGB").getdata()
        off_px = off_img.convert("RGB").getdata()
        n_fx = 0
        for j, hit in enumerate(mask):
            if not hit:
                continue
            n_fx += 1
            rgb = on_px[j]
            key = (rgb[0] >> 4, rgb[1] >> 4, rgb[2] >> 4)
            acc = palette_bins.setdefault(key, [0, 0, 0, 0])
            acc[0] += rgb[0]; acc[1] += rgb[1]; acc[2] += rgb[2]; acc[3] += 1
            if max(rgb) >= 160:                     # bright core of a sprite
                bacc = bright_bins.setdefault(key, [0, 0, 0, 0])
                bacc[0] += rgb[0]; bacc[1] += rgb[1]; bacc[2] += rgb[2]
                bacc[3] += 1
            if _is_gold_glow(rgb):
                gold_glow_total += 1
            fx_luma_sum += _luma(rgb)
            bg_luma_sum += _luma(off_px[j])
            fx_luma_n += 1
        fx_px_total += n_fx
        rel = f"{name}/{name}_{i:02d}.png"
        on_img.save(out_dir / rel)
        per_frame.append({
            "frame": i, "orbit_t": round(ot, 3), "png": rel,
            "hat_stats": stats,
            "fx_pixels": n_fx,
            "coverage_fx": round(n_fx / scene.girl_bbox_area_1x, 6),
        })

    # timing: freeze the fullest frame (last), repeat the composite only
    ot_full = 11.0
    now = warm_state(fxc, scene, ot_full, thinking, fast, moving)
    items = items_at_screen(scene, ot_full)
    for _ in range(3):
        render_frame(scene, fxc, back, items, now, hat_on=True)   # warmup
    samples = []
    for _ in range(TIMING_SAMPLES):
        t0 = time.perf_counter()
        render_frame(scene, fxc, back, items, now, hat_on=True)
        samples.append((time.perf_counter() - t0) * 1000.0)

    top8 = sorted(palette_bins.items(), key=lambda kv: -kv[1][3])[:8]
    palette = []
    for _key, acc in top8:
        n = acc[3]
        palette.append([round(acc[0] / n), round(acc[1] / n), round(acc[2] / n), n])
    top_bright = sorted(bright_bins.items(), key=lambda kv: -kv[1][3])[:8]
    palette_bright = []
    for _key, acc in top_bright:
        n = acc[3]
        palette_bright.append([round(acc[0] / n), round(acc[1] / n),
                               round(acc[2] / n), n])

    cov = [p["coverage_fx"] for p in per_frame]
    result = {
        "thinking": thinking, "quality": "full" if fast else "reduced",
        "moving": moving, "frames": frames, "substep_dt_s": dt,
        "composite_ms": {
            "median": round(statistics.median(samples), 3),
            "min": round(min(samples), 3),
            "max": round(max(samples), 3),
            "samples": TIMING_SAMPLES,
        },
        "particles_final": per_frame[-1]["hat_stats"],
        "particles_per_frame": [{"frame": p["frame"], "trail": p["hat_stats"].get("trail"),
                                 "smoke": p["hat_stats"].get("smoke"),
                                 "total": p["hat_stats"].get("total")}
                                for p in per_frame],
        "orbit_static_counts": {"bodies": len(HAT_ORBIT_BODIES),
                                "path_dots": HAT_ORBIT_PATH,
                                "body_trail_dots": len(HAT_ORBIT_BODIES) * HAT_ORBIT_TRAIL},
        "coverage_fx_ratio": {"mean": round(sum(cov) / len(cov), 6),
                              "min": round(min(cov), 6), "max": round(max(cov), 6)},
        "coverage_gold_glow_ratio_all_frames":
            round(gold_glow_total / (frames * scene.girl_bbox_area_1x), 6),
        "fx_pixels_total_all_frames": fx_px_total,
        "palette_top8_rgb_count": palette,
        "palette_top8_bright_core_rgb_count": palette_bright,
        "contrast_luma_delta": (round((fx_luma_sum - bg_luma_sum) / max(1, fx_luma_n), 2)
                                if fx_luma_n else None),
        "per_frame": per_frame,
    }
    return result


def cmd_measure(out_dir: Path, frames: int) -> None:
    t0 = time.perf_counter()
    rendered = cmd_offline(out_dir, frames)   # also saves the PNG deliverables
    scene = Scene()
    fxc = fx.FX(FX_SCALE, SS, defer=True, assets_dir=str(ASSETS))
    back = Image.new("RGBA", scene.bg.size, (0, 0, 0, 0))
    states = {}
    for name, thinking, fast, moving in STATES:
        states[name] = measure_state(scene, fxc, back, name, thinking, fast,
                                     moving, frames, out_dir)
        m = states[name]
        print(f"  {name:<22} median {m['composite_ms']['median']:7.2f} ms | "
              f"particles {json.dumps(m['particles_final'])} | "
              f"cov_fx {m['coverage_fx_ratio']['mean']:.4f} | "
              f"dL {m['contrast_luma_delta']}")
    doc = {
        "schema": "fx2-baseline/1",
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tool": "tools/fx2_harness.py measure",
        "what": ("A1/A2 hat FX baseline: paired fx-on/fx-off offline renders. "
                 "fx pixels = max-channel delta > %d vs the no-fx twin. "
                 "Coverage denominator = girl.png alpha bbox area. Reuse this "
                 "command unchanged for the 'after' pass." % DIFF_THRESHOLD),
        "scene": rendered["scene"],
        "notes": {
            "orbit_constants_source": "pet.py:189-200 (copied verbatim)",
            "tip_anchor": "hat_fx.tip_anchor(girl.png) applied to the pasted girl",
            "trail_rebuild": ("each frame warms the trail with %d/%d sub-steps of "
                              "0.075/0.125 s ending at the target phase"
                              % (WARMUP_STEPS_FAST, WARMUP_STEPS_REDUCED)),
            "quality_full_vs_reduced": ("fast flag feeds hat.update(fast=...) exactly "
                                        "like pet.py gain_star(hat_fx=True)"),
            "palette_note": ("palette counts composited on-screen pixels: faint alpha "
                             "tails dominate; bright_core = fx pixels with max(RGB)>=160. "
                             "Trail dust tops out at alpha index 4 (ALPHAS=.48) because "
                             "level max is (1)*(0.45+0.18*depth)<=0.63"),
            "composite_timing": ("bg.copy + hat.draw + orbit pastes + girl composite "
                                 "+ BILINEAR downscale, %d samples, median" % TIMING_SAMPLES),
        },
        "states": states,
        "png_files": rendered["saved"],
        "wall_time_s": round(time.perf_counter() - t0, 1),
    }
    path = out_dir / "baseline.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"measure: wrote {path} ({time.perf_counter() - t0:.1f}s total)")


# --------------------------------------------------------------------------- #
# Subcommand: live
# --------------------------------------------------------------------------- #
def find_pet_window(title="小乔 · 时之魔女"):
    """EnumWindows lookup of the running pet window. Returns (hwnd, rect)."""
    import ctypes.wintypes as wt
    user32 = ctypes.windll.user32
    EnumProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    exact, partial = [], []

    def cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            if cls.value == "TkTopLevel" or "小乔" in buf.value:
                rect = wt.RECT()
                if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    r = (rect.left, rect.top, rect.right, rect.bottom)
                    if buf.value == title:
                        exact.append((hwnd, r))
                    elif title in buf.value:
                        partial.append((hwnd, r))
        return True

    user32.EnumWindows(EnumProc(cb), 0)
    if exact:
        return exact[0]
    if partial:
        return partial[0]
    return None, None


def grab_window(rect) -> Image.Image:
    from PIL import ImageGrab
    return ImageGrab.grab(bbox=rect, all_screens=True)


def pet_state() -> dict:
    try:
        return json.loads((ROOT / "pet_state.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_pet_cmd(payload: dict) -> None:
    (ROOT / "pet_cmd.json").write_text(json.dumps(payload, ensure_ascii=False),
                                       encoding="utf-8")


def wait_hat_demo(flag: bool, timeout=6.0) -> bool:
    """Poll pet_state.json until hat_fx_demo matches `flag` (DEBUG_STATE only)."""
    end = time.time() + timeout
    while time.time() < end:
        if bool(pet_state().get("hat_fx_demo", False)) == flag:
            return True
        time.sleep(0.25)
    return False


def cmd_live(out_dir: Path, idle_n: int, think_n: int, demo_secs: float,
             interval: float) -> None:
    live_dir = out_dir / "live"
    live_dir.mkdir(parents=True, exist_ok=True)
    hwnd, rect = find_pet_window()
    if not hwnd:
        print("live: pet window '小乔 · 时之魔女' not found (is it running?)")
        sys.exit(2)
    ctypes.windll.user32.SetProcessDPIAware()   # GetWindowRect -> physical px
    hwnd, rect = find_pet_window()              # re-read rect as physical pixels
    log = {"title": "小乔 · 时之魔女", "hwnd": int(hwnd), "rect": list(rect),
           "dpi_aware": True, "interval_s": interval, "captures": []}

    def burst(tag, n):
        paths = []
        for i in range(n):
            p = live_dir / f"{tag}_{i:02d}.png"
            grab_window(rect).save(p)
            paths.append(str(p.resolve().relative_to(ROOT)))
            time.sleep(interval)
        log["captures"].append({"tag": tag, "n": n, "files": paths})
        print(f"live: {tag} x{n} -> {live_dir}")

    burst("idle", idle_n)

    demo_fired = False
    if think_n > 0:
        st = pet_state()
        if time.time() - st.get("time", 0) > 10:
            print("live: WARNING pet_state.json stale -> pet probably runs without "
                  "--debug-state; the hat_fx demo hook only exists in DEBUG_STATE")
        write_pet_cmd({"op": "demo", "secs": demo_secs,
                       "hat_fx": {"enabled": True, "thinking": True, "scale": 1.0}})
        demo_fired = wait_hat_demo(True, 6.0)
        if demo_fired:
            need = think_n * interval + 2.0
            if need > demo_secs:
                demo_secs = need + 2.0
                write_pet_cmd({"op": "demo", "secs": demo_secs,
                               "hat_fx": {"enabled": True, "thinking": True,
                                          "scale": 1.0}})
                wait_hat_demo(True, 6.0)
            burst("thinking_demo", think_n)
            restored = wait_hat_demo(False, demo_secs + 10)
            log["demo_auto_restored"] = restored
        else:
            print("live: demo hook did NOT fire (pet_state.hat_fx_demo stayed "
                  "false) -> only idle captured")
    log["demo_fired"] = demo_fired
    log["pet_cmd_note"] = ("pet_cmd.json now holds the last consumed demo "
                           "command; the pet restores its hat-fx state "
                           "automatically after `secs` (pet.py _configure_hat_fx_demo)")
    (live_dir / "live_log.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"live: wrote {live_dir / 'live_log.json'}; pet untouched "
          "(no start/kill, demo auto-restores)")


# --------------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for nm in ("offline", "measure"):
        p = sub.add_parser(nm)
        p.add_argument("--out", default=str(ROOT / "outputs" / "fx2" / "baseline"))
        p.add_argument("--frames", type=int, default=12,
                       help="frames per state (>=8)")
    p = sub.add_parser("live")
    p.add_argument("--out", default=str(ROOT / "outputs" / "fx2" / "baseline"))
    p.add_argument("--idle", type=int, default=8)
    p.add_argument("--thinking", type=int, default=10)
    p.add_argument("--demo-secs", type=float, default=25.0)
    p.add_argument("--interval", type=float, default=0.3)
    args = ap.parse_args(argv)
    out = Path(args.out)
    if args.cmd == "offline":
        if args.frames < 8:
            ap.error("--frames must be >= 8 for a usable baseline")
        cmd_offline(out, args.frames)
    elif args.cmd == "measure":
        if args.frames < 8:
            ap.error("--frames must be >= 8 for a usable baseline")
        cmd_measure(out, args.frames)
    else:
        cmd_live(out, args.idle, args.thinking, args.demo_secs, args.interval)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    main()
