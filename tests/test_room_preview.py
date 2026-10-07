"""Actual Tk click/resize checks for the isolated room layout viewer."""
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock

from room_preview_viewer import PAGES, RoomPreviewWindow

ASSETS = Path(__file__).resolve().parents[1] / "assets"


class RoomPreviewTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.view = RoomPreviewWindow(self.root, ASSETS)
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def click(self, key):
        x, y, w, h = self.view.rects[key]
        self.view.canvas.event_generate("<Button-1>", x=x + w // 2, y=y + h // 2)
        self.root.update()

    def test_clicks_at_normal_and_small_sizes_open_correct_pages(self):
        for scale in (1.0, 0.76):
            self.view.set_scale(scale)
            self.root.update()
            for key in PAGES:
                with self.subTest(scale=scale, entrance=key):
                    self.click(key)
                    self.assertEqual(self.view.selected, key)
                    self.assertEqual(self.view.page_title.get(), PAGES[key][0])
            # Clicking unused floor space must not open a different page.
            self.view.canvas.event_generate("<Button-1>", x=30, y=round(430 * scale))
            self.root.update()
            self.assertEqual(self.view.selected, "quota")

    def test_small_targets_stay_separate_and_back_closes_preview(self):
        self.view.set_scale(0.76)
        boxes = list(self.view.rects.items())
        for key, (x, y, w, h) in boxes:
            self.assertGreaterEqual(min(w, h), 32)
            for other, (ox, oy, ow, oh) in boxes:
                if key != other:
                    self.assertFalse(x < ox + ow and ox < x + w
                                     and y < oy + oh and oy < y + h)
        self.click("back")
        self.assertTrue(self.view.closed)
        self.assertFalse(self.view.win.winfo_exists())

    def test_scene_zoom_preserves_readable_panel_and_keyboard_selection(self):
        self.view.select("chat")
        self.root.update()
        normal_title = self.view.page_title.get()
        labels = [w for w in self.view.page.winfo_children() if isinstance(w, tk.Label)]
        fonts_and_wrap = [(w.cget("font"), w.cget("wraplength")) for w in labels]
        panel_size = (self.view.page.winfo_width(), self.view.page.winfo_height())
        self.view.set_scale(0.76)
        self.root.update()
        self.assertEqual(self.view.page_title.get(), normal_title)
        self.assertEqual((self.view.page.winfo_width(), self.view.page.winfo_height()), panel_size)
        self.assertEqual([(w.cget("font"), w.cget("wraplength")) for w in labels], fonts_and_wrap)
        self.view._next_entrance()
        self.view._activate_focused()
        self.assertEqual(self.view.selected, "quota")

    def test_pet_room_entrance_uses_integrated_scene_instead_of_preview(self):
        import pet
        from unittest.mock import patch
        p = pet.Pet.__new__(pet.Pet)
        p.root = self.root
        p.close_action_card = Mock()
        p._set_house_mode = Mock()
        scene = p._swing = {"art": True}
        p.state = "swing"
        with patch("room_preview_viewer.RoomPreviewWindow") as factory:
            p.open_room_preview()
            p._set_house_mode.assert_called_once_with(True)
            factory.assert_not_called()
        self.assertIs(p._swing, scene)
        self.assertEqual(p.state, "swing")

    def test_book_page_grows_for_larger_text_without_clipping(self):
        self.view.select("trace")
        for label in self.view.page.winfo_children():
            label.configure(font=("Microsoft YaHei UI", 16))
        self.view._fit_page()
        self.root.update()
        page = self.view.page
        self.assertGreater(page.winfo_height(), 355)
        for label in page.winfo_children():
            self.assertEqual(label.winfo_height(), label.winfo_reqheight())
            self.assertLessEqual(label.winfo_y() + label.winfo_height(), page.winfo_height() - 18)


if __name__ == "__main__":
    unittest.main()
