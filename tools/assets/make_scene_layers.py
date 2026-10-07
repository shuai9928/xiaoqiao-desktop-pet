# -*- coding: utf-8 -*-
"""把「秋千场景」整张原画(assets/scene_src.png,1254×1254 透明底)拆成运行时图层。

产物都在 assets/scene/,和原画同一张画布坐标(不裁剪,运行时按 meta 里的
bbox 取用):
  static.png   顶部横杆 + 两端金月牙 + 挂环 + 杆端垂饰 —— 不随秋千动。
               被帽尖挡住的那段杆身用相邻杆身补齐(秋千一动帽尖会挪开)。
  swing.png    吊绳 + 坐垫 + 她 —— 一起前后荡(运行时做梯形透视变形)。
  book.png     左侧魔法书(AI 轨迹入口);crystal.png 右侧水晶灯(AI 状态)。
  girl.png     离开秋千时的她(去掉吊绳、补好袖子/指缝,坐垫保留),同时
               按包围盒裁出 assets/main.png。
  meta.json    挂点线、坐垫线、脸部特征点、各层 bbox(全部为原画坐标)。

只在开发时跑(需要 numpy/scipy);桌宠运行时只读 png/json,不依赖它们。
"""

from pathlib import Path
import sys
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "tests"))

import json
import os

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

HERE = str(Path(__file__).resolve().parents[2])
SRC = os.path.join(HERE, "assets", "scene_src.png")
OUT = os.path.join(HERE, "assets", "scene")

# ---- 原画里量出来的几何(1254×1254 画布坐标)----
# 横杆上下沿:近似直线(杆身略向右下倾斜)
ROD_TOP = lambda x: 55 + 0.092 * (x - 340)
ROD_BOT = lambda x: 93 + 0.084 * (x - 340)
ROD_X = (300, 1012)
# 帽尖从杆前面穿过的列范围;这段杆身用左侧干净的杆身补
HAT_TIP_X = (795, 915)
HAT_UNDER_X = (680, 795)          # 杆下方、挂点线以上的帽体
# 吊绳挂点(挂环下沿):左 (330,152) 右 (1020,188);两点连成挂点线
PIVOT_L, PIVOT_R = (330, 152), (1020, 188)
# 两端金月牙 + 垂饰、中央宝饰、两个挂环(挂环下沿以上)。只认这些框和杆身
# 带,不能按"挂点线以上"一刀切 —— 帽檐左上沿也高过挂点线
STATIC_BOXES = [(150, 0, 292, 312), (1040, 0, 1254, 322)]
GEM_BOX = (588, 28, 714, 156)
RING_BOXES = [(298, 90, 352, 153), (996, 128, 1046, 189)]
# 魔法书:多边形外沿(书右下角紧贴她的蓝色腰带飘带,以 x≈306 为界)
BOOK_POLY = [(40, 620), (345, 620), (345, 850), (330, 866), (306, 880),
             (306, 1090), (40, 1090)]
# 坐垫座面线(她坐的地方)与脸部特征点 —— 运行时用来锚座、画眨眼/嘴
SEAT_LINE_Y = 905
FACE = {"eye_l": [610, 520], "eye_r": [737, 554], "mouth": [658, 582]}


# ---- 离开秋千时的她:去掉两根吊绳(连绳上小星饰、坐垫上方的金链),坐垫保留
# (落地后她坐着自己的魔法软垫飘着走)。被绳挡住的袖子/腰带/指缝补出来。
ROPE_HALF = 12                 # 绳宽实测 17~20px,中心线逐 10px 实测 + 线性插值
ROPE_Y = {"l": (118, 902), "r": (150, 906)}   # 从挂环里就开始(挂环在静态层)
ROPE_ANCHOR = {"l": (155, 336.0), "r": (186, 1020.0)}   # 挂环下沿的绳头
# 绳上的金星饰、绳脚金链(坐垫上沿以上那段):框里只去金色及其暗描边
ROPE_GOLD = [(318, 156, 374, 214), (334, 362, 376, 402), (996, 176, 1046, 270),
             (372, 852, 422, 902), (920, 828, 968, 906)]
# 右绳星饰下的流苏:框里整块都是它
ROPE_TASSEL = [(996, 214, 1046, 322)]
# 握绳的手:框里只留肤色和红棕描边,其余都是绳
FIST = (330, 586, 420, 642)
# 右侧帽檐整段盖住绳的那几行:框里全留
BRIM = (955, 496, 1016, 582)


