"""Persistent spellbook: account quotas and chronological, evidence-based steps.

Only consumes the host's snapshot. No file scanning, network, or model calls.
The existing detail reader owns full records; this surface never truncates them.
"""
from __future__ import annotations

import time
from PIL import Image, ImageDraw
from ai_quota import quota_view

INK = '#f5efe6'
DIM = '#b5a8c7'
GREEN = '#a8d9ae'
PURPLE = '#c19aef'
AMBER = '#efc17e'
RED = '#ef959a'
FACE = '#251c35'
COLORS = {'done': GREEN, 'running': PURPLE, 'waiting': AMBER,
          'error': RED, 'pending': '#776986', 'recorded': DIM}
LABELS = {'done': '已完成', 'running': '进行中', 'waiting': '等你处理',
          'error': '出错了', 'pending': '未开始', 'recorded': '已记录'}


def workflow(ui):
    """No plan is invented from action history. Result-less past steps are
    recorded, never green; only a real result (or explicit status) marks done.
    A stale session never keeps claiming to run. Indexes match trace_rows(48).
    """
    from pet import trace_rows, ai_session_stale
    session = ui.get('sel_session') or {}
    now = ui.get('now') or time.time()
    state = session.get('state', 'idle')
    stale = bool(session.get('stale') or (session and ai_session_stale(session, now)))
    rows = trace_rows(session, 48)
    # The current turn is the relevant progress track; older turns remain in
    # the full reader. Keep absolute indexes so clicks always open the right row.
    start = max((i + 1 for i, r in enumerate(rows) if r[0] == 'turn'), default=0)
    steps = []
    for index, row in enumerate(rows[start:], start):
        if row[0] != 'step':
            continue
        _, stamp, title, result, error, count = row
        if error:
            status = 'error'
        elif result and not result.startswith(('正在', '等待', '进行中')):
            status = 'done'
        else:
            status = 'recorded'
        steps.append({'index': index, 'title': title, 'result': result,
                      'status': status, 'count': count})
    if steps and not stale and steps[-1]['status'] == 'recorded':
        if state in ('running', 'waiting', 'error'):
            steps[-1]['status'] = state
    label = ('离线' if session.get('stale') else '久未更新') if stale else {
        'running': '运行中', 'waiting': '等你处理', 'done': '已结束',
        'error': '出错了', 'idle': '空闲'}.get(state, '状态未知')
    return {'session': session, 'steps': steps, 'state': state,
            'stale': stale, 'label': label if session else '暂无任务',
            'completed': sum(s['status'] == 'done' for s in steps)}


def _fit(s, font, width):
    s = str(s or '').replace('\n', ' ')
    if font.getlength(s) <= width:
        return s
    while s and font.getlength(s + '…') > width:
        s = s[:-1]
    return s + '…' if s else ''


TIERS = {
    # name: (quota row, quota details, workflow head, step row, two-line steps), in u units
    'full': (52, True, 58, 40, True),
    'compact': (34, False, 44, 34, False),
    'mini': (30, False, 24, 32, False),
}


def tier_for(h, u):
    """Pick the densest tier that fits; the type size never shrinks with zoom."""
    hu = h / max(1.0, u)
    if hu >= 400:
        return 'full'
    if hu >= 258:
        return 'compact'
    return 'mini'


def min_board(u):
    """Smallest readable board in pixels (the mini tier) for the host's zoom floor."""
    return round(210 * u), round(200 * u)


