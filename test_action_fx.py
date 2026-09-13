"""动作时序、打断和特效边界回归,不启动桌宠或触碰存档。"""
import unittest
from unittest.mock import Mock, patch
from PIL import Image, ImageDraw
import pet
import fx


class ActionTests(unittest.TestCase):
    def make_pet(self):
        p = pet.Pet.__new__(pet.Pet)
        p.state, p.fy, p.ground_feet = 'idle', 800., 800.
        p.sfx = Mock()
        p.say, p.land_fx, p.star_burst = Mock(), Mock(), Mock()
        with patch.object(pet.time, 'time', return_value=100):
            p.start_flip()
        return p

    def test_takeoff_apex_and_landing(self):
        duration = 2 * 680 / 1500
        self.assertEqual(pet.Pet._flip_flight(.3)[:2], (0., 0.))
        lift, turn, landing = pet.Pet._flip_flight(.3 + duration / 2)
        self.assertGreater(lift, 150)
        self.assertAlmostEqual(turn, .5)
        self.assertLess(landing, 0)
        lift, turn, landing = pet.Pet._flip_flight(.3 + duration)
        self.assertAlmostEqual(lift, 0)
        self.assertEqual(turn, 1)
        self.assertAlmostEqual(landing, 0)

    def test_landing_once_at_different_frame_rates(self):
        for fps in (10, 20, 30, 60):
            p = self.make_pet()
            for i in range(int(2.4 * fps) + 1):
                age = i / fps
                p._advance_flip(100 + age)
                self.assertLessEqual(p.fy, p.ground_feet)
                if age < .3 + 2 * 680 / 1500:
                    p.land_fx.assert_not_called()
            p.land_fx.assert_called_once_with(1.0)
            self.assertEqual(p.fy, p.ground_feet)
            self.assertEqual(p._spin_rot, 0)
            self.assertAlmostEqual(p.squash, 1)

    def test_long_frame_does_not_leave_pet_in_air(self):
        p = self.make_pet()
        p._advance_flip(100.4)
        self.assertLess(p.fy, p.ground_feet)
        p._advance_flip(103)
        self.assertEqual((p.state, p.fy), ('idle', 800.))
        p.land_fx.assert_called_once()

    def test_flip_does_not_teleport_from_air_to_ground(self):
        p = self.make_pet()
        p.state, p.fy = 'fly', 300
        p.start_flip()
        self.assertEqual((p.state, p.fy), ('fly', 300))


class EffectsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fx = fx.FX(1, 2)

    def shock(self, progress, strength):
        im = Image.new('RGBA', (600, 200))
        self.fx.shockwave(im, 300, 100, progress, strength)
        return im

    def test_shock_fades_and_all_strengths_finish_together(self):
        for strength in (0, .5, 1):
            early = self.shock(.2, strength).getchannel('A').getextrema()[1]
            late = self.shock(.8, strength).getchannel('A').getextrema()[1]
            self.assertGreater(early, late)
            self.assertIsNone(self.shock(1, strength).getbbox())
            self.assertIsNone(self.shock(-.1, strength).getbbox())

    def test_shock_strength_controls_radius(self):
        small, large = (self.shock(.5, s).getbbox() for s in (0, 1))
        self.assertLess(small[2] - small[0], large[2] - large[0])

    def test_ribbons_start_and_end_clear(self):
        for age in (0, .2, 2.65, 5):
            im = Image.new('RGBA', (700, 700))
            d = ImageDraw.Draw(im)
            for front in (False, True):
                fx.transform_ribbons(d, 350, 650, 500, 600, age, 2, front)
            self.assertIsNone(im.getbbox())

    def test_ribbons_have_two_layers_and_leave_face_clear(self):
        for front in (False, True):
            im = Image.new('RGBA', (700, 700))
            fx.transform_ribbons(ImageDraw.Draw(im), 350, 650, 500, 600, 1., 2, front)
            self.assertIsNotNone(im.getbbox())
            if front:
                self.assertIsNone(im.crop((0, 0, 700, 360)).getbbox())

    def test_energy_changes_speed_without_jumping_phase(self):
        layer = fx.FX(1, 1)
        im = Image.new('RGBA', (500, 200))
        d = ImageDraw.Draw(im)
        layer.ground_circle(im, d, 250, 100, 5000., 0)
        phase = layer._orbit_spin
        layer.ground_circle(im, d, 250, 100, 5000., 1)
        self.assertEqual(layer._orbit_spin, phase)
        layer.ground_circle(im, d, 250, 100, 5000.02, 1)
        self.assertAlmostEqual(layer._orbit_spin - phase, .02 * 2.15)
        phase = layer._orbit_spin
        layer.ground_circle(im, d, 250, 100, 0, 0)
        self.assertEqual(layer._orbit_spin, phase)