def rope_centers(al):
    """逐行实测绳身中心(只取宽 12~24px、离预估线 9px 内的不透明段),
    测不到的行(帽飘带前、手里、帽檐后)按相邻实测点线性插值。"""
    guess = {"l": lambda y: 358.5 + 0.0833 * (y - 420),
             "r": lambda y: 1001 - 0.1344 * (y - 360)}
    span = {"l": (300, 430), "r": (900, 1060)}
    out = {}
    for key in ("l", "r"):
        y0, y1 = ROPE_Y[key]
        lo, hi = span[key]
        pts = [ROPE_ANCHOR[key]]
        for y in range(y0, y1 + 1, 10):
            g = guess[key](y)
            row = al[y, lo:hi] > 128
            best, x = None, 0
            while x < len(row):
                if row[x]:
                    st = x
                    while x < len(row) and row[x]:
                        x += 1
                    c = lo + (st + x - 1) / 2
                    if 12 <= x - st <= 24 and abs(c - g) < 9 and (
                            best is None or abs(c - g) < abs(best - g)):
                        best = c
                x += 1
            if best is not None:
                pts.append((y, best))
        py_, px_ = zip(*sorted(pts))
        out[key] = (np.array(py_, float), np.array(px_, float))
    return out


def cut_girl(sw, xs, ys):
    from scipy import ndimage as ndi
    a = sw.astype(np.float64)
    al = a[..., 3]
    cen = rope_centers(al)
    cx = {k: np.interp(ys[:, 0], *cen[k]) for k in cen}       # 每行中心 x
    band = np.zeros(al.shape, bool)
    for key in ("l", "r"):
        y0, y1 = ROPE_Y[key]
        band |= ((np.abs(xs - cx[key][:, None]) <= ROPE_HALF)
                 & (ys >= y0) & (ys <= y1))
    # 绳带内一律算绳(暗部、高光、阴影都在),只在手和帽檐处放过她
    rope = band & (al > 0)
    r_, g_, b_ = a[..., 0], a[..., 1], a[..., 2]
    gold = (r_ > 150) & (g_ > 105) & (b_ < 140) & (r_ - b_ > 50)
    gold |= (r_ > 200) & (g_ > 175) & (r_ - b_ > 28)     # 金饰的奶油色高光
    dark = a[..., :3].max(-1) < 120
    gold_ish = gold | (dark & ndi.binary_dilation(gold, iterations=2))

    def inbox(b):
        x0, y0, x1, y1 = b
        return (xs >= x0) & (xs < x1) & (ys >= y0) & (ys < y1)

    for b in ROPE_GOLD:
        rope |= inbox(b) & gold_ish & (al > 0)
    for b in ROPE_TASSEL:
        rope |= inbox(b) & (al > 0)
    skin = (r_ > 190) & (g_ > 140) & (b_ > 115) & (r_ >= b_)
    outline = (r_ > g_ + 25) & (r_ > b_ + 20)
    rope &= ~(inbox(FIST) & (skin | outline))
    rope &= ~inbox(BRIM)
    # 绳外缘半透明光边(背景透明处):外扩 2px,只吃半透明像素
    halo = ndi.binary_dilation(rope, iterations=2) & (al < 250) & ~inbox(BRIM)
    rope |= halo & ~(inbox(FIST) & (skin | outline))

    girl = sw.copy()
    rest = (al > 0) & ~rope
    # 需要补的洞:绳横穿她身体的地方(绳两侧水平方向都有她)
    span = ndi.binary_closing(rest, structure=np.ones((1, 2 * ROPE_HALF + 15)))
    hole = rope & span
    girl[rope] = 0
    if hole.any():
        # 由近到远逐圈向内扩散填色(预乘 alpha),再在洞内轻微平滑
        known = rest.copy()
        pm = a.copy()
        pm[..., :3] *= al[..., None] / 255.0
        pm[~known] = 0
        filled = known.copy()
        for _ in range(40):
            todo = hole & ~filled
            if not todo.any():
                break
            ring = todo & ndi.binary_dilation(filled)
            acc = np.zeros_like(pm)
            cnt = np.zeros(al.shape)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    sh_f = np.roll(np.roll(filled, dy, 0), dx, 1)
                    sh_p = np.roll(np.roll(pm, dy, 0), dx, 1)
                    acc += sh_p * sh_f[..., None]
                    cnt += sh_f
            ok = ring & (cnt > 0)
            pm[ok] = acc[ok] / cnt[ok][:, None]
            filled |= ok
        # 调和平滑:洞内像素反复取上下左右平均(边界固定),颜色从洞边平滑
        # 过渡进来,不会留下逐圈扩散的条纹
        for _ in range(250):
            avg = (np.roll(pm, 1, 0) + np.roll(pm, -1, 0)
                   + np.roll(pm, 1, 1) + np.roll(pm, -1, 1)) / 4
            pm[hole] = avg[hole]
        out_a = np.clip(pm[..., 3], 0, 255)
        rgb = np.where(out_a[..., None] > 0,
                       pm[..., :3] * 255.0 / np.maximum(out_a[..., None], 1e-6), 0)
        fill = np.concatenate([rgb, out_a[..., None]], -1)
        girl[hole] = np.clip(fill[hole], 0, 255).astype(np.uint8)
    # 挂点线以上除帽尖外都不属于她(静态层边缘的月牙/挂环碎边);再去掉
    # 和她身体不相连的零碎小块(<400px,绳头残段之类)
    above = ys < np.vectorize(pivot_y)(xs)
    tip = (xs >= HAT_UNDER_X[0]) & (xs < HAT_TIP_X[1])
    girl[above & ~tip] = 0
    lab, n = ndi.label(girl[..., 3] > 40, structure=np.ones((3, 3)))
    if n:
        sizes = ndi.sum(girl[..., 3] > 40, lab, range(1, n + 1))
        small = np.isin(lab, 1 + np.nonzero(sizes < 400)[0])
        near = ndi.binary_dilation(small, iterations=3) & (girl[..., 3] <= 40)
        girl[small | near] = 0
    print("girl: rope px", int(rope.sum()), "inpainted px", int(hole.sum()))
    return girl


