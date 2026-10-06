"""Readable magical-book UI. Receives snapshots; never scans files or calls AI."""
import math
import time
import tkinter as tk

from PIL import Image, ImageDraw, ImageTk

import ui3d

# Moon-house reading material: quiet ink-purple, ivory, restrained brass.
INK = (245, 239, 230, 255)
DIM = (181, 168, 199, 255)
GOLD = (214, 189, 148, 255)
ACCENT = (193, 154, 239, 255)
LINE = (101, 84, 115, 150)
SURFACE = (47, 35, 62, 255)
BG = '#251c35'
TEXT = '#f5efe6'
MUTED = '#b5a8c7'


def level_color(remaining):
    """Quota by what is left: green, yellow, then red (system colours)."""
    if remaining is None:
        return DIM
    return ((48, 209, 88, 255) if remaining >= 50 else
            (255, 214, 10, 255) if remaining >= 20 else (255, 69, 58, 255))


def _apple_font(px):
    from apple_ui import font
    return font(px, 600 if px >= 18 else 420)


def fit(text, font, width):
    """Pixel-measured truncation, leaving the full text in the detail view."""
    text = str(text or '').replace('\n', ' ')
    if font.getlength(text) <= width:
        return text
    while text and font.getlength(text + '…') > width:
        text = text[:-1]
    return text + '…' if text else ''


def panel_position(scene, size, area, gap=16, avoid=()):
    """Choose the least-overlapping side, then clamp to the monitor work area.
    ``avoid`` = other windows (x, y, w, h) to keep clear of, e.g. the open chat;
    the scene always counts most."""
    sx, sy, sw, sh = scene
    w, h = size
    left, top, right, bottom = area
    candidates = [(sx + sw + gap, sy), (sx - w - gap, sy),
                  (sx, sy + sh + gap), (sx, sy - h - gap)]
    for ax, ay, aw, ah in avoid:                  # also try beside the other window
        candidates += [(ax + aw + gap, ay), (ax - w - gap, ay)]
    bounded = [(int(max(left + 8, min(x, right - w - 8))),
                int(max(top + 8, min(y, bottom - h - 8)))) for x, y in candidates]

    def cover(pos, rect):
        x, y = pos
        rx, ry, rw, rh = rect
        return (max(0, min(x + w, rx + rw) - max(x, rx))
                * max(0, min(y + h, ry + rh) - max(y, ry)))

    def overlap(pos):
        return cover(pos, scene) * 4 + sum(cover(pos, r) for r in avoid)
    return min(bounded, key=overlap)


class ScaledFont:
    """A font rendered at ``scale`` whose measurements stay in 1x layout units."""
    def __init__(self, font, scale):
        self.font, self.scale = font, scale

    def getlength(self, text):
        return self.font.getlength(text) / self.scale


class ScaledDraw:
    """ImageDraw proxy: 1x coordinates in, crisp scale-x pixels out.  Lets the
    one readable layout serve every display scale without blurry upscaling."""
    def __init__(self, draw, scale):
        self.d, self.s = draw, scale

    def _xy(self, xy):
        flat = []
        for v in xy:
            flat.extend(v if isinstance(v, (tuple, list)) else (v,))
        return [v * self.s for v in flat]

    def _w(self, width):
        return max(1, round(width * self.s))

    def text(self, xy, text, font=None, **kw):
        self.d.text(tuple(self._xy(xy)), text, font=getattr(font, 'font', font), **kw)

    def rounded_rectangle(self, xy, radius=0, width=1, **kw):
        self.d.rounded_rectangle(self._xy(xy), radius=radius * self.s, width=self._w(width), **kw)

    def ellipse(self, xy, width=1, **kw):
        self.d.ellipse(self._xy(xy), width=self._w(width), **kw)

    def line(self, xy, width=1, **kw):
        self.d.line(self._xy(xy), width=self._w(width), **kw)

    def polygon(self, xy, **kw):
        self.d.polygon(self._xy(xy), **kw)


