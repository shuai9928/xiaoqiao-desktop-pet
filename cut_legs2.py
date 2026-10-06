# -*- coding: utf-8 -*-
"""双腿独立切层:左腿/右腿各自成层(assets/legs_l.png / legs_r.png),
底图挖掉双腿(assets/main.png)。两腿之间用分界折线切开,摆动时可
剪刀式交错。备份:assets/main.prelegs.png(切腿前)。

腿层比底图挖掉的范围多出 OVERLAP 像素(连两腿分界线也互相越过):
静止时多出来的是同一批像素,叠上去看不出;踢腿/剪刀交错时它盖住
挖空处的边缘,不会露出一条透明缝。底图挖的范围不变。
"""
import os
from PIL import Image, ImageChops, ImageDraw, ImageFilter

BACKUP = "assets/main.prelegs.png"
SRC = OUT = "assets/main.png"
L_OUT = "assets/legs_l.png"
R_OUT = "assets/legs_r.png"

if not os.path.exists(BACKUP):
    Image.open(SRC).save(BACKUP)
im = Image.open(BACKUP).convert("RGBA")
w, h = im.size

# 腿部多边形(整体):大腿块(y 528-600 限 x≤452)+ 小腿鞋块
LEG_POLY = [(295, 528), (452, 528), (452, 600), (560, 600),
            (560, 750), (300, 750)]
# 两腿分界折线(从网格读数:大腿并拢处 x≈426,往下渐分开)
DIVIDER = [(424, 526), (428, 580), (434, 640), (450, 700), (468, 750)]

full = Image.new("L", (w, h), 0)
ImageDraw.Draw(full).polygon(LEG_POLY, fill=255)
full = full.filter(ImageFilter.GaussianBlur(0.6))

# 分界折线的"左侧"掩膜:用一个够大的矩形右边缘推到分界线处
div_mask = Image.new("L", (w, h), 0)
ImageDraw.Draw(div_mask).polygon(
    DIVIDER + [(0, 750), (0, 526)], fill=255)

OVERLAP = 8
grow = ImageFilter.MaxFilter(2 * OVERLAP + 1)
# 右腿不能用左侧掩膜取反:取反后分界线以上整条横带都算右腿
div_mask_r = Image.new("L", (w, h), 0)
ImageDraw.Draw(div_mask_r).polygon(
    DIVIDER + [(w, 750), (w, 526)], fill=255)
# 外扩只在原画不透明的像素上做:半透明描边重复叠两次会变深,
# 静止合成就不再和原画逐像素一致了
opaque = im.getchannel("A").point(lambda a: 255 if a >= 250 else 0)
ext = ImageChops.multiply(full.filter(grow), opaque)
mask_l = ImageChops.lighter(ImageChops.multiply(full, div_mask),
                            ImageChops.multiply(ext, div_mask.filter(grow)))
mask_r = ImageChops.lighter(ImageChops.subtract(full, div_mask),
                            ImageChops.multiply(ext, div_mask_r.filter(grow)))

legs_l = im.copy()
legs_l.putalpha(ImageChops.multiply(legs_l.getchannel("A"), mask_l))
lbl = legs_l.getbbox()
legs_l = legs_l.crop(lbl)
legs_l.save(L_OUT)

legs_r = im.copy()
legs_r.putalpha(ImageChops.multiply(legs_r.getchannel("A"), mask_r))
lbr = legs_r.getbbox()
legs_r = legs_r.crop(lbr)
legs_r.save(R_OUT)

import json
json.dump({"bbox": list(lbl)}, open("assets/legs_l.meta", "w"))
json.dump({"bbox": list(lbr)}, open("assets/legs_r.meta", "w"))

base = im.copy()
base.putalpha(ImageChops.subtract(base.getchannel("A"), full))
base.save(OUT)
print("legs_l:", lbl, "legs_r:", lbr)

# 预览:底图 + 左腿 + 右腿 + 帽 + 发,静止合成应无缝
bg = Image.new("RGBA", (w, h), (26, 20, 43, 255))
comp = Image.alpha_composite(bg, base)
comp.alpha_composite(legs_l, (lbl[0], lbl[1]))
comp.alpha_composite(legs_r, (lbr[0], lbr[1]))
if os.path.exists("assets/hat_layer.png"):
    hat = Image.open("assets/hat_layer.png").convert("RGBA")
    comp.alpha_composite(hat, (0, 0))
if os.path.exists("assets/hair_layer.png"):
    hair = Image.open("assets/hair_layer.png").convert("RGBA")
    hb = json.load(open("assets/hair_layer.meta"))["bbox"]
    comp.alpha_composite(hair, (hb[0], hb[1]))
side = Image.new("RGB", (w * 2 + 10, h), (60, 60, 60))
side.paste(Image.alpha_composite(bg, im).convert("RGB"), (0, 0))
side.paste(comp.convert("RGB"), (w + 10, 0))
side.resize((w, h // 2)).save("_legs2_check.png")
print("done -> _legs2_check.png")