class ChoreographyTests(unittest.TestCase):
    def test_peek_lands_once_after_jump_at_multiple_frame_rates(self):
        for fps in (10, 30, 60):
            p = self.make_pet()
            p.fy = p.ground_feet = 800
            p.parts = [{'kind': 'zzz'}, {'kind': 'firefly'}]
            with patch.object(pet.time, 'time', return_value=100):
                p.start_peek()
            for i in range(int(8*fps)):
                age = i/fps
                p._play_timeline(age, p._tl_tracks, p._tl_events, p._tl_done)
                self.assertGreaterEqual(p._spin_lift, 0)
                if age < 6.82:
                    p.land_fx.assert_not_called()
            p.land_fx.assert_called_once_with(.45)
            self.assertEqual((p._spin_lift, p.squash), (0, 1))
            self.assertEqual(p.parts, [{'kind': 'firefly'}])

    def test_peek_long_frame_resolves_jump_and_landing(self):
        p = self.make_pet()
        p.fy = p.ground_feet = 800
        p.parts = []
        with patch.object(pet.time, 'time', return_value=100):
            p.start_peek()
        p._play_timeline(9, p._tl_tracks, p._tl_events, p._tl_done)
        self.assertEqual(p._spin_lift, 0)
        p.land_fx.assert_called_once_with(.45)

    def test_peek_waits_until_grounded(self):
        p = self.make_pet()
        p.state, p.fy, p.ground_feet = 'fly', 300, 800
        p.start_peek()
        self.assertEqual((p.state, p.fy), ('fly', 300))

    def make_pet(self):
        p = pet.Pet.__new__(pet.Pet)
        p.x, p.x_min, p.x_max, p.scale, p.W, p.H, p.face = 400., 0, 1000, 1, 430, 520, 1
        p.sfx = Mock()
        for name in ('say', 'play_emotion', 'add_part', 'land_fx', 'star_burst', 'confetti_burst'):
            setattr(p, name, Mock())
        p._shocks = []
        return p

    def test_dance_feet_land_on_beat_and_finale(self):
        for beat in (.4, .43, .46):
            for i in range(14):
                self.assertAlmostEqual(pet.Pet._dance_motion((i + .9)*beat, beat, 1)[0], 0)
            self.assertGreater(pet.Pet._dance_motion(14.7*beat, beat, 1)[0], 20)
            self.assertAlmostEqual(pet.Pet._dance_motion(15.15*beat, beat, 1)[0], 0)

    def test_finale_once_after_touchdown_at_different_fps(self):
        for fps in (10, 30, 60):
            p = self.make_pet()
            with patch.object(pet.time, 'time', return_value=100):
                p.start_dance()
            for i in range(int(7.5 * fps)):
                age = i / fps
                p._advance_dance(100 + age)
                if age < 15.15*p.dance_beat:
                    p.land_fx.assert_not_called()
            p.land_fx.assert_called_once_with(.8)
            self.assertAlmostEqual(p.x, 400.)
            self.assertEqual(p.hop_t, 0)

    def test_long_frame_does_not_replay_all_dance_pulses(self):
        p = self.make_pet()
        with patch.object(pet.time, 'time', return_value=100):
            p.start_dance()
        p._advance_dance(100 + 10*p.dance_beat)
        self.assertEqual(len(p._shocks), 1)
        p._advance_dance(100 + 10*p.dance_beat)
        self.assertEqual(len(p._shocks), 1)

    def test_roll_distance_and_direction_are_frame_independent(self):
        for scale in (.7, 1., 1.5):
            for side in (-1, 1):
                self.assertEqual(pet.Pet._roll_offset(.3, side, scale), 0)
                values = []
                for fps in (10, 30, 60):
                    samples = [pet.Pet._roll_offset(i/fps, side, scale) for i in range(3*fps+1)]
                    self.assertTrue(all(side*(b-a) >= -1e-8 for a, b in zip(samples, samples[1:])))
                    values.append(samples[-1])
                for distance in values:
                    self.assertAlmostEqual(distance, side*114*scale)

    def test_rotated_roll_visible_contour_stays_on_ground(self):
        resting = Image.new('RGBA', (120, 160))
        ImageDraw.Draw(resting).rectangle((20, 65, 95, 150), fill=(255, 200, 100, 255))
        ground = 200
        expected = ground - (resting.height - resting.getbbox()[3])
        for angle in range(0, 361, 30):
            sprite = resting.rotate(angle, expand=True)
            top = ground - sprite.height + pet.Pet._roll_ground_offset(sprite, resting)
            self.assertEqual(top + sprite.getbbox()[3], expected)
        self.assertEqual(pet.Pet._roll_ground_offset(resting, resting), 0)
        self.assertEqual(pet.Pet._roll_ground_offset(Image.new('RGBA', (10, 10)), resting), 0)

    def test_stretch_is_bounded_and_returns_to_neutral(self):
        p = self.make_pet()
        with patch.object(pet.time, 'time', return_value=100):
            p.start_stretch()
        for i in range(230):
            squash = p._track(i/60, p._tl_tracks['squash'])
            self.assertTrue(.9 <= squash <= 1.12)
        self.assertEqual(p._track(3.8, p._tl_tracks['squash']), 1)
        self.assertEqual(p._track(3.8, p._tl_tracks['_bend']), 0)


