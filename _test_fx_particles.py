# -*- coding: utf-8 -*-
"""ParticleSprites 备料验证(不 import pet.py,几何公式自 pet.py 抄)。

  1. 视觉等价:参考画法(render 粒子段同款) vs 精灵贴图,同底合成逐像素
     比对;对比图存 _fxdev2/particle_equiv.png 供人眼复核。参考画法用的
     颜色也走 ParticleSprites 的量化档 —— 等价比对因此只验几何,固定色
     的"量化偏差 <=7/255"另有小断言把住。
  2. 缓存有界:随机参数轰炸 get(),条目数不得超 CACHE_MAX;同参数重复
     get 必须命中同一张(缓存生效);未知 kind / 缺 color 必须炸出来。
  3. 性能对照:模拟稳态 —— 50 颗持续存在的粒子跑 1000 帧,自转/闪烁让
     参数在档位间慢漂,统计缓存命中率,同一节奏下 50k 次 polygon 绘制
     vs 50k 次精灵 paste 计时。这是下一阶段接入决策的量化依据。
"""
import math
import os
import random
import sys
import time

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fx import ParticleSprites, GOLD, GOLD_L, MAGIC_A, MAGIC_B

HERE = os.path.dirname(os.path.abspath(__file__))
CAN = 160          # 单个比对画格边长(2x 空间像素)
KINDS = ["sparkle", "star", "cstar", "petal", "leaf", "confetti",
         "heart", "snow", "firefly"]


# ---- 参考几何:pet.py:629-655 逐行同款 ----
def star_pts(cx, cy, ro, ri, n=5, rot=-math.pi / 2):
    pts = []
    for i in range(2 * n):
        r = ro if i % 2 == 0 else ri
        a = rot + math.pi * i / n
        pts.append((cx + math.cos(a) * r, cy + math.sin(a) * r))
    return pts


def heart_pts(cx, cy, s):
    pts = []
    for i in range(26):
        a = 2 * math.pi * i / 26
        x = 16 * math.sin(a) ** 3
        y = (13 * math.cos(a) - 5 * math.cos(2 * a)
             - 2 * math.cos(3 * a) - math.cos(4 * a))
        pts.append((cx + x * s / 17.0, cy - y * s / 17.0))
    return pts


HEART_C = (255, 95, 138)      # pet.py:137
FIXED_LIT = {"heart": HEART_C, "snow": (245, 248, 255), "firefly": (240, 255, 180)}


def draw_ref(d, kind, cx, cy, s, rot, alpha, rgb):
    """pet.py render 粒子段同款画法。sway 等位置项归调用方,这里置 0。
    rgb 为空时用 pet.py 字面量固定色(性能对照路径);等价路径传的是
    量化后的颜色,和精灵逐值一致。"""
    if kind == "sparkle":
        d.polygon(star_pts(cx, cy, s, s * 0.3, n=4, rot=rot), fill=rgb + (alpha,))
    elif kind == "star":
        d.polygon(star_pts(cx, cy, s, s * 0.45, rot=rot), fill=rgb + (alpha,))
    elif kind == "cstar":
        d.polygon(star_pts(cx, cy, s, s * 0.5, n=5, rot=rot),
                  fill=GOLD_L + (245,), outline=GOLD + (255,))
    elif kind == "petal":
        ca, sa = math.cos(rot), math.sin(rot)
        d.polygon([(cx + dx * ca - dy * sa, cy + dx * sa + dy * ca)
                   for dx, dy in ((-s, 0), (0, -s * 0.6), (s, 0), (0, s * 0.6))],
                  fill=rgb + (alpha,))
    elif kind == "leaf":
        ca, sa = math.cos(rot), math.sin(rot)
        d.polygon([(cx + dx * ca - dy * sa, cy + dx * sa + dy * ca)
                   for dx, dy in ((-s, -s * 0.45), (s, -s * 0.3),
                                  (s * 0.4, s * 0.5), (-s * 0.5, s * 0.4))],
                  fill=rgb + (alpha,), outline=(120, 70, 40, int(alpha * 0.7)))
    elif kind == "confetti":
        w2, h2 = s, s * 0.55
        ca, sa = math.cos(rot), math.sin(rot)
        d.polygon([(cx + dx * ca - dy * sa, cy + dx * sa + dy * ca)
                   for dx, dy in ((-w2, -h2), (w2, -h2), (w2, h2), (-w2, h2))],
                  fill=rgb + (alpha,))
    elif kind == "heart":
        d.polygon(heart_pts(cx, cy, s), fill=(rgb or HEART_C) + (alpha,))
    elif kind == "snow":
        d.ellipse([cx - s, cy - s, cx + s, cy + s],
                  fill=(rgb or (245, 248, 255)) + (alpha,))
    elif kind == "firefly":
        d.ellipse([cx - s, cy - s, cx + s, cy + s],
                  fill=(rgb or (240, 255, 180)) + (alpha,))
    else:
        raise ValueError(kind)


