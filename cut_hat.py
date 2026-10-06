# -*- coding: utf-8 -*-
"""把大魔法帽从立绘切成独立图层(assets/hat_layer.png),
底图挖掉"帽檐上缘部分"并沿发际补绘(assets/main.png)。

层序设计:帽檐**下缘以下**的部分(含刘海压住帽檐的那截)留在底图 ——
静止时帽层与底图严丝合缝;帽子摆动时檐下 fringe 保持贴着头发不动,
看起来像"帽檐边缘搭在头发上",只有帽体/帽尖真的动。

备份:assets/main.orig.png(擦扫把前)、assets/main.prehat.png(切帽前)。

**已停用,不要重跑**(2026-10-02):这个脚本的产物是坏的 —— 「帽层」里切进去的是刘海+眼睛,帽子本身留在底图。
重跑会原样再生成同一份坏图层并改写 assets/main.png(10-01 下午就这样
复发过一次)。详见 EXPERIMENTS.md E40 / README「分层渲染」。要做帽/发分层
只能人工抠图 + 补画。确实要拿它做试验时加参数 --i-know-it-is-broken。
"""
import sys
if "--i-know-it-is-broken" not in sys.argv:
    sys.exit("cut 脚本已停用:产物有误,见文件头说明 / EXPERIMENTS.md E40")
import math
import os
import random
from PIL import Image, ImageChops, ImageDraw, ImageFilter

SRC = "assets/main.png"
BACKUP = "assets/main.prehat.png"
HAT_OUT = "assets/hat_layer.png"
OUT = "assets/main.png"

if not os.path.exists(BACKUP):
    Image.open(SRC).save(BACKUP)
im = Image.open(BACKUP).convert("RGBA")
w, h = im.size
px = im.load()

BBOX = (0, 0, 730, 470)


def clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


def is_hairish(r, g, b, a):
    return a > 60 and b > 150 and g > r and b > 140


def is_hat(px, x, y):
    """帽子 = 紫调(r ≥ g-22 的中暗色)+ 帽上装饰。青调亮发(g > r+22)
    和皮肤、冷白高光除外。"""
    r, g, b, a = px[x, y]
    if a < 20:
        return False
    if g > r + 22:
        return False
    if r > 205 and g > 175 and b > 165 and r >= b:
        return False
    if (r + g + b) > 680 and b >= r and abs(r - g) < 25:
        return False
    return True


def in_face_protect(x, y):
    if 270 <= x <= 620 and 402 <= y <= 500:
        return True
    if 380 <= x <= 535 and 426 <= y <= 498:
        return True
    return False


# ---- 1) CC:从锥顶种子找帽子连通域 ----
seed = (480, 150)
seen = set()
stack = [seed]
while stack:
    x, y = stack.pop()
    if (x, y) in seen or not (0 <= x < w and 0 <= y < h):
        continue
    if not (BBOX[0] <= x < BBOX[2] and BBOX[1] <= y < BBOX[3]):
        continue
    if not is_hat(px, x, y) or in_face_protect(x, y):
        continue
    seen.add((x, y))
    stack.extend(((x+1, y), (x-1, y), (x, y+1), (x, y-1)))
print("hat CC pixels:", len(seen))

# ---- 2) 孔洞填充(帽上亮色细节:彩虹带/白花/月饰/高光) ----
outside = set()
stack = [(0, 0), (w-1, 0), (0, h-1), (w-1, h-1)]
while stack:
    x, y = stack.pop()
    if (x, y) in outside or not (0 <= x < w and 0 <= y < h):
        continue
    if (x, y) in seen:
        continue
    outside.add((x, y))
    stack.extend(((x+1, y), (x-1, y), (x, y+1), (x, y-1)))
holes = 0
for y in range(BBOX[1], BBOX[3]):
    for x in range(BBOX[0], BBOX[2]):
        if (x, y) not in seen and (x, y) not in outside:
            if px[x, y][3] > 20 and not in_face_protect(x, y):
                seen.add((x, y))
                holes += 1
print("holes filled:", holes)

# ---- 3) 帽檐下缘线:线以下(刘海/眼睛/檐下 fringe)留在底图 ----
BRIM_LINE = [(0, 250), (120, 258), (200, 262), (280, 253), (360, 268),
             (440, 288), (520, 330), (600, 388), (680, 438), (730, 452)]

