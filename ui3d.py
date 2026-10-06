# -*- coding: utf-8 -*-
"""界面的"立体"材质:紫天鹅绒面板 + 金边 + 水晶高光,和秋千原画同一套语言。

原来的面板/气泡/灯板都是"深紫平涂 + 一圈细金线",没有光、没有厚度、
没有投影,看着像贴纸。这里统一给出:
  - 柔和投影(往下偏,面板浮在桌面上)
  - 顶亮底暗的竖向渐变 + 上缘一抹玻璃高光(光从上方来)
  - 金色描边自上而下由亮金过渡到古铜,内侧一圈暗线压出厚度
  - 四角小金钉(呼应原画里坐垫/横杆上的菱形金饰)
  - 灯板的状态灯换成带高光的水晶球

只用 PIL;结果按尺寸缓存,逐帧调用只是查表 + 贴图。
"""
import math
from collections import OrderedDict

from PIL import Image, ImageChops, ImageDraw, ImageFilter

# 主题色(和 pet.py 的 UI_* / BOOK_* 同色系)
TOP = (66, 48, 112)          # 面板顶部
BOTTOM = (22, 14, 42)        # 面板底部
GOLD_HI = (255, 230, 150)    # 金边高光
GOLD_LO = (150, 98, 42)      # 金边暗部(古铜)
SHEEN = (255, 255, 255)

# Opt-in quiet materials. Existing panel/button callers keep their original look.
# 克制的魔女紫:近乎平的紫面、一道细金边、淡紫强调(与月窗小屋书板一致)
CALM_TOP = (43, 32, 58)
CALM_BOTTOM = (30, 22, 42)
CALM_GOLD = (214, 189, 148)
CALM_TEXT = (245, 239, 230)
CALM_MUTED = (181, 168, 199)
CALM_ACCENT = (193, 154, 239)

_cache = OrderedDict()


def _memo(key, build, cap=96):
    hit = _cache.get(key)
    if hit is None:
        hit = build()
        _cache[key] = hit
        while len(_cache) > cap:
            _cache.popitem(last=False)
    else:
        _cache.move_to_end(key)
    return hit


def _vgrad(w, h, top, bottom, alpha=255):
    """竖向渐变(1px 宽再拉伸,便宜)。"""
    col = Image.new("RGBA", (1, max(1, h)))
    for y in range(max(1, h)):
        t = y / max(1, h - 1)
        # 稍微偏向暗部,像布料受光
        t = t ** 0.85
        col.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (alpha,))
    return col.resize((max(1, w), max(1, h)), Image.BILINEAR)


def _rmask(w, h, r, inset=0.0):
    """抗锯齿圆角遮罩(4 倍超采样画再缩回)。"""
    s = 4
    m = Image.new("L", (w * s, h * s), 0)
    ImageDraw.Draw(m).rounded_rectangle(
        (inset * s, inset * s, (w - inset) * s - 1, (h - inset) * s - 1),
        radius=max(0, (r - inset) * s), fill=255)
    return m.resize((w, h), Image.LANCZOS)


def shadow_pad(k=1.0):
    """面板四周给投影留的边(画布比面板大这么多;内容坐标要加上它)。"""
    return int(math.ceil(10 * k))


