"""The unified runner isolates private data and does not hide moved suites."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.run_checks import _disable_network, isolated_environment, prepare_stage, unit_modules


class CheckRunnerTests(unittest.TestCase):
    def test_network_guard_rejects_direct_socket_and_url_clients(self):
        import socket
        import urllib.request
        with patch.object(socket, 'create_connection'), \
             patch.object(socket.socket, 'connect'), \
             patch.object(socket.socket, 'connect_ex'), \
             patch.object(socket.socket, 'sendto'), \
             patch.object(urllib.request, 'urlopen'):
            _disable_network()
            with socket.socket() as client:
                for call in (lambda: client.connect(('127.0.0.1', 9)),
                             lambda: client.connect_ex(('127.0.0.1', 9)),
                             lambda: client.sendto(b'', ('127.0.0.1', 9)),
                             lambda: socket.create_connection(('127.0.0.1', 9)),
                             lambda: urllib.request.urlopen('https://example.invalid')):
                    with self.assertRaisesRegex(RuntimeError, 'Network access is disabled'):
                        call()

    def test_stage_copies_runtime_tests_tools_and_materials_without_personal_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, stage = root / 'source', root / 'stage'
            for path in (source, source / 'tests', source / 'tools', source / 'assets', stage):
                path.mkdir(parents=True, exist_ok=True)
            for relative in ('pet.py', 'tests/test_example.py', 'tools/helper.py', 'assets/main.png'):
                (source / relative).write_text('public fixture', encoding='utf-8')
            for relative in ('pet_settings.json', 'chat_history.json',
                             'assets/ai_config.json', 'assets/memories.json'):
                (source / relative).write_text('PRIVATE_SENTINEL', encoding='utf-8')
            home = prepare_stage(source, stage)
            for relative in ('pet.py', 'tests/test_example.py', 'tools/helper.py', 'assets/main.png'):
                self.assertTrue((stage / relative).is_file(), relative)
            self.assertFalse((stage / 'chat_history.json').exists())
            for relative in ('pet_settings.json', 'assets/ai_config.json', 'assets/memories.json'):
                self.assertNotIn('PRIVATE_SENTINEL', (stage / relative).read_text(encoding='utf-8'))
            self.assertTrue((home / '.codex').is_dir())

    def test_environment_overrides_user_homes_and_removes_credentials(self):
        stage = Path('synthetic-stage')
        home = stage / '_synthetic_home'
        env = isolated_environment(stage, home, {'PATH': 'kept', 'HOME': 'private-home',
            'USERPROFILE': 'private-home', 'CODEX_HOME': 'private-codex',
            'OPENAI_API_KEY': 'private-key', 'GITHUB_TOKEN': 'private-token'})
        self.assertEqual(env['PATH'], 'kept')
        self.assertEqual(env['HOME'], str(home))
        self.assertEqual(env['USERPROFILE'], str(home))
        self.assertEqual(env['CODEX_HOME'], str(home / '.codex'))
        self.assertNotIn('OPENAI_API_KEY', env)
        self.assertNotIn('GITHUB_TOKEN', env)
        self.assertEqual(env['PYTHONPATH'], os.pathsep.join((str(stage), str(stage / 'tests'))))

    def test_current_units_keep_required_suites_and_legacy_is_explicit(self):
        root = Path(__file__).resolve().parents[1]
        current = unit_modules(root)
        legacy = unit_modules(root, legacy=True)
        for name in ('test_life', 'test_swing', 'test_session_lights', 'test_ai_lights_data',
                     'test_core_profile', 'test_core_runtime', 'test_workflow_stages',
                     'test_hat_fx', 'test_popup_material'):
            self.assertIn(name, current)
        self.assertNotIn('test_pet', current)  # explicit script smoke, not an empty unittest module
        self.assertNotIn('test_recovery', current)
        self.assertIn('test_recovery', legacy)


if __name__ == '__main__':
    unittest.main()
