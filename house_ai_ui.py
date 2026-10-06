"""The room's AI nameplate, rendered from the existing AI UI snapshot only.

One readable line inset in the platform front: the workflow and its status
on the left, and a separately labelled account quota entry on the right.
The existing AIWorkPanel retains sources, both quota cycles and full records.
The two non-overlapping click regions emit ``house_trace`` and ``house_quota``.

``render_plaque(owner, ui, size)`` returns an RGBA image of exactly ``size``
and plaque-local ``(x, y, width, height, kind, payload)`` hit rectangles.
Rendering changes neither the owner nor the snapshot, scans no sources and
makes no model calls.
"""
import math
from functools import lru_cache

from PIL import Image, ImageDraw

import ui3d

INK = (246, 239, 227, 255)
DIM = (190, 178, 210, 255)
ACCENT = (205, 176, 250, 255)
WARN = (246, 192, 123, 255)
FACE_TOP, FACE_BOTTOM = (34, 26, 48), (22, 17, 32)
RIM = (214, 185, 139)


@lru_cache(maxsize=8)
def _font(size):
    from pet import load_font
    return load_font(size)


def _finite(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _fit(value, font, width):
    value = str(value or '').replace('\n', ' ')
    if width <= 0:
        return ''
    if font.getlength(value) <= width:
        return value
    while value and font.getlength(value + '…') > width:
        value = value[:-1]
    return value + '…' if value else ''


def plaque_lines(ui):
    """(color, initial, state, step, right text, right color) for the snapshot.
    The source shows as its initial on the gem (Z/M/C/W/✦, like the old status
    lights) so the one line is left for the state and the latest real step.
    Same honesty rules as the reader: the quota is the shared Claude account,
    an unknown cycle is never shown as 0 or 100, stale samples say so."""
    from pet import (CRYSTAL_COLORS, CRYSTAL_LABEL, QUOTA_STALE_AFTER,
                     ai_session_stale, quota_age, trace_rows)
    now = ui.get('now') if _finite(ui.get('now')) else 0.0
    session = ui.get('sel_session') or None
    quota = ui.get('quota') or None
    if session:
        state = 'offline' if session.get('stale') else session.get('state', 'idle')
        color = CRYSTAL_COLORS.get(state, CRYSTAL_COLORS['unknown'])
        label = CRYSTAL_LABEL.get(state, '状态未知')
        if not session.get('stale') and ai_session_stale(session, now):
            color, label = (151, 140, 166), '久未更新'
        initial = (next((ini for key, _, ini in (ui.get('sources') or [])
                         if key == ui.get('sel_key')), None)
                   or str(session.get('agent') or 'A')[:1].upper())
        actions = [dict(a, t=a.get('t') if _finite(a.get('t')) else 0)
                   for a in (session.get('actions') or []) if isinstance(a, dict)]
        steps = [row for row in trace_rows({'actions': actions}, 48) if row[0] == 'step']
        step = steps[-1][2] if steps else ''
    else:
        color, initial, step = CRYSTAL_COLORS['unknown'], '', ''
        label = '暂无任务 · 点开看记录' if not quota else 'Claude 共享账户'
    right, right_color = '', ACCENT
    used = (quota or {}).get('fh')
    if _finite(used):
        age = ui.get('quota_age')
        if not _finite(age):
            t = (quota or {}).get('t')
            age = quota_age(quota, now) if now > 0 and _finite(t) and t > 0 else None
        remaining = 100 - max(0.0, min(100.0, float(used)))
        right = f'5h 剩{remaining:.0f}%'
        if age is not None and age > QUOTA_STALE_AFTER:
            right, right_color = right + ' · 旧', WARN
    if ui.get('mock'):
        right = (right + ' · 模拟') if right else '模拟数据'
    return color, initial, label, step, right, right_color


def gem_motion(ui, now):
    """The nameplate gem is the room's status light: (rgb, glow 0..1).
    Running breathes slowly, waiting-for-you pulses, an error glows, a fresh
    finish shimmers for 90 s and then rests; idle/stale/offline stay still."""
    from pet import CRYSTAL_COLORS, ai_session_stale
    session = ui.get('sel_session') or None
    if not session or not _finite(now):
        return None, 0.0
    state = session.get('state')
    if session.get('stale') or ai_session_stale(session, now):
        return None, 0.0
    rgb = CRYSTAL_COLORS.get(state)
    if state == 'running':
        return rgb, .22 + .33 * (.5 - .5 * math.cos(math.tau * now / 2.6))
    if state == 'waiting':
        return rgb, .30 + .62 * max(0.0, math.sin(math.pi * ((now / 1.3) % 1.0))) ** 2
    if state == 'error':
        return rgb, .30 + .30 * (.5 - .5 * math.cos(math.tau * now / 2.0))
    updated = session.get('updated')
    if state == 'done' and _finite(updated) and 0 <= now - updated < 90:
        return rgb, .55 * (1 - (now - updated) / 90)
    return None, 0.0


def gem_center(h):
    """Gem centre and radius in plaque-local pixels (same formula as render_plaque)."""
    gem_r = max(5, round(h * .26))
    return round(h * .35) + gem_r, h / 2, gem_r


def quota_brief(ui):
    """Independent account summary; Codex 5h takes priority when obtained.

    Returns (provider, remaining or None, suffix, color).  The shared quota
    adapter owns validation and freshness, matching the full reader exactly.
    ``used is not None`` retains a legitimate zero while rejecting unknowns.
    """
    from ai_quota import quota_view
    views = [quota_view(ui, provider=key) for key in ('codex', 'claude')]
    for view in views:
        cycle = view['cycles'][0]       # Canonical adapter order: 5 hours, 7 days.
        if cycle['used'] is None:
            continue
        error = view['status'] == 'read_error'
        if error:
            suffix = '旧'
        elif view['status'] == 'unknown':
            suffix = '时间未知'
        else:
            suffix = '旧' if cycle['stale'] else ''
        if ui.get('mock'):
            suffix = (suffix+' · 模拟') if suffix else '模拟'
        provider = 'Codex' if view['provider'] == 'codex' else 'Claude'
        return provider, cycle['remaining'], suffix, WARN if cycle['stale'] or error else ACCENT
    failed = any(view['status'] == 'read_error' for view in views)
    suffix = '旧' if failed else '未取得'
    if ui.get('mock'):
        suffix = (suffix+' · 模拟') if failed else '模拟'
    return '', None, suffix, WARN if failed else DIM


def preferred_width(ui, h, font_px):
    """How wide the plaque wants to be for its labelled zones to read in full
    (workflow + state + the start of the step | quota with provider and 5h).
    The host grows a small plaque toward this instead of truncating to "工作流…"."""
    _, initial, state, step, _, _ = plaque_lines(ui)
    provider, remaining, suffix, _ = quota_brief(ui)
    if not ui.get('sel_session'):
        state = '暂无任务'
    font, small = _font(int(font_px)), _font(max(10, round(font_px * .9)))
    gx, _, gem_r = gem_center(h)
    tx = gx + gem_r + round(h * .28)
    left = '工作流·' + state + ((' · ' + step[:4] + '…') if step else '')
    mark = (' · ' + suffix) if suffix else ''
    right = (f'AI 限额 {provider}剩{remaining:.0f}%' + mark if remaining is not None
             else 'AI 限额' + mark)
    gap, right_pad = max(6, round(h * .28)), round(h * .4)
    return int(tx + font.getlength(left) + gap + small.getlength(right) + right_pad) + 1


def render_plaque(owner, ui, size, font_px=None):
    """Inset nameplate: dark matte face, thin gold rim, one line of text.
    ``owner`` is accepted for parity with render_content and never mutated."""
    w, h = (max(8, int(v)) for v in size)
    img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    r = max(4, h // 3)
    grad = Image.linear_gradient('L').resize((w, h))
    top = Image.new('RGBA', (w, h), FACE_TOP + (250,))
    bottom = Image.new('RGBA', (w, h), FACE_BOTTOM + (250,))
    face = Image.composite(bottom, top, grad)
    mask = Image.new('L', (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=255)
    img.paste(face, (0, 0), mask)
    d = ImageDraw.Draw(img)
    # recessed: a dark inner lip on top, a warm rim below (light from above)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=r, outline=RIM + (200,), width=1)
    d.line((r, 1, w - r, 1), fill=(8, 5, 14, 200), width=max(1, h // 18))
    color, initial, state, step, _, _ = plaque_lines(ui)
    provider, remaining, suffix, right_color = quota_brief(ui)
    if not ui.get('sel_session'):
        state = '暂无任务'
    fp = int(font_px or max(10, round(h * .52)))
    font = _font(fp)
    small = _font(max(10, round(fp * .9)))
    gem_r = max(5, round(h * .26))
    gx = round(h * .35) + gem_r
    gem = ui3d.gem(gem_r, tuple(color[:3]), glow=False)
    img.alpha_composite(gem, (int(gx - gem.width / 2), int(h / 2 - gem.height / 2)))
    ty = h / 2
    if initial:
        mark = _font(max(9, round(gem_r * 1.15)))
        d.text((gx, ty), initial, font=mark, fill=(255, 255, 255, 235), anchor='mm',
               stroke_width=1, stroke_fill=(30, 20, 46, 200))
    tx = gx + gem_r + round(h * .28)
    gap, right_pad = max(6, round(h * .28)), round(h * .4)
    flow = '工作流·'+state
    essential = 'AI 限额'+(' · 旧' if '旧' in suffix else '')
    left_min = min(font.getlength(flow), max(font.getlength('工作流'),
                   w-tx-gap-right_pad-small.getlength(essential)))
    right_room = max(0, w-tx-gap-right_pad-left_min)
    mark = (' · '+suffix) if suffix else ''
    candidates = []
    if remaining is not None:
        candidates += [f'AI 限额 {provider} 5h 剩{remaining:.0f}%'+mark,
                       f'AI 限额 {provider}剩{remaining:.0f}%'+mark,
                       'AI 限额 '+provider+mark]
    candidates += ['AI 限额'+mark, essential, 'AI 限额']
    right = next((label for label in candidates if small.getlength(label) <= right_room),
                 _fit('AI 限额', small, right_room))
    rx = w-right_pad-small.getlength(right)
    room = max(0, rx-gap-tx)
    text = flow
    if step and font.getlength(flow+' · '+step[:2]+'…') <= room:
        text = flow+' · '+step
    fitted = _fit(text, font, room)
    if fitted.rstrip('… ').endswith('·'):
        fitted = fitted.rstrip('… ').rstrip('· ').rstrip()+'…'
    d.text((tx, ty), fitted, font=font, fill=INK, anchor='lm')
    d.text((rx, ty), right, font=small, fill=right_color, anchor='lm')
    split = max(1, min(w-1, round(rx-gap/2)))
    d.line((split, max(3, h//4), split, h-max(3, h//4)), fill=RIM+(65,))
    return img, [(0, 0, split, h, 'house_trace', 'trace'),
                 (split, 0, w-split, h, 'house_quota', 'overview')]