# 每种 2~3 组代表参数:(kind, size 基础单位, rot, alpha, color|None)
CASES = [
    ("sparkle", 6, 0.7, 235, MAGIC_B),
    ("sparkle", 3, 2.1, 120, GOLD_L),
    ("sparkle", 9, 4.0, 200, (255, 255, 255)),
    ("star", 8, 1.2, 240, GOLD),
    ("star", 5, 3.3, 150, (140, 200, 255)),
    ("star", 11, 0.2, 90, (255, 160, 200)),
    ("cstar", 10, 0.9, 255, None),
    ("cstar", 7, 2.6, 255, None),
    ("petal", 7, 1.1, 240, (255, 170, 200)),
    ("petal", 5, 4.2, 160, (230, 180, 255)),
    ("leaf", 8, 0.5, 235, (180, 140, 90)),
    ("leaf", 6, 3.8, 180, (120, 180, 90)),
    ("confetti", 6, 2.2, 255, (255, 90, 90)),
    ("confetti", 4, 5.1, 200, (90, 200, 120)),
    ("heart", 9, 0.0, 200, None),
    ("heart", 5, 0.0, 255, None),
    ("snow", 4, 0.0, 210, None),
    ("snow", 7, 0.0, 120, None),
    ("firefly", 3, 0.0, 230, None),
    ("firefly", 5, 0.0, 100, None),
]


def test_equivalence(ps, sheet_path):
    """逐 case 比对参考画法与精灵贴图,顺带产出对比图。返回失败清单。"""
    rows, failures = [], []
    for kind, size, rot, alpha, color in CASES:
        _, s, rot_q, a_q, rgb_q = ps._resolve(kind, size, rot, alpha, color)
        ref = Image.new("RGBA", (CAN, CAN), (0, 0, 0, 0))
        # pet.py 的粒子是整像素覆写(连 alpha 一起替换;实测 Draw(im,"RGBA")
        # 在 RGBA 目标上并不混合),参考画法照抄这个语义
        draw_ref(ImageDraw.Draw(ref), kind, CAN // 2, CAN // 2,
                 s, rot_q, a_q, rgb_q)
        sp, mask = ps.get(kind, size, rot, alpha, color)
        got = Image.new("RGBA", (CAN, CAN), (0, 0, 0, 0))
        got.paste(sp, (CAN // 2 - sp.width // 2, CAN // 2 - sp.height // 2),
                  mask)
        diffs = [abs(a - b) for a, b in zip(ref.tobytes(), got.tobytes())]
        mean = sum(diffs) / len(diffs)
        bad = sum(1 for v in diffs if v > 32) / len(diffs)
        ok = mean < 4.0 and bad < 0.02
        if not ok:
            failures.append(f"{kind} size={size} rot={rot}: mean={mean:.2f} "
                            f"bad={bad * 100:.2f}%")
        rows.append((kind, ok, ref, got, diffs))

    try:
        fnt = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 12)
    except Exception:
        fnt = ImageFont.load_default()
    lab = 18
    sheet = Image.new("RGB", (CAN * 3 + 20, (CAN + lab) * len(rows) + 10),
                      (24, 24, 32))
    dd = ImageDraw.Draw(sheet)
    y = 5
    for kind, ok, ref, got, diffs in rows:
        heat = Image.new("L", (CAN, CAN), 0)
        per_px = [max(diffs[i:i + 4]) for i in range(0, len(diffs), 4)]
        heat.putdata([min(255, v * 8) for v in per_px])
        sheet.paste(ref, (5, y + lab), ref)
        sheet.paste(got, (10 + CAN, y + lab), got)
        sheet.paste(heat.convert("RGB"), (15 + CAN * 2, y + lab))
        dd.text((5, y + 2), f"{kind}  {'OK' if ok else 'FAIL'}",
                fill=(140, 220, 140) if ok else (255, 120, 120), font=fnt)
        dd.text((5 + CAN, y + 2), "ref | sprite | diff x8",
                fill=(150, 150, 170), font=fnt)
        y += CAN + lab
    os.makedirs(os.path.dirname(sheet_path), exist_ok=True)
    sheet.save(sheet_path)

    # 固定色量化后必须仍落在 pet.py 字面量的 COLOR_QUANT 邻域内
    for k, lit in FIXED_LIT.items():
        q = ps._q_color(lit)
        assert all(abs(a - b) < ps.COLOR_QUANT for a, b in zip(q, lit)), \
            f"{k} 固定色量化偏差过大: {lit} -> {q}"
    return failures


