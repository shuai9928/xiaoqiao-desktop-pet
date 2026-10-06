import copy
import unittest
from workflow_stages import stages, stage_title, RESEARCH, IMPLEMENT, VERIFY, GENERAL, DELEGATE, display_title, detail_steps
from test_moon_house import snapshot
from ai_lights_core import command_label
import flat_workspace as flat


class StageTests(unittest.TestCase):
    def ui(self, actions, state='running'):
        ui = snapshot()
        ui['sel_session'].update(state=state, actions=list(reversed(actions)))
        return ui

    def action(self, label, result='OK', **kw):
        return dict(a=label, r=result, **kw)

    def test_file_reads_and_searches_collapse_then_current_test_is_live(self):
        labels = ['收到新任务', '读 AGENTS.md', '搜索 private_name', '读 test_pet.py',
                  '改 pet.py', '执行工具', '写 helper.py', '跑测试 unittest', '等结果']
        ui = self.ui([self.action(x) for x in labels])
        ss = stages(ui)['steps']
        self.assertEqual([s['title'] for s in ss], [RESEARCH, IMPLEMENT, VERIFY])
        self.assertEqual(ss[-1]['status'], 'running')
        self.assertEqual(ss[-1]['index'], 8)  # detail click remains a real log index
        for mode in ('live', 'tasks', 'steps'):
            rows = flat.agent_rows(ui) if mode == 'live' else flat.rows_for(ui, mode)
            self.assertFalse(any('pet.py' in r['title'] or 'private_name' in r['title'] for r in rows))

    def test_housekeeping_does_not_replace_current_stage(self):
        ss = stages(self.ui([self.action('改 private.py'), self.action('命令 py utf8'), self.action('等结果')]))['steps']
        self.assertEqual([s['title'] for s in ss], [IMPLEMENT])

    def test_only_actual_phases_no_assumed_research_or_future_plan(self):
        ui = self.ui([self.action('改 private.py')])
        self.assertEqual([s['title'] for s in stages(ui)['steps']], [IMPLEMENT])
        self.assertEqual(flat.step_flow(flat.agent_rows(ui)[0]), (IMPLEMENT, None))

    def test_revisited_phase_preserves_test_fix_retest_order(self):
        ss = stages(self.ui([self.action(x) for x in ('跑测试 pytest', '改 bug.py', '跑测试 pytest')]))['steps']
        self.assertEqual([s['title'] for s in ss], [VERIFY, IMPLEMENT, VERIFY])

    def test_reopening_files_during_implementation_does_not_add_research_dots(self):
        ui = self.ui([self.action(x) for x in ('读 a.py', '改 a.py', '读 a.py', '搜索 symbol', '改 b.py', '跑测试 pytest', '读 log.txt')])
        self.assertEqual([s['title'] for s in stages(ui)['steps']], [RESEARCH, IMPLEMENT, VERIFY])

    def test_explicit_research_can_revisit_a_research_phase(self):
        ui = self.ui([self.action('改 a.py'), self.action('调研替代方案')])
        self.assertEqual([s['title'] for s in stages(ui)['steps']], [IMPLEMENT, RESEARCH])

    def test_unknown_and_terminal_records_never_expose_details(self):
        ui = self.ui([self.action('秘密自定义工具 abc/path'), self.action('本轮已结束')], 'done')
        self.assertEqual([s['title'] for s in stages(ui)['steps']], [GENERAL])
        ui = self.ui([self.action('改 bug.py'), self.action('本轮已结束')], 'done')
        self.assertEqual(stages(ui)['steps'][0]['title'], IMPLEMENT)
        self.assertEqual(flat.agent_rows(ui)[0]['state'], 'done')

    def test_errors_waits_stale_and_no_result_are_not_fake_success(self):
        ui = self.ui([self.action('读 file', ''), self.action('改 code', '', err=1)], 'error')
        self.assertEqual([s['status'] for s in stages(ui)['steps']], ['recorded', 'error'])
        ui['sel_session']['state'] = 'waiting'
        self.assertEqual(stages(ui)['steps'][-1]['status'], 'waiting')
        ui['sel_session']['stale'] = True
        self.assertEqual(flat.agent_rows(ui)[0]['state'], 'idle')
        self.assertTrue(flat.agent_rows(ui)[0]['stale'])

    def test_old_turn_does_not_bleed_into_new_task(self):
        ui = self.ui([self.action('跑测试 pytest'), {'turn':1}, self.action('改 new.py')])
        self.assertEqual([s['title'] for s in stages(ui)['steps']], [IMPLEMENT])

    def test_summary_does_not_mutate_public_history(self):
        ui = self.ui([self.action('读 private.py'), self.action('改 file.py')])
        before = copy.deepcopy(ui)
        stages(ui)
        self.assertEqual(before, ui)

    def test_python_flags_and_script_test_targets(self):
        for command in ('py -X utf8 -m unittest test_life', 'python -W ignore -m pytest', 'py test_pet.py'):
            self.assertEqual(stage_title(command_label(command)), VERIFY)
        self.assertEqual(stage_title(command_label('Get-Content test_pet.py')), RESEARCH)
        self.assertIsNone(stage_title(command_label('py -c "print(\'unittest\')"')))

    def test_work_direction_survives_incidental_reads_and_waits(self):
        ui=self.ui([self.action(x) for x in ('改 workflow_stages.py','读 test_chat_ui.py','等结果')])
        flow=stages(ui)
        self.assertEqual(len(flow['steps']),1)
        self.assertEqual(display_title(flow['steps'][0]),'编写与修改 · 工作流与进度')
        self.assertEqual(flat.step_flow(flat.agent_rows(ui)[0])[0],'编写与修改 · 工作流与进度')

    def test_responsibilities_do_not_inflate_progress_or_claim_child_completion(self):
        ui=self.ui([self.action(x) for x in ('委派子智能体 · 颜色与对比度','委派子智能体 · 比例与尺寸','等结果')])
        flow=stages(ui)
        self.assertEqual([s['title'] for s in flow['steps']],[DELEGATE])
        rows=flat.rows_for(ui,'steps')
        self.assertEqual([r['summary'] for r in rows],['委派子智能体 · 比例与尺寸','委派子智能体 · 颜色与对比度'])
        self.assertEqual([r['state'] for r in rows],['recorded','recorded'])
        self.assertEqual(len(flat.agent_rows(ui)[0]['chain']),1)

    def test_followup_preserves_direction_and_real_session_wait_error_stale(self):
        ui=self.ui([self.action('委派子智能体 · 颜色与对比度'),self.action('跟进子智能体 · 颜色与对比度')],'waiting')
        self.assertEqual(flat.agent_rows(ui)[0]['summary'],'跟进子智能体 · 颜色与对比度')
        self.assertEqual(flat.agent_rows(ui)[0]['state'],'waiting')
        ui['sel_session']['state']='error'
        self.assertEqual(flat.agent_rows(ui)[0]['state'],'error')
        ui['sel_session']['stale']=True
        self.assertEqual(flat.agent_rows(ui)[0]['state'],'idle')

    def test_scope_changes_never_add_phase_dots(self):
        flow=stages(self.ui([self.action('改 workflow_stages.py'),self.action('改 popup_material.py')]))
        self.assertEqual(len(flow['steps']),1)
        self.assertEqual(display_title(flow['steps'][0]),'编写与修改 · 窗口材质')

    def test_generic_validation_keeps_known_task_scope_across_phases(self):
        flow=stages(self.ui([self.action('改 fx.py'),self.action('跑测试 pytest'),self.action('等结果')]))
        self.assertEqual([s['title'] for s in flow['steps']],[IMPLEMENT,VERIFY])
        self.assertEqual(display_title(flow['steps'][-1]),'测试与验证 · 动态特效')

    def test_new_turn_does_not_reuse_old_responsibility(self):
        flow=stages(self.ui([self.action('委派子智能体 · 颜色与对比度'),{'turn':1},self.action('子代理')]))
        self.assertEqual(display_title(flow['steps'][0]),DELEGATE)
        self.assertEqual(len(detail_steps(flow)),1)

    def test_unknown_new_assignment_never_borrows_previous_responsibility(self):
        ui=self.ui([self.action('委派子智能体 · 颜色与对比度'),self.action('子代理'),self.action('等结果')])
        flow=stages(ui)
        self.assertEqual(display_title(flow['steps'][-1]),DELEGATE)
        self.assertEqual([s['index'] for s in detail_steps(flow)],[0,1])
        self.assertEqual(flat.rows_for(ui,'steps')[0]['summary'],DELEGATE)

    def test_direction_rows_reference_real_details_without_raw_task_text(self):
        ui=self.ui([self.action('委派子智能体 · 颜色与对比度'),self.action('委派子智能体 · 比例与尺寸')])
        for u in (1,1.14,1.5):
            im,hits,_=flat.render(ui,u,'steps')
            detail=[h[-1] for h in hits if h[4]=='detail']
            self.assertEqual({p[1] for p in detail},{0,1})
            self.assertTrue(all('子智能体' in p[2] for p in detail))


if __name__ == '__main__':unittest.main()
