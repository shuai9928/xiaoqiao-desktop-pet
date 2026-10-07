"""Compact room geometry and layered renderer; no Tk, user files or services."""
import unittest

from PIL import Image, ImageChops

from house_scene import PAD, HouseRenderer, depth_shift, layout, meta

LIVE_K = 0.4055          # swing scale of the live pet (scale 1.25, scene 1.0)


def _contains(outer, inner):
    x, y, w, h = inner
    return x >= 0 and y >= 0 and x + w <= outer[0] and y + h <= outer[1]


class HouseLayoutTests(unittest.TestCase):
    def test_room_is_compact_around_the_swing_it_hosts(self):
        # The old wide house with a permanent dashboard was 1179 x 811 here.
        box = (-20 * LIVE_K, 0, 1240 * LIVE_K, 1254 * LIVE_K)
        house = layout(LIVE_K, box)
        w, h = house.size
        self.assertLess(w, 720)
        self.assertLess(h, 860)
        self.assertLess(w * h, 0.65 * 1179 * 811)
        self.assertAlmostEqual(house.scale, LIVE_K / meta()["swing"]["ks"])
        for rect in (house.left_bounds, house.plaque):
            self.assertTrue(_contains(house.size, rect), rect)
        # nameplate sits on the platform, below the stage opening
        self.assertGreaterEqual(house.plaque[1], house.left_bounds[1] + house.left_bounds[3] - 2)
        self.assertGreaterEqual(min(house.room_origin), PAD)

    def test_swing_translation_is_uniform_and_hangs_under_the_beam(self):
        k = .3
        box = (-12.0, -3.0, 380.0, 376.0)
        house = layout(k, box)
        # canvas px of a scene-art point = art*k - O; the plain canvas had O=box[:2]
        for ax, ay in ((330, 152), (1020, 188), (658, 905)):
            before = (ax * k - box[0], ay * k - box[1])
            after = (ax * k - house.O[0], ay * k - house.O[1])
            self.assertAlmostEqual(after[0] - before[0], house.left_origin[0])
            self.assertAlmostEqual(after[1] - before[1], house.left_origin[1])
        # the crossbar top lands on the room's authored hanging line
        sw = meta()["swing"]
        bar_y = sw["scene_bar_top"] * k - house.O[1]
        self.assertAlmostEqual(bar_y, house.room_origin[1] + sw["top"] * house.scale, delta=1)
        self.assertGreater(house.floor_y, bar_y)

    def test_canvas_also_holds_a_swing_canvas_larger_than_the_room(self):
        k = .4
        box = (-300.0, -400.0, 900.0, 700.0)    # e.g. a big speech bubble above her
        house = layout(k, box)
        self.assertLessEqual(house.O[0], box[0])
        self.assertLessEqual(house.O[1], box[1])
        self.assertGreaterEqual(house.O[0] + house.size[0], box[2])
        self.assertGreaterEqual(house.O[1] + house.size[1], box[3])

    def test_invalid_geometry_is_rejected_instead_of_warping_the_character(self):
        for k in (float("nan"), float("inf"), 0, 9):
            with self.assertRaises(ValueError):
                layout(k, (0, 0, 10, 10))
        for box in ((0, 0, 0, 10), (5, 5, 1, 1), (0, float("nan"), 3, 3)):
            with self.assertRaises(ValueError):
                layout(.4, box)


class HouseRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.renderer = HouseRenderer(cache_limit=3)
        cls.house = layout(.3, (-10.0, 0.0, 370.0, 376.0))

    def test_layers_rebuild_the_room_and_leave_the_outside_transparent(self):
        back, front, at = self.renderer.render(self.house)
        self.assertEqual(back.size, self.house.size)
        self.assertEqual(front.size, self.house.room_size)
        self.assertEqual(at, self.house.room_origin)
        self.assertEqual(back.getpixel((0, 0))[3], 0)
        both = back.copy()
        both.alpha_composite(front, at)
        x, y, w, h = self.house.left_bounds
        # the stage opening shows the room interior, the frame surrounds it
        self.assertGreater(back.getpixel((x + w // 2, y + h // 2))[3], 240)
        self.assertEqual(front.getpixel((front.width // 2, front.height // 2))[3], 0)
        S = self.house.scale
        for px, py in ((90, 520), (860 - 90, 520), (430, 140), (430, 950)):   # pillars, beam, platform
            self.assertGreater(front.getpixel((round(px * S), round(py * S)))[3], 200, (px, py))

    def test_frame_and_back_wall_move_against_each_other(self):
        pf, pb = meta()["parallax"]["front"], meta()["parallax"]["back"]
        self.assertAlmostEqual(depth_shift(0.0, (1, 0))[0], -pf)
        self.assertAlmostEqual(depth_shift(1.0, (1, 0))[0], pb)
        plane = meta()["swing"]["plane_depth"]
        self.assertAlmostEqual(depth_shift(plane, (1, 0))[0], 0, places=2)
        _, _, left_at = self.renderer.render(self.house, (-1, 0))
        _, _, right_at = self.renderer.render(self.house, (1, 0))
        self.assertGreater(left_at[0], right_at[0])          # frame against the camera
        self.assertLessEqual(abs(left_at[0] - self.house.room_origin[0]), PAD)
        left, _, _ = self.renderer.render(self.house, (-1, 0))
        right, _, _ = self.renderer.render(self.house, (1, 0))
        # the back wall (window) moves with the camera: compare a window row
        x, y, w, h = self.house.left_bounds
        row = y + h // 3
        a = left.crop((x, row, x + w, row + 1)).convert("L")
        b = right.crop((x, row, x + w, row + 1)).convert("L")
        best = min(range(-12, 13), key=lambda s: sum(
            abs(a.getpixel((i, 0)) - b.getpixel((i + s, 0)))
            for i in range(20, w - 20)))
        self.assertGreater(best, 0)

    def test_cache_is_bounded_and_views_are_quantized(self):
        for view in ((-1, -1), (1, -1), (1, 1), (-1, 1), (.5, .5)):
            self.renderer.render(self.house, view)
        self.assertLessEqual(len(self.renderer._frames), 3)
        a = self.renderer.render(self.house, (.501, 0))
        b = self.renderer.render(self.house, (.502, 0))
        self.assertIs(a[0], b[0])

    def test_invalid_camera_is_rejected(self):
        for view in ((float("nan"), 0), (0, float("inf")), (0,)):
            with self.assertRaises(ValueError):
                self.renderer.render(self.house, view)


if __name__ == "__main__":
    unittest.main()