mask_cc = Image.new("L", (w, h), 0)
md = ImageDraw.Draw(mask_cc)
for (x, y) in seen:
    if px[x, y][3] > 20:
        md.point((x, y), fill=255)
below = Image.new("L", (w, h), 0)
ImageDraw.Draw(below).polygon(BRIM_LINE + [(730, h), (0, h)], fill=255)

hat_mask = mask_cc.copy()
hat_mask.paste(0, (0, 0, w, h), ImageChops.invert(below))
hat_mask = hat_mask.filter(ImageFilter.GaussianBlur(1.2))

erase_mask = hat_mask

hat = im.copy()
hat.putalpha(ImageChops.multiply(hat.getchannel("A"), hat_mask))
hat.crop((0, 0, w, 500)).save(HAT_OUT)   # 裁掉下方空白:变形/推帧省 1/3

# ---- 4) 底图擦除 + 发穹顶补绘(只补檐上擦除区) ----
im2 = im.copy()
im2.putalpha(ImageChops.subtract(im2.getchannel("A"), erase_mask))
p2 = im2.load()
erased = set()
ep = erase_mask.load()
for y in range(150, 470):
    for x in range(0, w):
        if ep[x, y] > 40:
            erased.add((x, y))

rng = random.Random(42)
left_c, right_c = {}, {}
for y in range(300, 470):
    ls, rs = [], []
    for x in range(215, 300):
        r, g, b, a = px[x, y]
        if a > 60 and is_hairish(r, g, b, a):
            ls.append((r, g, b))
    for x in range(500, 615):
        r, g, b, a = px[x, y]
        if a > 60 and is_hairish(r, g, b, a):
            rs.append((r, g, b))
    if ls:
        left_c[y] = tuple(sum(c[i] for c in ls) // len(ls) for i in range(3))
    if rs:
        right_c[y] = tuple(sum(c[i] for c in rs) // len(rs) for i in range(3))

filled = 0
for x in range(210, 600):
    dome_top = 306 + 16 * math.sin(math.pi * (x - 210) / 390.0)
    for y in range(462, int(dome_top), -1):
        if (x, y) not in erased:
            continue
        lc = left_c.get(y) or left_c.get(y + 1) or left_c.get(y - 1)
        rc = right_c.get(y) or right_c.get(y + 1) or right_c.get(y - 1)
        if not lc and not rc:
            continue
        lc = lc or rc
        rc = rc or lc
        tpos = clamp((x - 210) / 390.0, 0.0, 1.0)
        k = max(0.70, 1.0 - 0.30 * clamp((462 - y) / 130.0, 0.0, 1.0))
        n = rng.uniform(-3, 3)
        edge = 1.0
        if x > 540:
            edge *= clamp((585 - x) / 45.0, 0.0, 1.0)
        if x < 235:
            edge *= clamp((x - 210) / 25.0, 0.0, 1.0)
        if y < 332:
            edge *= clamp((y - 300) / 32.0, 0.0, 1.0)
        alpha = int(255 * edge)
        if alpha <= 6:
            continue
        p2[x, y] = (int(clamp((lc[0] * (1 - tpos) + rc[0] * tpos) * k + n, 0, 255)),
                    int(clamp((lc[1] * (1 - tpos) + rc[1] * tpos) * k + n, 0, 255)),
                    int(clamp((lc[2] * (1 - tpos) + rc[2] * tpos) * k + n, 0, 255)),
                    alpha)
        filled += 1
print("infill pixels:", filled)
im2.save(OUT)

# ---- 5) 预览:静止位置合成应无缝复原 ----
bg = Image.new("RGBA", (w, h), (26, 20, 43, 255))
comp = Image.alpha_composite(bg, im2)
comp = Image.alpha_composite(comp, hat)
side = Image.new("RGB", (w * 2 + 10, h), (60, 60, 60))
side.paste(Image.alpha_composite(bg, im).convert("RGB"), (0, 0))
side.paste(comp.convert("RGB"), (w + 10, 0))
side.resize((w, h // 2)).save("_cut_check.png")
hat_vis = Image.alpha_composite(bg, hat).convert("RGB")
hat_vis.resize((w // 2, h // 2)).save("_hat_layer_check.png")
print("done -> _cut_check.png / _hat_layer_check.png")
