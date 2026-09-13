"""真实 Tk 控件回归;使用模拟桌宠,不读取存档或调用 AI。"""
import sys
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from pet import ChatBox, Pet, InteractionCard


def make_card_pet(root):
    p = Pet.__new__(Pet)
    p.root, p.sw, p.sh, p.star, p.state = root,1366,768,76,'idle'
    p.action_card = None
    p.companion_days = lambda:12
    p.affection_level = lambda:'亲密伙伴'
    for name in ('open_chat','eat_candy','cast_magic','start_dance','throw_ball','wake_up','go_sleep','_show_full_menu'):
        setattr(p,name,Mock())
    return p


class CardUITests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.p = make_card_pet(self.root)
        self.area = patch('pet.work_area_at', return_value=(0,0,1366,728))
        self.area.start()
        self.addCleanup(self.area.stop)

    def tearDown(self):
        self.p.close_action_card()
        self.root.destroy()

    def open(self):
        self.p.open_action_card(1200,700)
        self.root.update()
        self.assertIsNotNone(self.p.action_card)
        return self.p.action_card

    def test_single_instance_and_close_before_action(self):
        first = self.open()
        second = self.open()
        self.assertTrue(first.closed)
        self.assertIsNot(first,second)
        self.p.eat_candy.side_effect = lambda:self.assertIsNone(self.p.action_card)
        second.buttons['喂糖'].invoke()
        self.p.eat_candy.assert_called_once()
        self.assertIsNone(self.p.action_card)

    def test_sleep_button_refresh_and_keyboard_dispatch(self):
        c = self.open()
        self.p.state = 'yawn'
        c.win.after_cancel(c._refresh_id)
        c._refresh()
        self.assertEqual(c.buttons['睡觉']['text'],'叫醒')
        c.buttons['睡觉'].focus_force()
        self.root.update()
        c.buttons['睡觉'].event_generate('<Return>')
        self.root.update()
        self.p.wake_up.assert_called_once()
        self.assertIsNone(self.p.action_card)

    def test_bounds_include_negative_monitor_coordinates(self):
        for area in ((0,0,800,560),(-1920,-100,0,980),(1920,0,3840,1040)):
            x,y = InteractionCard.position(area[2]-1,area[3]-1,320,384,area)
            self.assertGreaterEqual(x,area[0]+8)
            self.assertGreaterEqual(y,area[1]+8)
            self.assertLessEqual(x+320,area[2]-8)
            self.assertLessEqual(y+384,area[3]-8)
        with patch('pet.work_area_at',return_value=(-1920,-200,0,880)):
            self.p.open_action_card(-1500,-120)
            self.root.update_idletasks()
            c = self.p.action_card
            self.assertEqual(c.win.winfo_x(),-1492)
            self.assertEqual(c.win.winfo_y(),-112)

    def test_escape_and_more_release_card(self):
        c = self.open()
        c.win.event_generate('<Escape>')
        self.root.update()
        self.assertIsNone(self.p.action_card)
        c = self.open()
        c._more()
        self.p._show_full_menu.assert_called_once()
        self.assertIsNone(self.p.action_card)

    def test_losing_focus_closes_and_failed_build_falls_back(self):
        c = self.open()
        with patch.object(c.win,'focus_displayof',return_value=None):
            c._check_focus()
        self.assertTrue(c.closed)
        with patch('pet.InteractionCard',side_effect=RuntimeError('test build failure')), patch('traceback.print_exc'):
            self.p.open_action_card(20,30)
        self.p._show_full_menu.assert_called_once_with(20,30)

    def test_tab_moves_focus_inside_card(self):
        c = self.open()
        c.buttons['聊天'].event_generate('<Tab>')
        self.root.update()
        self.assertEqual(c.win.focus_get(),c.buttons['喂糖'])
        self.assertIs(self.p.action_card,c)

    def test_busy_actions_disable_then_recover(self):
        self.p.state = 'magic'
        c = self.open()
        self.assertEqual(str(c.buttons['喂糖']['state']),'disabled')
        self.assertEqual(str(c.buttons['时间魔法']['state']),'disabled')
        self.assertEqual(str(c.buttons['聊天']['state']),'normal')
        c._show_hint('喂糖')
        self.assertIn('魔法结束',c.cv.itemcget(c.hint,'text'))
        self.p.state = 'idle'
        c.win.after_cancel(c._refresh_id)
        c._refresh()
        self.assertEqual(str(c.buttons['喂糖']['state']),'normal')
        self.assertIn('40',c.cv.itemcget(c.hint,'text'))

    def test_click_rechecks_state_before_next_refresh(self):
        c = self.open()
        self.p.state = 'eat'
        c.buttons['喂糖'].invoke()
        self.p.eat_candy.assert_not_called()
        self.assertFalse(c.closed)
        self.assertIn('吃完',c.cv.itemcget(c.hint,'text'))

    def test_closed_card_does_not_replay_queued_action(self):
        c = self.open()
        c._run(self.p.eat_candy,'喂糖')
        c._run(self.p.eat_candy,'喂糖')
        self.p.eat_candy.assert_called_once()