class EverydayMotionTests(unittest.TestCase):
    def test_sleep_tint_preserves_character_opacity_and_transparent_margin(self):
        sprite = Image.new('RGBA', (20, 20))
        ImageDraw.Draw(sprite).rectangle((5, 5, 15, 15), fill=(230, 210, 200, 255))
        for strength in (16, 28, 40):
            result = Image.alpha_composite(sprite, pet.Pet._sleep_shade(sprite, strength))
            self.assertEqual(result.getpixel((10, 10))[3], 255)
            self.assertEqual(result.getpixel((0, 0))[3], 0)
            self.assertGreater(result.getpixel((10, 10))[0], 190)

    def test_candy_arrives_at_mouth_and_disappears(self):
        self.assertEqual(pet.Pet._candy_path(0), (.9, .7, 0))
        x, y, size = pet.Pet._candy_path(1.1)
        self.assertAlmostEqual(x, .487)
        self.assertAlmostEqual(y, .55)
        self.assertEqual(size, 0)
        for age in (-1, 1.2, 2.2, 10):
            self.assertEqual(pet.Pet._candy_path(age)[2], 0)
        for fps in (10, 30, 60):
            samples = [pet.Pet._candy_path(i/fps) for i in range(fps+1)]
            self.assertTrue(all(b[0] <= a[0] for a, b in zip(samples, samples[1:])))
            self.assertTrue(all(0 <= row[2] <= 1 for row in samples))

    def test_eating_recovers_after_long_frame(self):
        p = pet.Pet.__new__(pet.Pet)
        for age in (0, 2.2, 3, 20):
            self.assertEqual(p._eat_pose(age), (1, 0))
        for i in range(133):
            squash, bend = p._eat_pose(i/60)
            self.assertTrue(.96 <= squash <= 1.04)
            self.assertTrue(-.04 <= bend <= .11)

    def test_yawn_settles_to_sleep_without_squash_jump(self):
        p = pet.Pet.__new__(pet.Pet)
        self.assertEqual(p._yawn_pose(0), (1, 0))
        self.assertEqual(p._yawn_pose(1.6), (1, -.06))
        self.assertEqual(p._yawn_pose(10), (1, -.06))

    def test_wake_stretch_cancelled_by_new_interaction_or_action(self):
        p = pet.Pet.__new__(pet.Pet)
        p.state, p.state_until, p.last_interact = 'idle', 103, 90
        p._micro_motion = None
        p._micro_allowed, p.start_stretch = Mock(return_value=True), Mock()
        p._finish_wake(103, 90)
        p.start_stretch.assert_called_once()
        p.start_stretch.reset_mock()
        for attr, value in (('last_interact', 91), ('state_until', 106),
                            ('state', 'eat'), ('_micro_motion', ('nuzzle', 0))):
            old = getattr(p, attr)
            setattr(p, attr, value)
            p._finish_wake(103, 90)
            p.start_stretch.assert_not_called()
            setattr(p, attr, old)
        p._micro_allowed.return_value = False
        p._finish_wake(103, 90)
        p.start_stretch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
