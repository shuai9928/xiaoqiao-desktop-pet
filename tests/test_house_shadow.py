"""Floor/air/caching guards using a synthetic seated silhouette only."""
import unittest
from types import SimpleNamespace

from PIL import Image, ImageChops, ImageDraw

from house_shadow import HouseShadow


META = {"size": (860, 1040),
        "room": {"side_front_x": 150, "side_back_x": 295,
                 "floor_front_y": 920, "floor_back_y": 755},
        "parallax": {"front": 3.8, "back": 7.7}}


def silhouette():
    image = Image.new("RGBA", (240, 680))
    d = ImageDraw.Draw(image)
    d.polygon(((15, 140), (195, 40), (230, 150)), fill=(170, 140, 220, 255))
    d.ellipse((60, 130, 180, 300), fill=(170, 140, 220, 255))
    d.ellipse((65, 270, 170, 500), fill=(170, 140, 220, 255))
    d.rounded_rectangle((125, 475, 168, 655), radius=16, fill=(170, 140, 220, 255))
    return image


class HouseShadowTests(unittest.TestCase):
    def setUp(self):
        self.renderer = HouseShadow(META, cache_limit=3)
        self.house = SimpleNamespace(size=(876, 1056), room_origin=(8, 8),
                                     scale=1.0, floor_y=873.5)
        self.source = silhouette()

    def test_projection_is_faint_on_the_floor_and_never_a_shoe_contact_mark(self):
        before = self.source.copy()
        shadow, (x, y) = self.renderer.render(self.source, (300, 180), self.house)
        self.assertEqual(self.source.tobytes(), before.tobytes())
        alpha = shadow.getchannel("A")
        bbox = alpha.getbbox()
        self.assertIsNotNone(bbox)
        self.assertLessEqual(alpha.getextrema()[1], 34)
        self.assertGreater(y+bbox[1], 180+655+3)  # hanging shoe is safely above it
        # Independently paint the neutral room's authored floor bounds.
        allowed = Image.new("L", self.house.size)
        ImageDraw.Draw(allowed).polygon(((303, 763), (573, 763),
                                        (718, 928), (158, 928)), fill=255)
        placed = Image.new("L", self.house.size)
        placed.paste(alpha, (x, y))
        outside = ImageChops.multiply(placed, ImageChops.invert(allowed))
        self.assertIsNone(outside.getbbox())

    def test_output_is_owned_and_cache_cannot_grow_with_camera_or_pose(self):
        first, at = self.renderer.render(self.source, (300, 180), self.house)
        saved = first.copy()
        first.paste((255, 0, 0, 255), (0, 0, *first.size))
        same, same_at = self.renderer.render(self.source, (300, 180), self.house)
        self.assertEqual((same.tobytes(), same_at), (saved.tobytes(), at))
        for phase in (-.3, -.1, .1, .3):
            self.renderer.render(self.source, (300, 180), self.house, phase, (1, -.5))
        self.assertLessEqual(len(self.renderer._cache), 3)
        small = SimpleNamespace(size=(700, 840), room_origin=(8, 8),
                                scale=.76, floor_y=8+865.5*.76)
        self.renderer.render(self.source, (200, 0), small)
        self.assertLessEqual(len(self.renderer._cache), 1)

    def test_empty_silhouette_cannot_darken_the_floor_or_read_other_assets(self):
        shadow, offset = self.renderer.render(Image.new("RGBA", (10, 20)),
                                              (100, 100), self.house)
        self.assertIsNone(shadow.getchannel("A").getbbox())
        with self.assertRaises(ValueError):
            self.renderer.render(self.source, (100, 100), self.house, float("nan"))


if __name__ == "__main__":
    unittest.main()
