# -*- coding: utf-8 -*-
"""看门狗实弹测试:冻结主线程,验证检测->dump->自重启链路。

截胡 os.execv/os._exit(写入标记文件并抛异常),不会真的重启出第二只宠物,
也不会动正在跑的真小乔;save_settings 也替换成空操作防止碰真实配置。
"""

from pathlib import Path
import sys
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "tests"))

import os
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pet

MARKER = os.path.join(str(Path(__file__).resolve().parents[2]),
                      "_wd_test_marker.txt")
if os.path.exists(MARKER):
    os.remove(MARKER)

pet.WATCHDOG_STALE = 4   # 测试阈值:4 秒无心跳即算卡死


class FakeOS:
    """代理 os,只截胡看门狗的退场动作(必须抛异常:
    真的 os.execv 正常情况下不会返回,抛异常才能模拟"到这一步为止")。"""
    def __getattr__(self, name):
        return getattr(os, name)

    def execv(self, path, args):
        with open(MARKER, "w", encoding="utf-8") as f:
            f.write(f"EXECV {path} {args}")
        raise RuntimeError("execv intercepted by test")

    def _exit(self, code):
        with open(MARKER, "a", encoding="utf-8") as f:
            f.write(f" EXIT {code}")
        raise RuntimeError("_exit intercepted by test")


pet.os = FakeOS()

import tkinter as tk
root = tk.Tk()
root.withdraw()
p = pet.Pet(root)
p.save_settings = lambda: None       # 别碰真实 pet_settings.json
p._start_watchdog()
root.update()                        # 跑一帧,心跳就位
print("beat armed, freezing main thread now...", flush=True)
time.sleep(22)                       # 故意不喂心跳 —— 模拟 mainloop 卡死
try:
    root.update()
except Exception as e:
    print("root.update after freeze:", e)
time.sleep(0.5)

if os.path.exists(MARKER):
    print("WATCHDOG_FIRE_OK:", open(MARKER, encoding="utf-8").read())
else:
    print("WATCHDOG_TEST_FAIL: no marker after 22s")
root.destroy()
