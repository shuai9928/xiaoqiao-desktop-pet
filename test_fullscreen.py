"""全屏避让回归;不创建窗口,不读写用户存档,不调用真实 Windows 通知状态。

小乔默认置顶,全屏看视频、玩游戏或放幻灯片时会一直挡在画面上。这套用例
钉住:Windows 说"不该打扰"时她躲起来,全屏结束自己回来;托盘手动隐藏、
主人把她叫出来、聊天窗开着、提醒和番茄钟到点,这几种情况都不能被避让逻辑
搅乱。
"""
import unittest
from unittest.mock import Mock, patch

import pet

BUSY, NORMAL = 2, 5      # QUNS_BUSY / QUNS_ACCEPTS_NOTIFICATIONS


class FakeRoot:
    def __init__(self):
        self._state = "normal"

    def state(self):
        return self._state

    def withdraw(self):
        self._state = "withdrawn"

    def deiconify(self):
        self._state = "normal"


def fs_pet(fs_avoid=True):
    """造一只壳桌宠:只有全屏避让用得到的字段,不跑 __init__。"""
    p = pet.Pet.__new__(pet.Pet)
    p.root = FakeRoot()
    p.fs_avoid = fs_avoid
    p._fs_next = 0.0
    p._fs_streak = 0
    p._fs_hidden = False
    p._fs_user_shown = False
    p.state = "idle"
    p.pomo = None
    p.chatbox = None
    p.close_action_card = Mock()
    p.save_settings = Mock()
    p.say = Mock()
    return p


class FullscreenAvoidTests(unittest.TestCase):
    def setUp(self):
        self.ns = patch.object(pet.Pet, "_notification_state", return_value=NORMAL)
        self.mine = patch.object(pet.Pet, "_foreground_is_mine", return_value=False)
        self.state = self.ns.start()
        self.mine.start()
        self.addCleanup(self.ns.stop)
        self.addCleanup(self.mine.stop)
        self.now = 1000.0

    def tick(self, p, n=1):
        for _ in range(n):
            self.now += pet.Pet.FS_POLL
            p._fs_tick(self.now)

    def test_step_needs_consecutive_quiet_samples(self):
        step = pet.Pet._fs_step
        self.assertEqual(step(0, True), (1, False))
        self.assertEqual(step(1, True), (2, True))
        self.assertEqual(step(2, False), (0, False))

    def test_hides_after_streak_and_returns_when_fullscreen_ends(self):
        p = fs_pet()
        self.state.return_value = BUSY
        self.tick(p)
        self.assertEqual(p.root.state(), "normal", "一次采样就躲,切窗口一闪也会消失")
        self.tick(p)
        self.assertEqual(p.root.state(), "withdrawn")
        self.assertTrue(p._fs_hidden)
        p.close_action_card.assert_called()
        self.state.return_value = NORMAL
        self.tick(p)
        self.assertEqual(p.root.state(), "normal")
        self.assertFalse(p._fs_hidden)

    def test_samples_are_throttled(self):
        p = fs_pet()
        self.state.return_value = BUSY
        p._fs_tick(self.now)
        p._fs_tick(self.now + 0.1)
        p._fs_tick(self.now + 0.2)
        self.assertEqual(p._fs_streak, 1)

    def test_other_quiet_states_do_not_hide(self):
        """1=锁屏/屏保、6=安静时段、7=商店应用:不是全屏画面,不躲。"""
        for code in (None, 1, 5, 6, 7):
            p = fs_pet()
            self.state.return_value = code
            self.tick(p, 3)
            self.assertEqual(p.root.state(), "normal", code)

    def test_manual_tray_hide_is_left_alone(self):
        p = fs_pet()
        p.toggle_visible()                  # 托盘手动隐藏
        self.state.return_value = BUSY
        self.tick(p, 3)
        self.state.return_value = NORMAL
        self.tick(p, 2)
        self.assertEqual(p.root.state(), "withdrawn", "全屏结束不该把手动隐藏的她放出来")
        self.assertFalse(p._fs_hidden)

    def test_tray_show_during_fullscreen_sticks_until_it_ends(self):
        p = fs_pet()
        self.state.return_value = BUSY
        self.tick(p, 2)
        p.toggle_visible()                  # 主人从托盘把她叫出来
        self.assertEqual(p.root.state(), "normal")
        self.tick(p, 4)
        self.assertEqual(p.root.state(), "normal", "同一次全屏里不该再躲")
        self.state.return_value = NORMAL
        self.tick(p)
        self.state.return_value = BUSY
        self.tick(p, 2)
        self.assertEqual(p.root.state(), "withdrawn", "下一次全屏照常避让")

    def test_open_chat_or_own_foreground_or_magic_blocks_hiding(self):
        p = fs_pet()
        p.chatbox = Mock()
        p.chatbox.win.winfo_exists.return_value = True
        p.chatbox.win.winfo_ismapped.return_value = True
        self.state.return_value = BUSY
        self.tick(p, 3)
        self.assertEqual(p.root.state(), "normal")
        p = fs_pet()
        p.state = "magic"
        self.tick(p, 3)
        self.assertEqual(p.root.state(), "normal")
        p = fs_pet()
        with patch.object(pet.Pet, "_foreground_is_mine", return_value=True):
            self.tick(p, 3)
        self.assertEqual(p.root.state(), "normal")

    def test_setting_off_releases_and_stops_hiding(self):
        p = fs_pet()
        self.state.return_value = BUSY
        self.tick(p, 2)
        self.assertTrue(p._fs_hidden)
        p.fs_avoid = False
        self.tick(p)
        self.assertEqual(p.root.state(), "normal")
        self.tick(p, 3)
        self.assertEqual(p.root.state(), "normal")

    def test_due_pomodoro_brings_her_back(self):
        p = fs_pet()
        self.state.return_value = BUSY
        self.tick(p, 2)
        p.pomo = {"phase": "focus", "due": self.now, "mins": 25}
        self.tick(p)
        self.assertEqual(p.root.state(), "normal")
        self.tick(p, 3)
        self.assertEqual(p.root.state(), "normal", "番茄钟播报要看得见,这次全屏里不再躲")

    def test_reminder_brings_her_back(self):
        p = fs_pet()
        self.state.return_value = BUSY
        self.tick(p, 2)
        p.sfx = Mock()
        for name in ("wake_if_sleep", "_reply", "star_burst", "hop"):
            setattr(p, name, Mock())
        p._fire_reminder("喝水")
        self.assertEqual(p.root.state(), "normal")
        self.assertTrue(p._fs_user_shown)
        p._reply.assert_called_once()

    def test_toggle_persists_and_resets_streak(self):
        p = fs_pet()
        p._fs_streak = 1
        p.toggle_fs_avoid()
        self.assertFalse(p.fs_avoid)
        self.assertEqual(p._fs_streak, 0)
        p.save_settings.assert_called_once()


if __name__ == "__main__":
    unittest.main()
