"""动作时序、打断和特效边界回归,不启动桌宠或触碰存档。"""
import json
import os
import threading
import unittest
from collections import OrderedDict
from unittest.mock import Mock, patch
from PIL import Image, ImageDraw
import pet
import fx
import life


class ActionTests(unittest.TestCase):
    def make_pet(self):
        p = pet.Pet.__new__(pet.Pet)
        p._core_edition = False  # Explicit retired-engine compatibility fixture.
        p._seat_guard = Mock(return_value=False)  # These fixtures represent the old standing art.
        p.state, p._swing, p.drag = 'idle', None, None
        p.state, p.fy, p.ground_feet = 'idle', 800., 800.
        p.W, p.H = 540, 650          # 特效位置按窗口比例换算,壳桌宠也得有尺寸
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
        p._core_edition = False  # Explicit retired-engine compatibility fixture.
        p._seat_guard = Mock(return_value=False)  # These fixtures represent the old standing art.
        p.state, p._swing, p.drag = 'idle', None, None
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
        p._core_edition = False  # Explicit retired-engine compatibility fixture.
        p._seat_guard = Mock(return_value=False)  # These fixtures represent the old standing art.
        p.state, p._swing, p.drag = 'idle', None, None
        for age in (0, 2.2, 3, 20):
            self.assertEqual(p._eat_pose(age), (1, 0))
        for i in range(133):
            squash, bend = p._eat_pose(i/60)
            self.assertTrue(.96 <= squash <= 1.04)
            self.assertTrue(-.04 <= bend <= .11)

    def test_yawn_settles_to_sleep_without_squash_jump(self):
        p = pet.Pet.__new__(pet.Pet)
        p._core_edition = False  # Explicit retired-engine compatibility fixture.
        p._seat_guard = Mock(return_value=False)  # These fixtures represent the old standing art.
        p.state, p._swing, p.drag = 'idle', None, None
        self.assertEqual(p._yawn_pose(0), (1, 0))
        self.assertEqual(p._yawn_pose(1.6), (1, -.06))
        self.assertEqual(p._yawn_pose(10), (1, -.06))

    def test_wake_stretch_cancelled_by_new_interaction_or_action(self):
        p = pet.Pet.__new__(pet.Pet)
        p._core_edition = False  # Explicit retired-engine compatibility fixture.
        p._seat_guard = Mock(return_value=False)  # These fixtures represent the old standing art.
        p.state, p._swing, p.drag = 'idle', None, None
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


