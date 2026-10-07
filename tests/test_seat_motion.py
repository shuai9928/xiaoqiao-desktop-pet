"""I-40 秋千坐姿动作(套一陪你干活 + 套二摸摸她)。

纯逻辑部分(SeatMotion 时间轴)不依赖 Tk;接线部分用 test_swing 的壳桌宠,不创建窗口。
钉住:动作只用秋千上真实看得见的通道且不超过现有上限;缓入缓出不跳头;镜像;冲量只打一次;
优先级(摸摸她 > 陪你干活);停住只临时改阻尼;点帽子/坐垫/其余与长按的分流;减少动画等安静条件
退回原来的反馈;反应规则在秋千上换成坐姿动作、离开秋千照旧。
"""
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import life
import seat_motion as sm

NOW = 10_000.0
SET1, SET2 = ('glance', 'nudge', 'startle', 'relief'), ('pat', 'flick', 'push', 'shy')


class TimelineShapeTests(unittest.TestCase):
    def test_every_action_is_well_formed_and_inside_the_channel_caps(self):
        self.assertEqual(set(sm.ACTIONS), set(SET1 + SET2))
        for name, spec in sm.ACTIONS.items():
            with self.subTest(name):
                dur = spec['dur']
                for axis in ('lx', 'ly', 'breath'):
                    keys = spec.get(axis)
                    if keys is None:
                        continue
                    times = [t for t, _ in keys]
                    self.assertEqual(times, sorted(times))
                    self.assertLessEqual(times[-1], dur)
                    cap = 1.4 if axis == 'breath' else 1.0          # _art_pose clamps gaze to 1 and breath to 1.4
                    self.assertTrue(all(abs(v) <= cap for _, v in keys))
                for t, channel, dv in spec.get('hits', ()):
                    self.assertIn(channel, ('hat', 'swing'))       # hat_dx/hair stay below a pixel: never used
                    self.assertTrue(0 <= t < dur)
                hold = spec.get('hold')
                if hold:
                    self.assertTrue(0 <= hold[0] < hold[1] <= dur)
                lid = spec.get('lid')
                if lid:
                    self.assertTrue(0 <= lid[0] <= 1 and lid[2] > 0)
        self.assertGreater(min(sm.ACTIONS[n]['prio'] for n in SET2), max(sm.ACTIONS[n]['prio'] for n in SET1))

    def test_hat_impulses_are_visible_but_stay_inside_the_spring_caps(self):
        """Same springs, clamps and dead zones as Pet._art_pose: the tip moves 2..5 px at 150 %, never past 0.07 rad."""
        k = 183.4 * 1.5 / 1187                                       # art px -> screen px at 150 %
        for name, spec in sm.ACTIONS.items():
            for t, channel, dv in spec.get('hits', ()):
                if channel != 'hat':
                    continue
                with self.subTest(name=name, dv=dv):
                    lf, peak, now = life.LifeMotion(), 0.0, 0.0
                    lf.hat_rot.impulse(dv)
                    for _ in range(120):
                        now += 0.01
                        lf.update(now, 'swing', False, 0.0, 0.0, t=0.0)
                        rot = life.clamp(lf.hat_rot.x * 1.8, -0.07, 0.07)
                        peak = max(peak, 0.0 if abs(rot) < 0.008 else abs(round(rot / 0.01) * 0.01))
                    self.assertLessEqual(peak, 0.07)
                    self.assertGreaterEqual(peak * 330 * k, 1.5)         # tip ~330 art px above the hat base


