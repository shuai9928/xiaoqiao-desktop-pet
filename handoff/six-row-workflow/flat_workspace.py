"""Half-height workspace. Public actions above; live agent lights and AIQuota below."""
import json, math, os, time
from pathlib import Path
from PIL import Image,ImageDraw
from apple_ui import font
from ai_quota import quota_view, _number, _used, _timestamp
from moon_board import workflow,_fit

BG='#202126';SURFACE='#2b2c32';LINE='#3c3d44';INK='#f4f4f6';DIM='#a5a5af';ACCENT='#baa3ed'
COLORS={'running':ACCENT,'waiting':'#efba70','error':'#ef8585','done':'#83caa2','idle':DIM,'recorded':DIM}
W,H=440,260
LIST=(170,42,254,108)
ROW=18


def geometry(owner, geo):
    from pet import ChatBox
    u=ChatBox._layout(owner.sw,owner.sh)[0]
    sa=owner._scene_art;stand=owner._studio();bx,by,ex,ey=stand.bounds()
    k=min(142*u/(ex-bx),140*u/(ey-by))
    gb=sa.girl_bbox;sprh=owner._spr_disp_h();ss=k*(gb[3]-gb[1])/sprh
    cx=82*u;top=15*u
    O=((bx+ex)*k/2-cx,by*k-top)
    geo.update(k=k,ss=ss,O=O,size=(round(W*u),round(H*u)),flat=True,u=u,
               gtl=(gb[0]*k,gb[1]*k),anchor=((gb[0]+gb[2])/2*k,(gb[1]+(gb[3]-gb[1])*.45)*k))
    geo.pop('studio',None);geo.pop('house_layout',None);geo.pop('moon_house',None)
    return geo


def rows_for(ui,mode):
    if mode=='steps':
        f=workflow(ui)
        return [dict(s,id=f['session'].get('id'),state=s['status']) for s in reversed(f['steps'])]
    rows=[]
    for s in ui.get('sessions') or []:
        f=workflow(dict(ui,sel_session=s));steps=f['steps']
        if not steps:continue
        state='idle' if f['stale'] else s.get('state','idle')
        step=steps[-1] if steps else {}
        rows.append(dict(id=s.get('id'),title=step.get('title') or '暂无步骤记录',state=state,
                         result=step.get('result',''), index=step.get('index'),
                         updated=_number(s.get('updated')) or 0))
    priority={'running':0,'waiting':1,'error':2,'done':3,'idle':4}
    return sorted(rows,key=lambda r:(priority.get(r['state'],4),-r['updated']))


def agent_lights(ui):
    groups={}
    # This strip answers whether ANY agent is still running, independently
    # of errors or completion in another session from the same provider.
    priority={'running':0,'error':1,'waiting':2,'idle':3}
    for s in ui.get('sessions') or []:
        raw=str(s.get('agent') or 'AI').lower()
        name='Mac' if raw.startswith('mac') else ('Codex' if 'codex' in raw else 'Claude' if 'claude' in raw else 'ZCode' if 'zcode' in raw else 'AI')
        f=workflow(dict(ui,sel_session=s));state=s.get('state','idle')
        state=state if not f['stale'] and state in ('running','waiting','error') else 'idle'
        if name not in groups or priority[state]<priority[groups[name]]:groups[name]=state
    return [(name,groups[name]) for name in ('Codex','Claude','ZCode','Mac','AI') if name in groups]


def widget_rows(raw,now):
    """Whitelist display-only values from AIQuota; never read credentials/config."""
    if not isinstance(raw,dict) or raw.get('schemaVersion')!=1:return []
    providers=raw.get('providers')
    if not isinstance(providers,list):return []
    result=[]
    for p in providers[:12]:
        if not isinstance(p,dict):continue
        name=p.get('name')
        if name not in ('Claude','Codex','Codex WSL'):continue
        stamp=_timestamp(p.get('updated'));ttl=_number(p.get('staleAfter'))
        stale=bool(p.get('stale') or p.get('error') or stamp is None or stamp>now or now-stamp>(ttl if ttl and ttl>0 else 300))
        windows=p.get('windows');cycles=[]
        for c in (windows if isinstance(windows,list) else [])[:2]:
            if not isinstance(c,dict):continue
            reset=_timestamp(c.get('resetUnix'))
            cycles.append({'label':str(c.get('short') or '?')[:4],'used':_used(c.get('used')),
                           'reset':reset,'stale':stale or (reset is not None and reset<=now)})
        result.append({'name':name,'cycles':cycles,'stale':stale,'t':stamp})
    return result