class LivelinessTests(unittest.TestCase):
    """动态感一组(E20~E23):法阵呼吸光/光纹、命中光环、蹦跳、冥想星核。"""

    @classmethod
    def setUpClass(cls):
        cls.layer = fx.FX(1, 2)

    def blank(self):
        im = Image.new('RGBA', (900, 400), (26, 24, 40, 255))
        return im, ImageDraw.Draw(im)

    def test_frame_path_never_filters_or_rotates(self):
        # 铁律:新特效每帧只准贴图。把滤镜/旋转/缩放全换成炸弹再调一遍。
        layer = self.layer
        boom = AssertionError('帧循环里不许做滤镜/旋转/缩放')
        with patch.object(Image.Image, 'filter', side_effect=boom), \
                patch.object(Image.Image, 'rotate', side_effect=boom), \
                patch.object(Image.Image, 'resize', side_effect=boom), \
                patch.object(fx.ImageFilter, 'GaussianBlur', side_effect=boom):
            im, d = self.blank()
            for i in range(20):
                u = i / 19
                layer.ground_circle(im, d, 450, 300, 10 + i * .05, 0, breath=u)
                layer.ground_ripple(im, 450, 300, u)
                layer.hit_ring(im, 300, 120, u, 'pink')
                layer.hit_ring(im, 600, 120, u, 'gold')
                layer.orb(im, 450, 150, 'near', u)
                layer.orb(im, 450, 150, 'far', u)

    def test_sprites_are_prebuilt_with_expected_steps(self):
        layer = self.layer
        self.assertEqual(len(layer.breath), layer.BREATH_STEPS)
        self.assertIsNone(layer.breath[0])          # 最暗一档不贴
        self.assertEqual(len(layer.ripple), layer.RIPPLE_STEPS)
        for name in ('gold', 'pink'):
            self.assertEqual(len(layer.hit[name]), layer.HIT_STEPS)
        for side in ('near', 'far'):
            self.assertEqual(len(layer.orbs[side]), layer.ORB_STEPS)

    def test_breath_and_ripple_draw_only_when_active(self):
        layer = self.layer

        def circle(**kw):
            im, d = self.blank()
            layer._circle_time = None
            layer._orbit_spin = layer._bead_spin = 0.
            layer.ground_circle(im, d, 450, 300, 1., 0, **kw)
            return im

        plain = circle().tobytes()
        self.assertEqual(circle(breath=0).tobytes(), plain)
        self.assertNotEqual(circle(breath=1).tobytes(), plain)
        for p in (-.1, 1., 1.7):
            im, _ = self.blank()
            before = im.tobytes()
            layer.ground_ripple(im, 450, 300, p)
            self.assertEqual(im.tobytes(), before, p)
        im, _ = self.blank()
        before = im.tobytes()
        layer.ground_ripple(im, 450, 300, .5)
        self.assertNotEqual(im.tobytes(), before)

    def test_hit_ring_range_and_palette_fallback(self):
        layer = self.layer
        for p in (-.01, 1., 2.):
            im, _ = self.blank()
            before = im.tobytes()
            layer.hit_ring(im, 450, 200, p)
            self.assertEqual(im.tobytes(), before)
        a, _ = self.blank()
        b, _ = self.blank()
        layer.hit_ring(a, 450, 200, .2, 'no-such-palette')
        layer.hit_ring(b, 450, 200, .2, 'gold')
        self.assertEqual(a.tobytes(), b.tobytes())

    def test_hit_ring_is_a_show_particle_not_ambient(self):
        # 它是互动瞬间的演出,允许短暂顶到 60fps;但绝不能混进氛围集合,
        # 否则 0.38 秒后没人管它、安静档判定也不会把它当"在动"
        self.assertNotIn('hit_ring', pet.AMBIENT_PARTS)
        self.assertLess(pet.HIT_RING_LIFE, .5)

    def test_hop_starts_and_ends_on_ground_with_whole_bounces(self):
        for amp in (.4, .5, .7, .8, .95):
            p = pet.Pet.__new__(pet.Pet)
            p._core_edition = False  # Explicit retired-engine compatibility fixture.
            p._seat_guard = Mock(return_value=False)  # These fixtures represent the old standing art.
            p.state, p._swing, p.drag = 'idle', None, None
            p.hop(amp)
            total = p._hop_total
            self.assertEqual(p.hop_t, total)
            self.assertEqual(p.squash, .9)
            n = round((total - pet.HOP_CROUCH) / pet.HOP_PERIOD)
            self.assertAlmostEqual(total, pet.HOP_CROUCH + n * pet.HOP_PERIOD)
            curve = pet.Pet._hop_curve
            self.assertEqual(curve(0, total, amp), 0)                 # 不再凭空瞬移
            self.assertEqual(curve(pet.HOP_CROUCH * .9, total, amp), 0)
            self.assertEqual(curve(total, total, amp), 0)             # 不再半空掉落
            peaks = [curve(pet.HOP_CROUCH + (j + .5) * pet.HOP_PERIOD, total, amp)
                     for j in range(n)]
            self.assertAlmostEqual(peaks[0], 5 + 10 * amp)          # 峰值手感不变
            self.assertTrue(all(a > b for a, b in zip(peaks, peaks[1:])))
            for j in range(1, n):                                    # 每跳真的触地
                self.assertAlmostEqual(
                    curve(pet.HOP_CROUCH + j * pet.HOP_PERIOD + 1e-9, total, amp), 0,
                    places=5)

    def test_hop_touchdown_count_is_frame_rate_independent(self):
        total = pet.HOP_CROUCH + 4 * pet.HOP_PERIOD
        for fps in (10, 20, 30, 60):
            hits, age = 0, 0.
            while age < total + .2:
                nxt = age + 1 / fps
                hits += pet.Pet._hop_touchdown(age, nxt, total)
                age = nxt
            self.assertEqual(hits, 4, fps)

    def test_meditate_arms_depth_and_orb_fade(self):
        for i in range(50):
            t2 = .8 + i * .08
            arms = pet.Pet._meditate_arms(t2, 500, 600, 30)
            self.assertEqual(len(arms), 3)
            sides = [a[2] for a in arms]
            self.assertIn(sides.count('near'), (1, 2))
            for x, y, side, a in arms:
                self.assertEqual(side == 'near', pet.math.sin(a) > 0)
        vis = pet.Pet._meditate_orb_vis
        self.assertEqual(vis(.5), 0)
        self.assertEqual(vis(5.2), 0)
        self.assertEqual(vis(2.5), 1)
        self.assertTrue(0 < vis(1.0) < 1 and 0 < vis(4.7) < 1)


