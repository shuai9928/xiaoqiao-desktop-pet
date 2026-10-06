"""House host integration with shell pets; no Tk, user files or model calls.

The fixture deliberately omits _house_on until a test opts in, just like the
existing legacy __new__ fixtures.  SceneArt metadata is represented by geometry
only; apart from the room's geometry asset (assets/house/room-v2.json) no
asset/config/settings file is opened by this suite.
"""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from pet import BASE_W, BASE_H, Pet


def shell():
    p = Pet.__new__(Pet)
    p._core_edition = True
    p.scale = 1.5
    p.W, p.H = int(BASE_W * p.scale), int(BASE_H * p.scale)
    p.FOOT_Y = p.H - int(30 * p.scale)
    p._sprite_h, p._sprite_center_rel = 390, .384
    p.main_src = Image.new("RGBA", (906, 1187))
    p._scene_art = SimpleNamespace(girl_bbox=(292, 67, 1198, 1254),
                                  content_box=lambda: (56, 0, 1240, 1254))
    p.root, p.swing_layer = Mock(), Mock()
    p.settings = {}
    p.save_settings = Mock()
    p._save_swing_scene = Mock()
    p.close_action_card = Mock()
    p.say = Mock()
    p._ks_cache, p._art_face_cache = Mock(), Mock()
    p._swing, p._scene_drag, p.drag = None, None, None
    p._ai_work_panel, p._room_preview = None, None
    p._book_open, p._crystal_open = False, False
    p._book_anim = 1.0
    p._book_tab = "trace"
    p._book_sel = ("sid", "fixed-session")
    p._trace_snap = [{"a": "Already reading this step", "r": "Full result"}]
    p._trace_sid = "fixed-session"
    p._trace_page, p._session_page = 2, 0
    p._trace_expand = set()
    p._chain_rect_local, p._chain_rect = None, None
    p._chain_sid = None
    p._nap_on_swing = False
    p.state = "swing"
    p.x, p.fy = 800.0, 650.0
    p.sw, p.sh = 2880, 1800
    p.last_interact = 0.0
    p.ui_reduced_anim = True
    p.ai_lights, p.bubble = True, None
    p._ai_sessions = [{"id": "fixed-session", "agent": "zcode",
                       "state": "running", "updated": 10000.0,
                       "title": "Synthetic work", "actions": []}]
    return p


def seat(p, scale=1.0):
    geo = p._art_geo(scale)
    w, h = geo["size"]
    sw = {"art": True, "geo": geo, "scene_scale": scale,
          "scene_l": 400, "scene_t": 100, "scene_w": w, "scene_h": h,
          "scene_cx": 400 + w // 2, "rect": (400, 100, 400+w, 100+h),
          "pend": object(), "theta": .137, "omega": -.42, "t0": 10000.0,
          "x0": p.x, "fy0": p.fy, "ui_hits": []}
    p._swing = sw
    return sw


def monitors(area=(0, 0, 2880, 1800)):
    return (patch("pet.work_area_at", return_value=area),
            patch("pet.monitor_rect_at", return_value=area))


