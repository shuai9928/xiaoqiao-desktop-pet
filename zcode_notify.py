# -*- coding: utf-8 -*-
"""ZCode hook -> 小乔播报。

ZCode 在 ~/.zcode/cli/config.json 的 hooks 里配置(process 类型):
    Stop             -> ZCode 每轮回答结束时:python zcode_notify.py stop
    PermissionRequest-> ZCode 弹确认框等你点头:python zcode_notify.py permission

stdin 会收到 hook 的 JSON 输入,这里不解析、直接忽略。播报通过写
pet_cmd.json 的 {"op":"announce"} 实现,桌宠渲染循环每帧检测 mtime,
她在桌面右下角冒个气泡就把话带到了。

桌宠没开时:
    stop       -> 什么都不做(每轮回答结束都把她拉起来太吵)
    permission -> 先把她启动再播报。确认框漏看就是干等,不能静默丢掉。
                  hook 进程本身立刻返回,拉起和投递交给一个脱离的子进程
                  (python zcode_notify.py --deliver),不拖住 ZCode。
"""
import ctypes
import json
import os
import random
import shutil
import subprocess
import sys
import time
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
CMD = os.path.join(HERE, "pet_cmd.json")
STATE = os.path.join(HERE, ".zcode_hook_state.json")
PET = os.path.join(HERE, "pet.py")

MUTEX_NAME = "XiaoqiaoPet_SingleInstance"    # 与 pet.py main() 里的同名
WINDOW_TITLE = "小乔 · 时之魔女"               # Pet.__init__ 里 root.title()
SYNCHRONIZE = 0x00100000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

STOP_LINES = [
    "主人忙完一段啦,歇会儿眼睛~",
    "搞定一段!剩下的我来陪你~",
    "呼——干完一段了,伸个懒腰吧",
    "任务告一段落,记得喝水哦",
]
PERM_LINES = [
    "主人!ZCode 有确认框等你点头!",
    "喂喂,快去点一下确认,人家等着呢~",
    "有个弹窗在等你批准,快去看看!",
]


def announce(text, emotion="happy"):
    try:
        # 原子替换:桌宠按 mtime 轮询本文件,直接 open("w") 会让它读到
        # 写了一半的 JSON,这条播报就丢了
        tmp = CMD + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"op": "announce", "text": text, "emotion": emotion},
                      f, ensure_ascii=False)
        os.replace(tmp, CMD)
    except Exception:
        pass  # 盘不可写也无所谓,hook 不能因此报错


def pet_running():
    """查单实例互斥体是否存在。比扫进程可靠:看门狗自重启、换解释器都不影响。"""
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        k32.OpenMutexW.restype = wintypes.HANDLE
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        h = k32.OpenMutexW(SYNCHRONIZE, False, MUTEX_NAME)
        if h:
            k32.CloseHandle(h)
            return True
    except Exception:
        pass
    return False


def pet_window_ready():
    """窗口标题在 Pet.__init__ 里设置,晚于 _cmd_seen 的初始化 ——
    窗口出现后再写播报,才不会被当成启动前的旧指令忽略。"""
    try:
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        u32.FindWindowW.restype = wintypes.HWND
        return bool(u32.FindWindowW(None, WINDOW_TITLE))
    except Exception:
        return False


def find_pythonw():
    # 与 重启小乔.bat / 开机自启注册项用的解释器保持一致
    cand = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                        "Python", "pythoncore-3.14-64", "pythonw.exe")
    if os.path.exists(cand):
        return cand
    found = shutil.which("pythonw")
    if found:
        return found
    guess = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return guess if os.path.exists(guess) else sys.executable


def spawn_detached(args):
    subprocess.Popen(args, cwd=HERE, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL,
                     creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)


def deliver(text, emotion, timeout=30.0):
    """脱离子进程里跑:必要时拉起桌宠,等她就绪后再播报。"""
    if not pet_running():
        # 重复拉起也安全:pet.py 的单实例保护会让后来的那只自己退出
        spawn_detached([find_pythonw(), PET])
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pet_running() and pet_window_ready():
            time.sleep(1.0)      # 保证 mtime 严格晚于她启动时记下的 _cmd_seen
            announce(text, emotion)
            return 0
        time.sleep(0.3)
    return 1                     # 等不到就算了,别无限挂着


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--deliver":
        return deliver(random.choice(PERM_LINES), "surprised")

    event = (sys.argv[1] if len(sys.argv) > 1 else "stop").lower()
    try:
        if not sys.stdin.isatty():
            sys.stdin.read()
    except Exception:
        pass

    if event == "permission":
        # 要人点头的事不限频,漏一次就可能干等
        if pet_running():
            announce(random.choice(PERM_LINES), "surprised")
        else:
            try:
                spawn_detached([find_pythonw(), os.path.abspath(__file__),
                                "--deliver"])
            except Exception:
                pass
        return 0

    # stop:3 分钟最多播一次,不然每轮回答结束都吵一句;她没开就不打扰
    if not pet_running():
        return 0
    now = time.time()
    try:
        last = json.load(open(STATE, encoding="utf-8")).get("last_stop", 0)
    except Exception:
        last = 0.0
    if now - last < 180:
        return 0
    try:
        json.dump({"last_stop": now}, open(STATE, "w", encoding="utf-8"))
    except Exception:
        pass
    announce(random.choice(STOP_LINES), "happy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
