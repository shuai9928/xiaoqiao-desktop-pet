# -*- coding: utf-8 -*-
"""把前发/侧发/后发从立绘切成独立图层(assets/hair_layer.png),
底图挖掉头发(assets/main.png)—— 发层带自己的摆动物理,
帽子已在此前一步切走(assets/hat_layer.png)。

发层 CC 从 assets/main.prehat.png(切帽前原图)取色:那上面还没有
"发穹顶补绘",合成出来的发穹顶不会被误卷进发层 —— 它留在底图,
作为帽子摆动时露出的"头盖骨"。

备份:assets/main.orig.png / main.prehat.png / main.prehair.png。

**已停用,不要重跑**(2026-10-02):这个脚本的产物是坏的 —— 发层把一只眼睛和直角矩形边一起切了进去,底图脸部补成横向条纹。
重跑会原样再生成同一份坏图层并改写 assets/main.png(10-01 下午就这样
复发过一次)。详见 EXPERIMENTS.md E40 / README「分层渲染」。要做帽/发分层
只能人工抠图 + 补画。确实要拿它做试验时加参数 --i-know-it-is-broken。
"""
import sys
if "--i-know-it-is-broken" not in sys.argv:
    sys.exit("cut 脚本已停用:产物有误,见文件头说明 / EXPERIMENTS.md E40")
import math
import os
from PIL import Image, ImageChops, ImageDraw, ImageFilter

SRC = "assets/main.png"            # 当前底图(无帽)
PRE = "assets/main.prehat.png"     # 切帽前原图(发色取样源)
HAIR_OUT = "assets/hair_layer.png"
OUT = "assets/main.png"

if not os.path.exists("assets/main.prehair.png"):
    Image.open(SRC).save("assets/main.prehair.png")

pre = Image.open(PRE).convert("RGBA")
pw, ph = pre.size
pp = pre.load()
im = Image.open("assets/main.prehair.png").convert("RGBA")  # 永远从备份重建,不继承上一次的损坏

BBOX = (150, 240, 660, 660)        # 发区:帽檐线以下到肩/裙
BRIM_LINE = [(0, 250), (120, 258), (200, 262), (280, 253), (360, 268),
             (440, 288), (520, 330), (600, 388), (680, 438), (730, 452)]


def clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


def brim_y(x):
    """帽檐下缘线在 x 处的 y。线以上是帽子,不算头发。"""
    pts = BRIM_LINE
    for i in range(len(pts) - 1):
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / max(1, (x1 - x0))
    return pts[-1][1]


def is_hairish(r, g, b, a):
    """发色宽判(BFS 用):亮青蓝发 + 发丝间的深蓝描边都要能过。
    拒:暖调(皮肤/黄饰)、紫缎带(r << g 的反例)、胸口暗紫阴影
    (b-g 不够大)、近白裙。发内高光被拒没关系 —— 那是小"孔洞",
    会由孔洞填充回收。"""
    if a <= 40:
        return False
    if r > b + 10:                              # 暖调:皮肤/黄发饰
        return False
    if (r + g + b) > 640 and abs(r - g) < 30:   # 近白:白裙
        return False
    if g < r - 25:                              # 紫缎带类
        return False
    return (b > g + 42) or (b > 150 and g > r)


def in_eye_protect(x, y):
    """双眼精确框:CC 不收、底图不擦;但泛洪可以穿过(否则眼睛会变成
    "孔洞"被填进发层)。"""
    if 240 <= x <= 340 and 340 <= y <= 452:   # 左眼
        return True
    if 412 <= x <= 522 and 333 <= y <= 447:   # 右眼
        return True
    return False


# ---- 1) CC:从刘海种子找头发连通域(在切帽前原图上取色) ----
seed = (350, 300)          # 刘海中上(避开眼保护框)
seen = set()
stack = [seed]
while stack:
    x, y = stack.pop()
    if (x, y) in seen or not (BBOX[0] <= x < BBOX[2] and BBOX[1] <= y < BBOX[3]):
        continue
    if y < brim_y(x) + 2:              # 帽檐线以上归帽子
        continue
    if in_eye_protect(x, y):
        continue
    r, g, b, a = pp[x, y]
    if not is_hairish(r, g, b, a):
        continue
    seen.add((x, y))
    stack.extend(((x+1, y), (x-1, y), (x, y+1), (x, y-1)))
