"""The studio's AI status capsule (Dynamic-Island-like), rendered from the
existing AI UI snapshot only.

A black pill under the stand: a live status glyph (running spins, waiting
pulses, done shows a check, error an exclamation, idle a quiet dot), the
source and state, the latest real step, and a ring for the account's 5-hour
quota.  Two click zones: the status opens the work trace (``house_trace``),
the ring opens quota (``house_quota``).  Honesty rules are the nameplate's:
unknown quota draws an empty ring with no number, stale samples are dimmed.

Typography uses Noto Sans SC (variable weight) when installed, else the
pet's default font.  No model calls, no file reads beyond fonts.
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Apple system colours (dark appearance)
PURPLE = (191, 90, 242)
ORANGE = (255, 159, 10)
RED = (255, 69, 58)
GREEN = (48, 209, 88)
YELLOW = (255, 214, 10)
GRAY = (142, 142, 147)
INK = (255, 255, 255, 236)
SECOND = (235, 235, 245, 150)
BODY = (10, 10, 13, 246)
EDGE = (255, 255, 255, 30)
NOTO = Path("C:/Windows/Fonts/NotoSansSC-VF.ttf")


@lru_cache(maxsize=16)
def font(px, weight=420):
    """Noto Sans SC at a variable weight (Apple-like CJK); pet font as fallback."""
    px = max(8, int(px))
    if NOTO.exists():
        try:
            f = ImageFont.truetype(str(NOTO), px)
            try:
                f.set_variation_by_axes([weight])
            except Exception:
                pass
            return f
        except OSError:
            pass
    from pet import load_font
    return load_font(px)


def _fit(text, f, width):
    text = str(text or '').replace('\n', ' ')
    if width <= 0:
        return ''
    if f.getlength(text) <= width:
        return text
    while text and f.getlength(text + '…') > width:
        text = text[:-1]
    return text + '…' if text else ''


KIND_COLOR = {'running': PURPLE, 'waiting': ORANGE, 'done': GREEN, 'error': RED, 'idle': GRAY}


def capsule_state(ui, now):
    """(kind, source, state, step); kind in running/waiting/done/error/idle."""
    from house_ai_ui import plaque_lines
    from pet import ai_session_stale
    session = ui.get('sel_session') or None
    _, initial, state, step, _, _ = plaque_lines(ui)
    if not session:
        return 'idle', 'AI', '暂无任务', ''
    kind = session.get('state') or 'idle'
    if session.get('stale') or ai_session_stale(session, now):
        kind = 'idle'
    source = next((label for key, label, _ in (ui.get('sources') or [])
                   if key == ui.get('sel_key')), None) or str(session.get('agent') or 'AI')
    return (kind if kind in ('running', 'waiting', 'done', 'error') else 'idle'), source, state, step


def _ring(d, cx, cy, r, w, frac, color, track=(255, 255, 255, 46)):
    box = (cx - r, cy - r, cx + r, cy + r)
    d.arc(box, 0, 360, fill=track, width=max(1, int(w)))
    if frac is not None and frac > 0:
        d.arc(box, -90, -90 + 360 * min(1.0, frac), fill=color, width=max(1, int(w)))


def layout(ui, h, max_w, now):
    """Measure the capsule: returns (width, parts) for render_capsule."""
    from house_ai_ui import quota_brief
    kind, source, state, step = capsule_state(ui, now)
    provider, remaining, suffix, _ = quota_brief(ui)
    ft, fs = font(round(h * .42), 600), font(round(h * .4), 400)
    pad, glyph = round(h * .38), round(h * .3)
    ring_r = round(h * .27)
    pct = f'{remaining:.0f}%' if remaining is not None else ''
    fp = font(round(h * .36), 560)
    right = pad + ring_r * 2 + (round(h * .2) + fp.getlength(pct) if pct else 0) + pad
    left = pad + glyph * 2 + round(h * .3)
    gap = round(h * .28)
    title_w = ft.getlength(source) + gap + ft.getlength(state)
    step_w = fs.getlength(step) if step else 0
    want = left + title_w + (gap + min(step_w, 12 * h) if step else 0) + right
    w = int(min(max_w, max(want, h * 6)))
    return w, dict(kind=kind, source=source, state=state, step=step, pct=pct, remaining=remaining,
                   suffix=suffix, provider=provider, ft=ft, fs=fs, fp=fp, pad=pad,
                   glyph=glyph, ring_r=ring_r, left=left, right=right, gap=gap)


def render_capsule(ui, h, max_w, now, hover=None):
    """Black pill with live glyph, title, step and quota ring.
    Returns (image, hits, split_x) — hits in capsule-local pixels."""
    h = max(16, int(h))
    w, L = layout(ui, h, max_w, now)
    SS = 2
    big = Image.new('RGBA', (w * SS, h * SS), (0, 0, 0, 0))
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), radius=h * SS // 2,
                                          fill=BODY, outline=EDGE, width=SS)
    img = big.resize((w, h), Image.LANCZOS)
    d = ImageDraw.Draw(img)
    split = w - L['right'] + L['pad'] // 2
    if hover in ('house_trace', 'house_quota'):
        x0, x1 = (0, split) if hover == 'house_trace' else (split, w)
        lit = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        m = Image.new('L', (w * SS, h * SS), 0)
        ImageDraw.Draw(m).rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), radius=h * SS // 2, fill=255)
        m = m.resize((w, h), Image.LANCZOS)
        zone = Image.new('L', (w, h), 0)
        ImageDraw.Draw(zone).rectangle((x0, 0, x1, h), fill=255)
        from PIL import ImageChops
        lit.paste((255, 255, 255, 22), (0, 0, w, h), ImageChops.multiply(m, zone))
        img.alpha_composite(lit)
    cy = h / 2
    # glyph
    gx = L['pad'] + L['glyph']
    _glyph(img, gx, cy, L['glyph'], L['kind'], now)
    # title + step
    tx = L['left']
    room = split - tx - L['pad'] // 2
    # source in white, the state in its system colour, the latest step quieter
    source = _fit(L['source'], L['ft'], room)
    d.text((tx, cy), source, font=L['ft'], fill=INK, anchor='lm')
    used = L['ft'].getlength(source) + L['gap']
    state = _fit(L['state'], L['ft'], room - used)
    if state:
        d.text((tx + used, cy), state, font=L['ft'], fill=KIND_COLOR[L['kind']] + (255,)
               if L['kind'] != 'idle' else SECOND, anchor='lm')
        used += L['ft'].getlength(state)
    if L['step'] and room - used - L['gap'] > h * 1.2:
        d.text((tx + used + L['gap'], cy), _fit(L['step'], L['fs'], room - used - L['gap']),
               font=L['fs'], fill=SECOND, anchor='lm')
    # quota ring (+ number)
    rr = L['ring_r']
    rx = w - L['pad'] - rr
    if L['pct']:
        rx -= round(h * .2) + L['fp'].getlength(L['pct'])
    stale = '旧' in (L['suffix'] or '')
    rem = L['remaining']
    color = (GRAY if stale or rem is None else GREEN if rem >= 50 else YELLOW if rem >= 20 else RED)
    ring = Image.new('RGBA', (rr * 2 * 4 + 8, rr * 2 * 4 + 8), (0, 0, 0, 0))
    _ring(ImageDraw.Draw(ring), ring.width / 2, ring.height / 2, rr * 4 - 4, max(4, rr * 1.1),
          None if rem is None else rem / 100, color + (255,))
    ring = ring.resize((rr * 2 + 2, rr * 2 + 2), Image.LANCZOS)
    img.alpha_composite(ring, (int(rx - rr - 1), int(cy - rr - 1)))
    if L['pct']:
        d.text((rx + rr + round(h * .2), cy), L['pct'], font=L['fp'],
               fill=(SECOND if stale else INK), anchor='lm')
    hits = [(0, 0, split, h, 'house_trace', 'trace'), (split, 0, w - split, h, 'house_quota', 'overview')]
    return img, hits, split


def _glyph(img, cx, cy, r, kind, now):
    d = ImageDraw.Draw(img)
    if kind == 'running':                       # a calm spinner: 270° arc turning
        S = 4
        g = Image.new('RGBA', (r * 2 * S + 8, r * 2 * S + 8), (0, 0, 0, 0))
        a0 = (now * 300) % 360
        c = g.width / 2
        dg = ImageDraw.Draw(g)
        dg.arc((c - r * S, c - r * S, c + r * S, c + r * S), 0, 360, fill=PURPLE + (60,), width=int(r * S * .34))
        dg.arc((c - r * S, c - r * S, c + r * S, c + r * S), a0, a0 + 250, fill=PURPLE + (255,), width=int(r * S * .34))
        g = g.resize((r * 2 + 2, r * 2 + 2), Image.LANCZOS)
        img.alpha_composite(g, (int(cx - r - 1), int(cy - r - 1)))
    elif kind == 'waiting':                     # pulsing dot: it is waiting for you
        p = .5 - .5 * math.cos(now * math.tau / 1.3)
        rr = r * (1.0 + .55 * p)
        d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=ORANGE + (int(70 * (1 - p)),))
        d.ellipse((cx - r * .7, cy - r * .7, cx + r * .7, cy + r * .7), fill=ORANGE + (255,))
    elif kind == 'done':
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=GREEN + (255,))
        d.line([(cx - r * .45, cy + r * .02), (cx - r * .1, cy + r * .38), (cx + r * .5, cy - r * .35)],
               fill=(255, 255, 255, 255), width=max(1, int(r * .3)), joint='curve')
    elif kind == 'error':
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=RED + (255,))
        d.line([(cx, cy - r * .5), (cx, cy + r * .12)], fill=(255, 255, 255, 255), width=max(1, int(r * .28)))
        d.ellipse((cx - r * .15, cy + r * .32, cx + r * .15, cy + r * .6), fill=(255, 255, 255, 255))
    else:
        d.ellipse((cx - r * .55, cy - r * .55, cx + r * .55, cy + r * .55), fill=GRAY + (255,))
