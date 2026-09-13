"""专注陪伴模式回归;不创建窗口,不读写用户存档。

番茄钟原来只是个计时器 —— 专注期间她照常闲聊、走动、打喷嚏、主动搭话,
还会在 75 秒没互动后直接睡过去。这套用例钉住"专注时她安静地陪着"这件事,
以及一条硬约束:陪伴演出只许用 AMBIENT_PARTS 里的粒子,否则会把省电的
20fps 安静档顶成 60fps。
"""
import unittest
from unittest.mock import Mock, patch

import pet

NOW = 10_000.0


def focus_pet(phase="focus", mins=25.0, elapsed=0.0, now=NOW):
    """造一只壳桌宠:只有本模块用得到的字段,不跑 __init__。"""
    p = pet.Pet.__new__(pet.Pet)
    p.pomo = (None if phase is None else
              {"phase": phase, "due": now - elapsed + mins * 60, "mins": mins})
    p.state, p.drag, p.bubble, p.sticker = "idle", None, None, None
    p.singing = False
    p.scale = 1.0
    p.W, p.H = 430, 520
    p.parts = []
    p._focus_next = 0.0
    p._focus_half = False
    p._bubble_born = 0.0
    p.pomo_done = 0
    for name in ("_start_micro_motion", "play_emotion", "hop", "hearts",
                 "save_settings", "_reply", "go_sleep", "greet_period",
                 "start_chase", "start_dance", "start_peek", "_idle_event"):
        setattr(p, name, Mock())
    return p


class PredicateTests(unittest.TestCase):
    def test_only_focus_phase_counts(self):
        with patch.object(pet.time, "time", return_value=NOW):
            self.assertTrue(focus_pet("focus").focus_mode())
            self.assertFalse(focus_pet("break").focus_mode())
            self.assertFalse(focus_pet(None).focus_mode())

    def test_expired_pomo_is_not_focus(self):
        """due 已过但 tick 还没来得及收尾的那一帧,不该还算专注。"""
        p = focus_pet("focus", mins=25.0, elapsed=25 * 60 + 1)
        with patch.object(pet.time, "time", return_value=NOW):
            self.assertFalse(p.focus_mode())

    def test_survives_stub_pet_without_pomo(self):
        """几个 unittest 文件用 Pet.__new__ 造壳桌宠、不跑 __init__,
        而 say() 会调到 focus_mode() —— 这里必须是 False 而不是崩。"""
        bare = pet.Pet.__new__(pet.Pet)
        self.assertFalse(bare.focus_mode())


class SayTests(unittest.TestCase):
    def _say(self, p, text, **kw):
        with patch.object(pet.time, "time", return_value=NOW):
            pet.Pet.say(p, text, **kw)
        return p.bubble[1] - NOW

    def test_long_line_is_clamped_during_focus(self):
        p = focus_pet("focus")
        self.assertAlmostEqual(self._say(p, "很长的一句话" * 12), 2.2, places=6)

    def test_keep_is_exempt(self):
        """提醒和 AI 回答是主人自己要的内容,长度得按阅读速度来。"""
        p = focus_pet("focus")
        self.assertGreater(self._say(p, "很长的一句话" * 12, dur=9.0,
                                     keep=True), 8.0)

    def test_not_clamped_outside_focus(self):
        p = focus_pet("break")
        self.assertGreater(self._say(p, "很长的一句话" * 12), 2.2)


class EncouragementTests(unittest.TestCase):
    def _run(self, p, seconds, step=1.0, start=NOW):
        t = start
        end = start + seconds
        while t < end:
            with patch.object(pet.time, "time", return_value=t):
                pet.Pet._focus_tick(p, t)
            t += step

    def test_only_ambient_particles(self):
        """硬约束:陪伴演出只许用 AMBIENT_PARTS 里的种类。

        heart / confetti / note / gear 会把 20fps 安静档顶成 60fps,并且
        持续整个粒子寿命 —— 那等于把这个功能省下来的电又赔回去。
        """
        p = focus_pet("focus")
        p.add_part = Mock()
        self._run(p, 25 * 60)
        kinds = {c.args[0] for c in p.add_part.call_args_list}
        self.assertTrue(kinds, "整段专注一次陪伴演出都没有")
        self.assertTrue(kinds <= pet.AMBIENT_PARTS,
                        f"非氛围粒子会顶高帧率: {sorted(kinds - pet.AMBIENT_PARTS)}")

    def test_cadence_is_a_few_times_per_session(self):
        p = focus_pet("focus")
        p.add_part = Mock()
        self._run(p, 25 * 60)
        bursts = len(p.add_part.call_args_list) / 3.0   # 每次冒 3 颗
        self.assertTrue(2 <= bursts <= 7, bursts)

    def test_silent_no_bubble_no_sticker(self):
        p = focus_pet("focus")
        p.add_part = Mock()
        p.say = Mock()
        self._run(p, 25 * 60)
        p.say.assert_not_called()
        p.play_emotion.assert_not_called()

    def test_skipped_while_a_bubble_is_up(self):
        """主人刚摸过她,别让星光跟台词抢戏。"""
        p = focus_pet("focus")
        p.bubble = ("摸摸~", NOW + 99)
        p.add_part = Mock()
        self._run(p, 25 * 60)
        p.add_part.assert_not_called()

    def test_halfway_motion_fires_once(self):
        p = focus_pet("focus")
        p.add_part = Mock()
        self._run(p, 25 * 60)
        self.assertEqual(p._start_micro_motion.call_count, 1)

    def test_nothing_during_break(self):
        p = focus_pet("break")
        p.add_part = Mock()
        self._run(p, 5 * 60)
        p.add_part.assert_not_called()


if __name__ == "__main__":
    unittest.main()
