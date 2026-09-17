"""Open a real Tk UI with invented sample data in a disposable copy.

Use --view card or --view chat for documentation screenshots. No real AI,
personal saves, tray icon or external command channel. Closes after 3 minutes.
"""
from pathlib import Path
from unittest.mock import patch
import argparse
import json
import shutil
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--view', choices=('card', 'chat'), default='card')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='xiaoqiao-ui-guide-') as folder:
        stage = Path(folder)
        for name in ('pet.py', 'agent.py', 'ai_chat.py', 'fx.py', 'depth_model.py'):
            shutil.copy2(ROOT / name, stage / name)
        shutil.copytree(ROOT / 'assets', stage / 'assets', ignore=shutil.ignore_patterns(
            'ai_config*.json', 'memories*.json', '*backup*', 'audio_v2', '*.log', '*.tmp'))
        (stage/'assets'/'ai_config.json').write_text('{"enabled":false,"api_key":""}', encoding='utf-8')
        (stage/'pet_settings.json').write_text(json.dumps({
            'scale': 1, 'sound_on': False, 'tts_on': False, 'fg_watch': False,
            'star': 76, 'affection': 85,
            'today_stats': {'date': time.strftime('%Y-%m-%d'), 'pet': 8, 'candy': 2, 'catch': 6}
        }), encoding='utf-8')
        sys.path.insert(0, str(stage))
        import tkinter as tk
        import pet
        import ai_chat
        root = tk.Tk()
        p = None
        try:
            with patch.object(pet.Pet, 'tick'), patch.object(pet.Pet, 'start_tray'), patch.object(pet.Pet, '_start_watchdog'), \
                 patch.object(pet.SFX, 'play'), patch.object(ai_chat, 'AIBrain', return_value=None):
                p = pet.Pet(root, selftest=False)
            root.withdraw()
            p.selftest = False
            p.sfx.enabled = False
            p._pump = lambda: None
            p.state = 'idle'
            p.companion_days = lambda: 12
            if args.view == 'card':
                # Keep the sample open while a screenshot tool takes focus.
                # This override exists only inside this disposable process.
                pet.InteractionCard._check_focus = lambda self: None
                p.open_action_card(400, 180)
                window = p.action_card.win
            else:
                p.open_chat()
                window = p.chatbox.win
                p.chatbox.log_user('冥想')
                p.chatbox.log_reply('静下心来，感受星光的流动…')
                p.chatbox.log_user('5分钟后提醒我喝水')
                p.chatbox.log_reply('好，5 分钟后提醒你喝水。')
                p.chatbox.log_hint('以上为界面展示用的虚构对话，未调用 AI。')
            window.title('小乔文档预览 · ' + args.view + ' · 隔离样本')
            window.overrideredirect(False)
            window.attributes('-toolwindow', False)
            window.geometry('+400+160')
            root.after(180000, root.destroy)
            root.mainloop()
        finally:
            if p:
                p.sfx.close_all()
            try:
                root.destroy()
            except tk.TclError:
                pass


if __name__ == '__main__':
    main()