def live_ui(owner,ui):
    if ui.get('mock'):return ui
    now=time.time()
    if now-getattr(owner,'_flat_quota_read',0)>=5:
        owner._flat_quota_read=now
        try:
            path=Path(os.environ.get('LOCALAPPDATA',''))/'AIQuota'/'usage.json'
            if path.stat().st_size>65536:raise ValueError('oversize')
            raw=json.loads(path.read_text(encoding='utf-8-sig'))
            if not widget_rows(raw,now):raise ValueError('invalid')
            owner._flat_quota_raw=raw;owner._flat_quota_error=False
        except (OSError,ValueError,TypeError,RecursionError):
            owner._flat_quota_error=True
    rows=widget_rows(getattr(owner,'_flat_quota_raw',None),now)
    if getattr(owner,'_flat_quota_error',False):
        for row in rows:
            row['stale']=True
            for c in row['cycles']:c['stale']=True
    return dict(ui,quota_widget=rows)


def quota_rows(ui):
    if 'quota_widget' in ui:
        return ui['quota_widget'] or [{'name':n,'cycles':[],'stale':True} for n in ('Claude','Codex')]
    return [{'name':name,'stale':q['stale'],'cycles':[dict(c,label=label) for c,label in zip(q['cycles'],('5h','周'))]}
            for provider,name in (('claude','Claude'),('codex','Codex')) for q in [quota_view(ui,provider)]]


def scroll(owner,delta):
    sw=owner._swing;rows=rows_for(sw.get('ui') or {},getattr(owner,'_flat_mode','tasks'))
    limit=max(0,len(rows)*ROW-LIST[3])
    owner._flat_scroll=min(limit,max(0,getattr(owner,'_flat_scroll',0)-delta/120*ROW))
    owner._flat_cache=None


def bar_input(owner,e,phase):
    sw=getattr(owner,'_swing',None) or {};g=sw.get('geo') or {}
    if not g.get('flat'):return False
    if phase=='release':
        active=getattr(owner,'_flat_bar_drag',None) is not None
        owner._flat_bar_drag=None;return active
    u=g['u'];n=len(rows_for(sw.get('ui') or {},getattr(owner,'_flat_mode','tasks')))
    if n*ROW<=LIST[3]:return False
    thumb=max(20,LIST[3]**2/(n*ROW));limit=n*ROW-LIST[3]
    if phase=='press':
        if not (414*u<=e.x<=426*u and LIST[1]*u<=e.y<=(LIST[1]+LIST[3])*u):return False
        ty=LIST[1]+getattr(owner,'_flat_scroll',0)/limit*(LIST[3]-thumb)
        owner._flat_bar_drag=e.y/u-ty if ty<=e.y/u<=ty+thumb else thumb/2
    grab=getattr(owner,'_flat_bar_drag',None)
    if grab is None:return False
    owner._flat_scroll=max(0,min(limit,(e.y/u-LIST[1]-grab)/(LIST[3]-thumb)*limit))
    owner.last_interact=time.time();owner._flat_cache=None;return True


def action(owner,kind,payload):
    if kind=='flat_mode':owner._flat_mode=payload;owner._flat_scroll=0
    elif kind=='flat_task':owner._book_sel=('sid',payload);owner._flat_mode='steps';owner._flat_scroll=0
    elif kind=='flat_page':scroll(owner,-payload*120*3)
    elif kind=='flat_top':owner._flat_scroll=0
    else:return False
    owner._flat_cache=None;return True


