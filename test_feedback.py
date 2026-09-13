"""表情续接、快速切换及交互提示回归;不创建桌宠或访问存档。"""
import unittest
from unittest.mock import patch, Mock
from collections import OrderedDict
from PIL import Image
from pet import Pet


class StickerFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.p = Pet.__new__(Pet)
        self.p.sticker = self.p._sticker_previous = None
        self.p.emotions = {'happy':['one','two'],'shy':['three'],'surprised':['four']}
        self.files = patch('pet.os.path.exists',return_value=True)
        self.files.start()
        self.choice = patch('pet.random.choice',side_effect=lambda names:names[0])
        self.choice.start()
        self.addCleanup(patch.stopall)

    def play(self, category, now):
        with patch('pet.time.time',return_value=now):
            return self.p.play_emotion(category,2.0)

    def test_repeated_emotion_keeps_image_and_scale(self):
        self.play('happy',100)
        before = self.p.sticker
        pose = self.p._sticker_pose(before,100.8)
        self.play('happy',100.8)
        self.assertIs(self.p.sticker,before)
        self.assertEqual(self.p._sticker_pose(before,100.8),pose)
        self.assertEqual(before['born'],100)
        self.assertAlmostEqual(before['born']+before['life'],102.8)

    def test_renew_during_fade_restores_from_current_opacity(self):
        self.play('happy',100)
        alpha = self.p._sticker_pose(self.p.sticker,101.9)[1]
        self.play('happy',101.9)
        self.assertAlmostEqual(self.p._sticker_pose(self.p.sticker,101.9)[1],alpha)
        self.assertEqual(self.p._sticker_pose(self.p.sticker,102.1)[1],1)

    def test_switch_keeps_frozen_outgoing_layer(self):
        self.play('happy',100)
        before = self.p._sticker_pose(self.p.sticker,100.7)
        self.play('shy',100.7)
        self.assertEqual(self.p._sticker_previous[0]['name'],'one')
        self.assertEqual(self.p._sticker_previous[2],before)
        self.assertEqual(self.p.sticker['name'],'three')

    def test_rapid_switch_preserves_dominant_image_without_nested_layers(self):
        self.play('happy',100)
        self.play('shy',100.7)
        self.play('surprised',100.73)
        self.assertEqual(self.p._sticker_previous[0]['name'],'one')
        self.assertEqual(self.p.sticker['name'],'four')
        for i in range(50):
            self.play('shy' if i%2 else 'surprised',100.74+i*.01)
            self.assertNotIn('previous',self.p.sticker)
            self.assertEqual(len(self.p._sticker_previous),3)

    def test_pose_has_smooth_bounded_entry_and_full_exit(self):
        self.play('happy',100)
        st = self.p.sticker
        for fps in (10,30,60):
            for i in range(3*fps):
                sc,alpha = self.p._sticker_pose(st,100+i/fps)
                self.assertTrue(.9<=sc<=1.025)
                self.assertTrue(0<=alpha<=1)
        self.assertEqual(self.p._sticker_pose(st,102.1),(1,0))
        self.assertAlmostEqual(self.p._sticker_pose(st,100.14-1e-6)[0],
                               self.p._sticker_pose(st,100.14+1e-6)[0],places=6)

    def test_missing_category_preserves_current_feedback(self):
        self.play('happy',100)
        before = dict(self.p.sticker)
        self.assertFalse(self.play('missing',100.5))
        self.assertEqual(self.p.sticker,before)

    def test_layer_applies_fade_alpha_only_once(self):
        p = self.p
        p.load_expr = Mock(return_value=Image.new('RGBA',(40,40),(200,100,80,255)))
        p._spr_disp_h = Mock(return_value=100)
        p.paste_glow = Mock()
        p._expr_rs = OrderedDict()
        p.W = 200
        frame = Image.new('RGBA',(200,200))
        p._draw_sticker_layer(frame,100,1,0,0,80,Image.new('RGBA',(80,100)),
                              {'name':'one'},(1,.5))
        self.assertEqual(frame.getpixel((80,20)),(200,100,80,127))


if __name__=='__main__':
    unittest.main()
