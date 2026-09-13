"""立体网格、五官共用变形、缓存和动作边界;无个人数据/AI。"""
import math
import unittest
from unittest.mock import Mock
from PIL import Image, ImageChops, ImageDraw
from depth_model import DepthWarp, DepthMotion
from pet import Pet


class MotionTests(unittest.TestCase):
    def test_elapsed_time_is_independent_of_frame_rate(self):
        samples=[]
        for fps in (10,30,60):
            m=DepthMotion()
            m.sample(100,1,-1)
            for i in range(1,fps+1):
                out=m.sample(100+i/fps,1,-1)
            samples.append(out)
        for a,b in zip(samples[0],samples[2]):
            self.assertAlmostEqual(a,b,places=10)

    def test_regions_follow_at_different_rates_without_overshoot(self):
        m=DepthMotion()
        m.sample(0,1,1)
        p=m.sample(.12,1,1)
        self.assertGreater(p[0],p[2])
        self.assertGreater(p[2],p[4])
        for i in range(200):
            p=m.sample(.12+i*.04,(-1)**i,(-1)**i)
            self.assertTrue(all(-1<=v<=1 for v in p))
            self.assertLessEqual(abs(p[4]-p[0])*.015,.015)
        self.assertTrue(all(abs(v)<=1 for v in m.sample(100,9,-9)))

    def test_idle_sleep_drag_and_recovery(self):
        m=DepthMotion()
        m.sample(0,1,1)
        m.sample(5,1,1)
        self.assertAlmostEqual(m.sample(6,1,1,dragging=True)[0],.35)
        for state in DepthMotion.BLOCKED:
            self.assertEqual(m.sample(7,1,1,state),(0.,)*6)
        self.assertEqual(m.sample(8,1,1),(0.,)*6)
        self.assertAlmostEqual(m.sample(8.125,1,1)[0],.5)
        self.assertAlmostEqual(m.sample(8.25,1,1)[0],1)
        self.assertTrue(all(abs(v)<1e-7 for v in m.sample(14,1,1,'sleep')))

    def test_stationary_cursor_converges_without_jitter(self):
        m=DepthMotion()
        m.sample(0,.4,-.2)
        m.sample(6,.4,-.2)
        a=m.sample(7,.4,-.2)
        b=m.sample(8,.4,-.2)
        self.assertEqual(tuple(round(v*20) for v in a),tuple(round(v*20) for v in b))


