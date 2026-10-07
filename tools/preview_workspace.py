"""Render today's workspace with synthetic tasks and no account/session I/O."""
from pathlib import Path
import argparse
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))


def snapshot():
    now = 1800000000.0
    examples = [('native-codex', 'running', ['读 workflow_stages.py', '改 workflow_stages.py']),
                ('native-claude', 'waiting', ['委派子智能体 · 颜色与对比度', '委派子智能体 · 比例与尺寸']),
                ('zcode', 'running', ['读 fx.py', '改 fx.py', '跑测试 unittest'])]
    sessions = []
    for i, (agent, state, actions) in enumerate(examples):
        steps = [{'a': a, 'r': '', 't': now - len(actions) + j} for j, a in enumerate(actions)]
        sessions.append(dict(id=f'simulated-{i}', agent=agent, state=state, updated=now,
                             actions=list(reversed(steps))))
    return dict(now=now, mock=True, sessions=sessions, sel_session=sessions[0],
                sel_key='native-codex', quota=None, codex_quota=None, sources=[])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'outputs' / 'current-workspace.png')
    parser.add_argument('--mode', choices=('live', 'tasks', 'steps'), default='live')
    args = parser.parse_args()
    from PIL import Image
    from tools.assets.export_house_stage import owner
    import pet
    p = owner(1.25)
    p.sw, p.sh = 2880, 1800
    p._flat_panel_style = p._studio_style = True
    p._house_on = False
    p.settings = {}
    p._flat_mode = args.mode
    p._flat_quota_raw = None
    geo = p._art_geo(1)
    p._swing = dict(geo=geo, theta=0, scene_l=0, scene_t=0, ui=snapshot(), art=True)
    # No Tk instance, model, live collector, screen capture or layered-window push.
    with patch('pet.push_layered'):
        p._push_swing_art(Image.new('RGBA', (p.W, p.H)))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    p._swing['scene_canvas'].save(args.out)
    print(f'Saved simulated production render: {args.out}')


if __name__ == '__main__':
    main()
