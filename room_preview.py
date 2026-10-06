"""Offline room composition study; no Tk, settings, or session data is read.

The current main.png is intentionally reused without repainting or warping.
Its cushion belongs to the chair in this study; its raised rope-gripping hand
still needs an authored room pose. This module does not claim final room art.
"""

from __future__ import annotations

import argparse
import json
import math
from functools import lru_cache
from collections import OrderedDict
from pathlib import Path

from PIL import Image, ImageDraw

from room_portrait import RoomPortrait

BASE_SIZE = (400, 500)
ENTRANCE_LABELS = {
    "trace": "工作轨迹",
    "chat": "对话记录",
    "quota": "额度与状态",
    "back": "返回秋千",
}
ASSET_LIMITATIONS = (
    "空间样稿：连续深度网格复用 main.png，脸部刚性、坐垫固定；未切分原画。",
    "左手仍是握绳姿态，袖口/指缝保留已有去绳修补痕迹；需独立室内手势素材。",
    "需补自然扶椅/托书的左手与袖口，并核对帽檐原素材的裁切边；本稿不涂光或遮挡修补。",
    "桌椅和窗采用三维几何投影；人物为2.5D原画而非完整3D模型；尚未接入真实AI数据。",
)
_RECTS = {
    "trace": (280, 319, 325, 363),
    "chat": (334, 357, 378, 390),
    "quota": (341, 293, 382, 349),
    "back": (326, 47, 374, 93),
}


class _Painter:
    """Draw at 3x for clean edges at actual desktop dimensions."""

    def __init__(self):
        self.s = 3
        self.im = Image.new("RGBA", (BASE_SIZE[0] * self.s,
                                      BASE_SIZE[1] * self.s))
        self.d = ImageDraw.Draw(self.im)

    def box(self, box):
        return tuple(round(v * self.s) for v in box)

    def points(self, points):
        return [(round(x * self.s), round(y * self.s)) for x, y in points]

    def polygon(self, points, fill, outline=None):
        self.d.polygon(self.points(points), fill=fill)
        if outline:
            self.line(list(points) + [points[0]], outline, 1)

    def line(self, points, fill, width=1):
        self.d.line(self.points(points), fill=fill,
                    width=max(1, round(width * self.s)), joint="curve")

    def ellipse(self, box, fill=None, outline=None, width=1):
        self.d.ellipse(self.box(box), fill=fill, outline=outline,
                       width=max(1, round(width * self.s)))

    def rounded(self, box, radius, fill=None, outline=None, width=1):
        self.d.rounded_rectangle(self.box(box), radius=round(radius * self.s),
                                 fill=fill, outline=outline,
                                 width=max(1, round(width * self.s)))

    def shade(self, points, upper, lower, radius=None):
        """Material gradient clipped to a polygon or rounded rectangle."""
        mask = Image.new("L", self.im.size)
        md = ImageDraw.Draw(mask)
        if radius is None:
            md.polygon(self.points(points), fill=255)
            ys = [p[1] for p in points]
        else:
            md.rounded_rectangle(self.box(points), radius=round(radius * self.s),
                                 fill=255)
            ys = [points[1], points[3]]
        top, bottom = round(min(ys) * self.s), round(max(ys) * self.s)
        layer = Image.new("RGBA", self.im.size)
        ld = ImageDraw.Draw(layer)
        for y in range(max(0, top), min(layer.height, bottom + 1)):
            t = (y - top) / max(1, bottom - top)
            c = tuple(round(a + (b - a) * t) for a, b in zip(upper, lower))
            ld.line((0, y, layer.width, y), fill=c + (255,))
        layer.putalpha(mask)
        self.im.alpha_composite(layer)

    def crescent(self, box, color, shift=0.32):
        mask = Image.new("L", self.im.size)
        md = ImageDraw.Draw(mask)
        md.ellipse(self.box(box), fill=255)
        x0, y0, x1, y1 = box
        md.ellipse(self.box((x0 + (x1 - x0) * shift, y0 - 2,
                            x1 + (x1 - x0) * shift, y1 - 2)), fill=0)
        layer = Image.new("RGBA", self.im.size, color)
        layer.putalpha(mask)
        self.im.alpha_composite(layer)

    def sprite(self, path, box, *, crop=False):
        with Image.open(path) as source:
            src = source.convert("RGBA")
        if crop:
            bounds = src.getchannel("A").getbbox()
            if bounds:
                src = src.crop(bounds)
        x0, y0, x1, y1 = box
        factor = min((x1 - x0) / src.width, (y1 - y0) / src.height)
        size = (max(1, round(src.width * factor * self.s)),
                max(1, round(src.height * factor * self.s)))
        src = src.resize(size, Image.Resampling.LANCZOS)
        x = round((x0 + (x1 - x0 - size[0] / self.s) / 2) * self.s)
        y = round((y0 + (y1 - y0 - size[1] / self.s) / 2) * self.s)
        self.im.alpha_composite(src, (x, y))


