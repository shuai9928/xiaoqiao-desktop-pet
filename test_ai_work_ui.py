"""UI tests with synthetic snapshots, no source scans or model calls."""
import time
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import ImageDraw, Image

from ai_work_ui import AIWorkPanel, panel_position, render_content, trace_slice
from pet import Pet, trace_rows


def owner(root=None):
    p = Pet.__new__(Pet)
    p.root = root
    p.sw, p.sh, p.topmost = 1366, 768, True
    p.glow_cache = {}
    p._trace_snap = None
    p._trace_sid = 'test'
    p._trace_page = p._session_page = 0
    p._trace_expand = set()
    p._book_new_seen = {}
    p._book_open = True
    p._book_anim = 1
    p._book_sel = None
    p._book_tab = 'trace'
    p._copied_until = 0
    p.ai_mute_sess = set()
    p.ai_mute_sources = set()
    p._ai_sessions = []
    p.ui_reduced_anim = True
    p.last_interact = 0
    p.save_settings = Mock()
    return p


def snapshot(count=31):
    now = 1791081600.0
    actions = [{'a': f'检查步骤 {i}', 'r': f'结果 {i}', 't': now-i*60}
               for i in range(count)]
    actions.insert(4, {'turn': 1, 't': now-230})
    session = {'id': 'test', 'agent': 'zcode', 'title': '小乔界面打磨',
               'state': 'running', 'updated': now, 'actions': actions}
    return {'now': now, 'sources': [('zcode', 'ZCode', 'Z'), ('claude', 'Claude', 'C')],
            'sel_key': 'zcode', 'sel_session': session, 'sessions': [session],
            'book_tab': 'trace', 'quota': None, 'quota_age': None, 'mock': True,
            'book_rect': (12, 12, 400, 520), 'book_anim': 1, 'new_n': 0}


