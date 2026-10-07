# -*- coding: utf-8 -*-
"""TimeFX(时停/回溯演出层)验证。

  1. 素材构建:表盘涟漪 8 档、齿轮 3x12 旋转档、扫掠 12 相位全部可构建,
     且旋转档/相位之间互不相同(档位真的在转,不是同一张贴图)。
  2. 演出回放:两种模式各按 40 帧逐帧 draw,无异常、到点自动收起、
     逐帧画面有变化(不是死图)。
  3. 单帧开销:draw 平均 < 1.5ms(渲染预算 33ms 里占得住)。
"""

from pathlib import Path
import sys
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "tests"))

import os
import sys
import time

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from fx import TimeFX


def main():
    t = TimeFX(1.5, 2)
    print("== 1) 素材构建 ==")
    assert len(t.stop) == t.STEPS, "表盘涟漪档数不对"
    assert len(t.gear) == 3 and all(len(g) == t.ROT_BINS for g in t.gear), \
        "齿轮规格/旋转档不对"
    assert len(t.sweep) == 12, "扫掠相位不对"
    for g in t.gear:
        sigs = {sp.tobytes() for sp in g}
        assert len(sigs) == t.ROT_BINS, "齿轮旋转档里有重复贴图(没在转)"
    assert (t.sweep[0].tobytes() != t.sweep[3].tobytes()), "扫掠相位重复"
    mem = sum(sp.width * sp.height * 4
              for g in t.gear for sp in g) + \
        sum(sp.width * sp.height * 4 for sp in t.stop + t.sweep)
    print(f"   涟漪 8 档 / 齿轮 3x12 档 / 扫掠 12 相位,精灵内存约 "
          f"{mem / 1e6:.1f} MB")

    print("== 2) 演出回放 ==")
    W, H, N = 1290, 1560, 40
    for mode in ("stop", "rewind"):
        cv = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(cv, "RGBA")
        t.play(mode, 1.0)
        sigs = set()
        for i in range(N):
            t.draw(cv, d, 645, 1300, 2, t.t0 + i * (1.25 / N))
            sigs.add(cv.tobytes())
            if i < N - 8:                      # 最后几帧应已播完收起
                assert t.mode == mode, f"{mode} 中途收起(i={i})"
        assert t.mode is None, f"{mode} 播完没有自动收起"
        assert len(sigs) >= N * 3 // 4, f"{mode} 画面几乎不动(死图?)"
        print(f"   {mode}: {N} 帧无异常,{len(sigs)} 帧画面各不相同,到点收起")

    print("== 3) 单帧开销 ==")
    cv = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(cv, "RGBA")
    t.play("stop", 100.0)
    n = 300
    t0 = time.perf_counter()
    for i in range(n):
        t.draw(cv, d, 645, 1300, 2, t.t0 + 0.5 + i * 0.001)
    per = (time.perf_counter() - t0) / n * 1000
    assert per < 1.5, f"draw 单帧 {per:.2f}ms 超预算"
    print(f"   draw 平均 {per:.2f} ms/帧 < 1.5ms")
    print("ALL PASS")


if __name__ == "__main__":
    main()
