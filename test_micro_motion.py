"""轻互动动画回归;不创建窗口,不读取或写入用户存档。"""
import unittest
from unittest.mock import patch

import pet


class MicroMotionTests(unittest.TestCase):
    def setUp(self):
        self.p = pet.Pet.__new__(pet.Pet)
        self.p.state = "idle"
        self.p.drag = None
        self.p.singing = self.p.thinking_now = False
        self.p._micro_motion = None
        self.p.x, self.p.W = 0, 400
        self.p.next_event = 101
        self.p.lean, self.p.squash = .02, 1.0
        self.clock = patch.object(pet.time, "time", return_value=100)
        self.clock.start()
        self.cursor = patch.object(pet, "cursor_pos", return_value=(400, 200))
        self.cursor.start()
        self.addCleanup(patch.stopall)

    def test_motion_finishes_without_pose_drift(self):
        for kind in self.p.MICRO_POSES:
            self.assertTrue(self.p._start_micro_motion(kind))
            for i in range(180):
                lean, bend, squash, lift = self.p._micro_pose(100 + i / 60)
                self.assertLessEqual(abs(lean), .11)
                self.assertLessEqual(abs(bend), .20)
                self.assertLessEqual(abs(squash), .05)
                self.assertLessEqual(abs(lift), 5)
            self.assertIsNone(self.p._micro_motion)
            self.assertEqual((self.p.lean, self.p.squash, self.p.state), (.02, 1., "idle"))

    def test_repeated_touch_continues_current_pose(self):
        self.p._start_micro_motion("nuzzle")
        before = self.p._micro_pose(100.7)
        with patch.object(pet.time, "time", return_value=100.7):
            self.p._start_micro_motion("giggle")
        self.assertEqual(self.p._micro_pose(100.7), before)

    def test_sleep_and_big_actions_cancel_micro_motion(self):
        for state in ("sleep", "yawn", "dance", "magic", "fly", "fall", "twirl"):
            self.p.state = "idle"
            self.p._start_micro_motion("notice")
            self.p.state = state
            self.assertEqual(self.p._micro_pose(100.5), (0.,) * 4)
            self.assertIsNone(self.p._micro_motion)
            self.assertFalse(self.p._start_micro_motion("nuzzle"))

    def test_drag_singing_and_thinking_take_priority(self):
        for attr in ("drag", "singing", "thinking_now"):
            self.p._start_micro_motion("notice")
            setattr(self.p, attr, (0, 0, 0, 0, True, 100) if attr == "drag" else True)
            self.assertEqual(self.p._micro_pose(100.5), (0.,) * 4)
            self.assertFalse(self.p._start_micro_motion("notice"))
            setattr(self.p, attr, False)

    def test_stationary_press_does_not_interrupt_repeated_touch(self):
        self.p._start_micro_motion("nuzzle")
        self.p.drag = (0, 0, 0, 0, False, 100)
        self.assertNotEqual(self.p._micro_pose(100.62), (0.,) * 4)

    def test_response_faces_cursor_and_keeps_vertical_motion(self):
        self.p._start_micro_motion("nuzzle")
        right = self.p._micro_pose(100.62)
        self.p._micro_motion = None
        with patch.object(pet, "cursor_pos", return_value=(0, 200)):
            self.p._start_micro_motion("nuzzle")
        left = self.p._micro_pose(100.62)
        self.assertEqual(left, (-right[0], -right[1], right[2], right[3]))


if __name__ == "__main__":
    unittest.main()