def make_chat(root):
    p = SimpleNamespace(root=root, sh=768, sw=1366, x=1000, fy=700, H=520,
                        brain=None, chat_log=[], companion_days=lambda: 12,
                        pet_head=Mock(), eat_candy=Mock(), start_wave=Mock(), ask_ai=Mock())
    return ChatBox(p)


class ChatUITests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.chat = make_chat(self.root)
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def test_layout_fits_small_and_large_screens(self):
        for width, height in ((800, 600), (1280, 720), (1366, 768), (1920, 1080), (3840, 2160)):
            u, w, h, tail = ChatBox._layout(width, height)
            self.assertLessEqual(w+32, width)
            self.assertLessEqual(h+tail+60, height)
            self.assertGreater(h-114*u-94*u, 200)
        entry = self.chat.entry
        self.assertLess(entry.winfo_rooty()+entry.winfo_height(), 768)

    def test_send_state_and_history(self):
        c = self.chat
        self.assertEqual(str(c.send_btn['state']), 'disabled')
        c.draft.set('  ')
        self.assertEqual(str(c.send_btn['state']), 'disabled')
        c.draft.set('今晚想看星星')
        self.assertEqual(str(c.send_btn['state']), 'normal')
        c.send_btn.invoke()
        c.pet.ask_ai.assert_called_once_with('今晚想看星星')
        self.assertEqual(c.hist, ['今晚想看星星'])
        self.assertEqual(c.draft.get(), '')
        self.assertEqual(str(c.send_btn['state']), 'disabled')

    def test_reading_history_is_not_interrupted_by_reply(self):
        c = self.chat
        for i in range(70):
            c.log_reply(f'第 {i} 条测试消息,星光落在窗边。')
        self.root.update()
        c.log.yview_moveto(0)
        self.root.update()
        c.log_reply('新回复')
        self.root.update()
        self.assertLess(c.log.yview()[0], .05)
        c.log_user('继续聊')
        self.root.update()
        self.assertGreater(c.log.yview()[1], .99)

    def test_quick_buttons_dispatch_the_correct_action(self):
        c = self.chat
        buttons = [child for frame in c.win.winfo_children()
                   for child in frame.winfo_children() if isinstance(child, tk.Button)]
        for label, method in (('摸摸头', c.pet.pet_head), ('喂颗糖', c.pet.eat_candy),
                              ('挥挥手', c.pet.start_wave)):
            next(b for b in buttons if b['text'] == label).invoke()
            method.assert_called_once()


if __name__ == '__main__':
    if '--card-preview' in sys.argv:
        root = tk.Tk()
        root.withdraw()
        p = make_card_pet(root)
        p.open_action_card(500,200)
        p.action_card.win.overrideredirect(False)
        p.action_card.win.title('小乔互动卡片（测试预览）')
        root.after(240000,root.destroy)
        root.mainloop()
    elif '--preview' in sys.argv:
        root = tk.Tk()
        root.withdraw()
        c = make_chat(root)
        c.win.overrideredirect(False)  # 测试预览供窗口捕获,产品仍保留无边框外观。
        c.win.attributes('-transparentcolor', '')
        c.win.title('小乔界面预览（测试）')
        c.log_user('今晚想看星星。')
        c.log_reply('那就陪你待一会儿~ 点一下「挥挥手」,让我跟你打个招呼。')
        root.after(240000, root.destroy)
        root.mainloop()
    else:
        unittest.main()
