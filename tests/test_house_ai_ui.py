"""Room nameplate tests and optional previews, using synthetic snapshots only."""
import copy
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import ImageDraw

from house_ai_ui import plaque_lines, quota_brief, render_plaque

SIZES = ((403, 41), (306, 31), (250, 26))


def snapshot():
    now = 1791081600.0
    actions = [                                   # session files keep the newest first
        {'a': '完成界面验证', 'r': '字号、点击区和边缘均已检查', 't': now-10},
        {'a': '绘制小屋布局', 'r': '人物居中、帘幔挡住横杆', 't': now-60},
        {'turn': 1, 't': now-120},
        {'a': '读取项目约束', 'r': '采用紫金主题与小幅空间视差', 't': now-150},
    ]
    session = {'id': 'synthetic-task', 'agent': 'zcode', 'title': '小乔 · 小屋界面',
               'state': 'running', 'updated': now-10, 'actions': actions}
    return {'now': now,
            'sources': [('zcode', 'ZCode', 'Z'), ('mac-claude', 'Claude·Mac', 'M'),
                        ('claude', 'Claude', '✦')],
            'sel_key': 'zcode', 'sel_session': session, 'sessions': [session],
            'quota': {'fh': 23, 'sd': 48, 't': (now-60)*1000, 'reset_est': now+3600},
            'quota_age': 60, 'badge': {}, 'mock': False}


def owner():
    return SimpleNamespace(_trace_snap=None, _trace_page=7, _book_open=False,
                           save_settings=Mock(side_effect=AssertionError('unexpected save')),
                           _ui_hit=Mock(side_effect=AssertionError('unexpected callback')))


def codex_snapshot(ui, used=12):
    return {'provider': 'codex', 't': (ui['now']-60)*1000,
            'source': 'Codex 官方用量接口',
            'cycles': [{'label': '一周', 'used': 38, 'minutes': 10080, 'reset': ui['now']+86400},
                       {'label': '5 小时', 'used': used, 'minutes': 300, 'reset': ui['now']+3600}]}


def captured(ui, size=(403, 41), font_px=22):
    seen = []
    original = ImageDraw.ImageDraw.text

    def record(draw, xy, value, *args, **kwargs):
        seen.append((xy, value, kwargs.get('font'), kwargs.get('anchor')))
        return original(draw, xy, value, *args, **kwargs)

    with patch.object(ImageDraw.ImageDraw, 'text', record):
        image, hits = render_plaque(owner(), ui, size, font_px)
    return image, hits, seen


