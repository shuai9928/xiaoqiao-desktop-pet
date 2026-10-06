"""Export the actual room compositor with synthetic AI snapshots, no GUI/data I/O."""
import argparse
from collections import OrderedDict
import json
import math
from pathlib import Path
import time
from unittest.mock import patch

from PIL import Image

import pet
from export_function_ui import demo
from house_scene import HouseRenderer
from test_scene_art import _shell


def owner(scale=1.5):
    p = _shell()
    p.scale = scale
    p.W, p.H = round(pet.BASE_W*scale), round(pet.BASE_H*scale)
    p.FOOT_Y = p.H-round(30*scale)
    p._house_on, p._house_suspended = True, False
    p.state, p._nap_on_swing = 'swing', False
    p._scene_art.set_rig(p.cfg['rig']['regions'])
    p._last_depth_pose = (0.0,)*6
    p._last_face_key = None
    p._chain_rect_local = None
    p._art_small_back = None
    p.glow_cache = OrderedDict()
    p._house_plaque_cache = None
    p.hwnd = 0
    return p


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--scale', type=float, default=1.25, help='pet scale (live default 1.25)')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    p, renderer = owner(args.scale), HouseRenderer()
    p.sw, p.sh = 2880, 1800
    snapshot = demo()
    p.ai_mute_sess = set()
    measurements = []

    def scene(ss):
        geo = p._art_geo(ss)
        w, h = geo['size']
        sw = {'geo': geo, 'art': True, 'scene_l': 0, 'scene_t': 0, 'scene_w': w,
              'scene_h': h, 'scene_scale': ss, 'theta': 0, 'omega': 0, 'ui': snapshot}
        p._swing = sw
        return sw

    def draw(sw, theta=0, view=(0.0, 0.0)):
        sw.update(theta=theta, omega=.08)
        p._last_depth_pose = (view[0]*.5, view[1]*.3, 0, 0, 0, 0)
        p._house_layers = lambda stage: renderer.render(stage['geo']['house_layout'], view)
        started = time.perf_counter()
        with patch('pet.push_layered'):
            p._push_swing_art(Image.new('RGBA', (p.W, p.H)))
        measurements.append((time.perf_counter()-started)*1000)
        return sw['scene_canvas'].copy()

    def matte(image):
        m = Image.new('RGBA', image.size, '#1b1725')
        m.alpha_composite(image)
        return m.convert('RGB')

    sizes = {}
    for ss, label in ((1.0, '标准'), (.76, '76%'), (.60, '紧凑')):
        image = draw(scene(ss))
        image.save(args.out/f'代码预览-{label}-模拟.png')
        sizes[label] = image.size

    sw = scene(1.0)
    frames = []
    for i in range(40):
        t = i/40*math.tau
        image = draw(sw, .17*math.sin(2*t), (math.sin(t), .6*math.cos(t)))
        frames.append(matte(image))
        if i in (0, 10, 20, 30):
            image.save(args.out/f'动态复核-{i}.png')
    frames[0].save(args.out/'Live2.5D小屋-动态-模拟.gif', save_all=True,
                   append_images=frames[1:], duration=100, loop=0, disposal=2)

    snapshot.update(quota=None, quota_age=None, sel_session=None, sessions=[], sources=[], sel_key=None)
    p._house_plaque_cache = None
    draw(sw).save(args.out/'代码预览-未接入-模拟.png')
    result = {'scope': '当前主程序真实合成代码，离线合成数据；不是桌面截图或实际账户额度',
              'sizes': sizes, 'animated_frames': len(frames),
              'render_ms_median': round(sorted(measurements)[len(measurements)//2], 2),
              'artwork': 'assets/house/room-v2-{bg,fg,depth}.png (tools/build_house_room.py)'}
    (args.out/'布局与动态验证.json').write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                          encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
