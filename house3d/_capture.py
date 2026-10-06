"""3D 小屋截图工具(开发用):启动 house3d,按窗口矩形精确截图,然后关闭。

用法: py house3d/_capture.py <输出.png> [存活秒数=8]
"""
import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path

from PIL import ImageGrab

ROOT = Path(__file__).resolve().parent
EXE = Path.home() / "godot4" / "Godot_v4.7.2-stable_win64_console.exe"
TITLE = "小乔3D小屋"


def find_window_rect(title):
    import ctypes.wintypes as wt
    user32 = ctypes.windll.user32
    EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    found = []

    def cb(hwnd, _lparam):
        # 类名 "Engine" 是 Godot 窗口;标题含关键字的也收
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if cls.value == "Engine" or title in buf.value:
            if user32.IsWindowVisible(hwnd):
                found.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    for hwnd in found:
        # 只认本进程树里那个(避免匹配到编辑器)
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        rect = wt.RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if 700 < w < 2000 and 600 < h < 1600:
                return (rect.left, rect.top, rect.right, rect.bottom)
    return None


def main():
    # 让本进程 DPI 感知:GetWindowRect 返回物理像素,与 ImageGrab 一致
    ctypes.windll.user32.SetProcessDPIAware()
    out = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "_shot.png")
    alive = float(sys.argv[2]) if len(sys.argv) > 2 else 8.0
    pet_cmd = ROOT.parent / "pet_cmd.json"

    def pet_toggle_visible():
        # 截图期间隐藏 2.5D 桌宠,避免置顶窗口重叠;结束立刻恢复
        pet_cmd.write_text('{"op":"toggle_visible"}', encoding="utf-8")
        time.sleep(1.2)

    clean = os.environ.get("HOUSE3D_CLEAN", "1") == "1"
    if clean:
        pet_toggle_visible()
    log = open(ROOT / "_run.log", "w")
    proc = subprocess.Popen(
        [str(EXE), "--path", str(ROOT)],
        cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
    time.sleep(alive)
    rect = find_window_rect(TITLE)
    if rect is None:
        print("WINDOW NOT FOUND")
        proc.terminate()
        if clean:
            pet_toggle_visible()
        sys.exit(2)
    img = ImageGrab.grab(bbox=rect, all_screens=True)
    img.save(out)
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    if clean:
        pet_toggle_visible()
    print("saved", out, "rect", rect)


if __name__ == "__main__":
    main()
