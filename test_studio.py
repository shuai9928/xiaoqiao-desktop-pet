"""Studio scene (质感版): clean stand, cleaned swing layer, status capsule.
Offline with the shipped art and synthetic AI snapshots; no Tk, no user files."""
import os
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops

from export_function_ui import demo
from export_house_stage import owner
import scene_art
from status_capsule import capsule_state, render_capsule
from studio_scene import StudioStand

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE = os.path.join(HERE, "assets", "scene")
T0 = 1791100000.0


class StudioLayerTests(unittest.TestCase):
    def test_cleaned_layer_keeps_her_and_drops_only_ornaments(self):
        swing = Image.open(os.path.join(SCENE, "swing.png")).convert("RGBA")
        studio = Image.open(os.path.join(SCENE, "swing_studio.png")).convert("RGBA")
        self.assertEqual(swing.size, studio.size)
        # her head, body, hands and shoes are unchanged (only alpha<8 noise is cleared)
        def visible(im, box):
            c = im.crop(box)
            c.putalpha(c.getchannel("A").point(lambda v: 0 if v < 8 else v))
            return c.convert("RGBa")
        for box in ((480, 360, 900, 700), (380, 560, 460, 660), (620, 1060, 860, 1250)):
            diff = ImageChops.difference(visible(swing, box), visible(studio, box))
            self.assertLessEqual(max(hi for _, hi in diff.getextrema()), 24, box)   # faint fringe only
        # the dangling pendant under the cushion and the crossbar remnants are gone
        for box in ((360, 1020, 440, 1140), (292, 0, 350, 140), (995, 40, 1050, 180)):
            self.assertIsNone(studio.crop(box).getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox(), box)
        self.assertEqual(studio.getchannel("A").histogram()[1:8], [0] * 7)

    def test_scene_art_offers_the_studio_layer_with_the_swing_offsets(self):
        sa = scene_art.SceneArt.load(SCENE)
        self.assertTrue(sa.studio)
        L = sa.scaled(.4)
        self.assertEqual(L["swing_studio"][1], L["swing"][1])
        self.assertEqual(L["swing_studio"][0].size, L["swing"][0].size)