def _room_shell(p):
    wall = [(23, 93), (55, 41), (282, 28), (374, 79),
            (375, 416), (259, 447), (23, 416)]
    p.shade(wall, (60, 48, 87), (37, 28, 55))
    p.line(wall + [wall[0]], (115, 88, 125, 255), 1.1)
    # The narrow side wall gives a room corner without a large empty box.
    p.shade([(288, 31), (374, 79), (375, 416), (288, 437)],
            (67, 49, 80), (46, 30, 54))
    p.line([(288, 34), (288, 414)], (98, 72, 96, 255), 1)
    p.line([(33, 97), (57, 52), (279, 41)], (158, 116, 121, 255), 1)
    # Warm lavender light remains inside the window, not over the character.
    p.rounded((250, 94, 367, 289), 53, fill=(35, 27, 53, 255),
              outline=(163, 119, 112, 255), width=5)
    p.shade((256, 102, 361, 282), (85, 73, 133), (201, 149, 151), radius=46)
    p.line([(309, 106), (309, 281)], (111, 79, 92, 255), 3)
    p.line([(259, 192), (358, 192)], (116, 82, 95, 255), 3)
    p.crescent((323, 125, 346, 149), (239, 211, 165, 255))
    for x, y, r in ((318, 114, 1.1), (351, 163, 0.8), (334, 176, 0.8)):
        p.ellipse((x - r, y - r, x + r, y + r), (242, 214, 192, 255))
    # Upholstered curtains and a shaped wooden sill, kept behind the silhouette.
    p.shade([(243, 101), (257, 93), (261, 177), (253, 274), (242, 270)],
            (95, 60, 115), (53, 37, 76))
    p.line([(251, 111), (255, 178), (247, 269)], (126, 86, 143, 255), 1.2)
    p.polygon([(245, 281), (367, 281), (374, 292), (243, 295)],
              (130, 84, 77, 255), (174, 122, 97, 255))
    p.line([(249, 286), (365, 286)], (213, 151, 113, 255), 1)
    # Small plank floor with perspective; grain is sparse and deterministic.
    floor = [(17, 413), (222, 375), (381, 409), (379, 449),
             (163, 483), (17, 445)]
    p.shade(floor, (106, 66, 68), (137, 88, 74))
    p.line(floor + [floor[0]], (69, 43, 51, 255), 2)
    for a, b in (((51, 406), (85, 460)), ((95, 398), (140, 478)),
                 ((145, 389), (215, 475)), ((204, 379), (289, 462)),
                 ((259, 384), (354, 452))):
        p.line([a, b], (72, 46, 53, 255), 1)
    for n in range(8):
        x = 45 + n * 37
        y = 424 + math.sin(n * 1.9) * 9
        p.line([(x, y), (x + 9, y - 1), (x + 16, y + 1)],
               (164, 107, 88, 255), 0.6)


def _chair(p):
    # An upholstered frame under the existing cushion; no new seat covers it.
    p.shade((46, 235, 240, 371), (114, 67, 132), (62, 38, 86), radius=33)
    p.rounded((46, 235, 240, 371), 33, outline=(169, 119, 93, 255), width=3)
    p.rounded((55, 245, 231, 363), 27, outline=(137, 92, 132, 255), width=1)
    # Lower frame and curved wood legs visibly carry the source cushion.
    p.shade([(42, 354), (240, 354), (247, 371), (235, 386),
             (53, 386), (39, 373)], (110, 66, 105), (57, 32, 59))
    p.line([(45, 370), (145, 378), (241, 370)], (188, 138, 94, 255), 2)
    for pts in ([(57, 377), (52, 397), (58, 419), (48, 432)],
                [(224, 377), (237, 401), (237, 420), (250, 432)]):
        p.line(pts, (82, 48, 64, 255), 8)
        p.line([(x - 1, y) for x, y in pts], (165, 111, 89, 255), 1.5)
    p.ellipse((34, 427, 71, 436), (73, 44, 62, 255))
    p.ellipse((228, 427, 262, 436), (73, 44, 62, 255))