class SeatMotionTests(unittest.TestCase):
    def test_gaze_eases_from_her_own_gaze_and_hands_it_back(self):
        m = sm.SeatMotion()
        m.start('glance', NOW)
        base = (-0.5, 0.25)
        self.assertEqual(m.gaze(NOW, base), base)                       # weight 0 at the start: no jump
        lx, ly = m.gaze(NOW + 1.0, base)
        self.assertAlmostEqual(lx, 0.875)
        self.assertAlmostEqual(ly, 0.25)
        self.assertEqual(m.gaze(NOW + sm.ACTIONS['glance']['dur'], base), base)
        self.assertIsNone(m.active(NOW + 5))

    def test_side_mirrors_gaze_and_hat_but_not_the_swing(self):
        right, left = sm.SeatMotion(), sm.SeatMotion()
        right.start('startle', NOW, side=1)
        left.start('startle', NOW, side=-1)
        self.assertAlmostEqual(right.gaze(NOW + 1, (0, 0))[0], -left.gaze(NOW + 1, (0, 0))[0])
        self.assertEqual(right.due(NOW), [('swing', -0.22), ('hat', -0.6)])
        self.assertEqual(left.due(NOW), [('swing', -0.22), ('hat', 0.6)])

    def test_impulses_fire_once_in_time_order(self):
        m = sm.SeatMotion()
        m.start('nudge', NOW)
        self.assertEqual(m.due(NOW + 0.69), [])
        self.assertEqual(m.due(NOW + 0.70), [('hat', 0.45)])
        self.assertEqual(m.due(NOW + 0.80), [])
        self.assertEqual(m.due(NOW + 1.60), [('hat', 0.45)])
        self.assertEqual(m.due(NOW + 9), [])

    def test_hold_window_and_breath_only_where_designed(self):
        m = sm.SeatMotion()
        m.start('pat', NOW)
        self.assertTrue(m.holding(NOW + 0.1) and m.holding(NOW + 2.1))
        self.assertFalse(m.holding(NOW + 2.3))
        self.assertGreater(m.breath(NOW + 1.0, 0.0), 0.3)
        m.start('glance', NOW + 10)
        self.assertFalse(m.holding(NOW + 10.5))
        self.assertEqual(m.breath(NOW + 10.5, 0.25), 0.25)

    def test_her_own_touch_outranks_agent_reactions(self):
        m = sm.SeatMotion()
        self.assertTrue(m.start('pat', NOW))
        self.assertFalse(m.start('nudge', NOW + 0.5))                   # a waiting reminder does not cut the pat short
        self.assertEqual(m.active(NOW + 0.5), 'pat')
        self.assertTrue(m.start('nudge', NOW + 3.0))                    # after the pat it plays
        self.assertFalse(m.start('glance', NOW + 3.5))
        self.assertTrue(m.start('startle', NOW + 3.6))                  # equal rank: the newest wins
        self.assertTrue(m.start('push', NOW + 3.7))


def _pet():
    import pet
    from test_swing import seated_pet
    return pet, seated_pet