def test_cache_bound(ps):
    rnd = random.Random(7)
    pool = [(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
            for _ in range(40)]
    for _ in range(5000):
        kind = rnd.choice(KINDS)
        color = None if (kind == "cstar" or kind in ps._FIXED) else rnd.choice(pool)
        ps.get(kind, rnd.uniform(1, 14), rnd.uniform(0, 6.28),
               rnd.randint(10, 255), color)
        assert len(ps._cache) <= ps.CACHE_MAX, "缓存条目数超上限"
    a = ps.get("star", 8, 1.2, 240, GOLD)
    b = ps.get("star", 8, 1.2, 240, GOLD)
    assert a is b, "同参数两次 get 未命中同一张,缓存没生效"
    for bad_call in (lambda: ps.get("bogus", 5),          # 未知 kind
                     lambda: ps.get("star", 5)):          # 缺 color
        try:
            bad_call()
        except ValueError:
            pass
        else:
            assert False, "该炸出来的参数错误被吞了"


def test_perf(ps):
    """三个视角的实测,给下一阶段"哪些 kind 值得接入"提供数据。

    (a) 独参 churn(worst case):50 颗参数各异的常驻粒子,自转/闪烁持续
        穿越量化档位,未命中要重画。
    (b) 高共享 burst(主场):爆发粒子共用少数几档颜色 x 大小 x 旋转,
        预热后几乎全命中。
    (c) 每种单发对照(全命中):贴图 vs 直画的纯开销,含各自的参数换算
        (贴图走 paste 内的 _resolve,直画含 star_pts/heart_pts 点集计算),
        和接入后的真实调用形态一一对应。贴图开销 ∝ 外接盒面积,直画
        ∝ 点数 + 形状面积,所以按 kind 挑,别整段一刀切。
    """
    W, H = 1290, 1560
    rnd = random.Random(42)
    cols = [GOLD, GOLD_L, MAGIC_A, MAGIC_B, (255, 255, 255), (255, 160, 200),
            (140, 200, 255), (180, 140, 90)]
    kinds = ["star", "sparkle", "petal", "leaf", "confetti", "heart", "snow"]

    def style(pt, frame):
        rot = pt["phase"] + frame * 0.033 * pt["spin"]
        a = int(128 + 120 * math.sin(frame * 0.05 + pt["phase"]))
        return rot, a

    # ---- (a) 独参 churn ----
    N, P = 1000, 50
    parts = [dict(kind=rnd.choice(kinds),
                  x=rnd.uniform(60, W - 60), y=rnd.uniform(140, H - 140),
                  size=rnd.uniform(2, 10), spin=rnd.uniform(1.0, 4.0),
                  phase=rnd.uniform(0, 6.28), color=rnd.choice(cols))
             for _ in range(P)]

    frame_p = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(frame_p, "RGBA")
    t0 = time.perf_counter()
    for i in range(N):
        for pt in parts:
            rot, a = style(pt, i)
            draw_ref(d, pt["kind"], pt["x"], pt["y"], pt["size"] * ps.k,
                     rot, a, pt["color"])
    t_poly = time.perf_counter() - t0

    frame_s = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ps.stat_hit = ps.stat_miss = 0
    t0 = time.perf_counter()
    for i in range(N):
        for pt in parts:
            rot, a = style(pt, i)
            ps.paste(frame_s, pt["kind"], pt["x"], pt["y"], pt["size"],
                     rot, a, pt["color"])
    t_spr = time.perf_counter() - t0
    total = N * P
    print(f"   (a) 独参 churn {total} 次: 多边形 {t_poly * 1000:.0f} ms vs "
          f"精灵 {t_spr * 1000:.0f} ms(命中 {ps.stat_hit / total * 100:.0f}%,"
          f"倍率 x{t_poly / max(t_spr, 1e-9):.2f})")

    # ---- (b) 高共享 burst ----
    N2, P2 = 500, 40
    bcols = [GOLD, GOLD_L, MAGIC_A, MAGIC_B]
    bsizes = [4.0, 6.0, 9.0]
    bp = [(rnd.choice(bsizes), rnd.choice(bcols)) for _ in range(P2)]
    t0 = time.perf_counter()
    for i in range(N2):
        for size, col in bp:
            draw_ref(d, "star", 300 + (i * 7) % 600, 300 + (i * 13) % 900,
                     size * ps.k, (i * 0.61) % 6.28, 240, col)
    t_poly2 = time.perf_counter() - t0
    ps.stat_hit = ps.stat_miss = 0
    t0 = time.perf_counter()
    for i in range(N2):
        for size, col in bp:
            ps.paste(frame_s, "star", 300 + (i * 7) % 600,
                     300 + (i * 13) % 900, size, (i * 0.61) % 6.28, 240, col)
    t_spr2 = time.perf_counter() - t0
    total2 = N2 * P2
    print(f"   (b) 高共享 burst {total2} 次: 多边形 {t_poly2 * 1000:.0f} ms vs "
          f"精灵 {t_spr2 * 1000:.0f} ms(命中 {ps.stat_hit / total2 * 100:.0f}%,"
          f"倍率 x{t_poly2 / max(t_spr2, 1e-9):.2f})")

    # ---- (c) 每种单发对照(全命中,真实调用形态) ----
    reps = [("sparkle", 6, MAGIC_B), ("star", 8, GOLD), ("cstar", 9, None),
            ("petal", 7, (255, 170, 200)), ("leaf", 8, (180, 140, 90)),
            ("confetti", 6, (255, 90, 90)), ("heart", 9, None),
            ("snow", 5, None), ("firefly", 4, None)]
    N3 = 20000
    print("   (c) 每种单发对照(全命中): 直画 vs 贴图")
    for kind, size, col in reps:
        s_px = size * ps.k
        t0 = time.perf_counter()
        for i in range(N3):
            draw_ref(d, kind, 300 + (i * 7) % 600, 300 + (i * 13) % 900,
                     s_px, (i * 0.61) % 6.28, 240, col)
        t_p = time.perf_counter() - t0
        ps.get(kind, size, 1.0, 240, col)      # 预热该档
        t0 = time.perf_counter()
        for i in range(N3):
            ps.paste(frame_s, kind, 300 + (i * 7) % 600,
                     300 + (i * 13) % 900, size, (i * 0.61) % 6.28, 240, col)
        t_s = time.perf_counter() - t0
        print(f"      {kind:<9} s={size:>2}: 直画 {t_p / N3 * 1e6:5.1f} us | "
              f"贴图 {t_s / N3 * 1e6:5.1f} us | x{t_p / max(t_s, 1e-9):.2f}")


def main():
    ps = ParticleSprites(1.5, 2)   # 真宠当前运行参数(pet_settings.json)
    print("== 1) 视觉等价(参考画法 vs 精灵贴图) ==")
    fails = test_equivalence(ps, os.path.join(HERE, "_fxdev2",
                                              "particle_equiv.png"))
    print(f"   {len(CASES)} 组比对,失败 {len(fails)} 组"
          + ("" if not fails else ":" + "; ".join(fails)))
    print("   对比图: _fxdev2/particle_equiv.png")

    print("== 2) 缓存有界性 ==")
    test_cache_bound(ps)
    print(f"   5000 次随机 get 后条目数 {len(ps._cache)} <= {ps.CACHE_MAX},"
          "命中/报错行为正常")

    print("== 3) 性能对照(churn worst case vs 高共享 burst) ==")
    test_perf(ps)

    if fails:
        print("FAIL: 存在视觉等价不达标项")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
