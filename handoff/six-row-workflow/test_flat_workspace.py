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
 def test_steps_include_all_acquired_turns(self):
  ui=self.ui();ui['sel_session']['actions']=[{'a':f'Step{i}','r':'OK','t':ui['now']-i} for i in range(40)]
  ids=set()
  for off in range(0,40*18,96):
   _,hits,_=f.render(ui,1,'steps',off);ids.update(h[-1][1] for h in hits if h[4]=='detail')
  self.assertEqual(ids,set(range(40)))
 def test_scroll_clamps_and_never_rebuilds_scene(self):
  p=ui_owner();p.state='swing';p._swing={'geo':{'flat':True,'u':1.5},'ui':self.ui()};p._art_regeo=Mock()
  pet.Pet.on_wheel_scene(p,SimpleNamespace(x=300,y=100,delta=-120*100));self.assertEqual(p._flat_scroll,54);p._art_regeo.assert_not_called()
  pet.Pet.on_wheel_scene(p,SimpleNamespace(x=300,y=100,delta=120*100));self.assertEqual(p._flat_scroll,0)
  pet.Pet.on_wheel_scene(p,SimpleNamespace(x=100,y=50,delta=-120));self.assertEqual(p._flat_scroll,0)
 def test_partial_rows_have_clipped_click_targets(self):
  _,hits,_=f.render(self.ui(),1.5,'tasks',48)
  for x,y,w,h,kind,_ in hits:
   if kind=='flat_task':self.assertGreaterEqual(y,63);self.assertLessEqual(y+h,225)
 def test_task_click_selects_exact_task_and_scroll_resets(self):
  p=ui_owner();p._flat_scroll=100;pet.Pet._ui_hit(p,'flat_task','8');self.assertEqual(p._book_sel,('sid','8'));self.assertEqual(p._flat_mode,'steps');self.assertEqual(p._flat_scroll,0)
 def test_real_unknown_no_fake_rows(self):
  _,hits,_=f.render({});self.assertFalse(any(h[4] in ('flat_task','detail') for h in hits));self.assertEqual(len(f.quota_rows({})),2)
 def test_scrollbar_drag_reaches_last_row(self):
  p=ui_owner();p._flat_panel_style=True;p._swing={'geo':{'flat':True,'u':1.5},'ui':self.ui(9)}
  self.assertTrue(f.bar_input(p,SimpleNamespace(x=630,y=70),'press'))
  self.assertTrue(f.bar_input(p,SimpleNamespace(x=630,y=225),'move'))
  self.assertEqual(p._flat_scroll,54)
  self.assertTrue(f.bar_input(p,SimpleNamespace(x=630,y=225),'release'))
  self.assertIsNone(p._flat_bar_drag)
 def test_native_composition(self):
  p=owner(1.25);p.sw,p.sh=2880,1800;p._flat_panel_style=True;p._studio_style=True;p._house_on=False;p.settings={}
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
  self.assertEqual(f.agent_lights(ui),[('ZCode','running')])
 def test_stale_agent_never_shows_running(self):
  ui=snapshot();self.assertEqual(f.agent_lights(ui),[('ZCode','running')]);ui['now']+=9000
  self.assertEqual(f.agent_lights(ui),[('ZCode','idle')])
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
