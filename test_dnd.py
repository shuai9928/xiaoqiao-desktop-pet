"""勿扰回归;不创建窗口,不读写用户存档,不调用真实音频。

勿扰要钉住的是"她安静但还在":判定(手动定时、夜间时段、今晚提前结束)、
开关的落盘与回复、声音只放行提醒提示音、朗读闭嘴、喝水提醒顺延,以及专注
时原来漏掉的闲置自语现在也归 _hush() 管。
"""
import time
import unittest
from unittest.mock import Mock, patch

import pet

REAL_LOCALTIME = time.localtime   # 打桩 time.localtime 时,桩里要用真的那个


def at(y, mo, d, h, mi=0):
    """本机时区里某个时刻的时间戳(CI 在 UTC 跑,本机可能在东八区,都成立)。"""
    return time.mktime((y, mo, d, h, mi, 0, 0, 0, -1))


def dnd_pet(until=0.0, night=False, skip=None):
    """造一只壳桌宠:只有勿扰用得到的字段,不跑 __init__。"""
    p = pet.Pet.__new__(pet.Pet)
    p.dnd_until = until
    p.night_dnd = night
    p.settings = {} if skip is None else {"night_skip": skip}
    p.pomo = None
    p.save_settings = Mock()
    p._reply = Mock()
    p.say = Mock()
    return p


class PredicateTests(unittest.TestCase):
    def test_manual_timer(self):
        p = dnd_pet(until=1000.0)
        self.assertTrue(p.dnd_active(999.0))
        self.assertFalse(p.dnd_active(1000.0))

    def test_night_window_edges(self):
        p = dnd_pet(night=True)
        self.assertTrue(p.dnd_active(at(2026, 9, 27, 23, 0)))
        self.assertTrue(p.dnd_active(at(2026, 9, 28, 6, 59)))
        self.assertFalse(p.dnd_active(at(2026, 9, 28, 7, 0)))
        self.assertFalse(p.dnd_active(at(2026, 9, 27, 22, 59)))
        self.assertFalse(dnd_pet(night=False).dnd_active(at(2026, 9, 27, 23, 30)))

    def test_night_key_belongs_to_the_evening_it_started(self):
        key = pet.Pet._night_key
        self.assertEqual(key(time.localtime(at(2026, 9, 27, 23, 30))), "2026-09-27")
        self.assertEqual(key(time.localtime(at(2026, 9, 28, 2, 0))), "2026-09-27")
        self.assertEqual(key(time.localtime(at(2026, 10, 1, 1, 0))), "2026-09-30")
        self.assertIsNone(key(time.localtime(at(2026, 9, 28, 12, 0))))

    def test_skip_only_covers_that_night(self):
        p = dnd_pet(night=True, skip="2026-09-27")
        self.assertFalse(p.dnd_active(at(2026, 9, 27, 23, 30)))
        self.assertFalse(p.dnd_active(at(2026, 9, 28, 3, 0)))
        self.assertTrue(p.dnd_active(at(2026, 9, 28, 23, 30)), "第二晚照常勿扰")

    def test_survives_stub_pet(self):
        """say() 经 _hush() 调到这里;别的壳桌宠没有这些字段,必须是 False 而不是崩。"""
        bare = pet.Pet.__new__(pet.Pet)
        self.assertFalse(bare.dnd_active())
        self.assertFalse(bare._hush())

    def test_hush_covers_focus_and_dnd(self):
        now = 5000.0
        with patch.object(pet.time, "time", return_value=now):
            p = dnd_pet()
            self.assertFalse(p._hush())
            p.pomo = {"phase": "focus", "due": now + 600, "mins": 25}
            self.assertTrue(p._hush(), "专注时闲置自语也该闭嘴")
            p.pomo = None
            p.dnd_until = now + 60
            self.assertTrue(p._hush())


