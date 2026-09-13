"""运动、命中与气泡的回归;不创建真实桌宠或触碰存档。"""
import random
import unittest
from unittest.mock import Mock, patch
from PIL import ImageFont
import pet


def body(scale=1):
    p = pet.Pet.__new__(pet.Pet)
    p.state, p.drag, p.scale = 'idle', None, scale
    p.W, p.H, p.FOOT_Y = 430*scale, 520*scale, 490*scale
    p.fy = p.ground_feet = 800
    p.x, p.x_min, p.x_max = 200., -1920, 1920
    p.parts, p._drag_trail = [], []
    p._drag_lean = 0
    p._ball_active = False
    p._bubble_born = 0
    p.next_trail = 0
    p.sfx = Mock()
    for name in ('say', 'play_emotion', 'hop', 'hearts', '_start_micro_motion', 'save_settings', 'throw'):
        setattr(p, name, Mock())
    return p


class BallTests(unittest.TestCase):
    def launch(self, scale=1):
        p = body(scale)
        with patch.object(pet.time, 'time', return_value=100):
            random.seed(18)
            p.throw_ball()
        return p

    def test_same_physics_at_10_30_60_fps_and_scales(self):
        for scale in (.8, 1, 1.25, 1.75):
            states = []
            for fps in (10, 30, 60):
                p = self.launch(scale)
                for i in range(1, int(4.8*fps)+1):
                    with patch.object(pet.time, 'time', return_value=100+i/fps):
                        p._advance_ball(100+i/fps)
                    b = next(q for q in p.parts if q['kind']=='ball')
                    self.assertLessEqual(b['y'], p.FOOT_Y-7*scale)
                    self.assertTrue(19*scale <= b['x'] <= p.W-19*scale)
                    self.assertLessEqual(len(b['trail']), 6)
                states.append(tuple(b[k] for k in ('x','y','vx','vy')))
            self.assertEqual(states[0], states[1])
            self.assertEqual(states[1], states[2])

    def test_replace_and_expire_only_once(self):
        p = self.launch()
        with patch.object(pet.time, 'time', return_value=101):
            p.throw_ball()
        self.assertEqual(sum(q['kind']=='ball' for q in p.parts), 1)
        p.say.reset_mock()
        p._advance_ball(105.99)
        self.assertTrue(p._ball_active)
        p._advance_ball(106)
        p._advance_ball(107)
        self.assertFalse(p._ball_active)
        self.assertFalse(any(q['kind']=='ball' for q in p.parts))
        p.say.assert_called_once()

    def test_catch_is_single_and_uses_current_coordinates(self):
        p = self.launch()
        p._start_micro_motion.reset_mock()
        p._advance_ball(100.5)
        b = next(q for q in p.parts if q['kind']=='ball')
        x, y = b['x'], b['y']
        with patch.object(pet.time, 'time', return_value=100.5):
            self.assertTrue(p._catch_ball(x, y))
            self.assertFalse(p._catch_ball(x, y))
        p._start_micro_motion.assert_called_once_with('catch')
        p.hearts.assert_called_once()

    def test_sleep_and_drag_cancel_ball(self):
        for state, drag in (('sleep',None), ('yawn',None), ('idle',(0,0,0,0,True,100))):
            p = self.launch()
            p.state, p.drag = state, drag
            p._advance_ball(100.5)
            self.assertFalse(p._ball_active)
            self.assertFalse(any(q['kind']=='ball' for q in p.parts))

    def test_long_frame_does_not_replay_old_impacts(self):
        p = self.launch()
        p._advance_ball(104.8)
        self.assertLessEqual(sum(q['kind']=='ball_ring' for q in p.parts), 1)
        p._advance_ball(109)
        self.assertFalse(any(q['kind']=='ball' for q in p.parts))


class TravelTests(unittest.TestCase):
    def test_chase_arrives_same_place_and_stops_smoothly(self):
        for scale in (.8,1,1.75):
            for fps in (10,30,60):
                p = body(scale)
                target = p.x+120*scale
                with patch.object(pet.time, 'time', return_value=100), patch.object(pet, 'cursor_pos', return_value=(target+p.W/2, 0)):
                    p.start_chase()
                for i in range(7*fps):
                    p._advance_chase(100+i/fps)
                self.assertEqual(p.state, 'idle')
                self.assertAlmostEqual(p.x, target)
                self.assertEqual(p._spin_lift, 0)
                p._start_micro_motion.assert_called_once_with('arrive')
                self.assertEqual(p._travel_progress(p._chase_duration,p._chase_duration)[1],0)

    def test_chase_times_out_and_can_be_interrupted(self):
        p = body()
        with patch.object(pet.time, 'time', return_value=100), patch.object(pet, 'cursor_pos', return_value=(1800,0)):
            p.start_chase()
        p._advance_chase(107)
        self.assertEqual(p.state,'idle')
        self.assertLess(p.x,p.walk_target)
        p._start_micro_motion.assert_not_called()
        x = p.x
        p._advance_chase(108)
        self.assertEqual(p.x,x)

    def test_drag_stationary_release_does_not_throw(self):
        p = body()
        p.drag = (0,0,0,0,True,100)
        p._drag_trail = [(100,0,0),(100.1,200,0)]
        with patch.object(pet.time, 'time', return_value=100.5):
            p.on_release(Mock())
        p.throw.assert_not_called()

    def test_drag_speed_and_pose_decay_after_pause(self):
        p = body()
        p.drag = (0,0,0,0,True,100)
        p._drag_trail = [(100,0,0),(100.1,120,0)]
        vx, vy = p._drag_velocity(p._drag_trail,100.1)
        self.assertAlmostEqual(vx,1200)
        self.assertEqual(vy,0)
        for i in range(60):
            p._advance_drag_pose(100.1+i/60,1/60)
            self.assertLessEqual(abs(p._drag_lean),.1)
        self.assertLess(abs(p._drag_lean),.001)
        self.assertLessEqual(len(p.parts),1)


class BubbleTests(unittest.TestCase):
    def test_fades_at_both_ends_without_changing_expiry(self):
        p = body()
        p.bubble, p._bubble_born = ('你好',102),100
        for now, alpha in ((100,0),(100.06,.5),(100.5,1),(101.91,.5),(102,0)):
            self.assertAlmostEqual(p._bubble_alpha(now),alpha)
        self.assertEqual(p.bubble,('你好',102))

    def test_bubble_cache_is_reused_and_transparency_does_not_mutate_it(self):
        p = body()
        p._bubble_art = None
        p._bubble_lay = {}
        p._font = Mock()
        p.f_bubble = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',28)
        p.bubble = ('星光落在窗边,陪你聊一会儿。',102)
        a = p._bubble_sprite(2)
        before = a.tobytes()
        self.assertIs(a,p._bubble_sprite(2))
        faded = a.copy()
        faded.putalpha(faded.getchannel('A').point(lambda v:v//2))
        self.assertEqual(a.tobytes(),before)
        self.assertLess(a.width,p.W*2)


if __name__=='__main__':
    unittest.main()