def _desk_and_props(p, assets):
    # Narrow side desk, placed away from the face, hands and main body contour.
    p.shade([(277, 353), (376, 353), (369, 391), (286, 390)],
            (100, 62, 77), (68, 43, 63))
    p.line([(286, 388), (291, 427), (284, 441)], (80, 47, 60, 255), 6)
    p.line([(368, 386), (363, 426), (370, 437)], (80, 47, 60, 255), 6)
    p.line([(291, 394), (294, 427)], (170, 114, 84, 255), 1)
    p.line([(365, 394), (360, 426)], (170, 114, 84, 255), 1)
    p.shade([(271, 327), (364, 318), (384, 343), (373, 394),
             (280, 381)], (165, 105, 92), (108, 65, 72))
    p.line([(272, 328), (363, 320), (383, 343), (373, 393), (280, 381)],
           (201, 152, 111, 255), 1.3)
    for y in (340, 360, 378):
        p.line([(282, y), (306, y - 2)], (185, 123, 98, 255), 0.6)
    # Reuse the two existing matching prop assets, only crop transparent margins.
    p.sprite(assets / "scene" / "book.png", (281, 320, 334, 363), crop=True)
    p.ellipse((346, 336, 378, 345), (77, 46, 70, 255))
    p.sprite(assets / "scene" / "crystal.png", (343, 293, 381, 347), crop=True)
    # Folded letter with restrained linework and a purple wax seal.
    p.polygon([(329, 360), (366, 362), (369, 385), (331, 383)],
              (238, 213, 174, 255), (172, 121, 103, 255))
    p.polygon([(329, 360), (347, 375), (366, 362)],
              (249, 226, 185, 255), (189, 147, 121, 255))
    p.ellipse((342, 369, 354, 381), (123, 65, 117, 255),
              (199, 151, 104, 255), 0.7)
    p.crescent((345, 372, 351, 378), (232, 192, 133, 255))


def _return_plaque(p):
    p.line([(350, 42), (350, 54)], (182, 133, 108, 255), 1.3)
    p.rounded((330, 53, 370, 88), 12, fill=(61, 41, 78, 255),
              outline=(190, 142, 104, 255), width=1.1)
    p.crescent((341, 59, 362, 82), (227, 184, 121, 255))
    p.ellipse((334, 68, 337, 71), (166, 133, 205, 255))


def _render_flat_baseline(assets_dir, scale=1.0):
    """Return (RGBA image, entrance rectangles) in final pixel coordinates.

    Rectangles use x/y/width/height with the far edge exclusive. At 0.76 they
    remain at least 32px in either dimension, without overlapping each other.
    This only renders a study; consumers decide what opening an entrance does.
    """
    if not math.isfinite(scale) or not 0.5 <= scale <= 2.0:
        raise ValueError("Room preview scale must be finite and between 0.5 and 2.0")
    assets = Path(assets_dir)
    p = _Painter()
    _room_shell(p)
    _chair(p)
    # Full source canvas is preserved: no pose extraction, alpha edits or repair.
    # 375px visible height / 500px canvas = 75% character-first composition.
    p.sprite(assets / "main.png", (17, 52, 303, 427))
    _desk_and_props(p, assets)
    _return_plaque(p)
    size = tuple(round(v * scale) for v in BASE_SIZE)
    # Premultiplied downsampling avoids dark halos at transparent silhouette edges.
    image = p.im.convert("RGBa").resize(size, Image.Resampling.LANCZOS).convert("RGBA")
    rects = {}
    for key, box in _RECTS.items():
        x0, y0, x1, y1 = (v * scale for v in box)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        w, h = max(32, x1 - x0), max(32, y1 - y0)
        left, top = round(cx - w / 2), round(cy - h / 2)
        rects[key] = (left, top, round(cx + w / 2) - left,
                      round(cy + h / 2) - top)
    return image, rects


