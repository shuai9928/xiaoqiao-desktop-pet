"""Finite task summaries stay useful without carrying private source text."""
import unittest

from task_directions import DIRECTIONS, task_direction


class TaskDirectionsTests(unittest.TestCase):
    def test_explicit_categories_and_public_task_names(self):
        for direction in DIRECTIONS:
            self.assertEqual(task_direction(direction), direction)
        examples = {
            'workflow_metadata': '工作流与进度',
            'popup_material': '窗口材质',
            'color_contrast_review': '颜色与对比度',
            'real_size_review': '比例与尺寸',
            'closed_eye_blink': '角色动作',
            'hat_fx_render': '动态特效',
            'ui_layout_review': '界面与布局',
            'native_session_sync': '数据接入',
            'regression_testing': '测试与验证',
            'code_review': '审核与检查',
            'research': '资料调研',
            'deployment': '交付与部署',
        }
        for text, expected in examples.items():
            with self.subTest(text=text):
                self.assertEqual(task_direction(text), expected)

    def test_raw_prompt_never_returned(self):
        direction = task_direction('检查颜色对比度；PRIVATE_EMAIL TOKEN=PRIVATE_SECRET')
        self.assertEqual(direction, '颜色与对比度')
        self.assertNotIn('PRIVATE_', direction)
        self.assertIsNone(task_direction('PRIVATE_ACCOUNT private-client-99123'))
        self.assertIsNone(task_direction('testimony ouija sleepy rendering'))
        self.assertIsNone(task_direction({'task_name': 'test'}))

    def test_reading_test_filename_does_not_imply_test_task(self):
        self.assertEqual(task_direction('改 test_popup_material.py'), '窗口材质')
        self.assertEqual(task_direction('读 test_native_session_sync.py'), '数据接入')
        self.assertEqual(task_direction('读 test_ai_lights_core.py'), '数据接入')
        self.assertEqual(task_direction('改 flat_workspace.py'), '界面与布局')
        self.assertEqual(task_direction('读 fx.py'), '动态特效')
        self.assertIsNone(task_direction('读 test_other.py'))
        self.assertEqual(task_direction('跑测试 pytest'), '测试与验证')


if __name__ == '__main__':
    unittest.main()
