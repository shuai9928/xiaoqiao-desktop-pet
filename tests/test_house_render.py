"""Room compositing with the shipped art: layer order and backlight (offline,
synthetic AI snapshot, no Tk, no user files)."""
import unittest
from unittest.mock import patch

from PIL import Image

from tools.assets.export_function_ui import demo
from tools.assets.export_house_stage import owner
from house_scene import HouseRenderer


class RoomCompositeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = owner(1.25)
        cls.p.sw, cls.p.sh = 2880, 1800
        cls.p.ai_mute_sess = set()
        cls.renderer = HouseRenderer()

    def render(self, small, view=(0.0, 0.0)):
        p = self.p
        geo = p._art_geo(1.0)
        w, h = geo['size']
        sw = {'geo': geo, 'art': True, 'scene_l': 0, 'scene_t': 0, 'scene_w': w,
              'scene_h': h, 'scene_scale': 1.0, 'theta': 0.0, 'omega': 0.0, 'ui': demo()}
        p._swing = sw
        p._house_layers = lambda stage: self.renderer.render(stage['geo']['house_layout'], view)
        with patch('pet.push_layered'):
            p._push_swing_art(small)
        return sw

    def test_bubbles_and_effects_stay_above_the_front_frame(self):
        p = self.p
        sw = self.render(Image.new('RGBA', (p.W, p.H)))
        hl = sw['geo']['house_layout']
        _, front, at = self.renderer.render(hl)
        ox, oy, s = p._art_small_map(sw)
        x0, y0 = int(ox) + 2, int(oy) + 2
        x1, y1 = int(ox + p.W * s) - 2, int(oy + p.H * s) - 2
        spot = next(((x, y) for y in range(y0, y1, 7) for x in range(x0, x1, 7)
                     if 0 <= x - at[0] < front.width and 0 <= y - at[1] < front.height
                     and front.getpixel((x - at[0], y - at[1]))[3] == 255
                     and not any(hx <= x < hx + hw and hy <= y < hy + hh
                                 for hx, hy, hw, hh, _, _ in sw['ui_hits'])), None)
        self.assertIsNotNone(spot, 'the overlay never meets the frame; test is vacuous')
        red = Image.new('RGBA', (p.W, p.H), (255, 0, 0, 255))
        sw = self.render(red)
        self.assertEqual(sw['scene_canvas'].getpixel(spot)[:3], (255, 0, 0))

    def test_small_scene_plaque_grows_until_both_labels_read(self):
        from house_ai_ui import preferred_width
        p = self.p
        geo = p._art_geo(.6)
        w, h = geo['size']
        sw = {'geo': geo, 'art': True, 'scene_l': 0, 'scene_t': 0, 'scene_w': w,
              'scene_h': h, 'scene_scale': .6, 'theta': 0.0, 'omega': 0.0, 'ui': demo()}
        p._swing = sw
        p._house_layers = lambda stage: self.renderer.render(stage['geo']['house_layout'], (0, 0))
        with patch('pet.push_layered'):
            p._push_swing_art(Image.new('RGBA', (p.W, p.H)))
        hl = geo['house_layout']
        zones = [hit for hit in sw['ui_hits'] if hit[4] in ('house_trace', 'house_quota')]
        left = min(z[0] for z in zones)
        right = max(z[0] + z[2] for z in zones)
        self.assertGreater(right - left, hl.plaque[2])                  # grew past the face
        self.assertLessEqual(right - left, int(hl.room_size[0] * .88) + 1)
        self.assertGreaterEqual(left, hl.room_origin[0])
        self.assertLessEqual(right, hl.room_origin[0] + hl.room_size[0])

    def test_backlight_only_brightens_her_outline(self):
        p = self.p
        img = p._scene_art.scaled(p._art_geo(1.0)['k'])['swing'][0]
        lit = p._house_rim(img)
        self.assertIs(p._house_rim(img), lit)              # cached per scaled layer
        self.assertEqual(lit.getchannel('A').tobytes(), img.getchannel('A').tobytes())
        a = img.getchannel('A')
        w, h = img.size
        changed = brighter = 0
        for y in range(0, h, 3):
            for x in range(0, w, 3):
                if a.getpixel((x, y)) < 250:
                    continue
                o, n = img.getpixel((x, y)), lit.getpixel((x, y))
                if o[:3] != n[:3]:
                    changed += 1
                    brighter += sum(n[:3]) >= sum(o[:3])
        self.assertGreater(changed, 0)
        self.assertEqual(brighter, changed)                 # light, never a dark halo
        # the lower legs (bottom fifth of the layer) are not backlit
        for y in range(int(h * .82), h, 3):
            for x in range(0, w, 3):
                self.assertEqual(img.getpixel((x, y))[:3], lit.getpixel((x, y))[:3])


if __name__ == '__main__':
    unittest.main()
