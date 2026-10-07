"""Rest eye rendering against real art; no window or personal runtime data."""
import unittest
from PIL import ImageChops
from test_scene_art import _shell


class RestEyesTests(unittest.TestCase):
    def setUp(self):
        self.p = _shell()
        self.p.spr2 = self.p.main_src.copy()
        self.p._blink_patches = None

    def draw(self, key):
        return self.p._face_texture(None, key, base=self.p.spr2)

    def test_sleep_uses_the_same_single_pair_of_eyelids_as_a_blink(self):
        sleeping = self.draw(('sleep', 0, False, 1.0, ''))
        blink = self.draw(('', 0, True, 1.0, ''))
        self.assertIsNone(ImageChops.difference(sleeping.convert('RGB'), blink.convert('RGB')).getbbox())

    def test_sleep_does_not_change_face_silhouette_mouth_or_body(self):
        base = self.p.spr2
        sleeping = self.draw(('sleep', 0, False, 1.0, ''))
        self.assertEqual(sleeping.getchannel('A').tobytes(), base.getchannel('A').tobytes())
        w, h = base.size
        # Changes are confined to the eye band; her mouth and seated body stay intact.
        self.assertEqual(sleeping.crop((0, round(h*.455), w, h)).tobytes(),
                         base.crop((0, round(h*.455), w, h)).tobytes())

    def test_waking_restores_original_pixels_without_residual_lids(self):
        self.draw(('sleep', 0, False, 1.0, ''))
        awake = self.draw(('', 0, False, 0.0, ''))
        self.assertEqual(awake.tobytes(), self.p.spr2.tobytes())

    def test_both_painted_irises_are_covered_in_rest(self):
        sleeping = self.draw(('sleep', 0, False, 1.0, ''))
        w, h = sleeping.size
        for name in ('left', 'right'):
            ex, ey = self.p.cfg['eyes'][name]
            patch = sleeping.crop((round(ex*w-10), round(ey*h-7), round(ex*w+10), round(ey*h+1))).convert('RGB')
            # Blue iris pixels may not remain at the pupil position.
            self.assertFalse(any(b > r+20 and b > g+10 for r,g,b in patch.getdata()), name)


if __name__ == '__main__':
    unittest.main()