class StandTests(unittest.TestCase):
    def setUp(self):
        sa = scene_art.SceneArt.load(SCENE)
        self.stand = StudioStand(sa.pivot_l, sa.pivot_r)

    def test_render_is_cached_and_never_leaves_invisible_specks(self):
        a = self.stand.render(.4041)
        self.assertIs(self.stand.render(.4043), a)           # same quantized k
        img, at = a
        self.assertEqual(img.getchannel("A").histogram()[1:8], [0] * 7)
        x0, y0, x1, y1 = self.stand.bounds()
        self.assertAlmostEqual(at[0], x0 * .404, delta=1)
        self.assertLess(self.stand.floor, y1)

    def test_bar_is_level_and_the_frame_is_symmetric_enough(self):
        img, _ = self.stand.render(.5)
        a = img.getchannel("A")
        w = a.width
        left = a.crop((0, 0, w // 2, a.height)).getbbox()
        right = a.crop((w // 2, 0, w, a.height)).getbbox()
        self.assertLess(abs(left[1] - right[1]), 3)          # level top bar


class StudioScenePetTests(unittest.TestCase):
    def setUp(self):
        self.p = owner(1.25)
        self.p._house_on = False
        self.p._studio_style = True
        self.p.sw, self.p.sh = 2880, 1800
        self.p.ai_mute_sess = set()

    def push(self, ss=1.0):
        p = self.p
        geo = p._art_geo(ss)
        w, h = geo["size"]
        sw = {"geo": geo, "art": True, "scene_l": 0, "scene_t": 0, "scene_w": w, "scene_h": h,
              "scene_scale": ss, "theta": 0.0, "omega": 0.0, "ui": demo(), "t0": 0}
        p._swing = sw
        with patch("pet.push_layered") as push:
            p._push_swing_art(Image.new("RGBA", (p.W, p.H)))
        return sw, push

    def test_studio_replaces_the_gilded_swing_and_props(self):
        self.assertTrue(self.p.studio_enabled())
        sw, _ = self.push()
        geo = sw["geo"]
        self.assertIn("studio", geo)
        kinds = [h[4] for h in sw["ui_hits"]]
        self.assertEqual(kinds, ["house_trace", "house_quota"])      # capsule, no book/crystal
        g = geo["studio"]
        self.assertLessEqual(g["cap_y"] + g["cap_h"], geo["size"][1])
        self.assertGreater(g["cap_y"], g["floor"])                     # capsule sits below the floor

    def test_old_side_lights_and_head_scroll_stay_off(self):
        frame = Image.new("RGBA", (400, 520))
        self.p._chain_rect_local = (1, 2, 3, 4)
        self.p.ai_lights, self.p.bubble = True, None
        self.p._ai_sessions = [{"id": "s", "agent": "zcode", "state": "running",
                                "updated": T0, "title": "t", "actions": []}]
        self.p._draw_ai_lights(frame, T0, 120, 180, 480, 1)
        self.p._draw_ai_chain(frame, T0, 120, 110, 180)
        self.assertIsNone(frame.getbbox())
        self.assertIsNone(self.p._chain_rect_local)

    def test_scene_fades_in_instead_of_popping_onto_the_desktop(self):
        sw, push = self.push()
        sw["fade_at"] = 10.0
        with patch("pet.time.time", return_value=10.1), patch("pet.push_layered") as push:
            self.p._push_swing_art(Image.new("RGBA", (self.p.W, self.p.H)))
        self.assertLess(push.call_args[0][4], 120)
        with patch("pet.time.time", return_value=11.0), patch("pet.push_layered") as push:
            self.p._push_swing_art(Image.new("RGBA", (self.p.W, self.p.H)))
        self.assertEqual(push.call_args[0][4], 255)

    def test_without_the_studio_layer_the_legacy_swing_is_used(self):
        self.p._scene_art.studio = False
        try:
            self.assertFalse(self.p.studio_enabled())
            self.assertNotIn("studio", self.p._art_geo(1.0))
        finally:
            self.p._scene_art.studio = True


class ReaderPlacementTests(unittest.TestCase):
    def test_reader_keeps_clear_of_the_open_chat(self):
        from ai_work_ui import panel_position
        scene, size, area = (300, 300, 340, 450), (636, 816), (0, 0, 2880, 1704)
        chat = (656, 300, 840, 1044)                       # chat already opened to the right
        x, y = panel_position(scene, size, area, avoid=(chat,))
        overlap_w = max(0, min(x + size[0], chat[0] + chat[2]) - max(x, chat[0]))
        overlap_h = max(0, min(y + size[1], chat[1] + chat[3]) - max(y, chat[1]))
        self.assertEqual(overlap_w * overlap_h, 0)
        self.assertEqual(max(0, min(x + size[0], 640) - max(x, 300)) *
                         max(0, min(y + size[1], 750) - max(y, 300)), 0)


class CapsuleTests(unittest.TestCase):
    def ui(self, state="running", age=5, **kw):
        session = {"id": "s", "agent": "zcode", "state": state, "updated": T0 - age,
                   "title": "t", "actions": [{"a": "读 pet.py", "t": T0 - age}]}
        base = {"now": T0, "sources": [("zcode", "ZCode", "Z")], "sel_key": "zcode",
                "sel_session": session, "sessions": [session],
                "quota": {"fh": 42, "sd": 10, "t": (T0 - 60) * 1000}, "quota_age": 60}
        base.update(kw)
        return base

    def test_glyph_kind_follows_the_session(self):
        for state, kind in (("running", "running"), ("waiting", "waiting"), ("done", "done"),
                            ("error", "error"), ("idle", "idle")):
            self.assertEqual(capsule_state(self.ui(state), T0)[0], kind)
        self.assertEqual(capsule_state(self.ui("running", stale=None) | {"sel_session": None}, T0)[0], "idle")

    def test_two_zones_cover_the_pill_without_overlap(self):
        img, hits, split = render_capsule(self.ui(), 36, 420, T0)
        self.assertEqual(img.mode, "RGBA")
        (x0, y0, w0, h0, k0, _), (x1, y1, w1, h1, k1, _) = hits
        self.assertEqual((k0, k1), ("house_trace", "house_quota"))
        self.assertEqual(x0 + w0, x1)
        self.assertEqual(x1 + w1, img.width)
        self.assertLessEqual(img.width, 420)

    def test_unknown_quota_draws_no_number(self):
        ui = self.ui(quota={"fh": None, "sd": None}, quota_age=None)
        _, hits, _ = render_capsule(ui, 36, 420, T0)
        from status_capsule import layout
        self.assertEqual(layout(ui, 36, 420, T0)[1]["pct"], "")

    def test_spinner_moves_while_running_and_rests_when_done(self):
        a = render_capsule(self.ui("running"), 36, 420, T0)[0]
        b = render_capsule(self.ui("running"), 36, 420, T0 + .3)[0]
        self.assertIsNotNone(ImageChops.difference(a, b).getbbox())
        c = render_capsule(self.ui("done"), 36, 420, T0)[0]
        d = render_capsule(self.ui("done"), 36, 420, T0 + .3)[0]
        self.assertIsNone(ImageChops.difference(c, d).getbbox())


if __name__ == "__main__":
    unittest.main()
