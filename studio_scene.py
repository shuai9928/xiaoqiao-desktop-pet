"""Studio scene: she sits on a clean product stand instead of a gilded swing.

Design (Apple-like restraint): one bent tube of natural titanium forms a level
arch with generous corners and slightly splayed legs; two small feet; a soft
contact shadow under each foot and a broad, very light shadow on the "desk".
No gold, gems or sparkles.  The painted ropes hang from the bar; the right rope
is painted a little lower, so a short cable takes up the difference.

Geometry is in scene-art pixels (the 1254x1254 scene, pivots from meta.json);
``StudioStand.render(k)`` returns the stand drawn at k (canvas px per art px)
and its position in "art px x k" space, like SceneArt.scaled layers.  The
whole stand is drawn behind her.  Pure PIL, cached per k.
"""
from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageFilter

TITANIUM = ((176, 174, 170), (240, 238, 234), (112, 111, 108))
FOOT = (98, 97, 94)
SHADOW = (18, 18, 24)


class StudioStand:
    def __init__(self, pivot_l, pivot_r, seat_bottom=1254):
        self.pl, self.pr = tuple(pivot_l), tuple(pivot_r)
        self.bar_y = self.pl[1] - 4                  # level bar at the higher rope top
        self.x_lt, self.x_rt = 225, 1120             # bar ends / leg tops
        self.x_lf, self.x_rf = 180, 1165             # feet (legs splay a little)
        self.floor = seat_bottom + 68                # air under her shoes
        self.tube = 17
        self.corner = 78
        self._cache = None

    # geometry (art px) --------------------------------------------------
    def bounds(self):
        """Art-px box covering the stand and its floor shadows."""
        return (self.x_lf - 120, self.bar_y - self.tube, self.x_rf + 120, self.floor + 46)

    @property
    def center_x(self):
        return (self.x_lf + self.x_rf) / 2

    # drawing ------------------------------------------------------------
    @staticmethod
    def _corner(p0, p1, p2, r, n=18):
        """Round the corner at p1 (quadratic curve between the points r away
        from p1 along both edges).  Pure math: the pet must not need numpy."""
        def unit(a, b):
            dx, dy = a[0] - b[0], a[1] - b[1]
            d = math.hypot(dx, dy) or 1.0
            return dx / d, dy / d
        u1, u2 = unit(p0, p1), unit(p2, p1)
        s = (p1[0] + u1[0] * r, p1[1] + u1[1] * r)
        e = (p1[0] + u2[0] * r, p1[1] + u2[1] * r)
        out = []
        for i in range(n):
            t = i / (n - 1)
            a, b, c = (1 - t) ** 2, 2 * (1 - t) * t, t * t
            out.append((a * s[0] + b * p1[0] + c * e[0], a * s[1] + b * p1[1] + c * e[1]))
        return out

    def _tube(self, size, pts, w, base, light, dark):
        """Satin metal tube: base, a soft darker lower-right edge, a fine
        bright upper-left line (light from the upper left)."""
        m = Image.new("L", size, 0)
        ImageDraw.Draw(m).line(pts, fill=255, width=max(1, int(w)), joint="curve")
        for x, y in (pts[0], pts[-1]):
            ImageDraw.Draw(m).ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=255)
        col = Image.new("RGBA", size, base + (255,))
        shade = Image.new("L", size, 0)
        ImageDraw.Draw(shade).line([(x + w * .22, y + w * .22) for x, y in pts], fill=255,
                                   width=max(1, int(w * .55)), joint="curve")
        col = Image.composite(Image.new("RGBA", size, dark + (255,)), col,
                              shade.filter(ImageFilter.GaussianBlur(w * .18)))
        hi = Image.new("L", size, 0)
        ImageDraw.Draw(hi).line([(x - w * .2, y - w * .2) for x, y in pts], fill=230,
                                width=max(1, int(w * .18)), joint="curve")
        col = Image.composite(Image.new("RGBA", size, light + (255,)), col,
                              hi.filter(ImageFilter.GaussianBlur(max(.5, w * .08))))
        out = Image.new("RGBA", size, (0, 0, 0, 0))
        out.paste(col, (0, 0), m)
        return out

    def render(self, k):
        kq = round(k / 0.002) * 0.002
        if self._cache and self._cache[0] == kq:
            return self._cache[1]
        SS = 3
        bx0, by0, bx1, by1 = self.bounds()
        size = (max(1, int((bx1 - bx0) * kq * SS)), max(1, int((by1 - by0) * kq * SS)))

        def P(x, y):
            return ((x - bx0) * kq * SS, (y - by0) * kq * SS)

        img = Image.new("RGBA", size, (0, 0, 0, 0))
        # floor shadows: a broad, very light one and a contact shadow per foot
        sh = Image.new("L", size, 0)
        x0, y0 = P(self.x_lf - 40, self.floor - 26)
        x1, y1 = P(self.x_rf + 40, self.floor + 30)
        ImageDraw.Draw(sh).ellipse((x0, y0, x1, y1), fill=40)
        sh = sh.filter(ImageFilter.GaussianBlur(26 * kq * SS))
        for fx in (self.x_lf, self.x_rf):
            px, py = P(fx, self.floor)
            r = 30 * kq * SS
            c = Image.new("L", size, 0)
            ImageDraw.Draw(c).ellipse((px - r * 1.5, py - r * .32, px + r * 1.5, py + r * .42), fill=170)
            sh = Image.composite(Image.new("L", size, 255), sh, c.filter(ImageFilter.GaussianBlur(r * .35)))
        shadow = Image.new("RGBA", size, SHADOW + (0,))
        shadow.putalpha(sh.point(lambda v: int(v * .55)))
        img.alpha_composite(shadow)
        # the arch: one bent tube
        pts = [(self.x_lf, self.floor), (self.x_lt, self.bar_y),
               (self.x_rt, self.bar_y), (self.x_rf, self.floor)]
        arch = ([P(*pts[0])] + [P(*q) for q in self._corner(pts[0], pts[1], pts[2], self.corner)]
                + [P(*q) for q in self._corner(pts[1], pts[2], pts[3], self.corner)] + [P(*pts[3])])
        img.alpha_composite(self._tube(size, arch, self.tube * kq * SS, *TITANIUM))
        # short cable for the lower-painted right rope
        d = ImageDraw.Draw(img)
        d.line([P(self.pr[0], self.bar_y), P(self.pr[0], self.pr[1] + 4)],
               fill=FOOT + (255,), width=max(1, int(3.2 * kq * SS)))
        for fx in (self.x_lf, self.x_rf):                      # small feet
            px, py = P(fx, self.floor)
            w = 44 * kq * SS
            d.rounded_rectangle((px - w / 2, py - 5 * kq * SS, px + w / 2, py + 6 * kq * SS),
                                radius=6 * kq * SS, fill=FOOT + (255,))
        img = img.resize((max(1, round(size[0] / SS)), max(1, round(size[1] / SS))), Image.LANCZOS)
        img.putalpha(img.getchannel("A").point(lambda v: 0 if v < 8 else v))
        hit = (img, (bx0 * kq, by0 * kq))
        self._cache = (kq, hit)
        return hit
