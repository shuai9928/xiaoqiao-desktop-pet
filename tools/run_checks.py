"""Run checks in an isolated copy, without personal saves or real AI calls."""
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
UNITS=['test_action_fx','test_micro_motion','test_refinement','test_chat_ui',
       'test_focus','test_feedback','test_recovery','test_depth']


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--unit-only',action='store_true')
    args=parser.parse_args()
    if os.name!='nt':
        print('These tests require Windows and Tkinter.')
        return 2
    with tempfile.TemporaryDirectory(prefix='xiaoqiao-checks-') as directory:
        stage=Path(directory)
        for p in ROOT.glob('*.py'):
            if p.name in ('pet.py','agent.py','ai_chat.py','fx.py','depth_model.py') or p.name.startswith('test_'):
                shutil.copy2(p,stage/p.name)
        shutil.copytree(ROOT/'assets',stage/'assets',ignore=shutil.ignore_patterns(
            'ai_config*.json','memories*.json','*backup*','audio_v2','*.log','*.tmp'))
        (stage/'assets'/'ai_config.json').write_text(json.dumps({
            'enabled':False,'api_key':'','greet_interval_min':0}),encoding='utf-8')
        (stage/'assets'/'memories.json').write_text('{"facts": []}',encoding='utf-8')
        (stage/'pet_settings.json').write_text(json.dumps({
            'scale':1,'sound_on':False,'tts_on':False,'fg_watch':False}),encoding='utf-8')
        env={k:v for k,v in os.environ.items() if k not in ('GEMINI_API_KEY','GOOGLE_API_KEY')}
        commands=[[sys.executable,'-X','utf8','-m','unittest',*UNITS,'-q'],
                  [sys.executable,'-X','utf8','test_agent.py']]
        if not args.unit_only: commands.append([sys.executable,'-X','utf8','test_pet.py'])
        for command in commands:
            result=subprocess.run(command,cwd=stage,env=env)
            if result.returncode: return result.returncode
    return 0


if __name__=='__main__': raise SystemExit(main())
