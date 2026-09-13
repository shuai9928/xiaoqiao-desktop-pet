# -*- coding: utf-8 -*-
"""桌宠特效层。

设计约束:每帧只准做"贴图 + 少量矢量线",不许做滤镜、缩放、旋转。
所有贵的东西(高斯模糊、符文、光环、冲击波)一律预渲染成精灵缓存起来,
运行时按相位/半径挑一张贴上去。这样华丽度可以随便加,帧开销基本不变。

坐标约定:传进来的都是 2x 超采样空间的像素(和 pet.py 的 frame 一致)。
"""
import math
import random
import time

from PIL import Image, ImageDraw, ImageFilter

MAGIC_A = (168, 216, 255)
MAGIC_B = (199, 155, 255)
GOLD = (242, 193, 78)
GOLD_L = (255, 233, 160)


# ---------------- 通用小工具 ----------------
def _soft(im, blur):
    return im.filter(ImageFilter.GaussianBlur(blur)) if blur > 0 else im


def _ring_sprite(r, width, rgb, alpha, blur=0.0, ratio=1.0, bloom=True):
    """一张独立的圆环精灵(ratio<1 就是压扁的地面环)。bloom=True 时额外
    压一层大半径模糊的粗环当泛光 —— 这层是"华丽"的主要来源。"""
    pad = int(blur * 3 + width + 2 + (r * 0.12 if bloom else 0))
    w = int(r * 2 + pad * 2)
    h = int(r * 2 * ratio + pad * 2)
    box = [pad, pad, w - pad, h - pad]

    def shape(d, lw, col):
        d.ellipse(box, outline=col, width=max(1, int(lw)))

    layers = []
    if bloom:
        layers.append((width * 3.4, int(alpha * 0.55), rgb, max(2.0, r * 0.05)))
        layers.append((width * 1.8, int(alpha * 0.80), rgb, max(1.0, r * 0.018)))
    layers.append((width, alpha, rgb, blur))
    return _glow_stack(shape, (w, h), layers)


def _disc_sprite(r, rgb, alpha, ratio=1.0):
    """一坨柔光圆饼,垫在法阵底下。"""
    blur = r * 0.30
    pad = int(blur * 2 + 2)
    w, h = int(r * 2 + pad * 2), int(r * 2 * ratio + pad * 2)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse([pad, pad, w - pad, h - pad], fill=rgb + (alpha,))
    return _soft(im, blur)


