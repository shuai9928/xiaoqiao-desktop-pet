"""A1/A2 regression: synthetic coordinates, baked real sprites, no AI/user files."""
import math
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from pathlib import Path
from PIL import Image
import hat_fx,pet,fx

def orbit(t):
    points=[('path',160+90*math.cos(i*math.tau/32),180+25*math.sin(i*math.tau/32),.5,False,1) for i in range(32)]
    return points+[(name,160+85*math.cos(t+phase),180+23*math.sin(t+phase),.5,False,1)
        for name,phase in (('moon',0),('crystal',2),('planet',4))]

class HatFXTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template=hat_fx.bake(pet.ASSETS,2.)
        assert cls.template is not None

    def setUp(self):
        self.h=hat_fx.HatFX(self.template.sprites,2.)

    def advance(self,t,active=True,fast=True,moving=True):
        self.h.update(t,orbit(t),180,100,fast,moving)
        self.h.set_thinking(t,active,180,100)

    def test_no_smoke_without_thinking(self):
        for i in range(100):self.advance(i*.05,False)
        self.assertEqual(self.h.stats()['smoke'],0)

    def test_hard_cap_and_stable_storage(self):
        ids=[id(s) for tr in self.h.trails for s in tr]+[id(s) for s in self.h.smoke]
        for i in range(2000):
            self.advance(i*.02)
            self.assertLessEqual(self.h.stats()['total'],48)
        self.assertEqual(ids,[id(s) for tr in self.h.trails for s in tr]+[id(s) for s in self.h.smoke])
        self.assertEqual(sum(map(len,self.h.trails))+len(self.h.smoke)+3,45)

    def test_end_stops_emission_then_fades(self):
        for i in range(21):self.advance(i*.05)
        births=[s[0] for s in self.h.smoke];self.advance(1.05,False)
        self.assertEqual(births,[s[0] for s in self.h.smoke])
        self.assertGreater(self.h.stats()['smoke'],0)
        self.advance(2.4,False);self.assertEqual(self.h.stats()['smoke'],0)

    def test_stationary_orbit_does_not_emit(self):
        for i in range(50):self.advance(i*.05,False,moving=False)
        self.assertEqual(self.h.stats()['trail'],0)

    def test_old_orbit_trail_expires_when_motion_stops(self):
        self.advance(0);self.advance(.1,moving=False);self.advance(1.,moving=False)
        self.assertEqual(self.h.stats()['trail'],0)

    def test_slow_quality_reduces_both_emitters(self):
        counts=[]
        for fast in (True,False):
            self.h.clear();self.h.last_update=None;born=0;previous=-1
            for i in range(100):
                self.advance(i*.01,True,fast)
                if self.h.smoke_head!=previous:born+=1;previous=self.h.smoke_head
            counts.append((self.h.stats()['trail'],born))
        self.assertLess(counts[1][0],counts[0][0]);self.assertLess(counts[1][1],counts[0][1])
        self.assertEqual(self.h.stats()['quality'],'reduced')

    def test_suspend_resume_does_not_backfill(self):
        for i in range(20):self.advance(i*.05)
        self.advance(100)
        self.assertEqual(self.h.stats()['trail'],3);self.assertEqual(self.h.stats()['smoke'],1)

    def test_backward_clock_clears_stale_history(self):
        self.advance(100);self.advance(90)
        self.assertEqual(self.h.stats()['trail'],3);self.assertEqual(self.h.stats()['smoke'],1)

    def test_scaled_sprite_keeps_vapor_aspect_and_real_alpha(self):
        dust=self.h.sprites[0][-1];smoke=self.h.sprites[4][-1]
        self.assertLess(smoke.width,smoke.height/2)
        self.assertGreater(dust.getchannel('A').getextrema()[1],80)

    def test_thinking_smoke_whole_sprite_is_above_tip(self):
        self.h.update(0,(),180,100);self.h.set_thinking(0,True,180,100)
        self.h.update(.2,(),180,100,moving=False)
        im=Image.new('RGBA',(320,240));self.h.draw(im)
        self.assertIsNotNone(im.getbbox());self.assertLess(im.getbbox()[3],100)

    def test_runtime_never_filters_resizes_or_bakes(self):
        for i in range(20):self.advance(i*.05)
        im=Image.new('RGBA',(320,240))
        with patch.object(Image.Image,'filter',side_effect=AssertionError('runtime filter')),\
             patch.object(Image.Image,'resize',side_effect=AssertionError('runtime resize')),\
             patch.object(hat_fx,'bake',side_effect=AssertionError('runtime bake')):
            self.advance(1.);self.h.draw(im)
        self.assertIsNotNone(im.getbbox())

    def test_trails_remain_outside_original_ring(self):
        self.advance(0,False)
        for index,phase in enumerate((0,2,4)):
            x,y=160+85*math.cos(phase),180+23*math.sin(phase)
            s=self.h.trails[index][0]
            self.assertGreater(math.hypot(s[0]-160,s[1]-180),math.hypot(x-160,y-180))

    def test_missing_assets_fallback(self):
        self.assertIsNone(hat_fx.bake(None,2))
        self.assertIsNone(hat_fx.bake(Path(__file__).parent/'missing-fixture',2))

    def test_bake_only_from_fx_build(self):
        with patch.object(hat_fx,'bake',return_value=self.h) as bake:
            layer=fx.FX(.6,2,defer=True,assets_dir='fixture')
        bake.assert_called_once_with('fixture',1.2);self.assertIs(layer.hat,self.h)

    def test_pixel_gateway_does_not_award_currency_or_call_backend(self):
        p=pet.Pet.__new__(pet.Pet);p.fx=SimpleNamespace(hat=self.h)
        p.star=76;p.W=320;p.H=240;p.parts=[];p._fast_ok=False;p._orbit_speed=1
        p.sfx=Mock();p.brain=Mock()
        self.assertEqual(p.gain_star(0,180,100,hat_fx=True,orbit_items=orbit(0),now=0,thinking=True),0)
        self.assertEqual(p.star,76);self.assertEqual(p.parts,[])
        self.assertEqual(self.h.smoke[0][1:3],[180,100])
        self.assertFalse(self.h.fast);p.sfx.play.assert_not_called();self.assertFalse(p.brain.mock_calls)

    def test_regular_rewards_still_use_existing_gateway(self):
        p=pet.Pet.__new__(pet.Pet);p.star=98;p.parts=[];p.W=320;p.H=240;p.scale=1
        with patch.object(pet.time,'time',return_value=10):
            self.assertEqual(p.gain_star(5,180,100),2)
        self.assertEqual(p.star,100);self.assertEqual(p.parts[0]['kind'],'gain')

    def test_actual_thinking_only_outside_marked_debug_demo(self):
        p=pet.Pet.__new__(pet.Pet);p.ai_thinking=False;p._hat_fx_demo_until=100;p._hat_fx_demo_thinking=True
        with patch.object(pet,'DEBUG_STATE',False):self.assertFalse(p._hat_fx_thinking(1))
        p.ai_thinking=True
        with patch.object(pet,'DEBUG_STATE',False):self.assertTrue(p._hat_fx_thinking(1))
        p.ai_thinking=False
        with patch.object(pet,'DEBUG_STATE',True):
            self.assertTrue(p._hat_fx_thinking(1));self.assertFalse(p._hat_fx_thinking(101))

    def test_reduced_animation_switch_and_missing_sprites_disable(self):
        p=pet.Pet.__new__(pet.Pet);p.fx=SimpleNamespace(hat=self.h)
        self.assertTrue(p._hat_fx_enabled_now());p.ui_reduced_anim=True
        self.assertFalse(p._hat_fx_enabled_now());p.ui_reduced_anim=False;p.fx.hat=None
        self.assertFalse(p._hat_fx_enabled_now())

    def test_apex_detected_from_source_alpha(self):
        im=Image.new('RGBA',(100,100));im.putpixel((64,3),(255,255,255,200))
        self.assertEqual(hat_fx.tip_anchor(im),(.64,.03))

    def test_transparent_margin_does_not_break_bottom_row_scroll_or_thumb(self):
        import flat_workspace as f
        from test_flat_workspace import FlatTests
        from test_ai_work_ui import owner
        p=owner();p.state='swing';p._flat_mode='tasks';p._art_regeo=Mock()
        p._swing={'geo':{'flat':True,'u':1.5,'hat_fx_pad':30},'ui':FlatTests().ui(12)}
        pet.Pet.on_wheel_scene(p,SimpleNamespace(x=300,y=(f.LIST[1]+f.LIST[3]-3)*1.5+30,delta=-120))
        self.assertEqual(p._flat_scroll,f.ROW);p._art_regeo.assert_not_called()
        p._flat_scroll=0
        self.assertTrue(f.bar_input(p,SimpleNamespace(x=419*1.5,y=f.LIST[1]*1.5+34),'press'))
        self.assertEqual(p._flat_scroll,0)
        f.bar_input(p,SimpleNamespace(x=419*1.5,y=(f.LIST[1]+f.LIST[3])*1.5+30),'move')
        self.assertEqual(p._flat_scroll,12*f.ROW-f.LIST[3])

    def test_demo_restores_scale_and_state_without_changing_real_thinking(self):
        p=pet.Pet.__new__(pet.Pet);p.fx=SimpleNamespace(hat=self.h)
        p._swing={'scene_scale':1.};p.root=Mock();p._art_regeo=Mock();p.ai_thinking=False
        p._configure_hat_fx_demo({'thinking':True,'enabled':False,'scale':.76},3)
        self.assertFalse(p.ai_thinking);self.assertFalse(p._hat_fx_enabled)
        callback=p.root.after.call_args.args[1];callback()
        self.assertFalse(p.ai_thinking);self.assertTrue(p._hat_fx_enabled)
        p._art_regeo.assert_called_with(p._swing,1.);self.assertEqual(p._hat_fx_demo_until,0)

if __name__=='__main__':unittest.main()
