# -*- coding: utf-8 -*-
"""从立绘 assets/main.png 擦掉扫把 —— 多边形硬擦版。

颜色掩膜对低饱和的淡鼠尾草绿刷头无效(g-r 只有 15 左右),改用网格
读数定的两块多边形:P1 = 刷头整体(右缘贴着白裙边 x≤195 收),
P2 = 斜杆走廊(止于裙后 x≤254)。polygon 内 alpha 一律清零。
原始图备份在 assets/main.orig.png。
"""
import os
from PIL import Image, ImageChops, ImageDraw

SRC = "assets/main.png"
BACKUP = "assets/main.orig.png"
OUT = "assets/main.png"

if not os.path.exists(BACKUP):
    Image.open(SRC).save(BACKUP)

im = Image.open(BACKUP).convert("RGBA")

P1 = [(0, 612), (95, 598), (145, 588), (193, 580),      # 刷头:月牙+淡芯+翼尖
      (195, 700), (160, 722), (100, 726), (40, 712), (0, 690)]
P1B = [(0, 570), (32, 570), (34, 614), (0, 614)]        # 月牙上尖(不碰左边镰刀饰)
P2 = [(82, 620), (140, 548), (196, 500), (246, 462),    # 斜杆走廊,止于裙后
      (254, 476), (206, 520), (152, 568), (102, 642)]
P3 = [(186, 566), (212, 566), (212, 600), (186, 600)]   # 扇形顶漂浮碎片

mask = Image.new("L", im.size, 0)
md = ImageDraw.Draw(mask)
for poly in (P1, P1B, P2, P3):
    md.polygon(poly, fill=255)
im.putalpha(ImageChops.subtract(im.getchannel("A"), mask))
im.save(OUT)
print("broom erased:", Image.open(BACKUP).convert("RGBA").getchannel("A")
      .getextrema(), "->", im.getchannel("A").getextrema())
