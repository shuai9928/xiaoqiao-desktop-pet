import unittest,copy
from types import SimpleNamespace
from unittest.mock import patch,Mock
import flat_workspace as f
from test_moon_house import snapshot
from export_house_stage import owner
from test_ai_work_ui import owner as ui_owner
from PIL import Image
import pet

class FlatTests(unittest.TestCase):
 def ui(self,n=9):
  u=snapshot();s=u['sel_session'];u['sessions']=[dict(s,id=str(i),title=f'Task {i}') for i in range(n)];u['sel_session']=u['sessions'][0];return u
 def test_six_complete_rows_at_both_densities(self):
  for scale in (1,1.5):
   im,hits,off=f.render(self.ui(),scale)
   rows=[h for h in hits if h[4]=='flat_task'];self.assertEqual(len(rows),6)
   self.assertTrue(all(h[3]==round(18*scale) for h in rows));self.assertEqual(im.size,(round(f.W*scale),round(f.H*scale)))
 def test_every_task_reachable_no_hidden_cap(self):
  ui=self.ui(23);ids=set()
  for off in range(0,23*18,48):
   _,hits,_=f.render(ui,1,'tasks',off);ids.update(h[-1] for h in hits if h[4]=='flat_task')
  self.assertEqual(ids,{str(i) for i in range(23)})
 def test_track_click_pages_by_one_full_window(self):
  p=SimpleNamespace(_swing={'geo':{'flat':True,'u':1.5},'ui':self.ui(23)},_flat_mode='tasks');page=f.LIST[3]
  self.assertTrue(f.action(p,'flat_page',1));self.assertEqual(p._flat_scroll,page)
  self.assertTrue(f.action(p,'flat_page',1));self.assertEqual(p._flat_scroll,2*page)
  self.assertTrue(f.action(p,'flat_page',-1));self.assertEqual(p._flat_scroll,page)
 def test_steps_include_all_acquired_turns(self):
  ui=self.ui();ui['sel_session']['actions']=[{'a':f'Step{i}','r':'OK','t':ui['now']-i} for i in range(40)]
  ids=set()
  for off in range(0,40*18,96):
   _,hits,_=f.render(ui,1,'steps',off);ids.update(h[-1][1] for h in hits if h[4]=='detail')
  self.assertEqual(ids,set(range(40)))
 def test_scroll_clamps_and_never_rebuilds_scene(self):
  p=ui_owner();p.state='swing';p._swing={'geo':{'flat':True,'u':1.5},'ui':self.ui()};p._art_regeo=Mock();p._flat_mode='tasks'
  pet.Pet.on_wheel_scene(p,SimpleNamespace(x=300,y=100,delta=-120*100));self.assertEqual(p._flat_scroll,54);p._art_regeo.assert_not_called()
  pet.Pet.on_wheel_scene(p,SimpleNamespace(x=300,y=100,delta=120*100));self.assertEqual(p._flat_scroll,0)
  pet.Pet.on_wheel_scene(p,SimpleNamespace(x=100,y=50,delta=-120));self.assertEqual(p._flat_scroll,0)
 def test_partial_rows_have_clipped_click_targets(self):
  _,hits,_=f.render(self.ui(),1.5,'tasks',48)
  for x,y,w,h,kind,_ in hits:
   if kind=='flat_task':self.assertGreaterEqual(y,round(f.LIST[1]*1.5));self.assertLessEqual(y+h,round((f.LIST[1]+f.LIST[3])*1.5))
 def mixed(self):
  u=self.ui(6);s=u['sel_session']
  u['sessions']=[dict(s,id=str(i),title=f'Task {i}',state=st) for i,st in enumerate(('running','waiting','error','done','done','idle'))];u['sel_session']=u['sessions'][0];return u
 def test_live_mode_stays_in_compact_height_and_rest_is_transparent(self):
  for scale in (1,1.5):
   im,hits,_=f.render(self.mixed(),scale,'live');cut=round((f.PY+f.LIVE_H)*scale)
   self.assertEqual(im.size,(round(f.W*scale),round(f.H*scale)))
   self.assertEqual(im.crop((0,cut,im.width,im.height)).getchannel('A').getextrema(),(0,0))
   if f.PY:self.assertEqual(im.crop((0,0,im.width,round(f.PY*scale))).getchannel('A').getextrema(),(0,0))
   self.assertTrue(all(h[1]+h[3]<=cut for h in hits))
 def test_live_mode_has_no_scroll_and_switches_with_the_list(self):
  p=SimpleNamespace(_swing={'geo':{'flat':True,'u':1.5},'ui':self.ui(23)},_flat_mode='live')
  f.scroll(p,-120*50);self.assertFalse(getattr(p,'_flat_scroll',0));self.assertFalse(f.bar_input(p,SimpleNamespace(x=630,y=100),'press'))
  self.assertTrue(f.action(p,'flat_mode','tasks'));self.assertEqual(p._flat_mode,'tasks')
  self.assertTrue(f.action(p,'flat_mode','live'));self.assertEqual(p._flat_mode,'live')
 def test_default_is_live_and_expanded_list_offers_collapse(self):
  self.assertEqual(f._mode(SimpleNamespace()),'live')
  _,hits,_=f.render(self.ui(),1,'tasks');self.assertIn(('flat_mode','live'),[(h[4],h[5]) for h in hits])
 def test_live_mode_is_cross_agent_while_expanded_list_follows_selected_agent(self):
  ui=self.mixed();ui['sessions'][1]['agent']='claude-code';ui['flat_agent']='ZCode'
  _,live,_=f.render(ui,1,'live');_,tasks,_=f.render(ui,1,'tasks')
  self.assertEqual([h[-1] for h in live if h[4]=='flat_task'],['1','0'])                # Claude's waiting session, then ZCode's running one
  self.assertNotIn('1',[h[-1] for h in tasks if h[4]=='flat_task'])
 def test_task_click_from_live_view_opens_that_agents_steps(self):
  ui=self.mixed();ui['sessions'][1]['agent']='claude-code'
  p=SimpleNamespace(_swing={'ui':ui},_flat_agent='ZCode')
  self.assertTrue(f.action(p,'flat_task','1'));self.assertEqual((p._flat_agent,p._flat_mode,p._book_sel),('Claude','steps',('sid','1')))
 def test_task_click_ignores_malformed_swing_state(self):
  for bad in (Mock(),None,{'ui':Mock()},{'ui':{'sessions':Mock()}}):
   q=SimpleNamespace(_swing=bad);self.assertTrue(f.action(q,'flat_task','1'));self.assertEqual(q._flat_mode,'steps');self.assertFalse(hasattr(q,'_flat_agent'))
 def test_chain_length_matches_workflow_steps(self):
  ui=self.mixed()
  for r in f.rows_for(ui,'live'):
   s=next(x for x in ui['sessions'] if x['id']==r['id']);self.assertEqual(len(r['chain']),len(f.workflow(dict(ui,sel_session=s))['steps']))
 def test_status_shapes_differ_not_only_in_colour(self):
  from PIL import ImageChops
  masks={}
  for st in ('running','waiting','error','done'):
   t=Image.new('RGBA',(40,40));f.glyph(t,20,20,3.5,'#ffffff',f.SHAPES[st],1.5);masks[st]=t.getchannel('A').point(lambda v:255 if v>127 else 0)
  names=list(masks)
  for i,a in enumerate(names):
   for c in names[i+1:]:
    inter=ImageChops.darker(masks[a],masks[c]).histogram()[255];union=ImageChops.lighter(masks[a],masks[c]).histogram()[255]
    self.assertLess(inter/union,.8,(a,c))
 def test_panel_alpha_is_per_pixel_and_rim_stays_opaque(self):
  for mode in ('live','tasks'):
   for u in (1,1.5):
    for alpha in (None,248):
     ui=self.mixed() if mode=='live' else self.ui()
     if alpha:ui['panel_alpha']=alpha
     im,_,_=f.render(ui,u,mode)
     self.assertEqual(im.getpixel((round(30*u),round(100*u)))[3],alpha or f.PANEL_REST,(mode,u,alpha))
     self.assertEqual(im.getpixel((round(220*u),round(f.PY*u)))[3],255)
 def test_alpha_tier_follows_mode_attention_and_hover(self):
  o=SimpleNamespace();calm=self.ui(2)
  self.assertEqual(f.panel_alpha(o,calm,'live'),f.PANEL_REST);self.assertEqual(f.panel_alpha(o,calm,'tasks'),f.PANEL_ACTIVE)
  self.assertEqual(f.panel_alpha(o,self.mixed(),'live'),f.PANEL_ACTIVE)
  self.assertEqual(f.panel_alpha(SimpleNamespace(_flat_hover=True),calm,'live'),f.PANEL_ACTIVE)
 def test_rest_alpha_keeps_text_readable_over_white(self):
  def lum(c):
   r,g,b=[int(c[i:i+2],16)/255 for i in (1,3,5)];r,g,b=[x/12.92 if x<=.03928 else ((x+.055)/1.055)**2.4 for x in (r,g,b)];return .2126*r+.7152*g+.0722*b
  a=f.PANEL_REST/255;bg=lum('#%02x%02x%02x'%tuple(round(a*int(f.BG[i:i+2],16)+(1-a)*255) for i in (1,3,5)))
  ratio=lambda c:(max(bg,lum(c))+.05)/(min(bg,lum(c))+.05)
  self.assertGreaterEqual(ratio(f.INK),7);self.assertGreaterEqual(ratio(f.DIM),4.5);self.assertGreaterEqual(ratio(f.COLORS['error']),4.5)
 def test_layout_constants_are_consistent(self):
  self.assertEqual(f.H,f.PH+f.PY);self.assertEqual(f.LIST[0]+f.LIST[2],424)
  self.assertGreaterEqual(f.LIST[1],f.PY);self.assertLessEqual(f.LIST[1]+f.LIST[3],f.PY+158)
  l,t,r,b=f.pet_content()                                              # what she actually shows, not the invisible studio box
  self.assertGreaterEqual(t,0)                                         # the hat tip is never cut off by the window top
  if f.PY:self.assertLess(t,f.PY)                                      # with headroom, the hat rises above the panel
  self.assertLessEqual(b,f.PY+f.LIVE_H-4)                              # soles stay inside the compact panel (the expanded view has the whole column)
  self.assertGreaterEqual(l,0);self.assertLessEqual(r,f.LIST[0]-12)    # inside the pet column, clear of the step column
  self.assertGreaterEqual(f.LPITCH,32)                                  # a live row is two text lines (name + arrow line): rows must not overlap
  self.assertLessEqual(f.LROW0+f.LIVE_ROWS*f.LPITCH,120)                # and all of them fit above the divider
 def test_hits_stay_inside_the_window(self):
  for mode in ('live','tasks','steps'):
   for scale in (1,1.5):
    im,hits,_=f.render(self.mixed(),scale,mode)
    for x,y,w,h,kind,_ in hits:
     self.assertTrue(x>=0 and y>=0 and x+w<=im.width and y+h<=im.height,(mode,scale,kind,x,y,w,h))
     if kind in ('flat_task','detail') and mode!='live':self.assertLessEqual(x+w,round(414*scale))   # rows end before the scrollbar
 def test_long_step_title_is_cut_before_the_right_edge(self):
  u=self.mixed();s=u['sessions'][0];s['actions']=[{'a':'很长很长的步骤标题'*8,'r':'OK','t':u['now']-1}];u['sel_session']=s
  im,_,_=f.render(u,1,'live');band=im.crop((421,f.PY+f.LROW0+16,432,f.PY+f.LROW0+32))
  self.assertFalse(any(r>200 and g>200 and b>200 and a>200 for r,g,b,a in band.getdata()))
 def test_live_rows_feed_the_reaction_rules_without_adapting(self):
  import agent_reactions as ar
  rows=f.rows_for(self.mixed(),'live');rr=ar.Reactor('few',day_of=lambda t:0)
  self.assertEqual(rr.update(1000.0,rows),[])                                   # first sample is only a baseline
  out=rr.update(1000.0+ar.WAIT_DWELL+1,rows)                                    # 'waiting' has now held long enough
  self.assertEqual([(r.kind,r.agent) for r in out],[('waiting','ZCode')])
  self.assertIsNone(rr.pull(1000.0+ar.WAIT_DWELL+2,'approach',rows))             # she has just spoken: the global gap holds
  self.assertEqual(rr.pull(1000.0+ar.WAIT_DWELL+ar.GLOBAL_GAP+2,'approach',rows).kind,'error')   # then the errored one gets its touch
 def test_push_draws_the_stand_only_when_asked_for(self):
  import sys
  from unittest.mock import patch,Mock
  for show in (False,True):
   swing=Image.new('RGBA',(40,40),(200,100,255,255));sa=Mock();sa.scaled.return_value={'swing':(swing,(0,0))};sa.keystone.return_value=(swing,(5,6))
   studio=Mock();studio.return_value.render.return_value=(swing,(0,0))     # a stand render returns (image, offset) like the host's
   pushed=Mock();cache={};ks=SimpleNamespace(get=lambda k:cache.get(k),put=lambda k,v:cache.__setitem__(k,v))
   o=SimpleNamespace(_swing={'geo':{'u':1.5,'k':.2,'O':(0,0),'flat':True},'ui':self.mixed(),'scene_l':0,'scene_t':0,'theta':0},_scene_art=sa,_studio=studio,
                     _ac=Mock(),_art_pose=lambda ph:None,_last_face_key='x',_ks_cache=ks,_art_face_overlay=lambda face,k:None,hwnd=1)
   with patch.object(f,'SHOW_STAND',show),patch.dict(sys.modules,{'pet':SimpleNamespace(push_layered=pushed,SWING_PERSP=.1)}):f.push(o,False)
   self.assertEqual(studio.return_value.render.called,show,show)           # the grey frame is rendered only when asked for
   self.assertEqual(o._ac.call_count,2 if show else 1,show)                # otherwise only the swing art itself is composited
   self.assertEqual(pushed.call_args[0][1].size,(round(f.W*1.5),round(f.H*1.5)))
 def test_expanded_strip_and_quota_stay_in_the_right_column(self):
  for scale in (1,1.5):
   im,hits,_=f.render(self.mixed(),scale,'tasks')
   below=round((f.LIST[1]+f.LIST[3]+1)*scale);band=im.crop((round(12*scale),below,round((f.LIST[0]-6)*scale),round((f.PY+f.PH-8)*scale)))
   self.assertEqual(len(set(band.getdata())),1,scale)                                  # nothing is drawn under her: no divider, lamp, text or bar
   self.assertTrue(all(h[0]>=round((f.LIST[0]-4)*scale) for h in hits if h[1]>=below),scale)   # and no hit rect either, so clicks reach her
 def test_agent_chips_and_quota_fit_the_right_column(self):
  for n in (3,5):
   ui=self.mixed();ui['sessions']=ui['sessions']+[dict(ui['sessions'][0],id=f'x{i}',agent=a) for i,a in enumerate(('mac','zz-unknown')[:n-3])]
   im,hits,_=f.render(ui,1,'tasks')
   for x,y,w,h,kind,_ in hits:
    if kind=='flat_agent':self.assertTrue(f.LIST[0]-4<=x and x+w<=424,(n,x,w))
   q=im.crop((425,f.PY+160,438,f.PY+f.PH-24));self.assertEqual(len(set(q.getdata())),1,n)   # nothing spills into the right margin (stop above the rounded corner)
 def trio(self):
  u=self.ui(1);s=u['sel_session'];now=u['now']
  def mk(i,agent,state,age,*titles):return dict(s,id=i,agent=agent,state=state,updated=now-age,actions=[{'a':t,'r':'OK','t':now-30+k} for k,t in enumerate(titles)])
  u['sessions']=[mk('z1','zcode','waiting',1,'写入补丁'),mk('c0','claude','done',500,'旧任务'),mk('c1','claude','running',1,'读配置','改代码','跑测试'),mk('x1','codex','done',50,'整理文档')]
  u['sel_session']=u['sessions'][0];return u
 def test_live_shows_one_row_per_agent_in_a_fixed_order(self):
  rows=f.agent_rows(self.trio())
  self.assertEqual([(r['agent'],r['id'],r['state']) for r in rows],[('Codex','x1','done'),('Claude','c1','running'),('ZCode','z1','waiting')])   # Claude's live session beats its older finished one
  self.assertEqual([r['title'] for r in rows],['整理文档','跑测试','写入补丁']);self.assertEqual(len(rows[1]['chain']),3)
  _,hits,_=f.render(self.trio(),1,'live');tasks=sorted(h for h in hits if h[4]=='flat_task')
  self.assertEqual([h[-1] for h in tasks],['x1','c1','z1']);self.assertTrue(all(a[1]+a[3]<=c[1] for a,c in zip(tasks,tasks[1:])))   # three rows, top to bottom, no overlap
  self.assertEqual([h[-1] for h in sorted(hits) if h[4]=='flat_agent'],['Codex','Claude','ZCode'])                                   # each name opens that agent's list
 def test_an_agent_without_sessions_has_no_row_and_the_list_is_capped(self):
  u=self.trio();u['sessions']=[x for x in u['sessions'] if x['agent']!='codex']
  self.assertEqual([r['agent'] for r in f.agent_rows(u)],['Claude','ZCode'])
  u=self.trio();u['sessions']=u['sessions']+[dict(u['sessions'][0],id='m1',agent='mac'),dict(u['sessions'][0],id='a1',agent='who-knows')]
  self.assertEqual(len(f.agent_rows(u)),f.LIVE_ROWS)
 def test_a_session_without_steps_does_not_hide_the_agents_other_session(self):
  u=self.trio();u['sessions']=u['sessions']+[dict(u['sessions'][2],id='c2',actions=[],updated=u['now'])]
  self.assertEqual([r['id'] for r in f.agent_rows(u) if r['agent']=='Claude'],['c1'])
 def test_step_flow_points_at_the_next_step_and_shows_an_ellipsis_until_it_exists(self):
  self.assertEqual(f.step_flow({'title':'Read x','state':'running'}),('Read x','…'));self.assertEqual(f.step_flow({'title':'Read x','state':'waiting','next':'Edit y'}),('Read x','Edit y'))
  self.assertEqual(f.step_flow({'title':'Read x','state':'done'}),('Read x',None))      # a finished agent has no next step, so no arrow
 def test_there_is_no_header_title_any_more_and_the_step_count_follows_the_dots(self):
  ui=self.trio();r=f.agent_rows(ui)[0];n=min(len(r['chain']),6);lx=238+f.RX+(18 if len(r['chain'])>6 else 0)+13*(n-1)+14
  im,_,_=f.render(ui,1,'live')
  def bright(x1,x2,y1,y2):return [q for q in im.crop((x1,f.PY+y1,x2,f.PY+y2)).getdata() if q[3]>200 and q[0]>150 and q[1]>150 and q[2]>170]
  self.assertTrue(bright(lx,lx+30,f.LROW0,f.LROW0+14))                                   # '第 N 步' right after the dots
  self.assertFalse(bright(173+f.RX,176+f.RX+8,2,8))                                       # nothing is drawn where the title used to be
 def test_her_bubble_covers_the_top_only_when_she_has_something_to_say(self):
  def white(im):return sum(1 for q in im.crop((178+f.RX,f.PY+2,420,f.PY+27)).getdata() if q[3]>200 and q[0]>225 and q[1]>225 and q[2]>235)
  ui=self.trio();quiet,_,_=f.render(ui,1,'live');ui['bubble']='ZCode 有个确认在等你哦';said,_,_=f.render(ui,1,'live')
  self.assertEqual(white(quiet),0);self.assertGreater(white(said),200)
  ui['bubble']='很长很长的一句话'*30;long,_,_=f.render(ui,1,'live')
  self.assertEqual(len(set(long.crop((425,f.PY+18,438,f.PY+27)).getdata())),1)           # a long line is cut, never spilling into the right margin
 def test_a_finished_row_has_no_arrow_and_a_live_row_has_one(self):
  def after_the_text(row_state):                                                      # only the arrow and the '…' can be here: the 3-char step title ends near x=232
   u=self.trio();u['sessions']=[dict(x,state=row_state) if x['id']=='c1' else x for x in u['sessions']];im,_,_=f.render(u,2,'live')
   y=f.PY+f.LROW0+f.LPITCH+17
   return sum(1 for q in im.crop((236*2,round(y*2),330*2,round((y+14)*2))).getdata() if q[3]>200 and sum(q[:3])>300)
  self.assertGreater(after_the_text('running'),10);self.assertEqual(after_the_text('done'),0)
 def test_a_long_bubble_covers_the_chat_button_completely_and_is_itself_the_chat_button(self):
  def accent(im):return sum(1 for q in im.crop((396,f.PY+f.LROW0-2,424,f.PY+f.LROW0+16)).getdata() if q[3]>200 and q[2]>220 and 150<q[0]<210 and 140<q[1]<190)
  ui=self.trio();plain,_,_=f.render(ui,1,'live');ui['bubble']='短话';short,_,_=f.render(ui,1,'live');ui['bubble']='很长很长的一句话，'*12;long,hits,_=f.render(ui,1,'live')
  self.assertGreater(accent(plain),3);self.assertGreater(accent(short),3);self.assertEqual(accent(long),0)     # a short bubble leaves the button alone; a long one hides it whole, no stray glyph
  self.assertEqual(hits[0][4],'house_chat');self.assertGreaterEqual(hits[0][2],round((424-(178+f.RX))*1))     # and tapping the bubble opens the chat
 def test_task_click_selects_exact_task_and_scroll_resets(self):
  p=ui_owner();p._flat_scroll=100;pet.Pet._ui_hit(p,'flat_task','8');self.assertEqual(p._book_sel,('sid','8'));self.assertEqual(p._flat_mode,'steps');self.assertEqual(p._flat_scroll,0)
 def test_provider_selection_filters_workflow_and_steps(self):
  ui=snapshot();z=ui['sel_session']
  codex=copy.deepcopy(z);codex.update(id='codex-1',agent='wslcodex',title='Codex任务',updated=ui['now']+2)
  codex['actions']=[{'t':ui['now'],'a':'Codex步骤','r':'运行中'}]
  claude=copy.deepcopy(z);claude.update(id='claude-1',agent='mac-claude',title='Claude任务',updated=ui['now']+1)
  claude['actions']=[{'t':ui['now'],'a':'Claude步骤','r':'等待中'}]
  ui['sessions']=[z,codex,claude];ui['flat_agent']='Codex'
  self.assertEqual([r['title'] for r in f.rows_for(ui,'tasks')],['Codex步骤'])
  self.assertEqual([r['title'] for r in f.rows_for(ui,'steps')],['Codex步骤'])
  ui['flat_agent']='Claude'
  self.assertEqual([r['title'] for r in f.rows_for(ui,'tasks')],['Claude步骤'])
 def test_agent_strip_always_offers_codex_and_claude(self):
  ui=snapshot();ui['flat_agent']='Codex'
  self.assertEqual(f.agent_lights(ui),[('Codex','idle'),('Claude','idle'),('ZCode','running')])
  _,hits,_=f.render(ui)
  self.assertEqual([h[-1] for h in hits if h[4]=='flat_agent'],['Codex','Claude','ZCode'])
 def test_agent_switch_resets_list_and_selects_matching_source(self):
  p=ui_owner();ui=snapshot();c=copy.deepcopy(ui['sel_session']);c.update(id='codex-task',agent='mac-codex')
  ui['sessions'].append(c);p._swing={'ui':ui};p._flat_scroll=54;p._flat_mode='steps'
  self.assertTrue(f.action(p,'flat_agent','Codex'))
  self.assertEqual((p._flat_agent,p._flat_mode,p._flat_scroll),('Codex','tasks',0))
  self.assertEqual(p._book_sel,('agent','mac-codex'))
 def test_real_unknown_no_fake_rows(self):
  _,hits,_=f.render({});self.assertFalse(any(h[4] in ('flat_task','detail') for h in hits));self.assertEqual(len(f.quota_rows({})),2)
 def test_scrollbar_drag_reaches_last_row(self):
  p=ui_owner();p._flat_panel_style=True;p._swing={'geo':{'flat':True,'u':1.5},'ui':self.ui(9)};p._flat_mode='tasks'
  self.assertTrue(f.bar_input(p,SimpleNamespace(x=630,y=100),'press'))
  self.assertTrue(f.bar_input(p,SimpleNamespace(x=630,y=225),'move'))
  self.assertEqual(p._flat_scroll,54)
  self.assertTrue(f.bar_input(p,SimpleNamespace(x=630,y=225),'release'))
  self.assertIsNone(p._flat_bar_drag)
 def test_native_composition(self):
  p=owner(1.25);p.sw,p.sh=2880,1800;p._flat_panel_style=True;p._studio_style=True;p._house_on=False;p.settings={};p._flat_mode='tasks'
  g=p._art_geo(1);self.assertEqual(g['size'],(660,round(f.H*1.5)));p._swing={'geo':g,'theta':0,'scene_l':0,'scene_t':0,'ui':self.ui(),'art':True}
  with patch('pet.push_layered'):p._push_swing_art(Image.new('RGBA',(p.W,p.H)))
  self.assertEqual(sum(h[4]=='flat_task' for h in p._swing['ui_hits']),6)
  before=p._flat_cache;p._swing['ui']['now']+=.01
  with patch('pet.push_layered'):p._push_swing_art(Image.new('RGBA',(p.W,p.H)))
  self.assertIs(p._flat_cache,before)

