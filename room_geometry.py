"""Low-cost 3D room study: one camera, projected geometry, no live data.

Composite background, floor_shadow, furniture, character, foreground, plaque.
The seat's world origin always projects to (145, 350). Existing character art
must remain proportionate; this module neither cuts nor repairs that artwork.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

BASE_SIZE = (400, 500)
_SS = 3
_FOCAL, _DISTANCE, _PITCH, _SEAT_Y = 590.0, 18.0, 0.20, 2.45
_TABLE_Y = _SEAT_Y + 0.12
_ORIGIN = (145.0, 350.0)
_DESK = ((3.1, -3.65), (5.6, -4.30), (7.2, 1.85), (4.7, 2.50))
_FLOOR = ((-3.6, -0.7), (-1.8, -4.20), (5.7, -4.20),
          (7.3, -0.7), (7.3, 4.2), (-3.6, 4.2))
_LAYER_NAMES = ("background", "furniture", "floor_shadow", "foreground", "plaque")


def _view(view):
    if len(view) != 2 or not all(math.isfinite(v) for v in view):
        raise ValueError("view must contain two finite coordinates")
    return tuple(max(-1.0, min(1.0, float(v))) for v in view)


class _Camera:
    def __init__(self, view=(0.0, 0.0)):
        vx, vy = _view(view)
        yaw, pitch = 0.035 * vx, _PITCH + 0.014 * vy
        self.sy, self.cy = math.sin(yaw), math.cos(yaw)
        self.sp, self.cp = math.sin(pitch), math.cos(pitch)
        self.position = (-_DISTANCE * self.sy * self.cp,
                         _SEAT_Y + _DISTANCE * self.sp,
                         -_DISTANCE * self.cy * self.cp)

    def camera_point(self, point):
        x, y, z = point
        y -= _SEAT_Y
        horizontal = x * self.cy - z * self.sy
        forward = x * self.sy + z * self.cy
        vertical = y * self.cp + forward * self.sp
        depth = _DISTANCE + forward * self.cp - y * self.sp
        return horizontal, vertical, depth

    def project(self, point):
        x, y, depth = self.camera_point(point)
        if depth <= 0.1:
            raise ValueError("Geometry is behind the camera")
        return (_ORIGIN[0] + _FOCAL * x / depth,
                _ORIGIN[1] - _FOCAL * y / depth)


def _unproject(x, y, depth=0.0):
    """Reconstruct a neutral-camera world point on world z=depth."""
    v = (_ORIGIN[1] - y) / _FOCAL
    sp, cp = math.sin(_PITCH), math.cos(_PITCH)
    relative_y = (v * (_DISTANCE + depth * cp) - depth * sp) / (cp + v * sp)
    distance = _DISTANCE + depth * cp - relative_y * sp
    world_x = (x - _ORIGIN[0]) * distance / _FOCAL
    return world_x, relative_y + _SEAT_Y, depth


def project_anchor(x, y, view=(0.0, 0.0), depth=0.0):
    """Project a neutral-view pixel anchor on a world-depth plane.

    Returns logical 400x500 coordinates, before output scaling. World depth is
    measured in the same units as the room, positive toward the rear wall.
    For existing desk props use anchor_offsets() to share their tabletop plane.
    """
    if not all(math.isfinite(v) for v in (x, y, depth)):
        raise ValueError("Anchor coordinates and depth must be finite")
    return _Camera(view).project(_unproject(x, y, depth))


def _table_anchor(x, y):
    v = (_ORIGIN[1] - y) / _FOCAL
    sp, cp = math.sin(_PITCH), math.cos(_PITCH)
    t = _TABLE_Y - _SEAT_Y
    depth = (t * cp - v * _DISTANCE + v * t * sp) / (v * cp - sp)
    return _unproject(x, y, depth)


def anchor_offsets(view=(0.0, 0.0)):
    """Logical-pixel translations for trace/chat/quota/back and their hit boxes.

    Desk anchors are support points on the SAME y-plane as its 3D tabletop.
    Translation preserves existing prop pixels; this study adds no new AI art.
    """
    anchors = {"trace": (307.5, 341.5), "chat": (355.0, 374.0),
               "quota": (362.0, 341.0), "back": (350.0, 70.0)}
    camera = _Camera(view)
    offsets = {}
    for key, (x, y) in anchors.items():
        point = _unproject(x, y, 4.2) if key == "back" else _table_anchor(x, y)
        sx, sy = camera.project(point)
        offsets[key] = (sx - x, sy - y)
    return offsets


class _Paint:
    def __init__(self, camera):
        self.camera = camera
        self.im = Image.new("RGBA", (BASE_SIZE[0] * _SS, BASE_SIZE[1] * _SS))
        self.d = ImageDraw.Draw(self.im)

    def pixels(self, vertices):
        return [(round(x * _SS), round(y * _SS))
                for x, y in (self.camera.project(p) for p in vertices)]

    def polygon(self, vertices, color, outline=None, width=0.75):
        pts = self.pixels(vertices)
        self.d.polygon(pts, fill=color)
        if outline:
            self.d.line(pts + [pts[0]], fill=outline, width=max(1, round(width * _SS)),
                        joint="curve")

    def line(self, vertices, color, width=0.8):
        self.d.line(self.pixels(vertices), fill=color,
                    width=max(1, round(width * _SS)), joint="curve")

    def finish(self, scale):
        size = tuple(round(v * scale) for v in BASE_SIZE)
        return self.im.convert("RGBa").resize(size, Image.Resampling.LANCZOS).convert("RGBA")


def _normal(vertices):
    a, b, c = vertices[:3]
    u, v = tuple(b[i] - a[i] for i in range(3)), tuple(c[i] - a[i] for i in range(3))
    n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2],
         u[0] * v[1] - u[1] * v[0])
    length = math.sqrt(sum(k * k for k in n)) or 1.0
    return tuple(k / length for k in n)


def _slab(faces, footprint, low, high, color, edge=None):
    """A horizontal prism, including a true top and its vertical edge thickness."""
    bottom = [(x, low, z) for x, z in footprint]
    top = [(x, high, z) for x, z in footprint]
    faces.append((list(reversed(top)), color, edge))
    faces.append((bottom, color, edge))
    for i in range(len(top)):
        j = (i + 1) % len(top)
        faces.append(([bottom[j], bottom[i], top[i], top[j]], color, edge))


def _box(faces, x0, y0, z0, x1, y1, z1, color, edge=None):
    _slab(faces, ((x0, z0), (x1, z0), (x1, z1), (x0, z1)), y0, y1, color, edge)


def _faces(p, faces):
    # One camera and world-space normals for every material, not screen-space skew.
    light = (-0.44, 0.79, -0.43)
    for vertices, base, edge in sorted(faces, key=lambda f: sum(
            p.camera.camera_point(v)[2] for v in f[0]) / len(f[0]), reverse=True):
        n = _normal(vertices)
        center = tuple(sum(v[i] for v in vertices) / len(vertices) for i in range(3))
        direction = tuple(p.camera.position[i] - center[i] for i in range(3))
        if sum(n[i] * direction[i] for i in range(3)) <= 0:
            continue
        gain = 0.68 + 0.32 * max(0.0, sum(n[i] * light[i] for i in range(3)))
        color = tuple(round(c * gain) for c in base[:3]) + (base[3] if len(base) > 3 else 255,)
        p.polygon(vertices, color, edge)


def _ellipse3d(cx, cy, cz, rx, rz, count=48):
    return [(cx + rx * math.cos(i * math.tau / count), cy,
             cz + rz * math.sin(i * math.tau / count)) for i in range(count)]


def _arch(x0, x1, bottom, shoulder, top, z):
    cx, rx = (x0 + x1) / 2, (x1 - x0) / 2
    vertices = [(x0, bottom, z), (x1, bottom, z), (x1, shoulder, z)]
    vertices.extend((cx + rx * math.cos(t), shoulder + (top - shoulder) * math.sin(t), z)
                    for t in [i * math.pi / 28 for i in range(1, 29)])
    return vertices


def _background(p):
    # Open-front corner with a tapered cutaway side wall, not a floating UI card.
    p.polygon([(-3.6, 0, 4.2), (7.3, 0, 4.2), (7.3, 12.5, 4.2), (-3.6, 12.5, 4.2)],
              (62, 47, 83, 255), (122, 88, 118, 255))
    p.polygon([(7.3, 0, 1.3), (7.3, 0, 4.2), (7.3, 12.5, 4.2), (7.3, 9.0, 1.3)],
              (43, 32, 57, 255), (95, 67, 84, 255))
    p.line([(-3.45, 12.15, 4.19), (7.2, 12.15, 4.19)], (172, 120, 113, 255), 1)
    # Material relief: low wall rail projects in front of the plaster.
    rail = []
    _box(rail, -3.6, 0.2, 4.0, 7.3, 0.34, 4.18, (130, 79, 75), (158, 102, 87, 255))
    _faces(p, rail)
    base = []
    _slab(base, _FLOOR, -0.06, 0.0, (137, 88, 72), (71, 44, 49, 255))
    _faces(p, base)
    # All plank seams are parallel in world space and share the camera's vanishing point.
    for x in (-1.5, -0.15, 1.2, 2.55, 3.9, 5.25):
        p.line([(x, 0.009, -4.15), (x, 0.009, 4.13)], (82, 51, 49, 255), 0.75)
    for x, z in ((-0.9, -2.5), (1.4, -1.2), (3.0, -3.8), (5.6, 0.7)):
        p.line([(x, 0.015, z), (x + 0.28, 0.015, z + 0.03),
                (x + 0.45, 0.015, z - 0.015)], (165, 113, 88, 255), 0.5)
    # Recessed arch and glass; the sill is a separate solid with visible thickness.
    outer = _arch(3.15, 6.7, 4.25, 9.3, 11.15, 4.04)
    inner = _arch(3.32, 6.53, 4.43, 9.27, 10.98, 4.11)
    p.polygon(outer, (166, 117, 97, 255), (211, 160, 121, 255), 1)
    p.polygon(inner, (133, 109, 153, 255), (54, 36, 64, 255), 1)
    # Gentle vertical glass tint through actual world-space strips, clipped to its mask.
    glass = _Paint(p.camera)
    for i in range(35):
        y0, y1 = 4.43 + i * 6.55 / 35, 4.43 + (i + 1) * 6.55 / 35
        t = i / 34
        col = tuple(round(a + (b - a) * t) for a, b in zip((185, 139, 145), (99, 83, 136)))
        glass.polygon([(3.32, y0, 4.11), (6.53, y0, 4.11),
                       (6.53, y1, 4.11), (3.32, y1, 4.11)], col + (255,))
    mask = Image.new("L", p.im.size)
    ImageDraw.Draw(mask).polygon(p.pixels(inner), fill=255)
    glass.im.putalpha(mask)
    p.im.alpha_composite(glass.im)
    p.line([(4.925, 4.46, 4.0), (4.925, 10.95, 4.0)], (113, 75, 88, 255), 2)
    p.line([(3.34, 7.05, 4.0), (6.50, 7.05, 4.0)], (113, 75, 88, 255), 2)
    sill = []
    _box(sill, 2.98, 4.05, 3.35, 6.84, 4.25, 4.22,
         (160, 103, 85), (199, 145, 108, 255))
    _faces(p, sill)
    # Small cut crescent stays on the glass plane and does not cast glow over her.
    crescent = []
    for i in range(40):
        a = math.pi / 2 + i * math.pi / 39
        crescent.append((5.75 + 0.38 * math.cos(a), 9.45 + 0.50 * math.sin(a), 4.08))
    for i in range(40):
        a = 3 * math.pi / 2 - i * math.pi / 39
        crescent.append((5.94 + 0.38 * math.cos(a), 9.45 + 0.50 * math.sin(a), 4.08))
    p.polygon(crescent, (238, 207, 165, 255))


def _furniture(p, front):
    faces, foreground = [], []
    gold = (187, 130, 87, 255)
    # Backboard is a thick arch. Source cushion supplies the upholstery at the seat.
    back = _arch(-2.9, 2.9, 2.6, 5.5, 6.3, 1.55)
    rear = [(x, y, z + 0.18) for x, y, z in back]
    p.polygon(rear, (56, 33, 66, 255), (82, 51, 75, 255))
    p.polygon(back, (91, 52, 110, 255), gold, 2.1)
    p.line(_arch(-2.70, 2.70, 2.72, 5.46, 6.05, 1.50), (134, 79, 136, 255), 0.85)
    _box(faces, -3.13, 2.05, -0.5, 3.13, 2.48, 1.58, (92, 53, 92), gold)
    _box(faces, -3.19, 2.30, -0.53, 3.19, 2.43, 1.62, (173, 119, 82), gold)
    # Four independent chair legs: rear feet sit farther up the projected floor.
    for x in (-2.68, 2.68):
        for z in (-0.26, 1.32):
            _box(faces, x - 0.13, 0, z - 0.12, x + 0.13, 2.20, z + 0.12,
                 (113, 63, 70), (148, 89, 73, 255))
    for x in (-3.08, 3.08):
        _box(faces, x - 0.12, 2.35, -0.12, x + 0.12, 3.15, 0.12,
             (140, 84, 90), gold)
        _box(faces, x - 0.16, 3.04, -0.30, x + 0.16, 3.19, 1.38,
             (109, 64, 111), gold)
    # A genuinely rotated rectangular tabletop with thickness and four solid legs.
    _slab(faces, _DESK, _TABLE_Y - 0.20, _TABLE_Y,
          (167, 108, 87), (198, 148, 106, 255))
    desk_cx = sum(x for x, _ in _DESK) / 4
    desk_cz = sum(z for _, z in _DESK) / 4
    for x, z in _DESK:
        x, z = x + (desk_cx - x) * 0.09, z + (desk_cz - z) * 0.07
        _box(faces, x - 0.11, 0, z - 0.11, x + 0.11, _TABLE_Y - 0.18, z + 0.11,
             (117, 70, 71), (165, 105, 83, 255))
    _faces(p, faces)
    # Sparse tabletop grain follows its projected local axis, not screen diagonals.
    a, b, _, d = _DESK
    for t in (0.22, 0.54, 0.78):
        x, z = a[0] + (d[0] - a[0]) * t, a[1] + (d[1] - a[1]) * t
        p.line([(x + 0.30, _TABLE_Y + 0.006, z),
                (x + 0.65, _TABLE_Y + 0.006, z - 0.06)], (196, 135, 104, 255), 0.5)
    # Front rim is visible at the outer ends; her calves remain in front of it.
    # The full structural rail is already behind the character in furniture.
    for x0, x1 in ((-3.12, -0.30), (2.75, 3.12)):
        _box(foreground, x0, 2.03, -0.55, x1, 2.14, -0.46,
             (95, 51, 80), (178, 118, 86, 255))
    _faces(front, foreground)


def _shadows(p):
    p.polygon(_ellipse3d(0, 0.018, 0.45, 2.92, 1.45), (25, 16, 31, 46))
    p.polygon([(x - 0.18, 0.017, z - 0.23) for x, z in _DESK], (24, 16, 28, 38))
    for x in (-2.68, 2.68):
        for z in (-0.26, 1.32):
            p.polygon(_ellipse3d(x, 0.023, z, 0.30, 0.24), (25, 15, 27, 92))
    cx, cz = sum(x for x, _ in _DESK) / 4, sum(z for _, z in _DESK) / 4
    for x, z in _DESK:
        x, z = x + (cx - x) * 0.09, z + (cz - z) * 0.07
        p.polygon(_ellipse3d(x, 0.024, z, 0.25, 0.23), (27, 16, 29, 92))
    # Cast shadows stop at the actual floor, rather than floating past its cutaway edge.
    mask = Image.new("L", p.im.size)
    ImageDraw.Draw(mask).polygon(p.pixels([(x, 0, z) for x, z in _FLOOR]), fill=255)
    p.im.putalpha(ImageChops.multiply(p.im.getchannel("A"), mask))


def _plaque(p):
    # Match the existing return anchor, projected on the rear wall's plane.
    cx, cy, z = _unproject(350, 70, 4.2)
    board = [(cx - 0.60, cy - 0.48, z - 0.11), (cx + 0.60, cy - 0.48, z - 0.11),
             (cx + 0.60, cy + 0.48, z - 0.11), (cx - 0.60, cy + 0.48, z - 0.11)]
    p.line([(cx, cy + 0.78, z - 0.06), (cx, cy + 0.48, z - 0.06)],
           (193, 143, 103, 255), 1)
    p.polygon(board, (68, 43, 78, 255), (202, 153, 109, 255), 1)
    outer = []
    for i in range(32):
        a = math.pi / 2 + i * math.pi / 31
        outer.append((cx + 0.36 * math.cos(a), cy + 0.36 * math.sin(a), z - 0.12))
    for i in range(32):
        a = 3 * math.pi / 2 - i * math.pi / 31
        outer.append((cx + 0.16 + 0.36 * math.cos(a), cy + 0.36 * math.sin(a), z - 0.12))
    p.polygon(outer, (230, 191, 127, 255))


def render_room_layers(view=(0.0, 0.0), scale=1.0):
    """Return five same-size RGBA layers; scale changes the entire geometry once."""
    if not math.isfinite(scale) or not 0.5 <= scale <= 2.0:
        raise ValueError("scale must be finite and between 0.5 and 2.0")
    camera = _Camera(view)
    painters = {key: _Paint(camera) for key in _LAYER_NAMES}
    _background(painters["background"])
    _shadows(painters["floor_shadow"])
    _furniture(painters["furniture"], painters["foreground"])
    _plaque(painters["plaque"])
    return {key: painter.finish(scale) for key, painter in painters.items()}


def render_room_stage(view=(0.0, 0.0)):
    """Return (behind, foreground) at 400x500 for the interactive renderer.

    Geometry retains 3x antialiasing. Background, shadows and furniture are
    alpha-composited in that domain before ONE premultiplied downsample. The
    foreground has its own single downsample. No unused return plaque is drawn.
    """
    camera = _Camera(view)
    behind, shadow, furniture, front = (_Paint(camera) for _ in range(4))
    _background(behind)
    _shadows(shadow)
    _furniture(furniture, front)
    # A semi-transparent shadow layer must blend with the floor, not replace it.
    behind.im.alpha_composite(shadow.im)
    behind.im.alpha_composite(furniture.im)
    return behind.finish(1.0), front.finish(1.0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, default=Path(__file__).parent / "assets")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with Image.open(args.assets / "main.png") as src:
        char_src = src.convert("RGBA")
    factor = min(286 / char_src.width, 375 / char_src.height)
    char_size = tuple(round(v * factor * _SS) for v in char_src.size)
    char_src = char_src.resize(char_size, Image.Resampling.LANCZOS)
    char_canvas = Image.new("RGBA", (400 * _SS, 500 * _SS))
    char_canvas.alpha_composite(char_src, (round((17 + (286 - char_size[0] / _SS) / 2) * _SS),
                                           round((52 + (375 - char_size[1] / _SS) / 2) * _SS)))
    char = char_canvas.convert("RGBa").resize(BASE_SIZE, Image.Resampling.LANCZOS).convert("RGBA")
    for view, filename in (((0, 0), "geometry-neutral.png"),
                           ((-1, -0.5), "geometry-left.png"),
                           ((1, 0.5), "geometry-right.png")):
        layers = render_room_layers(view)
        im = Image.new("RGBA", BASE_SIZE)
        for key in ("background", "floor_shadow", "furniture"):
            im.alpha_composite(layers[key])
        im.alpha_composite(char)
        for key in ("foreground", "plaque"):
            im.alpha_composite(layers[key])
        im.save(args.out / filename)
        if view == (0, 0):
            im.convert("RGBa").resize((304, 380), Image.Resampling.LANCZOS).convert("RGBA").save(
                args.out / "geometry-neutral-0.76.png")
    print("Room geometry previews:", args.out)


if __name__ == "__main__":
    main()
