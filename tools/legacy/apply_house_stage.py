"""Atomic integration of the house stage; no runtime/user data is changed."""
import hashlib
from pathlib import Path
import shutil
from datetime import datetime

p = Path(__file__).resolve().parents[1] / 'pet.py'
raw = p.read_bytes()
digest = hashlib.sha256(raw).digest()
s = raw.decode('utf-8').replace('\r\n', '\n')

def replace(old, new):
    global s
    if s.count(old) != 1:
        raise RuntimeError('Integration anchor changed: ' + old[:85])
    s = s.replace(old, new, 1)

replace('    def open_ai_panel(self):\n', '''    def house_enabled(self):
        return bool(getattr(self, '_house_on', False) and self.core_profile()
                    and getattr(self, '_scene_art', None) is not None)

    @staticmethod
    def _house_dashboard_size(scene_scale):
        if scene_scale < .68:
            return (280, 390)
        if scene_scale < .80:
            return (300, 420)
        if scene_scale < .94:
            return (320, 440)
        return (340, 470)

    def _limit_house_scale(self, requested, sw=None):
        """Fit the entire architecture, retaining physical dashboard font sizes."""
        if not self.house_enabled():
            return requested
        sw = sw or getattr(self, '_swing', None)
        if sw:
            cx = sw['scene_l'] + sw['scene_w']/2
            cy = sw['scene_t'] + sw['scene_h']/2
        else:
            saved = self.settings.get('swing_scene') or {}
            cx = saved.get('cx', getattr(self, 'x', 0))
            cy = saved.get('cy', getattr(self, 'fy', 0))
        area = work_area_at(cx, cy) or (0, 0, self.sw, self.sh)
        available = (area[2]-area[0]-16, area[3]-area[1]-16)
        ss = min(SWING_ART_SCALE[1], max(SWING_ART_SCALE[0], requested))
        while True:
            w, h = self._art_geo(ss)['size']
            if (w <= available[0] and h <= available[1]) or ss <= SWING_ART_SCALE[0]:
                return ss
            ss = max(SWING_ART_SCALE[0], round(ss-.02, 4))

    def _set_house_mode(self, enabled):
        self.close_action_card()
        self._house_on = bool(enabled)
        self.settings['house_mode'] = self._house_on
        self._book_open = False
        self._crystal_open = False
        panel = getattr(self, '_ai_work_panel', None)
        if panel is not None and not panel.closed:
            panel.close(change_state=False)
        self._chain_rect_local = self._chain_rect = None
        self._house_dash_cache = None
        self._house_pointer = (0.0, 0.0)
        sw = getattr(self, '_swing', None)
        if sw and sw.get('art'):
            self._art_regeo(sw, self._limit_house_scale(sw.get('scene_scale', 1.0), sw))
            self._art_fit_scene(sw)
            self._save_swing_scene()
        else:
            self.mount_swing()
            self.save_settings()
        self.last_interact = time.time()

    def open_swing_scene(self):
        self._set_house_mode(False)

    def open_ai_panel(self):
''')

replace('        # ---- AI 会话灯 ----\n', '''        # A complete house is the current core scene; standalone swing remains available.
        self._house_on = bool(self.settings.get('house_mode', True))
        self._house_renderer = None
        self._house_dash_cache = None
        self._house_pointer = self._house_view = (0.0, 0.0)
        self._house_pointer_at = self._house_view_at = 0.0

        # ---- AI 会话灯 ----
''')

replace('        if not self.ai_lights:\n            return\n        sessions = self._ai_sessions\n', '''        if self.house_enabled() or not self.ai_lights:
            return
        sessions = self._ai_sessions
''')
replace('        self._chain_rect_local = None\n        if not self.ai_lights:\n', '''        self._chain_rect_local = None
        if self.house_enabled():
            self._chain_rect = None
            return
        if not self.ai_lights:
''')