class LivelinessRound2Tests(unittest.TestCase):
    """动态感第二批(E25~E28):星光飘字、光标感应、抛飞拖尾、抓取光环。"""

    @classmethod
    def setUpClass(cls):
        cls.layer = fx.FX(1, 2)
        cls.layer.build_gain_glyphs(pet.load_font(34))

    def test_gain_glyphs_prebuilt_and_frame_path_only_pastes(self):
        layer = self.layer
        for ch in layer.GAIN_CHARS + '*':
            self.assertEqual(len(layer.gain[ch]), layer.GAIN_ALPHA)
        boom = AssertionError('飘字每帧只准贴预渲染字形')
        im = Image.new('RGBA', (600, 300), (26, 24, 40, 255))
        with patch.object(Image.Image, 'filter', side_effect=boom), \
                patch.object(Image.Image, 'rotate', side_effect=boom), \
                patch.object(Image.Image, 'resize', side_effect=boom), \
                patch.object(ImageDraw.ImageDraw, 'text', side_effect=boom), \
                patch.object(fx.ImageFilter, 'GaussianBlur', side_effect=boom):
            for i in range(12):
                layer.gain_text(im, 300, 150, '+%d*' % (i * 7), (i + 1) / 12)

    def test_gain_text_noop_cases(self):
        im = Image.new('RGBA', (400, 200), (26, 24, 40, 255))
        blank = im.tobytes()
        self.layer.gain_text(im, 200, 100, '+5*', 0)             # 完全透明档
        self.layer.gain_text(im, 200, 100, '', 1)                # 空串
        self.layer.gain_text(im, 200, 100, '??', 1)              # 没有字形的字符
        fresh = fx.FX(1, 1)                                      # 还没预热字形
        fresh.gain_text(im, 200, 100, '+5*', 1)
        self.assertEqual(im.tobytes(), blank)
        self.layer.gain_text(im, 200, 100, '+5*', 1)
        self.assertNotEqual(im.tobytes(), blank)

    def test_gain_is_a_show_particle(self):
        self.assertNotIn('gain', pet.AMBIENT_PARTS)
        self.assertLess(pet.GAIN_LIFE, 1.2)

    def test_prox_target_clamps_and_is_monotonic(self):
        f = pet.Pet._prox_target
        self.assertEqual(f(0), 1)
        self.assertEqual(f(pet.PROX_NEAR), 1)
        self.assertEqual(f(pet.PROX_FAR), 0)
        self.assertEqual(f(5000), 0)
        vals = [f(d) for d in range(0, 400, 10)]
        self.assertTrue(all(a >= b for a, b in zip(vals, vals[1:])))