class QuotaAndLightsTests(unittest.TestCase):
 def test_empty_sessions_do_not_consume_action_rows(self):
  ui=snapshot();ui['sessions'].append(dict(ui['sel_session'],id='empty',actions=[]))
  self.assertEqual(len(f.rows_for(ui,'tasks')),1)
 def test_running_lamp_survives_other_session_error(self):
  ui=snapshot();ui['sessions'].append(dict(ui['sel_session'],id='error',state='error'))
  self.assertEqual(f.agent_lights(ui),[('Codex','idle'),('Claude','idle'),('ZCode','running')])
 def test_stale_agent_never_shows_running(self):
  ui=snapshot();self.assertEqual(f.agent_lights(ui),[('Codex','idle'),('Claude','idle'),('ZCode','running')]);ui['now']+=9000
  self.assertEqual(f.agent_lights(ui),[('Codex','idle'),('Claude','idle'),('ZCode','idle')])
 def test_current_actions_not_project_names(self):
  ui=snapshot();rows=f.rows_for(ui,'tasks');self.assertEqual(rows[0]['title'],'生成预览');self.assertNotIn('completed',rows[0])
 def test_recent_step_first_with_absolute_detail_indexes(self):
  rows=f.rows_for(snapshot(),'steps');self.assertEqual(rows[0]['title'],'生成预览');self.assertEqual(rows[0]['index'],2)
 def test_native_quota_used_stale_reset_and_extra_account(self):
  now=1791196800
  raw={'schemaVersion':1,'providers':[{'name':'Codex WSL','updated':now,'staleAfter':300,'windows':[{'short':'月','used':96,'resetUnix':now+60}]}]}
  rows=f.widget_rows(raw,now);self.assertEqual(rows[0]['cycles'][0]['used'],96);self.assertFalse(rows[0]['stale'])
  self.assertTrue(f.widget_rows(raw,now+61)[0]['cycles'][0]['stale']);self.assertTrue(f.widget_rows(raw,now+301)[0]['stale'])
  raw['providers'][0]['windows'][0]['used']=float('nan');self.assertIsNone(f.widget_rows(raw,now)[0]['cycles'][0]['used'])
 def test_mock_never_reads_real_quota(self):
  with patch('pathlib.Path.read_text',side_effect=AssertionError('read user data')):
   ui=snapshot();self.assertIs(f.live_ui(SimpleNamespace(),ui),ui)
 def test_failure_retains_last_sample_as_stale(self):
  import time
  p=SimpleNamespace(_flat_quota_raw={'schemaVersion':1,'providers':[{'name':'Codex','updated':time.time(),'windows':[{'short':'5h','used':50}]}]})
  with patch('pathlib.Path.stat',side_effect=OSError('unavailable')):ui=f.live_ui(p,{})
  self.assertEqual(ui['quota_widget'][0]['cycles'][0]['used'],50);self.assertTrue(ui['quota_widget'][0]['cycles'][0]['stale'])

if __name__=='__main__':unittest.main()

