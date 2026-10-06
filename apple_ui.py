"""Quiet dark material and controls, shared by the chat, the AI reader and
the capsule.  Restraint over ornament (Apple-like: hairline borders, generous
radii, crisp text, one accent per meaning) — but in the witch's violet, the same
palette as the moon-house board (2026-10-05: graphite lost the theme).

Everything is PIL (cached by size); Tk widgets only show the images.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# witch violet, dark appearance (= moon_board FACE / INK / DIM / PURPLE)
BG = (37, 28, 53)            # window (#251c35)
ELEV = (52, 40, 72)          # raised: fields, buttons, received bubbles
ELEV2 = (64, 50, 88)         # hover
ELEV3 = (78, 62, 104)        # pressed
SEP = (74, 60, 96)
TEXT = (245, 239, 230)
TEXT2 = (181, 168, 199)
TEXT3 = (122, 110, 140)
BLUE = (124, 88, 184)        # 'mine' bubbles / send: lilac (name kept for callers)
PURPLE = (191, 90, 242)
GREEN = (48, 209, 88)
ORANGE = (255, 159, 10)
RED = (255, 69, 58)
YELLOW = (255, 214, 10)
HAIR = (214, 189, 148, 70)   # thin gold hairline on dark surfaces

NOTO = Path("C:/Windows/Fonts/NotoSansSC-VF.ttf")
TK_FAMILY = "Noto Sans SC"
TK_MEDIUM = "Noto Sans SC Medium"


def hexc(rgb):
    return "#%02x%02x%02x" % tuple(rgb[:3])


@lru_cache(maxsize=32)
def font(px, weight=400):
    """Noto Sans SC at a variable weight; falls back to the pet font."""
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


def tk_font(px, medium=False):
    """Tk font tuple in the same family (negative size = pixels)."""
    return (TK_MEDIUM if medium else TK_FAMILY, -max(8, int(px)))


def _rounded(size, radius, fill, outline=None, width=1, ss=3):
    w, h = size
    big = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), radius=radius * ss,
                                          fill=fill, outline=outline, width=width * ss if outline else 0)
    return big.resize((w, h), Image.LANCZOS)


@lru_cache(maxsize=64)
def pill(w, h, state="normal", accent=None, base=None):
    """Capsule button. state: normal/hover/pressed/disabled; accent = rgb fill."""
    w, h = max(2, int(w)), max(2, int(h))
    if accent:
        k = {"normal": 1.0, "hover": 1.1, "pressed": .85, "disabled": .45}[state]
        fill = tuple(min(255, int(c * k)) for c in accent) + (255,)
        if state == "disabled":
            fill = ELEV + (255,)
    else:
        fill = {"normal": ELEV, "hover": ELEV2, "pressed": ELEV3, "disabled": ELEV}[state] + (255,)
    img = Image.new("RGBA", (w, h), (base or BG) + (255,))
    img.alpha_composite(_rounded((w, h), h // 2, fill))
    return img


@lru_cache(maxsize=32)
def circle_button(d, glyph, state="normal", accent=None, base=None):
    """Round icon button: '×' close, '↑' send."""
    d = max(8, int(d))
    if accent and state != "disabled":
        k = {"normal": 1.0, "hover": 1.1, "pressed": .85}.get(state, 1.0)
        fill = tuple(min(255, int(c * k)) for c in accent)
        ink = (255, 255, 255, 255)
    else:
        fill = {"normal": ELEV, "hover": ELEV2, "pressed": ELEV3, "disabled": ELEV}[state]
        ink = (TEXT2 if state != "disabled" else TEXT3) + (255,)
    ss = 4
    big = Image.new("RGBA", (d * ss, d * ss), (base or BG) + (255,))
    g = ImageDraw.Draw(big)
    g.ellipse((0, 0, d * ss - 1, d * ss - 1), fill=fill + (255,))
    c, r, w = d * ss / 2, d * ss * .2, max(2, int(d * ss * .085))
    if glyph == "×":
        g.line((c - r, c - r, c + r, c + r), fill=ink, width=w)
        g.line((c - r, c + r, c + r, c - r), fill=ink, width=w)
    elif glyph == "↑":
        g.line((c, c + r * 1.25, c, c - r * 1.2), fill=ink, width=w)
        g.line((c - r * 1.05, c - r * .2, c, c - r * 1.25, c + r * 1.05, c - r * .2), fill=ink, width=w, joint="curve")
    return big.resize((d, d), Image.LANCZOS)


def wrap(text, f, width):
    """Line-wrap for CJK and Latin: CJK breaks anywhere, Latin at spaces."""
    lines = []
    for para in str(text).split("\n"):
        line, word = "", ""
        tokens = []
        for ch in para:
            if ch.isascii() and not ch.isspace():
                word += ch
                continue
            if word:
                tokens.append(word)
                word = ""
            tokens.append(ch)
        if word:
            tokens.append(word)
        for tok in tokens:
            if f.getlength(line + tok) <= width or not line:
                if f.getlength(tok) > width:        # a very long word: hard break
                    for ch in tok:
                        if f.getlength(line + ch) > width and line:
                            lines.append(line)
                            line = ""
                        line += ch
                else:
                    line += tok
            else:
                lines.append(line.rstrip())
                line = tok.lstrip()
        lines.append(line)
    return lines or [""]


def bubble(text, max_w, f, mine, count=1, small=None, base=BG):
    """Messages-style bubble: yours blue on the right, hers graphite on the left.
    A repeat counter (×N) sits inside the bubble in a quieter tone."""
    pad_x, pad_y = round(f.size * .8), round(f.size * .5)
    lines = wrap(text, f, max_w - 2 * pad_x)
    lh = round(f.size * 1.42)
    tail = f"  ×{count}" if count > 1 else ""
    small = small or f
    widths = [f.getlength(s) for s in lines]
    widths[-1] += small.getlength(tail) if tail else 0
    w = int(min(max_w, max(widths) + 2 * pad_x)) + 1
    h = int(lh * len(lines) + 2 * pad_y)
    fill = (BLUE if mine else ELEV) + (255,)
    img = Image.new("RGBA", (w, h), base + (255,))
    img.alpha_composite(_rounded((w, h), min(round(f.size * 1.05), h // 2), fill))
    d = ImageDraw.Draw(img)
    ink = (255, 255, 255, 255) if mine else TEXT + (255,)
    for i, s in enumerate(lines):
        d.text((pad_x, pad_y + i * lh + lh / 2), s, font=f, fill=ink, anchor="lm")
    if tail:
        d.text((pad_x + f.getlength(lines[-1]), pad_y + (len(lines) - 1) * lh + lh / 2), tail,
               font=small, fill=(255, 255, 255, 170) if mine else TEXT2 + (255,), anchor="lm")
    return img


def typing_bubble(f, phase, base=BG):
    """Three dots, the lit one walking (the classic 'is typing')."""
    h = int(f.size * 1.42 + f.size)
    w = int(h * 1.9)
    img = Image.new("RGBA", (w, h), base + (255,))
    img.alpha_composite(_rounded((w, h), h // 2, ELEV + (255,)))
    d = ImageDraw.Draw(img)
    r = h * .1
    for i in range(3):
        cx = w / 2 + (i - 1) * r * 3.2
        a = 255 if i == phase % 3 else 110
        d.ellipse((cx - r, h / 2 - r, cx + r, h / 2 + r), fill=TEXT2 + (a,))
    return img


def window(w, h, radius, key):
    """Dark rounded window surface with a hairline edge on a key colour."""
    img = Image.new("RGBA", (w, h), key + (255,) if isinstance(key, tuple) else key)
    img.alpha_composite(_rounded((w, h), radius, BG + (255,), outline=HAIR, width=1))
    return img


@lru_cache(maxsize=16)
def panel(w, h, r):
    """Reader surface with the (image, pad) contract of ui3d panels.  The reader
    is a key-coloured Tk window (binary transparency), so a soft shadow would
    turn into a dark fringe: graphite body + hairline only."""
    w, h, r = max(8, int(w)), max(8, int(h)), max(2, int(r))
    pad = 2
    img = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    img.alpha_composite(_rounded((w, h), r, BG + (255,), outline=HAIR, width=1), (pad, pad))
    return img, pad
