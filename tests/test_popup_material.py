"""Native translucency and existing Tk interaction; no live account/user data."""
import ctypes
import json
import os
import tkinter as tk
import unittest
from ctypes import wintypes
from unittest.mock import patch
from popup_material import OPACITY, PANEL_REST, SurfaceMenu, native_menu_surfaces, watch_menu_surfaces
from test_chat_ui import make_chat, make_card_pet


class MaterialTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.root.withdraw()
        self.addCleanup(self.root.destroy)

    def test_chat_retains_color_key_and_input_behavior(self):
        c=make_chat(self.root);self.root.update()
        self.assertAlmostEqual(float(c.win.attributes('-alpha')),OPACITY)
        self.assertTrue(c.win.attributes('-transparentcolor'))
        c.entry.insert(0,'材质测试草稿');self.root.update()
        self.assertEqual(str(c.send_btn['state']),'normal')
        self.assertEqual(c.draft.get(),'材质测试草稿')
        c.log_reply('窗口验证文字');self.assertIn('窗口验证文字',c._text_without_typing())

    def test_card_material_survives_focus_disable_and_close(self):
        p=make_card_pet(self.root)
        with patch('pet.work_area_at',return_value=(0,0,1366,768)):
            p.open_action_card(800,200)
        c=p.action_card;self.root.update()
        self.assertAlmostEqual(float(c.win.attributes('-alpha')),OPACITY)
        c.buttons['聊天'].invoke()
        p.open_chat.assert_called_once();self.assertIsNone(p.action_card)

    @unittest.skipUnless(os.name=='nt','Windows native menus')
    def test_native_menu_hook_is_scoped_and_available(self):
        self.assertTrue(watch_menu_surfaces())
        self.assertEqual(native_menu_surfaces(),[])  # no popup, no other window changed

    def test_menu_postcommand_is_preserved_and_cascades_use_same_class(self):
        hit=[]
        menu=SurfaceMenu(self.root,tearoff=0,postcommand=lambda:hit.append('post'))
        child=SurfaceMenu(menu,tearoff=0);child.add_command(label='子项')
        menu.add_cascade(label='设置',menu=child)
        self.root.tk.call(menu.cget('postcommand'))
        self.assertEqual(hit,['post'])
        self.assertIsInstance(child,SurfaceMenu)


if __name__=='__main__':unittest.main()
