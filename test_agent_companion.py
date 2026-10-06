import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import agent_companion as c
import flat_workspace as f
from agent_reactions import Reactor


class CompanionIntegrationTests(unittest.TestCase):
    def owner(self):
        return SimpleNamespace(settings={}, state='swing', _swing=None,
                               _nap_on_swing=False, ai_announce=True, ai_lights=True,
                               ai_mute_sources=set(), ai_mute_sess=set(),
                               focus_mode=lambda: False, _fg_title=lambda: '',
                               say=Mock(), play_emotion=Mock(return_value=False),
                               _start_micro_motion=Mock(), hop=Mock(),
                               _swing_impulse=Mock(), stickers_enabled=False)

    def sample(self, now, state='waiting', source='claude', sid='one'):
        return dict(id=sid, agent=source, state=state, updated=now)

    def test_waiting_becomes_a_real_bubble_once(self):
        p=self.owner()
        with patch.object(c, 'live_ui', return_value={}), patch.object(c, 'quota_rows', return_value=[]):
            c.tick(p, 1000, [self.sample(1000)])
            c.tick(p, 1021, [self.sample(1021)])
            c.tick(p, 1040, [self.sample(1040)])
        p.say.assert_called_once()
        self.assertIn('Claude', p.say.call_args.args[0])
        p.hop.assert_called_once_with(.4)

    def test_sleeping_on_swing_and_muted_sources_drop_reminders(self):
        for asleep, muted in ((True,False), (False,True)):
            p=self.owner();p._nap_on_swing=asleep;p.ai_mute_sources={'claude'} if muted else set()
            with patch.object(c,'live_ui',return_value={}), patch.object(c,'quota_rows',return_value=[]):
                c.tick(p,1000,[self.sample(1000)])
                c.tick(p,1040,[self.sample(1040)])
            p.say.assert_not_called()

    def test_permission_hook_is_not_repeated_when_it_arrives_before_scan(self):
        p=self.owner();c.acknowledge_hook(p,1000)
        with patch.object(c,'live_ui',return_value={}), patch.object(c,'quota_rows',return_value=[]):
            c.tick(p,1001,[self.sample(1001,source='zcode')])
            c.tick(p,1025,[self.sample(1025,source='zcode')])
        p.say.assert_not_called()

    def test_report_names_both_agents_without_stale_or_muted_sessions(self):
        p=self.owner();p._ai_work_sessions=[self.sample(1000,'running','codex','a'),
            self.sample(1000,'waiting','claude','b'),dict(self.sample(1000,'error','zcode','c'),stale=True)]
        self.assertTrue(c.report(p,1001))
        line=p.say.call_args.args[0]
        self.assertIn('Codex',line);self.assertIn('Claude',line);self.assertNotIn('ZCode',line)

    def test_recovered_quota_cancels_held_warning(self):
        r=Reactor('normal');sessions=[dict(id='a',agent='Codex',state='running')]
        quota=lambda used:[dict(name='Codex',cycles=[dict(label='5h',used=used)])]
        r.update(1000,sessions,quota(95));self.assertIn(('quota','Codex'),r.notes)
        r.update(1010,sessions,quota(20));self.assertNotIn(('quota','Codex'),r.notes)
        self.assertIsNone(r.pull(1011,'approach'))

    def test_other_high_cycle_keeps_warning_after_one_cycle_resets(self):
        r=Reactor('normal');sessions=[dict(id='a',agent='Claude',state='running')]
        q=lambda short,week:[dict(name='Claude',cycles=[dict(label='5h',used=short),dict(label='周',used=week)])]
        r.update(1000,sessions,q(95,95));r.update(1010,sessions,q(20,95))
        self.assertIn(('quota','Claude'),r.notes)

    def test_turning_off_discards_pending_notes(self):
        r=Reactor('normal');s=[dict(id='a',agent='Claude',state='error')]
        r.update(1000,s);r.update(1011,s);self.assertTrue(r.notes)
        r.level='off';r.update(1012,s);self.assertFalse(r.notes)

    def test_selected_claude_rows_control_scroll_and_thumb(self):
        from test_flat_workspace import FlatTests
        ui=FlatTests().ui(2)
        codex=[dict(s,agent='codex') for s in ui['sessions']]
        claude=[dict(codex[0],id=f'claude-{i}',agent='claude') for i in range(12)]
        ui.update(sessions=codex+claude,sel_session=codex[0],flat_agent='Codex')
        p=SimpleNamespace(_flat_agent='Claude',_flat_mode='tasks',_swing=dict(ui=ui,geo=dict(flat=True,u=1)))
        f.scroll(p,-1200)
        self.assertEqual(p._flat_scroll,12*f.ROW-f.LIST[3])
        self.assertTrue(f.bar_input(p,SimpleNamespace(x=419,y=f.LIST[1]+10),'press'))

    def test_entire_flat_window_moves_onto_the_screen(self):
        import pet
        sw=dict(geo=dict(flat=True),scene_l=-156,scene_t=479,
                scene_w=330,scene_h=206,scene_scale=1)
        p=SimpleNamespace(_scene_drag=None)
        with patch('pet.work_area_at',return_value=(0,0,1920,1080)):
            self.assertTrue(pet.Pet._art_fit_scene(p,sw))
        self.assertEqual(sw['scene_l'],8)
        self.assertEqual(sw['rect'],(8,479,338,685))

    def test_real_artwork_hat_and_feet_fit_without_the_stand(self):
        from export_house_stage import owner
        import pet
        p=owner();p.sw,p.sh=2880,1800;p._flat_panel_style=True
        g=p._art_geo(1);sa=p._scene_art;k=g['k'];ox,oy=g['O']
        layers=sa.scaled(k);image,at=layers.get('swing_studio',layers['swing'])
        for phase in (-.18,0,.18):
            rendered,position=sa.keystone(image,at,k,phase,pet.SWING_PERSP)
            box=rendered.getbbox()
            top=(position[1]+box[1]-oy)/g['u']
            bottom=(position[1]+box[3]-oy)/g['u']
            right=(position[0]+box[2]-ox)/g['u']
            self.assertGreaterEqual(top,2,phase)
            self.assertLessEqual(bottom,f.PY+f.LIVE_H,phase)
            self.assertLess(right,f.LIST[0]-12,phase)


if __name__=='__main__':
    unittest.main()