def trace_slice(rows, page, capacity):
    """Non-overlapping pages, including the oldest partial page and turn rows."""
    capacity = max(1, capacity)
    pages = max(1, math.ceil(len(rows) / capacity))
    page = max(0, min(int(page), pages - 1))
    end = len(rows) - page * capacity
    start = max(0, end - capacity)
    return page, pages, list(enumerate(rows[start:end], start))


def render_content(owner, ui, w, h, scale=1.0):
    """Readable book page; hit rectangles share the same logical layout.

    Main navigation precedes source selection. Workflow rows open as a whole;
    account values stay independent of the selected task and reading history.
    """
    from pet import trace_rows, CRYSTAL_COLORS, CRYSTAL_LABEL, ai_session_stale
    load_font = _apple_font
    from ai_quota import quota_accounts, quota_view
    page = Image.new('RGBA', (round(w*scale), round(h*scale)), (0, 0, 0, 0))
    sizes = (11, 12, 13, 14, 18, 26)
    if scale == 1:
        d = ImageDraw.Draw(page)
        fonts = {n: load_font(n) for n in sizes}
    else:
        d = ScaledDraw(ImageDraw.Draw(page), scale)
        fonts = {n: ScaledFont(load_font(round(n*scale)), scale) for n in sizes}
    hits = []
    now = ui.get('now') or time.time()
    ss, selected = ui.get('sel_session'), ui.get('sel_key')
    tab = ui.get('book_tab', 'overview')
    quota = quota_view(ui)
    compact = h < 430

    def text(x, y, value, size=13, color=INK, width=None):
        value = fit(value, fonts[size], width) if width is not None else str(value)
        d.text((x, y), value, font=fonts[size], fill=color)

    def control(rect, label, kind, payload=None, on=False, enabled=True):
        x, y, bw, bh = rect
        # Only the active main tab is filled. Secondary actions retain their
        # 32-unit target without competing with the task or quota numbers.
        if on:
            d.rounded_rectangle((x+2, y+2, x+bw-2, y+bh-2), radius=9,
                                fill=(75, 54, 96, 255) if kind == 'tab' else (57, 42, 73, 255))
        elif kind == 'close':
            d.ellipse((x+3, y+3, x+bw-3, y+bh-3), fill=(57, 42, 73, 255))
        tw = fonts[12].getlength(label)
        text(x+(bw-tw)/2, y+(bh-15)/2-1, label, 12,
             INK if on else DIM if enabled else (112, 103, 128, 255))
        if enabled:
            hits.append((x, y, bw, bh, kind, payload))

    text(20, 16, 'AI 限额' if tab == 'overview' else 'AI 工作流', 18)
    control((w-46, 10, 32, 32), '×', 'close')
    # One continuous segmented rail, rather than two separately outlined cards.
    tab_y, tab_w = 53, (w-36)/2
    d.rounded_rectangle((18, tab_y, w-18, tab_y+36), radius=11,
                        fill=(44, 44, 46, 255))
    control((18, tab_y, tab_w, 36), '工作流', 'tab', 'trace', tab == 'trace')
    control((18+tab_w, tab_y, tab_w, 36), 'AI 限额', 'tab', 'overview', tab == 'overview')
    sx, sy = 18, 98
    entries = ([(k, label, '') for k, label in quota_accounts(ui)] if tab == 'overview'
               else [(k, label, initial) for k, label, initial in (ui.get('sources') or [])
                     if any(s.get('agent') == k for s in (ui.get('sessions') or []))])
    if compact and tab == 'trace' and entries:
        idx = next((i for i, e in enumerate(entries) if e[0] == selected), 0)
        bw = (w-44)//2
        label = fit(entries[idx][1], fonts[12], bw-22)+(' ›' if len(entries)>1 else '')
        control((18, sy, bw, 32), label, 'chip', entries[(idx+1)%len(entries)][0],
                on=True, enabled=len(entries)>1)
        pool = [s for s in (ui.get('sessions') or []) if s.get('agent') == selected]
        current = next((i for i, s in enumerate(pool) if s.get('id') == (ss or {}).get('id')), 0)
        label = (f'会话 {current+1}/{len(pool)}'+(' ›' if len(pool)>1 else '')) if pool else '暂无会话'
        control((26+bw, sy, bw, 32), label, 'session',
                pool[(current+1)%len(pool)]['id'] if pool else None, enabled=len(pool)>1)
    else:
        for key, label, _ in entries:
            bw = min(w-36, max(68, int(fonts[12].getlength(label))+24))
            if sx+bw > w-18:
                sx, sy = 18, sy+36
            control((sx, sy, bw, 32), label,
                    'quota_provider' if tab == 'overview' else 'chip', key,
                    key == (quota['provider'] if tab == 'overview' else selected))
            badge = (ui.get('badge') or {}).get(key) if tab != 'overview' else None
            if badge:
                color = CRYSTAL_COLORS['error' if badge == 'error' else 'waiting']
                d.ellipse((sx+bw-8, sy+3, sx+bw-3, sy+8), fill=color+(255,))
            sx += bw+6
    if not entries:
        text(20, sy+8, '等待接入会话 · 记录不会被清空', 12, DIM, w-40)
    y = sy+48
    footer = h-(42 if compact and tab == 'overview' else 32)

    def state_color(session):
        state = 'offline' if (session or {}).get('stale') else (session or {}).get('state', 'idle')
        if session and not session.get('stale') and ai_session_stale(session, now):
            return (142, 142, 147), '久未更新'
        return CRYSTAL_COLORS.get(state, (142, 142, 147)), CRYSTAL_LABEL.get(state, state)

    def task_header():
        nonlocal y
        title = (ss or {}).get('title') or '暂无会话'
        color, label = state_color(ss)
        new_n = ui.get('new_n') or 0
        task_height = (72 if compact else 78) if new_n else 64
        text(20, y+3, title, 14, width=w-156 if new_n else w-40)
        if new_n and ss:
            control((w-134, y, 110, 32), f'新记录 +{new_n}', 'ack', ss['id'], on=True)
        state_y = y+(44 if new_n else 30)
        d.ellipse((20, state_y+4, 27, state_y+11), fill=color+(255,))
        text(34, state_y, label if ss else '尚未接入', 12, color+(255,))
        if ss:
            updated = ss.get('updated')
            if isinstance(updated, (int, float)) and updated > 0 and w >= 300:
                stamp = time.strftime('%H:%M', time.localtime(updated))
                text(113, state_y+1, ('更新 '+stamp) if w >= 350 else stamp, 11, DIM, w-231)
            muted = ss.get('id') in (getattr(owner, 'ai_mute_sess', set()) or set())
            control((w-106, state_y-8, 88, 32), '提醒已静音' if muted else '会话提醒开',
                    'mute_sess', ss['id'])
        d.line((18, y+task_height, w-18, y+task_height), fill=LINE)
        y += task_height+12

    messages = {'current': '已取得额度数据', 'partial': '部分周期未取得',
                'unknown': '样本时间未知' if quota.get('cycles') and any(
                    c.get('used') is not None for c in quota['cycles']) else '额度尚未接入',
                'stale': '样本已过期 · 显示最后已知值',
                'read_error': '读取失败 · 显示最后已知值'}
    if tab == 'overview':
        sampled = ('采样 '+time.strftime('%m-%d %H:%M', time.localtime(quota['t']/1000))) if quota.get('t') else '采样时间：未知'
        text(20, y, quota['label'], 14, GOLD, w-40)
        y += 28
        status = quota['status']
        if not compact and status != 'current':
            text(20, y, messages.get(status, '额度数据未知'), 12,
                 (246, 192, 123, 255) if status in ('stale', 'read_error') else DIM, w-40)
            y += 24
        card_h = (min(58, max(48, (footer-y-12)//2-4)) if compact
                  else min(104, max(76, (footer-y-32)//2-4)))
        for cycle in quota['cycles']:
            d.rounded_rectangle((18, y, w-18, y+card_h), radius=14,
                                fill=(44, 44, 46, 255))
            used, remaining = cycle['used'], cycle['remaining']
            col = (152, 152, 157, 255) if cycle.get('stale') else level_color(remaining)
            if compact:
                text(30, y+7, cycle['label'], 13)
                value = f'剩余 {remaining:.0f}% · 已用 {used:.0f}%' if used is not None else '数据未知'
                text(w-30-fonts[12].getlength(value), y+8, value, 12, col if used is not None else DIM)
            else:
                text(30, y+10, cycle['label'], 13)
                value = f'{remaining:.0f}%' if used is not None else '—'
                vx = w-30-fonts[26].getlength(value)
                text(vx, y+5, value, 26, INK if used is not None else DIM)
                text(vx-36, y+18, '剩余', 11, DIM)
                text(30, y+34, f'已用 {used:.0f}%' if used is not None else '数据未知', 11, DIM)
                d.rounded_rectangle((30, y+52, w-30, y+56), radius=2,
                                    fill=(72, 72, 74, 255))
                if used is not None and remaining > 0:
                    d.rounded_rectangle((30, y+52, 30+(w-60)*remaining/100, y+56), radius=2, fill=col)
            reset = cycle.get('reset')
            if reset and reset > now:
                reset_text = ('预计恢复 ' if cycle.get('estimated') else '恢复 ') + time.strftime(
                    '%m-%d %H:%M', time.localtime(reset))
                if cycle.get('estimated'):
                    reset_text += '（估算）'
            elif reset:
                reset_text = '恢复时刻已过 · 请取得新样本'
            else:
                reset_text = '恢复时间：尚未取得'
            if used is None:
                reset_text = '未取得该周期数据'
            text(30, y+card_h-22, reset_text, 11, DIM, w-60)
            y += card_h+8
        if not compact and y+16 < footer:
            text(20, y+1, sampled, 11, DIM, w-40)
    else:
        task_header()
        sessions = [s for s in (ui.get('sessions') or []) if s.get('agent') == selected]
        if len(sessions) > 1 and not compact:
            index = next((i for i, s in enumerate(sessions) if s.get('id') == (ss or {}).get('id')), 0)
            text(20, y+8, f'此来源 · 会话 {index+1}/{len(sessions)}', 12, DIM, w-150)
            control((w-122, y, 104, 32), '切换会话 ›', 'session', sessions[(index+1)%len(sessions)]['id'])
            y += 40
        if ss:
            snap = getattr(owner, '_trace_snap', None)
            rows = trace_rows({'actions': ss.get('actions') if snap is None else snap}, 48)
            row_h = 48 if compact else 54
            capacity = max(1, (footer-y-10)//row_h)
            paginated = len(rows) > capacity
            if paginated:
                capacity = max(1, (footer-y-40)//row_h)
                row_h = min(row_h, max(32, (footer-y-40)//capacity))
            p, pages, visible = trace_slice(rows, getattr(owner, '_trace_page', 0), capacity)
            owner._trace_page = p
            if not rows:
                text(20, y+16, '暂无可取得的工作轨迹', 13, DIM)
                text(20, y+42, '接入后显示真实步骤和结果摘要', 11, DIM)
            for absolute, row in visible:
                if row[0] == 'turn':
                    d.line((22, y+23, w-22, y+23), fill=LINE)
                    text(36, y+6, '新的一轮', 11, DIM)
                    y += row_h
                    continue
                _, timestamp, action, result, error, repeat = row
                color = CRYSTAL_COLORS['error'] if error else (142, 142, 147)
                d.ellipse((22, y+13, 29, y+20), fill=color+(255,))
                title = action+(f' ×{repeat}' if repeat > 1 else '')
                text(40, y+5, title, 13, color+(255,) if error else INK, w-94)
                second = result or ('记录于 '+time.strftime('%H:%M', time.localtime(timestamp))
                                    if timestamp else '无时间戳的历史记录')
                if row_h >= 43:
                    text(40, y+27, second, 11, DIM, w-94)
                ax, ay = w-29, y+19
                d.line((ax-4, ay-5, ax+1, ay, ax-4, ay+5), fill=DIM, width=1)
                hits.append((18, y, w-36, row_h, 'detail', (ss['id'], absolute, action, result)))
                d.line((40, y+row_h-2, w-22, y+row_h-2), fill=LINE)
                y += row_h
            if pages > 1:
                controls_y = footer-34
                control((18, controls_y, 84, 32), '‹ 更早', 'pageup', enabled=p < pages-1)
                count = f'{p+1} / {pages}'
                text((w-fonts[12].getlength(count))/2, controls_y+9, count, 12, DIM)
                control((w-102, controls_y, 84, 32), '较新 ›', 'pagedown', enabled=p > 0)
        else:
            text(20, y+18, '尚未选择可查看的会话', 13, DIM)
            text(20, y+44, '请选择上方来源和会话', 11, DIM, w-40)
    d.line((18, footer, w-18, footer), fill=LINE)
    if ui.get('mock'):
        freshness = '演示数据 · 不代表实际额度'
    elif tab == 'overview':
        freshness = (messages.get(quota['status'], '数据未知') if compact and quota['status'] != 'current' else quota['note'])
    elif ss and ss.get('stale'):
        freshness = '来源离线 · 显示最后记录'
    elif ss and ai_session_stale(ss, now):
        freshness = '久未更新 · 显示历史记录'
    elif ss:
        freshness = '真实步骤与结果 · 点击步骤展开全文'
    else:
        freshness = '暂无接入的工作记录'
    text(20, footer+9, freshness, 11, DIM, w-40)
    if compact and tab == 'overview':
        text(20, footer+24, sampled, 11, DIM, w-40)
    hits.append((0, 0, w, h, 'swallow', None))
    return page, hits


class AIWorkPanel:
    """Book sheet beside the character. Semantic updates only.  ``size`` is in
    1x layout units; ``scale`` (the chat window's UI scale) sets the physical
    size, so text is as large as the chat window's on high-DPI screens."""
    def __init__(self, pet, size=(400, 520), scale=1.0):
        self.pet = pet
        self.closed = False
        self.body_size = size
        self.scale = s = max(1.0, float(scale))
        self.pad = 12
        self.size = (round((size[0]+24)*s), round((size[1]+24)*s))
        self.dragged = False
        self._last_key = None
        self._hits = []
        self._focus = -1
        self.detail = None
        self.win = tk.Toplevel(pet.root)
        self.win.withdraw()
        self.win.title('小乔 · AI 工作')
        self.win.overrideredirect(True)
        self.win.configure(bg='#020304')
        self.win.attributes('-transparentcolor', '#020304')
        self.win.attributes('-topmost', bool(getattr(pet, 'topmost', True)))
        self.cv = tk.Canvas(self.win, width=self.size[0], height=self.size[1],
                            bg='#020304', bd=0, highlightthickness=0)
        self.cv.pack()
        self.cv.bind('<Button-1>', self._press)
        self.cv.bind('<B1-Motion>', self._drag)
        self.cv.bind('<ButtonRelease-1>', lambda e: setattr(self, '_drag_start', None))
        self.win.bind('<Escape>', lambda e: self._escape())
        self.win.bind('<Tab>', self._tab)
        self.win.bind('<Return>', self._activate)
        self.win.bind('<Prior>', lambda e: None if self.detail is not None else pet._ui_hit('pageup', None))
        self.win.bind('<Next>', lambda e: None if self.detail is not None else pet._ui_hit('pagedown', None))
        self.win.protocol('WM_DELETE_WINDOW', self.close)

    def resize(self, size, scale):
        """Fit another monitor in place, preserving the open text and selection."""
        scale = max(1.0, float(scale))
        if self.closed or (self.body_size == size and self.scale == scale):
            return
        self.body_size, self.scale = size, scale
        self.size = (round((size[0]+24)*scale), round((size[1]+24)*scale))
        self.cv.configure(width=self.size[0], height=self.size[1])
        self.win.geometry(f'{self.size[0]}x{self.size[1]}')
        self._last_key = None
        self._drag_start = None
        if self.detail is not None:
            fraction = self.detail_text.yview()[0]
            self.detail.place_configure(x=round((self.pad+8)*scale), y=round((self.pad+45)*scale),
                                        width=round((size[0]-16)*scale), height=round((size[1]-55)*scale))
            self.detail.configure(padx=round(20*scale), pady=round(18*scale))
            self.detail_text.configure(font=('Microsoft YaHei UI', -round(14*scale)))
            self.detail_text.yview_moveto(fraction)
            for child in self.detail.winfo_children():
                if isinstance(child, tk.Label):
                    child.configure(font=('Microsoft YaHei UI', -round(18*scale), 'bold'))
                if isinstance(child, tk.Frame):
                    for button in child.winfo_children():
                        if isinstance(button, tk.Button):
                            button.configure(font=('Microsoft YaHei UI', -round(13*scale)))

    def update(self, ui, scene, area, avoid=()):
        if self.closed:
            return
        if not self.dragged:
            x, y = panel_position(scene, self.size, area, avoid=avoid)
        else:
            left, top, right, bottom = area
            x = int(max(left+8, min(self.win.winfo_x(), right-self.size[0]-8)))
            y = int(max(top+8, min(self.win.winfo_y(), bottom-self.size[1]-8)))
        self.win.geometry(f'{self.size[0]}x{self.size[1]}+{x}+{y}')
        self.win.attributes('-topmost', bool(getattr(self.pet, 'topmost', True)))
        snapshot = dict(ui, book_rect=(self.pad, self.pad, *self.body_size), book_anim=1.0,
                        ui_scale=self.scale)
        # Ignore changing sub-second time and pendulum animation. This is a passive display.
        key = repr({k: int(v) if k in ('now', 'quota_age') and v is not None else v
                    for k, v in snapshot.items() if k not in ('prop_rect', 'tooltip', 'crystal_hover')})
        key += repr((getattr(self.pet, '_trace_page', 0), getattr(self.pet, '_session_page', 0),
                     getattr(self.pet, 'ai_mute_sess', set()), self._focus))
        if key != self._last_key:
            self._last_key = key
            image = Image.new('RGBA', self.size, (0, 0, 0, 0))
            self._hits = []
            self.pet._draw_book_v2(image, ImageDraw.Draw(image), {}, snapshot, self._hits)
            targets = [hit for hit in self._hits if hit[4] != 'swallow']
            if 0 <= self._focus < len(targets):
                x, y, w, h, _, _ = targets[self._focus]
                ImageDraw.Draw(image).rounded_rectangle((x, y, x+w, y+h), radius=10*self.scale,
                                                       outline=ACCENT, width=round(2*self.scale))
            flat = Image.new('RGB', image.size, '#020304')
            flat.paste(image, mask=image.getchannel('A'))
            self._photo = ImageTk.PhotoImage(flat, master=self.win)
            self.cv.delete('all')
            self.cv.create_image(0, 0, anchor='nw', image=self._photo)
        if self.win.state() == 'withdrawn':
            self.win.deiconify()
            self.win.lift()

    def _press(self, event):
        self.pet.last_interact = time.time()
        for x, y, w, h, kind, payload in self._hits:
            if kind != 'swallow' and x <= event.x < x+w and y <= event.y < y+h:
                self.pet._ui_hit(kind, payload)
                return
        if event.y < (self.pad+44)*self.scale:
            self._drag_start = (event.x_root, event.y_root, self.win.winfo_x(), self.win.winfo_y())

    def _drag(self, event):
        start = getattr(self, '_drag_start', None)
        if start:
            from pet import work_area_at, ChatBox, BOOK_W, BOOK_H
            mx, my, x, y = start
            area = work_area_at(event.x_root, event.y_root) or (0, 0, self.pet.sw, self.pet.sh)
            left, top, right, bottom = area
            u = ChatBox._layout(self.pet.sw, self.pet.sh)[0]
            body = (min(BOOK_W, int((right-left-16)/u)-24),
                    min(BOOK_H, int((bottom-top-16)/u)-24))
            self.resize(body, u)
            self._drag_start = start
            x = int(max(left+8, min(x+event.x_root-mx, right-self.size[0]-8)))
            y = int(max(top+8, min(y+event.y_root-my, bottom-self.size[1]-8)))
            self.win.geometry(f'+{x}+{y}')
            self.dragged = True

    def _tab(self, event):
        if self.detail is not None:
            return None
        targets = [hit for hit in self._hits if hit[4] != 'swallow']
        if targets:
            self._focus = (self._focus + (-1 if event.state & 1 else 1)) % len(targets)
            self._last_key = None
        return 'break'

    def _activate(self, event):
        if self.detail is not None:
            return None
        targets = [hit for hit in self._hits if hit[4] != 'swallow']
        if 0 <= self._focus < len(targets):
            self.pet._ui_hit(*targets[self._focus][4:])
        return 'break'

    def show_detail(self, payload):
        """All available content, scrollable and selectable, without truncation."""
        sid, absolute, action, result = payload
        self.close_detail()
        s = self.scale
        frame = self.detail = tk.Frame(self.win, bg=BG, padx=round(20*s), pady=round(18*s))
        frame.place(x=round((self.pad+8)*s), y=round((self.pad+45)*s),
                    width=round((self.body_size[0]-16)*s),
                    height=round((self.body_size[1]-55)*s))
        tk.Label(frame, text='步骤全文', font=('Noto Sans SC Medium', -round(18*s)),
                 bg=BG, fg=TEXT, anchor='w').pack(fill='x', pady=(0, 14))
        content = action+('\n\n结果摘要\n'+result if result else '')
        row = tk.Frame(frame, bg=BG)
        row.pack(fill='both', expand=True)
        self.detail_text = tk.Text(row, wrap='word', bg=BG, fg=TEXT, relief='flat',
                                   font=('Noto Sans SC', -round(14*s)), padx=4, pady=8,
                                   spacing1=4, spacing3=8, highlightthickness=0)
        self.detail_text.pack(side='left', fill='both', expand=True)
        scroll = tk.Scrollbar(row, command=self.detail_text.yview, bd=0, bg=BG)
        scroll.pack(side='right', fill='y')
        self.detail_text.configure(yscrollcommand=scroll.set)
        self.detail_text.insert('1.0', content)
        self.detail_text.configure(state='disabled')
        buttons = tk.Frame(frame, bg=BG)
        buttons.pack(fill='x', pady=(14, 0))
        def copy():
            self.pet._ui_hit('copy', (action, result))
            self.copy_button.configure(text='已复制')
        self.copy_button = tk.Button(buttons, text='复制全文', command=copy, relief='flat',
                                    bg='#695085', fg='#ffffff', activebackground='#82649e',
                                    font=('Noto Sans SC', -round(13*s)), padx=14, pady=9)
        self.copy_button.pack(side='left')
        tk.Button(buttons, text='返回轨迹', command=self.close_detail, relief='flat',
                  bg='#2c2c2e', fg=TEXT, font=('Noto Sans SC', -round(13*s)),
                  padx=14, pady=9).pack(side='right')
        self.detail_text.focus_set()

    def close_detail(self):
        if self.detail is not None:
            self.detail.destroy()
            self.detail = None

    def _escape(self):
        if self.detail is not None:
            self.close_detail()
        else:
            self.close()
        return 'break'

    def close(self, change_state=True):
        if self.closed:
            return
        self.closed = True
        if change_state:
            self.pet._book_open = False
        self.win.destroy()