def _dot_sprite(r, rgb, alpha):
    def shape(d, w, col):
        d.ellipse([0, 0, r * 4, r * 4], fill=col)
    box = int(r * 4 + 1)
    im = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    dd = ImageDraw.Draw(im)
    dd.ellipse([r * 1.5, r * 1.5, r * 2.5, r * 2.5], fill=rgb + (alpha,))
    halo = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse([r * 0.8, r * 0.8, r * 3.2, r * 3.2],
                                 fill=rgb + (alpha // 3,))
    out = _soft(halo, r * 0.8)
    out.alpha_composite(im)
    return out


def _glow_stack(draw_fn, size, layers):
    """假辉光:同一形状按 (线宽, 透明度) 从粗到细叠几遍,再整体轻微模糊。

    比真做一次大半径高斯便宜得多,而且预渲染完就是一张贴图,运行时零成本。
    """
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for w, a, rgb, blur in layers:
        if blur:
            tmp = Image.new("RGBA", size, (0, 0, 0, 0))
            draw_fn(ImageDraw.Draw(tmp), w, rgb + (a,))
            im.alpha_composite(_soft(tmp, blur))
        else:
            draw_fn(d, w, rgb + (a,))
    return im


def _sigil_sprite(size, seed):
    """程序化生成一个发光小符文。不用字体 —— 免得依赖系统里装没装那套字。

    形状语汇刻意收窄:一根主干 + 弧 + 点 + 短横,看起来像一套字,
    而不是一堆随机划痕(第一版就是划痕,太像噪点)。
    """
    rnd = random.Random(seed)
    s = int(size)
    pad = int(s * 0.55)
    box = (s + pad * 2, s + pad * 2)
    cx = s / 2 + pad
    top, bot = pad + s * 0.08, pad + s * 0.92

    arcs = []
    for _ in range(rnd.randint(1, 2)):
        r = s * rnd.uniform(0.26, 0.44)
        yy = pad + s * rnd.uniform(0.25, 0.72)
        a0 = rnd.choice((0, 180))
        arcs.append((r, yy, a0))
    bars = [pad + s * rnd.uniform(0.2, 0.8) for _ in range(rnd.randint(0, 2))]
    cap = rnd.random()

    def shape(d, w, col):
        w = max(1, int(w))
        d.line([cx, top, cx, bot], fill=col, width=w)
        for r, yy, a0 in arcs:
            d.arc([cx - r, yy - r, cx + r, yy + r], a0, a0 + 180, fill=col, width=w)
        for y in bars:
            d.line([cx - s * 0.3, y, cx + s * 0.3, y], fill=col, width=w)
        if cap < 0.4:
            r = s * 0.13
            d.ellipse([cx - r, top - r, cx + r, top + r], outline=col, width=w)
        elif cap < 0.7:
            r = s * 0.1
            d.ellipse([cx - r, bot - r, cx + r, bot + r], fill=col)

    return _glow_stack(shape, box, [
        (s * 0.46, 255, MAGIC_A, s * 0.26),    # 外层弥散辉光:颜色主要来自这层
        (s * 0.20, 255, (190, 230, 255), s * 0.06),    # 中层
        (s * 0.06, 255, (225, 245, 255), 0),   # 芯只留一点点 —— 芯太粗就变成灰色图标了
    ])


def _alpha_scaled(im, a):
    """按比例调整整张图的 alpha。只在预渲染阶段用,不进每帧路径。"""
    out = im.copy()
    out.putalpha(out.getchannel("A").point(lambda v: int(v * a)))
    return out


class FX:
    """所有预渲染资源的持有者。缩放变了就整个重建(和 rebuild_scale_cache 同步)。"""

    SIGILS = 16          # 地面法阵上的符文个数
    ALPHA_STEPS = 6      # 呼吸/淡入淡出用几档预渲染的透明度

    def __init__(self, scale, ss):
        self.scale = scale
        self.ss = ss
        self._circle_time = None
        self._orbit_spin = 0.0
        self._bead_spin = 0.0
        self.build()

    # ---------- 预渲染 ----------
    def build(self):
        s, k = self.scale, self.ss
        rx = 88 * s * k
        self.rx = rx
        size = 11 * s * k / 2                     # 符文本体(2x 空间)
        self.sig = []
        for i in range(self.SIGILS):
            base = _sigil_sprite(size, seed=1700 + i)
            # 环转到远端时要淡下去,预先备好几档,运行时只挑不算
            self.sig.append([_alpha_scaled(base, 0.45 + 0.55 * (j + 1) / self.ALPHA_STEPS)
                             for j in range(self.ALPHA_STEPS)])
        # 三层地面环:外圈细、符文圈、内圈
        self.ring_out = _ring_sprite(rx * 1.00, 1.8 * k, MAGIC_A, 175, ratio=0.26)
        self.ring_out2 = _ring_sprite(rx * 0.94, 0.9 * k, MAGIC_A, 95, ratio=0.26)
        self.ring_mid = _ring_sprite(rx * 0.66, 1.2 * k, MAGIC_B, 130, ratio=0.26)
        self.ring_in = _ring_sprite(rx * 0.30, 1.0 * k, GOLD, 120, ratio=0.26)
        # 中心那团柔光垫底,让整个法阵"浮"起来
        self.core = _disc_sprite(rx * 0.78, MAGIC_B, 105, ratio=0.26)
        # 环上跑的小金点
        self.bead = _dot_sprite(3.0 * s * k, GOLD_L, 255)
        # 冲击波:三档强度 × 16 帧扩散与渐隐,运行时只挑贴图。
        self._shock_sets = [
            [_ring_sprite(rx * (.25 + i / 15) * strength,
                          max(1.0, 3.0 - 2.0 * i / 15) * k,
                          MAGIC_B, int(210 * (1 - i / 15) ** .8), ratio=.26)
             for i in range(16)] for strength in (.5, .75, 1.0)]
        self.shock = self._shock_sets[-1]

    # ---------- 每帧 ----------
    def ground_circle(self, frame, d, cx, cy, t, energy=0.0):
        """地面法阵。每帧代价 = 5 张环/光贴图 + 12 张符文 + 8 个金点 + 两条星形折线,
        全是贴图和直线,没有任何实时滤镜或旋转。"""
        k = self.ss
        rx = self.rx
        self._paste_c(frame, self.core, cx, cy)
        self._paste_c(frame, self.ring_out, cx, cy)
        self._paste_c(frame, self.ring_out2, cx, cy)
        self._paste_c(frame, self.ring_mid, cx, cy)
        self._paste_c(frame, self.ring_in, cx, cy)

        # 能量控制角速度。不能直接乘累计时间,否则每次踩点都会跳角度。
        dt = 0.0 if self._circle_time is None else max(0.0, min(.25, t - self._circle_time))
        self._circle_time = t
        self._orbit_spin = (self._orbit_spin + dt * (.55 + 1.6 * energy)) % math.tau
        self._bead_spin = (self._bead_spin - dt * (.9 + 1.2 * energy)) % math.tau
        spin = self._orbit_spin
        ratio = 0.26
        n = self.SIGILS
        rs = rx * 0.83
        order = []
        for i in range(n):
            a = spin + 2 * math.pi * i / n
            sy = math.sin(a)
            order.append((sy, i, math.cos(a) * rs, sy * rs * ratio))
        order.sort()                                # 远的先画,近的压在上面
        for sy, i, ox, oy in order:
            j = min(self.ALPHA_STEPS - 1, int((sy + 1) / 2 * self.ALPHA_STEPS))
            sp = self.sig[i][j]
            frame.paste(sp, (int(cx + ox - sp.width / 2),
                             int(cy + oy - sp.height / 2)), sp)

        # 反向跑的金点,和符文错开转速,层次感主要靠这个
        bspin = self._bead_spin
        for i in range(8):
            a = bspin + 2 * math.pi * i / 8
            self._paste_c(frame, self.bead,
                          cx + math.cos(a) * rx * 0.66,
                          cy + math.sin(a) * rx * 0.66 * ratio)

        # 五芒星:粗-中-细三道叠出辉光,比真模糊便宜,而且能跟着转
        for rot, rr, tint in ((-spin * 0.7, 0.44, MAGIC_B),):
            pts = []
            for i in range(11):
                r = rx * rr if i % 2 == 0 else rx * rr * 0.42
                a = rot + math.pi * i / 5
                pts.append((cx + math.cos(a) * r, cy + math.sin(a) * r * ratio))
            e = int(60 * energy)
            for w, al in ((5.0, 26 + e // 3), (2.4, 70 + e // 2), (1.1, 190 + e)):
                d.line(pts, fill=tint + (min(255, al),),
                       width=max(1, int(w * k * 0.6)), joint="curve")

    def shockwave(self, frame, cx, cy, p, strength=1.0):
        """扩散同时淡出;强弱只影响半径,不再把消失时间截在半途。"""
        if not 0 <= p < 1:
            return
        band = max(0, min(2, round(strength * 2)))
        sprites = self._shock_sets[band]
        i = min(len(sprites) - 1, int(p * len(sprites)))
        self._paste_c(frame, sprites[i], cx, cy)

    @staticmethod
    def _paste_c(frame, sp, cx, cy):
        frame.paste(sp, (int(cx - sp.width / 2), int(cy - sp.height / 2)), sp)


def transform_ribbons(d, cx, feet, width, height, age, k, front=False):
    """两条向上旋进的星带;远侧先画,近侧仅画腰以下,留出脸部。

    固定 2×48 段折线,无逐帧图片旋转、滤镜或新增缓存。
    """
    if not .2 < age < 2.65:
        return
    fade_in = min(1.0, (age - .2) / .35)
    fade_out = min(1.0, (2.65 - age) / .65)
    envelope = fade_in * fade_in * (3 - 2 * fade_in) * fade_out * fade_out
    rise = min(1.0, (age - .2) / .8)
    radius = width * .40 * (.75 + .25 * fade_in)
    for lane, color in enumerate((MAGIC_A, GOLD_L)):
        previous = None
        for i in range(49):
            u = i / 48
            angle = u * math.tau * 1.25 + age * 5 + lane * math.pi
            depth = math.sin(angle)
            point = (cx + math.cos(angle) * radius * (1 - .3 * u),
                     feet - height * .84 * u * rise + depth * height * .035)
            visible = (depth >= 0) == front and (not front or u < .45)
            if visible and previous is not None:
                alpha = int((100 if front else 145) * envelope * (1 - .45 * u))
                d.line([previous, point], fill=color + (alpha,),
                       width=max(1, int(1.5 * k)), joint="curve")
                if i % 8 == 0:
                    r = 2.5 * k * envelope
                    d.ellipse((point[0] - r, point[1] - r,
                               point[0] + r, point[1] + r),
                              fill=GOLD_L + (int(220 * envelope),))
            previous = point if visible else None


# ---------------- 施法大招 ----------------
def _beam_sprite(w, h, rgb, core_alpha):
    """竖直光柱。中间一道近乎不透明的芯,两侧高斯衰减。

    刻意做窄:宽度只比她本人宽一点。光柱一宽就变成"糊住半个屏幕"的光污染,
    而窄光柱即使芯是实的也只盖住一条,桌面其它地方干净。
    """
    im = Image.new("RGBA", (int(w), int(h)), (0, 0, 0, 0))
    px = im.load()
    cw = w / 2.0
    sigma = w * 0.24
    for x in range(int(w)):
        dx = (x - cw) / sigma
        a = math.exp(-0.5 * dx * dx)
        # 芯用近白,外沿转成主题色 —— 这样看着像"亮",而不是"一块半透明的紫"
        mix = min(1.0, a * 1.35)
        col = (int(rgb[0] + (255 - rgb[0]) * mix),
               int(rgb[1] + (255 - rgb[1]) * mix),
               int(rgb[2] + (255 - rgb[2]) * mix))
        for y in range(int(h)):
            v = y / h
            # 顶端到最后 18% 才收,不然整根柱子糊成一团光斑
            fade = min(1.0, (1.0 - v) / 0.18) * min(1.0, v * 5.0 + 0.10)
            px[x, y] = col + (int(core_alpha * a * fade),)
    return im


def _burst_sprite(r, rgb, alpha, spikes=8):
    """光爆:实心亮核 + 放射光刺。收得很紧,不往外糊。"""
    pad = int(r * 0.25)
    s = int(r * 2 + pad * 2)
    c = s / 2
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for i in range(spikes):
        a = math.pi * 2 * i / spikes
        ln = r * (1.0 if i % 2 == 0 else 0.62)
        d.line([c, c, c + math.cos(a) * ln, c + math.sin(a) * ln],
               fill=rgb + (int(alpha * 0.75),), width=max(1, int(r * 0.10)))
    im = _soft(im, r * 0.06)
    core = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    dc = ImageDraw.Draw(core)
    dc.ellipse([c - r * 0.34, c - r * 0.34, c + r * 0.34, c + r * 0.34],
               fill=rgb + (int(alpha * 0.55),))
    core = _soft(core, r * 0.12)
    dc = ImageDraw.Draw(core)
    dc.ellipse([c - r * 0.15, c - r * 0.15, c + r * 0.15, c + r * 0.15],
               fill=(255, 252, 246, alpha))          # 实芯:接受覆盖就靠它
    im.alpha_composite(core)
    return im


def _dial_sprite(r, ratio, rgb, alpha, k):
    """时钟表盘环:一圈刻度,四个方位是长刻度。她是时之魔女,这个意象最对题。"""
    pad = int(r * 0.18 + 6)
    w, h = int(r * 2 + pad * 2), int(r * 2 * ratio + pad * 2)
    cx, cy = w / 2, h / 2

    def shape(d, lw, col):
        lw = max(1, int(lw))
        d.ellipse([pad, pad, w - pad, h - pad], outline=col, width=lw)
        for i in range(24):
            a = math.pi * 2 * i / 24
            ln = 0.86 if i % 6 == 0 else (0.93 if i % 2 == 0 else 0.95)
            d.line([cx + math.cos(a) * r, cy + math.sin(a) * r * ratio,
                    cx + math.cos(a) * r * ln, cy + math.sin(a) * r * ln * ratio],
                   fill=col, width=lw)

    return _glow_stack(shape, (w, h), [
        (2.6 * k, int(alpha * 0.40), rgb, max(2.0, r * 0.05)),
        (1.6 * k, int(alpha * 0.75), rgb, 1.0),
        (0.9 * k, alpha, (235, 245, 255), 0),
    ])


def _flash_sprite(r, rgb, alpha):
    """四芒星闪光。爆发时到处炸一下,是"满"出来的关键。"""
    s = int(r * 2)
    c = s / 2
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for ln, wd, a in ((r, max(1, r * 0.10), int(alpha * 0.9)),
                      (r * 0.45, max(1, r * 0.16), alpha)):
        d.line([c - ln, c, c + ln, c], fill=rgb + (a,), width=int(wd))
        d.line([c, c - ln, c, c + ln], fill=rgb + (a,), width=int(wd))
    im = _soft(im, r * 0.07)
    d = ImageDraw.Draw(im)
    rr = r * 0.13
    d.ellipse([c - rr, c - rr, c + rr, c + rr], fill=(255, 253, 248, alpha))
    return im


def _split_h(sp):
    """把一张压扁的环切成上下两半:上半是环的远端(该画在她身后),
    下半是近端(该画在她身前)。环这样一前一后包住她,立体感立刻就出来了 ——
    整张贴在身后的话,只能从她两侧露出两条弧,看着就是两根线。
    返回 (上半图, 下半图, 上半相对中心的偏移, 下半偏移)。
    """
    w, h = sp.size
    m = h // 2
    top = sp.crop((0, 0, w, m))
    bot = sp.crop((0, m, w, h))
    return top, bot, -(h / 2) + m / 2, m / 2 - h / 2 + (h - m) / 2 + (h - m) / 2 * 0


class CastFX:
    """双击时间魔法的整段演出。p 是 0~1 的进度,内部自己分幕。

    分幕:0.00-0.18 蓄力(能量内吸) / 0.18-0.34 法阵展开 /
         0.34-0.55 爆发(光柱+光爆+冲击波+符文炸开) / 0.55-1.00 余韵回收。
    """

    STEPS = 8            # 各类精灵的预渲染档数

    def __init__(self, base):
        self.b = base
        k = base.ss
        rx = base.rx
        self.beam = [_beam_sprite(max(8, rx * 0.95), rx * 4.6, MAGIC_B, a)
                     for a in (70, 135, 200, 250)]
        self.burst = [_burst_sprite(rx * (0.22 + 0.13 * i), GOLD_L, 250)
                      for i in range(self.STEPS)]
        # 逆光:紧贴她轮廓的一圈,不是一大团。
        # 第一版半径给到 rx*1.75,浅色壁纸上直接糊出一块发灰的方斑 ——
        # 那正是"光污染"。收到 rx*0.75 以内、并把颜色提到接近白,
        # 才是"她背后透出来的光",而不是"桌面被蒙了一层紫"。
        self.halo = [_disc_sprite(rx * (0.42 + 0.11 * i), (236, 226, 255), 120,
                                  ratio=1.0)
                     for i in range(4)]
        self.dial = [_split_h(_dial_sprite(rx * (0.52 + 0.16 * i), 0.26,
                                          MAGIC_A, 225, k))
                     for i in range(self.STEPS)]
        self.flash = [_flash_sprite(rx * (0.10 + 0.05 * i), GOLD_L, 245)
                      for i in range(4)]
        self._tables()
        # 半空中的第二层法阵,和地面那圈反向转
        self.air = [_split_h(_ring_sprite(rx * (0.34 + 0.10 * i), 2.0 * k,
                                         MAGIC_A, 200, ratio=0.26))
                    for i in range(self.STEPS)]

    @staticmethod
    def _half(frame, pair, which, cx, cy):
        top, bot, _, _ = pair
        h = top.height + bot.height
        sp = top if which == 0 else bot
        y = int(cy - h / 2) + (0 if which == 0 else top.height)
        frame.paste(sp, (int(cx - sp.width / 2), y), sp)

    # 预生成的随机布点:每帧要用同一套位置,不能每帧现摇 —— 现摇会闪烁
    def _tables(self):
        rnd = random.Random(90210)
        self.motes = [(rnd.uniform(-1, 1), rnd.uniform(0, 1),
                       rnd.uniform(0.8, 1.6), rnd.uniform(0, 6.28))
                      for _ in range(26)]
        self.pops = [(rnd.uniform(0, 6.28), rnd.uniform(0.35, 1.15),
                      rnd.uniform(-0.9, 0.9), rnd.uniform(0.34, 0.58),
                      rnd.randrange(4)) for _ in range(14)]
        self.dust = [(rnd.uniform(-1.1, 1.1), rnd.uniform(0, 1),
                      rnd.uniform(0.5, 1.2)) for _ in range(22)]

    # 分成"她身后"和"她身前"两半 —— 光柱必须画在她后面。
    # 画在前面会在她脸上糊一层奶白,既丑又正好是你说的光污染;
    # 画在后面则是逆光剪影,同样的亮度看着高级得多。
    def draw_back(self, frame, d, cx, feet_y, p):
        b = self.b
        rx = b.rx
        # 蓄力:亮点从外圈螺旋收进脚下
        if p < 0.36:
            q = p / 0.36
            for i in range(14):
                a = math.pi * 2 * i / 14 + p * 7
                rr = rx * (1.7 - 1.3 * q)
                b._paste_c(frame, b.bead, cx + math.cos(a) * rr,
                           feet_y + math.sin(a) * rr * 0.26 - rx * 0.15 * q)
        # 逆光
        if 0.30 <= p < 0.70:
            q = max(0.0, min(1.0, (p - 0.30) / 0.20 if p < 0.50 else (0.70 - p) / 0.20))
            b._paste_c(frame, self.halo[min(3, int(q * 4))], cx, feet_y - rx * 1.15)
        # 光柱
        if 0.30 <= p < 0.66:
            q = (p - 0.30) / 0.36
            j = max(0, min(len(self.beam) - 1,
                           int((1 - abs(q - 0.30) * 2.0) * len(self.beam))))
            sp = self.beam[j]
            frame.paste(sp, (int(cx - sp.width / 2), int(feet_y - sp.height)), sp)
        # 顺着光柱往上飘的光粒 —— "满"的观感主要靠这一层
        if 0.28 <= p < 0.88:
            q = (p - 0.28) / 0.60
            for dx0, off, spd, ph in self.motes:
                v = (off + q * spd) % 1.0
                if v > 0.96:
                    continue
                x = cx + dx0 * rx * 0.42 + math.sin(ph + v * 5.0) * rx * 0.09
                y = feet_y - v * rx * 3.4
                b._paste_c(frame, b.bead, x, y)
        # 时钟表盘:她是时之魔女,这圈刻度升到胸口停住
        if 0.20 < p < 0.86:
            q = min(1.0, (p - 0.20) / 0.22)
            i = min(self.STEPS - 1, int(q * self.STEPS))
            self._half(frame, self.dial[i], 0, cx, feet_y - rx * (0.15 + 1.05 * q))
        # 半空法阵
        if 0.18 < p < 0.82:
            q = min(1.0, (p - 0.18) / 0.16)
            i = min(self.STEPS - 1, int(q * self.STEPS))
            self._half(frame, self.air[i], 0, cx, feet_y - rx * 1.75)

    def draw_front(self, frame, d, cx, feet_y, p, sigils):
        b = self.b
        rx = b.rx
        k = b.ss
        # 地面光纹:从中心向外抽出的放射线,三道叠出辉光
        if 0.32 <= p < 0.66:
            q = (p - 0.32) / 0.34
            fade = 1.0 - q
            for i in range(12):
                a = math.pi * 2 * i / 12 + 0.13
                r0 = rx * (0.18 + 0.9 * q)
                r1 = r0 + rx * 0.34 * (1 - q * 0.6)
                seg = [(cx + math.cos(a) * r0, feet_y + math.sin(a) * r0 * 0.26),
                       (cx + math.cos(a) * r1, feet_y + math.sin(a) * r1 * 0.26)]
                for w, al in ((3.4, 40), (1.8, 110), (0.9, 220)):
                    d.line(seg, fill=MAGIC_A + (int(al * fade),),
                           width=max(1, int(w * k * 0.6)))
        # 三道错开的冲击波,比一道"满"得多
        for delay in (0.0, 0.09, 0.19):
            q = (p - 0.34 - delay) / 0.26
            if 0.0 <= q < 1.0:
                b.shockwave(frame, cx, feet_y, q)
        # 环的近端:和 draw_back 里的远端合成一个包住她的整圈
        if 0.20 < p < 0.86:
            q = min(1.0, (p - 0.20) / 0.22)
            i = min(self.STEPS - 1, int(q * self.STEPS))
            self._half(frame, self.dial[i], 1, cx, feet_y - rx * (0.15 + 1.05 * q))
        if 0.18 < p < 0.82:
            q = min(1.0, (p - 0.18) / 0.16)
            i = min(self.STEPS - 1, int(q * self.STEPS))
            self._half(frame, self.air[i], 1, cx, feet_y - rx * 1.75)
        # 光爆
        if 0.34 <= p < 0.62:
            q = (p - 0.34) / 0.28
            i = min(self.STEPS - 1, int(q * self.STEPS))
            b._paste_c(frame, self.burst[i], cx, feet_y - rx * 0.22)
        # 四芒星闪光:在她周围此起彼伏地炸
        for a, rr, hy, t0, si in self.pops:
            q = (p - t0) / 0.16
            if 0.0 <= q < 1.0:
                j = min(3, int(si + q * 2) % 4)
                b._paste_c(frame, self.flash[j],
                           cx + math.cos(a) * rx * rr,
                           feet_y - rx * (0.35 + hy) - math.sin(a) * rx * rr * 0.20)
        # 符文炸开
        if 0.36 <= p < 0.82:
            q = (p - 0.36) / 0.46
            n = len(sigils)
            j = b.ALPHA_STEPS - 1 if q < 0.7 else max(0, int((1 - q) / 0.3 * b.ALPHA_STEPS))
            for i in range(n):
                a = math.pi * 2 * i / n - p * 1.2
                rr = rx * (0.55 + 0.80 * q)
                sp = sigils[i][j]
                frame.paste(sp, (int(cx + math.cos(a) * rr - sp.width / 2),
                                 int(feet_y + math.sin(a) * rr * 0.26
                                     - rx * 1.05 * q - sp.height / 2)), sp)
        # 余韵:星屑慢慢飘落
        if 0.58 <= p <= 1.0:
            q = (p - 0.58) / 0.42
            for dx0, off, spd in self.dust:
                v = (off + q * spd) % 1.0
                b._paste_c(frame, b.bead,
                           cx + dx0 * rx * 0.95 + math.sin(v * 4 + dx0 * 3) * rx * 0.07,
                           feet_y - rx * 2.2 * (1 - v))


# ---------------- 全屏版时间魔法 ----------------
class FullscreenArt:
    """全屏特效的画法。只画矢量 + 少量小贴图 —— 全屏画布上任何一次
    滤镜/缩放都是几十毫秒,一次都用不起。

    传进来的 canvas 是整块屏幕大小的 RGBA(直通 alpha),调用方负责
    清空、预乘和推送。坐标是屏幕像素,(cx, cy) 是她的位置。
    """

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.diag = math.hypot(w, h)
        rnd = random.Random(4242)
        # 星屑布点固定下来 —— 每帧现摇会变成一片乱闪
        self.motes = [(rnd.uniform(0, 6.28), rnd.uniform(0.15, 1.0),
                       rnd.uniform(0.6, 1.5), rnd.uniform(2.0, 5.0),
                       rnd.choice([GOLD_L, MAGIC_A, MAGIC_B, (255, 255, 255)]))
                      for _ in range(90)]
        self.rays = [(rnd.uniform(0, 6.28), rnd.uniform(0.55, 1.0),
                      rnd.uniform(0.010, 0.030)) for _ in range(22)]

    # ---- 各分层 ----
    def _rings(self, d, cx, cy, p):
        """三道错峰扩散的大圆环。矢量描边,大半径也几乎不要钱。"""
        for i, delay in enumerate((0.0, 0.10, 0.21)):
            q = (p - 0.05 - delay) / 0.55
            if not 0.0 <= q < 1.0:
                continue
            r = self.diag * 0.06 + self.diag * 0.62 * (q ** 0.62)
            fade = (1.0 - q) ** 1.5
            tint = (MAGIC_A, MAGIC_B, GOLD_L)[i]
            for wd, al in ((13, 32), (6, 80), (2.2, 190)):
                a = int(al * fade)
                if a <= 2:
                    continue
                d.ellipse([cx - r, cy - r * 0.92, cx + r, cy + r * 0.92],
                          outline=tint + (a,), width=max(1, int(wd * (1 - q * 0.5))))

    def _rays(self, d, cx, cy, p):
        """从她身上射向四周的光条。用细长三角形,比画线更有"束"的感觉。"""
        q = (p - 0.10) / 0.26
        if not 0.0 <= q < 1.0:
            return
        grow = min(1.0, q * 2.4)
        fade = (1.0 - q) ** 2.2          # 收得快一点,免得后半段拖着一片灰条
        for a0, ln, wid in self.rays:
            a = a0 + p * 0.5
            r0 = self.diag * 0.03
            r1 = self.diag * ln * 0.62 * grow
            for spread, al, col in ((2.4, 40, MAGIC_B), (1.0, 110, MAGIC_A),
                                    (0.35, 235, (255, 250, 240))):
                w = wid * spread
                pts = [(cx + math.cos(a) * r0, cy + math.sin(a) * r0),
                       (cx + math.cos(a + w) * r1, cy + math.sin(a + w) * r1),
                       (cx + math.cos(a - w) * r1, cy + math.sin(a - w) * r1)]
                d.polygon(pts, fill=col + (int(al * fade),))

    def _flash(self, d, cx, cy, p):
        """中心光爆:一圈圈同心椭圆堆出来的渐亮核,不做模糊。"""
        q = (p - 0.04) / 0.30
        if not 0.0 <= q < 1.0:
            return
        peak = math.sin(min(1.0, q * 1.25) * math.pi)
        r = self.diag * (0.05 + 0.20 * q)
        steps = 16
        for i in range(steps, 0, -1):
            f = i / steps
            a = int(215 * peak * (1 - f) ** 1.6)
            if a <= 2:
                continue
            rr = r * f
            col = (255, 252, 245) if f < 0.35 else MAGIC_B
            d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=col + (a,))

    def _motes(self, d, cx, cy, p):
        """全屏星屑:从她身上向外飞,后半段淡出。"""
        q = (p - 0.08) / 0.80
        if not 0.0 <= q < 1.0:
            return
        fade = 1.0 if q < 0.55 else (1.0 - q) / 0.45
        for a0, dist, spd, size, col in self.motes:
            a = a0 + q * spd * 0.35
            r = self.diag * 0.55 * dist * (q ** 0.7) * spd
            x = cx + math.cos(a) * r
            y = cy + math.sin(a) * r * 0.9
            if not (-40 < x < self.w + 40 and -40 < y < self.h + 40):
                continue
            s = size * (1.5 - 0.7 * q)
            # 外圈只留一点点:第一版给了 2.6 倍半径、alpha 40,
            # 铺开之后每颗都变成一个发灰的圆斑,整屏看着是脏的
            s2 = s * 1.7
            d.ellipse([x - s2, y - s2, x + s2, y + s2],
                      fill=col + (int(70 * fade),))
            d.ellipse([x - s, y - s, x + s, y + s],
                      fill=col + (int(255 * fade),))

    def draw(self, canvas, cx, cy, p):
        d = ImageDraw.Draw(canvas, "RGBA")
        self._rings(d, cx, cy, p)
        self._rays(d, cx, cy, p)
        self._motes(d, cx, cy, p)
        self._flash(d, cx, cy, p)


# ---------------- 粒子精灵库(备料完成,尚未接入 pet.py) ----------------
def _star_pts(cx, cy, ro, ri, n=5, rot=-math.pi / 2):
    """pet.py 的 star_pts 同款公式。fx 不能反向 import pet.py(pet.py 顶层
    import fx,会成环),几何只能复制一份;两处一致由 _test_fx_particles.py
    逐像素证明。"""
    return [(cx + math.cos(rot + math.pi * i / n) * (ro if i % 2 == 0 else ri),
             cy + math.sin(rot + math.pi * i / n) * (ro if i % 2 == 0 else ri))
            for i in range(2 * n)]


def _heart_pts(cx, cy, s):
    """pet.py 的 heart_pts 同款(26 点参数化心形)。"""
    pts = []
    for i in range(26):
        a = 2 * math.pi * i / 26
        x = 16 * math.sin(a) ** 3
        y = (13 * math.cos(a) - 5 * math.cos(2 * a)
             - 2 * math.cos(3 * a) - math.cos(4 * a))
        pts.append((cx + x * s / 17.0, cy - y * s / 17.0))
    return pts


class ParticleSprites:
    """pet.py 粒子系统的预渲染备料库。

    render 的粒子段(pet.py:5425-5587)每帧对最多 320 颗粒子逐个
    d.polygon/d.ellipse,星形/叶/瓣/彩纸还要每颗现算旋转点集 —— 粒子
    密集加 60fps 时这是 render 里最大的可变开销。这里按 fx.py 的老规矩
    把 9 种纯图形粒子预渲染成精灵:旋转/大小/alpha 全部量化成档,运行时
    只查表贴图。

    尚未接入。等 pet.py 的并行大改合并后逐 kind 换,一处绘制换一行:
        d.polygon(star_pts(px, py, s, s * 0.45, rot=rot), fill=col + (a2,))
      ->
        self.psprites.paste(frame, "star", px, py, s0, rot, a2, col)
    glow_lit(光晕层)不归这里管,接入时保持原调用。

    约定:size 用 pet.py 粒子的原始单位(p["size"] 那个数),内部乘 k 变成
    2x 空间像素(fx.py:8 的坐标约定);alpha 是最终填充透明度 0~255,和
    render 里 a2 的含义一致。cstar 例外:pet.py 写死 fill 245/outline 255,
    这里把传入 alpha 当缩放比,传 255 即原样。固定色 kind 的颜色经
    COLOR_QUANT 量化(偏差 <=7/255,肉眼不可辨),等价测试有专门断言。

    关键坑:pet.py 的粒子是 d.polygon 直接**覆写**帧像素(连 alpha 一起
    替换,实测;Draw(im,"RGBA") 在 RGBA 目标上不混合),所以 paste 绝不能
    拿精灵自身当掩码 —— 那是 source-over,RGB 被预乘、alpha 被平方,能量
    对不上。这里每张精灵配一张 "1" 模式二值足迹掩码,paste 整像素替换,
    与直画逐字节一致;alpha 派生变体共享同一张掩码(缩 alpha 不改足迹)。

    成本模型(实测,见 _test_fx_particles.py 场景 c):贴图开销 ∝ 外接盒
    面积,直画开销 ∝ 多边形点数 + 形状面积。全命中单发:heart(26 点)
    x2.7、star/cstar/sparkle(8~10 点)x1.2~1.3;petal/leaf/confetti(4 点)
    和雪/萤(椭圆)直画本就免费,贴图反而 x0.5~0.8。接入按 kind 挑,别
    整段一刀切。

    缓存有界 LRU、懒建:没建过的档位第一次贴时现画一张(代价约等于一次
    polygon 绘制,无尖峰),之后命中零成本。纯色填充 kind 的低档 alpha 不
    整张重画 —— 先备一张 alpha=255 基准图,低档用 _alpha_scaled 派生:
    自转的档位穿越躲不掉重画,但闪烁/淡出的 alpha 档穿越能便宜一个量级。
    被驱逐的精灵图就地回收当下一张的构建画布,省掉 Image.new 的分配。
    只在主线程 render 用,不加锁。
    """

    ROT_STEPS = 24        # 旋转档(15°/档)。粒子小、带光晕,台阶感可忽略
    ALPHA_STEPS = 8       # alpha 档数,对齐 pet.py 光晕缓存的 8 级
    SIZE_STEP = 2         # 2x 空间 2px 一档,reduce(2) 后正好 1px(同贴纸缓存)
    COLOR_QUANT = 8       # 颜色通道量化步长,把季节调色板的近色收敛到一张
    CACHE_MAX = 320       # LRU 上限(先例:_warp_cache=12、glow_cache=96)

    # 会转的 kind 才把旋转档计入键;雪/萤火/爱心不转,省 24 倍键空间
    _ROTATED = frozenset(("sparkle", "star", "cstar", "petal", "leaf", "confetti"))
    # alpha 可从基准图整张派生的 kind(纯色填充)。cstar/leaf 的描边透明度
    # 是填充的固定配比(pet.py:5488/5562),必须整张重画,不能统一缩 alpha
    _ALPHA_DERIVED = frozenset(("sparkle", "star", "petal", "confetti",
                                "heart", "snow", "firefly"))
    # 固定色 kind:字面量与 pet.py render 逐值一致(HEART_C 见 pet.py:137)
    _FIXED = {"heart": (255, 95, 138), "snow": (245, 248, 255),
              "firefly": (240, 255, 180)}
    # 外接盒相对 s 的放大系数,宁大勿切边
    _EXTENT = {"sparkle": 1.10, "star": 1.10, "cstar": 1.20, "petal": 1.15,
               "leaf": 1.25, "confetti": 1.40, "heart": 1.45,
               "snow": 1.05, "firefly": 1.05}

    def __init__(self, scale, ss):
        self.scale = scale
        self.ss = ss
        self.k = scale * ss
        self._cache = {}      # key -> (精灵, 掩码);dict 有序,触顶删最早即 LRU
        self._free = {}       # size -> 被驱逐的精灵图,回收当构建画布
        # 命中/未命中计数,给测试与接入评估读;热路径只 +1,无分支
        self.stat_hit = 0
        self.stat_miss = 0

    @staticmethod
    def _mask_of(im):
        """二值足迹掩码("1" 模式):形状内 255(整像素替换),形状外 0。

        用 "1" 而不是 L:二值掩码走 paste 的免混合快速路径,实测比 L 掩码
        快 3 倍以上,也快过小尺寸形状的 polygon 直画。查表 point,别用
        lambda —— 逐值调 Python 函数比 C 查表慢一个量级。
        """
        lut = b"\x00" + b"\xff" * 255
        return im.getchannel("A").point(lut).convert(
            "1", dither=Image.Dither.NONE)

    @classmethod
    def _q_color(cls, rgb):
        q = cls.COLOR_QUANT
        return (rgb[0] // q * q, rgb[1] // q * q, rgb[2] // q * q)

    def _resolve(self, kind, size, rot, alpha, color):
        """把连续参数量化成档并组缓存键,返回 (key, s, rot, alpha, rgb)。

        get/paste 与 _test_fx_particles.py 共用,保证参考画法用的是同一套
        档位 —— 量化误差因此不进等价比对。
        """
        if kind not in self._EXTENT:
            raise ValueError(f"未知粒子种类: {kind!r}")
        s = max(self.SIZE_STEP,
                int(size * self.k + self.SIZE_STEP / 2) // self.SIZE_STEP
                * self.SIZE_STEP)
        if kind in self._ROTATED:
            rb = int(math.floor(rot * self.ROT_STEPS / (2 * math.pi))) \
                % self.ROT_STEPS
            rot = rb * 2 * math.pi / self.ROT_STEPS
        else:
            rot = 0.0
        alpha = max(0, min(255, int(alpha)))
        alpha = int(round(alpha / 255 * (self.ALPHA_STEPS - 1))) \
            * 255 // (self.ALPHA_STEPS - 1)
        if kind == "cstar":
            rgb = None                      # 双色写死在 _build,键里占位
        elif kind in self._FIXED:
            rgb = self._q_color(self._FIXED[kind])
        elif color is None:
            raise ValueError(f"粒子 {kind!r} 需要显式 color")
        else:
            rgb = self._q_color(color)
        return (kind, s, rot, alpha, rgb), s, rot, alpha, rgb

    def _store(self, key, pair):
        """入缓存并触顶驱逐;被驱逐的图按尺寸回收,留作构建画布。"""
        self._cache[key] = pair
        if len(self._cache) > self.CACHE_MAX:
            oldest = next(iter(self._cache))    # dict 有序,最旧 = 首个键
            old = self._cache.pop(oldest)
            pool = self._free.setdefault(old[0].size, [])
            if len(pool) < 4:
                pool.append(old[0])

    def get(self, kind, size, rot=0.0, alpha=255, color=None):
        """按量化档取一张 (精灵, 掩码),缓存没有就现画。"""
        key, s, rot, alpha, rgb = self._resolve(kind, size, rot, alpha, color)
        cache = self._cache
        pair = cache.get(key)
        if pair is not None:
            cache.pop(key)
            cache[key] = pair           # 摘下重插 = LRU 的 touch
            self.stat_hit += 1
            return pair
        self.stat_miss += 1
        if kind in self._ALPHA_DERIVED and alpha != 255:
            bkey = (kind, s, rot, 255, rgb)
            base = cache.get(bkey)
            if base is None:
                base = self._build(kind, s, rot, 255, rgb)
                self._store(bkey, base)
            pair = (_alpha_scaled(base[0], alpha / 255), base[1])
        else:
            pair = self._build(kind, s, rot, alpha, rgb)
        self._store(key, pair)
        return pair

    def paste(self, frame, kind, x, y, size, rot=0.0, alpha=255, color=None):
        """一行贴图:查档取精灵,用二值掩码整像素替换到 2x 帧上 ——
        和 d.polygon 直画的覆写语义逐字节一致。"""
        sp, mask = self.get(kind, size, rot, alpha, color)
        frame.paste(sp, (int(x - sp.width / 2), int(y - sp.height / 2)), mask)

    def _build(self, kind, s, rot, alpha, rgb):
        ext = s * self._EXTENT[kind]
        box = int(math.ceil(ext)) * 2 + 2   # 偶数边长:中心恰在像素整点,
        c = box / 2                         # 整数坐标居中贴回时零偏移
        pool = self._free.get((box, box))
        if pool:
            im = pool.pop()
            im.putalpha(0)                  # alpha 清零即全透明,残留的 RGB
        else:                               # 会被掩码挡住,不必整块擦
            im = Image.new("RGBA", (box, box), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        if kind == "sparkle":
            d.polygon(_star_pts(c, c, s, s * 0.30, n=4, rot=rot),
                      fill=rgb + (alpha,))
        elif kind == "star":
            d.polygon(_star_pts(c, c, s, s * 0.45, rot=rot), fill=rgb + (alpha,))
        elif kind == "cstar":
            # pet.py:5487 写死 fill 245 / outline 255,alpha 等比缩放
            d.polygon(_star_pts(c, c, s, s * 0.5, n=5, rot=rot),
                      fill=GOLD_L + (int(245 * alpha / 255),),
                      outline=GOLD + (alpha,), width=1)
        elif kind == "petal":
            ca, sa = math.cos(rot), math.sin(rot)
            d.polygon([(c + dx * ca - dy * sa, c + dx * sa + dy * ca)
                       for dx, dy in ((-s, 0), (0, -s * 0.6), (s, 0), (0, s * 0.6))],
                      fill=rgb + (alpha,))
        elif kind == "leaf":
            ca, sa = math.cos(rot), math.sin(rot)
            d.polygon([(c + dx * ca - dy * sa, c + dx * sa + dy * ca)
                       for dx, dy in ((-s, -s * 0.45), (s, -s * 0.3),
                                      (s * 0.4, s * 0.5), (-s * 0.5, s * 0.4))],
                      fill=rgb + (alpha,),
                      outline=(120, 70, 40, int(alpha * 0.7)), width=1)
        elif kind == "confetti":
            w2, h2 = s, s * 0.55
            ca, sa = math.cos(rot), math.sin(rot)
            d.polygon([(c + dx * ca - dy * sa, c + dx * sa + dy * ca)
                       for dx, dy in ((-w2, -h2), (w2, -h2), (w2, h2), (-w2, h2))],
                      fill=rgb + (alpha,))
        elif kind == "heart":
            d.polygon(_heart_pts(c, c, s), fill=rgb + (alpha,))
        else:                               # snow / firefly:圆点
            d.ellipse([c - s, c - s, c + s, c + s], fill=rgb + (alpha,))
        return im, self._mask_of(im)


# ---------------- 时之魔女演出(时停/回溯) ----------------
def _gear_sprite(r, teeth, rot, rgb, alpha, k):
    """程序化齿轮:齿圈 + 辐条 + 轴心,叠 _glow_stack 出辉光。

    齿轮是"时间机器"最直白的意象。预渲染成若干旋转档,运行时轮换贴图
    就是旋转,不碰任何实时仿射。齿用每齿四点撑出齿宽,不然会画成太阳。
    """
    tooth = r * 0.24
    body = r - tooth
    pad = int(tooth + 4 * k)
    box = int(body * 2 + pad * 2) + 2
    c = box / 2

    def shape(d, w, col):
        w = max(1, int(w))
        pts = []
        for i in range(teeth):
            a = rot + 2 * math.pi * i / teeth
            hw = math.pi / teeth
            for da, rr in ((-hw * 0.62, body), (-hw * 0.30, r),
                           (hw * 0.30, r), (hw * 0.62, body)):
                pts.append((c + math.cos(a + da) * rr, c + math.sin(a + da) * rr))
        d.polygon(pts, outline=col, width=w)
        d.ellipse([c - body * 0.55, c - body * 0.55,
                   c + body * 0.55, c + body * 0.55], outline=col, width=w)
        for j in range(3):
            a = rot + math.pi * j / 3
            d.line([c + math.cos(a) * body * 0.14, c + math.sin(a) * body * 0.14,
                    c + math.cos(a) * body * 0.52, c + math.sin(a) * body * 0.52],
                   fill=col, width=w)
        d.ellipse([c - body * 0.10, c - body * 0.10,
                   c + body * 0.10, c + body * 0.10], fill=col)

    return _glow_stack(shape, (box, box), [
        (3.0 * k, int(alpha * 0.35), rgb, max(2.0, r * 0.07)),
        (1.6 * k, int(alpha * 0.80), rgb, 1.2),
        (0.8 * k, alpha, (238, 244, 255), 0),
    ])


def _sweep_sprite(r, rgb, ph, k):
    """回溯扫掠弧:一道拖着渐隐尾巴的亮弧,ph 决定弧头相位。运行时按
    倒序轮换相位,"时间倒着流"的方向感就出来了。"""
    span = math.pi * 1.05
    head = -2 * math.pi * ph / 12.0
    pad = int(r * 0.20 + 4 * k)
    box = int(r * 2 + pad * 2) + 2
    c = box / 2

    def shape(d, w, col):
        d.arc([c - r, c - r, c + r, c + r],
              start=math.degrees(head - span), end=math.degrees(head),
              fill=col, width=max(1, int(w)))

    return _glow_stack(shape, (box, box), [
        (3.2 * k, 70, rgb, max(2.0, r * 0.06)),
        (1.8 * k, 150, rgb, 1.2),
        (1.0 * k, 255, (242, 236, 255), 0),
    ])


class TimeFX:
    """时之魔女的时停/回溯演出层。

    用法:动作里 play("stop"/"rewind", 秒);render 每帧调一次
    draw(frame, d, cx, feet_y, k, now),播完自动收起 —— pet.py 侧只留
    这一个钩子。素材全部预渲染:时停 = 表盘涟漪(8 档半径)+ 三齿轮
    螺旋环绕(12 旋转档);回溯 = 12 相位倒转扫掠 + 内收光点 + 倒缩
    表盘。精灵总量约 15MB、随建随留 —— 和 _warp_cache 52MB 一个量级,
    桌宠内存预算内。
    """

    ROT_BINS = 12
    STEPS = 8

    def __init__(self, scale, ss):
        self.scale, self.ss = scale, ss
        self.rx = 62 * scale * ss          # 演出基准半径(2x 空间)
        self.mode = None
        self.t0 = 0.0
        self.dur = 1.0
        k = ss
        # 时停:表盘涟漪。整圆(ratio=1.0,和地面的 0.26 压扁环区分开,
        # 这是"悬在她胸口的时间涟漪"),8 档半径向外扩
        self.stop = [_dial_sprite(self.rx * (0.30 + 0.12 * i), 1.0,
                                  MAGIC_A, 190, k) for i in range(self.STEPS)]
        # 齿轮:三档(半径系数, 齿数, 颜色, 转速),各 12 个旋转档
        specs = ((0.42, 8, MAGIC_A, 0.55),
                 (0.28, 10, GOLD_L, -0.85),
                 (0.16, 12, MAGIC_B, 1.30))
        self.gear_spec = specs
        self.gear = [[_gear_sprite(self.rx * rf, teeth,
                                   2 * math.pi * b / self.ROT_BINS, col, 235, k)
                      for b in range(self.ROT_BINS)]
                     for rf, teeth, col, spd in specs]
        # 回溯:扫掠弧 12 相位 + 内收光点
        self.sweep = [_sweep_sprite(self.rx * 0.78, MAGIC_B, ph, k)
                      for ph in range(12)]
        self.mote = _dot_sprite(2.8 * scale * k, MAGIC_A, 200)

    @staticmethod
    def _pc(frame, sp, x, y):
        frame.paste(sp, (int(x - sp.width / 2), int(y - sp.height / 2)), sp)

    def play(self, mode, dur):
        """触发一段演出,render 钩子随后每帧 draw,播完自动收起。"""
        self.mode = mode
        self.t0 = time.time()
        self.dur = max(0.1, float(dur))

    def draw(self, frame, d, cx, feet_y, k, now):
        """每帧一步。feet_y 是她脚下基准(和地面法阵同一水平线)。"""
        if not self.mode:
            return
        p = (now - self.t0) / self.dur
        if p >= 1.0:
            self.mode = None
            return
        if self.mode == "stop":
            self._stop(frame, cx, feet_y, k, now, p)
        elif self.mode == "rewind":
            self._rewind(frame, cx, feet_y, k, now, p)

    # ---- 时停:表盘涟漪扩散 + 三齿轮螺旋切入、环绕、收场飞出 ----
    def _stop(self, frame, cx, cy, k, now, p):
        for delay in (0.0, 0.30, 0.60):
            q = (p - delay) / 0.40
            if 0.0 <= q < 1.0:
                sp = self.stop[min(self.STEPS - 1, int(q * self.STEPS))]
                self._pc(frame, sp, cx, cy - self.rx * 1.7)
        if not 0.10 <= p <= 0.92:
            return
        q_in = min(1.0, (p - 0.10) / 0.26)              # 螺旋切入
        q_out = max(0.0, (p - 0.78) / 0.14)             # 收场飞出
        for gi, (rf, teeth, col, spd) in enumerate(self.gear_spec):
            ring = self.rx * (0.55 + 0.35 * gi) * (1.75 - 0.75 * q_in + 1.2 * q_out)
            ang = now * spd * 2.0 + gi * 2.09
            b = int(now * spd * 3.2 * self.ROT_BINS / (2 * math.pi)) % self.ROT_BINS
            self._pc(frame, self.gear[gi][b],
                     cx + math.cos(ang) * ring,
                     cy - self.rx * 1.7 + math.sin(ang) * ring * 0.55)

    # ---- 回溯:倒缩表盘 + 双向倒转扫掠 + 内收光点 ----
    def _rewind(self, frame, cx, cy, k, now, p):
        q = min(1.0, p / 0.85)
        i = self.STEPS - 1 - min(self.STEPS - 1, int(q * self.STEPS))
        self._pc(frame, self.stop[i], cx, cy - self.rx * 1.7)
        if 0.05 <= p <= 0.92:
            b = int(-now * 1.4 * self.ROT_BINS) % self.ROT_BINS
            for ph, dy in ((b, 0), ((b + 6) % self.ROT_BINS, -self.rx * 0.8)):
                self._pc(frame, self.sweep[ph], cx,
                         cy - self.rx * 1.7 + dy)
            rr = self.rx * (2.4 - 1.9 * (p - 0.05) / 0.87)
            for j in range(8):
                a = 2 * math.pi * j / 8 + now * 0.7
                self._pc(frame, self.mote,
                         cx + math.cos(a) * rr,
                         cy - self.rx * 1.7 + math.sin(a) * rr * 0.5)
