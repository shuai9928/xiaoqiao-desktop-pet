"""Continuous portrait depth mesh. No cut layers, hidden artwork or AI calls."""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw


def clamp(value, lo=-1.0, hi=1.0):
    return max(lo, min(hi, value))


def smooth(lo, hi, value):
    t = clamp((value - lo) / (hi - lo), 0.0, 1.0)
    return t * t * (3 - 2 * t)


class RoomPortrait:
    """A shared mesh preserves seams, keeps the seat fixed and the face rigid."""

    BOX = (17, 52, 303, 427)
    FACE = (.22, .29, .63, .515)

    def __init__(self, assets_dir):
        with Image.open(Path(assets_dir) / "main.png") as opened:
            original = opened.convert("RGBA")
        x0, y0, x1, y1 = self.BOX
        factor = min((x1 - x0) / original.width, (y1 - y0) / original.height)
        self.size = (round(original.width * factor * 2), round(original.height * factor * 2))
        self.origin = (round(x0 + (x1 - x0 - self.size[0] / 2) / 2),
                       round(y0 + (y1 - y0 - self.size[1] / 2) / 2))
        self.source = original.convert("RGBa").resize(self.size, Image.Resampling.LANCZOS)
        self.w, self.h = self.size
        self.xs = [round(self.w * i / 24) for i in range(25)]
        self.ys = [round(self.h * i / 32) for i in range(33)]
        self._lights = {}
        # A restrained directional material field gives volume without a glow.
        # Face illumination varies as one constant patch, never per-feature.
        self._light_field = Image.new("L", (48, 64))
        values = []
        for j in range(64):
            y = j / 63
            for i in range(48):
                x = i / 47
                if self.in_face(x, y):
                    gain = .015
                else:
                    shape = math.exp(-(((x - .45) / .38) ** 2 + ((y - .48) / .62) ** 2))
                    gain = clamp((x - .40) * .05 + .024 * shape, -.025, .035)
                values.append(round(128 + gain * 128 / .04))
        self._light_field.putdata(values)

    @classmethod
    def in_face(cls, x, y):
        x0, y0, x1, y1 = cls.FACE
        return x0 <= x <= x1 and y0 <= y <= y1

    def displacement(self, x, y, view, lag=(0.0, 0.0), breath=0.0):
        """Return displacement in final display pixels, not supersampled pixels."""
        vx, vy = (clamp(v) for v in view)
        lx, ly = (clamp(v) for v in lag)
        # All face vertices share a translation. No yaw shear or breath on eyes.
        if self.in_face(x, y):
            return 4.0 * vx, 1.8 * vy
        seat_gate = 1.0 - smooth(.56, .69, y)
        if seat_gate == 0.0:
            return 0.0, 0.0
        face_distance = max(self.FACE[0] - x, x - self.FACE[2],
                            self.FACE[1] - y, y - self.FACE[3], 0.0)
        face_blend = 1.0 - smooth(0.0, .06, face_distance)
        # Hat cone, hair edge and chest have different apparent depths.
        depth = .38 + .28 * math.exp(-((y - .58) / .12) ** 2)
        depth += .18 * math.exp(-((x - .43) / .28) ** 2)
        dx = vx * 4.0 * depth * seat_gate
        dy = vy * 1.8 * depth * seat_gate
        hat = (1 - smooth(.22, .31, y)) * smooth(.15, .35, x)
        hair_edge = math.exp(-((y - .39) / .17) ** 2) * (1 - face_blend)
        dx += (lx - vx) * (1.3 * hat + .8 * hair_edge)
        dy += (ly - vy) * .6 * hat
        # Local chest breathing tapers out above the waist, leaving the seat fixed.
        chest = math.exp(-(((x - .40) / .27) ** 2 + ((y - .58) / .07) ** 2))
        dx += breath * (x - .40) * 2.6 * chest * seat_gate
        dy -= breath * .65 * chest * seat_gate
        return (dx * (1 - face_blend) + 4 * vx * face_blend,
                dy * (1 - face_blend) + 1.8 * vy * face_blend)

    def _lit_source(self, view):
        level = round(clamp(view[0]) * 4)
        if level in self._lights:
            return self._lights[level]
        rgba = self.source.convert("RGBA")
        alpha = rgba.getchannel("A")
        rgb = rgba.convert("RGB")
        low = rgb.point([round(v * .96) for v in range(256)] * 3).convert("RGBA")
        high = rgb.point([min(255, round(v * 1.04)) for v in range(256)] * 3).convert("RGBA")
        low.putalpha(alpha)
        high.putalpha(alpha)
        field = self._light_field.point(lambda v: clamp(round(v + level * 2), 0, 255))
        field = field.resize(self.size, Image.Resampling.BILINEAR)
        lit = Image.composite(high, low, field).convert("RGBa")
        self._lights[level] = lit
        return lit

    def render(self, view=(0.0, 0.0), lag=(0.0, 0.0), breath=0.0):
        """Return a scene-size layer; cushion geometry never changes with motion."""
        mesh = []
        for j in range(32):
            for i in range(24):
                quad = []
                for a, b in ((i, j), (i, j + 1), (i + 1, j + 1), (i + 1, j)):
                    sx, sy = self.xs[a], self.ys[b]
                    dx, dy = self.displacement(sx / self.w, sy / self.h, view, lag, breath)
                    quad.extend((sx - dx * 2, sy - dy * 2))
                mesh.append(((self.xs[i], self.ys[j], self.xs[i + 1], self.ys[j + 1]), tuple(quad)))
        result = self._lit_source(view).transform(self.size, Image.Transform.MESH,
                                                mesh, Image.Resampling.BILINEAR)
        result = result.resize((round(self.w / 2), round(self.h / 2)), Image.Resampling.LANCZOS).convert("RGBA")
        layer = Image.new("RGBA", (400, 500))
        layer.alpha_composite(result, self.origin)
        return layer

    def contact_shadow(self):
        """Visible localized contact under the cushion, not a silhouette glow."""
        shadow = Image.new("RGBA", (400, 500))
        d = ImageDraw.Draw(shadow)
        d.ellipse((51, 350, 235, 368), fill=(28, 18, 37, 70))
        d.ellipse((62, 354, 231, 363), fill=(25, 16, 31, 95))
        return shadow
