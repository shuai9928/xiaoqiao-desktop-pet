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
   self.assertTrue(all(h[3]==round(18*scale) for h in rows));self.assertEqual(im.size,(round(440*scale),round(260*scale)))
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
   if kind=='flat_task':self.assertGreaterEqual(y,63);self.assertLessEqual(y+h,225)
 def mixed(self):
  u=self.ui(6);s=u['sel_session']
  u['sessions']=[dict(s,id=str(i),title=f'Task {i}',state=st) for i,st in enumerate(('running','waiting','error','done','done','idle'))];u['sel_session']=u['sessions'][0];return u
 def test_live_mode_lists_only_live_sessions_capped_at_two(self):
  _,hits,_=f.render(self.mixed(),1,'live')
  self.assertEqual([h[-1] for h in hits if h[4]=='flat_task'],['0','1'])
  self.assertEqual([(h[4],h[-1]) for h in hits if h[4] in ('flat_mode','flat_agent')],[('flat_agent','ZCode')])
 def test_live_mode_hides_finished_sessions_even_when_few_are_live(self):
  u=self.mixed();u['sessions']=[dict(s,state=st) for s,st in zip(u['sessions'],('running','done','done','idle','done','done'))];u['sel_session']=u['sessions'][0]
  _,hits,_=f.render(u,1,'live')
  self.assertEqual([h[-1] for h in hits if h[4]=='flat_task'],['0']);self.assertEqual([(h[4],h[-1]) for h in hits if h[4] in ('flat_mode','flat_agent')],[('flat_agent','ZCode')])
 def test_live_mode_stays_in_compact_height_and_rest_is_transparent(self):
  for scale in (1,1.5):
   im,hits,_=f.render(self.mixed(),scale,'live');cut=round(f.LIVE_H*scale)
   self.assertEqual(im.size,(round(440*scale),round(260*scale)))
   self.assertEqual(im.crop((0,cut,im.width,im.height)).getchannel('A').getextrema(),(0,0))
   self.assertTrue(all(h[1]+h[3]<=cut for h in hits))
 def test_live_mode_has_no_scroll_and_switches_with_the_list(self):
  p=SimpleNamespace(_swing={'geo':{'flat':True,'u':1.5},'ui':self.ui(23)},_flat_mode='live')
  f.scroll(p,-120*50);self.assertFalse(getattr(p,'_flat_scroll',0));self.assertFalse(f.bar_input(p,SimpleNamespace(x=630,y=70),'press'))
  self.assertTrue(f.action(p,'flat_mode','tasks'));self.assertEqual(p._flat_mode,'tasks')
  self.assertTrue(f.action(p,'flat_mode','live'));self.assertEqual(p._flat_mode,'live')
 def test_default_is_live_and_expanded_list_offers_collapse(self):
  self.assertEqual(f._mode(SimpleNamespace()),'live')
  _,hits,_=f.render(self.ui(),1,'tasks');self.assertIn(('flat_mode','live'),[(h[4],h[5]) for h in hits])
 def test_live_mode_is_cross_agent_while_expanded_list_follows_selected_agent(self):
  ui=self.mixed();ui['sessions'][1]['agent']='claude-code';ui['flat_agent']='ZCode'
  _,live,_=f.render(ui,1,'live');_,tasks,_=f.render(ui,1,'tasks')
  self.assertEqual([h[-1] for h in live if h[4]=='flat_task'],['0','1'])
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
 def test_live_title_prioritises_attention(self):
  self.assertEqual(f.live_title([{'state':'running'},{'state':'waiting'}]),'1 个在等你确认')
  self.assertEqual(f.live_title([{'state':'running'},{'state':'running'}]),'我看着呢 · 2 个在跑')
  self.assertEqual((f.live_title([{'state':'done'}]),f.live_title([])),('都忙完啦','暂时没有任务'))
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
     self.assertEqual(im.getpixel((round(220*u),0))[3],255)
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
  self.assertTrue(f.bar_input(p,SimpleNamespace(x=630,y=70),'press'))
  self.assertTrue(f.bar_input(p,SimpleNamespace(x=630,y=225),'move'))
  self.assertEqual(p._flat_scroll,54)
  self.assertTrue(f.bar_input(p,SimpleNamespace(x=630,y=225),'release'))
  self.assertIsNone(p._flat_bar_drag)
 def test_native_composition(self):
  p=owner(1.25);p.sw,p.sh=2880,1800;p._flat_panel_style=True;p._studio_style=True;p._house_on=False;p.settings={};p._flat_mode='tasks'
  g=p._art_geo(1);self.assertEqual(g['size'],(660,390));p._swing={'geo':g,'theta':0,'scene_l':0,'scene_t':0,'ui':self.ui(),'art':True}
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

