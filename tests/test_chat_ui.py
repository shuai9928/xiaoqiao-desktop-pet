"""真实 Tk 控件回归;使用模拟桌宠,不读取存档或调用 AI。"""
import sys
import time
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
    for name in ('open_chat','open_ai_panel','open_room_preview','eat_candy','wake_up','go_sleep','_show_full_menu'):
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
        self.assertNotIn('时间魔法', c.buttons)
        self.assertEqual(str(c.buttons['小屋']['state']),'normal')
        self.assertEqual(str(c.buttons['聊天']['state']),'normal')
        c._show_hint('喂糖')
        self.assertIn('动作结束',c.cv.itemcget(c.hint,'text'))
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
                        pet_head=Mock(), eat_candy=Mock(), open_ai_panel=Mock(), ask_ai=Mock())
    return ChatBox(p)


class ChatUITests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.chat = make_chat(self.root)
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def test_background_is_cached_and_identical_to_fresh_render(self):
        # 背景图只跟尺寸有关:缓存命中要和现画逐像素一样,同尺寸复用同一张
        _, w, h, tail = ChatBox._layout(1366, 768)
        ChatBox._BG_CACHE.clear()
        fresh = ChatBox._render_bg(None, w, h, tail)
        ChatBox.prewarm_bg(1366, 768)
        cached = ChatBox.cached_bg(w, h, tail)
        self.assertIs(cached, ChatBox.cached_bg(w, h, tail))
        self.assertEqual(cached.tobytes(), fresh.tobytes())
        # 最多留两种尺寸
        ChatBox.prewarm_bg(1920, 1080)
        ChatBox.prewarm_bg(3840, 2160)
        self.assertLessEqual(len(ChatBox._BG_CACHE), 2)

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

    def test_repeated_lines_are_counted_not_repeated(self):
        c = self.chat
        for _ in range(4):
            c.log_reply('该喝水啦!顺便起来动一动~')
        text = c.log.get('1.0', 'end')
        self.assertEqual(text.count('该喝水啦'), 1)
        self.assertIn('×4', text)
        self.assertNotIn('×3', text)
        c.log_reply('换一句')
        c.log_reply('该喝水啦!顺便起来动一动~')       # not consecutive: shown again
        self.assertEqual(c.log.get('1.0', 'end').count('该喝水啦'), 2)
        c.log_user('好')
        c.log_user('好')                            # your own words are never merged
        self.assertEqual(c.log.get('1.0', 'end').count('好\n'), 2)

    def test_bubbles_left_and_right_with_one_time_stamp_per_stretch(self):
        c = self.chat
        def stamps():
            return len(c.log.tag_ranges('stamp')) // 2
        before = stamps()
        c.log_reply('第一句')
        c.log_reply('第二句')
        c.log_user('我说')
        self.assertEqual(stamps() - before, 1)               # one time label for the stretch
        self.assertEqual(c.log.tag_cget('user', 'justify'), 'right')
        self.assertEqual(c.log.tag_cget('qiao', 'justify'), 'left')
        self.assertIn('user', c.log.tag_names(c.log.search('我说', '1.0', elide=True)))
        self.assertGreaterEqual(len(c.log.image_names()), 3)  # each line is a bubble image
        c.log_reply('隔了很久', time.time() + 3600)
        self.assertEqual(stamps() - before, 2)               # a long gap gets a new time label

    def test_repeat_after_a_long_gap_is_a_new_bubble(self):
        c = self.chat
        now = time.time()
        c.log_reply('该喝水啦', now)
        c.log_reply('该喝水啦', now + 4000)
        self.assertEqual(c.log.get('1.0', 'end').count('该喝水啦'), 2)
        self.assertNotIn('×2', c.log.get('1.0', 'end'))

    def test_thinking_bubble_stays_last_and_is_not_copied(self):
        c = self.chat
        c.pet.ai_thinking = True
        c.show_typing(True)
        c.log_user('还有一个问题')
        text = c.log.get('1.0', 'end')
        self.assertLess(text.index('还有一个问题'), text.index('小乔正在想'))
        c.log_reply('她顺口说的一句')                      # not the answer: dots come back
        text = c.log.get('1.0', 'end')
        self.assertLess(text.index('她顺口说的一句'), text.index('小乔正在想'))
        self.assertNotIn('小乔正在想', c._text_without_typing())
        c.pet.ai_thinking = False
        c.show_typing(False)

    def test_thinking_line_shows_while_waiting_and_gives_way_to_the_answer(self):
        c = self.chat
        c.pet.ai_thinking = False
        c.pet.ask_ai.side_effect = lambda text: setattr(c.pet, 'ai_thinking', True)
        c.draft.set('今晚月亮圆吗')
        c.send()
        self.root.update()
        self.assertIn('小乔正在想', c.log.get('1.0', 'end'))
        c.pet.ai_thinking = False
        c.log_reply('今晚是上弦月哦~')
        text = c.log.get('1.0', 'end')
        self.assertNotIn('小乔正在想', text)
        self.assertIn('今晚是上弦月哦~', text)
        # a failed request (no reply ever comes) also clears it by itself
        c.pet.ai_thinking = True
        c.show_typing(True)
        c.pet.ai_thinking = False
        c._typing_tick(1)
        self.assertNotIn('小乔正在想', c.log.get('1.0', 'end'))
        self.assertIsNone(c._typing)

    def test_opens_beside_the_room_instead_of_over_it(self):
        self.chat.close()
        p = SimpleNamespace(root=self.root, sh=768, sw=1366, x=100, fy=700, H=520,
                            state='swing', _swing={'rect': (700, 100, 1100, 600)},
                            brain=None, chat_log=[], companion_days=lambda: 12,
                            pet_head=Mock(), eat_candy=Mock(), open_ai_panel=Mock(), ask_ai=Mock())
        with patch('pet.work_area_at', return_value=(0, 0, 1366, 728)):
            c = ChatBox(p)
        self.root.update()
        x, w = c.win.winfo_x(), c.win.winfo_width()
        self.assertTrue(x + w <= 700 or x >= 1100, (x, w))
        c.close()

    def test_quick_buttons_dispatch_the_correct_action(self):
        c = self.chat
        buttons = [child for frame in c.win.winfo_children()
                   for child in frame.winfo_children() if isinstance(child, tk.Button)]
        for label, method in (('摸摸头', c.pet.pet_head), ('喂颗糖', c.pet.eat_candy),
                              ('AI 工作信息', c.pet.open_ai_panel)):
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
