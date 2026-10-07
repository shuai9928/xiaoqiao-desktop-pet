"""Export the shipped AI page renderer with clearly synthetic snapshots."""

from pathlib import Path
import sys
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "tests"))

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw

from pet import Pet, load_font
from scene_art import SceneArt


def demo():
    now = 1791088320.0
    sessions = [
        {'id':'ui-demo-z', 'agent':'zcode', 'title':'小乔界面打磨', 'state':'running', 'updated':now,
         'actions':[{'t':now, 'a':'验证缩小后的点击区域', 'r':'正在检查'},
                    {'t':now-60, 'a':'调整信息层级', 'r':'完成：标题、来源和正文分层'},
                    {'t':now-120, 'a':'检查布局', 'r':'完成：面板移到人物侧边'}]},
        {'id':'ui-demo-m', 'agent':'mac-claude', 'title':'布局审核', 'state':'waiting', 'updated':now-20,
         'actions':[{'t':now-20, 'a':'等待审核结论', 'r':'等待确认'}]},
        {'id':'ui-demo-w', 'agent':'wslcodex', 'title':'回归检查', 'state':'done', 'updated':now-40,
         'actions':[{'t':now-40, 'a':'运行检查', 'r':'完成'}]},
    ]
    return {'now':now, 'sources':[('zcode','ZCode','Z'), ('mac-claude','Claude·Mac','M'),
                                  ('wslcodex','Codex·WSL','W'), ('claude','Claude','C')],
            'sel_key':'zcode', 'sel_session':sessions[0], 'sessions':sessions, 'book_tab':'trace',
            'quota':{'t':now*1000,'fh':32,'sd':58,'reset_est':now+3600}, 'quota_age':0,
            'mock':True, 'book_rect':(12,12,400,520), 'book_anim':1, 'new_n':0,
            'badge':{'mac-claude':'waiting'}, 'muted':[]}


def make_owner():
    p=Pet.__new__(Pet)
    p.glow_cache={}
    p._trace_page=p._session_page=0
    p._trace_snap=None
    p.ai_mute_sess=set()
    return p


def page(p, ui, name, output):
    image=Image.new('RGBA',(424,544))
    hits=[]
    p._draw_book_v2(image,ImageDraw.Draw(image),{},ui,hits)
    image.save(output/name)
    return image, hits


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    p=make_owner();ui=demo()
    trace,hits=page(p,ui,'实际界面-工作轨迹.png',args.out)
    quota,_=page(p,dict(ui,book_tab='overview',sel_key='claude',sel_session=None),
                 '实际界面-额度.png',args.out)
    unknown,_=page(p,dict(ui,book_tab='overview',quota=None,quota_age=None),
                   '实际界面-未接入.png',args.out)
    offline,_=page(p,dict(ui,book_tab='overview',sel_key='claude',quota_age=7200,
                         sel_session=dict(ui['sel_session'],stale=True)),
                   '实际界面-过期离线.png',args.out)
    scene=SceneArt(Path(__file__).resolve().parents[2]/'assets'/'scene')
    k=.32
    layers=scene.scaled(k)
    size=tuple(round(v*k)+12 for v in scene.size)
    original=Image.new('RGBA',size)
    for key in ('static','swing','book','crystal'):
        image,pos=layers[key]
        original.alpha_composite(image,(round(pos[0])+6,round(pos[1])+6))
    for scale in (1.0,.76):
        portrait=original.convert('RGBa').resize(tuple(round(v*scale) for v in size),Image.Resampling.LANCZOS).convert('RGBA')
        width=portrait.width+trace.width+52
        board=Image.new('RGBA',(width,600),'#1b1629')
        d=ImageDraw.Draw(board)
        d.text((20,12),'实际渲染 · 演示数据 · 场景 '+str(int(scale*100))+'%',font=load_font(14),fill='#b5a9ca')
        board.alpha_composite(portrait,(12,80))
        board.alpha_composite(trace,(portrait.width+32,42))
        board.convert('RGB').save(args.out/('实际界面-人物侧页-'+str(scale)+'.png'))
    metadata={'source':'shipped Pet._draw_book_v2 + ai_work_ui, offline synthetic snapshots',
              'ui_size':[424,544],'text_scale_changes_with_scene':False,
              'screens':['trace','quota','unknown','stale+offline'],'hits':hits,
              'no_model_calls':True,'no_user_files':True}
    (args.out/'ui-verification.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Actual UI renderer exports saved; all task and quota values are synthetic.')


if __name__=='__main__':
    main()
