"""喷嚏、眩晕与站起时序回归;不创建真实桌宠或访问存档。"""
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from pet import Pet


class RecoveryTests(unittest.TestCase):
    def make_pet(self, scale=1):
        p = Pet.__new__(Pet)
        p._core_edition = False  # Explicit retired-engine compatibility fixture.
        p.state, p.squash, p.lean, p.look_x = 'idle', 1, .02, .1
        p.scale, p.W, p.H, p.FOOT_Y = scale, 400*scale, 500*scale, 470*scale
        p.fy = p.ground_feet = 800
        p.sfx = Mock()
        p.say, p.play_emotion, p.star_burst, p.add_part = (Mock() for _ in range(4))
        p._shocks = []
        return p

    def test_sneeze_one_burst_and_same_pose_at_all_frame_rates(self):
        samples = []
        for fps in (10, 30, 60):
            p = self.make_pet()
            with patch('pet.time.time', return_value=100):
                p.start_sneeze()
            for i in range(25*fps//10+1):
                age = i/fps
                p._advance_sneeze(100+age)
                self.assertTrue(.83 <= p.squash <= 1.08)
                self.assertLessEqual(abs(p.lean), .141)
                if i == fps//2:
                    samples.append((p.squash, p.lean, p._bend))
            p.star_burst.assert_called_once()
            self.assertGreater(p.star_burst.call_args.args[1], .1*p.H)
            self.assertEqual(p.state, 'idle')
            self.assertEqual((p.squash, p.lean, p._bend), (1, 0, 0))
        self.assertEqual(samples[0], samples[1])
        self.assertEqual(samples[1], samples[2])

    def test_long_frame_skips_expired_sneeze_burst(self):
        p = self.make_pet()
        with patch('pet.time.time', return_value=100):
            p.start_sneeze()
        p._advance_sneeze(100.8)
        p._advance_sneeze(103)
        p._advance_sneeze(104)
        p.star_burst.assert_not_called()
        self.assertEqual(p.say.call_count, 2)
        self.assertEqual(p.state, 'idle')

    def test_sneeze_replacement_owns_its_own_burst(self):
        p = self.make_pet()
        with patch('pet.time.time', return_value=100):
            p.start_sneeze()
        p._advance_sneeze(100.7)
        previous = (p.squash, p.lean)
        with patch('pet.time.time', return_value=100.7):
            p.start_sneeze()
        p._advance_sneeze(100.7)
        self.assertEqual((p.squash, p.lean), previous)
        p._advance_sneeze(101)
        p.star_burst.assert_not_called()
        p._advance_sneeze(101.7)
        p.star_burst.assert_called_once()

    def test_interruption_does_not_restore_action_or_emit_effects(self):
        for start, advance in (('start_sneeze', '_advance_sneeze'),
                               ('go_dizzy', '_advance_dizzy')):
            p = self.make_pet()
            with patch('pet.time.time', return_value=100):
                getattr(p, start)()
            p.say.reset_mock()
            p.state = 'sleep'
            p.squash, p.lean = .99, .01
            getattr(p, advance)(104)
            self.assertEqual((p.state, p.squash, p.lean), ('sleep', .99, .01))
            p.say.assert_not_called()
            p.star_burst.assert_not_called()

    def test_dizzy_duration_and_settling_at_all_scales_and_frame_rates(self):
        for scale in (.8, 1, 1.75):
            for fps in (10, 30, 60):
                p = self.make_pet(scale)
                with patch('pet.time.time', return_value=100):
                    p.go_dizzy()
                p._advance_dizzy(100)
                self.assertAlmostEqual(p.lean, .02)
                self.assertAlmostEqual(p.look_x, .1)
                for i in range(3*fps+1):
                    p._advance_dizzy(100+i/fps)
                    self.assertLessEqual(abs(p.lean), .151)
                    self.assertTrue(.97 <= p.squash <= 1)
                self.assertEqual(p.state, 'idle')
                self.assertEqual((p.lean, p._bend, p.squash, p.dizzy_amp), (0, 0, 1, 0))
                self.assertEqual(p.say.call_count, 2)
                self.assertEqual(p.add_part.call_count, 6)
                for call in p.add_part.call_args_list:
                    self.assertGreaterEqual(abs(call.args[1]), .26*p.W)

    def test_dizzy_long_frame_finishes_once(self):
        p = self.make_pet()
        with patch('pet.time.time', return_value=100):
            p.go_dizzy()
        p._advance_dizzy(100.2)
        p._advance_dizzy(120)
        p._advance_dizzy(121)
        self.assertEqual(p.say.call_count, 2)
        self.assertEqual(p.dizzy_amp, 0)

    def test_stand_has_pause_rebound_and_neutral_finish(self):
        p = self.make_pet()
        with patch('pet.time.time', return_value=100):
            p.start_fall()
        self.assertEqual(len(p._shocks), 1)
        self.assertEqual(p.state_until, 101.2)
        self.assertLess(Pet._stand_pose(.15)[0], .81)
        self.assertGreater(Pet._stand_pose(.58)[0], 1)
        for fps in (10, 30, 60):
            for i in range(2*fps):
                squash, lean, bend = Pet._stand_pose(i/fps)
                self.assertTrue(.78 <= squash <= 1.035)
                self.assertLessEqual(abs(bend), .121)
            self.assertEqual(Pet._stand_pose(2), (1, 0, 0))

    def test_drag_cancels_sneeze_and_standing(self):
        for state in ('sneeze', 'fall_stand'):
            p = self.make_pet()
            p.state, p.x = state, 100
            p.drag = (0, 0, 100, 800, False, 100)
            p._cancel_ball, p._clamp_pos = Mock(), Mock()
            p._drag_trail, p._shake_dirs = [], []
            p._shake_cd = 200
            with patch('pet.time.time', return_value=100):
                p.on_drag(SimpleNamespace(x_root=10, y_root=0))
            self.assertEqual(p.state, 'idle')


class SfxThreadTests(unittest.TestCase):
    """音效的 MCI 调用挪到专用音频线程(E36):UI 线程只做限频判断。"""

    def make_sfx(self, calls, delay=0.0):
        import threading
        import time
        import pet

        def fake_mci(c):
            calls.append((threading.current_thread().name, c.split()[0]))
            if delay and c.startswith(('open', 'play')):
                time.sleep(delay)
            return (0, '80') if c.startswith('status') else (0, '')

        patcher = patch.object(pet, 'mci', fake_mci)
        patcher.start()
        self.addCleanup(patcher.stop)
        root = SimpleNamespace(after=Mock(side_effect=AssertionError('音频线程不该碰 Tk')))
        sfx = pet.SFX(root)
        if not sfx.groups:
            self.skipTest('assets/audio 不在')
        self.addCleanup(lambda: sfx._q.put(('stop',)))
        return sfx, next(iter(sfx.groups))

    def test_play_returns_immediately_even_if_mci_is_slow(self):
        import time
        calls = []
        sfx, name = self.make_sfx(calls, delay=0.25)
        t0 = time.perf_counter()
        self.assertTrue(sfx.play(name))
        self.assertLess(time.perf_counter() - t0, 0.05)     # 原来要串行等 open+play
        time.sleep(1.0)
        self.assertEqual([c for _, c in calls][:3], ['open', 'play', 'status'])
        self.assertTrue(all(th == 'pet-sfx' for th, _ in calls))

    def test_clip_is_closed_after_its_length_on_the_audio_thread(self):
        import time
        calls = []
        sfx, name = self.make_sfx(calls)
        sfx.play(name)
        time.sleep(0.2)
        self.assertNotIn('close', [c for _, c in calls])    # 80ms 长度 + 0.5s 余量还没到
        time.sleep(0.7)
        self.assertIn(('pet-sfx', 'close'), calls)
        self.assertEqual(sfx._chan, {})

    def test_throttle_is_unchanged_and_close_all_waits(self):
        import time
        calls = []
        sfx, name = self.make_sfx(calls)
        self.assertTrue(sfx.play(name))
        self.assertFalse(sfx.play(name))                   # 全局 5 秒限频照旧
        sfx.enabled = False
        sfx._next_any = 0
        sfx._next = {}
        self.assertFalse(sfx.play(name))                   # 总开关照旧
        sfx.enabled = True
        time.sleep(0.2)
        sfx.close_all()
        self.assertEqual(sfx._chan, {})


class SongThreadTests(unittest.TestCase):
    """唱歌也走音频线程,并遵守「语音(全部声音)」总开关(E38)。"""

    def make_sfx(self, calls, delay=0.0):
        import threading
        import time
        import pet

        def fake_mci(c):
            calls.append((threading.current_thread().name, c.split()[0]))
            if delay and c.startswith(('open', 'play')):
                time.sleep(delay)
            return (0, 'playing') if c.startswith('status') else (0, '')

        patcher = patch.object(pet, 'mci', fake_mci)
        patcher.start()
        self.addCleanup(patcher.stop)
        sfx = pet.SFX(SimpleNamespace(after=Mock(side_effect=AssertionError('音频线程不该碰 Tk'))))
        self.addCleanup(lambda: sfx._q.put(('stop',)))
        return sfx

    def test_song_starts_on_audio_thread_without_blocking(self):
        import time
        calls = []
        sfx = self.make_sfx(calls, delay=0.25)
        t0 = time.perf_counter()
        self.assertTrue(sfx.play_song('x.mp3'))
        self.assertLess(time.perf_counter() - t0, 0.05)      # 旧实现同步 open+play 要 290~490ms
        time.sleep(0.9)
        self.assertEqual([c for _, c in calls][:3], ['open', 'setaudio', 'play'])
        self.assertTrue(all(th == 'pet-sfx' for th, _ in calls))
        self.assertTrue(sfx.song_playing)
        sfx.stop_song()
        time.sleep(0.3)
        self.assertFalse(sfx.song_playing)
        self.assertIn('close', [c for _, c in calls])

    def test_song_respects_the_sound_switch(self):
        import time
        calls = []
        sfx = self.make_sfx(calls)
        sfx.enabled = False
        self.assertFalse(sfx.play_song('x.mp3'))
        time.sleep(0.2)
        self.assertEqual([c for _, c in calls if c in ('open', 'play')], [])
        self.assertFalse(sfx.song_playing)


class DeferredFxTests(unittest.TestCase):
    """互动/动作精灵后台补建(E36)。"""

    def test_defer_builds_later_and_draws_nothing_until_then(self):
        import threading
        from PIL import Image
        import fx
        layer = fx.FX(1, 1, defer=True)
        for attr in ('hit', 'puff', 'orbs', '_shock_sets'):
            self.assertIsNone(getattr(layer, attr, None), attr)
        im = Image.new('RGBA', (300, 200))
        layer.hit_ring(im, 150, 100, .3)
        layer.puff_at(im, 150, 100, .3)
        layer.orb(im, 150, 100, 'near', 1)
        layer.shockwave(im, 150, 100, .3)
        self.assertIsNone(im.getbbox())
        # 待机首帧要用的照常同步建好
        for attr in ('ground_static', 'breath', 'ripple', 'orbit', 'orbit_dots'):
            self.assertIsNotNone(getattr(layer, attr, None), attr)
        # 两条线程同时补建:只建一次,建完都能画
        built = []
        real = fx._hit_sprite

        def counting(*a, **k):
            built.append(1)
            return real(*a, **k)

        with patch.object(fx, '_hit_sprite', counting):
            ts = [threading.Thread(target=layer.build_deferred) for _ in range(2)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
        self.assertEqual(len(built), 2 * layer.HIT_STEPS)
        layer.hit_ring(im, 150, 100, .3)
        self.assertIsNotNone(im.getbbox())

    def test_default_is_still_eager(self):
        import fx
        layer = fx.FX(1, 1)
        self.assertIsNotNone(getattr(layer, 'hit', None))
        self.assertIsNotNone(getattr(layer, '_shock_sets', None))


if __name__ == '__main__':
    unittest.main()
