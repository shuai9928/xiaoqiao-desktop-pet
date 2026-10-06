"""Native event lifecycle, incremental files, and privacy checks (isolated data)."""
import json
import tempfile
import unittest
from pathlib import Path

from native_session_sync import NativeSessions, Transcript, codex_label, delegation_label, stamp

T = '2026-10-06T04:00:00Z'
NOW = stamp(T)


def event(typ, **values):
    return {'timestamp': T, 'type': 'event_msg', 'payload': {'type': typ, **values}}


class NativeSessionsTests(unittest.TestCase):
    def test_delegation_preserves_finite_responsibility_without_prompts(self):
        r = Transcript('test.jsonl', 'native-codex')
        r.consume({'type': 'response_item', 'timestamp': T, 'payload': {
            'type': 'function_call', 'name': 'collaboration.spawn_agent',
            'arguments': json.dumps({'task_name': 'color_contrast_review',
                'message': 'PRIVATE_PROMPT 检查颜色 TOKEN=PRIVATE_TOKEN'})}})
        self.assertEqual(r.actions[0]['a'], '委派子智能体 · 颜色与对比度')
        self.assertNotIn('PRIVATE_', json.dumps(r.snapshot(NOW)))
        self.assertEqual(delegation_label('spawn_agent', {'task_name': 'unknown',
            'message': 'PRIVATE_PROMPT'}), '委派子智能体')
        self.assertEqual(delegation_label('followup_task', {'target': 'PRIVATE_ID',
            'message': '复测回归并验证结果 PRIVATE_MESSAGE'}), '跟进子智能体 · 测试与验证')
        self.assertEqual(delegation_label('send_message', {'target': 'PRIVATE_ID',
            'message': '请复审 PRIVATE_MESSAGE'}), '跟进子智能体 · 审核与检查')
        self.assertIsNone(delegation_label('wait', {'message': '测试 PRIVATE_MESSAGE'}))
        self.assertEqual(delegation_label('spawn_agent', {'message':
            '请处理这项任务。\n不要修改颜色、尺寸、布局和工作流。'}), '委派子智能体')
        self.assertEqual(delegation_label('send_message', {'message':
            '不要修改颜色和布局。'}), '跟进子智能体')
        self.assertEqual(delegation_label('Task', {'subagent_type': 'Explore',
            'description': '检查颜色与对比度', 'prompt': 'PRIVATE_PROMPT'}),
            '委派子智能体 · 颜色与对比度')
        self.assertEqual(delegation_label('Task', {'subagent_type': 'Explore',
            'description': '处理这项任务', 'prompt': 'PRIVATE_PROMPT'}),
            '委派子智能体 · 资料调研')

    def test_wrapper_delegation_and_claude_task_summary(self):
        self.assertEqual(codex_label('exec', 'await tools.spawn_agent({task_name:"ui_layout",'
            'message:"PRIVATE_PROMPT"})'), '委派子智能体 · 界面与布局')
        r = Transcript('test.jsonl', 'native-claude')
        r.consume({'type': 'assistant', 'timestamp': T, 'message': {'content': [
            {'type': 'tool_use', 'id': 'PRIVATE_ID', 'name': 'Task', 'input': {
                'description': '审核代码', 'prompt': 'PRIVATE_PROMPT', 'subagent_type': 'general-purpose'}}]}})
        self.assertEqual(r.actions[0]['a'], '委派子智能体 · 审核与检查')
        self.assertNotIn('PRIVATE_', json.dumps(r.snapshot(NOW)))

    def test_wrapper_patch_retains_only_public_file_subject(self):
        patch = '*** Begin Patch\n*** Update File: C:/PRIVATE_CLIENT/workflow_stages.py\n@@\n-PRIVATE_OLD\n+PRIVATE_NEW\n*** End Patch'
        r = Transcript('test.jsonl', 'native-codex')
        r.consume({'type': 'response_item', 'timestamp': T, 'payload': {
            'type': 'custom_tool_call', 'name': 'exec',
            'input': 'text(await tools.apply_patch(' + json.dumps(patch) + '));'}})
        self.assertEqual(r.actions[0]['a'], '改 workflow_stages.py')
        self.assertNotIn('PRIVATE_', json.dumps(r.snapshot(NOW)))

    def test_codex_start_command_final_and_abort(self):
        r = Transcript('test.jsonl', 'native-codex')
        r.consume(event('task_started'))
        r.consume(event('item_completed', item={'type': 'CommandExecution',
            'command': ['pwsh', '-Command', 'git status --porcelain'], 'exit_code': 0,
            'stdout': 'private-output'}))
        self.assertEqual(r.snapshot(NOW)['state'], 'running')
        self.assertEqual(r.actions[0]['a'], '命令 git status')
        self.assertEqual(r.actions[0]['r'], '退出 0')
        r.consume(event('task_complete', last_agent_message='private-final'))
        self.assertEqual(r.snapshot(NOW)['state'], 'done')
        r.consume(event('turn_aborted'))
        self.assertEqual(r.snapshot(NOW)['state'], 'idle')

    def test_private_content_and_credentials_never_copied(self):
        r = Transcript('test.jsonl', 'native-codex')
        r.consume({'type': 'response_item', 'timestamp': T,
                   'payload': {'type': 'reasoning', 'summary': 'PRIVATE_REASON'}})
        r.consume(event('user_message', message='PRIVATE_USER'))
        r.consume(event('item_completed', item={'type': 'CommandExecution',
            'command': 'curl -H PRIVATE_TOKEN https://private.test?q=PRIVATE_URL',
            'stdout': 'PRIVATE_OUTPUT', 'exit_code': 0}))
        text = json.dumps(r.snapshot(NOW))
        self.assertNotIn('PRIVATE_', text)
        self.assertEqual(r.actions[0]['a'], '命令 curl')

    def test_partial_json_line_and_malformed_line_do_not_lose_events(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'test.jsonl'
            line = json.dumps(event('task_complete')).encode()
            p.write_bytes(b'{bad}\n' + line[:20])
            r = Transcript(p, 'native-codex')
            r.poll()
            self.assertEqual(r.state, 'idle')
            with p.open('ab') as f:
                f.write(line[20:] + b'\n')
            r.poll()
            self.assertEqual(r.state, 'done')
            r.poll()
            self.assertEqual(len(r.actions), 1)

    def test_claude_tool_result_and_end_turn_without_chat_text(self):
        r = Transcript('test.jsonl', 'native-claude')
        r.consume({'timestamp': T, 'type': 'assistant', 'message': {
            'content': [{'type': 'thinking', 'thinking': 'PRIVATE_REASON'},
                        {'type': 'tool_use', 'id': 'call', 'name': 'Read',
                         'input': {'file_path': 'C:/private/pet.py'}}]}})
        r.consume({'timestamp': T, 'type': 'user', 'message': {'content': [
            {'type': 'tool_result', 'tool_use_id': 'call', 'is_error': True,
             'content': 'PRIVATE_OUTPUT'}]}})
        self.assertEqual(r.actions[0]['a'], '读 pet.py')
        self.assertEqual(r.actions[0]['err'], 1)
        r.consume({'timestamp': T, 'type': 'assistant', 'message': {
            'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': 'PRIVATE_FINAL'}]}})
        self.assertEqual(r.state, 'done')
        self.assertNotIn('PRIVATE_', json.dumps(r.snapshot(NOW)))

    def test_expiry_does_not_refresh_work_from_polling(self):
        r = Transcript('test.jsonl', 'native-codex')
        r.consume(event('task_started'))
        old = r.snapshot(NOW + 901)
        self.assertEqual(old['state'], 'idle')
        self.assertTrue(old['stale'])
        self.assertEqual(old['updated'], NOW)

    def test_discovery_isolated_and_claude_idle_metadata_overrides_old_turn(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            p = home / '.claude' / 'projects' / 'test' / 'sid.jsonl'
            p.parent.mkdir(parents=True)
            p.write_text(json.dumps({'type': 'assistant', 'timestamp': T, 'message': {
                'content': [{'type': 'tool_use', 'name': 'Read', 'input': {'file_path': 'pet.py'}}]}}) + '\n')
            meta = home / '.claude' / 'sessions'
            meta.mkdir(parents=True)
            (meta / 'bad.json').write_text('{bad')
            (meta / '1.json').write_text(json.dumps({'sessionId': 'sid', 'status': 'idle',
                'statusUpdatedAt': (NOW + 1) * 1000}))
            sync = NativeSessions(home, home / 'output')
            sync.tick(NOW + 2)
            data = json.loads((home / 'output' / 'native-claude-sid.json').read_text())
            self.assertEqual(data['state'], 'idle')
            self.assertEqual(data['actions'][0]['a'], '读 pet.py')

    def test_waiting_for_real_user_input(self):
        r = Transcript('test.jsonl', 'native-codex')
        r.consume({'type': 'response_item', 'timestamp': T, 'payload': {
            'type': 'function_call', 'name': 'request_user_input', 'arguments': '{}'}})
        self.assertEqual(r.snapshot(NOW)['state'], 'waiting')

    def test_codex_wrapper_uses_public_command_and_discards_body(self):
        r = Transcript('test.jsonl', 'native-codex')
        r.consume({'type': 'response_item', 'timestamp': T, 'payload': {
            'type': 'custom_tool_call', 'name': 'exec',
            'input': 'text(await tools.exec_command({cmd:"git status --token PRIVATE_TOKEN"}));'}})
        self.assertEqual(r.actions[0]['a'], '命令 git status')
        self.assertNotIn('PRIVATE_', json.dumps(r.snapshot(NOW)))

    def test_cloud_session_is_not_fabricated(self):
        with tempfile.TemporaryDirectory() as d:
            sync = NativeSessions(d, Path(d) / 'output')
            sync.tick(NOW)
            self.assertEqual(list((Path(d) / 'output').glob('*.json')), [])


if __name__ == '__main__':
    unittest.main()
