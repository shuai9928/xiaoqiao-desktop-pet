"""Focused geometry safeguards for the optional swing portrait field; no pet/Tk."""
from pathlib import Path
import unittest
from unittest.mock import patch

from PIL import ImageChops, ImageStat

from scene_art import SceneArt


class SwingPortraitDepthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scene = SceneArt(Path(__file__).parent / "assets" / "scene")
        cls.k = .32

    def test_grip_mount_and_seat_are_pinned(self):
        points = ((330, 152), (1020, 188), (380, 630), (390, 760),
                  (987, 505), (959, 748), (705, 858), (658, 905), (810, 1140), (880, 110))
        for view in ((-1, -1), (1, 1), (-1, 1)):
            for point in points:
                with self.subTest(point=point, view=view):
                    self.assertEqual(self.scene.portrait_displacement(*point, self.k, view), (0.0, 0.0))

    def test_face_is_one_rigid_translation(self):
        points = ((610, 520), (737, 554), (658, 582), (570, 490), (790, 620))
        for view in ((-1, -1), (1, 1), (.4, -.8)):
            shifts = [self.scene.portrait_displacement(*p, self.k, view) for p in points]
            self.assertTrue(all(p == shifts[0] for p in shifts))

    def test_default_none_keeps_legacy_without_portrait_mesh(self):
        image, offset = self.scene.scaled(self.k)["swing"]
        with patch.object(self.scene, "_portrait_keystone", side_effect=AssertionError("legacy changed")):
            old, old_off = self.scene.keystone(image, offset, self.k, 0.0, .12)
            explicit, explicit_off = self.scene.keystone(image, offset, self.k, 0.0, .12,
                                                         portrait_view=None)
        self.assertEqual(old_off, explicit_off)
        self.assertEqual(max(hi for _lo, hi in ImageChops.difference(old, explicit).getextrema()), 0)
        margin = round(offset[0] - old_off[0])
        resting = old.crop((margin, 0, margin + image.width, image.height))
        diff = ImageChops.difference(resting.convert("RGBa"), image.convert("RGBa"))
        self.assertLessEqual(max(hi for _lo, hi in diff.getextrema()), 3)

    def test_zero_crossing_uses_one_continuous_mesh(self):
        image, offset = self.scene.scaled(self.k)["swing"]
        for theta in (-.28, 0, .28):
            zero, zero_off = self.scene.keystone(image, offset, self.k, theta, .12,
                                                 portrait_view=(0, 0))
            for amount in (-.02, -.0001, .0001, .02):
                moved, moved_off = self.scene.keystone(image, offset, self.k, theta, .12,
                                                       portrait_view=(amount, 0))
                self.assertEqual(zero_off, moved_off)
                # Evaluate visible premultiplied energy, not unweighted RGB in
                # transparent pixels. Tiny bilinear coordinates can cross an
                # 8-bit rounding boundary, but must never cause a geometry jump.
                diff = ImageChops.difference(zero.convert("RGBa"), moved.convert("RGBa"))
                maximum = max(hi for _lo, hi in diff.getextrema())
                mean = sum(ImageStat.Stat(diff).mean) / 4
                near_zero = abs(amount) < .001
                self.assertLessEqual(maximum, 2 if near_zero else 8)
                self.assertLessEqual(mean, .10 if near_zero else .15)

    def test_contact_pixels_do_not_change_with_portrait_depth(self):
        image, offset = self.scene.scaled(self.k)["swing"]
        contact_points = ((330, 152), (1020, 188), (380, 630), (987, 505),
                          (705, 858), (658, 905), (810, 1140))
        for theta in (-.28, 0, .28):
            zero, zero_off = self.scene.keystone(image, offset, self.k, theta, .12,
                                                 portrait_view=(0, 0))
            for view in ((-1, -1), (1, 1)):
                moved, moved_off = self.scene.keystone(image, offset, self.k, theta, .12,
                                                       portrait_view=view)
                self.assertEqual(zero_off, moved_off)
                for x, y in contact_points:
                    sx, sy = self.scene.fwd(self.scene.swing_geometry(self.k),
                                             x * self.k, y * self.k, theta, .12)
                    cx, cy = round(sx - zero_off[0]), round(sy - zero_off[1])
                    box = (cx - 3, cy - 3, cx + 4, cy + 4)
                    difference = ImageChops.difference(zero.crop(box).convert("RGBa"),
                                                       moved.crop(box).convert("RGBa"))
                    with self.subTest(theta=theta, view=view, contact=(x, y)):
                        self.assertEqual(max(hi for _lo, hi in difference.getextrema()), 0)

    def test_depth_is_bounded_and_smooth(self):
        for x in range(420, 950, 15):
            for y in range(185, 740, 15):
                dx, dy = self.scene.portrait_displacement(x, y, self.k, (1, 1))
                self.assertLessEqual(abs(dx), 1.22)
                self.assertLessEqual(abs(dy), .52)
                nx, ny = self.scene.portrait_displacement(x + .01, y, self.k, (1, 1))
                self.assertLess(abs(dx - nx), .003)
                self.assertLess(abs(dy - ny), .003)
        image, offset = self.scene.scaled(self.k)["swing"]
        for theta, view in ((-.28, (-1, 1)), (.28, (1, -1))):
            out, out_offset = self.scene.keystone(image, offset, self.k, theta, .12,
                                                  portrait_view=view)
            self.assertEqual(out.mode, "RGBA")
            self.assertEqual(out.height, image.height)
            self.assertLess(out_offset[0], offset[0])


if __name__ == "__main__":
    unittest.main()