replace('        self.last_interact = time.time()\n        if kind == "swallow":\n', '''        self.last_interact = time.time()
        if kind == 'house_chat':
            self.open_chat()
            return
        if kind == 'house_trace':
            self.open_ai_panel()
            return
        if kind == 'house_quota':
            self.open_ai_panel()
            self._book_tab = 'overview'
            self._book_sel = ('agent', 'claude')
            return
        if kind == "swallow":
''')
replace('''        elif kind == "detail":
            panel = getattr(self, "_ai_work_panel", None)
            if panel is not None and not panel.closed:
                panel.show_detail(payload)
''', '''        elif kind == "detail":
            panel = getattr(self, "_ai_work_panel", None)
            if self.house_enabled() and (panel is None or panel.closed):
                self.open_ai_panel()
                if payload:
                    self._book_sel = ('sid', payload[0])
                sw = getattr(self, '_swing', None)
                if sw and sw.get('ui'):
                    self._sync_ai_panel(sw, sw['ui'])
                panel = getattr(self, '_ai_work_panel', None)
            if panel is not None and not panel.closed:
                panel.show_detail(payload)
''')

replace('''        return {"k": k, "ss": scene_scale, "O": (x0, y0),
                "size": (int(math.ceil(x1 - x0)), int(math.ceil(y1 - y0))),
                "sl": sl, "gtl": gtl, "anchor": anchor}
''', '''        geo = {"k": k, "ss": scene_scale, "O": (x0, y0),
               "size": (int(math.ceil(x1 - x0)), int(math.ceil(y1 - y0))),
               "sl": sl, "gtl": gtl, "anchor": anchor}
        if self.house_enabled():
            from house_scene import layout
            house = layout(geo['size'], scene_scale,
                           dashboard_size=self._house_dashboard_size(scene_scale))
            lx, ly = house.left_origin
            geo.update(art_size=geo['size'], house_layout=house,
                       O=(x0-lx, y0-ly), size=house.size)
        return geo
''')
replace('''        geo = self._art_geo(scene_scale)
        cw, ch = geo["size"]
        sw.update(geo=geo,''', '''        scene_scale = self._limit_house_scale(scene_scale, sw)
        geo = self._art_geo(scene_scale)
        cw, ch = geo["size"]
        sw.update(geo=geo,''')

replace('    def _push_swing_art(self, small):\n', '''    def _house_layers(self, sw):
        from house_scene import HouseRenderer
        renderer = getattr(self, '_house_renderer', None)
        if renderer is None:
            renderer = self._house_renderer = HouseRenderer(
                os.path.join(ASSETS, 'house', 'witch-house-v1.png'))
        now = time.time()
        dt = min(.12, max(0, now-getattr(self, '_house_view_at', now)))
        target = getattr(self, '_house_pointer', (0.0, 0.0))
        if now-getattr(self, '_house_pointer_at', 0) > 2.0:
            target = (0.0, 0.0)
        old = getattr(self, '_house_view', (0.0, 0.0))
        amount = 1-math.exp(-dt*5)
        view = tuple(a+(b-a)*amount for a,b in zip(old,target))
        self._house_view, self._house_view_at = view, now
        return renderer.render(sw['geo']['house_layout'], view)

    def _draw_house_dashboard(self, canvas, sw, ui, hits):
        from house_ai_ui import render_dashboard
        x, y, w, h = sw['geo']['house_layout'].dashboard
        key = repr((w, h, ui.get('sources'), ui.get('sel_key'), ui.get('sel_session'),
                    ui.get('quota'), int((ui.get('quota_age') or 0)/60),
                    int((ui.get('now') or time.time())/5), ui.get('mock'),
                    ui.get('badge')))
        cached = getattr(self, '_house_dash_cache', None)
        if not cached or cached[0] != key:
            image, local_hits = render_dashboard(self, ui, (w, h))
            cached = self._house_dash_cache = (key, image, local_hits)
        self._ac(canvas, cached[1], x, y)
        hits.extend((x+hx, y+hy, hw, hh, kind, payload)
                    for hx, hy, hw, hh, kind, payload in cached[2])

    def _push_swing_art(self, small):
''')
replace('''        canvas.paste((0, 0, 0, 0), (0, 0, cw, ch))
        L = sa.scaled(k)
''', '''        canvas.paste((0, 0, 0, 0), (0, 0, cw, ch))
        house_front = None
        if geo.get('house_layout'):
            house_back, house_front = self._house_layers(sw)
            canvas.alpha_composite(house_back)
        L = sa.scaled(k)
''')
replace('''        self._draw_props_art(canvas, sw, ui, hits)
        # 这一帧的特效/气泡/灯板/卷轴''', '''        if not geo.get('house_layout'):
            self._draw_props_art(canvas, sw, ui, hits)
        # 这一帧的特效/气泡/灯板/卷轴''')