def pivot_y(x):
    (x0, y0), (x1, y1) = PIVOT_L, PIVOT_R
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def main():
    os.makedirs(OUT, exist_ok=True)
    src = Image.open(SRC).convert("RGBA")
    a = np.array(src)
    # 原画整张都有 alpha 1~7 的噪点:分层窗口里 alpha>0 就会截住鼠标,
    # 整块方形都变成"点得到"。先清掉(肉眼不可见)
    a[a[..., 3] < 8] = 0
    h, w = a.shape[:2]
    al = a[..., 3]
    ys, xs = np.mgrid[0:h, 0:w]

    # 1) 连通域:大块 = 主体(横杆+绳+座+她+书,书靠飘带连着),次大 = 水晶灯。
    #    半透明光晕/小星星按最近的大块归属,不会有游离碎点。
    lab, n = ndimage.label(al > 40, structure=np.ones((3, 3)))
    sizes = ndimage.sum(al > 40, lab, range(1, n + 1))
    order = np.argsort(-sizes) + 1
    main_id, crystal_id = int(order[0]), int(order[1])
    seeds = np.where(lab == main_id, 1, np.where(lab == crystal_id, 2, 0))
    _, (iy, ix) = ndimage.distance_transform_edt(seeds == 0, return_indices=True)
    owner = seeds[iy, ix]
    owner[al == 0] = 0

    # 2) 书:主体里落在书多边形内的部分
    book_m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(book_m).polygon(BOOK_POLY, fill=255)
    book = (np.array(book_m) > 0) & (owner == 1)
    crystal = owner == 2
    body = (owner == 1) & ~book

    # 3) 静态:杆身带(帽尖那几列除外)+ 宝饰 + 挂环 + 两端月牙垂饰
    rod_bot = ROD_BOT(xs) + 3
    rod_top = ROD_TOP(xs) - 3
    hat_tip = (xs >= HAT_TIP_X[0]) & (xs < HAT_TIP_X[1])
    hat_under = (xs >= HAT_UNDER_X[0]) & (xs < HAT_UNDER_X[1]) & (ys > rod_bot)
    rod = ((ys >= rod_top) & (ys <= rod_bot)
           & (xs >= ROD_X[0]) & (xs < ROD_X[1]) & ~hat_tip)

    def box(b):
        x0, y0, x1, y1 = b
        return (xs >= x0) & (xs < x1) & (ys >= y0) & (ys < y1)

    static = rod | (box(GEM_BOX) & ~hat_under)
    for b in STATIC_BOXES + RING_BOXES:
        static |= box(b)
    static &= body
    swing = body & ~static

    def layer(mask):
        out = np.zeros_like(a)
        out[mask] = a[mask]
        return out

    st = layer(static)
    # 帽尖背后的杆身:从帽尖右边一段上下都干净的杆身(x 920~960)逐列复制,
    # 按杆身上下沿(逐列实测,亚像素)比例映射行号。帽尖紧左边那段不能当
    # 素材:杆下沿贴着帽檐高光,复制过来是一排锯齿;离太远的杆身明暗略有
    # 差,接缝处会出台阶。
    def rod_edges(x):
        col = al[20:200, x].astype(float)
        y = 0
        while y < len(col) and col[y] <= 128:
            y += 1
        y0 = y
        while y < len(col) and col[y] > 128:
            y += 1
        top = 20 + y0 - (col[y0 - 1] / 255 if y0 > 0 else 0)
        bot = 20 + y - 1 + (col[y] / 255 if y < len(col) else 0)
        return top, bot

    (lt, lb), (rt, rb) = rod_edges(HAT_TIP_X[0] - 15), rod_edges(HAT_TIP_X[1])
    span = HAT_TIP_X[1] - (HAT_TIP_X[0] - 15)
    for x in range(HAT_TIP_X[0], HAT_TIP_X[1]):
        k = (x - (HAT_TIP_X[0] - 15)) / span
        t0, t1 = lt + (rt - lt) * k, lb + (rb - lb) * k
        x_src = 920 + (x - HAT_TIP_X[0]) % 40
        s0, s1 = rod_edges(x_src)
        for y in range(int(t0) - 3, int(t1) + 4):
            ys_ = int(round(s0 + (y - t0) * (s1 - s0) / (t1 - t0)))
            if 0 <= ys_ < h:
                st[y, x] = a[ys_, x_src]

    sw_arr = layer(swing)
    # 帽尖那几列里,swing 层还带着帽尖背后原画的杆身像素:帽子一摆,这截杆身
    # 会被一起拖走。和静态层补好的杆身逐像素比,颜色几乎一样的就是杆 → 从
    # swing 层拿掉(静态层的杆身从底下透出来,静止时画面不变)
    # 颜色分不开(帽尖内部也是深紫),按帽锥的几何轮廓分:左沿是 (793,135)→
    # 帽尖 (898,68) 的直线,右沿约 x=901;锥内是帽子,锥外是杆
    band = (xs >= HAT_TIP_X[0]) & (xs < HAT_TIP_X[1]) & (ys >= rod_top) & (ys <= rod_bot)
    cone = (ys >= 135 - (xs - 793) * 0.638 - 1) & (xs <= 901)
    rodlike = band & ~cone & (sw_arr[..., 3] > 0)
    sw_arr[rodlike] = 0
    print("hat-tip rod px moved to static:", int(rodlike.sum()))
    girl_arr = cut_girl(sw_arr, xs, ys)

    layers = {"static": st, "swing": sw_arr, "book": layer(book),
              "crystal": layer(crystal), "girl": girl_arr}
    meta = {"size": [w, h], "pivot_l": PIVOT_L, "pivot_r": PIVOT_R,
            "seat_line_y": SEAT_LINE_Y, "face": FACE, "bbox": {}}
    for name, arr in layers.items():
        im = Image.fromarray(arr, "RGBA")
        im.save(os.path.join(OUT, name + ".png"), optimize=True)
        meta["bbox"][name] = list(im.getbbox() or (0, 0, 0, 0))
        print(name, meta["bbox"][name])
    # 离开秋千时的立绘 = 她的包围盒裁图(assets/main.png);config.json 里的
    # 眼/嘴/rig 都是相对这张裁图的比例
    gb = meta["bbox"]["girl"]
    meta["girl_bbox"] = gb
    Image.fromarray(layers["girl"], "RGBA").crop(gb).save(
        os.path.join(HERE, "assets", "main.png"), optimize=True)
    with open(os.path.join(OUT, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)

    # 自检:四层叠回去应与原画逐像素一致(帽尖背后补的杆身被帽尖盖住)
    comp = Image.new("RGBA", (w, h))
    for name in ("static", "swing", "book", "crystal"):
        comp.alpha_composite(Image.fromarray(layers[name], "RGBA"))
    d = np.abs(np.array(comp).astype(int) - a.astype(int)).max(-1)
    print("recompose vs src: max diff", int(d.max()), "px>8:", int((d > 8).sum()))


if __name__ == "__main__":
    main()
