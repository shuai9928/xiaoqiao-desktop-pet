"""秋千原画场景(assets/scene/ + scene_art.py)与新立绘几何;无窗口、不碰存档。"""
import json
import os
import unittest

from PIL import Image, ImageChops

import pet
import scene_art

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENE = os.path.join(HERE, "assets", "scene")
HAVE_SCENE = os.path.exists(os.path.join(SCENE, "meta.json"))


def _premul(im):
    px = im.convert("RGBa")
    return px


@unittest.skipUnless(HAVE_SCENE, "没有拆好的场景原画")
class SceneArtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sa = scene_art.SceneArt.load(SCENE)
        cls.k = 0.37

    def test_loads_all_layers_and_meta(self):
        self.assertIsNotNone(self.sa)
        for n in scene_art.LAYERS:
            self.assertIn(n, self.sa.src)
            self.assertGreater(self.sa.src[n].getbbox()[2], 0)
        g = self.sa.girl_bbox
        self.assertLess(g[0], g[2])
        self.assertLess(g[1], g[3])

    def test_no_layer_has_near_invisible_noise(self):
        # alpha 1~7 的噪点会让分层窗口在"透明"处截住鼠标
        for n, im in self.sa.src.items():
            hist = im.getchannel("A").histogram()
            self.assertEqual(sum(hist[1:8]), 0, n)

    def test_keystone_is_identity_at_rest(self):
        img, off = self.sa.scaled(self.k)["swing"]
        out, oo = self.sa.keystone(img, off, self.k, 0.0, 0.12)
        m = int(round(off[0] - oo[0]))
        crop = out.crop((m, 0, m + img.width, img.height))
        diff = ImageChops.difference(_premul(crop), _premul(img))
        self.assertLessEqual(max(hi for lo, hi in diff.getextrema()), 3)

    def test_rope_tops_stay_on_the_bar_and_seat_moves(self):
        g = self.sa.swing_geometry(self.k)
        for th in (-0.4, -0.1, 0.2, 0.4):
            for x, y in ((g["x0"], g["y0"]), (g["x1"], g["y1"])):
                fx, fy = self.sa.fwd(g, x, y, th, 0.12)
                self.assertAlmostEqual(fx, x, places=6)
                self.assertAlmostEqual(fy, y, places=6)
        cx, seat = g["cx"], g["seat"]
        for th in (-0.3, 0.3):
            self.assertLess(self.sa.fwd(g, cx, seat, th, 0.12)[1], seat)   # 荡起来座椅抬高
        # 靠近观众(θ>0)座椅变宽,远离(θ<0)变窄
        edge = cx + 200
        self.assertGreater(self.sa.fwd(g, edge, seat, 0.3, 0.12)[0], edge)
        self.assertLess(self.sa.fwd(g, edge, seat, -0.3, 0.12)[0], edge)

    def test_inverse_round_trip(self):
        g = self.sa.swing_geometry(self.k)
        for th in (-0.4, 0.15, 0.4):
            for x, y in ((150, 200), (300, 330), (420, 460)):
                fx, fy = self.sa.fwd(g, x, y, th, 0.12)
                ix, iy = self.sa.inv(g, fx, fy, th, 0.12)
                self.assertAlmostEqual(ix, x, delta=0.05)
                self.assertAlmostEqual(iy, y, delta=0.05)

    def test_scaled_layers_are_cached_per_k(self):
        a = self.sa.scaled(self.k)
        self.assertIs(a, self.sa.scaled(self.k + 0.0004))     # 同一档
        self.assertIsNot(a, self.sa.scaled(self.k + 0.05))

    def test_keystone_cache_is_bounded(self):
        c = scene_art.KeystoneCache(cap=3)
        for i in range(6):
            c.put(i, i)
        self.assertIsNone(c.get(0))
        self.assertEqual(c.get(5), 5)


