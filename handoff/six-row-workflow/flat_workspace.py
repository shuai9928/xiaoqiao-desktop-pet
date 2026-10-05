"""Half-height workspace. Public actions above; live agent lights and AIQuota below."""
import json, math, os, time
from pathlib import Path
from PIL import Image,ImageColor,ImageDraw
from apple_ui import font
from ai_quota import quota_view, _number, _used, _timestamp
from moon_board import workflow,_fit

BG='#1d1e2e';SURFACE='#2b2c32';LINE='#363850';INK='#f4f5fc';DIM='#b4b7cc';ACCENT='#baa3ed';RIM='#666b96'
COLORS={'running':ACCENT,'waiting':'#efba70','error':'#f39292','done':'#83caa2','idle':DIM,'recorded':DIM}
W,H=440,260
PANEL_REST=232;PANEL_ACTIVE=248   # per-pixel alpha of the panel fill (not blur); rim, glyphs and text stay opaque
SHAPES={'running':'star','waiting':'ring','error':'tri','done':'dot','idle':'dot','recorded':'dot'}
LIST=(170,42,254,108)
ROW=18
AGENT_ORDER=('Codex','Claude','ZCode')
LIVE_H=170;LIVE_ROWS=2;LIVE=('running','waiting','error');DEFAULT_MODE='live'
NAMES={'Claude':'#cfac94','Codex':'#b9c6e5'}


def agent_name(raw):
    """Map session source keys (including Mac/WSL variants) to a visible agent."""
    value=str(raw or 'AI').lower()
    if value.startswith('mac-claude') or 'claude' in value:return 'Claude'
    if value.startswith('mac-codex') or 'codex' in value:return 'Codex'
    if 'zcode' in value:return 'ZCode'
    if value.startswith('mac'):return 'Mac'
    return 'AI'


def selected_agent(ui):
    """The strip selection drives the workflow list; default to the app selection."""
    raw=ui.get('flat_agent') or (ui.get('sel_session') or {}).get('agent') or ui.get('sel_key')
    return agent_name(raw) if raw else 'ZCode'


def sessions_for(ui,name=None):
    name=name or selected_agent(ui)
    return [s for s in ui.get('sessions') or [] if agent_name(s.get('agent'))==name]


def session_for(ui,name=None,prefer_current=True):
    """Pick a provider's freshest live session, falling back to its latest record."""
    rows=sessions_for(ui,name)
    current=ui.get('sel_session') or {}
    if prefer_current and current and agent_name(current.get('agent'))== (name or selected_agent(ui)):
        return current
    def rank(s):
        state=s.get('state','idle')
        f=workflow(dict(ui,sel_session=s))
        priority={'running':0,'waiting':1,'error':2,'done':3,'idle':4}
        return (0 if not f['stale'] and state in ('running','waiting','error') else 1,
                priority.get(state,4),-(_number(s.get('updated')) or 0))
    return min(rows,key=rank) if rows else None


def _mode(owner):return getattr(owner,'_flat_mode',DEFAULT_MODE)


def _swing_sessions(owner):
    sw=getattr(owner,'_swing',None);ui=sw.get('ui') if isinstance(sw,dict) else None
    rows=ui.get('sessions') if isinstance(ui,dict) else None
    return rows if isinstance(rows,list) else []


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
        session=session_for(ui)
        if session is None:return []
        f=workflow(dict(ui,sel_session=session))
        return [dict(s,id=f['session'].get('id'),state=s['status']) for s in reversed(f['steps'])]
    rows=[]
    for s in (ui.get('sessions') or [] if mode=='live' else sessions_for(ui)):
        f=workflow(dict(ui,sel_session=s));steps=f['steps']
        if not steps:continue
        state='idle' if f['stale'] else s.get('state','idle')
        step=steps[-1] if steps else {}
        rows.append(dict(id=s.get('id'),title=step.get('title') or '暂无步骤记录',state=state,
                         result=step.get('result',''), index=step.get('index'),
                         updated=_number(s.get('updated')) or 0,agent=agent_name(s.get('agent')),chain=[x.get('status') for x in steps]))
    priority={'running':0,'waiting':1,'error':2,'done':3,'idle':4}
    return sorted(rows,key=lambda r:(priority.get(r['state'],4),-r['updated']))