class ToggleTests(unittest.TestCase):
    def test_start_sets_timer_saves_and_replies(self):
        p = dnd_pet()
        with patch.object(pet.time, "time", return_value=1000.0):
            p.start_dnd(30)
        self.assertEqual(p.dnd_until, 1000.0 + 30 * 60)
        p.save_settings.assert_called_once()
        self.assertIn("提醒", p._reply.call_args[0][0])

    def test_start_clamps_duration(self):
        p = dnd_pet()
        with patch.object(pet.time, "time", return_value=0.0):
            p.start_dnd(0)
            self.assertEqual(p.dnd_until, 60.0)
            p.start_dnd(10_000)
            self.assertEqual(p.dnd_until, 12 * 3600.0)

    def test_end_during_night_skips_only_tonight(self):
        now = at(2026, 9, 28, 1, 0)
        p = dnd_pet(until=now + 600, night=True)
        with patch.object(pet.time, "time", return_value=now), \
                patch.object(pet.time, "localtime",
                             side_effect=lambda t=None: REAL_LOCALTIME(now if t is None else t)):
            p.end_dnd()
            self.assertEqual(p.dnd_until, 0.0)
            self.assertEqual(p.settings["night_skip"], "2026-09-27")
            self.assertFalse(p.dnd_active())
        p.save_settings.assert_called_once()

    def test_end_when_not_active_says_so(self):
        p = dnd_pet()
        noon = at(2026, 9, 28, 12, 0)
        with patch.object(pet.time, "localtime",
                          side_effect=lambda t=None: REAL_LOCALTIME(noon if t is None else t)):
            p.end_dnd()
        self.assertNotIn("night_skip", p.settings)
        self.assertIn("没有", p._reply.call_args[0][0])

    def test_night_toggle_clears_skip_and_persists(self):
        p = dnd_pet(night=True, skip="2026-09-27")
        p.toggle_night_dnd()
        self.assertFalse(p.night_dnd)
        self.assertNotIn("night_skip", p.settings)
        p.save_settings.assert_called_once()

    def test_end_text_takes_the_later_of_timer_and_night(self):
        now = at(2026, 9, 28, 1, 0)
        p = dnd_pet(until=now + 30 * 60, night=True)
        self.assertEqual(p._dnd_end_text(now), "07:00", "夜间时段比手动定时更晚结束")
        p = dnd_pet(until=at(2026, 9, 28, 8, 30), night=True)
        self.assertEqual(p._dnd_end_text(now), "08:30")
        p = dnd_pet(until=at(2026, 9, 28, 15, 30))
        self.assertEqual(p._dnd_end_text(at(2026, 9, 28, 14, 0)), "15:30")
        p = dnd_pet(night=True)   # 月底跨月:9 月 30 日晚 -> 10 月 1 日早上
        self.assertEqual(p._dnd_end_at(at(2026, 9, 30, 23, 30)), at(2026, 10, 1, 7, 0))

    def test_tray_toggles(self):
        p = dnd_pet()
        p.start_dnd, p.end_dnd = Mock(), Mock()
        p._tray_dnd()
        p.start_dnd.assert_called_once_with(60)
        p.dnd_until = time.time() + 600
        p._tray_dnd()
        p.end_dnd.assert_called_once()


class QuietOutputTests(unittest.TestCase):
    def _sfx(self, hush):
        s = pet.SFX.__new__(pet.SFX)
        s.root = Mock()
        s.enabled = True
        s._n, s._next_any, s._next, s._chan = 0, 0.0, {}, {}
        s.groups = {"boing": ["b.wav"], "notify": ["n.wav"]}
        s.hush = hush
        return s

    def test_sfx_only_lets_reminder_chime_through(self):
        with patch.object(pet, "mci", return_value=(0, "1000")):
            s = self._sfx(lambda: True)
            self.assertFalse(s.play("boing"))
            self.assertTrue(s.play("notify"))
            s = self._sfx(lambda: False)
            self.assertTrue(s.play("boing"))
            s = self._sfx(None)       # 没接勿扰的 SFX 照旧
            self.assertTrue(s.play("boing"))

    def test_tts_is_silent_during_dnd(self):
        p = dnd_pet(until=time.time() + 600)
        p.tts_on = p.sound_on = True
        with patch.object(pet.threading, "Thread") as thread:
            p._speak("你好")
        thread.assert_not_called()

    def test_say_is_shortened_during_dnd(self):
        now = 5000.0
        p = pet.Pet.__new__(pet.Pet)
        p.dnd_until = now + 600
        with patch.object(pet.time, "time", return_value=now):
            pet.Pet.say(p, "很长的一句话" * 10)
            self.assertLessEqual(p.bubble[1] - now, 2.2 + 1e-6)
            pet.Pet.say(p, "很长的一句话" * 10, keep=True)
            self.assertGreater(p.bubble[1] - now, 2.2, "keep=True(提醒/AI 回答)不受限")

    def test_water_waits_until_dnd_ends(self):
        p = dnd_pet(until=2000.0)
        p.water_min, p.water_next = 30, 1000.0
        p._fire_reminder = Mock()
        p._water_tick(1500.0)
        p._fire_reminder.assert_not_called()
        self.assertEqual(p.water_next, 1560.0)
        p._water_tick(2010.0)
        p._fire_reminder.assert_called_once()
        self.assertEqual(p.water_next, 2010.0 + 30 * 60)


if __name__ == "__main__":
    unittest.main()