@unittest.skipUnless(HAVE_SCENE, "没有拆好的场景原画")
class SwingPoseTests(unittest.TestCase):
    """秋千上的 2.5D(转头/帽子摆/发梢/呼吸):接触结构钉死、脸刚性、帽尖能动。"""

    @classmethod
    def setUpClass(cls):
        cls.sa = scene_art.SceneArt.load(SCENE)
        with open(os.path.join(HERE, "assets", "config.json"), encoding="utf-8") as f:
            rig = (json.load(f).get("rig") or {}).get("regions")
        if not rig:
            raise unittest.SkipTest("配置里没有 rig")
        cls.sa.set_rig(rig)
        cls.k = 0.32
        cls.big = {"look": (1, -1), "hat": (0.06, 6), "hair": 8, "breath": 1}

    def test_contact_points_never_move(self):
        pins = ((330, 152), (1020, 188), (380, 630), (390, 760), (987, 505),
                (959, 748), (705, 858), (658, 905), (810, 1140))
        for pose in (self.big, {"look": (-1, 1), "hat": (-0.06, -6), "hair": -8, "breath": -1}):
            for x, y in pins:
                self.assertEqual(self.sa.pose_displacement(x, y, pose), (0.0, 0.0), (x, y))

    def test_face_moves_as_one_piece(self):
        pts = ((610, 520), (737, 554), (658, 582))
        shifts = [self.sa.pose_displacement(x, y, self.big) for x, y in pts]
        for d in shifts[1:]:
            self.assertAlmostEqual(d[0], shifts[0][0], delta=0.6)
            self.assertAlmostEqual(d[1], shifts[0][1], delta=0.6)
        self.assertGreater(abs(shifts[0][0]), 5)            # 转头看得出来

    def test_hat_moves_more_than_face_and_tip_follows_the_hat(self):
        face = self.sa.pose_displacement(658, 560, {"look": (1, 0)})[0]
        brim = self.sa.pose_displacement(900, 330, {"look": (1, 0)})[0]
        self.assertGreater(brim, face)                      # 帽檐更靠前,视差更大
        tip = self.sa.pose_displacement(880, 120, {"hat": (0.05, 0)})
        self.assertGreater(abs(tip[0]) + abs(tip[1]), 5)

    def test_neutral_pose_at_rest_is_identity(self):
        img, off = self.sa.scaled(self.k)["swing"]
        out, oo = self.sa.pose_keystone(img, off, self.k, 0.0, 0.12,
                                        {"look": (0, 0), "hat": (0, 0), "hair": 0, "breath": 0})
        m = int(round(off[0] - oo[0]))
        crop = out.crop((m, 0, m + img.width, img.height))
        diff = ImageChops.difference(crop.convert("RGBa"), img.convert("RGBa"))
        self.assertLessEqual(max(hi for lo, hi in diff.getextrema()), 3)

    def test_lighting_keeps_alpha_and_changes_with_look(self):
        img, off = self.sa.scaled(self.k)["swing"]
        a = self.sa.light_field(img, off, self.k, {"look": (-1, 0)})
        b = self.sa.light_field(img, off, self.k, {"look": (1, 0)})
        self.assertEqual(a.getchannel("A").tobytes(), img.getchannel("A").tobytes())
        self.assertIsNotNone(ImageChops.difference(a.convert("RGB"), b.convert("RGB")).getbbox())


def _shell():
    """不建窗口的壳桌宠:只放原画场景几何要用的字段。"""
    p = object.__new__(pet.Pet)
    p.scale = 1.25
    p.W, p.H = int(pet.BASE_W * p.scale), int(pet.BASE_H * p.scale)
    p.FOOT_Y = p.H - int(30 * p.scale)
    with open(os.path.join(HERE, "assets", "config.json"), encoding="utf-8") as f:
        p.cfg = json.load(f)
    p._sprite_h = int(p.cfg.get("sprite_h", pet.SPRITE_H))
    p._sprite_center_rel = float(p.cfg.get("sprite_center_rel", 0.5))
    p._mouth_rel = tuple(p.cfg.get("mouth", (.487, .55)))
    p.main_src = Image.open(os.path.join(HERE, "assets", "main.png")).convert("RGBA")
    p._scene_art = scene_art.SceneArt.load(SCENE)
    p._ks_cache = scene_art.KeystoneCache()
    p._art_face_cache = {}
    p.glow_cache = {}
    return p


