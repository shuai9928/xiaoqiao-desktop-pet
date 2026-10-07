"""Run desktop checks in a temporary copy with synthetic user data and no AI.

Default: current unit suites plus the required test_pet compatibility smoke.
--unit-only omits that windowed script; --legacy adds retired-feature suites.
"""
from pathlib import Path
import argparse
import json
import os
import re
import runpy
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MANUAL_TESTS = {'test_pet', 'test_agent'}
LEGACY_UNITS = {
    'test_action_fx', 'test_feedback', 'test_focus', 'test_micro_motion',
    'test_recovery', 'test_refinement', 'test_studio',
}
KNOWN_SKIPS = {
    ('test_scene_art.NewSpriteGeometryTests.test_click_zones_follow_the_rig', '旧立绘配置没有 rig'),
    ('test_scene_art.NewSpriteGeometryTests.test_face_landmarks_sit_on_the_face_region', '旧立绘配置没有 rig'),
}


def unit_modules(root=ROOT, legacy=False):
    modules = sorted(path.stem for path in (root / 'tests').glob('test_*.py'))
    return [name for name in modules if name not in MANUAL_TESTS
            and (legacy or name not in LEGACY_UNITS)]


def prepare_stage(source, stage):
    """Copy code/materials only; never copy personal saves or transcripts."""
    for path in source.glob('*.py'):
        shutil.copy2(path, stage / path.name)
    ignores = shutil.ignore_patterns('__pycache__', '*.pyc', '*.log', '*.tmp')
    for folder in ('tests', 'tools'):
        shutil.copytree(source / folder, stage / folder, ignore=ignores)
    shutil.copytree(source / 'assets', stage / 'assets', ignore=shutil.ignore_patterns(
        'ai_config*.json', 'memories*.json', '*backup*', '*.log', '*.tmp'))
    (stage / 'assets' / 'ai_config.json').write_text(json.dumps({
        'enabled': False, 'api_key': '', 'greet_interval_min': 0}), encoding='utf-8')
    (stage / 'assets' / 'memories.json').write_text('{"facts": []}', encoding='utf-8')
    (stage / 'pet_settings.json').write_text(json.dumps({
        'scale': 1, 'sound_on': False, 'tts_on': False, 'fg_watch': False,
        'ai_announce': False}), encoding='utf-8')
    home = stage / '_synthetic_home'
    for folder in (home, home / '.codex', home / '.claude',
                   home / 'AppData' / 'Roaming', home / 'AppData' / 'Local'):
        folder.mkdir(parents=True, exist_ok=True)
    return home


def isolated_environment(stage, home, original=None):
    original = os.environ if original is None else original
    env = {key: value for key, value in original.items()
           if not re.search(r'API_KEY|TOKEN|SECRET|PASSWORD', key, re.I)}
    env.update({
        'HOME': str(home), 'USERPROFILE': str(home),
        'APPDATA': str(home / 'AppData' / 'Roaming'),
        'LOCALAPPDATA': str(home / 'AppData' / 'Local'),
        'CODEX_HOME': str(home / '.codex'), 'CLAUDE_CONFIG_DIR': str(home / '.claude'),
        'PYTHONPATH': os.pathsep.join((str(stage), str(stage / 'tests'))),
        'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUTF8': '1',
        'XIAOQIAO_CHECKS_ISOLATED': '1',
    })
    return env


def _disable_network():
    def blocked(*args, **kwargs):
        raise RuntimeError('Network access is disabled in desktop checks')
    socket.create_connection = blocked
    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    socket.socket.sendto = blocked
    urllib.request.urlopen = blocked


class ReportedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.unexpected_skips = []

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        identity = test.id()
        known = ((identity, reason) in KNOWN_SKIPS or
                 (identity.startswith('test_action_fx.LegLayerRenderTests.')
                  and reason == '没有腿层素材'))
        self.stream.writeln(f'\nSKIP {identity}: {reason} (known={known})')
        if not known:
            self.unexpected_skips.append((identity, reason))


def run_units(legacy=False):
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / 'tests'))
    _disable_network()
    modules = unit_modules(legacy=legacy)
    print(f'Unit suites: {len(modules)}; legacy={legacy}', flush=True)
    for name in modules:
        print(f'  {name}', flush=True)
    suite = unittest.defaultTestLoader.loadTestsFromNames(modules)
    result = unittest.TextTestRunner(verbosity=1, resultclass=ReportedResult).run(suite)
    print(f'Unit result: ran={result.testsRun}, failures={len(result.failures)}, '
          f'errors={len(result.errors)}, skips={len(result.skipped)}, '
          f'unexpected_skips={len(result.unexpected_skips)}', flush=True)
    return 0 if result.wasSuccessful() and not result.unexpected_skips else 1


def run_script(name):
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / 'tests'))
    _disable_network()
    print(f'Script smoke: {name} (isolated, network disabled)', flush=True)
    sys.argv = [str(ROOT / 'tests' / (name + '.py'))]
    runpy.run_path(sys.argv[0], run_name='__main__')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unit-only', action='store_true', help='omit the required windowed test_pet smoke')
    parser.add_argument('--legacy', action='store_true', help='also run retired-feature compatibility suites')
    parser.add_argument('--unit-worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--script-worker', choices=sorted(MANUAL_TESTS), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.unit_worker or args.script_worker:
        if os.environ.get('XIAOQIAO_CHECKS_ISOLATED') != '1':
            parser.error('workers must be started through the isolated runner')
        return run_script(args.script_worker) if args.script_worker else run_units(args.legacy)
    if os.name != 'nt':
        print('Desktop checks require Windows and Tkinter.')
        return 2
    docs = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'tools' / 'check_docs.py')], cwd=ROOT)
    if docs.returncode:
        return docs.returncode
    with tempfile.TemporaryDirectory(prefix='xiaoqiao-checks-') as directory:
        stage = Path(directory)
        home = prepare_stage(ROOT, stage)
        env = isolated_environment(stage, home)
        worker = [sys.executable, '-X', 'utf8', str(stage / 'tools' / 'run_checks.py')]
        commands = [worker + ['--unit-worker'] + (['--legacy'] if args.legacy else [])]
        if not args.unit_only:
            commands.append(worker + ['--script-worker', 'test_pet'])
        if args.legacy:
            commands.append(worker + ['--script-worker', 'test_agent'])
        status = 0
        # Keep running the required smoke even if a unit assertion fails so
        # reviewers get both real outcomes, rather than a hidden skipped run.
        for command in commands:
            result = subprocess.run(command, cwd=stage, env=env)
            if result.returncode:
                status = result.returncode
        return status


if __name__ == '__main__':
    raise SystemExit(main())