class LivelinessRound3Tests(unittest.TestCase):
    """动态感第三批(E29~E31):落地冲击、飞行速度线、喷气团。"""

    def test_puff_prebuilt_and_frame_path_only_pastes(self):
        layer = fx.FX(1, 2)
        self.assertEqual(len(layer.puff), layer.PUFF_STEPS)
        boom = AssertionError('喷气团每帧只准贴图')
        im = Image.new('RGBA', (500, 300), (26, 24, 40, 255))
        with patch.object(Image.Image, 'filter', side_effect=boom), \
                patch.object(Image.Image, 'rotate', side_effect=boom), \
                patch.object(Image.Image, 'resize', side_effect=boom), \
                patch.object(fx.ImageFilter, 'GaussianBlur', side_effect=boom):
            for i in range(12):
                layer.puff_at(im, 250, 150, i / 12)
        blank = Image.new('RGBA', (500, 300), (26, 24, 40, 255))
        for p in (-.1, 1., 3.):
            layer.puff_at(blank, 250, 150, p)
        self.assertEqual(blank.tobytes(), Image.new('RGBA', (500, 300), (26, 24, 40, 255)).tobytes())
        self.assertNotIn('puff', pet.AMBIENT_PARTS)

    def test_landing_strength_clamps_and_grows_with_speed(self):
        f = pet.Pet._landing_strength
        self.assertEqual(f(0), .35)
        self.assertEqual(f(1100), 1)
        self.assertEqual(f(9000), 1)
        vals = [f(v) for v in range(0, 1400, 50)]
        self.assertTrue(all(a <= b for a, b in zip(vals, vals[1:])))

    def shell(self, vx, vy):
        p = pet.Pet.__new__(pet.Pet)
        p._core_edition = False  # Explicit retired-engine compatibility fixture.
        p._seat_guard = Mock(return_value=False)  # These fixtures represent the old standing art.
        p.state, p._swing, p.drag = 'idle', None, None
        p.vx, p.vy, p.W, p.scale = vx, vy, 540, 1.0
        return p

    def test_speed_lines_only_when_fast_and_always_behind(self):
        self.assertEqual(self.shell(200, -100)._speed_line_specs(10.0), [])
        for vx, vy in ((-1300, -900), (900, 0), (0, 1200), (700, 700)):
            specs = self.shell(vx, vy)._speed_line_specs(10.0)
            self.assertEqual(len(specs), 7)
            for (x0, y0), (x1, y1), a in specs:
                # 起笔在身后(和速度方向相反),线段也朝身后延伸
                self.assertLess(x0 * vx + y0 * vy, 0)
                self.assertLess((x1 - x0) * vx + (y1 - y0) * vy, 0)
                self.assertTrue(0 < a <= 255)

    def test_speed_lines_grow_with_speed_and_are_stable_within_a_slot(self):
        def mean_len(sp):
            specs = self.shell(-sp, 0)._speed_line_specs(10.0)
            return sum(abs(x1 - x0) for (x0, _), (x1, _), _ in specs) / len(specs)
        self.assertLess(mean_len(500), mean_len(1300))
        p = self.shell(-1000, -300)
        self.assertEqual(p._speed_line_specs(10.01), p._speed_line_specs(10.04))   # 同一 50ms 片


