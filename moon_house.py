"""Open moon house using generated transparent architecture and the original rig.

This is depth-warped 2.5D artwork, not a freely rotating 3D character model.
The reading surface is fixed; only the architecture gets a small depth warp.
"""
from collections import OrderedDict
import json
from pathlib import Path
import time
from PIL import Image
from house_scene import layout as base_layout, _solid


def load_meta(asset_dir):
    return json.loads((Path(asset_dir)/'moon-house.json').read_text(encoding='utf-8'))


def layout(k, swing_box, room):
    return base_layout(k, swing_box, room)


def board_rect(L, room):
    x, y, w, h = room['board']
    return (L.room_origin[0]+round(x*L.scale), L.room_origin[1]+round(y*L.scale),
            round(w*L.scale), round(h*L.scale))


class MoonRenderer:
    def __init__(self, asset_dir):
        self.meta = load_meta(asset_dir)
        self.source = Image.open(Path(asset_dir)/self.meta['asset']).convert('RGBA')
        if self.source.size != tuple(self.meta['size']):
            raise ValueError('Moon house dimensions do not match metadata')
        self._frames = OrderedDict()
        self._scaled = OrderedDict()
        self.last_view = (0.0, 0.0)
        self.min_interval = .12
        self._last_at = 0
        self._last = None

    def render(self, L, view=(0, 0)):
        view = tuple(round(max(-1, min(1, v))*8)/8 for v in view)
        geo = (L.size, L.room_size, L.room_origin)
        key = (geo, view)
        now = time.monotonic()
        if self._last and self._last[0][0] == geo and now-self._last_at < self.min_interval:
            self.last_view = self._last[0][1]
            return self._last[1]
        if key not in self._frames:
            if L.room_size not in self._scaled:
                self._scaled.clear()
                self._scaled[L.room_size] = self.source.convert('RGBa').resize(L.room_size, Image.Resampling.LANCZOS)
                self._frames.clear()
            im = self._scaled[L.room_size]
            if view != (0.0, 0.0):
                w, h = im.size
                nx, ny = 20, 20
                def point(x, y):
                    ax, ay = x/L.scale, y/L.scale
                    # Board and swing hanging line are stable; depth increases
                    # toward the rear posts, with the foreground floor opposite.
                    if ax >= self.meta['board'][0]-30:
                        shift = 0.0
                    elif ay < 310:
                        shift = 0.0
                    else:
                        depth = max(0, min(1, (900-ay)/600))
                        shift = (-2+7*depth)*L.scale
                    return x-view[0]*shift, y-view[1]*shift*.4
                mesh = []
                for j in range(ny):
                    y0, y1 = round(h*j/ny), round(h*(j+1)/ny)
                    for i in range(nx):
                        x0, x1 = round(w*i/nx), round(w*(i+1)/nx)
                        q = (point(x0,y0),point(x0,y1),point(x1,y1),point(x1,y0))
                        mesh.append(((x0,y0,x1,y1),tuple(v for p in q for v in p)))
                im = im.transform(im.size, Image.Transform.MESH, mesh, Image.Resampling.BILINEAR)
                # resampling would still blur the board by a fraction of a pixel:
                # put the reading face back exactly as drawn
                bx = max(0, int((self.meta['board'][0]-30)*L.scale))
                im.paste(self._scaled[L.room_size].crop((bx, 0, im.width, im.height)), (bx, 0))
            back = Image.new('RGBA', L.size)
            back.alpha_composite(_solid(im.convert('RGBA')), L.room_origin)
            # Mesh interpolation can move a cell that straddles the boundary.
            # Restore the exact fixed reading face after the architectural warp.
            bx, by, bw, bh = self.meta['board']
            box = tuple(round(v*L.scale) for v in (bx,by,bx+bw,by+bh))
            fixed = self._scaled[L.room_size].crop(box).convert('RGBA')
            back.paste(fixed, (L.room_origin[0]+box[0], L.room_origin[1]+box[1]))
            # Empty foreground sentinel keeps existing host overlay ordering.
            result = (back, Image.new('RGBA', (1,1)), (0,0))
            self._frames[key] = result
            while len(self._frames) > 6:
                self._frames.popitem(last=False)
        result = self._frames[key]
        self.last_view = view
        self._last_at = now
        self._last = key, result
        return result


def draw_board(owner, canvas, sw, ui, hits):
    from moon_board import render
    from pet import ChatBox
    L = sw['geo']['house_layout']
    room = owner._house_room()
    x, y, w, h = board_rect(L, room)
    u = ChatBox._layout(owner.sw, owner.sh)[0]
    # Never shrink glyphs with character zoom. Geometry is clamped at setup.
    key = (w, h, u, repr((ui.get('sel_session'), ui.get('quota'), ui.get('codex_quota'),
           ui.get('sources'), ui.get('sessions'), ui.get('mock'), ui.get('codex_quota_error'))),
           int((ui.get('now') or time.time())/15))
    cached = getattr(owner, '_moon_board_cache', None)
    if cached is None or cached[0] != key:
        im, local = render(ui, (w,h), u)
        owner._moon_board_cache = key, im, local
    else:
        _, im, local = cached
    canvas.alpha_composite(im, (x,y))
    hits.extend((x+hx,y+hy,hw,hh,kind,payload) for hx,hy,hw,hh,kind,payload in local)
    # Swallow only actual opaque book space; open house gaps remain click-through.
    hits.append((x,y,w,h,'swallow',None))


def react(owner, ui):
    """Quiet, debounced linkage to genuine session transitions. No speech or AI.
    Startup and task switching only establish a baseline; sleep/mute respected.
    """
    from moon_board import workflow
    f = workflow(ui)
    s = f['session']
    key = (s.get('id'), s.get('state'), f['completed'])
    previous = getattr(owner, '_moon_reaction', None)
    owner._moon_reaction = key
    if (not s or f['stale'] or getattr(owner, '_nap_on_swing', False)
            or getattr(owner, 'ui_reduced_anim', False)
            or s.get('agent') in (getattr(owner, 'ai_mute_sources', ()) or ())
            or s.get('id') in (getattr(owner, 'ai_mute_sess', ()) or ())):
        return
    now = ui.get('now') or time.time()
    if previous is None or previous[0] != key[0] or previous == key:
        return
    if now-getattr(owner, '_moon_reacted_at', 0) < 8:
        return
    owner._moon_reacted_at = now
    if s.get('state') in ('waiting', 'error'):
        owner._moon_look_until = now+4
        owner.play_emotion('curious' if s['state'] == 'waiting' else 'worry', 2.2)
    elif s.get('state') == 'done' or key[2] > previous[2]:
        owner.play_emotion('proud', 1.8)
        # Only a tiny existing hat spring impulse; keep grip/seat/face rigid.
        lf = getattr(owner, 'life', None)
        if lf is not None:
            lf.hat_rot.impulse(.014)
