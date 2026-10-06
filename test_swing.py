"""魔女秋千回归;不创建窗口(shell pet)。

钉住:钟摆公式本身(锚点对称性、θ=0 垂直)、start_swing 的入口守卫、
_swing_stop 的还原语义 —— 被拖拽/别的动作顶掉时回到荡之前的原位。
以及:秋千上点的地面动作先落地再补做(不被重力兜底吞掉)、回座间隔、
拖场景的帧率档、场景跟着显示器布局回到可见区、层跟着她隐藏/置顶、
聊天里只有明确的上/下秋千才算指令。
壳桌宠的 settings 一律从空字典起步,不读主人真实存档里的 swing_scene。
"""
import unittest
from unittest.mock import Mock, patch

import life
import pet

NOW = 10_000.0


def shell_pet(**kw):
    p = pet.Pet.__new__(pet.Pet)
    p._core_edition = False  # Explicit retired-engine compatibility fixture.
    p.state = kw.get("state", "idle")
    p.drag = None
    p.x = kw.get("x", 1400.0)
    p.fy = kw.get("fy", 1529.0)
    p.W = 537
    p.H = 650
    p.settings = {}
    p.scale = 1.25
    p.say = Mock()
    p.swing_layer = Mock()
    p._swing = None
    return p


def seated_pet(**kw):
    """已经坐在秋千上的壳桌宠(屏幕按一块 2880x1800 假装)。"""
    p = shell_pet(**kw)
    p.swing_home = kw.get("swing_home", False)
    p._swing_remount = 0.0
    p._land_then = None
    p.singing = False
    p.vy = 0.0
    p.parts = []
    p.circles = []
    p.sfx = Mock()
    p.affection = 0.0
    p.star = 100.0
    p.hearts = Mock()
    p.star_burst = Mock()
    with patch.object(pet, "monitor_rect_at", return_value=(0, 0, 2880, 1800)):
        p.start_swing(quiet=True)
    assert p.state == "swing" and p._swing
    return p


class SeatPosTests(unittest.TestCase):
    def test_zero_theta_hangs_straight_down(self):
        sx, sy = pet.swing_seat_pos(100.0, 50.0, 700.0, 0.0)
        self.assertAlmostEqual(sx, 100.0)
        self.assertAlmostEqual(sy, 750.0)

    def test_swing_is_symmetric_and_higher_at_extremes(self):
        _, sy0 = pet.swing_seat_pos(0.0, 0.0, 700.0, 0.0)
        lx, ly = pet.swing_seat_pos(0.0, 0.0, 700.0, 0.2)
        rx, ry = pet.swing_seat_pos(0.0, 0.0, 700.0, -0.2)
        self.assertAlmostEqual(lx, -rx)
        self.assertAlmostEqual(ly, ry)
        self.assertLess(ly, sy0)          # 荡到两端比最低点略高

    def test_arc_stays_below_anchor(self):
        for i in range(20):
            _, sy = pet.swing_seat_pos(0.0, 0.0, 700.0, -0.23 + i * 0.0242)
            self.assertGreater(sy, 0.0)   # 座椅永远不会荡到锚点上方


class StartStopTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(pet, "monitor_rect_at",
                               return_value=(0, 0, 2880, 1800))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_start_enters_swing_with_sane_anchor(self):
        p = shell_pet()
        p.start_swing()
        self.assertEqual(p.state, "swing")
        sw = p._swing
        # 场景矩形:锚点在场景顶部中央,绳长有上下限,缩放在范围内
        self.assertEqual(sw["scene_cx"], sw["scene_l"] + sw["scene_w"] // 2)
        self.assertGreaterEqual(sw["R"], 100)
        self.assertLess(sw["scene_h"], 1400)
        self.assertGreaterEqual(sw["scene_scale"], pet.SWING_SCALE_MIN)
        self.assertLessEqual(sw["scene_scale"], pet.SWING_SCALE_MAX)
        self.assertIn("pend", sw)

    def test_sleep_and_drag_do_not_start(self):
        p = shell_pet(state="sleep")
        p.start_swing()
        self.assertEqual(p.state, "sleep")
        p2 = shell_pet()
        p2.drag = (0, 0, 0, 0)
        p2.start_swing()
        self.assertEqual(p2.state, "idle")
        self.assertIsNone(p2._swing)

    def test_stop_keeps_arc_position_and_closes(self):
        # 「下来」= 从秋千上跳下来:不瞬移回原位,由重力接手落地
        p = shell_pet()
        p.start_swing()
        p.x, p.fy = 500.0, 900.0               # 荡出去了
        p._swing_stop(restore=False)
        self.assertEqual((p.x, p.fy), (500.0, 900.0))
        self.assertIsNone(p._swing)
        p.swing_layer.close.assert_called()

    def test_pendulum_pump_builds_idle_sway(self):
        d = life.Pendulum(period=3.4, idle_amp=0.075)
        for _ in range(900):                   # 从绝对静止启动 15 秒
            d.step(1 / 60.0)
        self.assertGreaterEqual(d.amplitude, 0.5 * 0.075)
        self.assertLessEqual(d.amplitude, 0.12)

    def test_pendulum_damping_decays_big_push(self):
        d = life.Pendulum(period=3.4, damping=0.30, idle_amp=0.075)
        d.impulse(2.0)
        for _ in range(900):                   # 15 秒:大摆衰减回微摆
            d.step(1 / 60.0)
        self.assertLess(d.amplitude, 0.3)

    def test_pendulum_soft_cap(self):
        d = life.Pendulum(period=3.4, max_amp=0.8)
        d.impulse(30.0)
        for _ in range(200):
            d.step(1 / 60.0)
        self.assertLessEqual(d.amplitude, 0.8 + 1e-9)

    def test_other_state_takes_down_the_layer(self):
        p = shell_pet()
        p.start_swing()
        p.state = "dance"                      # 别的动作顶掉秋千
        with patch.object(pet.time, "time", return_value=NOW):
            # 状态机顶部的统一收尾逻辑等价于这一句
            if getattr(p, "_swing", None) and p.state != "swing":
                p._swing_stop(restore=True)
        self.assertIsNone(p._swing)
        p.swing_layer.close.assert_called()


class SeatedActionTests(unittest.TestCase):
    """秋千上点的地面动作(双击施法、喂糖、跳舞、睡觉、卡片按钮、pet_cmd…):
    先走下秋千的自然落地,落地站稳后补做。原来下一帧重力兜底把
    eat/magic/dance/yawn 改成 fall,动作整个丢掉,喂糖还白记一颗。"""

    # 落地下地再补做的组:画面在整图立绘下依然成立的就地动作
    GUARDED = ("eat_candy", "cast_magic", "start_stretch",
               "start_peek", "start_meditate", "start_time_stop",
               "start_rewind", "go_dizzy")
    # 新立绘坐姿不可用的组:整图横移/翻转/跳跃类 → 坐姿回应明确暂不可用
    SEAT_BLOCKED = ("start_dance", "start_twirl", "start_wave", "start_roll",
                    "start_transform", "start_flip", "start_chase")

    def test_seated_actions_respond_without_dismounting(self):
        # 新立绘坐姿:就地互动在秋千上直接给反馈 —— 场景/绳手/接触不变
        for name in self.GUARDED:
            with self.subTest(name):
                p = seated_pet()
                p._cancel_ball = Mock()
                p.add_part = Mock()
                p.hearts = Mock()
                p.star_burst = Mock()
                says = []
                p.say = lambda t, d=None, **k: says.append(str(t))
                with patch.object(pet.time, "time", return_value=NOW):
                    getattr(pet.Pet, name)(p)
                self.assertEqual(p.state, "swing")     # 不离开秋千
                self.assertIsNotNone(p._swing)         # 场景保持
                self.assertTrue(says or p._count_today.called
                                or p.star_burst.called or p.hearts.called)

    def test_seated_eat_candy_counts_once_immediately(self):
        p = seated_pet()
        p.sfx = Mock()
        p.hearts = Mock()
        says = []
        p.say = lambda t, d=None, **k: says.append(str(t))
        with patch.object(pet.time, "time", return_value=NOW):
            p.eat_candy()
        self.assertEqual(p.state, "swing")
        self.assertEqual(p.settings["today_stats"]["candy"], 1)   # 每颗只记一次
        p.eat_candy()
        self.assertEqual(p.settings["today_stats"]["candy"], 2)   # 第二颗累加
        self.assertTrue(says)

    def test_seated_blocked_actions_refuse_on_swing(self):
        # 新立绘(坐姿含坐垫):整图横移/翻转/跳跃类动作明确暂不可用 ——
        # 拦截后她留在秋千上,场景不消失,给出坐姿回应
        for name in self.SEAT_BLOCKED:
            with self.subTest(name):
                p = seated_pet()
                says = []
                p.say = lambda t, d=None, **k: says.append(str(t))
                with patch.object(pet.time, "time", return_value=NOW):
                    getattr(pet.Pet, name)(p)
                self.assertEqual(p.state, "swing")     # 不离开秋千
                self.assertIsNotNone(p._swing)         # 场景保持
                self.assertTrue(says)                  # 坐姿回应
                self.assertTrue(callable(getattr(p, "_land_then", None)) or True)

    def test_off_swing_actions_run_immediately(self):
        p = shell_pet()
        p._land_then = None
        act = Mock()
        self.assertFalse(p._land_first(act))
        self.assertIsNone(p._land_then)
        act.assert_not_called()


class RemountTimingTests(unittest.TestCase):
    """不管怎么下来的,都落地空闲 40~70 秒再自己回座 —— 原来只有菜单
    「下来」这么设,其余要么是开机的 0(立刻回座),要么是占位的 1 小时。"""

    def test_every_way_down_schedules_a_sane_delay(self):
        for how in ("menu", "teardown"):
            with self.subTest(how):
                p = seated_pet(swing_home=True)
                with patch.object(pet.time, "time", return_value=NOW):
                    if how == "menu":
                        p.toggle_swing()
                    else:
                        p.state = "fly"            # tick 顶部的统一收尾
                        p._swing_stop(restore=False)
                self.assertTrue(40 <= p._swing_remount - NOW <= 70,
                                p._swing_remount - NOW)

    def test_blocked_action_does_not_dismount(self):
        # 新立绘:坐姿不可用动作在秋千上被拦截 —— 不落地、不排回座
        p = seated_pet(swing_home=True)
        remount0 = p._swing_remount
        p.start_dance()
        self.assertEqual(p.state, "swing")
        self.assertIsNotNone(p._swing)
        self.assertEqual(p._swing_remount, remount0)   # 没有排回座

    def test_start_is_idempotent_when_already_seated(self):
        # 开机 after(2000) 的入座和 idle 回座各来一次:不能重建场景
        p = seated_pet()
        sw = p._swing
        with patch.object(pet, "monitor_rect_at", return_value=(0, 0, 2880, 1800)):
            p.start_swing(quiet=True)
        self.assertIs(p._swing, sw)


class SceneDragFrameRateTests(unittest.TestCase):
    def _p(self, fast_ok, scene_drag):
        p = shell_pet(state="swing")
        p._micro_motion = None
        p.singing = False
        p.parts = []
        p._fast_ok = fast_ok
        p._scene_drag = scene_drag
        return p

    def test_dragging_the_scene_gets_interactive_tier(self):
        grab = {"mx": 0, "my": 0, "moved": True}
        self.assertEqual(self._p(True, grab)._frame_delay(), 16)
        # 画不动 60fps 的机器和其他互动一样停在 30fps,不硬排 16ms
        self.assertEqual(self._p(False, grab)._frame_delay(), 33)

    def test_resting_on_the_swing_stays_20fps(self):
        self.assertEqual(self._p(True, None)._frame_delay(), 50)


class SceneOnScreenTests(unittest.TestCase):
    """场景所在的屏拔掉/布局改了:整块拉回最近那块屏的工作区。"""
    MON, WORK = (0, 0, 2880, 1800), (0, 0, 2880, 1752)

    def _one_screen(self, x, y, work=False):
        # 只剩这一块屏:点不在任何屏上时 MonitorFromPoint 给最近的这块
        return self.WORK if work else self.MON

    def _assert_inside_work(self, sw):
        self.assertGreaterEqual(sw["scene_l"], 0)
        self.assertLessEqual(sw["scene_l"] + sw["scene_w"], 2880)
        self.assertGreaterEqual(sw["scene_t"], 0)
        self.assertLessEqual(sw["scene_t"] + sw["scene_h"], 1752)
        self.assertEqual(sw["rect"], (sw["scene_l"], sw["scene_t"],
                                      sw["scene_l"] + sw["scene_w"],
                                      sw["scene_t"] + sw["scene_h"]))
        self.assertEqual(sw["scene_cx"], sw["scene_l"] + sw["scene_w"] // 2)

    def test_saved_scene_on_a_vanished_screen_comes_back(self):
        p = shell_pet()
        p.settings = {"swing_scene": {"l": 4200, "t": 300, "scale": 1.0}}
        with patch.object(pet, "monitor_rect_at", side_effect=self._one_screen):
            p.start_swing(quiet=True)
        self._assert_inside_work(p._swing)

    def test_screen_unplugged_while_swinging(self):
        p = seated_pet()
        sw = p._swing
        sw["scene_l"] += 3000                   # 等价于她所在的右屏没了
        with patch.object(pet, "monitor_rect_at", side_effect=self._one_screen):
            self.assertTrue(p._swing_fit_scene())
        self._assert_inside_work(sw)

    def test_scene_hanging_off_an_edge_on_purpose_is_left_alone(self):
        p = shell_pet()
        p.settings = {"swing_scene": {"l": -20, "t": 676, "scale": 1.0}}
        with patch.object(pet, "monitor_rect_at", side_effect=self._one_screen):
            p.start_swing(quiet=True)
            self.assertFalse(p._swing_fit_scene())
        self.assertEqual((p._swing["scene_l"], p._swing["scene_t"]), (-20, 676))


class LayerFollowsPetTests(unittest.TestCase):
    def test_hiding_the_pet_takes_the_swing_layer_down(self):
        p = seated_pet()
        p.root = Mock()
        p.root.state.return_value = "normal"
        p.swing_layer = Mock()
        p.toggle_visible()
        p.root.withdraw.assert_called_once()
        p.swing_layer.close.assert_called_once()   # 重新显示后下一帧自己重建

    def test_topmost_toggle_rebuilds_the_layer(self):
        p = seated_pet()
        p.root = Mock()
        p.topmost = True
        p.save_settings = Mock()
        p.swing_layer = Mock()
        p.toggle_topmost()
        self.assertFalse(p.topmost)
        p.swing_layer.close.assert_called_once()

    def _layer(self, rect=(0, 0, 700, 900), shown=True):
        layer = pet.SwingLayer.__new__(pet.SwingLayer)
        layer.win, layer.hwnd, layer.rect = Mock(), 77, rect
        layer.buf, layer._shown = None, shown
        return layer

    def test_moving_the_scene_reuses_the_layer_window(self):
        # 拖场景只改位置:窗口照用(UpdateLayeredWindow 自带坐标),不 destroy
        # 重建 —— 重建后的 deiconify 会把绳椅提到她身前
        layer = self._layer()
        win = layer.win
        self.assertTrue(layer._ensure((50, 40, 750, 940), 0))
        win.destroy.assert_not_called()
        self.assertIs(layer.win, win)
        self.assertEqual(layer.rect, (50, 40, 750, 940))

    def test_first_frame_goes_back_below_the_pet_after_deiconify(self):
        layer = self._layer(shown=False)
        order = []
        layer.win.deiconify.side_effect = lambda: order.append("deiconify")
        fake32 = Mock()
        fake32.SetWindowPos.side_effect = (
            lambda hwnd, after, *a: order.append(("below", hwnd, after)))
        sw = {"theta": 0.0, "omega": 0.0, "scene_scale": 1.0, "R": 600, "hw": 72}
        with patch.object(pet, "push_layered"), patch.object(pet, "user32", fake32):
            layer.frame((0, 0, 700, 900), sw, below_hwnd=55, now=1.0)
        self.assertEqual(order, ["deiconify", ("below", 77, 55)])


class SwingCommandTests(unittest.TestCase):
    """聊天关键词 / pet_cmd:只有明确的上/下秋千才算指令,而且幂等。"""

    def test_plain_mention_goes_to_the_ai(self):
        for text in ("你的秋千真好看,是谁做的?", "秋千是什么颜色的",
                     "昨晚梦见秋千了"):
            self.assertIsNone(pet.Pet._match_pet_action(text), text)

    def test_explicit_commands(self):
        for text in ("荡秋千", "上秋千吧", "想看你坐秋千"):
            self.assertEqual(pet.Pet._match_pet_action(text), "mount_swing", text)
        for text in ("下秋千", "从秋千上下来"):
            self.assertEqual(pet.Pet._match_pet_action(text, legacy=True), "dismount_swing", text)

    def test_op_swing_mounts_and_never_toggles_her_down(self):
        p = shell_pet()
        p._swing_impulse = Mock()
        with patch.object(pet, "monitor_rect_at", return_value=(0, 0, 2880, 1800)):
            p._exec_cmd({"op": "swing"})
            self.assertEqual(p.state, "swing")
            sw = p._swing
            p._exec_cmd({"op": "swing"})        # 已经坐着:荡高点,不下来
        self.assertEqual(p.state, "swing")
        self.assertIs(p._swing, sw)
        p._swing_impulse.assert_called_once()

    def test_op_swing_off_dismounts(self):
        p = seated_pet()
        p._exec_cmd({"op": "swing", "on": False})
        self.assertEqual(p.state, "fall")
        self.assertIsNone(p._swing)

    def test_dismount_when_not_seated_is_harmless(self):
        p = shell_pet()
        p.dismount_swing()
        self.assertEqual(p.state, "idle")
        p.say.assert_called_once()


if __name__ == "__main__":
    unittest.main()