def panel(w, h, r, k=1.0, alpha=246, tone=None, studs=True, glow=None):
    """立体面板。返回 (图, pad):图比 w×h 大 pad 一圈(投影),面板本体
    左上角在 (pad, pad)。tone=(top, bottom) 换底色;glow=(r,g,b) 给面板
    内一圈状态色辉光(比如水晶提示框随状态)。"""
    w, h, r = max(8, int(w)), max(8, int(h)), max(2, int(r))
    key = ("panel", w, h, r, round(k, 2), alpha, tone, studs, glow)

    def build():
        pad = shadow_pad(k)
        top, bottom = tone or (TOP, BOTTOM)
        out = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
        # 1) 投影:往下偏 3k,模糊 5k
        sm = Image.new("L", out.size, 0)
        sm.paste(_rmask(w, h, r), (pad, pad + int(4 * k)))
        sm = sm.filter(ImageFilter.GaussianBlur(5 * k))
        shadow = Image.new("RGBA", out.size, (8, 4, 18, 0))
        shadow.putalpha(sm.point(lambda v: v * 175 // 255))
        out.alpha_composite(shadow)
        # 2) 本体:竖向渐变
        body = _vgrad(w, h, top, bottom, alpha)
        mask = _rmask(w, h, r)
        body.putalpha(ImageChops.multiply(body.getchannel("A"), mask))
        # 3) 上缘玻璃高光:顶部一条柔和的亮带,越往下越淡
        sheen = Image.new("L", (w, h), 0)
        sd = ImageDraw.Draw(sheen)
        sd.rounded_rectangle((2 * k, 1.5 * k, w - 2 * k, h * 0.46), radius=max(1, r - 2 * k), fill=255)
        sheen = sheen.filter(ImageFilter.GaussianBlur(max(1, h * 0.10)))
        fade = _vgrad(1, h, (255, 255, 255), (0, 0, 0)).convert("L").resize((w, h))
        sheen = ImageChops.multiply(sheen, fade)
        sheen = ImageChops.multiply(sheen, _rmask(w, h, r, inset=1.5 * k))
        hl = Image.new("RGBA", (w, h), SHEEN + (0,))
        hl.putalpha(sheen.point(lambda v: v * 50 // 255))
        body.alpha_composite(hl)
        if glow:
            g = Image.new("L", (w, h), 0)
            ImageDraw.Draw(g).rounded_rectangle((0, 0, w - 1, h - 1), radius=r, outline=255,
                                                width=max(2, int(5 * k)))
            g = ImageChops.multiply(g.filter(ImageFilter.GaussianBlur(4 * k)), mask)
            gi = Image.new("RGBA", (w, h), glow + (0,))
            gi.putalpha(g.point(lambda v: v * 120 // 255))
            body.alpha_composite(gi)
        out.alpha_composite(body, (pad, pad))
        # 4) 金边:外圈渐变金(上亮下暗),内侧一圈暗线压出厚度
        bw = 2.0 * k                        # 金边宽:够宽才读得出"框"的厚度
        ring = ImageChops.subtract(_rmask(w, h, r), _rmask(w, h, r, inset=bw))
        gold = _vgrad(w, h, GOLD_HI, GOLD_LO)
        gold.putalpha(ring.point(lambda v: v * 240 // 255))
        # 金边上半圈再提一道亮:斜面受光
        bevel = ImageChops.subtract(_rmask(w, h, r), _rmask(w, h, r, inset=bw * 0.5))
        bevel = ImageChops.multiply(bevel, _vgrad(1, h, (255, 255, 255), (0, 0, 0)).convert("L").resize((w, h)))
        shine = Image.new("RGBA", (w, h), (255, 248, 215, 0))
        shine.putalpha(bevel.point(lambda v: v * 150 // 255))
        inner = ImageChops.subtract(_rmask(w, h, r, inset=bw), _rmask(w, h, r, inset=bw + 1.3 * k))
        dark = Image.new("RGBA", (w, h), (10, 6, 22, 0))
        dark.putalpha(inner.point(lambda v: v * 170 // 255))
        lip = ImageChops.subtract(_rmask(w, h, r, inset=bw + 1.3 * k), _rmask(w, h, r, inset=bw + 2.3 * k))
        lipm = ImageChops.multiply(lip, _vgrad(1, h, (255, 255, 255), (0, 0, 0)).convert("L").resize((w, h)))
        light = Image.new("RGBA", (w, h), (220, 200, 255, 0))
        light.putalpha(lipm.point(lambda v: v * 70 // 255))
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        for im in (dark, light, gold, shine):
            layer.alpha_composite(im)
        out.alpha_composite(layer, (pad, pad))
        # 5) 四角小金钉(菱形),面板够大才放
        if studs and w > 120 * k and h > 52 * k:     # 小气泡上放钉子显得挤
            st = stud(max(2.0, 2.6 * k))
            off = r * 0.55
            for cx, cy in ((off, off), (w - off, off), (off, h - off), (w - off, h - off)):
                out.alpha_composite(st, (int(pad + cx - st.width / 2), int(pad + cy - st.height / 2)))
        return out, pad

    return _memo(key, build)


def stud(rr):
    """菱形小金钉,带高光。"""
    key = ("stud", round(rr, 1))

    def build():
        s = 4
        n = int(math.ceil(rr * 2 + 2))
        im = Image.new("RGBA", (n * s, n * s), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        c = n * s / 2
        R = rr * s
        d.polygon([(c, c - R), (c + R * 0.8, c), (c, c + R), (c - R * 0.8, c)], fill=GOLD_LO + (255,))
        d.polygon([(c, c - R), (c + R * 0.8, c), (c, c)], fill=GOLD_HI + (255,))
        d.polygon([(c, c - R), (c - R * 0.8, c), (c, c)], fill=(255, 214, 120, 255))
        return im.resize((n, n), Image.LANCZOS)

    return _memo(key, build)


def tail(w, h, k=1.0, alpha=246, tone=None):
    """气泡尾巴(向下的小三角,同材质)。返回图,顶边中点对齐气泡底边中点。"""
    key = ("tail", int(w), int(h), round(k, 2), alpha, tone)

    def build():
        top, bottom = tone or (TOP, BOTTOM)
        s = 4
        W, H = int(w) * s, int(h) * s
        m = Image.new("L", (W, H), 0)
        ImageDraw.Draw(m).polygon([(0, 0), (W, 0), (W / 2, H)], fill=255)
        m = m.resize((int(w), int(h)), Image.LANCZOS)
        body = Image.new("RGBA", (int(w), int(h)), bottom + (0,))
        body.putalpha(m.point(lambda v: v * alpha // 255))
        e = Image.new("L", (W, H), 0)
        ImageDraw.Draw(e).line([(0, 0), (W / 2, H), (W, 0)], fill=255, width=int(1.4 * k * s))
        e = e.resize((int(w), int(h)), Image.LANCZOS)
        g = Image.new("RGBA", (int(w), int(h)), GOLD_LO + (0,))
        g.putalpha(e.point(lambda v: v * 220 // 255))
        body.alpha_composite(g)
        return body

    return _memo(key, build)


def gem(r, rgb, hollow=False, glow=True):
    """水晶球状态灯:径向明暗 + 左上高光 + 底部反光 + 同色外辉。返回图,
    球心在图中心。hollow=空闲(只剩一圈玻璃壳)。"""
    r = max(3, int(round(r)))
    key = ("gem", r, tuple(rgb), hollow, glow)

    def build():
        s = 4
        pad = r if glow else 1
        n = (r + pad) * 2
        im = Image.new("RGBA", (n * s, n * s), (0, 0, 0, 0))
        c, R = n * s / 2, r * s
        if glow and not hollow:
            gl = Image.new("L", im.size, 0)
            ImageDraw.Draw(gl).ellipse((c - R * 1.35, c - R * 1.35, c + R * 1.35, c + R * 1.35), fill=255)
            gl = gl.filter(ImageFilter.GaussianBlur(R * 0.5))
            gi = Image.new("RGBA", im.size, tuple(rgb) + (0,))
            gi.putalpha(gl.point(lambda v: v * 110 // 255))
            im.alpha_composite(gi)
        d = ImageDraw.Draw(im)
        if hollow:
            d.ellipse((c - R, c - R, c + R, c + R), fill=(40, 30, 70, 120),
                      outline=tuple(min(255, v + 30) for v in rgb) + (210,), width=int(1.6 * s))
        else:
            # 径向:从球心偏左上的亮色,向边缘过渡到深色
            steps = 14
            for i in range(steps, 0, -1):
                t = i / steps
                rr = R * t
                ox, oy = -R * 0.18 * (1 - t), -R * 0.22 * (1 - t)
                col = tuple(int(rgb[j] * (0.55 + 0.6 * (1 - t)) + 40 * (1 - t)) for j in range(3))
                col = tuple(min(255, v) for v in col)
                d.ellipse((c + ox - rr, c + oy - rr, c + ox + rr, c + oy + rr), fill=col + (255,))
            d.ellipse((c - R, c - R, c + R, c + R), outline=(20, 12, 36, 200), width=int(1.0 * s))
            # 底部反光
            d.chord((c - R * 0.62, c + R * 0.25, c + R * 0.62, c + R * 0.86), 0, 180,
                    fill=tuple(min(255, v + 70) for v in rgb) + (90,))
        # 左上高光
        d.ellipse((c - R * 0.58, c - R * 0.64, c - R * 0.05, c - R * 0.18), fill=(255, 255, 255, 200))
        return im.resize((n, n), Image.LANCZOS)

    return _memo(key, build)


def button(w, h, r, k=1.0, state="normal", accent=False):
    """凸起按钮:normal / hover / pressed / disabled。accent=主按钮(偏亮紫)。"""
    key = ("button", int(w), int(h), int(r), round(k, 2), state, accent)

    def build():
        if accent:
            top, bottom = (138, 104, 222), (70, 46, 140)
        else:
            top, bottom = (84, 64, 138), (40, 28, 76)
        if state == "hover":
            top = tuple(min(255, v + 22) for v in top)
            bottom = tuple(min(255, v + 12) for v in bottom)
        elif state == "pressed":
            # 按下:亮暗倒过来再整体压暗一点,像陷进去
            top, bottom = (tuple(int(v * 0.8) for v in bottom),
                           tuple(int(v * 0.95) for v in top))
        elif state == "disabled":
            top, bottom = (58, 52, 76), (38, 34, 52)
        im, pad = panel(w, h, r, k=k * 0.6, tone=(top, bottom), studs=False)
        return im, pad

    return _memo(key, build)


def calm_panel(w, h, r, k=1.0, alpha=246, tone=None, studs=True, glow=None):
    """Quiet violet material with the same (image, pad) contract as panel.

    The reading area is at least 244/255 opaque. Only the rounded silhouette and
    a small downward shadow are transparent; this does not blur the desktop.
    studs/glow remain accepted for call compatibility but are not rendered.
    """
    w, h, r = max(8, int(w)), max(8, int(h)), max(2, int(r))
    k = max(.05, float(k))
    alpha = max(244, min(255, int(alpha)))
    top, bottom = ((tuple(tone[0]), tuple(tone[1])) if tone
                   else (CALM_TOP, CALM_BOTTOM))
    key = ("calm_panel", w, h, r, round(k, 2), alpha, top, bottom)

    def build():
        pad = shadow_pad(k)
        out = Image.new("RGBA", (w + 2 * pad, h + 2 * pad))
        mask = _rmask(w, h, r)
        sm = Image.new("L", out.size)
        sm.paste(mask, (pad, pad + round(2 * k)))
        sm = sm.filter(ImageFilter.GaussianBlur(3 * k))
        shadow = Image.new("RGBA", out.size, (9, 6, 18, 0))
        shadow.putalpha(sm.point(lambda v: v * 66 // 255))
        out.alpha_composite(shadow)
        body = _vgrad(w, h, top, bottom, alpha)
        body.putalpha(ImageChops.multiply(body.getchannel("A"), mask))
        # One thin edge, brightest at the upper rim. No bevel or inset groove.
        ring = ImageChops.subtract(mask, _rmask(w, h, r, inset=max(.75, min(1.1, k))))
        edge = Image.new("RGBA", (w, h), CALM_GOLD + (0,))
        fade = _vgrad(w, h, (96, 96, 96), (36, 36, 36)).convert("L")
        edge.putalpha(ImageChops.multiply(ring, fade))
        body.alpha_composite(edge)
        out.alpha_composite(body, (pad, pad))
        return out, pad

    return _memo(key, build)


def calm_button(w, h, r, k=1.0, state="normal", accent=False):
    """Rounded, low-contrast button; signature and return match button()."""
    key = ("calm_button", int(w), int(h), int(r), round(k, 2), state, accent)

    def build():
        top, bottom = (((132, 96, 192), (110, 78, 168)) if accent
                       else ((60, 47, 80), (50, 39, 68)))
        if state == "hover":
            top = tuple(min(255, v + 8) for v in top)
            bottom = tuple(min(255, v + 6) for v in bottom)
        elif state == "pressed":
            top = tuple(max(0, v - 7) for v in top)
            bottom = tuple(max(0, v - 5) for v in bottom)
        elif state == "disabled":
            top, bottom = (44, 36, 56), (38, 31, 48)
        return calm_panel(w, h, r, k=k * .6, alpha=250,
                          tone=(top, bottom), studs=False)

    return _memo(key, build)


def cylinder(w, h, rgb):
    """竖放的圆柱(卷轴杆):横向明暗(左 1/3 处最亮、两侧压暗)+ 细金边。"""
    key = ("cyl", int(w), int(h), tuple(rgb))

    def build():
        w_, h_ = max(2, int(w)), max(2, int(h))
        row = Image.new("RGBA", (w_, 1))
        for x in range(w_):
            t = (x + 0.5) / w_
            shade = 0.55 + 0.75 * math.exp(-((t - 0.34) / 0.28) ** 2)
            row.putpixel((x, 0), tuple(min(255, int(c * shade)) for c in rgb) + (255,))
        body = row.resize((w_, h_), Image.NEAREST)
        body.putalpha(_rmask(w_, h_, w_ / 2))
        ring = ImageChops.subtract(_rmask(w_, h_, w_ / 2), _rmask(w_, h_, w_ / 2, inset=0.9))
        g = Image.new("RGBA", (w_, h_), GOLD_HI + (0,))
        g.putalpha(ring.point(lambda v: v * 170 // 255))
        body.alpha_composite(g)
        return body

    return _memo(key, build)


def frame_overlay(w, h, r, k=1.0, studs=True):
    """只有"框"的部分(金边斜面 + 内侧暗线 + 受光边 + 上缘玻璃高光 + 金钉),
    叠在已有底图上用(聊天窗这种自己画渐变星空底的窗口)。"""
    w, h, r = int(w), int(h), int(r)
    key = ("frame", w, h, r, round(k, 2), studs)

    def build():
        out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sheen = Image.new("L", (w, h), 0)
        ImageDraw.Draw(sheen).rounded_rectangle((3 * k, 2 * k, w - 3 * k, h * 0.30),
                                                radius=max(1, r - 3 * k), fill=255)
        sheen = sheen.filter(ImageFilter.GaussianBlur(max(1, h * 0.06)))
        sheen = ImageChops.multiply(sheen, _vgrad(1, h, (255, 255, 255), (0, 0, 0)).convert("L").resize((w, h)))
        hl = Image.new("RGBA", (w, h), SHEEN + (0,))
        hl.putalpha(sheen.point(lambda v: v * 30 // 255))
        out.alpha_composite(hl)
        bw = 2.2 * k
        ring = ImageChops.subtract(_rmask(w, h, r), _rmask(w, h, r, inset=bw))
        gold = _vgrad(w, h, GOLD_HI, GOLD_LO)
        gold.putalpha(ring.point(lambda v: v * 240 // 255))
        bevel = ImageChops.subtract(_rmask(w, h, r), _rmask(w, h, r, inset=bw * 0.5))
        bevel = ImageChops.multiply(bevel, _vgrad(1, h, (255, 255, 255), (0, 0, 0)).convert("L").resize((w, h)))
        shine = Image.new("RGBA", (w, h), (255, 248, 215, 0))
        shine.putalpha(bevel.point(lambda v: v * 150 // 255))
        inner = ImageChops.subtract(_rmask(w, h, r, inset=bw), _rmask(w, h, r, inset=bw + 1.4 * k))
        dark = Image.new("RGBA", (w, h), (10, 6, 22, 0))
        dark.putalpha(inner.point(lambda v: v * 170 // 255))
        for im in (dark, gold, shine):
            out.alpha_composite(im)
        if studs:
            st = stud(max(2.0, 3.0 * k))
            off = r * 0.55
            for cx, cy in ((off, off), (w - off, off), (off, h - off), (w - off, h - off)):
                out.alpha_composite(st, (int(cx - st.width / 2), int(cy - st.height / 2)))
        return out

    return _memo(key, build, cap=96)


def well(w, h, r, k=1.0):
    """下凹的槽(输入框/记录区底下):深色底,上沿内阴影、下沿受光,细金边。"""
    w, h, r = int(w), int(h), int(r)
    key = ("well", w, h, r, round(k, 2))

    def build():
        out = _vgrad(w, h, (12, 8, 26), (30, 22, 56), 255)
        mask = _rmask(w, h, r)
        out.putalpha(mask)
        top = Image.new("L", (w, h), 0)
        ImageDraw.Draw(top).rounded_rectangle((0, 0, w - 1, int(6 * k)), radius=r, fill=255)
        top = ImageChops.multiply(top.filter(ImageFilter.GaussianBlur(2.5 * k)), mask)
        sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sh.putalpha(top.point(lambda v: v * 150 // 255))
        out.alpha_composite(sh)
        bot = ImageChops.subtract(_rmask(w, h, r), _rmask(w, h, r, inset=1.0 * k))
        bot = ImageChops.multiply(bot, _vgrad(1, h, (0, 0, 0), (255, 255, 255)).convert("L").resize((w, h)))
        li = Image.new("RGBA", (w, h), (200, 180, 255, 0))
        li.putalpha(bot.point(lambda v: v * 110 // 255))
        out.alpha_composite(li)
        edge = ImageChops.subtract(_rmask(w, h, r), _rmask(w, h, r, inset=0.8 * k))
        g = Image.new("RGBA", (w, h), GOLD_LO + (0,))
        g.putalpha(edge.point(lambda v: v * 120 // 255))
        out.alpha_composite(g)
        return out

    return _memo(key, build, cap=96)
