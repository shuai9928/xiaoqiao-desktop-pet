"""Regression tests for seated sleep across public interaction entrances."""
import unittest
from unittest.mock import Mock, patch

import pet
from test_swing import NOW, seated_pet


def napping_pet():
    p = seated_pet()
    p._core_edition = True
    p._swing["art"] = True
    p._cancel_ball = Mock()
    p.add_part = Mock()
    p.play_emotion = Mock()
    p._start_micro_motion = Mock()
    p.go_sleep()
    p.parts = [{"kind": "zzz"}, {"kind": "heart"}]
    return p


class SeatedWakeTests(unittest.TestCase):
    def assert_awake_on_same_scene(self, p, scene):
        self.assertFalse(p._nap_on_swing)
        self.assertEqual(p.state, "swing")
        self.assertIs(p._swing, scene)
        self.assertEqual(p.parts, [{"kind": "heart"}])
        self.assertEqual(scene["pend"].idle_amp, 0.085)
        self.assertEqual(scene["pend"].damping, 0.30)

    def test_all_wake_entrances_preserve_scene_and_clear_sleep_particles(self):
        for entrance in ("wake_up", "wake_if_sleep", "card"):
            with self.subTest(entrance=entrance):
                p = napping_pet()
                scene = p._swing
                with patch.object(pet.time, "time", return_value=NOW):
                    if entrance == "card":
                        card = pet.InteractionCard.__new__(pet.InteractionCard)
                        card.pet = p
                        card._sleep()
                    else:
                        getattr(p, entrance)()
                self.assert_awake_on_same_scene(p, scene)
                self.assertEqual(p.last_interact, NOW)

    def test_feeding_wakes_without_duplicate_candy_count(self):
        p = napping_pet()
        scene = p._swing
        with patch.object(pet.time, "time", return_value=NOW):
            p.eat_candy()
        self.assert_awake_on_same_scene(p, scene)
        self.assertEqual(p.settings["today_stats"]["candy"], 1)
        p.hearts.assert_called_once()
        p.sfx.play.assert_called_once_with("voice_yum")

    def test_retired_magic_cannot_wake_or_dismount(self):
        p = napping_pet()
        scene = p._swing
        self.assertFalse(p.cast_magic())
        self.assertTrue(p._nap_on_swing)
        self.assertIs(p._swing, scene)
        p.star_burst.assert_not_called()

    def test_card_label_and_hint_follow_seated_nap(self):
        p = napping_pet()
        p.affection_level = Mock(return_value="熟悉")
        card = pet.InteractionCard.__new__(pet.InteractionCard)
        card.pet = p
        card.closed = False
        card.u = 1.0
        card.cv = Mock()
        card.win = Mock()
        card.status, card.energy, card.hint = 1, 2, 3
        card.buttons = {k: Mock() for k in ("睡觉", "玩球")}
        card._hint_key = "睡觉"
        card._default_hint = lambda: "一起度过这会儿"
        card._refresh()
        card.buttons["睡觉"].configure.assert_any_call(text="叫醒")
        self.assertIn("叫醒", card.cv.itemconfigure.call_args.kwargs["text"])
        card._sleep()
        card._refresh()
        card.buttons["睡觉"].configure.assert_any_call(text="睡觉")
        self.assertNotIn("玩球", card.disabled_reasons(p))

    def test_nap_on_swing_frame_tiers(self):
        """I-37:秋千打盹安静档 —— 无互动 10fps,互动信号当帧回互动档。"""
        def tiered(nap_pet):
            nap_pet._fast_ok = True
            nap_pet._micro_motion = None
            nap_pet._scene_drag = None
            nap_pet.bubble = None
            nap_pet.sticker = None
            nap_pet.circles = []
            nap_pet.thinking_now = False
            return nap_pet
        p = tiered(napping_pet())
        p.parts = [{"kind": "zzz"}]          # 打盹偶发 zzz 是慢飘粒子
        self.assertEqual(p._frame_delay(), 100)
        p.parts = [{"kind": "zzz"}, {"kind": "heart"}]
        # 非 zzz 粒子:_fast_ok 分支优先级更高,先回 16;画不动的机器
        # (_fast_ok=False)落到打盹分支自己的互动档 33
        self.assertEqual(p._frame_delay(), 16)
        p._fast_ok = False
        self.assertEqual(p._frame_delay(), 33)
        p._fast_ok = True
        p.parts = [{"kind": "zzz"}]
        p.bubble = ("嗯?", 0.0)
        self.assertEqual(p._frame_delay(), 33)     # 气泡回互动档
        p.bubble = None
        p.thinking_now = True
        self.assertEqual(p._frame_delay(), 33)     # 思考回互动档
        p.thinking_now = False
        p._scene_drag = {"mx": 0, "my": 0, "moved": False}
        self.assertEqual(p._frame_delay(), 16)     # 场景拖拽:既有互动档
        p._scene_drag = None
        p.drag = (0, 0, 0, 0, False, 0.0)
        self.assertEqual(p._frame_delay(), 16)     # 拖她:既有互动档
        p.drag = None
        with patch.object(pet.time, "time", return_value=NOW):
            p.wake_up()
        self.assertFalse(p._nap_on_swing)
        self.assertEqual(p.state, "swing")
        self.assertEqual(p._frame_delay(), 50)     # 清标记后回常驻荡 20fps


if __name__ == "__main__":
    unittest.main()
