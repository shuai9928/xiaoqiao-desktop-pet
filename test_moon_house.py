"""Moon-house semantics, hit geometry and native composition; no user data."""
import copy
import unittest
from unittest.mock import patch
from PIL import Image

import moon_board
import moon_house


def snapshot():
    now = 1791196800.0
    s = {'id': 'moon-test', 'agent': 'zcode', 'title': '小屋界面优化',
         'state': 'running', 'updated': now,
         'actions': [{'t':now,'a':'生成预览','r':''},
                     {'t':now-20,'a':'调整布局','r':'完成'},
                     {'t':now-40,'a':'整理素材','r':'完成'}]}
    return {'now':now, 'sel_session':s, 'sel_key':'zcode', 'sessions':[s],
            'sources':[('zcode','ZCode','Z')], 'mock':True,
            'quota':{'t':now*1000,'fh':28,'sd':40,'reset_est':now+3600},
            'codex_quota':{'provider':'codex','t':now*1000,
                           'cycles':[{'minutes':300,'used':46,'reset':now+4000},
                                     {'minutes':10080,'used':32,'reset':now+80000}]}}


class WorkflowTests(unittest.TestCase):
    def test_chronological_completion_and_active_step(self):
        f = moon_board.workflow(snapshot())
        self.assertEqual([x['title'] for x in f['steps']], ['整理素材','调整布局','生成预览'])
        self.assertEqual([x['status'] for x in f['steps']], ['done','done','running'])
        self.assertEqual(f['completed'], 2)

    def test_no_result_is_not_inferred_success(self):
        ui = snapshot()
        ui['sel_session']['actions'][1]['r'] = ''
        self.assertEqual(moon_board.workflow(ui)['steps'][1]['status'], 'recorded')

    def test_error_never_becomes_a_green_check(self):
        ui = snapshot()
        ui['sel_session']['actions'][1]['err'] = 1
        self.assertEqual(moon_board.workflow(ui)['steps'][1]['status'], 'error')

    def test_stale_running_is_not_live(self):
        ui = snapshot(); ui['now'] += 9000
        f = moon_board.workflow(ui)
        self.assertTrue(f['stale'])
        self.assertEqual(f['steps'][-1]['status'], 'recorded')

    def test_turns_preserve_absolute_detail_indexes(self):
        ui = snapshot()
        ui['sel_session']['actions'] += [{'turn':1,'t':ui['now']-50},
                                         {'a':'旧轮次','r':'完成','t':ui['now']-60}]
        steps = moon_board.workflow(ui)['steps']
        self.assertEqual([s['index'] for s in steps], [2,3,4])
        self.assertNotIn('旧轮次', [s['title'] for s in steps])

    def test_completion_persists_after_session_finishes(self):
        ui = snapshot();ui['sel_session']['state']='done'
        ui['sel_session']['actions'][0]['r']='预览已保存'
        ui['now'] += 600
        self.assertEqual(moon_board.workflow(ui)['completed'], 3)

    def test_renderer_is_pure_and_hit_regions_dont_overlap(self):
        for size,u in (((390,600),1),((600,780),1.5),((350,480),1),((315,300),1.5),((315,336),1.5),((491,523),1.5)):
            ui = snapshot();before = copy.deepcopy(ui)
            im,hits = moon_board.render(ui,size,u)
            self.assertEqual(ui,before)
            self.assertEqual(im.size,size)
            self.assertEqual(sum(h[4]=='moon_quota' for h in hits),2)
            for i,(x,y,w,h,kind,payload) in enumerate(hits):
                self.assertGreaterEqual(x,0);self.assertGreaterEqual(y,0)
                self.assertLessEqual(x+w,size[0]);self.assertLessEqual(y+h,size[1])
                if kind=='detail': self.assertEqual(len(payload),4)
                for ox,oy,ow,oh,*_ in hits[i+1:]:
                    overlap=max(0,min(x+w,ox+ow)-max(x,ox))*max(0,min(y+h,oy+oh)-max(y,oy))
                    self.assertEqual(overlap,0,(kind,size))

    def test_empty_and_unknown_still_have_both_quota_actions(self):
        _,hits=moon_board.render({'now':snapshot()['now']},(390,600))
        self.assertEqual([h[-1] for h in hits if h[4]=='moon_quota'],['codex','claude'])
        self.assertFalse(any(h[4]=='detail' for h in hits))


class NativeSceneTests(unittest.TestCase):
    def test_open_pixels_and_static_book_across_camera(self):
        import pet
        from export_house_stage import owner
        p=owner(1.25);p.sw,p.sh=2880,1800
        p._moon_house_style=True;p._house_room_meta=None
        geo=p._art_geo(1.0);L=geo['house_layout']
        renderer=moon_house.MoonRenderer(pet.ASSETS+'/house');renderer.min_interval=0
        bx,by,bw,bh=moon_house.board_rect(L,renderer.meta)
        frames=[]
        for view in ((-1,0),(0,0),(1,0)):
            frames.append(renderer.render(L,view)[0])
        for im in frames[1:]:
            self.assertEqual(im.crop((bx,by,bx+bw,by+bh)).tobytes(),frames[0].crop((bx,by,bx+bw,by+bh)).tobytes())
        self.assertGreater(frames[0].getchannel('A').histogram()[0],L.size[0]*L.size[1]*.3)
        p._swing={'geo':geo,'art':True,'scene_l':0,'scene_t':0,
                  'scene_w':L.size[0],'scene_h':L.size[1],'scene_scale':1.0,
                  'theta':0,'omega':0,'ui':snapshot()}
        p._house_layers=lambda sw:renderer.render(L,(0,0))
        with patch('pet.push_layered'):
            p._push_swing_art(Image.new('RGBA',(p.W,p.H)))
        self.assertTrue(any(h[4]=='moon_quota' for h in p._swing['ui_hits']))


if __name__=='__main__':unittest.main()