class HatOrbitTests(unittest.TestCase):
    """帽檐星轨(E34)。"""

    def test_sprites_prebuilt_and_frame_path_only_pastes(self):
        layer = fx.FX(1, 2)
        for name in ('planet', 'moon', 'crystal'):
            self.assertEqual(len(layer.orbit[name]), layer.ORBIT_DEPTH)
        self.assertEqual(len(layer.orbit_dots), layer.ORBIT_DOT_STEPS)
        boom = AssertionError('星轨每帧只准贴图')
        im = Image.new('RGBA', (600, 400))
        with patch.object(Image.Image, 'filter', side_effect=boom), \
                patch.object(Image.Image, 'rotate', side_effect=boom), \
                patch.object(Image.Image, 'resize', side_effect=boom), \
                patch.object(fx.ImageFilter, 'GaussianBlur', side_effect=boom):
            for i in range(12):
                layer.orbit_body(im, 300, 200, ('planet', 'moon', 'crystal')[i % 3], i / 11)
                layer.orbit_dot(im, 300, 200, i / 11)

    def test_layout_shape_depth_and_periodicity(self):
        lay = pet.Pet._hat_orbit_layout
        items = lay(3.7)
        n_bodies = len(pet.HAT_ORBIT_BODIES)
        self.assertEqual(len(items), pet.HAT_ORBIT_PATH + n_bodies * (pet.HAT_ORBIT_TRAIL + 1))
        names = [it[0] for it in items if it[0] not in (None, 'path')]
        self.assertEqual(sorted(names), sorted(b[0] for b in pet.HAT_ORBIT_BODIES))
        for name, nx, ny, depth, near, level in items:
            self.assertTrue(0 <= depth <= 1)
            self.assertEqual(near, depth > .5)
        # 轨道虚点不随时间动;每颗天体过一个自己的周期回到原位
        self.assertEqual([it for it in lay(0) if it[0] == 'path'],
                         [it for it in lay(123.4) if it[0] == 'path'])
        for name, _, period, _ in pet.HAT_ORBIT_BODIES:
            a = next(it for it in lay(2.0) if it[0] == name)
            b = next(it for it in lay(2.0 + period) if it[0] == name)
            self.assertAlmostEqual(a[1], b[1], places=6)
            self.assertAlmostEqual(a[2], b[2], places=6)

    def test_spin_follows_mood_of_the_state(self):
        f = pet.Pet._orbit_spin_target
        self.assertEqual(f('idle'), 1.0)
        self.assertEqual(f('sleep'), 0.0)
        self.assertEqual(f('tstop'), 0.0)        # 时停:星星也停
        self.assertLess(f('rewind'), 0)          # 回溯:倒着转
        self.assertGreater(f('magic'), 1.0)

    def test_rotate_about_matches_pil_rotate(self):
        im = Image.new('RGBA', (101, 101))
        ImageDraw.Draw(im).rectangle([85, 48, 90, 52], fill=(255, 0, 0, 255))
        for angle in (90, -40, 135):
            r = im.rotate(angle, expand=True)
            bb = r.getbbox()
            got = ((bb[0] + bb[2]) / 2 - r.width / 2, (bb[1] + bb[3]) / 2 - r.height / 2)
            want = pet.Pet._rotate_about(87.5 - 50.5, 50 - 50.5, angle)
            self.assertAlmostEqual(got[0], want[0], delta=1.5)
            self.assertAlmostEqual(got[1], want[1], delta=1.5)

    def test_follow_is_zero_at_rest_and_leans_with_the_hat(self):
        f = pet.Pet._orbit_follow
        self.assertEqual(f(300, 100, 600, 700, 0, 1, 0), (0.0, 0.0))
        dx, dy = f(300, 100, 600, 700, .115, 1, 0)
        self.assertGreater(dx, 0)                # 实测:倾斜 0.115 帽子往 +x 挪约 30px
        self.assertAlmostEqual(dy, 0)
        dx2, _ = f(300, 100, 600, 700, -.115, 1, 0)
        self.assertAlmostEqual(dx2, -dx)