# 几何硬边界:胸前中心(领口到裙腰)没有头发 —— 暗色飘带和深发在暗区
# 无法用颜色区分,直接从 CC 减除;发梢超过 y=620 的部分也不要
chest = Image.new("L", (pw, ph), 0)
ImageDraw.Draw(chest).polygon(
    [(295, 415), (475, 415), (505, 560), (445, 660), (330, 660), (275, 540)],
    fill=255)
cp = chest.load()
seen = {(x, y) for (x, y) in seen if not cp[x, y] and y <= 620}
print("hair CC pixels:", len(seen))

# ---- 2) 孔洞填充(发上高光/浅色挑染) ----
outside = set()
stack = [(BBOX[0], BBOX[1]), (BBOX[2]-1, BBOX[1]),
         (BBOX[0], BBOX[3]-1), (BBOX[2]-1, BBOX[3]-1)]
while stack:
    x, y = stack.pop()
    if (x, y) in outside or not (BBOX[0] <= x < BBOX[2] and BBOX[1] <= y < BBOX[3]):
        continue
    if (x, y) in seen:
        continue
    outside.add((x, y))
    stack.extend(((x+1, y), (x-1, y), (x, y+1), (x, y-1)))
holes = 0
visited = set()
for y in range(BBOX[1], BBOX[3]):
    for x in range(BBOX[0], BBOX[2]):
        if (x, y) in seen or (x, y) in outside or (x, y) in visited:
            continue
        if in_eye_protect(x, y):
            visited.add((x, y))
            continue
        comp = set()
        stack2 = [(x, y)]
        while stack2:
            cx, cy = stack2.pop()
            if (cx, cy) in comp or not (BBOX[0] <= cx < BBOX[2] and BBOX[1] <= cy < BBOX[3]):
                continue
            if (cx, cy) in seen or (cx, cy) in outside or in_eye_protect(cx, cy):
                continue
            comp.add((cx, cy))
            stack2.extend(((cx+1, cy), (cx-1, cy), (cx, cy+1), (cx, cy-1)))
        visited |= comp
        if len(comp) <= 900:               # 只回收发上小高光;大区域留底图
            seen |= comp
            holes += len(comp)
print("holes filled:", holes)

# ---- 3) hair layer(带 1px 羽化,裁到 bbox)+ 底图擦除 ----
mask = Image.new("L", (pw, ph), 0)
mp = mask.load()
for (x, y) in seen:
    if pp[x, y][3] > 20:
        mp[x, y] = 255
mask = mask.filter(ImageFilter.GaussianBlur(1.0))

hair = pre.copy()
hair.putalpha(ImageChops.multiply(hair.getchannel("A"), mask))
hb = hair.getbbox()
hair = hair.crop(hb)
hair.save(HAIR_OUT)
import json
json.dump({"bbox": list(hb)}, open("assets/hair_layer.meta", "w"))
print("hair layer bbox:", hb)

im2 = im.copy()
im2.putalpha(ImageChops.subtract(im2.getchannel("A"), mask))
im2.save(OUT)

# ---- 4) 预览:底图 → 发层 → 帽层,静止位置合成应无缝 ----
bg = Image.new("RGBA", (pw, ph), (26, 20, 43, 255))
hat = Image.open("assets/hat_layer.png").convert("RGBA")
comp = Image.alpha_composite(bg, im2)
comp.alpha_composite(hair, (hb[0], hb[1]))
comp.alpha_composite(hat, (0, 0))

orig = Image.alpha_composite(bg, Image.open("assets/main.prehair.png").convert("RGBA"))
side = Image.new("RGB", (pw * 2 + 10, ph), (60, 60, 60))
side.paste(orig.convert("RGB"), (0, 0))
side.paste(comp.convert("RGB"), (pw + 10, 0))
side.resize((pw, ph // 2)).save("_hair_cut_check.png")
print("done -> _hair_cut_check.png")