class RoomSceneRenderer:
    """A small geometry stage with an anchored, continuously warped portrait."""

    def __init__(self, assets_dir):
        self.assets = Path(assets_dir)
        self.portrait = RoomPortrait(self.assets)
        self._geometry_cache = OrderedDict()
        self._props = {}
        for key, filename, box in (
            ("trace", "book.png", (281, 320, 334, 363)),
            ("quota", "crystal.png", (343, 293, 381, 347)),
        ):
            painter = _Painter()
            painter.sprite(self.assets / "scene" / filename, box, crop=True)
            self._props[key] = painter.im.convert("RGBa").resize(BASE_SIZE, Image.Resampling.LANCZOS).convert("RGBA")
        painter = _Painter()
        painter.polygon([(335, 360), (372, 362), (375, 385), (337, 383)],
                        (238, 213, 174, 255), (172, 121, 103, 255))
        painter.polygon([(335, 360), (353, 375), (372, 362)],
                        (249, 226, 185, 255), (189, 147, 121, 255))
        painter.ellipse((348, 369, 360, 381), (123, 65, 117, 255))
        painter.crescent((351, 372, 357, 378), (232, 192, 133, 255))
        self._props["chat"] = painter.im.convert("RGBa").resize(BASE_SIZE, Image.Resampling.LANCZOS).convert("RGBA")
        painter = _Painter()
        _return_plaque(painter)
        self._props["back"] = painter.im.convert("RGBa").resize(BASE_SIZE, Image.Resampling.LANCZOS).convert("RGBA")

    def render(self, scale=1.0, view=(0.0, 0.0), lag=None, breath=0.0):
        from room_geometry import render_room_stage, anchor_offsets
        if not math.isfinite(scale) or not .5 <= scale <= 2:
            raise ValueError("Room scale must be finite and between .5 and 2")
        if any(not math.isfinite(v) for v in (*view, breath)):
            raise ValueError("Room pose must be finite")
        # Same geometry remains valid while only the character breathes.
        # Quantization moves room edges less than one pixel; sampling quality stays.
        geometry_view = tuple(round(max(-1, min(1, v)) * 24) / 24 for v in view)
        if geometry_view not in self._geometry_cache:
            self._geometry_cache[geometry_view] = render_room_stage(geometry_view)
            while len(self._geometry_cache) > 8:
                self._geometry_cache.popitem(last=False)
        back, front = self._geometry_cache[geometry_view]
        self._geometry_cache.move_to_end(geometry_view)
        frame = back.copy()
        frame.alpha_composite(self.portrait.contact_shadow())
        frame.alpha_composite(self.portrait.render(view, lag or view, breath))
        frame.alpha_composite(front)
        # The plaque itself follows the back-wall anchor along with its hit box.
        offsets = anchor_offsets(geometry_view)
        rects = {}
        for key, prop in self._props.items():
            dx, dy = offsets[key]
            shifted = prop.convert("RGBa").transform(BASE_SIZE, Image.Transform.AFFINE,
                (1, 0, -dx, 0, 1, -dy), Image.Resampling.BILINEAR).convert("RGBA")
            frame.alpha_composite(shifted)
            x0, y0, x1, y1 = _RECTS[key]
            cx, cy = (x0 + x1) / 2 + dx, (y0 + y1) / 2 + dy
            w, h = max(32, (x1 - x0) * scale), max(32, (y1 - y0) * scale)
            left, top = round(cx * scale - w / 2), round(cy * scale - h / 2)
            rects[key] = (left, top, round(cx * scale + w / 2) - left,
                          round(cy * scale + h / 2) - top)
        frame = frame.convert("RGBa").resize(tuple(round(v * scale) for v in BASE_SIZE),
                                             Image.Resampling.LANCZOS).convert("RGBA")
        return frame, rects


@lru_cache(maxsize=2)
def _renderer(assets_dir):
    return RoomSceneRenderer(assets_dir)


def render_room_preview(assets_dir, scale=1.0, *, view=(0.0, 0.0), lag=None, breath=0.0):
    """Render geometry + portrait, returning entrance rectangles for this frame."""
    return _renderer(str(Path(assets_dir).resolve())).render(scale, view, lag, breath)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, default=Path(__file__).parent / "assets")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    metadata = {"kind": "visual-study", "base_size": BASE_SIZE,
                "labels": ENTRANCE_LABELS, "material_limits": ASSET_LIMITATIONS,
                "previews": {}}
    for scale, name in ((1.0, "room-normal.png"), (0.76, "room-0.76.png")):
        im, rects = render_room_preview(args.assets, scale)
        im.save(args.out / name)
        metadata["previews"][name] = {"scale": scale, "size": im.size,
                                      "entrances": rects}
    (args.out / "room-preview.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.out), "previews": metadata["previews"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
