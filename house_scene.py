"""Compact Live2.5D room: layout and depth-layered rendering.

The room art is built by tools/build_house_room.py from witch-house-v1.png:
a front frame layer (roof, beam, drape swags, curtains, pillars, platform)
and a room interior layer with a box-room depth map.  The swing renderer owns
every character/contact coordinate; this module only says where the room sits
around the already-scaled swing, and renders the two room layers for a camera
offset.  The swing is the still reference plane: the frame moves against the
camera, the back wall with it, floor/walls/ceiling shear in between, and the
frame really occludes the swing's crossbar and the room behind it.

It does not read settings, sessions, chat, or make any model requests.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import json
import math
from pathlib import Path
import time

from PIL import Image

Rect = tuple[int, int, int, int]  # x, y, width, height
ASSET_DIR = Path(__file__).parent / "assets" / "house"
PAD = 8                           # canvas margin for the frame's parallax


def load_meta(asset_dir=None):
    path = Path(asset_dir or ASSET_DIR) / "room-v2.json"
    return json.loads(path.read_text(encoding="utf-8"))


_META = None


def meta():
    global _META
    if _META is None:
        _META = load_meta()
    return _META


@dataclass(frozen=True)
class HouseLayout:
    size: tuple[int, int]         # canvas size (room + parallax margin + swing extras)
    O: tuple[float, float]        # canvas origin in swing "art px x k" coordinates
    scale: float                  # canvas px per room px
    room_origin: tuple[int, int]  # canvas position of the room image's (0, 0)
    room_size: tuple[int, int]    # scaled room image size
    left_origin: tuple[float, float]   # translation applied to the plain swing canvas
    left_bounds: Rect             # the stage (room opening) on the canvas
    plaque: Rect                  # nameplate on the platform front, camera at rest
    floor_y: float                # floor line under the swing plane, canvas y


def layout(k, swing_box, room=None):
    """Place the room around a swing drawn with scale ``k`` (canvas px per
    scene-art px).  ``swing_box`` = (x0, y0, x1, y1): the plain swing canvas in
    the same "art px x k" coordinates (its x0, y0 is that canvas' O).  The room
    is uniformly scaled so the swing hangs where the art expects it; the canvas
    is the room (plus parallax margin) united with the swing canvas, so speech
    bubbles above her head are never clipped."""
    room = room or meta()
    if not (math.isfinite(k) and 0.05 <= k <= 4.0):
        raise ValueError("k must be a finite swing scale")
    x0, y0, x1, y1 = swing_box
    if not all(math.isfinite(v) for v in swing_box) or x1 <= x0 or y1 <= y0:
        raise ValueError("swing_box must be a finite, non-empty rectangle")
    sw_ = room["swing"]
    ks = sw_["ks"]
    S = k / ks
    rw, rh = room["size"]
    # room pixel (u, v) -> art*k space: ((u - rx0) * S, (v - ry0) * S)
    rx0 = sw_["cx"] - sw_["scene_bar_cx"] * ks
    ry0 = sw_["top"] - sw_["scene_bar_top"] * ks
    left, top = -rx0 * S - PAD, -ry0 * S - PAD
    right, bottom = (rw - rx0) * S + PAD, (rh - ry0) * S + PAD
    ox, oy = math.floor(min(left, x0)), math.floor(min(top, y0))
    width = math.ceil(max(right, x1) - ox)
    height = math.ceil(max(bottom, y1) - oy)
    room_origin = (round(-rx0 * S - ox), round(-ry0 * S - oy))
    room_size = (max(1, round(rw * S)), max(1, round(rh * S)))
    g = room["room"]
    fx = g["side_front_x"]
    stage = (room_origin[0] + round(fx * S), room_origin[1] + round(g["ceil_front_y"] * S),
             round((rw - 2 * fx) * S),
             round((g["floor_front_y"] - g["ceil_front_y"]) * S))
    px0, py0, px1, py1 = room["plaque"]
    plaque = (room_origin[0] + round(px0 * S), room_origin[1] + round(py0 * S),
              round((px1 - px0) * S), round((py1 - py0) * S))
    return HouseLayout((width, height), (ox, oy), S, room_origin, room_size,
                       (x0 - ox, y0 - oy), stage, plaque,
                       room_origin[1] + sw_["floor_y"] * S)


def _view(view):
    if len(view) != 2 or not all(math.isfinite(v) for v in view):
        raise ValueError("view must contain two finite coordinates")
    return tuple(max(-1.0, min(1.0, float(v))) for v in view)


def depth_shift(depth, view, room=None):
    """Room-pixel displacement of a point at ``depth`` (0 front .. 1 back wall)
    for a camera offset ``view`` in [-1, 1]^2.  Zero at the swing's plane."""
    room = room or meta()
    vx, vy = _view(view)
    pf, pb = room["parallax"]["front"], room["parallax"]["back"]
    s = -pf + (pf + pb) * depth
    return vx * s, vy * s * .5


def _solid(im):
    """Resampling brings back alpha 1..7 specks; they are invisible but would
    catch clicks on a layered window, so clear them after every resample."""
    im.putalpha(im.getchannel("A").point(lambda v: 0 if v < 8 else v))
    return im


class HouseRenderer:
    """PIL-only renderer with bounded caches.

    ``render(layout, view)`` returns (behind, front, front_offset): the room
    interior warped for the camera (canvas-sized), the front frame (room-sized)
    and where to paste it.  Callers composite behind, then the swing, then the
    frame; the returned images are cached and must not be modified.
    """

    def __init__(self, asset_dir=None, cache_limit=8):
        d = Path(asset_dir or ASSET_DIR)
        self.meta = load_meta(d)
        with Image.open(d / "room-v2-bg.png") as im:
            self.bg = im.convert("RGBA")
        with Image.open(d / "room-v2-fg.png") as im:
            self.fg = im.convert("RGBA")
        with Image.open(d / "room-v2-depth.png") as im:
            self.depth = im.convert("L")
        if self.bg.size != tuple(self.meta["size"]) or self.fg.size != self.bg.size:
            raise ValueError("room layers do not match their geometry")
        self.cache_limit = max(1, min(16, int(cache_limit)))
        # A cache miss re-warps the whole interior (about 20 ms at the default
        # size, ~60 ms at the largest zoom).  The host may cap how often that
        # happens while the camera glides; the last frame is reused meanwhile.
        self.min_interval = 0.0
        self._last_warp = -1e9
        self._last_hit = None
        self.last_view = (0.0, 0.0)
        self._scaled = OrderedDict()
        self._frames = OrderedDict()

    @classmethod
    def load(cls, asset_dir=None):
        try:
            return cls(asset_dir)
        except (OSError, ValueError, KeyError):
            return None

    def _layers(self, size):
        hit = self._scaled.get(size)
        if hit is None:
            bg = self.bg.convert("RGBa").resize(size, Image.Resampling.LANCZOS)
            fg = _solid(self.fg.convert("RGBa").resize(size, Image.Resampling.LANCZOS).convert("RGBA"))
            depth = self.depth.resize(size, Image.Resampling.BILINEAR)
            hit = self._scaled[size] = (bg, fg, depth.load())
            while len(self._scaled) > 2:
                self._scaled.popitem(last=False)
        self._scaled.move_to_end(size)
        return hit

    def _mesh(self, size, depth, view, scale):
        w, h = size
        nx, ny = 28, 34
        xs = [round(w * i / nx) for i in range(nx + 1)]
        ys = [round(h * j / ny) for j in range(ny + 1)]
        pts = {}
        for y in ys:
            for x in xs:
                d = depth[min(w - 1, x), min(h - 1, y)] / 255.0
                dx, dy = depth_shift(d, view, self.meta)
                pts[x, y] = (x - dx * scale, y - dy * scale)
        mesh = []
        for x0, x1 in zip(xs, xs[1:]):
            for y0, y1 in zip(ys, ys[1:]):
                q = (pts[x0, y0], pts[x0, y1], pts[x1, y1], pts[x1, y0])
                mesh.append(((x0, y0, x1, y1), tuple(v for p in q for v in p)))
        return mesh

    def front_offset(self, house_layout, view):
        dx, dy = depth_shift(0.0, _view(view), self.meta)
        S = house_layout.scale
        return (house_layout.room_origin[0] + round(dx * S),
                house_layout.room_origin[1] + round(dy * S))

    def render(self, house_layout, view=(0.0, 0.0)):
        view = _view(view)
        # slow camera moves stay smooth, without keeping every sampled view
        view = tuple(round(v * 16) / 16 for v in view)
        L = house_layout
        geometry = (L.size, L.room_size, L.room_origin)
        key = geometry + (view,)
        hit = self._frames.get(key)
        now = time.monotonic()
        last = self._last_hit
        if (hit is None and last is not None and last[0][:3] == geometry
                and now - self._last_warp < self.min_interval):
            key, hit = last                       # gliding camera: keep the last view a moment
            view = key[3]
        if hit is None:
            if any(k[:3] != geometry for k in self._frames):
                self._frames.clear()              # zoom changed: old sizes are dead weight
            bg, fg, depth = self._layers(L.room_size)
            if view != (0.0, 0.0):
                bg = bg.transform(L.room_size, Image.Transform.MESH,
                                  self._mesh(L.room_size, depth, view, L.scale),
                                  Image.Resampling.BILINEAR)
            behind = Image.new("RGBA", L.size, (0, 0, 0, 0))
            behind.alpha_composite(_solid(bg.convert("RGBA")), L.room_origin)
            hit = self._frames[key] = (behind, fg)
            self._last_warp = now
            while len(self._frames) > self.cache_limit:
                self._frames.popitem(last=False)
        self._frames.move_to_end(key)
        self._last_hit = (key, hit)
        self.last_view = view                     # the view these layers were drawn for
        behind, fg = hit
        return behind, fg, self.front_offset(L, view)