class SeatedWiringTests(unittest.TestCase):
    def setUp(self):
        self.pet, seated_pet = _pet()
        self.p = p = seated_pet()
        p.life = life.LifeMotion()
        p.last_interact = NOW
        p.ui_reduced_anim = False
        p._nap_on_swing = False
        p._scene_drag = None

    def start(self, name, side=1, at=NOW):
        with patch.object(self.pet.time, 'time', return_value=at):
            return self.p.start_seat_action(name, side)

    def test_only_on_the_swing_and_never_in_quiet_states(self):
        self.assertTrue(self.start('pat'))
        for attr, value in (('ui_reduced_anim', True), ('_nap_on_swing', True), ('singing', True),
                            ('drag', (0, 0, 0, 0, True, 0)), ('_scene_drag', {'moved': True})):
            with self.subTest(attr):
                self.setUp()
                setattr(self.p, attr, value)
                self.assertFalse(self.start('pat'))
        self.setUp()
        self.p.state = 'idle'
        self.assertFalse(self.start('glance'))

    def test_eyelids_and_mouth_come_with_the_action(self):
        self.assertTrue(self.start('push'))
        self.assertEqual((self.p._lid, self.p._lid_mode), (0.22, 'happy'))
        self.assertEqual(self.p._mouth[0], 'laugh')

    def test_holding_still_damps_the_swing_and_restores_its_damping(self):
        def run(action, damping):
            self.setUp()
            sw = self.p._swing
            pend = sw['pend']
            pend.theta, pend.omega, pend.damping = 0.0, 0.5, damping
            if action:
                self.start(action)
            t = NOW
            for _ in range(40):                                          # 2 s at 20 fps
                t += 0.05
                self.p._seat_swing_step(sw, 0.05, t)
            return pend.amplitude, pend.damping
        free, d0 = run(None, 0.30)
        held, d1 = run('pat', 0.30)
        napping, d2 = run('pat', 0.9)
        self.assertLess(held, free * 0.4)
        self.assertEqual((d0, d1, d2), (0.30, 0.30, 0.9))                # the nap's own damping survives

    def test_swing_step_fires_hat_and_swing_impulses(self):
        sw = self.p._swing
        sw['pend'].theta, sw['pend'].omega = 0.1, 0.0
        twin = life.Pendulum(period=self.pet.SWING_PERIOD, idle_amp=sw['pend'].idle_amp, max_amp=sw['pend'].max_amp)
        twin.theta, twin.omega = 0.1, 0.0
        twin.step(0.05, pump=True)                                       # the same step without the action
        self.start('startle')
        self.p._seat_swing_step(sw, 0.05, NOW + 0.05)
        self.assertLess(self.p.life.hat_rot.v, 0)                        # tip jolts back
        self.assertAlmostEqual(sw['pend'].omega - twin.omega, -0.22)     # the swing jerks back by exactly the impulse
        v = self.p.life.hat_rot.v
        self.p._seat_swing_step(sw, 0.05, NOW + 0.10)
        self.assertGreater(self.p.life.hat_rot.v, v - 0.6)               # not fired twice

    def test_art_pose_blends_the_action_gaze_and_breath(self):
        import scene_art
        p = self.p
        p._scene_art = scene_art.SceneArt.load(os.path.join(self.pet.ASSETS, 'scene'))
        with open(os.path.join(self.pet.ASSETS, 'config.json'), encoding='utf-8') as f:
            p._scene_art.set_rig(json.load(f)['rig']['regions'])
        p._last_depth_pose = (0.0,) * 6
        p._swing.update(theta=0.0, omega=0.0)
        self.start('glance')
        with patch.object(self.pet.time, 'time', return_value=NOW + 1.0):
            pose = p._art_pose(0.0)
        self.assertEqual(pose['look'], (0.875, 0.25))
        self.assertEqual(pose['q'][:2], (0.875, 0.25))                    # quantised into the cache key
        with patch.object(self.pet.time, 'time', return_value=NOW + 5.0):
            self.assertEqual(p._art_pose(0.0)['look'], (0.0, 0.0))
        self.start('relief', at=NOW + 10)
        with patch.object(self.pet.time, 'time', return_value=NOW + 11.0):
            self.assertGreaterEqual(p._art_pose(0.0)['breath'], 1.0)

    def test_seat_zone_is_the_cushion_and_legs_not_her_face_hands_or_hat(self):
        import scene_art
        p = self.p
        p._scene_art = scene_art.SceneArt.load(os.path.join(self.pet.ASSETS, 'scene'))
        with open(os.path.join(self.pet.ASSETS, 'config.json'), encoding='utf-8') as f:
            p._scene_art.set_rig(json.load(f)['rig']['regions'])
        k, O = 0.25, (-40.0, 150.0)                                      # a real offset: skipping it moves points ~600 art px
        p._swing.update(art=True, geo={'k': k, 'O': O})
        at = lambda ax, ay: (ax * k - O[0], ay * k - O[1])               # art px -> scene canvas
        for name, point, seat in (('cushion', (520, 960), True), ('shoe', (760, 1200), True),
                                  ('face', (673, 540), False), ('hand on the lap', (735, 850), False),
                                  ('hat', (900, 200), False), ('outside her', (200, 1000), False)):
            with self.subTest(name):
                self.assertEqual(p._art_seat_hit(*at(*point)), seat)
        self.assertTrue(p._art_hat_hit(*at(900, 200)))                   # the hat still wins its own clicks

    def release(self, hat=False, seat=False, moved=False, held=None):
        p = self.p
        p.root = SimpleNamespace(after=lambda ms, fn: fn())
        p.click_token = 0
        p._art_hat_hit = Mock(return_value=hat)
        p._art_seat_hit = Mock(return_value=seat)
        p.wobble_hat, p.pet_head, p._swing_impulse = Mock(), Mock(), Mock()
        p._save_swing_scene = Mock()
        p._scene_drag = {'mx': 0, 'my': 0, 'moved': moved}
        if held:
            p._scene_drag['seat'] = held
        with patch.object(self.pet.time, 'time', return_value=NOW):
            p.on_release(SimpleNamespace(x=10, y=10, x_root=0, y_root=0))
        return p

    def test_clicks_on_the_swing_route_to_flick_push_and_pat(self):
        p = self.release(hat=True)
        p.wobble_hat.assert_called_once()
        p._swing_impulse.assert_not_called()
        self.assertEqual(p._seat_motion.name, 'flick')
        p = self.release(seat=True)
        p._swing_impulse.assert_called_once_with(sm.PUSH_IMPULSE)
        p.pet_head.assert_not_called()
        self.assertEqual(p._seat_motion.name, 'push')
        p = self.release()
        p.pet_head.assert_called_once()
        p._swing_impulse.assert_not_called()
        self.assertEqual(p._seat_motion.name, 'pat')

    def test_reduced_motion_keeps_the_old_click_feedback(self):
        self.p.ui_reduced_anim = True
        p = self.release(hat=True)
        p._swing_impulse.assert_called_once_with(0.05)
        self.p.ui_reduced_anim = True
        p = self.release(seat=True)
        p.pet_head.assert_called_once()
        p._swing_impulse.assert_called_once_with(0.10)
        self.p.ui_reduced_anim = True
        p = self.release()
        p._swing_impulse.assert_called_once_with(0.10)
        self.assertIsNone(p.__dict__.get('_seat_motion') and p._seat_motion.active(NOW))

    def test_long_press_is_shy_and_swallows_the_release(self):
        p = self.p
        d = p._scene_drag = {'mx': 0, 'my': 0, 'moved': False}
        with patch.object(self.pet.time, 'time', return_value=NOW):
            self.assertTrue(p._seat_long_press(d, 10))
        self.assertEqual((p._seat_motion.name, d['seat']), ('shy', 'shy'))
        p = self.release(held='shy')
        p.pet_head.assert_not_called()
        p.wobble_hat.assert_not_called()
        moved = p._scene_drag = {'mx': 0, 'my': 0, 'moved': True}
        self.assertFalse(p._seat_long_press(moved, 10))
        other = {'mx': 0, 'my': 0, 'moved': False}
        self.assertFalse(p._seat_long_press(other, 10))                   # a stale timer from an earlier press

    def test_press_on_the_swing_arms_the_long_press_unless_it_woke_her(self):
        for napping in (False, True):
            with self.subTest(napping=napping):
                self.setUp()
                p = self.p
                p.root = Mock()
                p._flat_panel_style = False
                for name in ('_catch_collect', '_pop_bubble', '_catch_ball', '_catch_leaf',
                             '_catch_flower', '_catch_snow'):
                    setattr(p, name, Mock(return_value=False))
                p._chain_rect = None
                p._book_open = p._crystal_open = False
                p._swing['ui_hits'] = []
                p._nap_on_swing = napping
                with patch.object(self.pet.time, 'time', return_value=NOW):
                    p.on_press(SimpleNamespace(x=10, y=10, x_root=5, y_root=5))
                self.assertEqual(p._scene_drag['moved'], False)
                if napping:
                    p.root.after.assert_not_called()
                else:
                    self.assertEqual(p.root.after.call_args.args[0], sm.LONG_PRESS_MS)

    def test_companion_reactions_become_seated_actions_on_the_swing(self):
        import agent_companion as c
        from agent_reactions import Reaction
        p = self.p
        p.say, p.play_emotion = Mock(), Mock(return_value=False)
        p._start_micro_motion, p._swing_impulse, p.hop = Mock(), Mock(), Mock()
        for kind, action in (('started', 'glance'), ('waiting', 'nudge'), ('error_seen', 'startle'), ('done', 'relief')):
            with self.subTest(kind):
                p._seat_motion = sm.SeatMotion()
                r = Reaction(kind, 'Claude', motion='notice' if kind == 'started' else '',
                             effects=('hop',) if kind == 'waiting' else ())
                with patch.object(self.pet.time, 'time', return_value=NOW):
                    c.execute(p, r, NOW)
                self.assertEqual(p._seat_motion.name, action)
        p._start_micro_motion.assert_not_called()
        p._swing_impulse.assert_not_called()                             # 'hop' became the nudge
        p.state = 'idle'                                                  # off the swing: the old primitives
        c.execute(p, Reaction('started', 'Claude', motion='notice'), NOW)
        p._start_micro_motion.assert_called_once_with('notice')


if __name__ == '__main__':
    unittest.main()