def render(ui,u=1,mode='tasks',offset=0):
    w,h=round(W*u),round(H*u);im=Image.new('RGBA',(w,h));d=ImageDraw.Draw(im);hits=[]
    def box(rect,color,r=0,outline=None):
        x,y,a,b=rect;d.rounded_rectangle(tuple(round(v*u) for v in (x,y,x+a,y+b)),radius=round(r*u),fill=color,outline=outline,width=1)
    def txt(x,y,s,size=13,color=INK,width=None,weight=450,anchor='la'):
        f=font(round(size*u),weight);d.text((round(x*u),round(y*u)),_fit(s,f,width*u) if width else str(s),font=f,fill=color,anchor=anchor)
    def hit(rect,kind,payload=None):hits.append(tuple(round(v*u) for v in rect)+(kind,payload))
    box((0,0,W-1,H-1),BG,16,LINE)
    txt(173,13,'当前步骤' if mode=='steps' else '工作流 · 当前步骤',13,weight=550)
    txt(420,14,'返回' if mode=='steps' else '聊聊',11,ACCENT,anchor='ra')
    hit((386,7,40,30),'flat_mode' if mode=='steps' else 'house_chat','tasks' if mode=='steps' else None)
    rows=rows_for(ui,mode);n=len(rows);offset=max(0,min(float(offset),max(0,n*ROW-LIST[3])))
    crop=Image.new('RGBA',(round(LIST[2]*u),round(LIST[3]*u)))
    for i,row in enumerate(rows):
        yy=i*ROW-offset
        if yy+ROW<=0 or yy>=LIST[3]:continue
        tile=Image.new('RGBA',(round(240*u),round(ROW*u)));td=ImageDraw.Draw(tile)
        col=COLORS.get(row['state'],DIM)
        td.ellipse((2*u,6*u,8*u,12*u),fill=col)
        f=font(round(12*u),450)
        td.text((17*u,ROW*u/2),_fit(row['title'],f,218*u),font=f,fill=INK,anchor='lm')
        src=max(0,round(-yy*u));dst=max(0,round(yy*u));height=min(tile.height-src,crop.height-dst)
        if height>0:crop.alpha_composite(tile.crop((0,src,tile.width,src+height)),(0,dst))
        kind,payload=('flat_task',row['id']) if mode=='tasks' else ('detail',(row['id'],row['index'],row['title'],row.get('result','')))
        hit((LIST[0],LIST[1]+max(0,yy),240,min(ROW+min(0,yy),LIST[3]-max(0,yy))),kind,payload)
    im.alpha_composite(crop,(round(LIST[0]*u),round(LIST[1]*u)))
    if not rows:txt(185,76,'暂无步骤记录',12,DIM,width=225)
    if n*ROW>LIST[3]:
        thumb=max(20,LIST[3]**2/(n*ROW));ty=LIST[1]+offset/(n*ROW-LIST[3])*(LIST[3]-thumb)
        box((419,LIST[1],3,LIST[3]),LINE,1);box((419,ty,3,thumb),'#8e8c98',1)
        hit((414,LIST[1],10,max(0,ty-LIST[1])),'flat_page',-1)
        hit((414,ty+thumb,10,max(0,LIST[1]+LIST[3]-ty-thumb)),'flat_page',1)
    hit(LIST,'swallow')
    box((16,158,408,1),LINE)
    txt(17,163,'Agent',10,DIM)
    lamps=agent_lights(ui)
    if not lamps:txt(67,163,'暂无运行记录',11,DIM)
    for i,(name,st) in enumerate(lamps):
        x=66+i*70;col={'running':'#83caa2','waiting':'#efba70','error':'#ef8585','idle':'#656772'}[st]
        box((x,171,6,6),col,3);txt(x+11,163,name,11,INK if st!='idle' else DIM)
    hit((16,160,359,25),'house_trace')
    txt(420,164,'模拟' if ui.get('mock') else '已用',10,DIM,anchor='ra')
    box((16,187,408,1),LINE)
    for i,row in enumerate(quota_rows(ui)[:3]):
        y=190+i*21
        txt(18,y,row['name'],11,'#cfac94' if row['name']=='Claude' else '#b9c6e5',width=80)
        if not row['cycles']:txt(113,y,'暂无数据',11,DIM)
        for j,c in enumerate(row['cycles']):
            x=105+j*156;v=c['used'];stale=c['stale'];col=DIM if stale else '#ef8585' if v is not None and v>=90 else '#efba70' if v is not None and v>=70 else '#83caa2'
            txt(x,y,c['label'],10,DIM)
            box((x+23,y+10,70,4),LINE,2)
            if v is not None and v>0:box((x+23,y+10,max(2,70*v/100),4),col,2)
            txt(x+145,y,('—' if v is None else f'{v:.0f}%')+('旧' if stale and v is not None else ''),11,col,anchor='ra')
    hit((16,188,408,67),'swallow')
    return im,[q for q in hits if q[2]>0 and q[3]>0],offset


def push(owner,small):
    from pet import push_layered,SWING_PERSP
    sw=owner._swing;g=sw['geo'];u=g['u'];ui=live_ui(owner,sw.get('ui') or {});mode=getattr(owner,'_flat_mode','tasks')
    key=(repr(tuple(ui.get(n) for n in ('sessions','sel_session','quota','codex_quota','codex_quota_error','mock','quota_widget'))),int((ui.get('now') or time.time())/15),u,mode,getattr(owner,'_flat_scroll',0))
    cache=getattr(owner,'_flat_cache',None)
    if cache is None or cache[0]!=key:
        base,hits,off=render(ui,u,mode,getattr(owner,'_flat_scroll',0));owner._flat_scroll=off;owner._flat_cache=(key,base,hits)
    else:_,base,hits=cache
    canvas=base.copy();sa=owner._scene_art;k=g['k'];O=g['O'];layers=sa.scaled(k)
    stand,at=owner._studio().render(k);owner._ac(canvas,stand,at[0]-O[0],at[1]-O[1])
    phase=round(sw.get('theta',0)/.008)*.008;pose=owner._art_pose(phase);face=owner._last_face_key
    ck=('flat',round(k,4),phase,face,pose['q'] if pose else None)
    cached=owner._ks_cache.get(ck)
    if cached is None:
        img,at=layers.get('swing_studio',layers['swing']);ov=owner._art_face_overlay(face,k)
        if ov:
            img=img.copy();owner._ac(img,ov[0],ov[1][0]-at[0],ov[1][1]-at[1])
        cached=sa.pose_keystone(img,at,k,phase,SWING_PERSP,pose) if pose else sa.keystone(img,at,k,phase,SWING_PERSP)
        owner._ks_cache.put(ck,cached)
    owner._ac(canvas,cached[0],cached[1][0]-O[0],cached[1][1]-O[1])
    sw['scene_canvas']=canvas;sw['ui_hits']=hits
    push_layered(owner.hwnd,canvas,sw['scene_l'],sw['scene_t'],255)