@unittest.skipUnless(HAVE_SCENE, "没有拆好的场景原画")
class ArtSwingPetTests(unittest.TestCase):
    def setUp(self):
        self.p = _shell()

    def test_render_frame_lands_on_the_painted_girl_at_rest(self):
        # 渲染帧里"那只没画出来的立绘"的左上角,映射后必须正好落在原画里她的位置:
        # 气泡、灯板、粒子才贴着她
        for ss in (0.8, 1.0, 1.4):
            geo = self.p._art_geo(ss)
            sw = {"geo": geo, "theta": 0.0}
            ox, oy, s = self.p._art_small_map(sw)
            self.assertAlmostEqual(s, ss, places=6)
            sx, sy = geo["sl"]
            self.assertAlmostEqual(sx * s + ox, geo["gtl"][0] - geo["O"][0], places=4)
            self.assertAlmostEqual(sy * s + oy, geo["gtl"][1] - geo["O"][1], places=4)

    def test_canvas_contains_art_and_render_frame(self):
        geo = self.p._art_geo(1.0)
        cw, ch = geo["size"]
        ox, oy, s = self.p._art_small_map({"geo": geo, "theta": 0.0})
        self.assertGreaterEqual(ox, -0.5)
        self.assertGreaterEqual(oy, -0.5)
        self.assertLessEqual(ox + self.p.W * s, cw + 0.5)
        self.assertLessEqual(oy + self.p.H * s, ch + 0.5)
        cb = self.p._scene_art.content_box()
        self.assertGreaterEqual(cb[0] * geo["k"] - geo["O"][0], 0)
        self.assertLessEqual(cb[3] * geo["k"] - geo["O"][1], ch)

    def test_same_size_on_and_off_the_swing(self):
        # 场景缩放 1.0 时她在秋千上和落地时一样高
        geo = self.p._art_geo(1.0)
        gb = self.p._scene_art.girl_bbox
        self.assertAlmostEqual((gb[3] - gb[1]) * geo["k"], self.p._spr_disp_h(), places=4)

    def test_props_hits_keep_their_kinds(self):
        geo = self.p._art_geo(1.0)
        cw, ch = geo["size"]
        sw = {"geo": geo, "theta": 0.0}
        canvas = Image.new("RGBA", (cw, ch))
        hits = []
        self.p._draw_props_art(canvas, sw, {"crystal_state": "running", "now": 1.0,
                                            "badge": {"codex": "error"}}, hits)
        kinds = [h[4] for h in hits]
        self.assertEqual(sorted(kinds), ["book", "crystal"])
        for x, y, w, h, kind, _ in hits:
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + w, cw)
            self.assertLessEqual(y + h, ch)
        boxes = self.p._art_props_boxes(sw)
        self.assertLess(boxes["book"][0], boxes["crystal"][0])   # 书在左、水晶在右

    def test_scene_content_is_pulled_back_inside_the_screen(self):
        from unittest.mock import patch
        geo = self.p._art_geo(1.0)
        cw, ch = geo["size"]
        sw = {"art": True, "geo": geo, "scene_w": cw, "scene_h": ch,
              "scene_l": 1000 - cw // 3, "scene_t": 100}
        sw["scene_cx"] = sw["scene_l"] + cw // 2
        self.p._swing = sw
        self.p._scene_drag = None
        cb = self.p._scene_art.content_box()
        with patch("pet.monitor_rect_at", return_value=(0, 0, 1000, 800)):
            self.assertTrue(self.p._swing_fit_scene())        # 水晶半截出了右边
            right = sw["scene_l"] + cb[2] * geo["k"] - geo["O"][0]
            self.assertLessEqual(right, 1000 + 1)
            self.assertEqual(sw["rect"][0], sw["scene_l"])
            self.assertFalse(self.p._swing_fit_scene())       # 已经在屏内:不再动
            self.p._scene_drag = {"moved": True}
            sw["scene_l"] += 400
            self.assertFalse(self.p._swing_fit_scene())       # 拖着的时候不抢

    def test_neutral_face_needs_no_overlay(self):
        self.assertIsNone(self.p._art_face_overlay(None, 0.37))
        self.assertIsNone(self.p._art_face_overlay(("", 0, False, 0.0, ""), 0.37))


class NewSpriteGeometryTests(unittest.TestCase):
    def setUp(self):
        self.p = _shell()
        self.rig = self.p.cfg.get("rig") or {}

    def _win(self, rx, ry):
        spr_h = self.p._spr_disp_h()
        spr_w = spr_h * self.p.main_src.width / self.p.main_src.height
        left = self.p.W / 2 - self.p._sprite_center_rel * spr_w
        return left + rx * spr_w, self.p.FOOT_Y - spr_h + ry * spr_h

    @unittest.skipUnless(os.path.exists(os.path.join(HERE, "assets", "config.json")), "")
    def test_click_zones_follow_the_rig(self):
        if not self.rig.get("regions"):
            self.skipTest("旧立绘配置没有 rig")
        ex, ey = self.p.cfg["eyes"]["left"]
        self.assertEqual(self.p._click_zone(*self._win(ex, ey)), "head")
        # 帽檐右侧伸到和脸同高:按多边形判还是帽子
        self.assertEqual(self.p._click_zone(*self._win(0.85, 0.40)), "hat")
        self.assertEqual(self.p._click_zone(*self._win(0.50, 0.75)), "body")

    def test_point_in_poly(self):
        sq = ((0, 0), (1, 0), (1, 1), (0, 1))
        self.assertTrue(pet.point_in_poly(0.5, 0.5, sq))
        self.assertFalse(pet.point_in_poly(1.5, 0.5, sq))

    def test_face_landmarks_sit_on_the_face_region(self):
        if not self.rig.get("regions"):
            self.skipTest("旧立绘配置没有 rig")
        face = self.rig["regions"]["face"]
        for key in ("left", "right"):
            self.assertTrue(pet.point_in_poly(*self.p.cfg["eyes"][key], face), key)
        self.assertTrue(pet.point_in_poly(*self.p._mouth_rel, face))


if __name__ == "__main__":
    unittest.main()