class RoomPlaqueTests(unittest.TestCase):
    def test_exact_size_two_non_overlapping_targets_and_opaque_face(self):
        for size in SIZES:
            image, hits = render_plaque(owner(), snapshot(), size)
            self.assertEqual((image.size, image.mode), (size, 'RGBA'))
            self.assertGreaterEqual(image.getpixel((size[0]//2, size[1]//2))[3], 240)
            self.assertEqual([hit[4:6] for hit in hits],
                             [('house_trace', 'trace'), ('house_quota', 'overview')])
            left, right = hits
            self.assertEqual(left[:2], (0, 0))
            self.assertEqual(right[1], 0)
            self.assertEqual(left[2], right[0])
            self.assertEqual(right[0]+right[2], size[0])
            self.assertEqual((left[3], right[3]), (size[1], size[1]))
            self.assertGreater(min(left[2], right[2]), 0)

    def test_shows_source_state_latest_real_step_and_account_quota(self):
        _, initial, state, step, right, _ = plaque_lines(snapshot())
        self.assertEqual((initial, state, step), ('Z', '运行中', '完成界面验证'))
        self.assertEqual(right, '5h 剩77%')
        _, _, seen = captured(snapshot())
        labels = [value for _, value, _, anchor in seen if anchor == 'lm']
        self.assertTrue(labels[0].startswith('工作流·运行中'))
        self.assertTrue(labels[1].startswith('AI 限额'))

    def test_codex_account_snapshot_has_priority_and_retains_real_zero_usage(self):
        ui = snapshot()
        ui['codex_quota'] = codex_snapshot(ui, 0)
        provider, remaining, suffix, _ = quota_brief(ui)
        self.assertEqual((provider, remaining, suffix), ('Codex', 100, ''))
        _, _, seen = captured(ui)
        labels = [value for _, value, _, anchor in seen if anchor == 'lm']
        self.assertIn('Codex', labels[1])
        self.assertNotIn('Claude', labels[1])

    def test_invalid_codex_cycle_falls_back_to_real_claude_data(self):
        for invalid in (None, True, float('nan'), float('inf'), '20', -1, 101):
            ui = snapshot()
            ui['codex_quota'] = codex_snapshot(ui, invalid)
            self.assertEqual(quota_brief(ui)[:2], ('Claude', 77))
            ui['quota'] = None
            self.assertEqual(quota_brief(ui)[:3], ('', None, '未取得'))

    def test_codex_weekly_data_is_not_presented_as_a_five_hour_cycle(self):
        ui = snapshot()
        ui['codex_quota'] = codex_snapshot(ui)
        ui['codex_quota']['cycles'] = ui['codex_quota']['cycles'][:1]
        self.assertEqual(quota_brief(ui)[:2], ('Claude', 77))

    def test_codex_old_timestamp_and_passed_reset_are_marked_old(self):
        ui = snapshot()
        for age, reset, old in ((3599, ui['now']+60, False),
                                (3601, ui['now']+60, True),
                                (60, ui['now'], True), (60, ui['now']-1, True)):
            ui['codex_quota'] = codex_snapshot(ui)
            ui['codex_quota']['t'] = (ui['now']-age)*1000
            ui['codex_quota']['cycles'][1]['reset'] = reset
            self.assertEqual(quota_brief(ui)[2], '旧' if old else '')
            if old:
                for size in SIZES:
                    _, _, seen = captured(ui, size)
                    right = [value for _, value, _, anchor in seen if anchor == 'lm'][1]
                    self.assertIn('旧', right)

    def test_codex_snapshot_time_unknown_and_simulation_are_explicit(self):
        ui = snapshot()
        ui['codex_quota'] = codex_snapshot(ui)
        ui['codex_quota']['t'] = None
        self.assertEqual(quota_brief(ui)[:3], ('Codex', 88, '时间未知'))
        ui['mock'] = True
        self.assertEqual(quota_brief(ui)[2], '时间未知 · 模拟')
        ui['codex_quota']['t'] = (ui['now']-7200)*1000
        self.assertEqual(quota_brief(ui)[2], '旧 · 模拟')

    def test_missing_claude_sample_time_cannot_be_freshened_by_age(self):
        ui = snapshot()
        ui['quota']['t'] = None
        ui['quota_age'] = 0
        self.assertEqual(quota_brief(ui)[:3], ('Claude', 77, '时间未知'))
        ui['quota']['t'] = (ui['now']+60)*1000
        self.assertEqual(quota_brief(ui)[2], '时间未知')

    def test_read_failure_keeps_the_last_codex_value_and_marks_it_old(self):
        ui = snapshot()
        ui['codex_quota'] = codex_snapshot(ui, 12)
        ui['codex_quota_error'] = True
        self.assertEqual(quota_brief(ui)[:3], ('Codex', 88, '旧'))
        for size in SIZES:
            _, _, seen = captured(ui, size)
            right = [value for _, value, _, anchor in seen if anchor == 'lm'][1]
            self.assertIn('旧', right)
        ui.update(codex_quota=None, quota=None)
        self.assertEqual(quota_brief(ui)[:3], ('', None, '旧'))

    def test_invalid_claude_percentages_are_unknown_instead_of_clamped(self):
        ui = snapshot()
        for used in (-1, 101):
            ui['quota']['fh'] = used
            self.assertEqual(quota_brief(ui)[:3], ('', None, '未取得'))
            _, _, seen = captured(ui)
            right = [value for _, value, _, anchor in seen if anchor == 'lm'][1]
            self.assertNotIn('%', right)

    def test_quota_label_is_visible_even_when_no_sample_exists(self):
        ui = snapshot()
        ui.update(quota=None, codex_quota=None)
        for size in SIZES:
            _, _, seen = captured(ui, size, max(12, round(size[1]*.52)))
            right = [value for _, value, _, anchor in seen if anchor == 'lm'][1]
            self.assertTrue(right.startswith('AI 限额'))
            self.assertNotIn('%', right)
            self.assertIn('未取得', right)

    def test_claude_quota_is_the_account_for_every_source(self):
        for key in ('zcode', 'mac-claude', 'claude'):
            ui = snapshot()
            ui['sel_key'] = key
            self.assertEqual(plaque_lines(ui)[4], '5h 剩77%')

    def test_unknown_cycle_is_never_shown_as_zero_or_full(self):
        for invalid in (None, True, float('nan'), float('inf'), '20'):
            ui = snapshot()
            ui['quota'] = {'fh': invalid, 'sd': 30}
            self.assertEqual(plaque_lines(ui)[4], '')

    def test_stale_samples_and_simulation_say_so(self):
        ui = snapshot()
        ui['quota_age'] = 7200
        self.assertEqual(plaque_lines(ui)[4], '5h 剩77% · 旧')
        ui.update(quota_age=60, mock=True)
        self.assertEqual(plaque_lines(ui)[4], '5h 剩77% · 模拟')
        ui.update(quota=None)
        self.assertEqual(plaque_lines(ui)[4], '模拟数据')

    def test_session_status_matches_existing_stale_semantics(self):
        for stale, age, expected in ((False, 10, '运行中'), (False, 2500, '久未更新'),
                                     (True, 10, '离线')):
            ui = snapshot()
            ui['sel_session'].update(stale=stale, updated=ui['now']-age)
            self.assertEqual(expected, plaque_lines(ui)[2])

    def test_quota_only_and_empty_states_are_honest(self):
        ui = snapshot()
        ui.update(sel_key='claude', sel_session=None, sessions=[])
        self.assertEqual(plaque_lines(ui)[1:4], ('', 'Claude 共享账户', ''))
        ui.update(quota=None)
        self.assertIn('暂无任务', plaque_lines(ui)[2])
        ui = snapshot()
        ui['sel_session']['actions'] = []
        self.assertEqual(plaque_lines(ui)[2:4], ('运行中', ''))

    def test_no_dangling_separator_when_the_step_does_not_fit(self):
        _, _, seen = captured(snapshot(), (150, 26), 14)
        main = [value for _, value, _, anchor in seen if anchor == 'lm'][0]
        self.assertTrue(main.startswith('工作流'))
        self.assertFalse(main.rstrip('… ').endswith('·'))

    def test_long_text_is_measured_and_stays_inside_the_plaque(self):
        ui = snapshot()
        ui['sel_session']['actions'][0].update(a='极长步骤名称'*50, t=float('nan'))
        for size in SIZES:
            _, _, seen = captured(ui, size, max(12, round(size[1]*.52)))
            lines = [item for item in seen if item[3] == 'lm']
            self.assertEqual(len(lines), 2)
            for (x, y), value, font, anchor in lines:
                self.assertGreaterEqual(x, 0, value)
                self.assertLessEqual(x+font.getlength(value), size[0], value)
            (x0, _), _, f0, _ = lines[0]
            (x1, _), _, _, _ = lines[1]
            self.assertLessEqual(x0+f0.getlength(lines[0][1]), x1, 'main text overlaps quota')

    def test_rendering_neither_changes_inputs_nor_calls_owner(self):
        ui, pet = snapshot(), owner()
        ui['codex_quota'] = codex_snapshot(ui)
        render_plaque(pet, ui, (403, 41))         # warm the font cache
        saved_ui, saved_owner = copy.deepcopy(ui), dict(vars(pet))
        with patch('builtins.open', side_effect=AssertionError('unexpected file read')):
            render_plaque(pet, ui, (403, 41))
        self.assertEqual(ui, saved_ui)
        self.assertEqual(vars(pet), saved_owner)
        pet.save_settings.assert_not_called()
        pet._ui_hit.assert_not_called()


def write_previews(directory):
    """Save rendered synthetic states; never construct Pet or scan real data."""
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    offline = snapshot()
    offline['sel_session']['stale'] = True
    offline['quota_age'] = 7200
    empty = snapshot()
    empty.update(sources=[], sel_key=None, sel_session=None, sessions=[], quota=None)
    for name, ui in (('plaque-default', snapshot()), ('plaque-offline', offline),
                     ('plaque-empty', empty)):
        render_plaque(owner(), ui, (403, 41), 22)[0].save(path/(name+'.png'))


if __name__ == '__main__':
    import sys
    if '--preview' in sys.argv:
        write_previews(Path(__file__).resolve().parents[1]/'outputs'/'house-ai-ui')
    else:
        unittest.main()