replace('''        d2 = ImageDraw.Draw(canvas, "RGBA")
        if (ui.get("book_panel")''', '''        if house_front is not None:
            canvas.alpha_composite(house_front)
            self._draw_house_dashboard(canvas, sw, ui, hits)
        d2 = ImageDraw.Draw(canvas, "RGBA")
        if (ui.get("book_panel")''')
replace('''        ss = min(hi, max(lo, float(saved.get("scale", 1.0))))
        geo = self._art_geo(ss)
''', '''        ss = min(hi, max(lo, float(saved.get("scale", 1.0))))
        ss = self._limit_house_scale(ss)
        geo = self._art_geo(ss)
''')

replace('''        geo = sw["geo"]
        k, O = geo["k"], geo["O"]
        cb = self._scene_art.content_box()
        x0 = sw["scene_l"]''', '''        geo = sw["geo"]
        if geo.get('house_layout'):
            x0, y0 = sw['scene_l'], sw['scene_t']
            x1, y1 = x0+sw['scene_w'], y0+sw['scene_h']
            wa = work_area_at((x0+x1)/2, (y0+y1)/2)
            if not wa:
                return False
            nx = int(max(wa[0]+8, min(x0, wa[2]-sw['scene_w']-8)))
            ny = int(max(wa[1]+8, min(y0, wa[3]-sw['scene_h']-8)))
            if (nx, ny) == (x0, y0):
                return False
            sw.update(scene_l=nx, scene_t=ny, scene_cx=nx+sw['scene_w']//2,
                      rect=(nx, ny, nx+sw['scene_w'], ny+sw['scene_h']))
            return True
        k, O = geo["k"], geo["O"]
        cb = self._scene_art.content_box()
        x0 = sw["scene_l"]''')

replace('''    def on_hover(self, e):
        self.last_interact = time.time()
''', '''    def on_hover(self, e):
        self.last_interact = time.time()
        if self.house_enabled() and getattr(self, '_swing', None):
            bounds = self._swing['geo']['house_layout'].left_bounds
            hx, hy, hw, hh = bounds
            self._house_pointer = (max(-1.0, min(1.0, (e.x-hx)/max(1,hw)*2-1)),
                                   max(-1.0, min(1.0, (e.y-hy)/max(1,hh)*2-1)))
            self._house_pointer_at = time.time()
''')
replace('''                self._book_open = self._crystal_open = False
                return                       # 点空白处:先收面板
''', '''                self._book_open = self._crystal_open = False
                if not self.house_enabled():
                    return                   # standalone scene closes its panel first
''')

start = s.index('    def open_room_preview(self):\n')
end = s.index('    def _show_full_menu(self, x, y):\n', start)
s = s[:start]+'''    def open_room_preview(self):
        """Enter the integrated house while keeping the same swing and AI pipeline."""
        self._set_house_mode(True)

'''+s[end:]
replace('''        scenes.add_command(label="秋千", command=self.mount_swing)
        scenes.add_command(label="小屋 · 空间预览", command=self.open_room_preview)
''', '''        scenes.add_command(label="秋千", command=self.open_swing_scene)
        scenes.add_command(label="小屋 · Live2.5D", command=self.open_room_preview)
''')
replace('''                pystray.MenuItem("小屋 · 空间预览", lambda: self.post(self.open_room_preview)),''', '''                pystray.MenuItem("小屋 · Live2.5D", lambda: self.post(self.open_room_preview)),''')
replace('''                "book_panel": self._book_open,
                "ai_state": crystal_state(self._ai_sessions),''', '''                "book_panel": self._book_open,
                "house_mode": self.house_enabled(),
                "ai_state": crystal_state(self._ai_sessions),''')

# Compile first, recheck the source fingerprint, then write one atomic replacement.
compile(s, str(p), 'exec')
if hashlib.sha256(p.read_bytes()).digest() != digest:
    raise RuntimeError('Another writer changed pet.py; integration was not applied.')
backup = p.parent/'outputs'/'house-integration-backups'/datetime.now().strftime('%Y%m%d-%H%M%S')
backup.mkdir(parents=True, exist_ok=False)
shutil.copy2(p, backup/'pet.py')
tmp = p.with_suffix('.house.tmp')
tmp.write_bytes(s.replace('\n', '\r\n').encode('utf-8'))
tmp.replace(p)
print('House stage integrated atomically; source backup saved.')
