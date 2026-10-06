"""A restrained floor projection of the EXISTING seated swing alpha.

No art is cut, painted, written, or read here.  The input remains untouched.
The projection starts beyond the hanging shoes; it is a cast shadow, never a
contact mark pretending that the seated character stands on the floor.
"""
from __future__ import annotations

from collections import OrderedDict
import math

from PIL import Image, ImageChops, ImageDraw, ImageFilter


def _view(view):
    if len(view) != 2 or not all(math.isfinite(v) for v in view):
        raise ValueError("view must contain two finite coordinates")
    return tuple(max(-1.0, min(1.0, float(v))) for v in view)


class HouseShadow:
    """Small local images; bounded cache, no mutable cached output.

    ``render(swing_rgba, canvas_offset, house_layout, phase=0, view=(0,0))``
    returns ``(rgba_image, (canvas_x, canvas_y))``.  Use the actual rendered
    swing image and its canvas placement, after keystone, before compositing
    the character.  Replace the old ellipse in house mode, rather than stack
    both.  ``room_meta`` is the already-loaded room-v2.json metadata.

    Cached source images must remain immutable, as in the host's keystone
    cache.  At most twelve existing input references are retained by default;
    changing the room geometry immediately clears them.
    """

    def __init__(self, room_meta, cache_limit=12):
        room, parallax = room_meta["room"], room_meta["parallax"]
        self.width = float(room_meta["size"][0])
        self.near_x, self.far_x = float(room["side_front_x"]), float(room["side_back_x"])
        self.near_y, self.far_y = float(room["floor_front_y"]), float(room["floor_back_y"])
        self.pf, self.pb = float(parallax["front"]), float(parallax["back"])
        values = (self.width, self.near_x, self.far_x, self.near_y, self.far_y,
                  self.pf, self.pb)
        if not all(math.isfinite(v) for v in values) or not (
                0 <= self.near_x < self.far_x < self.width / 2 and self.near_y > self.far_y):
            raise ValueError("room floor geometry must be a finite trapezoid")
        self.cache_limit = max(1, min(24, int(cache_limit)))
        self._cache = OrderedDict()
        self._geometry = None

    def _floor_point(self, x, y, house_layout, view):
        """The same depth interpolation used by the illustrated room's floor."""
        rx, ry = house_layout.room_origin
        S = house_layout.scale
        depth = max(0.0, min(1.0, (self.near_y-y) / (self.near_y-self.far_y)))
        shift = -self.pf + (self.pf+self.pb) * depth
        return (rx+(x+view[0]*shift)*S, ry+(y+view[1]*shift*.5)*S)

    def floor_polygon(self, house_layout, view=(0.0, 0.0)):
        """Visible floor bounds in canvas pixels, excluding pillars/platform."""
        view = _view(view)
        points = ((self.far_x, self.far_y), (self.width-self.far_x, self.far_y),
                  (self.width-self.near_x, self.near_y), (self.near_x, self.near_y))
        return tuple(self._floor_point(x, y, house_layout, view) for x, y in points)

    @staticmethod
    def _empty():
        return Image.new("RGBA", (1, 1)), (0, 0)

    def render(self, swing_rgba, canvas_offset, house_layout, phase=0.0, view=(0.0, 0.0)):
        view = tuple(round(v*16)/16 for v in _view(view))
        if not math.isfinite(phase) or not all(math.isfinite(v) for v in canvas_offset):
            raise ValueError("shadow pose and placement must be finite")
        phase = round(max(-.65, min(.65, float(phase))) / .02) * .02
        S = house_layout.scale
        if not math.isfinite(S) or S <= 0:
            raise ValueError("house scale must be positive and finite")
        geometry = (house_layout.size, house_layout.room_origin, S, house_layout.floor_y)
        if geometry != self._geometry:
            self._cache.clear()
            self._geometry = geometry
        offset = tuple(round(float(v), 2) for v in canvas_offset)
        key = (id(swing_rgba), offset, phase, view)
        hit = self._cache.get(key)
        if hit is not None and hit[0] is swing_rgba:
            self._cache.move_to_end(key)
            return hit[1].copy(), hit[2]
        if swing_rgba.mode == "L":
            alpha = swing_rgba
        elif "A" in swing_rgba.getbands():
            alpha = swing_rgba.getchannel("A")
        else:
            raise ValueError("the swing input must contain its real alpha")
        bbox = alpha.getbbox()
        if bbox is None:
            return self._empty()
        bx0, by0, bx1, by1 = bbox
        ox, oy = offset
        rx, ry = house_layout.room_origin
        # Shoes remain in the air.  A rear high window projects higher parts
        # farther toward the viewer, hence the vertical reversal of the alpha.
        top_canvas = max(house_layout.floor_y + 9*S + 2*S*math.sin(phase),
                         oy+by1+max(3, 3*S))
        top_y = (top_canvas-ry) / S
        bottom_y = min(top_y+48, self.near_y-10)
        if bottom_y-top_y < 8:
            return self._empty()
        center_x = (ox+(bx0+bx1)/2-rx) / S
        width = max(12, (bx1-bx0)*.54)
        blur = max(2.0, 3.6*S)
        drift = 11.0                       # room px: slight forward/right cast
        rows = 8
        spans = []
        for j in range(rows+1):
            f = j/rows
            y = top_y+(bottom_y-top_y)*f
            cx, cy = self._floor_point(center_x+drift*f, y, house_layout, view)
            spans.append((cx, cy, width*(.90+.10*f)))
        pad = math.ceil(blur*3)+2
        left = math.floor(min(cx-w/2 for cx, _, w in spans))-pad
        right = math.ceil(max(cx+w/2 for cx, _, w in spans))+pad
        top = math.floor(spans[0][1])-pad
        bottom = math.ceil(spans[-1][1])+pad
        out_size = right-left, bottom-top
        # Pre-filter the large alpha once before the very shallow projection.
        # This avoids thin ropes/hat edges aliasing into harsh black strokes.
        source = alpha.crop(bbox).transpose(Image.Transpose.FLIP_TOP_BOTTOM).resize(
            (max(12, round(width)), max(16, round((spans[-1][1]-spans[0][1])*2))),
            Image.Resampling.LANCZOS)
        mesh = []
        for j, ((c0, y0, w0), (c1, y1, w1)) in enumerate(zip(spans, spans[1:])):
            ya, yb = round(y0-top), round(y1-top)
            if yb <= ya:
                continue
            s0, s1 = source.height*j/rows, source.height*(j+1)/rows
            def sx(x, center, span):
                return ((x-center)/span+.5)*source.width
            q = (sx(left, c0, w0), s0, sx(left, c1, w1), s1,
                 sx(right, c1, w1), s1, sx(right, c0, w0), s0)
            mesh.append(((0, ya, out_size[0], yb), q))
        mask = source.transform(out_size, Image.Transform.MESH, mesh,
                                Image.Resampling.BILINEAR, fillcolor=0)
        mask = mask.filter(ImageFilter.GaussianBlur(blur))
        # Enough to link her to the room's lighting, without darkening its
        # sunlit floor or creating a hard contact patch under the shoe.
        opacity = round(34*(1-.10*abs(math.sin(phase))))
        mask = mask.point(lambda v: round(v*opacity/255))
        floor = Image.new("L", out_size)
        ImageDraw.Draw(floor).polygon([(x-left, y-top) for x, y in
                                      self.floor_polygon(house_layout, view)], fill=255)
        mask = ImageChops.multiply(mask, floor)
        result = Image.new("RGBA", out_size, (22, 15, 36, 0))
        result.putalpha(mask)
        at = (left, top)
        self._cache[key] = swing_rgba, result, at
        while len(self._cache) > self.cache_limit:
            self._cache.popitem(last=False)
        return result.copy(), at
