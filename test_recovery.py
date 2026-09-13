"""喷嚏、眩晕与站起时序回归;不创建真实桌宠或访问存档。"""
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from pet import Pet


class RecoveryTests(unittest.TestCase):
    def make_pet(self, scale=1):
        p = Pet.__new__(Pet)
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


if __name__ == '__main__':
    unittest.main()