class HouseIntegrationTests(unittest.TestCase):
    def test_missing_house_flag_preserves_legacy_fixture_geometry(self):
        p = shell()
        self.assertFalse(p.house_enabled())
        normal = p._art_geo(1.0)
        self.assertEqual(normal["size"], (652, 780))
        p._house_on = False
        self.assertEqual(p._art_geo(1.0), normal)

    def test_house_translation_preserves_live_swing_scale_and_contact_coordinates(self):
        p = shell()
        old = p._art_geo(.76)
        p._house_on = True
        new = p._art_geo(.76)
        for key in ("k", "sl", "gtl", "anchor", "ss"):
            self.assertEqual(new[key], old[key], key)
        self.assertEqual(new["art_size"], old["size"])
        origin = new["house_layout"].left_origin
        self.assertEqual(new["size"], new["house_layout"].size)
        # Both mounts, hand/rope and seat receive precisely the SAME translation.
        for point in ((330, 152), (1020, 188), (380, 630), (987, 505), (658, 905)):
            for axis in (0, 1):
                before = point[axis] * old["k"] - old["O"][axis]
                after = point[axis] * new["k"] - new["O"][axis]
                self.assertAlmostEqual(after - before, origin[axis])

    def test_mode_switch_keeps_pendulum_nap_and_selected_source(self):
        p = shell()
        sw = seat(p)
        p._nap_on_swing = True
        p._chain_rect_local = (10, 10, 120, 40)
        p._chain_rect = (20, 20, 120, 40)
        reader = p._ai_work_panel = Mock(closed=False)
        reader.close.side_effect = lambda **_kw: setattr(reader, "closed", True)
        p._book_open = True
        p._swing_stop = Mock(side_effect=AssertionError("must keep the seated scene"))
        p.start_swing = Mock(side_effect=AssertionError("must keep the same pendulum"))
        pend, selected = sw["pend"], p._book_sel
        ma, mb = monitors()
        with ma, mb:
            p._set_house_mode(True)
            self.assertTrue(p.house_enabled())
            self.assertIsNone(p._chain_rect_local)
            self.assertIsNone(p._chain_rect)
            self.assertFalse(p._book_open)
            reader.close.assert_called()
            p._set_house_mode(False)
        self.assertIs(p._swing, sw)
        self.assertIs(sw["pend"], pend)
        self.assertEqual((sw["theta"], sw["omega"]), (.137, -.42))
        self.assertTrue(p._nap_on_swing)
        self.assertEqual(p.state, "swing")
        self.assertEqual(p._book_sel, selected)
        p._ks_cache.clear.assert_called()
        p._art_face_cache.clear.assert_called()

    def test_fit_search_reduces_oversized_house_before_it_is_positioned(self):
        for area in ((0, 0, 1366, 728), (0, 0, 1280, 680)):
            with self.subTest(area=area):
                p = shell()
                p._house_on = True
                sw = seat(p)
                self.assertGreater(sw["scene_h"], area[3]-area[1])
                ma, mb = monitors(area)
                with ma, mb:
                    limited = p._limit_house_scale(1.0, sw)
                self.assertGreater(limited, 0)
                self.assertLess(limited, 1.0)
                self.assertTrue(p.house_enabled())
                geo = p._art_geo(limited)
                self.assertIn("house_layout", geo)
                width, height = geo["size"]
                self.assertLessEqual(width, area[2]-area[0]-16)
                self.assertLessEqual(height, area[3]-area[1]-16)

    def test_small_screen_falls_back_without_losing_pose_data_and_can_retry(self):
        p = shell()
        sw = seat(p)
        p._nap_on_swing = True
        pend, selected, trace = sw["pend"], p._book_sel, p._trace_snap
        p._swing_stop = Mock(side_effect=AssertionError("must keep the seated scene"))
        p.start_swing = Mock(side_effect=AssertionError("must keep the same pendulum"))
        # the compact room still fits 1024x600; only a really small area falls back
        ma, mb = monitors((0, 0, 900, 490))
        with ma, mb:
            p._set_house_mode(True)
        self.assertTrue(p._house_on)
        self.assertTrue(p._house_suspended)
        self.assertFalse(p.house_enabled())
        self.assertNotIn("house_layout", sw["geo"])
        self.assertLessEqual(sw["scene_w"], 900-16)
        self.assertLessEqual(sw["scene_h"], 490-16)
        self.assertTrue(p._book_open)
        self.assertIs(p._swing, sw)
        self.assertIs(sw["pend"], pend)
        self.assertEqual((sw["theta"], sw["omega"]), (.137, -.42))
        self.assertTrue(p._nap_on_swing)
        self.assertEqual(p._book_sel, selected)
        self.assertIs(p._trace_snap, trace)
        self.assertEqual(p.state, "swing")
        p.say.assert_called_once()
        ma, mb = monitors((0, 0, 1280, 680))
        with ma, mb:
            p._set_house_mode(True)
        self.assertFalse(p._house_suspended)
        self.assertTrue(p.house_enabled())
        self.assertIn("house_layout", sw["geo"])
        self.assertLessEqual(sw["scene_w"], 1280-16)
        self.assertLessEqual(sw["scene_h"], 680-16)
        self.assertIs(sw["pend"], pend)
        self.assertTrue(p._nap_on_swing)

    def test_fit_uses_whole_room_and_negative_monitors(self):
        p = shell()
        p._house_on = True
        area = (-1920, -100, 0, 980)
        sw = seat(p, .76)
        w, h = sw["geo"]["size"]
        sw.update(scene_l=area[2]-30, scene_t=area[3]-20)
        ma, mb = monitors(area)
        with ma, mb:
            self.assertTrue(p._art_fit_scene(sw))
            self.assertGreaterEqual(sw["scene_l"], area[0])
            self.assertGreaterEqual(sw["scene_t"], area[1])
            self.assertLessEqual(sw["scene_l"]+w, area[2])
            self.assertLessEqual(sw["scene_t"]+h, area[3])
            self.assertEqual(sw["rect"], (sw["scene_l"], sw["scene_t"],
                                          sw["scene_l"]+w, sw["scene_t"]+h))
            p._scene_drag = {"mx": 0, "my": 0, "moved": True}
            sw["scene_l"] = 200
            before = (sw["scene_l"], sw["scene_t"])
            self.assertFalse(p._art_fit_scene(sw))
            self.assertEqual((sw["scene_l"], sw["scene_t"]), before)

    def test_existing_house_refits_when_moved_to_a_smaller_work_area(self):
        p = shell()
        p._house_on = True
        sw = seat(p, 1.0)  # This canvas was valid on a larger display.
        pend = sw["pend"]
        p._nap_on_swing = True
        area = (0, 0, 1280, 680)
        self.assertGreater(sw["scene_h"], area[3]-16)
        ma, mb = monitors(area)
        with ma, mb:
            self.assertTrue(p._art_fit_scene(sw))
        self.assertTrue(p.house_enabled())
        self.assertIn("house_layout", sw["geo"])
        self.assertGreaterEqual(sw["scene_l"], 8)
        self.assertGreaterEqual(sw["scene_t"], 8)
        self.assertLessEqual(sw["scene_l"]+sw["scene_w"], area[2]-8)
        self.assertLessEqual(sw["scene_t"]+sw["scene_h"], area[3]-8)
        self.assertIs(sw["pend"], pend)
        self.assertEqual((sw["theta"], sw["omega"]), (.137, -.42))
        self.assertTrue(p._nap_on_swing)

    def _click_shell(self):
        p = shell()
        p._house_on = True
        sw = seat(p, .76)
        p._wake_from_nap = Mock()
        p._ui_hit, p._swing_impulse = Mock(), Mock()
        for name in ("_catch_collect", "_pop_bubble", "_catch_ball", "_catch_leaf",
                     "_catch_flower", "_catch_snow"):
            setattr(p, name, Mock(return_value=False))
        return p, sw

    def test_background_press_closes_reader_but_starts_drag_on_first_press(self):
        p, sw = self._click_shell()
        p._book_open = True
        p.on_press(SimpleNamespace(x=20, y=400, x_root=500, y_root=450))
        self.assertIsNotNone(p._scene_drag)
        before = (sw["scene_l"], sw["scene_t"])
        p.on_drag(SimpleNamespace(x_root=530, y_root=490))
        self.assertEqual((sw["scene_l"], sw["scene_t"]),
                         (before[0]+30, before[1]+40))
        p.on_release(SimpleNamespace(x=20, y=400, x_root=530, y_root=490))
        self.assertIsNone(p._scene_drag)
        self.assertEqual((sw["theta"], sw["omega"]), (.137, -.42))
        p._save_swing_scene.assert_called_once()
        p._swing_impulse.assert_not_called()

    def test_plaque_click_dispatches_once_without_drag_or_swing_impulse(self):
        p, sw = self._click_shell()
        sw["ui_hits"] = [(110, 560, 300, 31, "house_trace", "trace")]
        p.on_press(SimpleNamespace(x=200, y=575, x_root=600, y_root=675))
        p._ui_hit.assert_called_once_with("house_trace", "trace")
        self.assertIsNone(p._scene_drag)
        p._swing_impulse.assert_not_called()

    def test_room_geometry_is_found_through_pet_assets_like_the_frozen_release(self):
        # PyInstaller keeps assets/ beside the exe, not beside house_scene.py
        import house_scene
        p = shell()
        p._house_on = True
        with patch.object(house_scene, "ASSET_DIR", house_scene.Path("missing/_internal/assets/house")), \
                patch.object(house_scene, "_META", None):
            self.assertIn("house_layout", p._art_geo(1.0))

    def test_missing_room_art_falls_back_to_the_plain_swing(self):
        p = shell()
        p._house_on = True
        with patch("pet.ASSETS", "missing-assets-dir"):
            self.assertFalse(p.house_enabled())
            self.assertNotIn("house_layout", p._art_geo(1.0))

    def test_detached_reader_fits_a_small_work_area_at_ui_scale(self):
        p = shell()
        p._book_open = True
        sw = seat(p)
        made = {}

        class Reader:
            closed = False

            def __init__(self, pet, size, scale):
                made.update(size=size, scale=scale)

            def update(self, ui, scene, area, avoid=()):
                pass

        with patch("ai_work_ui.AIWorkPanel", Reader), \
                patch("pet.work_area_at", return_value=(0, 0, 1280, 680)):
            p._sync_ai_panel(sw, {})
        (w, h), u = made["size"], made["scale"]
        self.assertEqual(u, 1.5)                          # same UI scale as the chat window
        self.assertLessEqual((w + 24) * u, 1280 - 16)
        self.assertLessEqual((h + 24) * u, 680 - 16)

    def test_house_suppresses_old_ai_pixels_and_local_scroll_hit(self):
        p = shell()
        p._house_on = True
        seat(p, .76)
        p._chain_rect_local = (10, 20, 100, 50)
        frame = Image.new("RGBA", (400, 520))
        p._draw_ai_lights(frame, 10000, 120, 180, 480, 1)
        p._draw_ai_chain(frame, 10000, 120, 110, 180)
        self.assertIsNone(frame.getbbox())
        self.assertIsNone(p._chain_rect_local)


if __name__ == "__main__":
    unittest.main()
