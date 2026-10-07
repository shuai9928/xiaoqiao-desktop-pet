"""Depth regressions protect the face, seated contact and moving entrances."""
import math
from pathlib import Path
import unittest

from PIL import ImageChops

from room_portrait import RoomPortrait

ASSETS = Path(__file__).resolve().parents[1] / "assets"


class PortraitDepthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.portrait = RoomPortrait(ASSETS)

    def test_eyes_and_mouth_remain_one_rigid_patch_at_extreme_views(self):
        p = self.portrait
        for view in ((-1, -1), (1, 1), (-1, 1), (1, -1)):
            moves = [p.displacement(x, y, view, lag=(-view[0], -view[1]), breath=1)
                     for x, y in ((.30, .35), (.51, .41), (.47, .46), (.40, .49))]
            self.assertTrue(all(move == moves[0] for move in moves))
            self.assertLessEqual(abs(moves[0][0]), 4)

    def test_breath_and_view_do_not_move_the_cushion_or_seated_legs(self):
        p = self.portrait
        for y in (.70, .76, .85, .96):
            for x in (.15, .45, .70):
                self.assertEqual(p.displacement(x, y, (1, 1), (-1, -1), 1), (0, 0))
        left = p.render((-1, 1), (1, -1), 1)
        right = p.render((1, -1), (-1, 1), -1)
        self.assertIsNone(ImageChops.difference(left.getchannel("A").crop((20, 335, 300, 426)),
                                               right.getchannel("A").crop((20, 335, 300, 426))).getbbox())

    def test_mesh_has_shared_edges_and_never_folds(self):
        p = self.portrait
        for view in ((-1, -1), (1, 1)):
            for j in range(32):
                for i in range(24):
                    points = []
                    for a, b in ((i, j), (i, j+1), (i+1, j+1), (i+1, j)):
                        x, y = p.xs[a], p.ys[b]
                        dx, dy = p.displacement(x/p.w, y/p.h, view, (-view[0], -view[1]), 1)
                        points.append((x-dx*2, y-dy*2))
                    for k in range(4):
                        a, b, c = points[k], points[(k+1)%4], points[(k+2)%4]
                        self.assertLess((b[0]-a[0])*(c[1]-b[1]) - (b[1]-a[1])*(c[0]-b[0]), 0)


class RoomStageTests(unittest.TestCase):
    def test_entrances_follow_projected_props_at_both_sizes(self):
        from room_preview import RoomSceneRenderer, _RECTS
        from room_geometry import anchor_offsets
        r = RoomSceneRenderer(ASSETS)
        for scale in (1.0, .76):
            for view in ((-1, -1), (-1, 1), (1, -1), (1, 1), (0, 0)):
                image, rects = r.render(scale, view)
                offsets = anchor_offsets(view)
                self.assertEqual(image.size, (round(400*scale), round(500*scale)))
                for key, (x, y, w, h) in rects.items():
                    sx0, sy0, sx1, sy1 = _RECTS[key]
                    dx, dy = offsets[key]
                    self.assertLessEqual(abs(x+w/2-((sx0+sx1)/2+dx)*scale), .6)
                    self.assertLessEqual(abs(y+h/2-((sy0+sy1)/2+dy)*scale), .6)
                    self.assertGreaterEqual(min(w, h), 32)
                    self.assertGreaterEqual(min(x,y), 0)
                    self.assertLessEqual(x+w,image.width)
                    self.assertLessEqual(y+h,image.height)
                    for other, (ox, oy, ow, oh) in rects.items():
                        if key != other:
                            self.assertFalse(x < ox+ow and ox < x+w and y < oy+oh and oy < y+h)


if __name__ == "__main__":
    unittest.main()