class LegLayerRenderTests(unittest.TestCase):
    """腿层切出底图以后的整帧渲染(无窗口:壳桌宠 + 真素材,推帧换成 Mock)。"""

    def make_pet(self):
        paths = [os.path.join(pet.ASSETS, f'legs_{s}.{ext}')
                 for s in 'lr' for ext in ('png', 'meta')]
        if not all(os.path.exists(pth) for pth in paths):
            self.skipTest('没有腿层素材')
        p = pet.Pet.__new__(pet.Pet)
        p._core_edition = False  # Explicit retired-engine compatibility fixture.
        p._seat_guard = Mock(return_value=False)  # These fixtures represent the old standing art.
        p.state, p._swing, p.drag = 'idle', None, None
        p.root, p.scale = Mock(), 1.0
        p.W, p.H = int(pet.BASE_W * p.scale), int(pet.BASE_H * p.scale)
        p.main_src = Image.open(os.path.join(pet.ASSETS, 'main.png')).convert('RGBA')
        p.hat_src = p.hair_src = None
        p.hair_off = (0, 0)
        for side in 'lr':
            with open(os.path.join(pet.ASSETS, f'legs_{side}.meta')) as f:
                bb = json.load(f)['bbox']
            setattr(p, f'legs{side}_src', Image.open(
                os.path.join(pet.ASSETS, f'legs_{side}.png')).convert('RGBA'))
            setattr(p, f'legs{side}_off', (bb[0], bb[1]))
        p._warp_cache, p._legs_warp_cache = OrderedDict(), OrderedDict()
        p._hat_warp_cache, p._hair_warp_cache = OrderedDict(), OrderedDict()
        p.glow_cache, p._expr_rs = OrderedDict(), OrderedDict()
        p._castfx_lock, p.decors_meta, p._text_warm_scheduled = threading.Lock(), [], True
        p.rebuild_scale_cache()
        p.state, p.x, p.fy, p.ground_feet, p.cfg = 'idle', 600.0, 800.0, 800.0, {}
        p.hop_t = p.lean = p._drag_lean = p._bend = p.look_x = p.look_y = 0.0
        p.squash, p.drag, p.life = 1.0, None, life.LifeMotion()
        p.t0 = p._life_prev_t = p._life_prev_bob = p.blink_until = 0.0
        p._spin_rot = p._spin_lift = p._prox = p.snow_ground = 0.0
        p._micro_motion = p.sticker = p.bubble = None
        p._afters, p.circles, p._shocks, p.parts = [], [], [], []
        p.hat_orbit = p.singing = p.thinking_now = p.selftest = p.ai_lights = False
        p._push = Mock()
        return p

    def test_roll_ground_reference_includes_leg_layers(self):
        """打滚贴地的参照必须是叠好腿层、还没旋转的合成图。原来拿只有底图
        的 warped 当参照:切腿后底图可见下沿比脚高 56 原画 px,一进 roll
        (还没开始转)整只就往上一跳,滚完再掉回地面。"""
        p = self.make_pet()
        seen = []
        real = pet.Pet._roll_ground_offset

        def spy(sprite, resting):
            got = real(sprite, resting)
            seen.append((sprite.getbbox(), resting.getbbox(), got))
            return got
        p.state, now = 'roll', 1000.0
        with patch.object(pet.Pet, '_roll_ground_offset', staticmethod(spy)):
            p.render(now, now - p.t0)
            p._spin_rot = -90.0
            p.render(now, now - p.t0)
        (upright, ref0, off0), (_, ref90, _) = seen
        self.assertEqual(off0, 0)             # 没转就不该挪
        self.assertEqual(ref0, upright)       # 参照 = 贴上去的那张合成图
        self.assertEqual(ref90, upright)      # 转起来以后仍按直立合成图贴地

    def test_leg_layer_cache_ignores_face_and_sway(self):
        """腿层变形不吃五官贴图、也不吃帽/发/裙摆的 sway:眨眼和弹簧台阶
        只该重变形底图(原来腿层键里塞了整个 wkey,每次白变形两条腿)。"""
        p = self.make_pet()
        calls = []
        real = p.warper.warp

        def counting(*a, **kw):
            calls.append('legs' if kw.get('leg_bend') else 'base')
            return real(*a, **kw)
        p.warper.warp = counting
        now = 1000.0
        p.render(now, now - p.t0)
        p.render(now, now - p.t0)             # 同一时刻再来一帧:全部命中
        self.assertEqual(calls, ['base', 'legs', 'legs'])
        calls.clear()
        p.blink_until = now + 1.0             # 眨眼:只换脸
        p.render(now, now - p.t0)
        self.assertEqual(calls, ['base'])
        calls.clear()
        p.life.hem.x += 1.5                   # 裙摆弹簧走了一个台阶
        p.render(now, now - p.t0)
        self.assertEqual(calls, ['base'])
        calls.clear()
        p.lean = 0.05                         # 腿真正用到的输入变了才重变形
        p.render(now, now - p.t0)
        self.assertEqual(calls, ['base', 'legs', 'legs'])
        self.assertLessEqual(len(p._legs_warp_cache), 12)


if __name__ == '__main__':
    unittest.main()