class LayoutTests(unittest.TestCase):
    def test_all_pages_include_every_record_and_turn_once(self):
        rows = trace_rows({'actions': snapshot()['sel_session']['actions']}, 48)
        for capacity in (3, 4, 6):
            p, pages, _ = trace_slice(rows, 0, capacity)
            seen = []
            for page in range(pages):
                _, _, result = trace_slice(rows, page, capacity)
                seen.extend(index for index, _ in result)
            self.assertEqual(sorted(seen), list(range(len(rows))))
            self.assertEqual(len(seen), len(set(seen)))
            self.assertEqual(trace_slice(rows, 100, capacity)[0], pages-1)

    def test_long_content_is_not_cut_before_display_or_copy(self):
        action = '完整步骤 '*80
        result = '完整结果 '*110
        row = trace_rows({'actions': [{'a': action, 'r': result, 't': 1}]}, 48)[0]
        self.assertEqual(row[2], action)
        self.assertEqual(row[3], result)

    def test_interactive_targets_are_large_separated_and_in_bounds(self):
        p = owner()
        for key in ('zcode', 'claude'):
            for tab in ('trace', 'overview'):
                for height in (520, 480):
                    ui = snapshot()
                    ui.update(sel_key=key, book_tab=tab, new_n=3,
                              sources=[('zcode','ZCode','Z'), ('mac-claude','Claude·Mac','M'),
                                       ('mac-codex','Codex·Mac','C'), ('wslcodex','Codex·WSL','W'),
                                       ('claude','Claude','C')],
                              quota={'fh':32, 'sd':58, 'reset_est': ui['now']+3600}, quota_age=7200)
                    image, hits = render_content(p, ui, 400, height)
                    targets = [r for r in hits if r[4] != 'swallow']
                    for i, (x,y,w,h,kind,data) in enumerate(targets):
                        self.assertGreaterEqual(w,32,(tab,kind))
                        self.assertGreaterEqual(h,32,(tab,kind))
                        self.assertGreaterEqual(min(x,y),0,(tab,kind))
                        self.assertLessEqual(x+w,400,(tab,kind))
                        self.assertLessEqual(y+h,height,(tab,kind))
                        for ox,oy,ow,oh,ok,_ in targets[i+1:]:
                            self.assertFalse(x < ox+ow and ox < x+w and y < oy+oh and oy < y+h,
                                             (tab,key,kind,ok))

    def test_side_position_avoids_character_and_clamps_negative_monitors(self):
        for scene, area in (((500,100,413,413),(0,0,1920,1040)),
                            ((-1700,-50,413,413),(-1920,-100,0,980)),
                            ((760,520,400,400),(0,0,1366,728)),
                            ((0,0,314,314),(0,0,800,568))):
            w,h=424,544
            x,y=panel_position(scene,(w,h),area)
            self.assertGreaterEqual(x,area[0]+8)
            self.assertGreaterEqual(y,area[1]+8)
            self.assertLessEqual(x+w,area[2]-8)
            self.assertLessEqual(y+h,area[3]-8)
        x,y=panel_position((500,100,413,413),(424,544),(0,0,1920,1040))
        self.assertGreaterEqual(x,913)

    def test_trace_page_buttons_keep_absolute_record_identity(self):
        p=owner()
        ui=snapshot()
        for page in (0,1,2):
            p._trace_page=page
            _,hits=render_content(p,ui,400,520)
            for x,y,w,h,kind,payload in hits:
                if kind=='detail':
                    sid,index,action,result=payload
                    actual=trace_rows({'actions':ui['sel_session']['actions']},48)[index]
                    self.assertEqual((action,result),(actual[2],actual[3]))
                    self.assertEqual(sid,'test')

    def test_state_labels_distinguish_expired_and_disconnected_sources(self):
        import ai_work_ui
        from pet import CRYSTAL_COLORS
        self.assertEqual(CRYSTAL_COLORS['running'], (193,154,239))    # board lilac, same as the lights
        for stale, age, expected in ((False,30,'运行中'), (False,2500,'久未更新'),
                                     (True,30,'离线')):
            ui=snapshot()
            ui['sel_session']=dict(ui['sel_session'],stale=stale,updated=ui['now']-age)
            seen=[]
            original=ImageDraw.ImageDraw.text
            def record(draw, xy, value, *args, **kwargs):
                seen.append(value)
                return original(draw, xy, value, *args, **kwargs)
            with patch.object(ImageDraw.ImageDraw,'text',record):
                render_content(owner(),ui,400,520)
            self.assertIn(expected,seen)

    def test_unknown_quota_cycle_is_not_presented_as_zero_or_full(self):
        ui=snapshot()
        ui.update(sel_key='claude',sel_session=None,book_tab='overview',
                  quota={'fh':None,'sd':25},quota_age=60)
        seen=[]
        original=ImageDraw.ImageDraw.text
        def record(draw, xy, value, *args, **kwargs):
            seen.append(value)
            return original(draw, xy, value, *args, **kwargs)
        with patch.object(ImageDraw.ImageDraw,'text',record):
            render_content(owner(),ui,400,520)
        self.assertIn('数据未知',seen)
        self.assertIn('75%',seen)
        self.assertIn('已用 25%',seen)
        self.assertNotIn('尚未接入',seen)


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk()
        self.root.withdraw()
        self.pet=owner(self.root)
        self.panel=self.pet._ai_work_panel=AIWorkPanel(self.pet)
        self.ui=snapshot()
        self.pet._ai_sessions=self.ui['sessions']
        self.panel.update(self.ui,(500,100,314,314),(0,0,1366,728))
        self.root.update()

    def tearDown(self):
        if not self.panel.closed:
            self.panel.close()
        self.root.destroy()

    def test_full_detail_copy_and_escape_preserve_trace_page(self):
        action,result='完整动作 '*100,'完整结果 '*120
        self.pet._trace_page=2
        self.pet._ui_hit('detail',('test',17,action,result))
        text=self.panel.detail_text.get('1.0','end-1c')
        self.assertIn(action,text)
        self.assertIn(result,text)
        with patch.object(self.root,'clipboard_clear'), patch.object(self.root,'clipboard_append') as append:
            self.panel.copy_button.invoke()
            append.assert_called_once_with((action+' → '+result).strip())
        self.panel._escape()
        self.assertIsNone(self.panel.detail)
        self.assertFalse(self.panel.closed)
        self.assertEqual(self.pet._trace_page,2)
        self.panel._escape()
        self.assertTrue(self.panel.closed)
        self.assertFalse(self.pet._book_open)

    def test_unchanged_state_reuses_image_and_close_leaves_no_timer(self):
        previous=self.panel._photo
        self.panel.update(self.ui,(500,100,314,314),(0,0,1366,728))
        self.assertIs(self.panel._photo,previous)
        self.panel.close()
        self.panel.update(self.ui,(500,100,314,314),(0,0,1366,728))
        self.root.update()
        self.assertTrue(self.panel.closed)

    def test_keyboard_and_mouse_dispatch_without_dragging_scene(self):
        self.panel._focus=-1
        self.panel._tab(SimpleNamespace(state=0))
        self.assertEqual(self.panel._focus,0)
        with patch.object(self.pet,'_ui_hit') as hit:
            self.panel._activate(None)
            self.assertEqual(hit.call_args.args[0],'close')
            target=next(t for t in self.panel._hits if t[4]=='tab' and t[5]=='overview')
            x,y,w,h,kind,payload=target
            self.panel._press(SimpleNamespace(x=x+w/2,y=y+h/2))
            hit.assert_called_with(kind,payload)

    def test_reading_detail_is_not_replaced_by_incoming_snapshot(self):
        self.panel.show_detail(('test',3,'正在阅读的完整动作','结果'))
        frame=self.panel.detail
        updated=dict(self.ui,new_n=5)
        self.panel.update(updated,(500,100,314,314),(0,0,1366,728))
        self.assertIs(self.panel.detail,frame)
        self.assertIn('正在阅读',self.panel.detail_text.get('1.0','end'))
        self.assertIsNone(self.panel._activate(None))

    def test_monitor_resize_preserves_open_text_and_copy(self):
        self.panel.show_detail(('test',3,'阅读内容 '*100,'完整结果'))
        frame=self.panel.detail
        before=self.panel.detail_text.get('1.0','end-1c')
        self.panel.resize((400,480),1.5)
        self.panel.update(self.ui,(500,100,314,314),(0,0,1920,1040))
        self.root.update()
        self.assertIs(self.panel.detail,frame)
        self.assertEqual(self.panel.detail_text.get('1.0','end-1c'),before)
        self.panel.resize((400,344),1.0)
        self.panel.update(self.ui,(100,0,314,314),(0,0,800,568))
        self.root.update()
        self.assertIs(self.panel.detail,frame)
        self.assertEqual(self.panel.detail_text.get('1.0','end-1c'),before)
        self.assertEqual(self.panel.size,(424,368))
        self.assertLessEqual(self.panel.win.winfo_y()+self.panel.win.winfo_height(),560)

    def test_parent_sync_reuses_then_closes_panel_without_canvas_overlay(self):
        scene={'scene_l':500,'scene_t':100,'scene_w':314,'scene_h':314}
        with patch('pet.work_area_at',return_value=(0,0,1366,728)):
            self.pet._sync_ai_panel(scene,self.ui)
            self.assertIs(self.pet._ai_work_panel,self.panel)
            self.assertTrue(self.ui['detached'])
            self.pet._book_open=False
            self.pet._sync_ai_panel(scene,self.ui)
            self.assertTrue(self.panel.closed)


if __name__=='__main__':
    unittest.main()
