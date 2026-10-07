"""立体网格、五官共用变形、缓存和动作边界;无个人数据/AI。"""
import math
import unittest
from unittest.mock import Mock, patch
from PIL import Image, ImageChops, ImageDraw
from depth_model import DepthWarp, DepthMotion
import pet
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

    def test_cropped_layer_matches_full_canvas_warp(self):
        # 裁剪图层(腿/发)走 source_offset:结果要和"贴回整张画布再变形"一致。
        # 两个坑都要钉住:图层正好落在底图挖空处(不能被底图覆盖表滤光),
        # 偏移不在网格线上(Pillow 裁左/上越界框会让整格错位)。
        img=Image.new('RGBA',(197,203))
        ImageDraw.Draw(img).ellipse((40,20,160,110),fill=(170,130,220,255))
        w=DepthWarp(img)
        self.assertNotIn(67,w.gxs)
        # 内容四周留 8px 透明边:贴着画布边的内容在双线性采样下本来就会
        # 差一像素的软硬边,那不是这里要钉的问题
        layer=Image.new('RGBA',(61,57))
        d=ImageDraw.Draw(layer)
        d.rectangle((8,8,52,48),fill=(240,200,180,255))
        d.line((8,8,52,48),fill=(40,20,90,255),width=3)
        off=(67,131)
        full=Image.new('RGBA',img.size)
        full.paste(layer,off)
        box=(off[0],off[1],off[0]+layer.width,off[1]+layer.height)
        for pose,lean,leg_bend in (((0,)*6,0,None),((1,-.5)*3,.04,(150,5.)),((-1,.5)*3,-.03,(150,-5.))):
            got=w.warp(0,0,lean,0,1,9,pose=pose,source=layer,source_alpha_fixed=True,
                       lighting=False,source_offset=off,leg_bend=leg_bend)
            self.assertEqual(got.size,layer.size)
            want=w.warp(0,0,lean,0,1,9,pose=pose,source=full,lighting=False,leg_bend=leg_bend)
            diff=ImageChops.difference(got,want.crop(box))
            self.assertLessEqual(max(hi for lo,hi in diff.getextrema()),2)
            self.assertGreater(got.getchannel('A').histogram()[255],45*41*3//4)

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
        p._mouth_rel=(.487,.55)  # This synthetic old-art fixture uses the old mouth.
        p.spr2=Image.new('RGBA',(340,350),(140,140,140,220))
        p.warper=DepthWarp(p.spr2)
        p._draw_singing_mouth=Mock()
        p._face_texture((0,)*6,('sing',4,False,0.0,''))
        args=p._draw_singing_mouth.call_args.args
        self.assertAlmostEqual(args[1],340*.487)
        self.assertAlmostEqual(args[2],350*.55)
        self.assertEqual(p.warper.img.getpixel((10,10)),(140,140,140,220))
        p.cfg={'eyes':{'left':[.413,.496],'right':[.541,.487]}}
        p._blink_patches=None
        result=p._face_texture((0,)*6,('sleep',0,False,1.0,''))
        self.assertIsNone(ImageChops.difference(result.getchannel('A'),p.spr2.getchannel('A')).getbbox())

    def test_face_cache_phase_and_expiry(self):
        p=Pet.__new__(Pet)
        p.cfg={}
        p.blink_until=0
        p.singing=False
        p._mouth=('laugh',102)
        keys={p._face_texture_key(100,i/60,False) for i in range(300)}
        self.assertLessEqual(len(keys),9)
        self.assertEqual(p._face_texture_key(103,0,False),('',0,False,0.0,''))
        self.assertIsNone(p._mouth)

    def emo_pet(self):
        p=Pet.__new__(Pet)
        p.scale=1
        p._mouth_rel=(.487,.55)  # Explicit old-art mouth for this synthetic image.
        p.spr2=Image.new('RGBA',(340,350),(200,170,160,255))
        p.warper=DepthWarp(p.spr2)
        p.cfg={'eyes':{'left':[.413,.496],'right':[.541,.487]}}
        p._blink_patches=None
        p.blink_until=0
        p.singing=False
        p._mouth=None
        p.emotions={}
        return p

    def play(self,p,category,at=100.0):
        with patch.object(pet.time,'time',return_value=at):
            p.play_emotion(category)

    def test_angry_sad_mouth_blink_and_expiry_never_raise(self):
        # 原来 sk 只在 lid 分支里赋值:情绪中的眨眼帧、情绪到期后 em 还挂着,
        # 读 sk 就 UnboundLocalError,render 每帧抛、画面定格
        for mode in ('angry','sad'):
            p=self.emo_pet()
            self.play(p,mode)
            p.blink_until=100.5
            key=p._face_texture_key(100.1,0,False)
            self.assertEqual(key[2:],(True,1.0,mode))
            p._face_texture((0,)*6,key)
            p.blink_until=0
            for i in range(1,150):          # 30fps 走 5 秒,跨过 _lid_until
                key=p._face_texture_key(100.1+i/30,0,False)
                p._face_texture((0,)*6,key)
            # 到期且眼睑缓回全开:嘴也撤掉,键回到中性脸、走无绘制捷径
            self.assertEqual(key,('',0,False,0.0,''))
            self.assertIs(p._face_texture((0,)*6,key),p.warper.lit_source((0,)*6))

    def test_lid_eases_in_and_out(self):
        # approach 的 rate>=1 直接返回目标,原来传 12.0 等于没有缓动
        p=self.emo_pet()
        self.play(p,'angry')
        keys=[(100+i/30,p._face_texture_key(100+i/30,0,False)) for i in range(120)]
        lids=[k[3] for _,k in keys[:9]]
        self.assertLess(lids[0],.375)
        self.assertEqual(lids,sorted(lids))
        self.assertGreaterEqual(len(set(lids)),3)
        self.assertEqual(lids[-1],.375)    # 约 0.25 秒到位
        outs=[k for t,k in keys if t>=p._lid_until]
        self.assertGreater(outs[0][3],0)
        self.assertEqual(outs[0][4],'angry')   # 缓出期间嘴和斜睑缘随眼睑一起走
        self.assertEqual(outs[-1],('',0,False,0.0,''))
        # 静止时键不变:安静档每帧都能命中变形缓存
        self.assertEqual(len({p._face_texture_key(110+i/20,0,False) for i in range(40)}),1)

    def test_mouth_cover_only_when_redrawn_and_uses_skin(self):
        p=self.emo_pet()
        pose=(0,)*6
        self.play(p,'happy')
        key=p._face_texture_key(100.3,0,False)
        self.assertGreater(key[3],0)
        self.assertEqual(key[4],'')        # 没有替代嘴形的情绪不进键、不盖嘴
        # 即使键里带了这种模式,也不能只盖不画把嘴抹掉
        got=p._face_texture(pose,('',0,False,0.0,'happy'))
        self.assertIsNone(ImageChops.difference(got,p.warper.lit_source(pose)).getbbox())
        got=p._face_texture(pose,('',0,False,0.0,'surprised'))
        w,h=got.size
        # 盖嘴椭圆里、O 嘴外的一点:颜色取眨眼贴片采到的肤色
        self.assertEqual(got.getpixel((round(w*.487-w*.019),round(h*.555)))[:3],p._blink_skin)
        self.assertEqual(p._blink_skin,(200,170,160))



if __name__=='__main__': unittest.main()
