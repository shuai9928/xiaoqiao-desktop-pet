"""Quiet ambient life for the compact room.

The room is a painting; a few slow, small things make it feel inhabited:
stars that twinkle and a moon whose glow breathes in the window, dust drifting
in the moonlight, the shelf orbs' faint inner glow, an occasional glint
running over one of the front crystal pendants, and the room dimming while
she dozes.  Everything except the pendant glints is drawn behind her, nothing
is drawn on her, and nothing hides structure (constitution 1/3/5).

Pure PIL and deterministic in time: every effect is a function of ``now``
(no random state between frames), positions are room pixels from
room-v2.json["life"], and each effect follows the parallax of its depth.
"""
from __future__ import annotations

import math
from collections import OrderedDict

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from house_scene import depth_shift

STAR = (255, 247, 226)
MOON = (255, 244, 214)
ORB = (200, 186, 255)
MOTE = (255, 238, 212)
DIM = (16, 12, 34)


def _hash(i, k=0):
    """Small deterministic pseudo-random in [0, 1)."""
    v = math.sin(i * 12.9898 + k * 78.233) * 43758.5453
    return v - math.floor(v)


class RoomLife:
    def __init__(self, meta):
        life = meta["life"]
        self.meta = meta
        self.moon = life["moon"]
        self.glass = life["glass"]
        self.stars = life["stars"]
        self.orbs = life["orbs"]
        self.beam = life["beam"]
        self.glints = life["glints"]
        self.room_size = tuple(meta["size"])
        self._cache = OrderedDict()          # small sprites
        self._scaled = (None, {})            # per-zoom masks (only the current zoom)
        self._dim = None                     # (behind, fg, level, overlays)

    # ---------------------------------------------------------------- sprites
    def _memo(self, key, build):
        hit = self._cache.get(key)
        if hit is None:
            hit = self._cache[key] = build()
            while len(self._cache) > 96:
                self._cache.popitem(last=False)
        else:
            self._cache.move_to_end(key)
        return hit

    @staticmethod
    def _glow(r, rgb, hole=0.0):
        """Soft radial glow sprite (alpha 255 at the centre, or at ``hole``)."""
        n = max(3, int(math.ceil(r)) * 2 + 3)
        m = Image.new("L", (n, n), 0)
        d = ImageDraw.Draw(m)
        c = n / 2
        steps = 14
        for i in range(steps, 0, -1):
            t = i / steps
            rr = hole + (r - hole) * t
            d.ellipse((c - rr, c - rr, c + rr, c + rr), fill=int(255 * (1 - t) ** 1.6))
        m = m.filter(ImageFilter.GaussianBlur(max(.6, r / 6)))
        if hole > 0:
            # cut the inside out: light around something, never over it
            cut = Image.new("L", (n, n), 255)
            ImageDraw.Draw(cut).ellipse((c - hole, c - hole, c + hole, c + hole), fill=0)
            m = ImageChops.multiply(m, cut.filter(ImageFilter.GaussianBlur(max(.5, hole / 10))))
        img = Image.new("RGBA", (n, n), rgb + (0,))
        img.putalpha(m)
        return img

    @staticmethod
    def _sparkle(r, rgb):
        """Four-point star: thin cross with a small bright core."""
        n = max(5, int(math.ceil(r * 2)) * 2 + 3)
        m = Image.new("L", (n, n), 0)
        d = ImageDraw.Draw(m)
        c = (n - 1) / 2
        arm = r * 2
        w = max(1.0, r * .32)
        d.polygon([(c, c - arm), (c + w, c), (c, c + arm), (c - w, c)], fill=200)
        d.polygon([(c - arm, c), (c, c - w), (c + arm, c), (c, c + w)], fill=200)
        d.ellipse((c - w * 1.4, c - w * 1.4, c + w * 1.4, c + w * 1.4), fill=255)
        m = m.filter(ImageFilter.GaussianBlur(max(.35, r / 7)))
        img = Image.new("RGBA", (n, n), rgb + (0,))
        img.putalpha(m)
        return img

    @staticmethod
    def _fade(img, a):
        if a >= .999:
            return img
        out = img.copy()
        out.putalpha(out.getchannel("A").point(lambda v, a=a: int(v * a)))
        return out

    def _paste(self, canvas, img, x, y, a=1.0):
        if a <= .01:
            return
        img = self._fade(img, max(0.0, min(1.0, a)))
        canvas.alpha_composite(img, (int(round(x - img.width / 2)), int(round(y - img.height / 2))))

    # ---------------------------------------------------------------- helpers
    def _at(self, L, x, y, depth, view):
        dx, dy = depth_shift(depth, view, self.meta)
        S = L.scale
        return L.room_origin[0] + (x + dx) * S, L.room_origin[1] + (y + dy) * S

    def _per_scale(self, key, S, build):
        s, store = self._scaled
        if s != round(S, 4):
            store = {}
            self._scaled = (round(S, 4), store)
        if key not in store:
            store[key] = build()
        return store[key]

    def _halo(self, S):
        """Moon glow clipped to the centre pane (light lives in the glass)."""
        def build():
            mx, my, mr = self.moon
            R = mr * 1.9 * S
            glow = self._glow(R, MOON, hole=mr * .95 * S)
            mask = Image.new("L", glow.size, 0)
            ox, oy = mx * S - glow.width / 2, my * S - glow.height / 2
            ImageDraw.Draw(mask).polygon([(x * S - ox, y * S - oy) for x, y in self.glass[0]], fill=255)
            glow.putalpha(Image.composite(glow.getchannel("A"), mask, mask))
            return glow
        return self._per_scale("halo", S, build)

    def _beam_mask(self, S):
        def build():
            w, h = (max(1, round(v * S)) for v in self.room_size)
            m = Image.new("L", (w, h), 0)
            ImageDraw.Draw(m).polygon([(x * S, y * S) for x, y in self.beam], fill=255)
            return m.filter(ImageFilter.GaussianBlur(14 * S))
        return self._per_scale("beam", S, build)

    # ---------------------------------------------------------------- layers
    def draw_behind(self, canvas, L, view, now, sleepy=0.0):
        """Window sky, orb glow and moonlit dust; drawn after the room interior,
        before the swing.  ``sleepy`` (0..1) deepens the night while she naps."""
        S = L.scale
        # moon glow breathes very slowly (11 s); a little brighter at night-nap
        mx, my, _ = self.moon
        x, y = self._at(L, mx, my, 1.0, view)
        breath = .5 - .5 * math.cos(now * math.tau / 11.0)
        self._paste(canvas, self._halo(S), x, y, .32 + .22 * breath + .25 * sleepy)
        # stars: mostly faint, each brightening briefly on its own slow rhythm
        for i, (sx, sy, sr) in enumerate(self.stars):
            period = 3.8 + 4.5 * _hash(i, 1)
            ph = (now / period + _hash(i, 2)) % 1.0
            pulse = max(0.0, math.sin(ph * math.pi)) ** 6
            a = .18 + .62 * pulse + .2 * sleepy
            spr = self._memo(("star", round(sr * S * 2) / 2),
                             lambda r=sr * S: self._sparkle(max(.8, r), STAR))
            x, y = self._at(L, sx, sy, 1.0, view)
            self._paste(canvas, spr, x, y, a)
        # shelf orbs: a faint inner glow, slow and out of phase
        for i, (ox_, oy_, orr, depth) in enumerate(self.orbs):
            g = .5 - .5 * math.cos(now * math.tau / 6.5 + i * 2.1)
            spr = self._memo(("orb", round(orr * S)), lambda r=orr * S: self._glow(r * 1.25, ORB))
            x, y = self._at(L, ox_, oy_, depth, view)
            self._paste(canvas, spr, x, y, .16 + .22 * g)
        # dust in the moonlight: slow upward drift, alive only inside the beam
        beam = self._beam_mask(S)
        bx0, by0 = min(p[0] for p in self.beam), min(p[1] for p in self.beam)
        bx1, by1 = max(p[0] for p in self.beam), max(p[1] for p in self.beam)
        dot = self._memo(("mote", round(S * 4) / 4), lambda: self._glow(max(1.0, 1.7 * S), MOTE))
        for i in range(14):
            life = 7.0 + 5.0 * _hash(i, 3)
            t = now / life + _hash(i, 4)
            gen, age = int(t), t % 1.0
            u = _hash(i * 31 + gen, 5)
            v = _hash(i * 17 + gen, 6)
            px = bx0 + (bx1 - bx0) * u + 9 * math.sin(now * .7 + i)
            py = by1 - (by1 - by0) * (v * .7 + age * .3)
            bxp, byp = int(px * S), int(py * S)
            inside = beam.getpixel((min(beam.width - 1, max(0, bxp)),
                                    min(beam.height - 1, max(0, byp)))) / 255
            if inside <= .05:
                continue
            a = math.sin(age * math.pi) * inside * (.55 + .2 * sleepy)
            x, y = self._at(L, px, py, .6, view)
            self._paste(canvas, dot, x, y, a)

    def draw_front(self, canvas, L, front_at, now, fg):
        """An occasional glint running over one front crystal pendant (frame
        layer, so it follows the frame's parallax offset).  Clipped to the
        frame's own alpha: light on the crystal, never on the desktop."""
        S = L.scale
        cycle = 3.4
        n = int(now // cycle)
        t = (now % cycle) / .75                    # the glint lives 0.75 s
        if t >= 1.0:
            return
        gx, gy, gr = self.glints[int(_hash(n, 7) * len(self.glints)) % len(self.glints)]
        a = math.sin(t * math.pi) ** 1.5
        size = gr * S * (.32 + .2 * math.sin(t * math.pi))
        spr = self._memo(("glint", round(size * 2) / 2), lambda r=size: self._sparkle(max(1.0, r), (255, 255, 255)))
        # light comes from the upper left: the glint sits on that facet
        x = front_at[0] + (gx - gr * .22) * S
        y = front_at[1] + (gy - gr * .35) * S
        img = self._fade(spr, .85 * a)
        if img is spr:
            img = spr.copy()
        px, py = int(round(x - img.width / 2)), int(round(y - img.height / 2))
        lx, ly = px - front_at[0], py - front_at[1]
        under = fg.getchannel("A").crop((lx, ly, lx + img.width, ly + img.height))
        img.putalpha(ImageChops.multiply(img.getchannel("A"), under))
        canvas.alpha_composite(img, (px, py))

    def dim_layers(self, L, behind, fg, level):
        """Cached overlays that dim the room (not her) by ``level`` (0..1): one
        over the interior (canvas-sized, from the behind image's alpha) and one
        over the frame (room-sized)."""
        q = round(max(0.0, min(1.0, level)) * 12) / 12
        if q <= 0:
            return None, None
        hit = self._dim
        if hit and hit[0] is behind and hit[1] is fg and hit[2] == q:
            return hit[3]

        def over(src, amount):
            a = src.getchannel("A").point(lambda v, k=amount * q: int(v * k))
            img = Image.new("RGBA", src.size, DIM + (0,))
            img.putalpha(a)
            return img
        out = (over(behind, .42), over(fg, .30))
        self._dim = (behind, fg, q, out)
        return out