def agent_lights(ui):
    groups={name:'idle' for name in AGENT_ORDER}
    # This strip answers whether ANY agent is still running, independently
    # of errors or completion in another session from the same provider.
    priority={'running':0,'error':1,'waiting':2,'idle':3}
    for s in ui.get('sessions') or []:
        name=agent_name(s.get('agent'))
        f=workflow(dict(ui,sel_session=s));state=s.get('state','idle')
        state=state if not f['stale'] and state in ('running','waiting','error') else 'idle'
        if name not in groups or priority[state]<priority[groups[name]]:groups[name]=state
    return [(name,groups[name]) for name in (*AGENT_ORDER,'Mac','AI') if name in groups]


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
    if _mode(owner)=='live':return
    sw=owner._swing;rows=rows_for(sw.get('ui') or {},_mode(owner))
    limit=max(0,len(rows)*ROW-LIST[3])
    owner._flat_scroll=min(limit,max(0,getattr(owner,'_flat_scroll',0)-delta/120*ROW))
    owner._flat_cache=None


def bar_input(owner,e,phase):
    sw=getattr(owner,'_swing',None) or {};g=sw.get('geo') or {}
    if not g.get('flat'):return False
    if phase=='release':
        active=getattr(owner,'_flat_bar_drag',None) is not None
        owner._flat_bar_drag=None;return active
    if _mode(owner)=='live':return False
    u=g['u'];n=len(rows_for(sw.get('ui') or {},_mode(owner)))
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
    elif kind=='flat_task':
        owner._book_sel=('sid',payload);owner._flat_mode='steps';owner._flat_scroll=0
        s=next((x for x in _swing_sessions(owner) if isinstance(x,dict) and str(x.get('id'))==str(payload)),None)
        if s:owner._flat_agent=agent_name(s.get('agent'))
    elif kind=='flat_agent':
        name=str(payload or '')
        if name not in AGENT_ORDER:return False
        owner._flat_agent=name;owner._flat_mode='tasks';owner._flat_scroll=0
        ui=((getattr(owner,'_swing',None) or {}).get('ui') or {})
        session=session_for(ui,name,prefer_current=False)
        if session:owner._book_sel=('agent',session.get('agent'))
    elif kind=='flat_page':scroll(owner,-payload*120*(LIST[3]//ROW))
    elif kind=='flat_top':owner._flat_scroll=0
    else:return False
    owner._flat_cache=None;return True


def _pen(u):
    im=Image.new('RGBA',(round(W*u),round(H*u)));d=ImageDraw.Draw(im);hits=[]
    def box(rect,color,r=0,outline=None):
        x,y,a,b=rect;d.rounded_rectangle(tuple(round(v*u) for v in (x,y,x+a,y+b)),radius=round(r*u),fill=color,outline=outline,width=1)
    def txt(x,y,s,size=13,color=INK,width=None,weight=450,anchor='la'):
        f=font(round(size*u),weight);d.text((round(x*u),round(y*u)),_fit(s,f,width*u) if width else str(s),font=f,fill=color,anchor=anchor)
    def hit(rect,kind,payload=None):hits.append(tuple(round(v*u) for v in rect)+(kind,payload))
    return im,d,hits,box,txt,hit


def glyph(im,cx,cy,r,color,shape,u,glow=False):
    """Status glyph centred at (cx,cy) in panel units, drawn 8x supersampled. Shape carries the state as well as colour:
    star = running, ring = waiting, tri = error, dot = done/idle (so error vs done survives red-green colour blindness)."""
    k=8;g=int((r+5)*2*u*k)+2;t=Image.new('RGBA',(g,g));td=ImageDraw.Draw(t);c=g/2;s=r*u*k;col=ImageColor.getrgb(color)
    if glow:e=(r+2.6)*u*k;td.ellipse((c-e,c-e,c+e,c+e),fill=col+(90,))
    if shape=='star':
        R=1.34*s;td.polygon([(c+(R if i%2==0 else R*.46)*math.cos(math.radians(-90+45*i)),c+(R if i%2==0 else R*.46)*math.sin(math.radians(-90+45*i))) for i in range(8)],fill=col)
    elif shape=='ring':
        td.ellipse((c-1.12*s,c-1.12*s,c+1.12*s,c+1.12*s),fill=col);td.ellipse((c-.52*s,c-.52*s,c+.52*s,c+.52*s),fill=(0,0,0,0))
    elif shape=='tri':
        td.polygon([(c,c-1.22*s),(c+1.12*s,c+.82*s),(c-1.12*s,c+.82*s)],fill=col)
    else:td.ellipse((c-s,c-s,c+s,c+s),fill=col)
    t=t.resize((max(1,round(g/k)),max(1,round(g/k))),Image.LANCZOS);im.alpha_composite(t,(round(cx*u-t.width/2),round(cy*u-t.height/2)))


def panel_fill(ui):
    """BG as #rrggbbaa. ImageDraw writes this alpha into an RGBA image as-is (no blending)."""
    return BG+'%02x'%max(0,min(255,int(ui.get('panel_alpha',PANEL_REST))))


def panel_alpha(owner,ui,mode):
    """Calm at rest; more opaque when expanded, hovered (owner._flat_hover, set by the host) or something needs attention."""
    attention=any(isinstance(s,dict) and s.get('state') in ('waiting','error') for s in ui.get('sessions') or [])
    return PANEL_ACTIVE if mode!='live' or attention or getattr(owner,'_flat_hover',False) else PANEL_REST


def live_title(rows):
    n={k:sum(r['state']==k for r in rows) for k in LIVE}
    if n['waiting']:return f"{n['waiting']} 个在等你确认"
    if n['error']:return f"{n['error']} 个出错了"
    if n['running']:return f"我看着呢 · {n['running']} 个在跑"
    return '都忙完啦' if rows else '暂时没有任务'


def render_live(ui,u=1):
    """Compact view: live sessions of every agent, a dot chain per session, quota in the right column.
    Draws in the top LIVE_H of the same window; the rest stays transparent so the window size is unchanged."""
    im,d,hits,box,txt,hit=_pen(u)
    rows=rows_for(ui,'live');live=[r for r in rows if r['state'] in LIVE];shown=live[:LIVE_ROWS]
    box((0,0,W-1,LIVE_H-1),panel_fill(ui),16,RIM)
    txt(173,13,live_title(rows),13,width=205,weight=550)
    txt(420,14,'聊聊',11,ACCENT,anchor='ra');hit((386,7,40,30),'house_chat')
    for i,row in enumerate(shown):
        y=38+i*32;col=COLORS.get(row['state'],DIM);idx=row['index'];chain=row['chain'];cut=len(chain)>6;chain=chain[-6:];x0=208 if cut else 190
        glyph(im,175,y+8,3.5,col,SHAPES.get(row['state'],'dot'),u)
        txt(186,y,row['agent'],11,NAMES.get(row['agent'],'#b9c6e5'),width=40)
        txt(228,y-1,row['title'],12,width=148)
        txt(420,y,f"第 {idx+1 if isinstance(idx,int) else len(chain)} 步",10,DIM,anchor='ra')
        if cut:glyph(im,190,y+23,1.3,'#656772','dot',u);glyph(im,195,y+23,1.3,'#656772','dot',u)
        if len(chain)>1:box((x0,y+23,13*(len(chain)-1),1),'#4a4b54')
        for j,st in enumerate(chain):
            last=j==len(chain)-1
            if last:glyph(im,x0+j*13,y+23.5,4.2,col,SHAPES.get(row['state'],'dot'),u,True)
            else:glyph(im,x0+j*13,y+23.5,2.6 if st in ('done','idle') else 3.1,COLORS.get(st,DIM),SHAPES.get(st,'dot'),u)
        hit((172,y-4,252,30),'flat_task',row['id'])
    if not shown:txt(186,56,'现在没有在跑的任务' if rows else '暂无步骤记录',12,DIM,width=225)
    rest=len(rows)-len(shown)
    if rest>0:
        y=38+len(shown)*32+2 if shown else 82;go=rows[0]['agent']
        txt(186,y,f"另有 {rest} 个{'会话' if len(live)>len(shown) else '已结束'} · 展开",10.5,DIM,width=200)
        d.polygon([(round(410*u),round((y+6)*u)),(round(418*u),round((y+6)*u)),(round(414*u),round((y+11)*u))],fill=DIM)
        hit((172,y-3,252,18),*(('flat_agent',go) if go in AGENT_ORDER else ('flat_mode','tasks')))
    box((173,121,251,1),LINE)
    for i,row in enumerate(quota_rows(ui)[:2]):
        y=128+i*17;txt(173,y,row['name'],11,NAMES.get(row['name'],'#b9c6e5'),width=42)
        if not row['cycles']:txt(217,y,'暂无数据',11,DIM)
        for j,c in enumerate(row['cycles'][:2]):
            x=217+j*84;v=c['used'];stale=c['stale'];col=DIM if stale else COLORS['error'] if v is not None and v>=90 else '#efba70' if v is not None and v>=70 else '#83caa2'
            txt(x,y,c['label'],10,DIM);box((x+13,y+10,30,4),LINE,2)
            if v is not None and v>0:box((x+13,y+10,max(2,30*v/100),4),col,2)
            txt(x+78,y,('—' if v is None else f'{v:.0f}%')+('旧' if stale and v is not None else ''),11,col,anchor='ra')
    txt(420,129,'模拟' if ui.get('mock') else '已用',10,DIM,anchor='ra')
    hit((172,120,252,46),'swallow')
    return im,[q for q in hits if q[2]>0 and q[3]>0],0


def render(ui,u=1,mode='tasks',offset=0):
    if mode=='live':return render_live(ui,u)
    im,d,hits,box,txt,hit=_pen(u)
    box((0,0,W-1,H-1),panel_fill(ui),16,RIM)
    agent=selected_agent(ui)
    txt(173,13,f'{agent} · 当前步骤' if mode=='steps' else f'{agent} 工作流 · 当前步骤',13,weight=550,width=185)
    txt(420,14,'返回' if mode=='steps' else '聊聊',11,ACCENT,anchor='ra')
    hit((386,7,40,30),'flat_mode' if mode=='steps' else 'house_chat','tasks' if mode=='steps' else None)
    if mode=='tasks':txt(384,14,'收起',11,ACCENT,anchor='ra');hit((350,7,34,30),'flat_mode','live')
    rows=rows_for(ui,mode);n=len(rows);offset=max(0,min(float(offset),max(0,n*ROW-LIST[3])))
    crop=Image.new('RGBA',(round(LIST[2]*u),round(LIST[3]*u)))
    for i,row in enumerate(rows):
        yy=i*ROW-offset
        if yy+ROW<=0 or yy>=LIST[3]:continue
        tile=Image.new('RGBA',(round(240*u),round(ROW*u)));td=ImageDraw.Draw(tile)
        col=COLORS.get(row['state'],DIM)
        glyph(tile,5,ROW/2,3.2,col,SHAPES.get(row['state'],'dot'),u)
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
    for i,(name,st) in enumerate(lamps):
        x=66+i*67;col=COLORS[st] if st!='idle' else '#656772'
        if name==agent:
            box((x-3,159,62,23),'#35343d',5,ACCENT)
        glyph(im,x+3.5,170.5,3.4,col,SHAPES.get(st,'dot'),u);txt(x+12,163,name,11,ACCENT if name==agent else INK if st!='idle' else DIM)
        if name in AGENT_ORDER:hit((x-3,159,62,23),'flat_agent',name)
    hit((16,160,42,25),'house_trace')
    txt(420,164,'模拟' if ui.get('mock') else '已用',10,DIM,anchor='ra')
    box((16,187,408,1),LINE)
    for i,row in enumerate(quota_rows(ui)[:3]):
        y=190+i*21
        txt(18,y,row['name'],11,'#cfac94' if row['name']=='Claude' else '#b9c6e5',width=80)
        if not row['cycles']:txt(113,y,'暂无数据',11,DIM)
        for j,c in enumerate(row['cycles']):
            x=105+j*156;v=c['used'];stale=c['stale'];col=DIM if stale else COLORS['error'] if v is not None and v>=90 else '#efba70' if v is not None and v>=70 else '#83caa2'
            txt(x,y,c['label'],10,DIM)
            box((x+23,y+10,70,4),LINE,2)
            if v is not None and v>0:box((x+23,y+10,max(2,70*v/100),4),col,2)
            txt(x+145,y,('—' if v is None else f'{v:.0f}%')+('旧' if stale and v is not None else ''),11,col,anchor='ra')
    hit((16,188,408,67),'swallow')
    return im,[q for q in hits if q[2]>0 and q[3]>0],offset


def push(owner,small):
    from pet import push_layered,SWING_PERSP
    sw=owner._swing;g=sw['geo'];u=g['u'];ui=live_ui(owner,sw.get('ui') or {});mode=_mode(owner)
    ui=dict(ui,flat_agent=getattr(owner,'_flat_agent',None) or selected_agent(ui))
    ui=dict(ui,panel_alpha=panel_alpha(owner,ui,mode))
    key=(repr(tuple(ui.get(n) for n in ('sessions','sel_session','quota','codex_quota','codex_quota_error','mock','quota_widget','flat_agent','panel_alpha'))),int((ui.get('now') or time.time())/15),u,mode,getattr(owner,'_flat_scroll',0))
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

