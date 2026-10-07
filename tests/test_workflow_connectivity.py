"""Workflow/quota routing regression with synthetic files and snapshots only."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import ImageDraw

import pet
from ai_work_ui import render_content
from test_ai_work_ui import owner, snapshot
from test_session_lights import shell_pet, write_session, NOW


class WorkflowConnectivityTests(unittest.TestCase):
    def test_reader_keeps_all_48_acquired_actions_and_full_results(self):
        with tempfile.TemporaryDirectory() as folder:
            actions = [{'a': '完整步骤 '*90, 'r': '完整结果 '*120, 't': NOW-i}
                       for i in range(48)]
            write_session(folder, 'task.json', actions=actions, state='running')
            got = pet.scan_ai_sessions(folder, cap=None, now=NOW)[0]
            self.assertEqual(len(got['actions']), 48)
            self.assertEqual([{k:r[k] for k in ('a','r','t')} for r in got['actions']], actions)

    def test_old_running_record_never_takes_priority_over_fresh_work(self):
        sessions = [dict(id='old', agent='zcode', state='running', updated=NOW-5000),
                    dict(id='new', agent='mac-claude', state='waiting', updated=NOW-2)]
        sources = [('zcode','ZCode','Z'), ('mac-claude','Claude·Mac','M')]
        self.assertEqual(pet.pick_auto_source(sessions, sources, NOW), 'mac-claude')
        sessions[1]['agent'] = 'zcode'
        self.assertEqual(pet.select_work_session(sessions, 'zcode', NOW)['id'], 'new')

    def test_complete_workflow_list_is_not_limited_to_five_indicator_lights(self):
        with tempfile.TemporaryDirectory() as folder:
            for i in range(8):
                write_session(folder, f'task-{i}.json', agent='zcode', state='idle', updated=NOW-i)
            p = shell_pet(ai_states=None)
            with patch('pet.AI_SESSION_DIR', folder), patch('pet.time.time', return_value=NOW), \
                 patch('pet.read_claude_quota', return_value=None), \
                 patch('ai_quota.read_codex_quota', return_value=None), \
                 patch('pet.CODEX_QUOTA_FILE', str(Path(folder)/'quota.json')):
                p._scan_ai_sessions()
            self.assertEqual(len(p._ai_sessions), 5)
            self.assertEqual(len(p._ai_work_sessions), 8)

    def test_quota_account_switch_preserves_selected_workflow_and_reading(self):
        p = owner()
        p.state = 'swing'
        p.close_action_card = lambda: None
        p._book_sel = ('sid','test')
        p._trace_snap = [{'a':'currently reading'}]
        p._quota = None
        p._codex_quota = {'t':1}
        p._ui_hit('house_quota', 'overview')
        self.assertEqual((p._book_tab,p._quota_provider), ('overview','codex'))
        p._ui_hit('quota_provider','claude')
        self.assertEqual(p._book_sel, ('sid','test'))
        self.assertEqual(p._trace_snap, [{'a':'currently reading'}])

    def test_opening_workflow_from_quota_only_source_selects_actual_tasks(self):
        p = owner()
        p.state = 'swing'
        p.close_action_card = lambda: None
        p._book_sel = ('agent','claude')
        p._ai_sessions = snapshot()['sessions']
        p._ui_hit('house_trace','trace')
        self.assertEqual(p._book_tab, 'trace')
        self.assertIsNone(p._book_sel)

    def test_quota_read_failure_retains_last_snapshot_and_sets_error(self):
        p = shell_pet(ai_states=None)
        p._codex_quota = {'provider':'codex','t':NOW*1000,'cycles':[]}
        with tempfile.TemporaryDirectory() as folder:
            quota = Path(folder)/'quota.json'
            quota.write_text('{broken')
            with patch('pet.AI_SESSION_DIR', folder), patch('pet.time.time', return_value=NOW), \
                 patch('pet.read_claude_quota', return_value=None), \
                 patch('pet.CODEX_QUOTA_FILE', str(quota)):
                p._scan_ai_sessions()
        self.assertTrue(p._codex_quota_error)
        self.assertEqual(p._codex_quota['t'], NOW*1000)

    def test_quota_render_is_independent_of_task_and_restores_real_provider(self):
        ui = snapshot()
        ui.update(book_tab='overview', quota_provider='codex', mock=False,
                  codex_quota={'provider':'codex','t':ui['now']*1000,'cycles':[
                      {'minutes':300,'used':20,'reset':ui['now']+3600},
                      {'minutes':10080,'used':49,'reset':ui['now']+7*86400}]})
        seen=[]
        original = ImageDraw.ImageDraw.text
        def record(draw, xy, value, *args, **kw):
            seen.append(value)
            return original(draw, xy, value, *args, **kw)
        with patch.object(ImageDraw.ImageDraw,'text',record):
            _, hits = render_content(owner(), ui, 400, 520, 1.5)
        self.assertIn('80%', seen)
        self.assertIn('已用 20%', seen)
        self.assertIn('51%', seen)
        self.assertIn('已用 49%', seen)
        self.assertIn('Codex · 账户额度', seen)
        self.assertIn('用量快照 · 自动同步尚未接入', seen)
        self.assertEqual({hit[5] for hit in hits if hit[4]=='quota_provider'},
                         {'codex','claude','zcode'})

    def test_multiple_workflow_sessions_have_a_visible_switch(self):
        ui = snapshot()
        other = dict(ui['sel_session'], id='other', title='other task')
        ui['sessions'].append(other)
        _, hits = render_content(owner(), ui, 400, 520)
        self.assertIn('other', [h[5] for h in hits if h[4]=='session'])

    def test_native_and_unknown_real_sources_remain_selectable(self):
        sessions = [dict(agent='codex'),dict(agent='claude'),dict(agent='local-ai')]
        self.assertEqual([r[0] for r in pet.book_sources(sessions, None)],
                         ['codex','claude','local-ai'])

    def test_small_reader_targets_never_overlap_or_leave_the_page(self):
        ui = snapshot()
        sources = [('zcode','ZCode','Z'),('mac-claude','Claude·Mac','M'),
                   ('mac-codex','Codex·Mac','C'),('wslcodex','Codex·WSL','W')]
        ui['sources'] = sources
        ui['sessions'] += [dict(ui['sel_session'],id=key,agent=key) for key,_,_ in sources[1:]]
        ui['sessions'] += [dict(ui['sel_session'],id='second')]
        ui['new_n'] = 3
        p = owner()
        for height in (338,344,400,520):
            for tab in ('trace','overview'):
                p._trace_page=1
                ui['book_tab']=tab
                _,hits=render_content(p,ui,400,height)
                targets=[hit for hit in hits if hit[4]!='swallow']
                for i,(x,y,w,h,kind,_) in enumerate(targets):
                    self.assertLessEqual(y+h,height,(height,tab,kind))
                    self.assertLessEqual(x+w,400,(height,tab,kind))
                    for xx,yy,ww,hh,k,_ in targets[i+1:]:
                        self.assertFalse(x<xx+ww and xx<x+w and y<yy+hh and yy<y+h,
                                         (height,tab,kind,k))

    def test_bad_quota_timestamp_keeps_values_and_does_not_break_rendering(self):
        for field in ('t','reset'):
            ui = snapshot()
            ui.update(book_tab='overview',quota_provider='codex',mock=False,
                      codex_quota={'provider':'codex','t':ui['now']*1000,'cycles':[
                          {'minutes':300,'used':20,'reset':ui['now']+3600}]})
            if field=='t':
                ui['codex_quota']['t']=1e100
            else:
                ui['codex_quota']['cycles'][0]['reset']=1e100
            image,_=render_content(owner(),ui,400,520)
            self.assertEqual(image.size,(400,520))


if __name__=='__main__':
    unittest.main()