class WarpTests(unittest.TestCase):
    def make_warp(self,size=(197,203)):
        img=Image.new('RGBA',size)
        d=ImageDraw.Draw(img)
        d.ellipse((size[0]*.3,size[1]*.3,size[0]*.7,size[1]*.8),fill=(170,130,220,255))
        return DepthWarp(img)

    def test_neutral_mesh_preserves_image_and_transparency(self):
        w=self.make_warp()
        neutral=w.warp(0,0,0,0,1,9,lighting=False)
        self.assertIsNone(ImageChops.difference(neutral,w.img).getbbox())
        self.assertEqual(neutral.getpixel((0,0)),(0,0,0,0))

    def test_ornaments_are_protected_from_turning(self):
        w=self.make_warp()
        for x,y in ((.86,.15),(.075,.47),(.04,.04),(.97,.96),(.74,.315)):
            weights=w.region_weights(x,y)
            self.assertLess(sum(weights),.015)
            dx,dy=w.displacement(x*w.w,y*w.h,weights,(1,1)*3,0,1,0)
            self.assertLess(abs(dx)+abs(dy),.1)

    def test_lighting_is_bounded_and_keeps_alpha(self):
        w=self.make_warp()
        for yaw in (-1,0,1):
            for pitch in (-1,1):
                for x,y in ((.42,.51),(.51,.51),(.48,.56)):
                    self.assertTrue(.96<=w.light_gain(x,y,yaw,pitch)<=1.04)
                for i in range(20):
                    self.assertTrue(.92<=w.light_gain(i/20,.3,yaw,pitch)<=1.08)
                self.assertIsNone(ImageChops.difference(w.img.getchannel('A'),w.lit_source((yaw,pitch)*3).getchannel('A')).getbbox())

    def test_mesh_no_fold_at_scale_and_action_extremes(self):
        for scale in (.8,1,1.75):
            w=self.make_warp((round(340*scale),round(350*scale)))
            for side in (-1,1):
                for lean,sq,bend in ((0,1,0),(.2,.84,.17),(-.2,1.08,-.15)):
                    for box,q in w.mesh((side,-side,-side,side,side,side),lean,sq,bend):
                        pts=list(zip(q[::2],q[1::2]))
                        for i in range(4):
                            a,b,c=pts[i],pts[(i+1)%4],pts[(i+2)%4]
                            cross=(b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0])
                            self.assertLess(cross,0,(scale,box,q))

    def test_actual_face_pixels_and_background_keep_original_color(self):
        for value in (80,180,240,255):
            w=DepthWarp(Image.new('RGBA',(192,192),(value,value,value,180)))
            for pose in ((0,)*6,(1,1)*3,(-1,-1)*3):
                lit=w.lit_source(pose)
                self.assertEqual(lit.getpixel((2,2)),(value,value,value,180))
                for x,y in ((.42,.52),(.51,.52),(.48,.56)):
                    pixel=lit.getpixel((round(x*192),round(y*192)))
                    self.assertLessEqual(abs(pixel[0]-value),math.ceil(value*.04)+1)
                    self.assertEqual(pixel[3],180)

    def test_cache_is_bounded_and_shadow_fades(self):
        w=self.make_warp()
        for i in range(15):
            w.lit_source((math.sin(i),math.cos(i))*3)
        self.assertLessEqual(len(w._light_cache),2)
        near=w.shadow(0)
        far=w.shadow(100)
        self.assertGreater(far.width,near.width)
        self.assertLess(far.getchannel('A').getextrema()[1],near.getchannel('A').getextrema()[1])
        self.assertIsNone(w.shadow(1000).getbbox())
        for h in range(300): w.shadow(h)
        self.assertLessEqual(len(w._shadow_cache),13)

    def test_transparent_tile_skip_preserves_hairlines_and_alpha(self):
        img=Image.new('RGBA',(197,203))
        d=ImageDraw.Draw(img)
        d.line((3,6,190,195),fill=(220,180,90,7),width=1)
        d.line((170,1,170,200),fill=(120,170,240,255),width=1)
        w=DepthWarp(img)
        for pose in ((0,)*6,(1,-1)*3,(-1,1)*3):
            full=w.warp(0,0,.02,0,.98,9,pose=pose,source=img)
            fast=w.warp(0,0,.02,0,.98,9,pose=pose,source=img,source_alpha_fixed=True)
            self.assertEqual(full.tobytes(),fast.tobytes())

    def test_face_texture_and_body_use_identical_sampling(self):
        w=self.make_warp()
        mark=Image.new('RGBA',w.img.size)
        ImageDraw.Draw(mark).ellipse((78,97,87,106),fill=(255,255,255,255))
        pose=(1,-.5,.6,-.3,.2,-.1)
        expected=mark.transform(mark.size,Image.Transform.MESH,w.mesh(pose,.04,1,.02),Image.Resampling.BILINEAR)
        actual=w.warp(0,0,.04,0,1,9,bend=.02,pose=pose,source=mark)
        self.assertIsNone(ImageChops.difference(expected,actual).getbbox())


class FaceTests(unittest.TestCase):
    def test_local_face_draw_precedes_warp_and_keeps_alpha(self):
        p=Pet.__new__(Pet)
        p.scale=1
        p.spr2=Image.new('RGBA',(340,350),(140,140,140,220))
        p.warper=DepthWarp(p.spr2)
        p._draw_singing_mouth=Mock()
        p._face_texture((0,)*6,('sing',4,False))
        args=p._draw_singing_mouth.call_args.args
        self.assertAlmostEqual(args[1],340*.487)
        self.assertAlmostEqual(args[2],350*.55)
        self.assertEqual(p.warper.img.getpixel((10,10)),(140,140,140,220))
        p.cfg={'eyes':{'left':[.413,.496],'right':[.541,.487]}}
        p._blink_patches=None
        result=p._face_texture((0,)*6,('sleep',0,False))
        self.assertIsNone(ImageChops.difference(result.getchannel('A'),p.spr2.getchannel('A')).getbbox())

    def test_face_cache_phase_and_expiry(self):
        p=Pet.__new__(Pet)
        p.cfg={}
        p.blink_until=0
        p.singing=False
        p._mouth=('laugh',102)
        keys={p._face_texture_key(100,i/60,False) for i in range(300)}
        self.assertLessEqual(len(keys),9)
        self.assertEqual(p._face_texture_key(103,0,False),('',0,False))
        self.assertIsNone(p._mouth)



if __name__=='__main__': unittest.main()
