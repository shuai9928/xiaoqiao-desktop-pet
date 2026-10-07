"""Ambient room life: deterministic, behind her, never on the desktop; the
nameplate gem as a status light; the room dimming while she naps.
Offline with the shipped room art; no Tk, no user files."""
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops

from house_ai_ui import gem_motion
from house_scene import HouseRenderer, layout, meta
from room_life import RoomLife

K = 0.4055
T0 = 1791100000.0


class RoomLifeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.L = layout(K, (-20 * K, 0, 1240 * K, 1254 * K))
        cls.r = HouseRenderer()
        cls.behind, cls.fg, cls.at = cls.r.render(cls.L)
        cls.life = RoomLife(meta())

    def room(self):
        c = self.behind.copy()
        c.alpha_composite(self.fg, self.at)
        return c

    def test_same_moment_draws_the_same_frame(self):
        a, b = self.room(), self.room()
        for c in (a, b):
            self.life.draw_behind(c, self.L, (0, 0), T0 + 1.234, .3)
            self.life.draw_front(c, self.L, self.at, T0 + 1.234, self.fg)
        self.assertIsNone(ImageChops.difference(a, b).getbbox())

    def test_nothing_is_drawn_on_the_desktop_around_the_room(self):
        base = self.room()
        alpha0 = base.getchannel("A")
        for i in range(0, 120, 3):              # 12 s, glints included
            c = base.copy()
            t = T0 + i * .1
            self.life.draw_behind(c, self.L, ((i % 7) / 3 - 1, 0), t, (i % 5) / 4)
            self.life.draw_front(c, self.L, self.at, t, self.fg)
            grown = ImageChops.subtract(c.getchannel("A"), alpha0)
            outside = ImageChops.multiply(grown, alpha0.point(lambda v: 255 if v == 0 else 0))
            self.assertIsNone(outside.getbbox(), i)

    def test_effects_are_small_and_slow(self):
        a, b = self.room(), self.room()
        self.life.draw_behind(a, self.L, (0, 0), T0, 0)
        self.life.draw_behind(b, self.L, (0, 0), T0 + .1, 0)
        diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).convert("L")
        changed = diff.point(lambda v: 255 if v > 6 else 0).histogram()[255]
        self.assertLess(changed, 0.01 * a.width * a.height)   # a frame changes < 1% of the room

    def test_a_glint_lights_a_front_crystal_only(self):
        hit = None
        for i in range(0, 80):
            t = T0 + i * .05
            if (t % 3.4) / .75 < 1 and abs((t % 3.4) / .75 - .5) < .1:
                hit = t
                break
        self.assertIsNotNone(hit)
        a, b = self.room(), self.room()
        self.life.draw_front(b, self.L, self.at, hit, self.fg)
        box = ImageChops.difference(a, b).getbbox()
        self.assertIsNotNone(box)
        self.assertLess((box[2] - box[0]) * (box[3] - box[1]), 60 * 60)

    def test_nap_dims_the_room_not_beyond_it(self):
        self.assertEqual(self.life.dim_layers(self.L, self.behind, self.fg, 0), (None, None))
        back, front = self.life.dim_layers(self.L, self.behind, self.fg, 1)
        self.assertEqual(back.size, self.behind.size)
        self.assertEqual(front.size, self.fg.size)
        self.assertLessEqual(back.getchannel("A").getextrema()[1], int(.42 * 255) + 1)
        self.assertLessEqual(front.getchannel("A").getextrema()[1], int(.30 * 255) + 1)
        empty = self.behind.getchannel("A").point(lambda v: 255 if v == 0 else 0)
        self.assertIsNone(ImageChops.multiply(back.getchannel("A"), empty).getbbox())
        self.assertIs(self.life.dim_layers(self.L, self.behind, self.fg, 1)[0], back)


class NameplateGemTests(unittest.TestCase):
    def session(self, state, age=5, stale=False):
        return {'sel_session': {'id': 's', 'state': state, 'updated': T0 - age, 'stale': stale}}

    def test_running_breathes_waiting_pulses_error_glows(self):
        for state, lo, hi in (('running', .2, .56), ('waiting', .29, .93), ('error', .29, .61)):
            values = [gem_motion(self.session(state), T0 + i * .1)[1] for i in range(40)]
            self.assertGreaterEqual(min(values), lo, state)
            self.assertLessEqual(max(values), hi, state)
            self.assertGreater(max(values) - min(values), .2, state)
        waiting = [gem_motion(self.session('waiting'), T0 + i * .05)[1] for i in range(40)]
        self.assertGreater(max(waiting), .8)

    def test_fresh_finish_shimmers_then_rests(self):
        self.assertGreater(gem_motion(self.session('done', age=5), T0)[1], .4)
        self.assertEqual(gem_motion(self.session('done', age=120), T0), (None, 0.0))

    def test_idle_stale_and_missing_stay_still(self):
        for ui in (self.session('idle'), self.session('running', stale=True),
                   self.session('running', age=99999), {}, {'sel_session': None}):
            self.assertEqual(gem_motion(ui, T0), (None, 0.0), ui)


class NapDimEasingTests(unittest.TestCase):
    def test_room_eases_dark_while_she_naps_and_back_when_she_wakes(self):
        from test_house_integration import shell
        p = shell()
        p._room_dim = (0.0, T0)
        p._nap_on_swing = True
        levels = [p._room_sleep_level(T0 + i * .1) for i in range(1, 31)]
        self.assertTrue(all(b >= a for a, b in zip(levels, levels[1:])))
        self.assertLess(levels[0], .3)            # no sudden blackout
        self.assertEqual(levels[-1], 1.0)
        p._nap_on_swing = False
        back = [p._room_sleep_level(T0 + 3 + i * .1) for i in range(1, 31)]
        self.assertEqual(back[-1], 0.0)


if __name__ == "__main__":
    unittest.main()