def render(ui, size, font_scale=1.0):
    """Opaque reading face and local hit zones.  Font sizes follow the screen
    density (u), not the character's zoom; a smaller board shows less, it never
    shrinks or overlaps text.  Three densities: full / compact / mini."""
    from apple_ui import font as _font
    w, h = map(int, size)
    u = max(1.0, float(font_scale))
    tier = tier_for(h, u)
    q_row, q_detail, wf_head, row_h, two_line = TIERS[tier]
    q_row, wf_head, row_h = q_row * u, wf_head * u, row_h * u
    im = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    font = _font(round(14 * u), 430)
    small = _font(round(11 * u), 420)
    large = _font(round((22 if tier == 'full' else 18) * u), 560)
    heading = _font(round(15 * u), 600)
    pad = round((14 if tier != 'mini' else 11) * u)
    hits = []

    def text(x, y, s, f=font, color=INK, width=None, anchor='la'):
        d.text((round(x), round(y)), _fit(s, f, width) if width else str(s), font=f, fill=color,
               anchor=anchor)

    def hit(rect, kind, payload=None):
        x, y, rw, rh = (round(v) for v in rect)
        x, y = max(0, x), max(0, y)
        hits.append((x, y, min(rw, w - x), min(rh, h - y), kind, payload))

    footer_h = (34 if tier == 'mini' else 36) * u
    footer_top = h - pad - footer_h
    y = pad
    tag = '模拟数据' if ui.get('mock') else '账户快照'
    if tier == 'full':
        text(pad, y, 'AI 额度', heading)
        text(w - pad, y + 2 * u, tag, small, DIM, anchor='ra')
        y += 26 * u
    for provider, name in (('codex', 'Codex'), ('claude', 'Claude')):
        view = quota_view(ui, provider)
        cycle = view['cycles'][0]
        remaining = cycle['remaining']
        old = cycle['stale'] or view['status'] in ('unknown', 'read_error')
        display = '未取得' if remaining is None else f'{remaining:.0f}%'
        top = y
        text(pad, y + 2 * u, name + (' · 旧' if old and remaining is not None and tier != 'full' else ''), font)
        text(w - pad, y - (3 if tier == 'full' else 1) * u, display, large,
             AMBER if old else INK, anchor='ra')
        if remaining is not None:
            vw = large.getlength(display)
            text(w - pad - vw - 6 * u, y + 5 * u, '剩余', small, DIM, anchor='ra')
        by = y + (27 if tier == 'full' else 23 if tier == 'compact' else 22) * u
        d.rounded_rectangle((pad, by, w - pad, by + 3 * u), radius=2 * u, fill='#51435e')
        if remaining is not None and remaining > 0:
            d.rounded_rectangle((pad, by, pad + (w - 2 * pad) * remaining / 100, by + 3 * u),
                                radius=2 * u, fill=AMBER if old else '#d4b77f')
        if q_detail:
            if remaining is None:
                line = '5小时 · 暂无额度样本'
            elif old:
                line = '5小时 · 旧样本' if view['status'] != 'unknown' else '5小时 · 采样时间未知'
            elif cycle['reset']:
                reset = time.strftime('%H:%M', time.localtime(cycle['reset']))
                line = f"5小时 · {'预计' if cycle['estimated'] else ''}{reset} 重置"
            else:
                line = '5小时 · 重置时间未知'
            if remaining is not None and view['t']:
                fmt = '%m-%d %H:%M' if old else '%H:%M'
                line += f" · {time.strftime(fmt, time.localtime(view['t'] / 1000))}采样"
            text(pad, y + 34 * u, line, small, AMBER if old else DIM, w - 2 * pad)
        y += q_row
        hit((pad, top - 3 * u, w - 2 * pad, q_row - 2 * u), 'moon_quota', provider)
    y += 4 * u
    if tier != 'full':
        # no title row in the denser tiers: the data tag sits on the divider instead
        tw_ = small.getlength(tag) + 8 * u
        d.line((pad, y, w - pad - tw_, y), fill='#655473', width=1)
        text(w - pad, y, tag, small, DIM, anchor='rm')
    else:
        d.line((pad, y, w - pad, y), fill='#655473', width=1)
    y += 9 * u
    flow = workflow(ui)
    ss = flow['session']
    label = flow['label']
    head_top = y
    text(pad, y, '工作流', heading, '#dfc598')
    if flow['steps']:
        n = len(flow['steps'])
        progress = f"{flow['completed']}项完成" if flow['completed'] else f'{n}条记录'
        label = f'{label} · {progress}'
    text(w - pad, y + 2 * u, label, small, DIM if flow['stale'] else COLORS.get(flow['state'], DIM),
         anchor='ra')
    if tier != 'mini':
        task = ss.get('title') or '等待接入工作记录'
        sources = ui.get('sources') or []
        source = next((lab for key, lab, _ in sources if key == ui.get('sel_key')), ss.get('agent', ''))
        many = len(ui.get('sessions') or []) > 1
        text(pad, y + 22 * u, task + (f' · {source}' if source and tier == 'compact' else ''), font,
             INK, w - 2 * pad - (70 * u if many else 0))
        if tier == 'full':
            text(pad, y + 44 * u, source or '没有可读取的会话', small, DIM, w - 2 * pad)
        if many:
            text(w - pad, y + 24 * u, '切换 ›', small, PURPLE, anchor='ra')
            hit((w - pad - 66 * u, y + 16 * u, 66 * u, 28 * u), 'moon_next')
    y = head_top + wf_head
    capacity = max(1, int((footer_top - y - 6 * u) / row_h))
    visible = flow['steps'][-capacity:]
    if not visible:
        text(pad, y + 4 * u, '暂无步骤记录', font, DIM, w - 2 * pad)
    cx = pad + 10 * u
    r = 8 * u
    for i, step in enumerate(visible):
        cy = y + i * row_h + (12 if two_line else row_h / 2 / u) * u
        color = COLORS[step['status']]
        if i:
            previous = visible[i - 1]['status']
            line = GREEN if previous == step['status'] == 'done' else '#655473'
            d.line((cx, cy - row_h + r + 2 * u, cx, cy - r - 2 * u), fill=line, width=max(1, round(2 * u)))
        if step['status'] == 'done':
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
            d.line((cx - 4 * u, cy, cx - u, cy + 3 * u, cx + 4.5 * u, cy - 3.5 * u), fill=FACE,
                   width=max(1, round(2 * u)))
        else:
            d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=color, width=max(1, round(2 * u)))
            if step['status'] in ('running', 'waiting', 'error'):
                d.ellipse((cx - 3.5 * u, cy - 3.5 * u, cx + 3.5 * u, cy + 3.5 * u), fill=color)
        tx = pad + 28 * u
        status = LABELS[step['status']]
        if two_line:
            text(tx, cy - 12 * u, step['title'], font, INK, w - pad - tx)
            text(tx, cy + 9 * u, status, small, color, w - pad - tx)
        else:
            sw_ = small.getlength(status)
            text(tx, cy, step['title'], font, INK, w - pad - tx - sw_ - 8 * u, anchor='lm')
            text(w - pad, cy, status, small, color, anchor='rm')
        hit((pad, cy - row_h / 2 + 1, w - 2 * pad, row_h - 2), 'detail',
            (ss.get('id'), step['index'], step['title'], step['result']))
    # footer: open the current task; chat beside it (not in mini)
    bw = round((w - 2 * pad) * (1.0 if tier == 'mini' else .66))
    d.rounded_rectangle((pad, footer_top, pad + bw, footer_top + footer_h), radius=8 * u, fill='#d0b9e9')
    label = '查看当前任务'
    text(pad + bw / 2, footer_top + footer_h / 2, label, font, '#281c38', anchor='mm')
    hit((pad, footer_top, bw, footer_h), 'house_trace')
    if tier != 'mini':
        text(pad + bw + (w - 2 * pad - bw) / 2, footer_top + footer_h / 2, '聊聊', font, INK, anchor='mm')
        hit((pad + bw + 6 * u, footer_top, w - 2 * pad - bw - 6 * u, footer_h), 'house_chat')
    return im, hits
