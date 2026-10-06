"""Integrated core-profile smoke with synthetic files and a disabled AI backend."""
import json
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import ai_chat
import pet


class CoreRuntimeTests(unittest.TestCase):
    def test_shipped_profile_renders_and_keeps_retired_data_dormant(self):
        with tempfile.TemporaryDirectory(prefix='xiaoqiao_core_') as folder:
            base = Path(folder)
            legacy_timer = {'phase': 'focus', 'due': 1, 'mins': 25}
            prefs = {'scale': .8, 'sound_on': False, 'tts_on': False,
                     'swing_home': False, 'water_min': 1, 'fg_watch': True,
                     'battery_watch': True, 'pomo': legacy_timer, 'city': 'synthetic'}
            config = base/'pet_settings.json'
            config.write_text(json.dumps(prefs), encoding='utf-8')
            reminders = base/'pet_reminders.json'
            original = b'[{"due":1,"text":"old synthetic reminder"}]'
            reminders.write_bytes(original)
            errors = []
            with patch.object(pet, 'HERE', folder), \
                 patch.object(pet, 'CONFIG_FILE', str(config)), \
                 patch.object(pet, 'REMINDERS_FILE', str(reminders)), \
                 patch.object(pet, 'TTS_CACHE', str(base/'tts')), \
                 patch.object(pet, 'AI_SESSION_DIR', str(base/'sessions')), \
                 patch.object(ai_chat, 'AIBrain', return_value=None), \
                 patch.object(pet.Pet, 'start_tray', autospec=True,
                              side_effect=lambda obj: setattr(obj, '_tray', None)):
                root = tk.Tk()
                p = pet.Pet(root)
                root.report_callback_exception = lambda *args: errors.append(str(args[1]))
                self.assertTrue(p.core_profile())
                p._fire_reminder = Mock()
                p._ai_quick = Mock()
                p.water_next = 1
                try:
                    menu = p._build_menu()
                    menu.destroy()
                    p.mount_swing()
                    scene = p._swing
                    p._exec_cmd({'op': 'sleep'})
                    self.assertTrue(p._nap_on_swing)
                    p._exec_cmd({'op': 'wake'})
                    self.assertFalse(p._nap_on_swing)
                    self.assertIs(p._swing, scene)
                    p._exec_cmd({'op': 'feed'})
                    self.assertIs(p._swing, scene)
                    p._exec_cmd({'op': 'dance'})
                    self.assertEqual(p.state, 'swing')
                    p.go_sleep()
                    self.assertTrue(p._nap_on_swing)
                    p.on_double(None)
                    self.assertFalse(p._nap_on_swing)
                    self.assertIs(p._swing, scene)
                    self.assertIsNotNone(p.chatbox)
                    p.chatbox.close()
                    p._write_state()
                    exported = json.loads((base/'pet_state.json').read_text(encoding='utf-8'))
                    self.assertEqual(exported['state'], 'swing')
                    self.assertFalse(exported['ai_panel']['codex_quota_connected'])
                    p.open_room_preview()
                    self.assertTrue(p.house_enabled())
                    self.assertIs(p._swing, scene)
                    self.assertIn('house_layout', scene['geo'])
                    # Demo without an injected quota must never inherit actual
                    # account values, even when both cached sources exist.
                    p._quota = {'fh':19,'sd':27,'t':time.time()*1000}
                    p._codex_quota = {'provider':'codex','t':time.time()*1000,
                                      'cycles':[{'minutes':300,'used':29}]}
                    p._demo_until = time.time()+120
                    p._demo_sessions = []
                    p._demo_quota = None
                    for _ in range(12):
                        root.update()
                        time.sleep(.025)
                    self.assertTrue(scene['ui']['mock'])
                    self.assertIsNone(scene['ui']['quota'])
                    self.assertIsNone(scene['ui']['codex_quota'])
                    p._demo_until = 0
                    p.open_swing_scene()
                    self.assertFalse(p.house_enabled())
                    self.assertIs(p._swing, scene)
                    for _ in range(24):
                        root.update()
                        time.sleep(.025)
                    p.save_settings()
                    saved = json.loads(config.read_text(encoding='utf-8'))
                    self.assertEqual(saved['pomo'], legacy_timer)
                    self.assertEqual(saved['water_min'], 1)
                    self.assertEqual(saved['city'], 'synthetic')
                    self.assertEqual(reminders.read_bytes(), original)
                    p._fire_reminder.assert_not_called()
                    p._ai_quick.assert_not_called()
                    self.assertEqual(errors, [])
                finally:
                    p.quit()


if __name__ == '__main__':
    unittest.main()
