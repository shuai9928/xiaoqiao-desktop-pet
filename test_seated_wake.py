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


if __name__ == "__main__":
    unittest.main()
