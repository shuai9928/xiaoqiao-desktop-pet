# -*- coding: utf-8 -*-
"""秋千场景原画的运行时:读 assets/scene/ 的分层、按缩放取图、前后荡透视。

分层由 make_scene_layers.py 从 assets/scene_src.png 拆出(原画 1254×1254
画布坐标):static 横杆 / swing 绳+坐垫+她 / book 魔法书 / crystal 水晶灯。

前后荡不是整体等比缩放:绳头挂在横杆上不动,越往下(离挂点越远)越吃
摆角 —— 座椅随 cosθ 上抬、随透视变大/变小,她和绳一起跟着走,手永远
握在绳上。挂点线以上一律不动(帽尖压着横杆,动了会和横杆错开)。

只依赖 PIL;不碰 Tk / Win32,方便无窗口测试。
"""
import json
import math
import os
from collections import OrderedDict

from PIL import Image, ImageDraw, ImageFilter

LAYERS = ("static", "swing", "book", "crystal")


class SceneArt:
    def __init__(self, folder):
        with open(os.path.join(folder, "meta.json"), encoding="utf-8") as f:
            meta = json.load(f)
        self.meta = meta
        self.size = tuple(meta["size"])
        self.bbox = {n: tuple(meta["bbox"][n]) for n in LAYERS}
        self.girl_bbox = tuple(meta["girl_bbox"])
        self.pivot_l = tuple(meta["pivot_l"])
        self.pivot_r = tuple(meta["pivot_r"])
        self.seat_y = float(meta["seat_line_y"])
        # 道具在原画里的几何(水晶内芯中心/金环半径,书的包围盒)
        self.crystal_c = tuple(meta.get("crystal_c", (1116, 852)))
        self.crystal_r = float(meta.get("crystal_r", 108))
        # 只留各层包围盒里的部分,省内存也省缩放时间
        self.src = {}
        for n in LAYERS:
            im = Image.open(os.path.join(folder, n + ".png")).convert("RGBA")
            self.src[n] = im.crop(self.bbox[n])
        # 工作室场景用的秋千层(tools/build_studio_layers.py:去掉横杆残片、坐垫下的
        # 垂饰和飘散的小星点);和 swing 同一个包围盒,偏移完全一致。没有就不启用工作室
        self.studio = False
        studio = os.path.join(folder, "swing_studio.png")
        if os.path.exists(studio):
            im = Image.open(studio).convert("RGBA")
            if im.size == self.size:
                self.bbox["swing_studio"] = self.bbox["swing"]
                self.src["swing_studio"] = im.crop(self.bbox["swing"])
                self.studio = True
        self._scaled_k = None
        self._scaled = None

    @classmethod
    def load(cls, folder):
        """素材不全(没拆过层、旧版本)就返回 None:桌宠照旧画程序秋千。"""
        try:
            if not os.path.exists(os.path.join(folder, "meta.json")):
                return None
            return cls(folder)
        except Exception:
            return None

    # ---- 缩放 ----
    def content_box(self):
        """所有分层的并集包围盒(原画坐标)。"""
        xs0, ys0, xs1, ys1 = zip(*(self.bbox[n] for n in LAYERS))
        return min(xs0), min(ys0), max(xs1), max(ys1)

    def scaled(self, k):
        """按 k(屏幕 px / 原画 px)缩放好的各层:{名字: (图, (原画x*k, 原画y*k))}。
        k 量化到 0.002,只留最近一档(滚轮缩放时才重建)。"""
        kq = round(k / 0.002) * 0.002
        if self._scaled is not None and self._scaled_k == kq:
            return self._scaled
        out = {}
        for n, im in self.src.items():
            x0, y0 = self.bbox[n][:2]
            w = max(1, round(im.width * kq))
            h = max(1, round(im.height * kq))
            out[n] = (im.resize((w, h), Image.LANCZOS), (x0 * kq, y0 * kq))
        self._scaled_k, self._scaled = kq, out
        return out

    # ---- 前后荡 ----
    def swing_geometry(self, k):
        """缩放后、以原画 (0,0) 为原点的挂点线与座椅线。"""
        (x0, y0), (x1, y1) = self.pivot_l, self.pivot_r
        return {"x0": x0 * k, "y0": y0 * k, "x1": x1 * k, "y1": y1 * k,
                "cx": (x0 + x1) / 2 * k, "seat": self.seat_y * k}

    @staticmethod
    def _pivot_y(g, x):
        return g["y0"] + (g["y1"] - g["y0"]) * (x - g["x0"]) / (g["x1"] - g["x0"])

    @classmethod
    def fwd(cls, g, x, y, theta, persp):
        """原画缩放坐标 → 荡起来以后的位置。d = 离挂点线的垂距(沿绳方向)。"""
        L = cls._pivot_y(g, x)
        d = y - L
        if d <= 0:
            return x, y
        R = max(1.0, g["seat"] - cls._pivot_y(g, g["cx"]))
        s = 1.0 + persp * (d / R) * math.sin(theta)
        return g["cx"] + (x - g["cx"]) * s, L + d * math.cos(theta) * s

    @classmethod
    def inv(cls, g, xo, yo, theta, persp):
        """fwd 的逆(不动点迭代,8 次足够收敛到亚像素)。"""
        R = max(1.0, g["seat"] - cls._pivot_y(g, g["cx"]))
        x, d = xo, yo - cls._pivot_y(g, xo)
        if d <= 0:
            return xo, yo
        c, sn = math.cos(theta), math.sin(theta)
        for _ in range(8):
            s = 1.0 + persp * (d / R) * sn
            x = g["cx"] + (xo - g["cx"]) / s
            d = max(0.0, (yo - cls._pivot_y(g, x)) / (c * s))
        return x, cls._pivot_y(g, x) + d

    @staticmethod
    def _smooth(lo, hi, value):
        t = max(0.0, min(1.0, (value - lo) / (hi - lo)))
        return t * t * (3.0 - 2.0 * t)

    def portrait_displacement(self, x, y, k, view):
        """A continuous, restrained depth field in scaled ORIGINAL coordinates.

        Only the inner hat brim and hair participate. Rope corridors, the raised
        hand, mounting line, torso, lap and cushion have zero displacement. The
        enlarged face region receives one rigid translation, never local shear.
        """
        vx, vy = (max(-1.0, min(1.0, float(v))) for v in view)
        gx0, gy0, gx1, gy1 = self.girl_bbox
        gw, gh = gx1 - gx0, gy1 - gy0
        # Leave a full mesh-cell buffer around the grip and rope corridors.
        # Pinning just their exact coordinates still lets adjacent moving
        # vertices interpolate a small displacement into the contact pixels.
        gate_x = self._smooth(gx0 + gw * .18, gx0 + gw * .235, x)
        gate_x *= 1.0 - self._smooth(gx0 + gw * .62, gx0 + gw * .69, x)
        gate_y = self._smooth(gy0 + gh * .104, gy0 + gh * .171, y)
        gate_y *= 1.0 - self._smooth(gy0 + gh * .425, gy0 + gh * .533, y)
        gate = gate_x * gate_y
        dx = 3.8 * k * vx * gate
        dy = 1.6 * k * vy * gate
        face = self.meta.get("face") or {}
        eyes = [face.get("eye_l", (610, 520)), face.get("eye_r", (737, 554))]
        mouth = face.get("mouth", (658, 582))
        scale = gw / 906.0
        x0, x1 = min(p[0] for p in eyes) - 105 * scale, max(p[0] for p in eyes) + 110 * scale
        y0, y1 = min(p[1] for p in eyes) - 85 * scale, mouth[1] + 81 * scale
        distance = max(x0 - x, x - x1, y0 - y, y - y1, 0.0)
        face_weight = 1.0 - self._smooth(0.0, 55.0 * scale, distance)
        dx = dx * (1.0 - face_weight) + .6 * k * vx * face_weight
        dy = dy * (1.0 - face_weight) + .3 * k * vy * face_weight
        return dx, dy


    # ---- 秋千上的 2.5D:视线 / 帽子弹簧 / 发梢 / 呼吸 / 受光 ----
    # 原来的 portrait_view 只跟摆角走、最大 3.8 原画 px(屏幕上约 1px),帽尖
    # 还整个钉死 —— 看着就是一张贴图。这里换成真正的分层视差:她转头时脸整体
    # 平移、头发少一点、帽檐和帽尖多一点(越靠前越多);帽子绕帽基跟着弹簧摆、
    # 发梢滞后、胸口呼吸。绳、握绳的手、挂点、臀垫、膝上的手、腿脚一律钉住
    # (和 portrait_view 同一批接触点),手永远握在绳上。
    HAT_BASE = (705, 330)            # 帽子绕着转的点(原画):帽冠压在头顶处
    CHEST = (640, 720)

    def set_rig(self, regions):
        """config.json 的 rig 多边形(相对 girl_bbox 裁图)→ 原画坐标的软遮罩。"""
        n = 128
        self._rig = {}
        for name in ("hat", "hair", "face", "body"):
            pts = (regions or {}).get(name)
            if not pts:
                continue
            m = Image.new("L", (n, n), 0)
            ImageDraw.Draw(m).polygon([(x * (n - 1), y * (n - 1)) for x, y in pts], fill=255)
            self._rig[name] = m.filter(ImageFilter.GaussianBlur(3.0)).load()
        self._rig_n = n

    def _rig_w(self, name, x, y):
        px = getattr(self, "_rig", {}).get(name)
        if px is None:
            return 0.0
        gx0, gy0, gx1, gy1 = self.girl_bbox
        u, v = (x - gx0) / (gx1 - gx0), (y - gy0) / (gy1 - gy0)
        if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
            return 0.0
        n = self._rig_n - 1
        return px[int(u * n), int(v * n)] / 255.0

    def contact_gate(self, x, y):
        """0 = 钉死(接触结构),1 = 可以动。软过渡,网格插值也不会把位移带进接触处。"""
        cl = 325.97 + 0.07198 * y + 1.12e-5 * y * y          # 左绳中心线
        cr = 1053.42 - 0.15167 * y + 1.08e-5 * y * y         # 右绳中心线
        g = self._smooth(30.0, 72.0, abs(x - cl)) * self._smooth(30.0, 72.0, abs(x - cr))

        def off_rect(x0, y0, x1, y1, m):
            return self._smooth(0.0, m, max(x0 - x, x - x1, y0 - y, y - y1, 0.0))
        g *= off_rect(325, 555, 445, 705, 46)                # 握绳的手和腕
        g *= 1.0 - self._smooth(760.0, 830.0, y)             # 膝/坐垫/腿脚
        g *= self._smooth(30.0, 58.0, y)                     # 顶上挂环
        return g

    def pose_displacement(self, x, y, pose):
        """原画坐标 (x, y) 在这个姿态下的位移(原画 px)。pose 的键:
        look=(lx, ly) 视线 -1..1;hat=(弧度, 横移 px);hair=横移 px;breath -1..1。"""
        gate = self.contact_gate(x, y)
        if gate <= 0.0:
            return 0.0, 0.0
        lx, ly = pose.get("look", (0.0, 0.0))
        wf = self._rig_w("face", x, y)
        wb = self._rig_w("body", x, y) * (1 - wf)
        wh = self._rig_w("hair", x, y) * (1 - wf) * (1 - wb)
        wt = self._rig_w("hat", x, y) * (1 - wf) * (1 - wb) * (1 - wh)
        bx, by = self.HAT_BASE
        # 视线:越靠近观众的部位挪得越多(帽檐 > 脸 > 头发 > 身体)
        lift = max(0.0, min(1.0, (by - y) / 260.0))          # 帽尖更靠前
        # 幅度对齐旧立绘的头部跟随(旧图脸约 6 屏幕 px):脸 13、发 9、帽 18~30 原画 px
        dx = lx * (13.0 * wf + 9.0 * wh + (18.0 + 12.0 * lift) * wt + 3.0 * wb)
        dy = ly * (5.5 * wf + 4.0 * wh + 8.0 * wt + 1.5 * wb)
        # 帽子:绕帽基小角度转 + 越高越大的横移
        rot, hdx = pose.get("hat", (0.0, 0.0))
        if wt and (rot or hdx):
            vx, vy = x - bx, y - by
            dx += wt * (-rot * vy + hdx * (0.4 + 0.6 * lift))
            dy += wt * (rot * vx)
        # 发梢:越往下越滞后
        hair = pose.get("hair", 0.0)
        if wh and hair:
            dx += wh * hair * self._smooth(430.0, 640.0, y)
        # 呼吸:胸肩微微扩张
        br = pose.get("breath", 0.0)
        if wb and br:
            cx, cy = self.CHEST
            dx += wb * br * (x - cx) * 0.010
            dy += wb * br * (y - cy) * 0.007
        return dx * gate, dy * gate

    def light_field(self, img, off, k, pose):
        """受光:主光在左上,她转头/荡近荡远时明暗跟着移(最强的立体线索)。
        和 DepthWarp 一样用一亮一暗两张端点图按 24×24 小场混合;按量化姿态缓存。"""
        lx = round(max(-1.0, min(1.0, pose.get("look", (0.0, 0.0))[0])) * 4) / 4
        th = round(pose.get("theta", 0.0) / 0.1) * 0.1
        key = (id(img), round(k, 4), lx, th)
        cache = self.__dict__.setdefault("_lit_cache", {})
        hit = cache.get(key)
        if hit is not None:
            return hit
        ends = self.__dict__.setdefault("_lit_ends", {})
        e = ends.get(id(img))
        if e is None or e[0] is not img:
            rgb, a = img.convert("RGB"), img.getchannel("A")
            lo = rgb.point([round(v * 0.86) for v in range(256)] * 3).convert("RGBA")
            hi = rgb.point([min(255, round(v * 1.12)) for v in range(256)] * 3).convert("RGBA")
            lo.putalpha(a)
            hi.putalpha(a)
            e = (img, lo, hi)
            ends.clear()
            ends[id(img)] = e
        n = 24
        dark, bright = Image.new("L", (n, n)), Image.new("L", (n, n))
        gx0, gy0, gx1, gy1 = self.girl_bbox
        dv, bv = [], []
        for j in range(n):
            for i in range(n):
                ax = (off[0] + (i + 0.5) / n * img.width) / k
                ay = (off[1] + (j + 0.5) / n * img.height) / k
                u = (ax - gx0) / (gx1 - gx0) - 0.42
                v = (ay - gy0) / (gy1 - gy0) - 0.45
                g = -0.10 * u - 0.07 * v - 0.17 * lx * u + 0.05 * math.sin(th)
                g = max(-0.12, min(0.12, g))
                dv.append(int(max(0.0, -g) / 0.14 * 255))
                bv.append(int(max(0.0, g) / 0.12 * 255))
        dark.putdata(dv)
        bright.putdata(bv)
        dark = dark.resize(img.size, Image.BILINEAR)
        bright = bright.resize(img.size, Image.BILINEAR)
        lit = Image.composite(e[1], img, dark)
        lit = Image.composite(e[2], lit, bright)
        if len(cache) > 10:
            cache.clear()
        cache[key] = lit
        return lit

    def pose_keystone(self, img, off, k, theta, persp, pose):
        """前后荡 + 2.5D 姿态,一次预乘 MESH 采样(整张连续网格,不切层)。
        挂点线以上也进网格:帽尖要能跟着帽子摆(杆身已经从 swing 层里剔掉)。"""
        g = self.swing_geometry(k)
        w, h = img.size
        margin = int(math.ceil(w * .05))
        width = w + 2 * margin
        ox, oy = off[0] - margin, off[1]
        nx, ny = 14, 30
        xs = [round(width * i / nx) for i in range(nx + 1)]
        ys = [round(h * j / ny) for j in range(ny + 1)]
        vert = {}
        for j, py in enumerate(ys):
            for i, px in enumerate(xs):
                sx, sy = self.inv(g, px + ox, py + oy, theta, persp)
                dx, dy = self.pose_displacement(sx / k, sy / k, pose)
                vert[i, j] = (sx - off[0] - dx * k, sy - off[1] - dy * k)
        mesh = []
        for j in range(ny):
            for i in range(nx):
                if xs[i + 1] <= xs[i] or ys[j + 1] <= ys[j]:
                    continue
                quad = tuple(v for ij in ((i, j), (i, j + 1), (i + 1, j + 1), (i + 1, j))
                             for v in vert[ij])
                mesh.append(((xs[i], ys[j], xs[i + 1], ys[j + 1]), quad))
        out = img.convert("RGBa").transform((width, h), Image.Transform.MESH,
                                              mesh, Image.Resampling.BILINEAR)
        return out.convert("RGBA"), (ox, oy)

    def _portrait_keystone(self, img, off, k, theta, persp, view):
        """Global swing and portrait depth in ONE premultiplied MESH sample."""
        g = self.swing_geometry(k)
        w, h = img.size
        margin = int(math.ceil(w * .04))
        width = w + 2 * margin
        ox, oy = off[0] - margin, off[1]
        top = int(max(0, min(g["y0"], g["y1"]) - oy))
        top = min(top, h)
        mesh = []
        if top:
            mesh.append(((0, 0, width, top),
                         (-margin, 0, -margin, top, width - margin, top, width - margin, 0)))
        xs = [round(width * i / 16) for i in range(17)]
        ys = [top + round((h - top) * j / 32) for j in range(33)]
        # Adjacent cells share the EXACT same inverse vertices; no layer cuts or seams.
        vertices = {}
        for j, py in enumerate(ys):
            for i, px in enumerate(xs):
                sx, sy = self.inv(g, px + ox, py + oy, theta, persp)
                dx, dy = self.portrait_displacement(sx / k, sy / k, k, view)
                vertices[i, j] = (sx - off[0] - dx, sy - off[1] - dy)
        for j in range(32):
            for i in range(16):
                if xs[i + 1] <= xs[i] or ys[j + 1] <= ys[j]:
                    continue
                quad = tuple(v for ij in ((i, j), (i, j + 1), (i + 1, j + 1), (i + 1, j))
                             for v in vertices[ij])
                mesh.append(((xs[i], ys[j], xs[i + 1], ys[j + 1]), quad))
        out = img.convert("RGBa").transform((width, h), Image.Transform.MESH,
                                              mesh, Image.Resampling.BILINEAR)
        return out.convert("RGBA"), (ox, oy)

    def keystone(self, img, off, k, theta, persp, strips=10, portrait_view=None):
        """把缩放好的 swing 层按摆角变形。img 的左上角在原画缩放坐标 off。

        返回 (新图, 新图左上角的原画缩放坐标)。左右各留 4% 余量:靠近观众
        时底部会变宽。挂点线以上整块恒等;以下切成横条,每条一个四边形
        (逆映射取角点),PIL 一次 MESH 变换搞定 —— 比逐格网格快一个量级。
        portrait_view=(vx,vy) 可选开启微幅帽发纵深;默认 None 完全保留旧行为。
        有额外视差时缓存键须包含其量化值。"""
        if portrait_view is not None:
            if len(portrait_view) != 2 or not all(math.isfinite(v) for v in portrait_view):
                raise ValueError("portrait_view requires two finite coordinates")
            # Zero belongs to the same mesh family: quantized motion can cross it
            # without changing the global swing approximation underneath the face.
            return self._portrait_keystone(img, off, k, theta, persp, portrait_view)
        g = self.swing_geometry(k)
        w, h = img.size
        m = int(math.ceil(w * 0.04))
        ox, oy = off[0] - m, off[1]
        top = int(max(0, min(g["y0"], g["y1"]) - oy))      # 挂点线最高处(局部 y)
        W2 = w + 2 * m
        mesh = []
        if top > 0:
            mesh.append(((0, 0, W2, top), (-m, 0, -m, top, W2 - m, top, W2 - m, 0)))
        if top < h:
            ys = [top + (h - top) * i / strips for i in range(strips + 1)]
            ys = [int(round(v)) for v in ys]
            for y_a, y_b in zip(ys, ys[1:]):
                if y_b <= y_a:
                    continue
                quad = []
                for (u, v) in ((0, y_a), (0, y_b), (W2, y_b), (W2, y_a)):
                    sx, sy = self.inv(g, u + ox, v + oy, theta, persp)
                    quad.extend((sx - off[0], sy - off[1]))
                mesh.append(((0, y_a, W2, y_b), tuple(quad)))
        out = img.convert("RGBa").transform((W2, h), Image.Transform.MESH, mesh,
                                             Image.Resampling.BILINEAR)
        return out.convert("RGBA"), (ox, oy)


class KeystoneCache:
    """荡秋千时的变形结果缓存。摆角量化 0.008 rad(座椅位移 <0.3px,看不出
    台阶);待机微摆 ±0.085 rad 一个来回只有 ~22 档,LRU 24 张基本常驻命中。"""

    def __init__(self, cap=24):
        self.cap = cap
        self._d = OrderedDict()

    def get(self, key):
        hit = self._d.get(key)
        if hit is not None:
            self._d.move_to_end(key)
        return hit

    def put(self, key, val):
        self._d[key] = val
        while len(self._d) > self.cap:
            self._d.popitem(last=False)

    def clear(self):
        self._d.clear()
