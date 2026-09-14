"""Render release visuals from the real Pet renderer, in an isolated directory.

Windows + runtime dependencies only. No AI, microphone, user saves or screen
capture. The background and editorial labels are presentation artwork; character
motion and effects come from pet.py. Run from any directory.
"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import base64
import argparse
import io
import json
import math
import random
import shutil
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs' / 'media'
FPS = 20
W, H = 960, 560
INK, MUTED, GOLD = '#f5f1ff', '#a5a0b9', '#e5d2a0'


def font(size, bold=False):
    return ImageFont.truetype('C:/Windows/Fonts/msyh' + ('bd' if bold else '') + '.ttc', size)


def background():
    # A static editorial stage, separate from the actual desktop effects.
    im = Image.new('RGB', (W, H))
    pix = im.load()
    for y in range(H):
        for x in range(W):
            glow = math.exp(-(((x-675)/300)**2 + ((y-310)/230)**2))
            pix[x,y] = (int(16+21*glow), int(15+15*glow), int(25+38*glow))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((1,1,W-2,H-2), radius=24, outline='#34303f')
    d.line((40,90,W-40,90), fill='#302c3b')
    d.text((40,33), 'XIAOQIAO  /  MOMENTS', font=font(15), fill=GOLD)
    d.text((710,35), '当前源码 · 隔离渲染', font=font(13), fill=MUTED)
    return im


def panel(bg, art, number, title, subtitle, detail, dx=0, dy=0):
    canvas = bg.copy()
    d = ImageDraw.Draw(canvas)
    d.text((42,133), number, font=font(18), fill=GOLD)
    for i, line in enumerate(title.split('\n')):
        d.text((40,185+55*i), line, font=font(38,True), fill=INK)
    d.text((42,330), subtitle, font=font(17), fill=GOLD)
    for i,line in enumerate(detail.split('\n')):
        d.text((42,368+i*28), line, font=font(15), fill=MUTED)
    # Same fixed viewport for every frame; never reshape character anatomy.
    art = art.crop((0,90,art.width,art.height))
    canvas.paste(art,(430+round(dx),105+round(dy)),art)
    d = ImageDraw.Draw(canvas)
    d.text((42,H-37), '小乔 · 时之魔女', font=font(13), fill=MUTED)
    return canvas


def save_animation(name, frames, poster):
    # Animated WebP preserves soft gradients without a heavy GIF download.
    frames[0].save(OUT/(name+'.webp'),save_all=True,append_images=frames[1:],
                   duration=1000//FPS,loop=0,quality=84,method=4)
    frames[poster].save(OUT/(name+'.png'),optimize=True)
    print(name, len(frames), 'frames', round((OUT/(name+'.webp')).stat().st_size/1024), 'KiB', flush=True)


def hero(art):
    stream=io.BytesIO()
    art.save(stream,format='PNG')
    encoded=base64.b64encode(stream.getvalue()).decode('ascii')
    # A self-contained SVG remains crisp in GitHub's light and dark themes.
    svg=f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1440" height="1000" viewBox="0 0 1440 1000" role="img" aria-labelledby="title desc">
<title id="title">小乔 · 时之魔女。让桌面，多一点魔法。</title>
<desc id="desc">Windows 开源桌宠。原画、轻微转头、星光互动与安静陪伴。中央角色为当前程序渲染。</desc>
<defs><radialGradient id="g"><stop stop-color="#473357"/><stop offset=".65" stop-color="#201b30"/><stop offset="1" stop-color="#101018"/></radialGradient><linearGradient id="t"><stop stop-color="#fff5dd"/><stop offset="1" stop-color="#c6b3ed"/></linearGradient></defs>
<rect width="1440" height="1000" rx="28" fill="#101018"/>
<ellipse cx="920" cy="555" rx="590" ry="600" fill="url(#g)"/>
<g fill="none" stroke="#b9a27c" opacity=".14"><circle cx="956" cy="519" r="327"/><circle cx="956" cy="519" r="344"/><path d="M956 157V182 M1318 519H1293 M956 881V856 M594 519H619" stroke-width="2"/><path d="M956 519L1040 385 M956 519L1155 558"/></g>
<g font-family="Microsoft YaHei, PingFang SC, sans-serif">
<text x="76" y="87" font-size="22" letter-spacing="5" fill="#e5d2a0">XIAOQIAO</text>
<text x="1364" y="87" text-anchor="end" font-size="17" letter-spacing="2" fill="#a8a0b5">WINDOWS · OPEN SOURCE</text>
<path d="M76 120H1364" stroke="#36303f"/>
<text x="76" y="293" font-size="25" fill="#e5d2a0">小乔 · 时之魔女</text>
<text x="69" y="402" font-size="80" font-weight="700" fill="url(#t)">让桌面，</text>
<text x="69" y="505" font-size="80" font-weight="700" fill="url(#t)">多一点魔法。</text>
<text x="76" y="577" font-size="23" fill="#b6afc5">会望向你。会回应你。</text>
<text x="76" y="618" font-size="23" fill="#b6afc5">也会安静地，陪着你。</text>
<rect x="76" y="674" width="228" height="49" rx="24" fill="#292334" stroke="#54465e"/>
<text x="190" y="706" text-anchor="middle" font-size="17" fill="#ead9b0">自然立体感 · 2.5D</text>
<text x="76" y="887" font-size="18" fill="#e5d2a0">原画之美</text><text x="280" y="887" font-size="18" fill="#e5d2a0">星光互动</text><text x="484" y="887" font-size="18" fill="#e5d2a0">日常陪伴</text>
<text x="76" y="934" font-size="14" fill="#888093">角色来自程序实际渲染 · 背景与排版为发布视觉设计</text>
</g><image x="566" y="115" width="790" height="750" preserveAspectRatio="xMidYMid meet" xlink:href="data:image/png;base64,{encoded}"/>
</svg>'''
    (OUT/'hero.svg').write_text(svg,encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--hero-only', action='store_true')
    args = parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='xiaoqiao-showcase-') as folder:
        stage=Path(folder)
        for name in ('pet.py','agent.py','ai_chat.py','fx.py','depth_model.py'):
            shutil.copy2(ROOT/name,stage/name)
        shutil.copytree(ROOT/'assets',stage/'assets',ignore=shutil.ignore_patterns(
            'ai_config*.json','memories*.json','*backup*','audio_v2','*.log','*.tmp'))
        (stage/'assets'/'ai_config.json').write_text('{"enabled":false,"api_key":"","greet_interval_min":0}',encoding='utf-8')
        (stage/'pet_settings.json').write_text(json.dumps({'scale':1,'sound_on':False,'tts_on':False,'fg_watch':False}),encoding='utf-8')
        sys.path.insert(0,str(stage))
        import tkinter as tk
        import pet
        import ai_chat
        root=tk.Tk()
        try:
            with patch.object(pet.Pet,'tick'),patch.object(pet.Pet,'start_tray'),patch.object(pet.SFX,'play'),patch.object(ai_chat,'AIBrain',return_value=None):
                p=pet.Pet(root,selftest=True)
            root.withdraw()
            p.selftest=False
            p._push=lambda image:None
            p._tray=None
            p.sfx.enabled=False
            p._pump=lambda:None
            p._fg_watch_tick=lambda now:None
            p.reminders,p.pomo,p.water_min=[],None,0
            p.cfg['blink_overlay']=True
            bg=background()
            scenes=[('presence',[('look',3.6),('nuzzle',2.4)]),
                    ('magic',[('transform',3.2),('dance',4.4)]),
                    ('play',[('drag',3.2),('ball',3.6)])]
            labels={
                'look':('01','你的目光，\n她会回应。','轻微转头 · 自然呼吸','头部、身体与发梢，\n各有一点自己的节奏。'),
                'nuzzle':('01','轻轻摸头，\n靠近一点。','摸头反馈 · 轻蹭回应','一次小小的互动，\n也有认真回应。'),
                'transform':('02','施一点魔法，\n点亮日常。','星带 · 光圈 · 变身','动作和星光一起出现。\n这次，让桌面热闹一点。'),
                'dance':('02','想开心，\n就跳一支舞。','节拍摆动 · 动作节选','踩着星光，\n把快乐晃给你看。'),
                'drag':('03','提起来，\n轻轻放下来。','速度反馈 · 柔和回正','移动有回应，\n停下也有小小的缓冲。'),
                'ball':('03','这一颗星，\n一起接住。','光球反弹 · 点击接住','点一下光球，\n收下她的星光回应。')}
            for name,segments in scenes:
                frames=[]
                for scene,duration in segments:
                    random.seed(18)
                    born=10000.0
                    p.t0=p.last=p.last_interact=born
                    p.state,p.fy,p.x='idle',p.ground_feet,500
                    p.look_x=p.look_y=p.lean=p._drag_lean=0
                    p.squash=1
                    p.hop_t=p.lean_kick=p._spin_rot=p._spin_lift=p._bend=0
                    p._micro_motion=p.bubble=p.sticker=p.drag=p._sticker_previous=None
                    p.parts,p.circles,p._afters,p._shocks,p._drag_trail=[],[],[],[],[]
                    p._afterimage_on=False
                    p._starform_until=p.blink_until=0
                    p._depth_motion=pet.DepthMotion()
                    p.star=75
                    p.next_trail=0
                    for attr in ('next_event','next_whine','next_ambient','next_meteor','next_blink','next_seasonal','_curious_cd','_next_screen_check'):
                        setattr(p,attr,born+1000)
                    with patch.object(pet.time,'time',return_value=born):
                        if scene in ('transform','dance'): getattr(p,'start_'+scene)()
                        elif scene=='ball': p.throw_ball()
                        elif scene=='drag': p.drag=(100,100,500,p.ground_feet,False,born)
                        elif scene=='nuzzle': p._start_micro_motion('nuzzle')
                    for i in range(round(duration*FPS)):
                        age=i/FPS
                        now=born+age
                        cursor=(round(p.x+p.W/2),round(p.fy-p.H*.18))
                        with patch.object(pet.time,'time',return_value=now),patch.object(pet,'cursor_pos',return_value=cursor):
                            if scene=='look':
                                p.look_x=math.sin(age*1.6)*.95
                                p.look_y=.18*math.sin(age*1.1)
                                p.lean=.028*math.sin(age*1.6)
                                if .65<age<.78: p.blink_until=now+.01
                            else:
                                if scene=='drag':
                                    if age<1.4:
                                        p.on_drag(SimpleNamespace(x_root=100+75*min(1,age/.65),y_root=100-30*min(1,age/.6)))
                                    elif i==38:p.on_release(SimpleNamespace())
                                if scene=='ball' and i==45:
                                    p._advance_ball(now)
                                    b=next(q for q in p.parts if q['kind']=='ball')
                                    p._catch_ball(b['x'],b['y'])
                                p._tick_body()
                            # Keep original action particles, but suppress random phrase/sticker
                            # overlays so this fixed editorial viewport stays readable.
                            p.bubble=p.sticker=None
                            p.render(now,age)
                        art=p._frame_buf.resize((p.W,p.H),Image.Resampling.LANCZOS)
                        if scene=='look' and i==12:
                            hero(p._frame_buf.crop(p._frame_buf.getbbox()))
                            if args.hero_only:
                                p.sfx.close_all()
                                return
                        frame=panel(bg,art,*labels[scene],dx=(p.x-500)*.35,dy=(p.fy-p.ground_feet)*.35)
                        if scene=='ball' and i in range(40,49):
                            # An editorial click indicator, explicitly part of the demo.
                            d=ImageDraw.Draw(frame)
                            d.text((780,515),'点击光球',font=font(12),fill=GOLD)
                        frames.append(frame)
                save_animation(name,frames,20 if name!='magic' else 28)
            p.sfx.close_all()
        finally:
            root.destroy()
    print('Showcase complete; temporary pet closed.',flush=True)


if __name__=='__main__': main()
