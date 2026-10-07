# -*- coding: utf-8 -*-
"""小乔 · 时之魔女 —— 2.5D 视差桌宠(核心陪伴版)"""

import base64
import ctypes
import faulthandler
import hashlib
import io
import json
import math
import os
import queue
import random
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.parse
import urllib.request
import webbrowser
from collections import OrderedDict
from ctypes import wintypes

PET_SWAY = True  # 次级物理总开关(性能回退用)
PET_SCENE_ART = True  # 秋千用原画分层(assets/scene/);素材不在就退回程序画的秋千
import agent
import scene_art
import ui3d
import fx
import life
import seat_motion
from fx import transform_ribbons
from depth_model import DepthWarp, DepthMotion

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageGrab, ImageTk

# 必须在任何 Tk 调用前设 DPI awareness(否则分层窗口尺寸错位)
def _set_dpi_awareness():
    # SetProcessDpiAwarenessContext 在 user32 里,不在 shcore —— 原来从 shcore
    # 取它永远 AttributeError,于是一直静默回退到 per-monitor v1,多屏不同缩放
    # 时对话框会发虚。参数是指针大小的句柄,必须声明 argtypes。
    try:
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        u32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        u32.SetProcessDpiAwarenessContext.restype = ctypes.c_int
        if u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):  # per-monitor v2
            return
    except Exception:
        pass
    for level in (2, 1):            # per-monitor v1 / system DPI aware
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(level)
            return
        except Exception:
            pass


_set_dpi_awareness()

try:
    import pystray
    HAS_TRAY = True
except Exception:
    HAS_TRAY = False

# ---------------- 基本参数 ----------------
# 打包成 exe 之后 __file__ 指向 PyInstaller 的临时解包目录,配置和聊天记录
# 写在那里会随进程退出一起消失。所以冻结状态下一律以 exe 所在目录为准 ——
# assets/ 也放在 exe 旁边,用户想换立绘直接替换文件就行。
if getattr(sys, "frozen", False):
    HERE = os.path.dirname(sys.executable)
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")

# ---------------- 开机自启(HKCU 注册表 Run 键,无需管理员) ----------------
AUTOSTART_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_NAME = "XiaoqiaoPet"


def autostart_command():
    """开机自启要写进注册表的命令行。

    非打包运行时必须换成 pythonw.exe:如果桌宠是用 python.exe(或 IDE)
    启动的,sys.executable 就是带控制台的那个,开机时会跟着弹一个黑框。
    """
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = sys.executable
    if os.path.basename(exe).lower() == "python.exe":
        noconsole = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(noconsole):
            exe = noconsole
    return f'"{exe}" "{os.path.join(HERE, "pet.py")}"'


def autostart_enabled():
    try:
        r = subprocess.run(
            ["reg", "query", rf"HKCU\{AUTOSTART_RUN}", "/v", AUTOSTART_NAME],
            capture_output=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        # reg.exe 输出是系统 OEM/GBK 编码,别用 text=True(UTF-8 会炸)
        out = r.stdout.decode("gbk", "replace") if r.stdout else ""
        return r.returncode == 0 and AUTOSTART_NAME in out
    except Exception:
        return False


def autostart_set(on):
    try:
        if on:
            r = subprocess.run(
                ["reg", "add", rf"HKCU\{AUTOSTART_RUN}", "/v", AUTOSTART_NAME,
                 "/t", "REG_SZ", "/d", autostart_command(), "/f"],
                capture_output=True, timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return r.returncode == 0
        subprocess.run(
            ["reg", "delete", rf"HKCU\{AUTOSTART_RUN}", "/v", AUTOSTART_NAME, "/f"],
            capture_output=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except Exception:
        return False


CONFIG_FILE = os.path.join(HERE, "pet_settings.json")
REMINDERS_FILE = os.path.join(HERE, "pet_reminders.json")
KEY = "#010203"  # 聊天面板/桌宠透明色

BASE_W, BASE_H = 430, 520
SS = 2
DEBUG_STATE = "--debug-state" in sys.argv   # 写 pet_state.json(每秒一次)
MAX_PARTS = 320          # 同时存在的粒子上限,防止庆典特效叠爆
WATCHDOG_STALE = 30      # 主循环心跳停滞多少秒算卡死(看门狗自重启)
WARP_CACHE_MAX = 12      # 每张 = 精灵尺寸的 RGBA,1.5 倍缩放下约 4.3MB
GLOW_CACHE_MAX = 96      # 光晕精灵,键量化后条目数很小,每张最大约 56KB
# 值得给 60fps 的状态:拖拽和这些演出动作,别的时候 30fps 看不出差别。
# 这里写的必须是 self.state 真会被赋成的字面量 —— 曾经写成 "casting"
# (真名是 "magic",旁边 render 里那个局部变量才叫 casting),于是旗舰的
# 时间魔法一直在 30fps 上演;而旧用例自己也手写 "casting" 去断言,刚好
# 把这个错误一起验证成了"正确"。见 test_pet.py 的"状态名防线"。
FAST_STATES = frozenset((
    "magic", "tstop", "rewind",      # 时间魔法三兄弟,全片最快的一段
    "dance", "flip", "roll", "twirl", "transform",
    "fly", "fall", "peek", "stretch", "wave", "sneeze",
    "chase",                         # 整只横向追光标,30fps 有台阶感
    "meditate",                      # 浮空冥想:环绕星尘 + 悬停起伏
    "dizzy"))                        # dizzy_amp 驱动的高频摇摆,欠采样会抖
# 氛围粒子:慢速飘浮的环境元素,20fps 也看不出差别,不该把待机拽到 60fps
# (与之相对,"star/confetti/gear"这类演出粒子速度快,仍然走 60fps 档)
AMBIENT_PARTS = frozenset(
    ("zzz", "snow", "petal", "leaf", "firefly", "sparkle", "note"))
# note 是哼歌的音符:24~40px/秒,20fps 下每帧才走 1.6px。它以前不在这里,
# 于是一次没人要求的哼歌要把待机顶成 60fps 整整 2 秒(实测 901ms CPU,
# 安静档只要 424ms)。唱歌/跳舞照样是 60fps —— 那两个由 singing 标志和
# FAST_STATES 管,主人点的演出不该跟着氛围粒子降档(E39)。
CALM_PARTS = frozenset(("meteor",))
# 夜间流星:680px/秒,20fps 会有台阶感,但 0.85 秒的背景氛围也不值 60fps。
# 它的拖尾 109px 比 30fps 的每帧位移 23px 长得多,连成一条不会断。
# 放这里 = 不进 60fps 档,但仍然拦住安静档(落到 30fps)。
_NOT_FAST_PARTS = AMBIENT_PARTS | CALM_PARTS
# 专注陪伴:她安静地待着,每隔这么久用几点星光说一次"我在"。
# 25 分钟一段约 3~6 次。只用 sparkle —— 它在 AMBIENT_PARTS 里,
# _quiet_idle_ok 和 _frame_delay 都不把它算成"画面在动",所以整段陪伴
# 演出的帧率成本是 0。heart / confetti / gear 都会把 20fps 档
# 顶成 60fps 并持续整个粒子寿命,别用。
FOCUS_ENCOURAGE = (240.0, 420.0)
FAST_BUDGET_MS = 13.0    # 单帧滑动平均超过它就退回 30fps(16ms 排期留余量)
RIPPLE_PERIOD = 5.2      # 法阵光纹:每隔多久荡出一道
RIPPLE_TRAVEL = 1.8      # 一道光纹从内圈走到外圈用多久
HIT_RING_LIFE = 0.38     # 命中光环(hit_ring 粒子)寿命,一次点击的"啪"
# 蹦跳:一次 hop 拆成"蹲一下 + 若干个抛物线小跳"。原来用全局时钟的
# abs(sin(16t)),起跳那帧可能正落在半空(凭空瞬移上去),结束那帧也可能
# 在半空(啪地掉回地面),每次触地也没有压扁。
HOP_CROUCH = 0.07
HOP_PERIOD = 0.2
GAIN_LIFE = 0.95         # 星光飘字 "+N✦" 从出现到淡完
# 光标感应:光标离她胸口多远时法阵开始"醒"、多近时满(px/scale)
PROX_FAR = 320.0
PROX_NEAR = 120.0
PUFF_LIFE = 0.42         # 喷气团(喷嚏/撞墙)
SPEED_LINE_MIN = 420.0   # 飞行速度超过它(px/s)才画速度线
SPEED_LINE_FULL = 1300.0 # 到这个速度速度线最长最亮
# 帽檐星轨:她的帽檐本来就画成了一圈"土星环",这里在同一个倾斜平面上放三颗
# 小天体绕帽子公转。坐标是 main.png 的像素(对着原画叠椭圆肉眼对齐帽檐)。
HAT_ORBIT_ART = (730.0, 750.0)
HAT_ORBIT = (400.0, 190.0, 380.0, 92.0, 27.0)    # 中心 x, y, 长半轴, 短半轴, 倾角(度)
# (精灵名, 轨道半径倍数, 公转周期秒, 初相位):里圈快、外圈慢,像真的行星。
# 外圈不超过 1.0:第一版星晶走 1.13 倍,近侧最低点压到她眼睛那条线上,
# 每 20 秒从眼前扫过一次
HAT_ORBIT_BODIES = (("moon", 0.84, 11.0, 0.4),
                    ("crystal", 0.92, 15.0, 4.6),
                    ("planet", 1.0, 20.0, 2.6))
HAT_ORBIT_TRAIL = 6      # 每颗身后拖几个轨迹点
HAT_ORBIT_PATH = 32      # 中间那圈轨道画成多少个淡淡的虚点
_HAT_PATH_CACHE = []     # 轨道虚点是静态几何,算一次就够
HAT_ORBIT_TRAIL_GAP = 0.085   # 轨迹点之间差多少弧度
SPRITE_H = 350
FEET_GAP = 140
SPEED = 40.0
PARALLAX_AMP = 9.0

MAGIC_A = (168, 216, 255)
MAGIC_B = (199, 155, 255)
GOLD = (242, 193, 78)
GOLD_L = (255, 233, 160)
HEART_C = (255, 95, 138)
WHITE = (255, 255, 255)
STAR_COLORS = [(242, 193, 78), WHITE, (255, 178, 200), (159, 216, 255),
               (201, 242, 255), (230, 204, 255)]
INK = (46, 26, 82)

# ---- tkinter 面板/对话框主题(上面那组 RGB 元组是给 PIL 画角色用的)----
# 原来 29 处 #RRGGBB 散在各处:同一个暗紫底被写成 #221C40 和 #1D1838 两份
# (复制粘贴出来的巧合),#EDE7FF 手打了 5 遍。这里收口成一套,顺便把那两个
# 近似色明确成"面板底 / 抬起面板"两档,原来的巧合变成有意的层次。
# 2026-10-05:克制但保留魔女主题 —— 和月窗小屋书板同一套紫(石墨版丢了主题)
UI_BG       = "#251C35"   # 面板底
UI_PANEL    = "#2F2342"   # 抬起的面板、对话框底
UI_FIELD    = "#342848"   # 输入框
UI_BTN      = "#3B2E52"   # 次要按钮
UI_ACCENT   = "#7C58B8"   # 主按钮 / 强调(淡紫)
UI_TEXT     = "#F5EFE6"   # 主文字
UI_TEXT_DIM = "#B5A8C7"   # 次要文字
UI_TITLE    = "#F5EFE6"   # 标题
UI_WARN     = "#EFC17E"   # 校验提示
UI_GOLD     = "#DFC598"   # 主按钮文字 / 小标题金
UI_DANGER   = "#EF959A"   # 关闭 / 危险
UI_BORDER   = "#4A3A60"   # 卡片、记录区和输入框的统一描边

UI_FONT = "Noto Sans SC"
TYPE_TITLE, TYPE_BODY, TYPE_BTN, TYPE_HINT = 15, 14, 13, 10


def ui_font(px, u=1.0, bold=False):
    """统一字号阶梯。px 取 TYPE_* 档位,u 是按屏幕高度换算的 DPI 系数。"""
    return (UI_FONT, -int(px * u)) + (("bold",) if bold else ())


_DATE_RE = re.compile(r"^\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})\s*[日号]?\s*$")
# 2 月按 29 天算 —— 闰年生日是合法的
_DAYS_IN_MONTH = (0, 31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def parse_mmdd(s):
    """'09-15' / '9/15' / '3月5日' / '3月5号' -> (9, 15);看不懂返回 None。

    原来 anniv_dialog 和 birthday_dialog 各抄了一份一模一样的解析(连报错
    文案都一样),而且都只校验 1<=dd<=31 —— 2月31号能存进去。
    """
    m = _DATE_RE.match(str(s or ""))
    if not m:
        return None
    mm, dd = int(m.group(1)), int(m.group(2))
    if not (1 <= mm <= 12 and 1 <= dd <= _DAYS_IN_MONTH[mm]):
        return None
    return mm, dd

GREET = ["小乔回来啦~", "一起玩吧!", "嘿嘿,想我了吗?"]
HELP = "拖动移动 · 滚轮缩放 · 双击聊天 · 右键互动与场景"
IDLE_SAY = ["时间过得好快呀…", "要珍惜当下哟~", "在练习魔法哦",
            "别发呆啦,看看我嘛", "今天也是元气满满!", "星河很漂亮吧?",
            "今天的云朵好软呀~", "偷偷在练习新的魔法哦", "咦,时间又溜走了一点",
            "主人主人,看我一眼嘛~", "星星们今天也很安静呢", "刚才做了个小小的梦~"]
TICKLE_SAY = ["嘻嘻,好痒~", "别闹啦~", "嘿嘿嘿…", "哈哈哈哈别挠了!",
              "再挠要喘不上气啦…"]
HUNGRY_SAY = ["星光快用完了…", "想吃甜甜的糖果…", "没有力气施魔法了…",
              "肚子…不对,星光咕咕叫了…"]
NIGHT_SAY = ["夜深了…主人也要早点睡哦", "星星都困了,我也有一点点困…",
             "深夜的桌面好安静呀", "主人,别熬太晚嘛…"]
WAKE_LINES = ["呼啊…睡醒了", "梦到好多星星哦", "唔…我睡多久了?",
              "嘿嘿,梦到好吃的了~"]
STROKE_LINES = ["嘿嘿,好痒~", "蹭蹭~"]
CAST_LINES = ["时间魔法,发动!", "时光流转~", "看我的厉害!",
              "咻——时间听我指挥!", "魔法少女小乔,登场!"]
WHEEL_LINES = ["呜…头发乱掉啦", "顺毛好舒服~", "再多摸一会儿嘛", "唔…痒痒的"]
ENTER_LINES = ["你来啦!", "欸,发现你了~", "在这儿在这儿!"]
LEAVE_LINES = ["诶,要走了吗…", "我等你回来哦", "拜拜~",
               "路上小心哦~", "记得想我一点点就好"]
DIZZY_LINES = ["晕…晕了…", "别摇啦!星星在转圈", "呜哇——"]
DANCE_LINES = ["看我跳舞!", "一起摇摆吧~", "今天心情超好!",
               "转圈圈~晕了也要转!", "我的舞台就是主人的桌面!"]
CHASE_LINES = ["等等我!", "光标跑那么快干嘛~", "抓到你了!",
               "追上你啦,嘿嘿~", "我的腿都要跑细了…"]
MELT_LINES = ["呀…再摸就要融化啦~", "呜,头要冒烟了啦!", "嘿嘿…喜欢我到这个程度吗?",
              "呀!头发都要飞起来啦~"]
REUNION_LINES = ["主人终于回来啦!我等好久了~", "呜呜,终于回来了…",
                 "你不在的时候,我可想你了!"]
STRETCH_LINES = ["唔——伸个懒腰", "骨头都松啦~", "呼…舒服",
                 "把瞌睡虫都伸跑啦~", "嗯——睡醒要伸个懒腰~",
                 "呜哇,身体好僵…伸个懒腰!", "伸——展——时——间——到!"]
PEEK_LINES = ["外面有什么呢…", "唔,风景不错", "在想事情…",
              "咦,那个窗口在干嘛?", "假装在观察世界~"]
MIDDLE_LINES = ["变个魔术!", "锵锵~", "惊不惊喜?"]
PERIOD_GREET = {
    "morning": (["早安呀!", "今天也要元气满满~"], "greet"),
    "noon":    (["中午啦,吃饭了吗?", "午休一下嘛"], "mild"),
    "evening": (["晚上好~", "今天辛苦啦"], "tired"),
    "night":   (["这么晚还不睡?", "熬夜对身体不好哦…"], "lazy"),
}
# 被冷落撒娇(15 分钟一次上限):清醒时委屈,睡着时说梦话
WHINE_LINES = ["主人去哪了呀…我等好久了…", "哼,都不理我…",
               "呜…一个人的桌面好冷清…", "摸摸我嘛,就摸一下~"]
SLEEP_WHINE_LINES = ["唔…主人…", "别丢下小乔…", "呼…呼…主人…"]

# ---------------- Win32 ----------------
user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
winmm = ctypes.WinDLL("winmm", use_last_error=True)

# 显式声明 argtypes/restype:64 位 Windows 下若不声明,ctypes 会按默认 32 位 int
# 猜测参数/返回值类型,导致 HWND/HDC 等指针型句柄高 32 位被截断成垃圾值,
# UpdateLayeredWindow 等调用随即以 ERROR_INVALID_WINDOW_HANDLE(1400)失败,
# 桌宠因此完全不渲染却不报任何异常。
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
user32.MonitorFromPoint.restype = wintypes.HANDLE
user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
user32.GetMonitorInfoW.restype = wintypes.BOOL
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_void_p
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
user32.SetWindowLongPtrW.restype = ctypes.c_void_p
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
# 鼠标穿透投递需要:不显式声明 argtypes,64 位 Windows 下 ctypes 会按
# 默认 32 位 int 猜测,HWND 指针型句柄高 32 位被截断,WindowFromPoint/
# PostMessageW 会返回错的窗口或直接失败。
user32.WindowFromPoint.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.ScreenToClient.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
    ctypes.POINTER(wintypes.SIZE), wintypes.HDC, ctypes.POINTER(wintypes.POINT),
    wintypes.COLORREF, ctypes.c_void_p, wintypes.DWORD]
user32.UpdateLayeredWindow.restype = wintypes.BOOL
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL


def mci(c):
    buf = ctypes.create_unicode_buffer(260)
    return winmm.mciSendStringW(c, buf, 259, 0), buf.value


# ---------------- 音效(CC0/自制,来源与许可证见 assets/audio/CREDITS.md) ----------------
SFX_DIR = os.path.join(ASSETS, "audio")
# 行为 -> 音效名 -> 候选文件(播放时随机挑一个,避免每次都一模一样)
SFX_FILES = {
    "voice_happy":    ("voice_happy_1", "voice_happy_2", "voice_happy_3"),
    "voice_giggle":   ("voice_giggle_1", "voice_giggle_2", "voice_giggle_3"),
    "voice_magic":    ("voice_magic_1", "voice_magic_2", "voice_magic_3"),
    "voice_play":     ("voice_play_1", "voice_play_2", "voice_play_3"),
    "voice_yum":      ("voice_yum_1", "voice_yum_2"),
    "voice_surprise": ("voice_surprise_1", "voice_surprise_2", "voice_surprise_3"),
    "magic":          ("magic_1", "magic_2", "magic_3", "magic_4", "magic_5", "magic_6"),
    "boing":          ("boing_1", "boing_2", "boing_3"),
    "sparkle":        ("sparkle_1", "sparkle_2", "sparkle_3"),
    "sleep":          ("sleep_1", "sleep_2"),
    "wake":           ("wake_1", "wake_2"),
    "levelup":        ("levelup_1", "levelup_2", "levelup_3"),
    "pop":            ("pop_1", "pop_2"),
    "notify":         ("notify_1", "notify_2"),
    "greet":          ("greet_1", "greet_2", "greet_3"),
    "bye":            ("bye_1", "bye_2", "bye_3"),
    "tick":           ("tick_1", "tick_2"),
}


class SFX:
    """桌宠小音效:复用 winmm MCI(和唱歌同一套 mci 通道)。

    - 全局限频:最多每 5 秒出一次声(主人定的,嫌吵)。间隔不足 5 秒时
      新请求直接丢弃,正在播的那条继续播完;
    - 同一时刻只播最新的:"main"槽位上真有新声音获准播放时,会立刻
      close 掉上一条,永远不会叠罗汉;
    - 唯一的例外是"fx"槽位:施法时魔法闪烁垫在人声下面。它不占 5 秒
      全局名额,但只在人声获准播放的同一拍才跟着出(cast_magic 里连锁),
      所以听感上仍是"5 秒一次";
    - 音量已经在预处理时烘焙进文件(MCI 的 waveaudio 不支持运行时调音量),
      详见 assets/audio/CREDITS.md;
    - assets/audio 缺失或 MCI 失败时静默跳过,绝不影响原有动画和交互。
    """

    GLOBAL_CD = 5.0     # 任意两个音效之间的最小间隔(最多每 5 秒响一次)
    CLOSE_DELAY = 0.5   # 播完再回收 alias 的余量(秒)
    CD = {              # 同名音效的最小重触发间隔(全局限频之外的安全网)
        "voice_happy": 0.7, "voice_giggle": 0.7, "voice_magic": 0.9,
        "voice_play": 0.8, "voice_yum": 0.8, "voice_surprise": 0.8,
        "magic": 1.2, "boing": 0.5, "sparkle": 0.6, "sleep": 1.5,
        "wake": 1.0, "levelup": 0.8, "pop": 0.8, "notify": 1.5,
        "greet": 2.5, "bye": 2.5, "tick": 1.0,
    }

    def __init__(self, root):
        self.root = root
        self.enabled = True
        self._n = 0
        self._next_any = 0.0
        self._next = {}
        self._chan = {}     # 槽位 -> 当前 alias("main"=最新语音,"fx"=闪烁层);只在音频线程里读写
        self._closes = []   # [(到点时间, alias, 槽位)] 播完回收;只在音频线程里读写
        self._song = None   # 正在放的歌 alias;只在音频线程里读写
        self.song_playing = False   # 音频线程写、UI 线程读的只读标志
        self._q = queue.Queue()
        self._worker = None
        self.groups = {}
        for name, stems in SFX_FILES.items():
            files = [os.path.join(SFX_DIR, s + ".wav") for s in stems]
            files = [f for f in files if os.path.exists(f)]
            if files:
                self.groups[name] = files

    def play(self, name, fx=False):
        """尝试播一个音效。返回 True=已排进音频线程,False=被限频/关闭跳过。

        限频判断在这里同步做完(纯算术,瞬间);MCI 的 open/play/status 全部交给
        音频线程。原来这三次 MCI 调用在 UI 线程上串行执行,实测 Pet() 构造时
        开场那一声就占了 572ms(open 本身只要 20~55ms,余下几乎都是 play),
        播音效期间动画是冻住的。现在 MCI 失败只会少一声,不再能反馈给调用方
        —— 调用方从来只用返回值判断"有没有被限频"。"""
        if not self.enabled or name not in self.groups:
            return False
        try:
            now = time.time()
            # fx 层不占全局名额:它跟着获准播放的人声同拍出(施法),
            # 否则背靠背的两连叫会被 GLOBAL_CD 拦掉
            if not fx and now < self._next_any:
                return False
            if now < self._next.get(name, 0):
                return False
            if not fx:
                self._next_any = now + self.GLOBAL_CD
            self._next[name] = now + self.CD.get(name, 0.15)
            self._n += 1
            alias = f"petsfx{self._n}"      # 每次唯一,旧 alias 的定时回收不会误伤新播放
            self._ensure_worker()
            self._q.put(("play", "fx" if fx else "main", alias,
                         random.choice(self.groups[name])))
            return True
        except Exception:
            return False

    def play_song(self, path, volume=600):
        """把一首歌交给音频线程播放。返回 False = 声音总开关关着,没出声。

        原来 sing() 直接在 UI 线程 open/play 这首 mp3:实测 open 17~59ms、
        play 271~429ms,点「唱首歌」画面要僵住小半秒。而且它绕过了
        「语音(全部声音)」开关 —— 关掉声音照样唱出声。
        """
        if not self.enabled:
            return False
        self._ensure_worker()
        self._q.put(("song", str(path), int(volume)))
        return True

    def stop_song(self):
        if self._worker is not None and self._worker.is_alive():
            self._q.put(("song_stop",))
        self.song_playing = False

    def _ensure_worker(self):
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._run, name="pet-sfx", daemon=True)
            self._worker.start()

    def _run(self):
        """音频线程:所有 SFX 的 MCI 调用都在这一条线程上,设备的打开和关闭同线程。"""
        while True:
            timeout = None
            if self._closes:
                timeout = max(0.0, min(t for t, _, _ in self._closes) - time.time())
            if self._song:
                timeout = 0.5 if timeout is None else min(timeout, 0.5)   # 歌放完要收尾
            try:
                job = self._q.get(timeout=timeout)
            except queue.Empty:
                job = None
            now = time.time()
            for item in [c for c in self._closes if c[0] <= now]:
                self._closes.remove(item)
                self._close(item[1], item[2])
            if self._song:
                _, mode = mci(f'status {self._song} mode')
                if "playing" not in (mode or "").lower():
                    self._stop_song()
            if job is None:
                continue
            kind = job[0]
            if kind == "play":
                self._do_play(*job[1:])
            elif kind == "song":
                self._do_song(*job[1:])
            elif kind == "song_stop":
                self._stop_song()
            elif kind == "close_all":
                for slot, a in list(self._chan.items()):
                    self._close(a, slot)
                self._closes.clear()
                self._stop_song()
                job[1].set()
            elif kind == "stop":
                return

    def _do_play(self, slot, alias, src):
        try:
            old = self._chan.get(slot)
            if old:
                mci(f'close {old}')         # 最新胜出:立刻掐掉这条槽上的上一条
                self._chan.pop(slot, None)
            err, _ = mci(f'open "{src}" type waveaudio alias {alias}')
            if err != 0:
                return
            err, _ = mci(f'play {alias}')
            if err != 0:
                print(f"[SFX DEBUG] play err={err} alias={alias}")
                mci(f'close {alias}')
                return
            self._chan[slot] = alias
            _, dur = mci(f'status {alias} length')   # 毫秒
            ms = int(dur) if (dur or "").isdigit() else 3000
            self._closes.append((time.time() + ms / 1000.0 + self.CLOSE_DELAY, alias, slot))
        except Exception:
            pass

    def _do_song(self, path, volume):
        self._stop_song()
        alias = "petsong"
        try:
            err, _ = mci(f'open "{path}" type mpegvideo alias {alias}')
            if err != 0:
                return
            mci(f'setaudio {alias} volume to {volume}')
            err, _ = mci(f'play {alias}')
            if err != 0:
                mci(f'close {alias}')
                return
            self._song = alias
            self.song_playing = True
        except Exception:
            self.song_playing = False

    def _stop_song(self):
        self.song_playing = False
        alias, self._song = self._song, None
        if not alias:
            return
        try:
            mci(f'stop {alias}')
            mci(f'close {alias}')
        except Exception:
            pass

    def _close(self, alias, slot=None):
        try:
            if slot and self._chan.get(slot) == alias:
                self._chan.pop(slot, None)
            mci(f'close {alias}')
        except Exception:
            pass

    def close_all(self, wait=1.0):
        """退出时收掉所有还开着的音频设备。在音频线程里做,最多等 wait 秒。"""
        if self._worker is None or not self._worker.is_alive():
            return
        done = threading.Event()
        self._q.put(("close_all", done))
        done.wait(wait)


# ---------------- 在线 TTS(聊天时现合成)----------------
# assets/audio 里的反馈音是 gen_voice_tts.py 用晓晓预渲染好的,但聊天回复是
# 动态文本没法预渲染。以前这里走系统 SAPI,音色和她的反馈音完全对不上 ——
# 一个是神经网络女声,一个是 Windows 自带的机器音,听起来像两个人。
# 所以改成运行时调同一个 edge-tts,音高/语速也对齐 gen_voice_tts.py 那一档。
# 拿不到就退回 SAPI:声音变回机器音,但不会哑掉。
TTS_VOICE = "zh-CN-XiaoxiaoNeural"
TTS_PITCH = "+25Hz"        # gen_voice_tts.py 的 CLIPS 用的是 +20~38Hz
TTS_RATE = "+8%"
TTS_CACHE = os.path.join(HERE, "_tts_cache")
TTS_CACHE_MAX = 300        # 固定台词(问候/帮助/碎碎念)会命中缓存,第二次起零延迟
_tts_py = None             # None=还没找过;False=找过,没有


def tts_python():
    """找到装了 edge_tts 的解释器。打包版不带 venv 时返回 None,自动退回 SAPI。"""
    global _tts_py
    if _tts_py is not None:
        return _tts_py or None
    for c in (os.environ.get("PET_TTS_PYTHON"),
              os.path.join(HERE, "_sfx_dl", "ttsvenv", "Scripts", "python.exe"),
              os.path.join(HERE, "ttsvenv", "Scripts", "python.exe")):
        if c and os.path.exists(c):
            _tts_py = c
            return c
    _tts_py = False
    return None


# ---------------- 屏幕边界 ----------------
# winfo_screenwidth() 只给主屏尺寸,而且只在启动时取一次。后果是:
# 插拔外接屏/改分辨率之后她的"地面"还是旧值(可能悬空或陷进任务栏),
# 而且她永远走不到第二块屏幕上。这里改成读虚拟桌面 + 当前显示器工作区。
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79
MONITOR_DEFAULTTONEAREST = 2


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", _RECT),
                ("rcWork", _RECT), ("dwFlags", wintypes.DWORD)]


def build_stamp():
    """当前跑的到底是哪一份代码(取 pet.py / exe 的修改时间)。

    这一路上"改完没生效"排查了太多次 —— 进程没重启、跑的是打包版、
    读到另一个目录的副本,表现全都是"我改的东西不见了"。
    把它显示在菜单标题上、开机写进日志,一眼就能对上。
    """
    try:
        p = (sys.executable if getattr(sys, "frozen", False)
             else os.path.abspath(__file__))
        return time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(p)))
    except Exception:
        return "?"


def virtual_screen():
    """所有显示器并集的范围 (x, y, w, h)。取不到返回 None。"""
    try:
        g = user32.GetSystemMetrics
        w, h = g(SM_CXVIRTUALSCREEN), g(SM_CYVIRTUALSCREEN)
        if w > 0 and h > 0:
            return g(SM_XVIRTUALSCREEN), g(SM_YVIRTUALSCREEN), w, h
    except Exception:
        pass
    return None


def monitor_rect_at(x, y, work=False):
    """点 (x, y) 所在显示器的矩形。work=True 取工作区(扣掉任务栏),
    否则取整块屏幕 —— 全屏魔法要连任务栏一起盖住才够劲。"""
    try:
        hm = user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)),
                                     MONITOR_DEFAULTTONEAREST)
        mi = _MONITORINFO()
        mi.cbSize = ctypes.sizeof(_MONITORINFO)
        if user32.GetMonitorInfoW(hm, ctypes.byref(mi)):
            r = mi.rcWork if work else mi.rcMonitor
            return r.left, r.top, r.right, r.bottom
    except Exception:
        pass
    return None


def work_area_at(x, y):
    """点 (x, y) 所在那块显示器的工作区(已扣掉任务栏)。取不到返回 None。"""
    try:
        hm = user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)),
                                     MONITOR_DEFAULTTONEAREST)
        mi = _MONITORINFO()
        mi.cbSize = ctypes.sizeof(_MONITORINFO)
        if user32.GetMonitorInfoW(hm, ctypes.byref(mi)):
            r = mi.rcWork
            return r.left, r.top, r.right, r.bottom
    except Exception:
        pass
    return None


# ---------------- 工具函数 ----------------
def cursor_pos():
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


class LightLayer:
    """加色光层:让重叠的光晕真的更亮,而不是互相盖住。

    项目里所有合成都是 PIL 的 alpha-over —— 两团光晕叠在一起时,后画的那
    团直接顶掉先画的,重叠处不但没更亮,后者 RGB 更暗时还会把亮处压暗。
    这正是密集粒子看起来发灰发平的根因,光的正确叠加方式是相加。

    做法:发光的东西先攒进这一层,层内用 ImageChops.add 相加(RGB 和 alpha
    都加,饱和不回绕),整层最后按脏矩形一次性 alpha-over 回主帧。

    两个关键性质:
      - 只有一团光时,层里就是那张光晕原图,贴回去与改动前逐位相同 ——
        不会整体走色,只有重叠处才变化。
      - 按脏矩形操作,成本与实际发光面积成正比;一帧没有任何发光元素时
        box 是 None,整条路径零开销。
    """
    __slots__ = ("im", "box")

    def __init__(self, size):
        self.im = Image.new("RGBA", size, (0, 0, 0, 0))
        self.box = None

    def add(self, spr, cx, cy):
        w, h = self.im.size
        x0, y0 = int(cx - spr.width / 2), int(cy - spr.height / 2)
        x1, y1 = x0 + spr.width, y0 + spr.height
        cx0, cy0 = max(0, x0), max(0, y0)
        cx1, cy1 = min(w, x1), min(h, y1)
        if cx1 <= cx0 or cy1 <= cy0:
            return                      # 整个飘到画布外了
        box = (cx0, cy0, cx1, cy1)
        # ImageChops 要求两张图尺寸一致,越界的先把精灵裁掉
        sub = spr if box == (x0, y0, x1, y1) else spr.crop(
            (cx0 - x0, cy0 - y0, cx1 - x0, cy1 - y0))
        self.im.paste(ImageChops.add(self.im.crop(box), sub), box)
        b = self.box
        self.box = box if b is None else (
            min(b[0], box[0]), min(b[1], box[1]),
            max(b[2], box[2]), max(b[3], box[3]))

    def flush(self, frame):
        if self.box is None:
            return
        b = self.box
        crop = self.im.crop(b)
        frame.paste(crop, b, crop)
        self.im.paste((0, 0, 0, 0), b)   # 只清脏矩形,不动整张
        self.box = None


def tail_fade(kk, tail=0.3):
    """生命末段的淡出系数。kk 是归一化年龄(0..1),返回 1 -> 0。

    大多数粒子自己带 (1 - kk*f) 的淡出,但 sweat / snow / ball 是画完就
    等寿命到、被清理直接过滤掉 —— 观感上是"啪"一下凭空消失。
    """
    if kk < 1.0 - tail:
        return 1.0
    return max(0.0, (1.0 - kk) / tail)


def approach(cur, target, rate, dt):
    """帧率无关的指数逼近,替换 `x += (target - x) * rate` 这种写法。

    rate 直接沿用老代码里那个调好的系数(30fps 下每帧吃掉的残差比例),
    所以 dt == 1/30 时结果与老写法逐位相同 —— 现在的手感一个字节都不会
    变,只有帧率偏离 30fps 时才开始纠偏。

    数学上:老写法每 1/30 秒保留 (1-rate) 倍残差,dt 秒就该保留
    (1-rate)**(30*dt) 倍。直接用幂形式,省掉一次 log,而且无论 dt 多大
    残差因子恒在 [0,1] —— 卡顿一整秒也不会过冲。

    原来的问题:_frame_delay 睡眠时降到 10fps,同一个每帧系数在真实时间
    里就慢了 3 倍,所以睡醒那一下她的视线要爬好几帧才跟上光标。
    """
    if rate >= 1.0:
        return target
    if dt <= 0.0:
        return cur
    return cur + (target - cur) * (1.0 - (1.0 - rate) ** (dt * 30.0))


def premult_bgra(img):
    """RGBA 图 → 预乘 alpha 的 BGRA 字节串(推分层窗口专用,每帧都走)。

    预乘单趟 convert("RGBa") 在 C 里做完,比 3 次 ImageChops.multiply
    + merge 快约 1/3(645x780 实测 7.8ms → 5.2ms,全屏画布省得更多);
    Pillow 没有 RGBa→BGRA 的 packer,字节序用 bytearray 切片把 R/B
    对调(现已改用 Pillow 自带的 BGRa packer)。与旧实现逐字节比只有 0.9% 的中间 alpha 像素差 ±1 舍入,
    肉眼不可见。Windows 32 位 DIB(BI_RGB)按 B,G,R,A 存放,所以必须
    是 BGRA —— 直接 RGBA 取字节会让蓝发变橙发。
    """
    # Pillow 的 RGBa 模式带 BGRa packer,一步取出预乘 BGRA 字节;原来的
    # bytearray 手工对调 R/B 与之逐字节相同,但多两次整帧拷贝(3.6ms -> 2.1ms)。
    # 已经是 RGBa 的(预乘域降采样出来的帧)不再转换。
    if img.mode != "RGBa":
        img = img.convert("RGBa")
    return img.tobytes("raw", "BGRa")


def load_font(size, sym=False):
    paths = (["C:/Windows/Fonts/seguisym.ttf"] if sym
             else ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/segoeui.ttf"])
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()


def point_in_poly(x, y, pts):
    """射线法判点在多边形内(归一化坐标,点击分区用)。"""
    inside = False
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def star_pts(cx, cy, ro, ri, n=5, rot=-math.pi / 2):
    pts = []
    for i in range(2 * n):
        r = ro if i % 2 == 0 else ri
        a = rot + math.pi * i / n
        pts.append((cx + math.cos(a) * r, cy + math.sin(a) * r))
    return pts


def flat_star(cx, cy, rx, ratio, ro, ri, n=5, rot=-math.pi / 2):
    pts = []
    for i in range(2 * n):
        r = ro if i % 2 == 0 else ri
        a = rot + math.pi * i / n
        pts.append((cx + math.cos(a) * r, cy + math.sin(a) * r * ratio))
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


def gear_pts(cx, cy, r, teeth, rot):
    """齿轮齿圈顶点:每齿四点撑出齿宽,不然会画成太阳(同 fx._gear_sprite)。"""
    tooth = r * 0.24
    body = max(1.0, r - tooth)
    hw = math.pi / teeth
    pts = []
    for i in range(teeth):
        a = rot + 2 * math.pi * i / teeth
        for da, rr in ((-hw * 0.62, body), (-hw * 0.30, r),
                       (hw * 0.30, r), (hw * 0.62, body)):
            pts.append((cx + math.cos(a + da) * rr, cy + math.sin(a + da) * rr))
    return pts


class FullscreenMagic:
    """全屏时间魔法的承载窗口。

    桌宠自己的窗口只有 645x780,特效画到边上就被裁掉了,所以"全屏版"
    必须另开一块盖住整个显示器的分层窗口。这块窗口点击穿透
    (WS_EX_TRANSPARENT),不会挡住底下任何东西,只在施法那两秒活着。

    每帧成本实测:绘制 1.1ms + 预乘取字节 19ms。绘制便宜是因为全是矢量,
    全屏画布上任何一次滤镜或缩放都要几十毫秒,一次都用不起。
    """

    def __init__(self, root):
        self.root = root
        self.win = None
        self.hwnd = 0
        self.art = None
        self.buf = None
        self.rect = None

    def _ensure(self, rect):
        if self.win is not None and self.rect == rect:
            return True
        self.close()
        x0, y0, x1, y1 = rect
        w, h = x1 - x0, y1 - y0
        try:
            win = tk.Toplevel(self.root)
            win.withdraw()                      # 先藏起来再配置
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            # 先让 Tk 把整窗透明度压到 0 再显示 —— 否则从 deiconify 到我们
            # 自己设好分层样式之间有一两帧,Tk 会拿窗口底色糊满整个屏幕,
            # 表现就是施法瞬间全屏黑闪一下
            win.attributes("-alpha", 0.0)
            win.geometry(f"{w}x{h}+{x0}+{y0}")
            win.deiconify()
            # HWND 必须在 overrideredirect/deiconify 之后取:Tk 在 Windows
            # 上会销毁重建顶层窗口,先取到的句柄当场作废(这个坑踩过一次)
            win.update_idletasks()
            hwnd = user32.GetAncestor(win.winfo_id(), 2) or win.winfo_id()
            ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) or 0
            user32.SetWindowLongPtrW(
                hwnd, GWL_EXSTYLE,
                int(ex) | WS_EX_LAYERED | WS_EX_TRANSPARENT)
        except Exception:
            self.close()
            return False
        self.win, self.hwnd, self.rect = win, hwnd, rect
        self.buf = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        self.art = fx.FullscreenArt(w, h)
        return True

    def frame(self, sx, sy, p):
        """画一帧。(sx, sy) 是她在屏幕上的位置,p 是 0~1 的进度。"""
        rect = monitor_rect_at(sx, sy)
        if not rect or not self._ensure(rect):
            return
        x0, y0, _, _ = self.rect
        self.buf.paste((0, 0, 0, 0), (0, 0, self.buf.width, self.buf.height))
        try:
            self.art.draw(self.buf, sx - x0, sy - y0, p)
        except Exception:
            return
        push_layered(self.hwnd, self.buf, x0, y0)

    def close(self):
        if self.win is not None:
            try:
                self.win.destroy()
            except Exception:
                pass
        self.win = None
        self.hwnd = 0
        self.buf = None          # 8MB 的画布,用完就还回去
        self.art = None
        self.rect = None


# ---------------- 推帧 GDI 资源池 ----------------
# GetDC + CreateCompatibleDC + CreateDIBSection 每帧全套重建是一笔每帧
# 固定税。按尺寸缓存一套常驻的 屏幕DC+内存DC+DIB:位图保持选入 mdc,
# 每帧只 memmove 新帧字节。池很小(≤4):主窗口一个尺寸、全屏魔法一个
# 尺寸,只有改缩放档才会出现新尺寸,超员按 FIFO 连位图带 DC 归还系统。
_gdi_pool = {}


def _gdi_surface(w, h):
    """取 (屏幕DC, 内存DC, DIB内存指针);创建失败时返回 (None, None, None)。

    仅限主线程使用(_push 和 FullscreenMagic 都在主循环里)。池里的位图
    一直保持选入 mdc,所以不再需要每帧 SelectObject/DeleteObject。
    """
    ent = _gdi_pool.get((w, h))
    if ent is not None:
        return ent[0], ent[1], ent[3]
    hdc = user32.GetDC(None)
    mdc = gdi32.CreateCompatibleDC(hdc)
    hbmp = None
    ptr = ctypes.c_void_p()
    if mdc:
        bmi = _BMI()
        bmi.bmiHeader.biSize = 40
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h      # 负高 = 自上而下的行序
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0
        bmi.bmiHeader.biSizeImage = w * h * 4
        hbmp = gdi32.CreateDIBSection(hdc, ctypes.byref(bmi), 0,
                                      ctypes.byref(ptr), None, 0)
        if hbmp:
            gdi32.SelectObject(mdc, hbmp)
    if not (mdc and hbmp and ptr):
        if hbmp:
            gdi32.DeleteObject(hbmp)
        if mdc:
            gdi32.DeleteDC(mdc)
        if hdc:
            user32.ReleaseDC(None, hdc)
        return None, None, None
    if len(_gdi_pool) >= 4:
        o_hdc, o_mdc, o_hbmp, _o_ptr = _gdi_pool.pop(next(iter(_gdi_pool)))
        gdi32.DeleteDC(o_mdc)            # 删 DC 会先解除位图选中,再删位图
        gdi32.DeleteObject(o_hbmp)
        user32.ReleaseDC(None, o_hdc)
    _gdi_pool[(w, h)] = (hdc, mdc, hbmp, ptr)
    return hdc, mdc, ptr


def push_layered(hwnd, img, x, y, alpha=255):
    """把一张 RGBA 图推到指定的分层窗口上。Pet._push 的通用版。
    alpha 是整窗的不透明度(淡入用),逐像素 alpha 照旧。"""
    w, h = img.size
    # 同 _push:必须按 BGRA 取字节,否则红蓝对调(全屏法阵曾经偏色就这条路)
    buf = premult_bgra(img)
    hdc, mdc, ptr = _gdi_surface(w, h)
    if not mdc:
        return
    ctypes.memmove(ptr, buf, len(buf))
    blend = _Blend(0, 0, max(0, min(255, int(alpha))), 1)
    user32.UpdateLayeredWindow(
        hwnd, hdc, ctypes.byref(wintypes.POINT(int(x), int(y))),
        ctypes.byref(wintypes.SIZE(w, h)), mdc,
        ctypes.byref(wintypes.POINT(0, 0)), 0,
        ctypes.byref(blend), ULW_ALPHA)


# ---------------- AI 会话灯(Mac TouchBar 同款) ----------------
# ai_sessions/*.json 一个会话一个文件:id/agent/state/title/updated。
# 写入方:zcode_notify.py(本机 ZCode hook)与 mac_session_sync.py(Mac 拉取)。
AI_SESSION_DIR = os.path.join(HERE, "ai_sessions")
# An allowlisted official Codex usage snapshot. UI refresh reads only this file.
CODEX_QUOTA_FILE = os.path.join(HERE, "ai_quota_codex.json")
AI_SESSION_STATES = ("running", "waiting", "done", "error", "idle")
# Mac 会话的状态变化才由她播报:本机 ZCode 的 stop/permission 已经有
# zcode_notify 的播报,灯再说话就是连播两句。详见 _scan_ai_sessions。
AI_SESSION_LINES = {
    "waiting": ["Mac 那边有确认框等你点头!", "Mac 上的 AI 在等你批准哦~",
                "快去瞅一眼,Mac 卡在确认框啦!"],
    "error": ["哎呀,Mac 的任务出错了…", "Mac 那边亮红灯了,去看看吧~"],
    "done": ["Mac 的任务干完啦!", "Mac 那边收工了~", "Mac 传来捷报!"],
}

# 自主情绪阈值:waiting 超过 90 秒她会好奇地看一眼;error 只担心一次
AI_CURIOUS_AFTER = 90.0

# ---- 水晶灯 / 魔法书:聚合状态与面板数据(纯函数,可测) ----
CRYSTAL_COLORS = {"running": (193, 154, 239), "waiting": (239, 193, 126),
                  "error": (239, 149, 154), "done": (168, 217, 174),
                  "idle": (150, 140, 180)}
CRYSTAL_LABEL = {"running": "运行中", "waiting": "等你确认",
                 "error": "出错", "done": "已完成", "idle": "空闲"}


def crystal_state(sessions, now=None):
    """水晶灯聚合状态:error > waiting > running > idle。灯已当熄掉的会话
    (卡太久、Mac 同步断了)不算 —— 不然确认框时关掉 ZCode,水晶永远橙着。"""
    now = time.time() if now is None else now
    has = {s.get("state") for s in sessions
           if s.get("state") and not ai_session_stale(s, now)}
    for st in ("error", "waiting", "running"):
        if st in has:
            return st
    return "idle"


def parse_quota(samples):
    """plan-usage-history 样本 → 最近一条有效 {fh, sd, t, reset_est};无则 None。

    reset_est:5h 窗口恢复时间估算 = 最近一次 fh 显著回落(窗口滚动)时刻
    + 5 小时(毫秒)。样本没有恢复字段,滚动点是从序列实测的,页面标注
    「估算」;回落不明显(样本太稀)时不给,宁可显示未接入。"""
    valid = [s for s in reversed(samples or [])
             if isinstance(s.get("u"), dict)
             and any(isinstance(s["u"].get(k), (int, float))
                     for k in ("fh", "sd"))]
    if not valid:
        return None
    latest = valid[0]
    reset_est = None
    prev_fh = None
    for s in reversed(valid):                        # 旧 -> 新
        fh = s["u"].get("fh")
        if not isinstance(fh, (int, float)):
            continue
        if prev_fh is not None and fh < prev_fh - 20:   # 显著回落 = 新窗口
            reset_est = (float(s.get("t") or 0) / 1000.0) + 5 * 3600
        prev_fh = fh
    return {"fh": latest["u"].get("fh"), "sd": latest["u"].get("sd"),
            "t": latest.get("t"), "reset_est": reset_est}


def crystal_rows(sessions, quota, now=None):
    """水晶详情面板行:会话状态 + 额度(诚实标注未接入)。灯已熄的会话记空闲。"""
    now = time.time() if now is None else now
    rows = []
    for s in sessions[:5]:
        st = s.get("state") if s.get("state") in AI_SESSION_STATES else "idle"
        if ai_session_stale(s, now):
            st = "idle"
        rows.append(("dot", CRYSTAL_COLORS.get(st, CRYSTAL_COLORS["idle"]),
                     f"{s.get('agent', '?')} · {CRYSTAL_LABEL.get(st, st)}",
                     str(s.get("title") or "")))
    rows.append(("sep",))
    if quota:
        rows.append(("text", None, f"Claude 5小时 已用 {quota.get('fh', '?')}%"))
        rows.append(("text", None, f"Claude 本周 已用 {quota.get('sd', '?')}%"))
        rows.append(("dim", None, "恢复时间 未接入"))
    else:
        rows.append(("dim", None, "额度数据 未接入"))
    return rows


def read_claude_quota():
    """读本机 Claude 桌面版用量采样 → {fh, sd, t}。读不到如实返回 None。"""
    import glob as _g
    root = os.environ.get("LOCALAPPDATA", "")
    hits = _g.glob(os.path.join(root, "Packages", "Claude_*", "LocalCache",
                                "Roaming", "Claude", "plan-usage-history.json"))
    if not hits:
        return None
    try:
        with open(hits[0], encoding="utf-8") as f:
            data = json.load(f)
        return parse_quota(data.get("samples"))
    except Exception:
        return None


def book_rows(sessions, cap=5, now=None):
    """魔法书面板行:标题 + 最近动作链(真实 hook 记录;没有就如实说)。
    灯已熄的会话圆点记空闲,和灯、水晶一个口径。"""
    now = time.time() if now is None else now
    rows = []
    for s in sessions[:cap]:
        title = s.get("title") or AI_AGENT_CHAR.get(s.get("agent"), "?")
        acts = [a for a in (s.get("actions") or []) if a][:3]
        st = "idle" if ai_session_stale(s, now) else s.get("state", "idle")
        rows.append((title, st, acts))
    return rows


def ai_wait_since(s, now):
    """这段 waiting 从什么时候开始等的。Mac 文件的 updated 每轮同步都改成
    现在(年龄永远到不了 90 秒),要用 since;本机 hook 只在变状态时写 updated。"""
    return float(s.get("since") or s.get("updated") or now)


def ai_reactions(sessions, reacted, now):
    """扫描会话 → 自主情绪。返回 (lid, mode, 新增已反应 id 集合)。

    reacted: 已反应过的集合(调用方持有,运行期内有效):error 记会话 id;
    waiting 记 ("waiting", id, 开始等的时间),一段等待只好奇一次。
    规则:error 会话 → 担心神情(每个 id 只触发一次);
          waiting 超过 90 秒 → 好奇微眯(同一段等待也只一次)。"""
    lid, mode, wait_key = None, None, None
    new_reacted = set()
    for s in sessions:
        st = s.get("state")
        sid = s.get("id")
        if st == "error" and sid not in reacted:
            new_reacted.add(sid)
            # 担心优先于好奇:列表里久等的 waiting 排在前面时,原来 lid 已被
            # curious 占住,这个 error 的 id 照记却永远不担心了
            if mode != "sad":
                lid, mode = 0.34, "sad"
        elif st == "waiting" and lid is None:
            key = ("waiting", sid, ai_wait_since(s, now))
            if key not in reacted and now - key[2] > AI_CURIOUS_AFTER:
                lid, mode, wait_key = 0.16, "curious", key
    # 好奇真播出去了才记:被同一轮的担心顶掉的,下一轮还能再看一眼。
    # 不记的话每 2 秒扫一次,她会一直眯着眼
    if mode == "curious":
        new_reacted.add(wait_key)
    if new_reacted:
        reacted |= new_reacted
    return lid, mode, reacted


# 灯板最多几盏;Mac 文件的 syncedAt 超过这么久没动就当同步断了:
# mac_session_sync 10 分钟拉不到才标 stale,再多给一轮空闲间隔(120 秒)的余量
AI_SESSION_CAP = 5
AI_MAC_SYNC_STALE = 720.0


def scan_ai_sessions(dir_path, cap=AI_SESSION_CAP, now=None):
    """读 ai_sessions/*.json,返回最新 cap 个(按 updated 降序;cap=None 全要)。

    单个文件坏/缺字段只跳过它自己,其余灯照常亮。Mac 来源的文件 syncedAt
    太久没动 —— 同步进程没在跑(重启电脑后没人拉起它),也就没人去标
    stale —— 这边自己补上:按空闲算、标 stale,和 mark_stale 一个效果。"""
    now = time.time() if now is None else now
    try:
        names = os.listdir(dir_path)
    except OSError:
        return []
    out = []
    for n in names:
        if not n.endswith(".json"):
            continue
        try:
            with open(os.path.join(dir_path, n), "r", encoding="utf-8") as f:
                s = json.load(f)
            if not isinstance(s, dict):
                continue
            raw_acts = s.get("actions")
            norm = []
            for a in (raw_acts if isinstance(raw_acts, list) else []):
                if isinstance(a, dict):
                    if a.get("turn"):
                        norm.append({"turn": 1, "t": float(a.get("t") or 0)})
                    elif a.get("a"):
                        norm.append({"t": float(a.get("t") or 0),
                                     "a": str(a.get("a")),
                                     "r": str(a.get("r")) if a.get("r") else "",
                                     "err": 1 if a.get("err") else 0})
                elif isinstance(a, str) and a:
                    norm.append({"a": str(a)})     # 旧格式兼容
            acts = norm
            state = s.get("state") if s.get("state") in AI_SESSION_STATES else "idle"
            stale = bool(s.get("stale")) or (
                s.get("source") == "mac"
                and now - float(s.get("syncedAt") or s.get("updated") or 0) > AI_MAC_SYNC_STALE)
            out.append({"id": str(s.get("id") or n[:-5]),
                        "agent": str(s.get("agent", "?")),
                        "state": "idle" if stale else state,
                        "title": str(s.get("title", ""))[:40],
                        "updated": float(s.get("updated", 0) or 0),
                        "since": float(s.get("since", 0) or 0),
                        "stale": stale,
                        "actions": acts[:48]})
        except Exception:
            continue
    out.sort(key=lambda s: -s["updated"])
    return out[:cap]


AI_AGENT_CHAR = {"zcode": "Z", "mac-claude": "M", "mac-codex": "C", "wslcodex": "W"}
AI_STATE_WORD = {"running": "工作中…", "waiting": "等你批准", "done": "刚完成",
                 "error": "出错了", "idle": "空闲"}


def ai_chain_lines(sessions, now=None):
    """头顶思维链的内容:(标题行, 动作行列表, 会话 id)—— id 供卷轴
    点击直达该会话的轨迹页。

    取最近一个还在跑/等人的会话;动作行来自 hook 记的 actions(最新在前,
    最多 3 条),没有动作数据(Mac 的 AIQuota 没有)就退回状态词。
    灯已当熄掉的(卡太久、Mac 同步断了)跳过,不然灯空心了链子还挂几天。"""
    now = time.time() if now is None else now
    for s in sessions:
        if s["state"] in ("running", "waiting") and not ai_session_stale(s, now):
            title = s["title"] or AI_AGENT_CHAR.get(s["agent"], s["agent"])
            cur = []
            for a in (s.get("actions") or []):      # 新的在前;停在轮次标记
                if isinstance(a, dict):
                    if a.get("turn"):
                        break
                    if a.get("a"):
                        cur.append(a["a"])
                elif isinstance(a, str) and a:      # 旧格式:纯文本动作
                    cur.append(a)
            if not cur:
                cur = [AI_STATE_WORD.get(s["state"], "…")]
            return title, cur[:3], s["id"]
    return None


def ai_session_stale(s, now):
    """灯已当熄掉的会话:Mac 同步断了(stale),或在跑/等你/出错卡太久(灯成了
    空心)。思维链、自主情绪、久等催促都按这一个口径,和灯对得上。"""
    if s.get("stale"):
        return True
    st = s.get("state")
    return (st in ("running", "waiting", "error")
            and ai_light_style(st, s.get("updated"), now)[1] == "hollow")


def ai_light_style(state, updated, now, done_fade=90.0, running_stale=2400.0,
                   waiting_stale=7200.0, error_stale=3600.0):
    """会话灯样式:(rgb, kind)。kind: pulse=呼吸 blink=闪烁
    blink_fast=急闪 solid=实心 hollow=空心。done 亮 done_fade 秒后转空心,
    免得满屏绿灯常驻;running 超 running_stale 秒(40 分钟)没有任何更新
    也按熄掉算 —— 进程硬崩溃时没人来写 done,别留一盏永远的紫灯。
    waiting 超 2 小时、error 超 1 小时没有更新同理:在确认框时关掉 ZCode
    不会有 Stop,橙灯会一直闪。Mac 的这几种状态同步每轮都写 updated=现在,
    只要 Mac 还说亮着就不会过期;等得久不久看 since,不看这里。"""
    age = now - float(updated or 0)
    if state == "waiting" and age <= waiting_stale:
        return (255, 170, 60), "blink"
    if state == "error" and age <= error_stale:
        return (255, 92, 92), "blink_fast"
    if state == "running" and age <= running_stale:
        return (185, 140, 255), "pulse"
    if state == "done" and age <= done_fade:
        return (120, 235, 170), "solid"
    return (168, 150, 210), "hollow"

# ---- 魔法书 v2(设计基准:小乔AI界面设计方案.md)----
# 书页配色:深紫墨底、暖白正文、细金边;装饰收在边角,不做厚发光/大金块
BOOK_BG = (33, 27, 46)
BOOK_BG2 = (46, 36, 66)
BOOK_INK = (245, 238, 224)
BOOK_DIM = (181, 169, 202)
BOOK_GOLD = (214, 185, 139)
BOOK_W, BOOK_H = 400, 520            # 100% UI 逻辑像素,不随场景缩放
TOOLTIP_DELAY = 0.35                 # 悬停水晶 350ms 后出小提示
QUOTA_STALE_AFTER = 3600.0           # 额度样本超过 1 小时 = 过期
DONE_GLOW = 90.0                     # 完成对勾在水晶上停留的秒数
CRYSTAL_COLORS["offline"] = (119, 105, 134)
CRYSTAL_COLORS["unknown"] = (119, 105, 134)
CRYSTAL_LABEL["offline"] = "离线"
CRYSTAL_LABEL["unknown"] = "未接入"
CRYSTAL_MARK = {"running": "", "waiting": "?", "error": "!",
                "done": "\u2713", "idle": "", "offline": "\u2013", "unknown": ""}


def quota_age(quota, now):
    """额度样本年龄(秒);没有样本返回 None。t 是毫秒时间戳。"""
    if not quota or not isinstance(quota.get("t"), (int, float)) or quota["t"] <= 0:
        return None
    return max(0.0, now - quota["t"] / 1000.0)


def book_sources(sessions, quota):
    """真实存在的来源芯片:有会话的 agent + 有额度数据的 Claude 桌面版。
    名称来自实际数据,绝不凭空列出未接入的服务。→ [(key, label, 字符)]"""
    order = [("zcode", "ZCode", "Z"), ("mac-claude", "Claude·Mac", "M"),
             ("mac-codex", "Codex·Mac", "C"), ("wslcodex", "Codex·WSL", "W")]
    have = {s.get("agent") for s in sessions}
    out = [(k, lab, ch) for k, lab, ch in order if k in have]
    known = {k for k, _, _ in out}
    for session in sessions:
        key = session.get("agent")
        if key and key not in known:
            label = {"codex":"Codex", "claude":"Claude"}.get(key, str(key))
            out.append((key, label, label[:1].upper()))
            known.add(key)
    if quota and "claude" not in known:
        out.append(("claude", "Claude", "✦"))
    return out


def pick_auto_source(sessions, sources, now=None):
    """Select a fresh task first; old running records never beat a live task."""
    now = time.time() if now is None else now
    keys = {key for key, _, _ in sources}
    live = [s for s in sessions if s.get("agent") in keys and not ai_session_stale(s, now)]
    for want in ("running", "waiting", "error", "done"):
        for row in live:
            if row.get("state") == want:
                return row["agent"]
    if live:
        return live[0]["agent"]
    recorded = [s for s in sessions if s.get("agent") in keys]
    return recorded[0]["agent"] if recorded else (sources[0][0] if sources else None)


def select_work_session(sessions, key, now=None):
    """A user-pinned session is resolved elsewhere; source defaults prefer live work."""
    now = time.time() if now is None else now
    pool = [s for s in sessions if s.get("agent") == key]
    for state in ("running", "waiting", "error"):
        active = next((s for s in pool if s.get("state") == state
                       and not ai_session_stale(s, now)), None)
        if active:
            return active
    return pool[0] if pool else None


def trace_rows(session, cap=10):
    """轨迹页行:真实动作链(文件里最新在前)→ 显示按先后(旧→新)。

    动作为 dict:{t 时间戳, a 动作, r 结果摘要, err 失败, turn 轮次标记};
    旧格式(纯字符串)兼容为无时间步骤。连续重复动作折叠 ×n。
    → [("turn", HH:MM) | ("step", HH:MM|"", 动作, 结果, 失败, 重复数)]"""
    steps = []
    for a in (session or {}).get("actions") or []:
        if not isinstance(a, dict) or not (a.get("a") or a.get("turn")):
            continue
        if a.get("turn"):
            steps.append(["turn", a.get("t") or 0, "", "", 0, 1])
            continue
        if steps and steps[-1][0] == "step" and steps[-1][2] == a.get("a")                 and not steps[-1][3]:
            steps[-1][5] += 1
        else:
            steps.append(["step", float(a.get("t") or 0), str(a.get("a")),
                          str(a.get("r") or ""), 1 if a.get("err") else 0, 1])
    steps = steps[:cap]                  # 只保留最新的 cap 条
    steps.reverse()                      # 旧 → 新,读起来像执行步骤
    return [tuple(s) for s in steps]


# ---------------- 魔女秋千 ----------------
SWING_PERIOD = 3.4                    # 一个来回的秒数
SEAT_LIFT_ART = 99                    # 座面接触点在脚底上方多少原画px(=裙摆下缘)
SWING_PERSP = 0.12                    # 前后荡的透视强度(靠近放大/远离缩小)
SWING_SCALE_MIN, SWING_SCALE_MAX = 0.72, 1.10   # 上限 1.10:再大帽尖与卷轴会裁出场景顶(实测 iter/scale-1_4.png)
SWING_ART_SCALE = (0.6, 1.8)          # 原画场景的滚轮缩放范围(画布随内容一起长,不会裁)
BUTT_X_REL, BUTT_Y_REL = 0.486, 0.865 # 座面接触点在渲染帧中的相对位置:
#                                      大裙摆立绘的"坐线"=裙摆下缘/小腿穿出处,
#                                      裙摆搭在座缘上、小腿垂下才像坐(0.74 是
#                                      隐形臀折线,视觉上座椅会横在腰上)
# ---- 结构重设计(顶部横杆 + 双吊绳,场景紧凑化)----
SWING_SCENE_H = 1.26                  # 场景高 = 人物高 × 1.26(人物约占 79%)
SWING_BAR_Y = 0.045                   # 横杆中心离场景顶:场景高比例
SWING_ROPE_LEN = 0.915                # 绳长(杆→座椅)= 人物高比例
SWING_BAR_HALF = 128                  # 横杆半长(基准 px,随场景缩放)
SWING_BAR_ATT = 82                    # 挂点离中线距离(≈座椅角上方,静止近竖直)
SWING_MAX_AMP = 0.40                  # 摆角上限:帽尖贴近横杆但不穿出场景顶
SWING_BAR_STYLE = "A"                 # 横杆造型:A=星轨杖杆 B=弯月双钩(预览用)
SWING_AMP = math.radians(13)          # 摆角


def swing_seat_pos(ax, anchor_y, rope_len, theta):
    """座椅沿钟摆弧线的位置(锚点在显示器顶边)。主窗口跟随和秋千层
    画绳共用这一个公式,两处永不漂移。"""
    return (ax + rope_len * math.sin(theta),
            anchor_y + rope_len * math.cos(theta))


class SwingLayer:
    """从显示器顶边垂下来的星链秋千(独立分层窗口,点击穿透)。

    绳子和月牙座椅画在这层,主窗口沿钟摆弧线被她"坐"着走 —— 和全屏
    魔法同一套路:Tk Toplevel 罩住摆动区,WS_EX_LAYERED|TRANSPARENT,
    每帧 push_layered。z 序插在主窗口正下方,绳子永远垫在她身后。
    """

    def __init__(self, root):
        self.root = root
        self.win = None
        self.hwnd = 0
        self.buf = None
        self.rect = None
        self._shown = False
        self.font13 = load_font(13)
        self.font12 = load_font(12)
        self.font11 = load_font(11)

    def _ensure(self, rect, below_hwnd, topmost=True):
        if self.win is not None and self.rect == rect:
            return True
        x0, y0, x1, y1 = rect
        w, h = x1 - x0, y1 - y0
        if self.win is not None and self.rect is not None and (
                self.rect[2] - self.rect[0], self.rect[3] - self.rect[1]) == (w, h):
            # 只挪了位置(拖动整个场景):窗口照用,push_layered 自带新坐标。
            # 原来每挪一下就 destroy/新建一次,新窗口 deiconify 时被提到
            # 她身前,绳子和月牙就盖在她脸上
            self.rect = rect
            return True
        self.close()
        try:
            win = tk.Toplevel(self.root)
            win.withdraw()
            win.overrideredirect(True)
            # 跟随主窗口的置顶设定:关了置顶,这层也不能继续浮在别的应用上
            win.attributes("-topmost", bool(topmost))
            win.geometry(f"{w}x{h}+{x0}+{y0}")
            # 注意:不要碰 -alpha —— 那会让 Tk 走 SetLayeredWindowAttributes
            # 模式,之后的 UpdateLayeredWindow 会一直静默失败(绳子永远不上
            # 屏)。防灰闪的办法是先推帧、后 deiconify(见 frame)。
            win.update_idletasks()
            hwnd = user32.GetAncestor(win.winfo_id(), 2) or win.winfo_id()
            ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) or 0
            user32.SetWindowLongPtrW(
                hwnd, GWL_EXSTYLE,
                int(ex) | WS_EX_LAYERED | WS_EX_TRANSPARENT)
            if below_hwnd:
                # 插到主窗口正下方(SWP_NOSIZE|NOMOVE|NOACTIVATE)
                user32.SetWindowPos(hwnd, below_hwnd, 0, 0, 0, 0, 0x0013)
        except Exception:
            self.close()
            return False
        self.win, self.hwnd, self.rect = win, hwnd, rect
        self.buf = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        self._shown = False
        return True

    def close(self):
        if self.win is not None:
            try:
                self.win.destroy()
            except Exception:
                pass
        self.win = None
        self.hwnd = 0
        self.buf = None
        self.rect = None

    @staticmethod
    def _rope(d, x0, y0, x1, y1, now=0.0, side=0, sag=0.0):
        """麻花扭纹吊绳:连续绳身 + 斜向绞纹(双色交替),近看有编绳质感。
        sag = 二次贝塞尔垂弧:静止微垂、快摆绷直。"""
        steps = max(30, int(math.hypot(x1 - x0, y1 - y0) / 7))
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2 + sag
        pts = []
        for i in range(steps + 1):
            t = i / steps
            u = 1 - t
            pts.append((u * u * x0 + 2 * u * t * cx + t * t * x1,
                        u * u * y0 + 2 * u * t * cy + t * t * y1))
        # 绳身底色
        d.line(pts, fill=(96, 68, 146, 245), width=4)
        # 绞纹:沿路径画斜向短刻线,明暗交替 → 麻花质感
        for i in range(2, steps - 1, 3):
            x, y = pts[i]
            xn, yn = pts[i + 1]
            dx, dy = xn - x, yn - y
            ln = math.hypot(dx, dy) or 1
            nx, ny = -dy / ln, dx / ln               # 法向
            d.line((x - nx * 2.2 - dx / ln * 2.6, y - ny * 2.2 - dy / ln * 2.6,
                    x + nx * 2.2 + dx / ln * 2.6, y + ny * 2.2 + dy / ln * 2.6),
                   fill=(56, 38, 92, 235), width=1)
            d.line((x - nx * 2.4, y - ny * 2.4, x + nx * 2.4, y + ny * 2.4),
                   fill=(172, 142, 222, 210), width=1)

    def _draw_bar(self, d, ax, by, ss, now):
        """顶部魔法横杆(目标参考图造型):紫杆金边,两端大金月牙端帽
        (内嵌紫晶),中央金饰框蓝晶,挂点金箍,杆端蓝晶垂饰。"""
        half = SWING_BAR_HALF * ss
        th = 15 * ss
        x0, x1 = ax - half, ax + half
        y0, y1 = by - th / 2, by + th / 2
        # 杆身:深紫 + 细金边 + 上下明暗
        d.rounded_rectangle((x0, y0, x1, y1), radius=th / 2,
                            fill=(58, 38, 96, 255),
                            outline=(242, 193, 78, 225), width=1)
        d.line((x0 + 10 * ss, y0 + 3.5 * ss, x1 - 10 * ss, y0 + 3.5 * ss),
               fill=(140, 112, 190, 210), width=1)
        d.line((x0 + 12 * ss, y1 - 2.2 * ss, x1 - 12 * ss, y1 - 2.2 * ss),
               fill=(30, 20, 52, 230), width=1)
        # 两端:大金月牙端帽(环抱杆端)+ 内嵌紫晶
        for side in (-1, 1):
            ex = (x0 - 3 * ss) if side < 0 else (x1 + 3 * ss)
            r = 13 * ss
            if side < 0:
                d.arc((ex - r, by - r, ex + r, by + r), 95, 265,
                      fill=(255, 214, 120, 255), width=max(3, int(5.2 * ss)))
            else:
                d.arc((ex - r, by - r, ex + r, by + r), -85, 85,
                      fill=(255, 214, 120, 255), width=max(3, int(5.2 * ss)))
            gx = ex - side * 3.5 * ss
            d.ellipse((gx - 2.6 * ss, by - 2.6 * ss, gx + 2.6 * ss, by + 2.6 * ss),
                      fill=(150, 120, 220, 255))
        # 中央:金饰框 + 蓝晶(目标图中央宝珠)
        d.polygon(star_pts(ax, by, 9.5 * ss, 9.5 * ss * 0.4, n=4,
                           rot=math.radians(45)),
                  fill=(255, 214, 120, 248))
        d.ellipse((ax - 3.4 * ss, by - 3.4 * ss, ax + 3.4 * ss, by + 3.4 * ss),
                  fill=(150, 205, 255, 255),
                  outline=(255, 255, 255, 210), width=1)
        # 挂点:金箍(环带)+ 金环(绳从这里穿)
        for side in (-1, 1):
            rx = ax + side * SWING_BAR_ATT * ss
            d.rounded_rectangle((rx - 3 * ss, y0 - 1.5 * ss,
                                 rx + 3 * ss, y1 + 1.5 * ss), radius=2 * ss,
                                fill=(255, 214, 120, 240))
            d.ellipse((rx - 4.5 * ss, y1 - 1 * ss,
                       rx + 4.5 * ss, y1 + 8 * ss),
                      outline=(242, 193, 78, 245), width=2)
        # 杆端垂饰:细金链 + 蓝晶坠
        for side in (-1, 1):
            ex = (x0 - 3 * ss) if side < 0 else (x1 + 3 * ss)
            d.line((ex, by + 13 * ss, ex, by + 24 * ss),
                   fill=(242, 193, 78, 210), width=1)
            gy_ = by + 28 * ss
            d.polygon(star_pts(ex, gy_, 4.8 * ss, 4.8 * ss * 0.5, n=4,
                               rot=math.radians(45)),
                      fill=(150, 200, 255, 248),
                      outline=(255, 214, 120, 245))

    def frame(self, rect, sw, below_hwnd=0, now=0.0, topmost=True):
        """画一帧场景。sw=None 时为"落地模式":只画水晶灯/魔法书/面板。

        荡秋千时:锚点固定在场景顶部中央;座椅沿垂线上下(θ 前后摆),
        随透视缩放;绳索从锚点连到座椅两角,角间距随透视张开 —— 靠近时
        绳脚外扩、远离时收拢,天然表达纵深。座椅不旋转(前后荡在正面
        视角里座椅不侧倾),人物由主窗口按同一透视绘制,永远端正坐在座上。"""
        if not self._ensure(rect, below_hwnd, topmost):
            return
        scene_w = rect[2] - rect[0]
        scene_h = rect[3] - rect[1]
        mounted = sw is not None
        ss = sw.get("scene_scale", 1.0) if mounted else 1.0
        theta = sw.get("theta", 0.0) if mounted else 0.0
        omega = sw.get("omega", 0.0) if mounted else 0.0
        persp = (1.0 + SWING_PERSP * math.sin(theta)) if mounted else 1.0
        S = sw.get("scene_scale", 1.0) * persp if mounted else 1.0
        scene_cx = rect[0] + scene_w // 2
        ax = scene_cx - rect[0]
        bar_y = sw.get("bar_y", 8) if mounted else 8
        R = sw.get("R", int(scene_h * 0.70) - 8)
        seat_sy = bar_y + R * math.cos(theta)
        sx = scene_cx - rect[0]
        hw = sw["hw"] * S

        buf = sw.get("scene_buf") if mounted else None
        if buf is None or buf.size != (scene_w, scene_h):
            buf = Image.new("RGBA", (scene_w, scene_h), (0, 0, 0, 0))
            if mounted:
                sw["scene_buf"] = buf
        buf.paste((0, 0, 0, 0), (0, 0, scene_w, scene_h))
        d = ImageDraw.Draw(buf, "RGBA")

        if mounted:
            # 软影:荡得越快影子越散越淡
            sh_w = (240 + abs(omega) * 300) * S
            sh_a = int(max(10, 30 - abs(omega) * 14))
            d.ellipse((sx - sh_w / 2, scene_h - 46, sx + sh_w / 2, scene_h - 14),
                      fill=(20, 14, 34, sh_a))
            # 双吊绳:横杆左右挂点 → 座椅两端挂钩(连续绳身,装饰只留星珠)
            sag = (7.0 - min(5.5, abs(omega) * 8.0)) * S
            for side in (-1, 1):
                att_x = ax + side * SWING_BAR_ATT * ss
                ex = sx + side * (hw - 16 * S)      # 座椅挂钩位置
                ey = seat_sy - 10 * S               # 软垫上角金环
                self._rope(d, att_x, bar_y + 6 * ss, ex, ey,
                           now=now, side=side, sag=sag)
        # 顶部魔法横杆(固定,不随摆动;整体随场景缩放)
        self._draw_bar(d, ax, bar_y, ss, now)
        # (透视系数,供绳/座椅缩放;横杆不随前后透视)
        # 月牙座椅(仅 mounted):透视缩放,臀点锚在座椅线
        if mounted:
            if mounted:
                hw0 = sw["hw"]                  # 座椅按基准尺寸绘制,只缩放一次
            else:
                hw0 = sw["hw"]
            seat = Image.new("RGBA", (int(hw0 * 2.9 + 56), 66), (0, 0, 0, 0))
            sd = ImageDraw.Draw(seat)
            cw, ch = seat.size
            ccx, ccy = cw // 2, ch // 2
            # 紫缎软垫坐椅(目标参考图):枕形坐垫 + 金沿 + 菱形铆钉
            sd.rounded_rectangle((10, 8, cw - 10, ch - 8), radius=16,
                                 fill=(104, 70, 156, 255),
                                 outline=(242, 193, 78, 235), width=2)
            sd.rounded_rectangle((16, 10, cw - 16, 24), radius=6,
                                 fill=(150, 118, 200, 255))     # 坐面高光
            sd.line((18, ch - 14, cw - 18, ch - 14),
                    fill=(242, 193, 78, 200), width=1)          # 前襟金线
            for fx in (0.3, 0.5, 0.7):                          # 菱形铆钉
                fx_ = int(cw * fx)
                sd.polygon(star_pts(fx_, ch - 20, 4.5, 4.5 * 0.45, n=4,
                                    rot=math.radians(45)),
                           fill=(255, 214, 120, 245))
            for side in (-1, 1):                                # 两端垂穗
                ex = 14 if side < 0 else cw - 14
                sd.line((ex, ch - 10, ex, ch - 3),
                        fill=(242, 193, 78, 220), width=2)
                sd.ellipse((ex - 3, ch - 5, ex + 3, ch + 1),
                           fill=(255, 214, 120, 240))
            if abs(S - 1.0) > 1e-3:
                seat = seat.resize((max(4, int(cw * S)), max(4, int(ch * S))),
                                   Image.LANCZOS)
            buf.alpha_composite(seat, (int(sx - seat.width / 2),
                                       int(seat_sy - seat.height / 2)))
            # 接触阴影:臀部压在座面上的柔和局部暗斑(重量感;不是整圈黑边)
            for rx, vh, a in ((0.50, 4.5, 30), (0.34, 3.0, 46)):
                d.ellipse((sx - hw0 * S * rx, seat_sy + (3 - vh) * S,
                           sx + hw0 * S * rx, seat_sy + (3 + vh) * S),
                          fill=(36, 20, 58, a))
            # 前缘层:座面线以下的月牙下沿,存到 sw 由主画布画在她之上,
            # 压住裙摆下缘 —— 她坐进座兜里,而不是贴在座椅前面
            # (seat 已按 S resize:裁剪坐标用缩放后空间)
            split_r = int(ch / 2 + 2 * S)
            fx0 = int(ccx - hw0 * 0.88 * S)
            fx1 = int(ccx + hw0 * 0.88 * S)
            front = seat.crop((fx0, split_r, fx1, seat.height))
            sw["seat_front"] = (
                front,
                (int(sx - front.width / 2),
                 int(seat_sy - seat.height / 2 + split_r)))
        push_layered(self.hwnd, buf, rect[0], rect[1])
        if not self._shown:
            self.win.deiconify()
            self._shown = True
            # deiconify 会把窗口提到同一 z 带的最顶上 —— _ensure 里插好的
            # "主窗口正下方"就白插了,绳子从她脸前穿过。推完再插回去一次
            if below_hwnd:
                user32.SetWindowPos(self.hwnd, below_hwnd, 0, 0, 0, 0, 0x0013)
def _faded(img, a):
    """Copy of ``img`` with its alpha scaled by ``a`` (0..1)."""
    a = max(0.0, min(1.0, a))
    out = img.copy()
    out.putalpha(out.getchannel("A").point(lambda v, a=a: int(v * a)))
    return out


class Pet:
    # The shipped edition has one scope. Legacy engine routines remain solely
    # for old data compatibility and explicitly isolated regression fixtures.
    CORE_EDITION = True

    def core_profile(self):
        return getattr(self, "_core_edition", self.CORE_EDITION)

    def house_enabled(self):
        return bool(not getattr(self, '_flat_panel_style', False)
                    and getattr(self, '_house_on', False) and self.core_profile()
                    and not getattr(self, '_house_suspended', False)
                    and getattr(self, '_scene_art', None) is not None
                    and self._house_room() is not None)

    def studio_enabled(self):
        """原画秋千、不在小屋、且有工作室素材时 = 工作室场景。"""
        sa = getattr(self, '_scene_art', None)
        return bool(getattr(self, '_studio_style', False) and sa is not None
                    and getattr(sa, 'studio', False) and not self.house_enabled())

    def _studio(self):
        stand = getattr(self, '_studio_stand', None)
        if stand is None:
            from studio_scene import StudioStand
            sa = self._scene_art
            stand = self._studio_stand = StudioStand(sa.pivot_l, sa.pivot_r)
        return stand

    def _house_room(self):
        """assets/house/room-v2.json(按 pet 的 ASSETS 找:打包版 assets 在 exe 旁边)。
        读不到就当没有小屋,退回单秋千,而不是每帧抛异常。"""
        room = getattr(self, '_house_room_meta', None)
        if room is None:
            try:
                if getattr(self, '_moon_house_style', False):
                    from moon_house import load_meta
                else:
                    from house_scene import load_meta
                room = load_meta(os.path.join(ASSETS, 'house'))
            except (OSError, ValueError):
                room = False
            self._house_room_meta = room
        return room or None

    def _limit_house_scale(self, requested, sw=None):
        """Fit the entire room into the work area (largest scale that fits)."""
        if not self.house_enabled():
            return requested
        sw = sw or getattr(self, '_swing', None)
        if sw:
            cx = sw['scene_l'] + sw['scene_w']/2
            cy = sw['scene_t'] + sw['scene_h']/2
        else:
            saved = self.settings.get('swing_scene') or {}
            cx = saved.get('cx', getattr(self, 'x', 0))
            cy = saved.get('cy', getattr(self, 'fy', 0))
        area = work_area_at(cx, cy) or (0, 0, self.sw, self.sh)
        available = (area[2]-area[0]-16, area[3]-area[1]-16)
        lo = .48
        if getattr(self, '_moon_house_style', False):
            room = self._house_room()
            u = ChatBox._layout(area[2]-area[0], area[3]-area[1])[0]
            _, _, bw, bh = room['board']
            gb = self._scene_art.girl_bbox
            base_k = self._spr_disp_h()/(gb[3]-gb[1])
            # Room zoom stops before the book becomes unreadable; glyphs do
            # not get raster-shrunk with the character. Fits smaller screens.
            from moon_board import min_board
            need_w, need_h = min_board(u)
            readable = max(need_w/bw, need_h/bh)*room['swing']['ks']/base_k
            requested = max(requested, readable)
        ss = min(SWING_ART_SCALE[1], max(lo, requested))
        while True:
            w, h = self._art_geo(ss)['size']
            if w <= available[0] and h <= available[1]:
                return ss
            if ss <= lo:
                self._house_suspended = True
                self._book_open = True
                return max(SWING_ART_SCALE[0], ss)
            ss = max(lo, round(ss-.02, 4))

    def _set_house_mode(self, enabled):
        self.close_action_card()
        self._house_on = bool(enabled)
        self._house_suspended = False
        self.settings['house_mode'] = self._house_on
        self._book_open = False
        self._crystal_open = False
        panel = getattr(self, '_ai_work_panel', None)
        if panel is not None and not panel.closed:
            panel.close(change_state=False)
        self._chain_rect_local = self._chain_rect = None
        self._house_plaque_cache = None
        self._house_pointer = (0.0, 0.0)
        self._set_house_hover(None)
        sw = getattr(self, '_swing', None)
        if sw and sw.get('art'):
            self._art_regeo(sw, self._limit_house_scale(sw.get('scene_scale', 1.0), sw))
            self._art_fit_scene(sw)
            self._save_swing_scene()
            sw['fade_at'] = time.time()          # 换场景也淡入
        else:
            self.mount_swing()
            self.save_settings()
        self.last_interact = time.time()
        if enabled and getattr(self, '_house_suspended', False):
            self._book_open = True
            self.say('屏幕空间较小，先用秋千与展开书页显示。', 3.0)

    def open_swing_scene(self):
        self._set_house_mode(False)

    def open_ai_panel(self):
        self.close_action_card()
        self.last_interact = time.time()
        if self.state != "swing":
            self.mount_swing()
        self._book_open = True
        self._book_tab = "trace"
        # Quota-only sources have no work history. Keep real/pinned history,
        # but return to automatic task selection when opening from quota.
        selection = getattr(self, "_book_sel", None)
        if selection and selection[0] == "agent":
            sessions = getattr(self, "_ai_work_sessions", self._ai_sessions)
            if not any(s.get("agent") == selection[1] for s in sessions):
                self._book_sel = None

    def __init__(self, root, selftest=False):
        self.root = root
        self._core_edition = True
        # 菜单/按钮回调里的异常:Tk 默认只把栈打到 stderr(pythonw 下是
        # pet_error.log),界面上什么都不发生 —— 用户只看到"点了没反应"。
        # 时停菜单就这样坏了很久没人发现(E33)。
        root.report_callback_exception = self._on_tk_error
        self.selftest = selftest
        self.t0 = time.time()
        self.snap_done = False

        self.settings = self._load_json(CONFIG_FILE, {})
        self.scale = float(self.settings.get("scale", 1.5))
        self.topmost = bool(self.settings.get("topmost", True))
        # 鼠标穿透默认关:之前只存在内存里,运行时打开后进程不退出,
        # 下次连右键都点不到,只能外部改窗口样式救回来,现在落盘跟随。
        self.click_through = bool(self.settings.get("click_through", False))

        self.cfg = self._load_json(os.path.join(ASSETS, "config.json"), {})
        # 立绘相关的几何(换立绘只改 config.json):嘴、人物躯干中心、帽檐星轨
        self._mouth_rel = tuple(self.cfg.get("mouth", (.487, .55)))
        self._sprite_center_rel = float(self.cfg.get("sprite_center_rel", 0.5))
        _ho = self.cfg.get("hat_orbit")
        if _ho and len(_ho) >= 7:
            global HAT_ORBIT, HAT_ORBIT_ART
            HAT_ORBIT = tuple(float(v) for v in _ho[:5])
            HAT_ORBIT_ART = (float(_ho[5]), float(_ho[6]))
        self.emotions = self._load_json(os.path.join(ASSETS, "emotions.json"), {})
        self.decors_meta = self._load_json(os.path.join(ASSETS, "decors.json"),
                                           {}).get("decors", [])
        self.main_src = Image.open(os.path.join(ASSETS, "main.png")).convert("RGBA")
        # 立绘显示高度(新立绘带腿和坐垫,头占比小,按 config 放大一点)
        self._sprite_h = int(self.cfg.get("sprite_h", SPRITE_H))
        # 秋千场景原画(横杆 / 绳+坐垫+她 / 书 / 水晶);素材不在就还是程序秋千
        self._scene_art = (scene_art.SceneArt.load(os.path.join(ASSETS, "scene"))
                           if PET_SCENE_ART else None)
        if self._scene_art is not None and (self.cfg.get("rig") or {}).get("regions"):
            # 秋千上的 2.5D(转头/帽子摆/发梢/呼吸)按立绘同一套部位多边形
            self._scene_art.set_rig(self.cfg["rig"]["regions"])
        self._ks_cache = scene_art.KeystoneCache(cap=40)
        self._art_back = None           # 原画模式:帽檐星轨远侧画在她身后的那层
        self._art_face_cache = OrderedDict()
        self._last_face_key = None
        hat_path = os.path.join(ASSETS, "hat_layer.png")
        self.hat_src = (Image.open(hat_path).convert("RGBA")
                        if os.path.exists(hat_path) else None)
        hair_path = os.path.join(ASSETS, "hair_layer.png")
        self.hair_src = (Image.open(hair_path).convert("RGBA")
                         if os.path.exists(hair_path) else None)
        self.hair_off = (0, 0)
        self.hair_off_s = (0, 0)
        for side, out in (("l", "legs_l"), ("r", "legs_r")):
            pth = os.path.join(ASSETS, f"{out}.png")
            src_img = (Image.open(pth).convert("RGBA")
                       if os.path.exists(pth) else None)
            setattr(self, f"legs{side}_src", src_img)
            setattr(self, f"legs{side}_off", (0, 0))
            mth = os.path.join(ASSETS, f"{out}.meta")
            if src_img is not None and os.path.exists(mth):
                try:
                    bb = json.load(open(mth))["bbox"]
                    setattr(self, f"legs{side}_off", (bb[0], bb[1]))
                except Exception:
                    setattr(self, f"legs{side}_off", (0, 0))
        hair_meta = os.path.join(ASSETS, "hair_layer.meta")
        if self.hair_src is not None and os.path.exists(hair_meta):
            try:
                bb = json.load(open(hair_meta))["bbox"]
                self.hair_off = (bb[0], bb[1])
            except Exception:
                self.hair_off = (0, 0)
        self.expr_cache = {}
        self._fast_ok = True        # 这台机器画得动 60fps 吗(tick 里实测)
        self._frame_ms = 0.0        # 单帧耗时滑动平均
        self.glow_cache = OrderedDict()
        self._expr_rs = OrderedDict()   # 表情贴纸的缩放结果缓存
        self._bubble_lay = {}           # 气泡排版缓存:(文本,字体,宽) -> (行,行高,宽)
        self._bubble_art = None
        self._bubble_born = 0.0
        self.warper = None
        self.decor_imgs = {}
        self._blink_patches = None
        self._warp_cache = OrderedDict()
        self._frame_buf = None
        self._light = None          # 加色光层(LightLayer),随画布尺寸重建
        self.fx = None            # 特效层,跟着 scale 一起建
        self._castfx = None       # 大招的精灵较大,单独建
        self._castfx_lock = threading.Lock()

        self.W = int(BASE_W * self.scale)
        self.H = int(BASE_H * self.scale)
        self.rebuild_scale_cache()

        self._font_cache = {}

        # sw/sh 仍是主屏尺寸(对话框居中、右键菜单避让按主屏算才对);
        # 她能走到哪、地面在哪则按虚拟桌面和当前显示器的工作区算。
        self.sw = root.winfo_screenwidth()
        self.sh = root.winfo_screenheight()
        self._vscreen = None
        self.x_min, self.x_max = 4, self.sw - self.W - 4
        self.ground_feet = self.sh - int(FEET_GAP * self.scale)
        self._refresh_screen()

        self.state = "idle"
        self.last = self.t0
        self.state_until = self.t0 + 3
        self.next_event = self.t0 + random.uniform(9, 22)
        self.next_ambient = self.t0 + 0.5
        self.next_trail = 0
        self.next_fountain = 0
        self.next_z = 0
        self.next_whine = self.t0 + 900   # 被冷落撒娇的下限时间(15 分钟一次)
        self.next_meteor = self.t0 + random.uniform(20, 60)   # 夜间流星计时
        self.snow_ground = 0.0     # 冬季脚下积雪强度 0~1(落雪增长,缓慢融化)
        self.face = 1
        self.hop_t = 0.0
        self.squash = 1.0
        self._spin_rot = 0.0    # 整只的平面旋转角(度,陀螺式转圈)
        self._spin_lift = 0.0   # 旋转时的腾空抬升(px)
        self._bend = 0.0        # 上半身侧向弓弯量
        self.look_x = 0.0
        self.look_y = 0.0
        self._depth_motion = DepthMotion()
        self.lean = 0.0
        self._micro_motion = None
        self._cursor_near = False
        self.parts = []
        self.circles = []
        self._shocks = []      # 待渲染的落地冲击波(land_fx 登记)
        self._afters = []      # 残影队列[(图, x, y, 时刻)]
        self._after_last = 0.0
        self._afterimage_on = False
        self.bubble = None
        self.sticker = None
        self._sticker_previous = None
        self.eat_start = 0
        self.magic_start = 0
        # 各个演出状态的起始时刻/方向。只在对应 start_* 跑过之后才会被读到,
        # 但 _exec_cmd 和存档恢复都能直接改 state —— 一旦绕过 start_*,
        # _tick_body 里那条分支就会 AttributeError 把整个 tick 打断。
        # (fvy 原来在 4360 行用 getattr 兜底,说明这个坑早就踩到过了。)
        self.twirl_start = 0.0
        self.sneeze_start = 0.0
        self._sneeze_initial = (1.0, 0.0)
        self._dizzy_initial = (0.0, 1.0, 0.0)
        self.fall_stand_start = 0.0
        self.peek_start = 0.0
        self.flip_start = 0.0
        self._flip_landed = False
        self.wave_start = 0.0
        self.roll_start = 0.0
        self.transform_start = 0.0
        self._ball_start = 0.0
        self._ball_active = False
        self._chase_home = self._chase_travel = 0.0
        self._chase_duration = 1.0
        self.flip_dir = 1
        self.roll_dir = 1
        self.roll_home = 0.0
        self._dance_home = 0.0
        self._dance_landed_beat = -1
        self._dance_bi = -1
        self.dance_face0 = 1
        self.dance_beat = 0.43      # start_dance 会重新随机
        self.fvy = 0.0              # 飞行竖直速度
        self.fy = float(self.settings.get("fy", self.ground_feet))
        self.vy = 0.0
        self._geo = ""
        self.click_token = 0
        self._pet_combo = []        # 连摸彩蛋:6 秒内的摸头时间戳
        self._pet_combo_cd = 0      # 彩蛋触发后的冷却
        self._sneeze_cd = 0         # 打喷嚏冷却(5 分钟)
        self._fall_cd = 0           # 脚滑摔跤冷却(5 分钟)
        self._poke_cd = 0           # 长按戳脸冷却(30 秒)
        self._return_greeted = False
        self._guess = None          # 猜数字游戏:{"n": 答案, "tries": 次数}
        self._sneeze_done = False
        self._mouth = None          # 表情嘴 (style, until),渲染到期自动熄灭
        self.lean_kick = 0.0        # 被逗弄时上半身的甩动量,随时间衰减
        self.tstop_start = 0.0      # 时停/回演的时间轴原点,进对应状态时覆写;
        self.rewind_start = 0.0     # 这里先给 0,免得 _tick_body 读到未初始化属性
        self._catch_total = 0       # 接星星小游戏:剩余可捕捉数
        self._catch_got = 0         # 已接住数
        self.catch_best = int(self.settings.get("catch_best", 0))  # 单局最高纪录
        self.battery_watch = bool(self.settings.get("battery_watch", True))
        self.hat_orbit = bool(self.settings.get("hat_orbit", True))
        self._batt_prev = None          # 上一次采样的 (接着电源, 电量%)
        self._batt_next = 0.0           # 下次采样时间(每分钟一次)
        self._batt_star_cd = 0.0        # 插电送星光的冷却,防反复插拔刷星光
        self._stats_dirty = False       # 今日计数有改动待落盘
        self._stats_next_save = 0.0
        self._walk_phase = 0.0          # 步相:按走过的距离推进,整数处落脚
        self._step_flash = 0.0          # 最近一次落脚的时刻:脚下法阵跟着亮一下
        self.meditate_start = 0.0
        self.pomo_done = int(self.settings.get("pomo_done", 0))    # 累计完成专注次数
        self.drag = None
        self.stroke_acc = 0.0
        self.stroke_cd = 0
        self.last_interact = self.t0
        self.blink_until = 0
        self.next_blink = self.t0 + random.uniform(2, 4)
        self._hover_last = None
        self._spark_cd = 0
        self._curious_cd = 0
        self._ai_cur_cd = 0
        self.next_greet = time.time() + 30
        self._curious_cd = 0
        self.singing = False
        self.next_note = 0
        self._sing_poll = 0
        self.next_sing_pulse = 0
        self._sing_started = 0
        self.mainq = queue.Queue()

        # ---- 扩展交互/动作 ----
        self.wheel_acc = 0.0        # 滚轮顺毛累积量
        self.wheel_cd = 0
        self.dizzy_amp = 0.0        # 眩晕摇摆幅度
        self._shake_dirs = []       # 拖拽方向翻转记录,用于摇晃检测
        self._shake_cd = 0
        self._inside = False        # 鼠标是否在她身上
        self._enter_cd = 0
        self._leave_cd = 0
        self.dance_start = 0.0
        # 时间轴的三个字段原来只在 _begin_tl 里才第一次出现,而 tstop /
        # rewind 这些分支是直接读它们的 —— 没先播过任何时间轴就进这些
        # 状态(存档恢复、pet_cmd.json 直接改 state)会 AttributeError 把
        # 整个 tick 打断。空轨道下 _play_timeline 是干净的空操作。
        self._tl_tracks = {}
        self._tl_events = []
        self._tl_done = set()
        self.stretch_start = 0.0
        self.chase_cd = 0
        self.chase_started = 0.0    # 进 chase 态时覆写;渲染分支直接读它
        self.peek_dir = 1
        self._period_greeted = None  # 已问候过的时段,避免重复
        self.vx = 0.0               # 抛掷用的水平速度(原来只有 vy)
        self._drag_trail = []       # [(t, x, fy)] 拖拽轨迹,松手时据此算初速
        self._drag_lean = 0.0
        self.bounces = 0
        self.affection = float(self.settings.get("affection", 0))
        self.rps = list(self.settings.get("rps", [0, 0, 0]))  # [赢, 平, 输]
        self._rps_busy = False

        # 饱食度(糖分)系统
        self.star = float(self.settings.get("star", 100.0))
        # 陪伴天数:第一次见到主人的日期(只记一次)
        self.first_day = self.settings.get("first_day") or time.strftime("%Y-%m-%d")
        # 时间魔法的风格(0=原版 1=全屏炫酷版)。这两行原来漏了:
        # magic_style 没初始化 -> save_settings 里建字典时抛 AttributeError,
        # 而那时文件已经用 "w" 打开截断了,于是 pet_settings.json 被清成 0 字节;
        # _magic_style_var 没初始化 -> on_menu 直接抛异常,右键菜单整个打不开。
        self.magic_style = int(self.settings.get("magic_style", 0) or 0)
        self._magic_style_cur = 0
        self.fsmagic = FullscreenMagic(root)
        self.swing_layer = SwingLayer(root)
        self._swing = None        # 荡秋千会话:ax/ay/L/t0/原位置,见 start_swing
        # 次级物理:帽尖/发梢/裙摆的延迟摆动与惯性(life.py)
        self.life = life.LifeMotion()
        self._life_prev_bob = 0.0
        self._life_prev_t = 0.0
        self._hat_warp_cache = OrderedDict()
        self._hair_warp_cache = OrderedDict()
        self._lid = 0.0            # 眼睑开合度:0 睁圆 .. 1 全闭(情绪神情)
        self._lid_until = 0.0
        self._lid_mode = ""
        self._crystal_open = False     # (v1 遗留,由魔法书 v2 取代)
        self._crystal_hover = False
        self._crystal_hover_since = 0.0   # 悬停水晶起点(350ms 后出提示)
        self._book_open = False        # 魔法书展开
        self._book_anim = 0.0          # 展开缓动 0→1(150-220ms)
        self._book_tab = "overview"    # overview | trace
        self._book_sel = None          # None=自动;("agent",k)/("sid",id)=用户固定
        self._book_new_seen = {}       # 会话 id → 打开时已见动作数(新记录提示)
        self._trace_snap = None        # 打开书时冻结的动作快照(阅读不跳走)
        self._trace_sid = None         # 快照对应的会话 id
        self._trace_expand = set()     # 展开的行(全历史内索引)
        self._trace_page = 0           # 历史翻页:0=最新,1=更早一页…
        self._copied_until = 0.0       # 「已复制」提示截止时间
        self.walk_target = 0.0         # 行走目标(闲置行走暂缓,保留字段)
        self.ai_mute_sess = set(self.settings.get("ai_mute_sess", []) or [])
        # 旧立绘情绪贴纸开关:新形象无匹配素材,默认关(保留眼睑反馈)
        self.stickers_enabled = bool(self.settings.get("stickers_enabled", False))
        self._scene_drag = None        # 场景整体拖动状态(on_press 里赋值)
        self.ui_reduced_anim = bool(self.settings.get("ui_reduced_anim", False))
        self._demo_until = 0.0         # 演示/截图:模拟会话注入截止时间
        self._demo_sessions = []
        self._demo_quota = None
        root.bind("<Escape>", self._on_escape)   # Esc 收起魔法书
        self._quota = None             # 额度缓存(claude 桌面采样)
        self._codex_quota = None       # 官方用量快照，保留真实采样时间
        self._codex_quota_error = False
        self._quota_provider = None   # 额度账户选择独立于工作会话
        self._quota_scan = 0
        self._lid_pending = None   # 排队待补播的自主情绪 (lid, mode, 过期时刻)
        # 分缕渲染端按 hair_s0/s1/s2 取值 —— 映射到 life 的三缕弹簧
        self.hair_s0, self.hair_s1, self.hair_s2 = (
            self.life.hair_strands[0], self.life.hair_strands[1],
            self.life.hair_strands[2])
        self._legs_warp_cache = OrderedDict()
        # 秋千是默认的家:开机 ~2 秒后自动入座(swing_home 可关)
        self.swing_home = bool(self.settings.get("swing_home", True))
        self._swing_pull = None
        self._swing_remount = 0.0
        self._swing_kick_cd = 0.0  # 自己荡一下的冷却(不再借 last_interact 伪造互动)
        self._land_then = None     # 秋千上点的地面动作:下秋千落地后补做(_land_first)
        if self.swing_home:
            root.after(2000, lambda: self.start_swing(quiet=True))
        self._magic_style_var = tk.BooleanVar(master=root,
                                              value=self.magic_style == 1)
        self._star_warned = False   # 星光跌破 25% 的提醒只说一次,充回复位
        self._star_full_cele = False # 星光满格庆祝只演一次,低于 90 复位

        # ---- 本事:提醒 / 喝水 / 剪贴板 / 找文件 ----
        # 一次性提醒落盘,重启不丢;喝水是循环提醒,间隔存设置
        self.reminders = []
        self._load_reminders()
        self.water_min = int(self.settings.get("water_min", 45))
        self.water_next = time.time() + max(self.water_min, 1) * 60

        # ---- 番茄钟 / 前台窗口感知 ----
        # 番茄钟状态落盘:重启(含看门狗自愈重启)不再静默丢计时 —— 到点
        # 分支按 due 时间戳触发,重启后过期的自然补一次提醒,未到的续跑。
        # 一次性提醒就是这个待遇,番茄钟同等重要。
        self.pomo = self.settings.get("pomo")
        if not (isinstance(self.pomo, dict)
                and self.pomo.get("phase") in ("focus", "break")
                and isinstance(self.pomo.get("due"), (int, float))
                and isinstance(self.pomo.get("mins"), (int, float))):
            self.pomo = None
        self._focus_next = 0.0    # 下一次"无声陪伴"的时刻
        self._focus_half = False  # 过半那一下的小动作用过了吗
        # 她隔一会儿瞄一眼前台窗口标题(只在本机判断,评论时才会随提示词
        # 发给 Gemini);不想被看可以在右键菜单关掉
        self.fg_watch = bool(self.settings.get("fg_watch", True))
        self.fg_bucket = ""
        self.fg_since = 0.0
        self.next_fg_check = self.t0 + 30
        self._fg_said_video = 0.0
        self._fg_said_code = 0.0

        # ---- 开口说话(TTS)/ 天气 ----
        # TTS 走 Windows 自带 SAPI(PowerShell 调),零依赖;一次只说一句
        self.tts_on = bool(self.settings.get("tts_on", True))
        # MCI 的 mpegvideo 支持运行时调音量(0~1000),唱歌用的是 600。
        # 没做菜单项,想调直接改 pet_settings.json 里的 tts_volume。
        self.tts_volume = max(0, min(1000, int(self.settings.get("tts_volume", 700))))
        self._tts_n = 0
        # 小音效(摸头/魔法/弹跳等)独立于 TTS 朗读,可在托盘或右键菜单关
        self.sound_on = bool(self.settings.get("sound_on", True))
        self.sfx = SFX(root)
        self.sfx.enabled = self.sound_on
        self._speak_lock = threading.Lock()
        self.city = str(self.settings.get("city", ""))
        self.city_lat = self.settings.get("lat")
        self.city_lon = self.settings.get("lon")

        # 调试/自动化接口:写 pet_cmd.json 即可驱动桌宠,状态输出到 pet_state.json
        self.cmd_path = os.path.join(HERE, "pet_cmd.json")
        self.state_path = os.path.join(HERE, "pet_state.json")
        # 以当前文件时间为起点,否则冷启动时 _cmd_seen=0,上次残留的指令会被
        # 当成新指令重新执行一遍(重启后聊天框自己弹出来就是这么来的)
        try:
            self._cmd_seen = os.path.getmtime(self.cmd_path)
        except OSError:
            self._cmd_seen = 0.0

        # 2026-10-05 selected moon house: violet theme and persistent book.
        # One-time migration; subsequent user scene choices remain respected.
        if self.settings.get('style_rev', 0) < 4:
            self.settings['style_rev'] = 4
            self.settings['house_mode'] = True
            self.settings['swing_scene'] = dict(self.settings.get('swing_scene') or {}, scale=1.32)
        self._flat_panel_style = not selftest and self.settings.get('workspace_layout', 'flat') == 'flat'
        # Follow the workspace's current default; the agent list remains expandable.
        from flat_workspace import DEFAULT_MODE
        self._flat_mode = DEFAULT_MODE
        self._studio_style = True
        self._moon_house_style = not selftest
        self._house_on = bool(self.settings.get('house_mode', True))
        self._house_suspended = False
        self._house_renderer = None
        self._house_plaque_cache = None
        self._house_pointer = self._house_view = (0.0, 0.0)
        self._house_pointer_at = self._house_view_at = 0.0

        # ---- AI 会话灯 ----
        # 状态文件来自 zcode_notify.py(本机 ZCode)与 mac_session_sync.py(Mac),
        # _pump 里限频扫描;开关持久化,和别的设置一样走 save_settings 白名单
        self.ai_lights = bool(self.settings.get("ai_lights", True))
        # 任务提醒(播报)独立于会话灯:静音时灯/水晶/面板照常,只是不说话
        self.ai_announce = bool(self.settings.get("ai_announce", True))
        # 按来源静音提醒:集合里的 agent 不再冒播报气泡(灯/角标/面板照常)
        self.ai_mute_sources = set(self.settings.get("ai_mute_sources", []) or [])
        self._ai_sessions = []
        self._ai_work_sessions = []    # 完整会话列表；灯板仍只显示前五盏
        self._ai_states = None      # None=还没扫过:第一轮只记下磁盘上的现状,不当新变化播报
        self._ai_key_last = {}
        self._ai_last_say = 0.0
        self._ai_err_seen = set()
        self._next_ai_scan = 0.0

        # ---- AI 大脑(原生 Gemini)----
        self.brain = None
        self.chatbox = None
        self.action_card = None
        # 可见聊天记录:聊天框关掉会销毁文本控件,所以对话必须存在 Pet 上,
        # 重开时回放。存盘后重启也能接着看。
        self.chat_path = os.path.join(HERE, "chat_history.json")
        # 拿存档给 AI 续上上下文,这样重启后她也还记得聊过什么。
        # 只认 dict 条目:手改坏的历史会让 replay_history 的 m.get 炸掉
        self.chat_log = [m for m in self._load_json(self.chat_path, [])[-200:]
                         if isinstance(m, dict)]
        self.history = [
            {"role": "user" if m.get("role") == "user" else "assistant",
             "content": m.get("text", ""),
             "emotion": m.get("emotion", "")}
            for m in self.chat_log if m.get("text")][-16:]
        self.ai_thinking = False
        self.next_thinkfx = 0
        self._think_demo_until = 0.0
        self.thinking_now = False
        try:
            import ai_chat
            self.brain = ai_chat.AIBrain(os.path.join(ASSETS, "ai_config.json"))
        except Exception as e:
            print("AI 模块不可用:", e)

        cfg_x = int(self.settings.get("x", self.sw * 0.68))
        self.x = max(self.x_min, min(cfg_x, self.x_max))
        self._clamp_pos()
        root.geometry(f"{self.W}x{self.H}+{int(self.x)}+{int(self.fy - self.FOOT_Y)}")
        root.title("小乔 · 时之魔女")
        root.overrideredirect(True)
        root.attributes("-topmost", self.topmost)
        # overrideredirect 会让 Tk 在 Windows 上销毁并重建顶层窗口,
        # 所以 HWND 必须在它之后才能取; 否则拿到的是已失效的句柄,
        # UpdateLayeredWindow 会一直以 ERROR_INVALID_WINDOW_HANDLE(1400) 失败,
        # 桌宠因此完全不渲染却不报任何异常。
        root.update_idletasks()
        root.update()
        self.hwnd = 0
        self._push_fail = 0
        self._acquire_hwnd()
        root.configure(bg="black")
        root.bind("<ButtonPress-1>", self.on_press)
        root.bind("<B1-Motion>", self.on_drag)
        root.bind("<ButtonRelease-1>", self.on_release)
        root.bind("<MouseWheel>", self.on_wheel_scene)
        root.bind("<Double-Button-1>", self.on_double)
        root.bind("<Motion>", self.on_hover)
        root.bind("<Button-3>", self.on_menu)
        root.bind("<MouseWheel>", self.on_wheel)      # 滚轮顺毛
        root.bind("<Button-2>", self.on_middle)       # 中键随机惊喜
        root.bind("<Enter>", self.on_enter)           # 鼠标靠上来
        root.bind("<Leave>", self.on_leave)           # 鼠标离开

        # 启动时如果上次的 click_through=True,把左键相关绑定切到穿透版
        self._apply_click_through_bindings()

        self.sfx.play("greet")
        # 陪伴里程碑:第 7/30/100/365 天当天的启动问候变成庆祝
        milestone = {7: "第一个星期啦", 30: "满一个月了呢",
                     100: "整整 100 天了", 365: "一周年了"}.get(self.companion_days())
        today = time.strftime("%Y-%m-%d")
        if not self.core_profile() and milestone and self.settings.get("milestone_day") != today:
            self.settings["milestone_day"] = today
            self.save_settings()
            self.say(f"今天是我们陪伴的第 {self.companion_days()} 天——{milestone}!", 4.0)
            self.play_emotion("excited", 3.2)
            self.confetti_burst(0, -0.1 * self.H, 26)
            self.sfx.play("levelup")
        else:
            self.say(random.choice(GREET), 2.4)
        self.root.after(2700, lambda: self.say(HELP, 4))
        self.start_tray()
        # 首次启动且没有密钥 -> 引导填写(发布版不预置密钥)
        if not self.core_profile() and not selftest and self.brain and not self.brain.cfg.get("api_key"):
            self.root.after(2200, lambda: self.setup_api_key(first_run=True))
        # AI 库预热:google.genai 的 import 要一秒多,推迟到首次聊天才加载
        # 的话,第一句话会卡一下 —— 开机 25 秒后趁没人在意,后台补加载
        if self.brain and not self.core_profile():
            self.root.after(25000, self._prewarm_ai)
        self.tick()
        if selftest:
            root.after(3200, root.destroy)

    # ==================== 工具 ====================
    def _load_json(self, path, default):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 类型必须与 default 一致:JSON 合法但结构不对(手改坏/旧版本)
            # 时直接用默认值,不然 .get() 会在启动/使用途中炸
            return data if isinstance(data, type(default)) else default
        except Exception:
            return default

    def _now_local(self):
        """按秒缓存的本地时间。帧循环里多处只需要秒级时间(季节氛围/流星/
        数字彩蛋),原来每帧各调一次 localtime/strftime —— 30fps 下每帧
        7 次全是浪费。取完本函数,同帧内可用 self._now_lt/_now_hm/_now_ymd。"""
        sec = int(time.time())
        if sec != getattr(self, "_now_sec", -1):
            lt = time.localtime()
            self._now_sec = sec
            self._now_lt = lt
            self._now_hm = time.strftime("%H:%M", lt)
            self._now_ymd = time.strftime("%Y-%m-%d", lt)
        return self._now_lt

    def _on_tk_error(self, exc_type, exc, tb):
        import traceback
        traceback.print_exception(exc_type, exc, tb)      # 日志照旧,和 Tk 默认行为一致
        now = time.time()
        if now > getattr(self, "_tk_err_cd", 0.0):
            self._tk_err_cd = now + 10.0                  # 连点也只说一次
            try:
                self.say("呜…这个没弄好,出错的经过记在 pet_error.log 里了", 3.2, keep=True)
            except Exception:
                pass                                      # 说话本身再出错就只留日志

    def _log_exc(self, tag):
        """异常去重打印:同一处(类型+文件+行号)只在第一次打全栈,之后
        只累计次数,换了地方才再打。帧循环里任何持续复现的异常都不至于
        把 1MB 的 pet_error.log 灌满、冲掉真正的事故痕迹。"""
        import traceback
        e = sys.exc_info()[1]
        tb = traceback.extract_tb(e.__traceback__)
        sig = ((type(e).__name__, tb[-1].filename, tb[-1].lineno)
               if tb else (type(e).__name__, "", 0))
        key = (tag,) + sig
        if key != getattr(self, "_exc_sig", None):
            prev = getattr(self, "_exc_n", 0)
            if prev > 1:
                print(f"[{tag}] 上一处异常累计重复 {prev} 次,略")
            self._exc_sig = key
            self._exc_n = 0
            traceback.print_exc()
        self._exc_n += 1

    def _font(self, size1x, sym=False):
        # 音符 ♪♫ 这类符号在微软雅黑里是缺字形的(渲染成豆腐块),
        # 得走 Segoe UI Symbol。所以缓存键要带上 sym。
        key = (int(size1x * SS), sym)
        f = self._font_cache.get(key)
        if f is None:
            f = load_font(key[0], sym=sym)
            self._font_cache[key] = f
        return f

    def get_glow(self, radius, rgb, alpha=120):
        """光晕精灵缓存。

        键必须量化:star / cstar / magic_corner / leaf 这几个粒子每帧传进来
        的半径和透明度都在连续变化(半径随年龄收缩、alpha 随年龄递减),
        不量化的话缓存键每帧都是新的 —— 缓存等于没有,每帧现算一次高斯
        模糊,还顺手把别人的条目挤掉。4px 半径 / 8 级 alpha 的台阶,在一团
        模糊光斑上肉眼分辨不出来。

        淘汰也从"满了就整个 clear()"改成真 LRU:原来一清空,下一帧所有
        光晕又要重新模糊一遍,正好在粒子最密的时候抖得最厉害。
        """
        radius = max(4, (int(radius) + 2) // 4 * 4)
        alpha = max(8, (int(alpha) + 4) // 8 * 8)
        key = (radius, rgb, alpha)
        c = self.glow_cache
        g = c.get(key)
        if g is not None:
            c.move_to_end(key)
            return g
        d = radius * 2
        im = Image.new("RGBA", (d, d), (0, 0, 0, 0))
        dr = ImageDraw.Draw(im)
        m = radius * 0.35
        dr.ellipse([m, m, d - m, d - m], fill=rgb + (alpha,))
        g = im.filter(ImageFilter.GaussianBlur(radius * 0.38))
        c[key] = g
        while len(c) > GLOW_CACHE_MAX:
            c.popitem(last=False)
        return g

    def paste_glow(self, frame, x2, y2, radius, rgb, alpha=120):
        g = self.get_glow(radius, rgb, alpha)
        frame.paste(g, (int(x2 - g.width / 2), int(y2 - g.height / 2)), g)

    def glow_lit(self, x2, y2, radius, rgb, alpha=120):
        """把一团光晕攒进加色光层(见 LightLayer)。只给粒子用 —— 粒子是在
        精灵之后画的,光层在粒子循环末尾统一 flush,不会盖到她身上。"""
        self._light.add(self.get_glow(radius, rgb, alpha), x2, y2)

    def rebuild_scale_cache(self):
        s = self.scale
        self.FOOT_Y = self.H - int(30 * s)
        h = int(getattr(self, "_sprite_h", SPRITE_H) * s * SS)
        img = self.main_src.resize(
            (int(self.main_src.width * h / self.main_src.height), h),
            Image.LANCZOS)
        self.spr2 = img
        # 部位几何随立绘走(config.json 的 rig);没配就是旧立绘那套
        self.warper = DepthWarp(img, rig=self.cfg.get("rig"))
        self._depth_motion = DepthMotion()
        # 各图层与底图同一缩放因子(不是同一目标高度 —— 图层是裁剪过的)。
        # k 必须无条件算:之前只在有帽层时才赋值,只放发层/腿层就 NameError。
        k = h / self.main_src.height
        if getattr(self, "hat_src", None) is not None:
            self.hat_spr2 = self.hat_src.resize(
                (max(1, int(self.hat_src.width * k)), max(1, int(self.hat_src.height * k))),
                Image.LANCZOS)
        else:
            self.hat_spr2 = None
        if getattr(self, "hair_src", None) is not None and k:
            hs = self.hair_src.resize(
                (max(1, int(self.hair_src.width * k)), max(1, int(self.hair_src.height * k))),
                Image.LANCZOS)
            self.hair_off_s = (int(self.hair_off[0] * k), int(self.hair_off[1] * k))
            # 三分带:左/中/右缕,羽化重叠 4%,各带自己的摆动相位
            self.hair_bands = []
            for lo, hi in ((0.0, 0.24), (0.19, 0.40), (0.36, 0.57),
                           (0.53, 0.73), (0.69, 0.88), (0.84, 1.0)):
                m = Image.new("L", hs.size, 0)
                ImageDraw.Draw(m).rectangle(
                    (int(hs.width * lo) - 4, -4, int(hs.width * hi) + 4, hs.height + 4),
                    fill=255)
                m = m.filter(ImageFilter.GaussianBlur(6))
                part = hs.copy()
                part.putalpha(ImageChops.multiply(hs.getchannel("A"), m))
                pb = part.getbbox()
                if pb:
                    self.hair_bands.append((part.crop(pb), (pb[0], pb[1])))
        else:
            self.hair_bands = None
            self.hair_off_s = (0, 0)
        for side in ("l", "r"):
            src_img = getattr(self, f"legs{side}_src", None)
            if src_img is not None and k:
                setattr(self, f"legs{side}_spr2", src_img.resize(
                    (max(1, int(src_img.width * k)), max(1, int(src_img.height * k))),
                    Image.LANCZOS))
                off = getattr(self, f"legs{side}_off")
                setattr(self, f"legs{side}_off_s", (int(off[0] * k), int(off[1] * k)))
            else:
                setattr(self, f"legs{side}_spr2", None)
                setattr(self, f"legs{side}_off_s", (0, 0))
        if hasattr(self, "_hat_warp_cache"):
            self._hat_warp_cache.clear()
        if hasattr(self, "_hair_warp_cache"):
            self._hair_warp_cache.clear()
        if hasattr(self, "_legs_warp_cache"):
            self._legs_warp_cache.clear()
        # 缩放后精灵尺寸变了,旧缓存里全是上一个尺寸的图 ——
        # 不清的话菜单里改完大小,画面会在新旧两个尺寸之间乱跳。
        self._warp_cache.clear()
        # 这两个缓存里存的都是按旧 scale 算出来的绝对像素尺寸,不清的话
        # 改完大小会继续拿旧尺寸的光晕和贴纸用
        self.glow_cache.clear()
        self._expr_rs.clear()
        self._frame_buf = None
        self._light = None          # 加色光层(LightLayer),随画布尺寸重建
        self.tfx = None             # 时停/回溯精灵也按 scale 建,下次用时按新尺寸重建
        # 这两行必须在锁里换:_warm_fx 的后台线程可能正握着这把锁、在
        # fx.CastFX(self.fx) 里用"换之前"的那个 FX 建精灵。裸着换的话
        # 它建完会把结果写回 self._castfx —— 于是 self.fx 已经是新尺寸,
        # 而大招精灵还是按旧 scale 建的那份,改完大小放大招就会不匹配。
        with self._castfx_lock:
            # defer:互动/动作才用的精灵不压在启动路径上,稍后后台补建
            self.fx = fx.FX(s, SS, defer=True, assets_dir=ASSETS)
            from hat_fx import tip_anchor
            self._hat_fx_tip_uv = tip_anchor(self.main_src)
            self._castfx = None
        self.root.after(700, self._warm_fx_deferred)
        if not getattr(self, "_text_warm_scheduled", False):
            self._text_warm_scheduled = True
            self.root.after(5000, self._warm_tk_text)
        # 换过缩放之后精灵尺寸全变了,重新在后台预热一份
        self.root.after(2500, self._warm_fx)
        self.decor_imgs = {}
        # 旧立绘配套的两只小动物(画风不搭新立绘):config 里 decors=false 就不挂
        for d in (self.decors_meta if self.cfg.get("decors", True) else ()):
            p = os.path.join(ASSETS, d["name"] + ".png")
            if os.path.exists(p):
                im = Image.open(p).convert("RGBA")
                factor = (getattr(self, "_sprite_h", SPRITE_H) * s) / self.main_src.height
                dh = max(24, int(im.height * factor))
                self.decor_imgs[d["name"]] = (
                    im.resize((max(24, int(im.width * dh / im.height)), dh), Image.LANCZOS),
                    d["rel"], d.get("layer", "back"))
        self._blink_patches = None
        sw_ = getattr(self, "_swing", None)
        if sw_ and sw_.get("art"):
            self._art_regeo(sw_, sw_.get("scene_scale", 1.0))
        # 同步字体
        self.f_bubble = load_font(int(16 * s * SS))
        self.f_moon = load_font(int(24 * s * SS), sym=True)
        self.f_chain = load_font(int(12 * s * SS))

    def save_settings(self):
        """先把字典建好,再写临时文件、原子替换。

        原来是 open(..., "w") 之后在 json.dump 的参数里现建字典 —— 只要有
        一个属性没初始化,文件已经被截断了才抛异常,再被 except 吞掉,
        结果就是 pet_settings.json 变成 0 字节,养成数据全没。
        现在:建字典在打开文件之前;写 .tmp 再 os.replace;真出错也会
        在日志里留一次痕迹,不再无声无息。
        """
        try:
            data = {"x": int(self.x), "fy": int(self.fy), "scale": self.scale,
                           "topmost": self.topmost, "click_through": self.click_through,
                           "star": round(self.star, 1),
                           "first_day": self.first_day,
                           "catch_best": self.catch_best,
                           "magic_style": self.magic_style,
                           "pomo_done": self.pomo_done,
                           "pomo": self.pomo,
                           "affection": round(self.affection, 1), "rps": self.rps,
                           "water_min": self.water_min,
                           "fg_watch": self.fg_watch,
                           "battery_watch": self.battery_watch,
                           "hat_orbit": getattr(self, "hat_orbit", True),
                           "ai_lights": getattr(self, "ai_lights", True),
                           "ai_announce": getattr(self, "ai_announce", True),
                           "ai_mute_sources": sorted(getattr(self,
                               "ai_mute_sources", set())),
                           "ai_mute_sess": sorted(getattr(self,
                               "ai_mute_sess", set())),
                           "stickers_enabled": getattr(self,
                               "stickers_enabled", False),
                           "swing_home": getattr(self, "swing_home", True),
                           "tts_on": self.tts_on,
                           "tts_volume": self.tts_volume,
                           "sound_on": self.sound_on,
                           "city": self.city,
                           "lat": self.city_lat, "lon": self.city_lon}
        except Exception:
            if not getattr(self, "_save_warned", False):
                self._save_warned = True
                import traceback
                traceback.print_exc()
            return
        if self.core_profile():
            # Retired preferences are archival data; normal position/star saves
            # must not reset an old timer, reminder or game score.
            for key in ("catch_best", "magic_style", "pomo_done", "pomo", "rps",
                        "water_min", "fg_watch", "battery_watch", "hat_orbit",
                        "stickers_enabled", "city", "lat", "lon"):
                if key in self.settings:
                    data[key] = self.settings[key]
                else:
                    data.pop(key, None)
        # 白名单之外、散在 self.settings 里的键(纪念日/生日/里程碑去重)
        # 也一并带回盘里。之前只写白名单,这几个功能等于内存版,重启即丢。
        for k, v in self.settings.items():
            if k not in data:
                data[k] = v
        tmp = CONFIG_FILE + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, CONFIG_FILE)
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            if not getattr(self, "_save_warned", False):
                self._save_warned = True
                import traceback
                traceback.print_exc()

    def load_expr(self, name):
        img = self.expr_cache.get(name)
        if img is None:
            p = os.path.join(ASSETS, "expr", name + ".png")
            if not os.path.exists(p):
                return None
            img = Image.open(p).convert("RGBA")
            self.expr_cache[name] = img
        return img

    def play_emotion(self, category, life=None):
        # 情绪 → 眼睑:先于贴纸资产检查(眼睑不依赖贴纸存在也能动)
        lid_map = {"angry": 0.42, "annoyed": 0.38, "curious": 0.16,
                   "sleepy": 0.55, "tired": 0.42, "shy": 0.30,
                   "sad": 0.34, "amazed": 0.05, "shocked": 0.02,
                   "surprised": 0.02, "happy": 0.22, "care": 0.30,
                   "mild": 0.22, "proud": 0.16}
        if category in lid_map:
            self._lid = lid_map[category]
            self._lid_mode = category
            self._lid_until = time.time() + (life or 2.6) + 0.9
        # 旧立绘情绪贴纸:新形象无匹配素材,整体关闭(眼睑与台词反馈保留;
        # 新形象贴纸素材到位后经 stickers_enabled 重开)
        if not getattr(self, "stickers_enabled", False):
            return False
        # 强度分级:默认按情感类型给合适时长(覆盖大部分调用)
        if life is None:
            SHORT = {"surprised", "tired", "shocked", "curious", "shy", "speechless"}
            LONG = {"excited", "proud", "thanks", "amazed", "rooger", "lazy", "comfort"}
            life = 1.5 if category in SHORT else 3.2 if category in LONG else 2.6
        names = self.emotions.get(category) or []
        names = [n for n in names
                 if os.path.exists(os.path.join(ASSETS, "expr", n + ".png"))]
        if not names:
            return False
        now = time.time()
        current = self.sticker
        if current and now < current['born']+current['life'] and current.get('category') == category:
            # 连续摸头保留当前贴纸与尺寸;即使正在淡出,也从当前亮度恢复。
            _, alpha = self._sticker_pose(current, now)
            current.update(life=now-current['born']+life, resume=(now, alpha))
            return True
        previous = None
        if current:
            sc, alpha = self._sticker_pose(current, now)
            if alpha > 0:
                previous = (dict(current), now, (sc, alpha))
        old = getattr(self, '_sticker_previous', None)
        if old:
            remaining = max(0.0, 1-(now-old[1])/.18)
            old_alpha = old[2][1]*remaining
            # 快速切换时延续仍然最明显的一层,最多保留两张贴纸。
            if old_alpha > (previous[2][1] if previous else 0):
                previous = (old[0], now, (old[2][0], old_alpha))
        self._sticker_previous = previous
        self.sticker = dict(name=random.choice(names), category=category, born=now, life=life)
        return True

    @staticmethod
    def _sticker_pose(sticker, now):
        age = max(0.0, now-sticker['born'])
        sc = Pet._track(age, [(0,.90),(.14,1.025),(.28,1.0)])
        alpha = max(0.0, min(1.0, age/.14, (sticker['life']-age)/.25))
        if 'resume' in sticker:
            born, initial = sticker['resume']
            u = max(0.0, min(1.0, (now-born)/.14))
            alpha = min(alpha, initial+(1-initial)*u*u*(3-2*u))
        return sc, alpha

    def add_part(self, kind, rx, ry, *, vx=0.0, vy=0.0, life=1.0, size=6,
                 color=GOLD, phase=0.0, spin=0.0, grav=0.0, txt=None, born=None):
        # born 可指定在未来:渲染对 age<0 的粒子直接跳过,清理只删 age>=life 的,
        # 于是天然成为"延迟出场"
        self.parts.append(dict(kind=kind, x=self.W / 2 + rx, y=self.H / 2 + ry,
                               vx=vx, vy=vy, born=time.time() if born is None else born,
                               life=life, size=size,
                               color=color, phase=phase, spin=spin, grav=grav, txt=txt))
        if kind == 'ball':
            self.parts[-1].update(sim_steps=0, trail=[], grounded=False, life=5.0)

    def star_burst(self, rx, ry, n, sp=(90, 170), grav=200, life=(1.0, 1.6), size=(5, 10)):
        for _ in range(n):
            a = random.uniform(0, 2 * math.pi)
            v = random.uniform(*sp)
            self.add_part("star", rx, ry, vx=math.cos(a) * v, vy=math.sin(a) * v - 40,
                          life=random.uniform(*life), size=random.uniform(*size),
                          color=random.choice(STAR_COLORS), phase=random.uniform(0, 6.28),
                          spin=random.uniform(-6, 6), grav=grav)

    def confetti_burst(self, rx, ry, n=14):
        """彩带屑:庆祝专用(好感升级/番茄钟完成)。小方块自旋+飘落。"""
        colors = [HEART_C, GOLD, MAGIC_A, MAGIC_B, (126, 217, 163), WHITE]
        for _ in range(n):
            a = random.uniform(-math.pi, 0)      # 向上扇形喷
            v = random.uniform(120, 260)
            self.add_part("confetti", rx, ry, vx=math.cos(a) * v, vy=math.sin(a) * v,
                          life=random.uniform(1.6, 2.3), size=random.uniform(4, 7),
                          color=random.choice(colors),
                          phase=random.uniform(0, 6.28), spin=random.uniform(-9, 9),
                          grav=190)

    def _click_rel(self, default_ry):
        """刚才那一下点在哪(相对窗口中心)。不是鼠标点出来的调用(聊天里
        说"摸摸头"、pet_cmd.json)没有新鲜的点击位置,落回默认的头顶。"""
        c = getattr(self, "_last_click", None)
        if c and time.time() - c[2] < 0.6:
            return c[0] - self.W / 2, c[1] - self.H / 2
        return 0.0, default_ry * self.H

    def gain_star(self, amount, rx=0.0, ry=None, *, hat_fx=False,
                  orbit_items=(), now=None, thinking=False, girl_box=None):
        """加星光并在画面上飘一行 "+N✦"。返回实际加上的量(满了就少加)。

        原来星光增减只改数字,只有托盘悬停和右键卡片能看到 —— 接星、喂糖
        这些"攒星光"的时刻,画面上没有任何对应。飘的是实际加上的量:星光
        快满时喂糖不会谎报 +40。不足 1 点不飘。"""
        if hat_fx:
            # A1/A2 (and the B1~B5 batch) enter through the star-feedback
            # gateway with ZERO reward.
            # rx/ry are actual supersampled pixel coordinates, never ratios.
            layer = getattr(self.fx, "hat", None)
            if layer is not None:
                moving=abs(getattr(self, "_orbit_speed", 1.0)) > .025
                fast=getattr(self, "_fast_ok", False)
                if getattr(layer, "b_series", False):
                    # B1 能量:E = clamp(max(|_orbit_speed|/2.4, |dθ_swing/dt|/2.2), 0, 1)
                    # (design_spec.md §B);sw["omega"] 是秋千摆角的每秒变化率。
                    om=(getattr(self, "_swing", None) or {}).get("omega", 0.0)
                    energy=max(0.0, min(1.0, max(abs(getattr(self, "_orbit_speed", 1.0))/2.4,
                                                 abs(om)/2.2)))
                    layer.update(now, orbit_items, rx, ry, fast=fast, moving=moving,
                                 energy=energy, girl_box=girl_box)
                else:
                    layer.update(now, orbit_items, rx, ry, fast=fast, moving=moving)
                layer.set_thinking(now, thinking, rx, ry)
                margin=24*layer.scale
                top=56*layer.scale
                if getattr(layer, "b_series", False):
                    # B 系列背层裁剪放宽:B2 烟升到帽尖上方约 68×scale,
                    # B3 萤火在轨道两侧再外扩约半个立绘宽的留白,
                    # B4/B5 星爆半宽约 20×scale(爆心已在帽尖上方)。
                    margin=56*layer.scale
                    top=72*layer.scale
                xs=[item[1] for item in orbit_items]+[rx]
                ys=[item[2] for item in orbit_items]+[ry]
                # Pixel crop in the 1x back layer; includes all smoke ascent.
                self._hat_fx_back_box=(max(0, math.floor((min(xs)-margin)/SS)),
                    max(0, math.floor(min(min(ys)-margin,ry-top)/SS)),
                    min(self.W, math.ceil((max(xs)+margin)/SS)),
                    min(self.H, math.ceil((max(ys)+margin)/SS)))
            return 0.0
        gained = max(0.0, min(float(amount), 100.0 - self.star))
        self.star = min(100.0, self.star + amount)
        if gained >= 1:
            self.add_part("gain", rx, -0.36 * self.H if ry is None else ry,
                          vy=-46 * self.scale, life=GAIN_LIFE, size=1.0,
                          txt="+%d*" % round(gained))
        return gained

    @staticmethod
    def _landing_strength(vy):
        """触地竖直速度(px/s) -> land_fx 强度 0.35..1。轻轻放下也有一圈,
        被狠狠甩到地上时冲击波最大。"""
        return max(0.35, min(1.0, vy / 1100.0))

    @staticmethod
    def _prox_target(dist):
        """光标距离(px/scale) -> 法阵感应强度 0..1,两端夹住、中间线性。"""
        return max(0.0, min(1.0, (PROX_FAR - dist) / (PROX_FAR - PROX_NEAR)))

    def puff(self, rx, ry, vx=0.0, vy=0.0, grav=0.0):
        """一团"噗"的喷气/尘雾(预渲染贴图)。给点速度就顺着喷的方向飘。"""
        self.add_part("puff", rx, ry, vx=vx, vy=vy, grav=grav, life=PUFF_LIFE)

    def hit_ring(self, rx, ry, palette="gold", double=False):
        """命中光环:点中的那一下在落点"啪"地亮一圈。粒子是飘走的,只有它
        钉在原地,手感上才有"打中了"。double=连击时紧跟着再荡一圈。"""
        self.add_part("hit_ring", rx, ry, life=HIT_RING_LIFE, txt=palette)
        if double:
            self.add_part("hit_ring", rx, ry, life=HIT_RING_LIFE, txt=palette,
                          born=time.time() + 0.09)

    def hearts(self, rx, ry, n=4):
        for _ in range(n):
            self.add_part("heart", rx + random.uniform(-26, 26), ry + random.uniform(-8, 8),
                          vy=-random.uniform(36, 60), life=random.uniform(1.1, 1.5),
                          size=random.uniform(9, 14), phase=random.uniform(0, 6.28))

    # ==================== 状态动作 ====================
    def say(self, text, dur=None, keep=False):
        # 气泡是单段排版:换行/连续空白压平,免得 PIL 渲染出豆腐块
        text = " ".join(str(text).split())
        if not text:
            return
        if dur is None:
            # 原来所有调用点共用写死的 2.5 秒,只有 AI 回复那条路径按长度
            # 自适应 —— 于是长台词也是 2.5 秒就蒸发。没显式指定时按阅读
            # 速度给足时间;显式传了 dur 的(猜拳倒计时 0.8 等)行为不变。
            dur = max(2.5, min(14.0, 1.2 + len(text) * 0.14))
        if not keep and self.focus_mode():
            # 专注陪伴中她把话说短:主人主动摸她当然要回应,但不占着屏幕
            # 不走。keep=True 的是提醒和 AI 回答 —— 那是主人自己要的内容,
            # 长度得按阅读速度来,不受此限。
            dur = min(dur, 2.2)
        self._bubble_born = time.time()
        self.bubble = (text, self._bubble_born + dur)

    def hop(self, strength=0.7):
        # 时长凑成整数个小跳,最后一跳正好落回地面;hop_t 仍是"剩余秒数",
        # 其他地方拿 hop_t > 0 判断"正在蹦"的语义不变。
        n = max(2, round(strength / HOP_PERIOD))
        self.hop_t = self._hop_total = HOP_CROUCH + n * HOP_PERIOD
        self._hop_amp = strength
        self.squash = 0.9            # 蹲一下蓄力,起跳前保持住

    @staticmethod
    def _hop_curve(age, total, amp):
        """蹦跳第 age 秒的离地高度(px/scale)。

        每个小跳是一条抛物线 —— 触地瞬间干净地折返;旧的 abs(sin) 按 30fps
        采样时谷底几乎踩不到 0,看着一直悬在半空抖。一跳比一跳低,峰值沿用
        原来的 5 + 10*力度,手感高度不变。

        不做空中拉伸:变形缓存按 round(squash*12) 分档,±0.045 的拉伸跨不过
        档位边界,画出来和没拉一样(实测见 EXPERIMENTS E22)。
        """
        if age < HOP_CROUCH or age >= total:
            return 0.0
        a = (age - HOP_CROUCH) / HOP_PERIOD
        i = int(a)
        u = a - i
        n = max(1, round((total - HOP_CROUCH) / HOP_PERIOD))
        return (5 + 10 * amp) * max(0.0, 1.0 - i / n) * 4 * u * (1 - u)

    @staticmethod
    def _hop_touchdown(prev_age, age, total):
        """这一帧里有没有触地(帧率无关:按跨过的触地时刻判断)。"""
        if prev_age >= total or age <= HOP_CROUCH:
            return False
        if age >= total:
            return True
        # prev 夹到蹲完那一刻:跨过起跳点的那一帧,(prev-蹲)是负数,地板除
        # 得 -1,会把"起跳"误数成一次触地
        prev_age = max(prev_age, HOP_CROUCH)
        return int((prev_age - HOP_CROUCH) // HOP_PERIOD) < int((age - HOP_CROUCH) // HOP_PERIOD)
    def wake_if_sleep(self, line=None):
        if self._wake_from_nap():
            self.sfx.play("wake")
            self.parts = [q for q in self.parts if q.get("kind") != "zzz"]
            self._start_micro_motion("wake")
            if line:
                self.say(line, 2.5)
            return
        if self.state in ("sleep", "yawn"):
            self.state = "idle"
            self.state_until = time.time() + 3
            self.sfx.play("wake")
            self.parts = [p for p in self.parts if p["kind"] != "zzz"]
            self._start_micro_motion("wake")
            if line:
                self.say(line, 2.5)

    def pet_head(self):
        self._count_today("pet")
        if getattr(self, "_flat_panel_style", False):
            from agent_companion import pull
            if pull(self, time.time(), "head"):
                self.last_interact = time.time()
                return
        if random.random() < 0.05 and time.time() > getattr(self, "_gift_cd", 0):
            # 5% 摸头送星光糖(5 分钟冷却):星光+5 + 谢谢表情
            self._gift_cd = time.time() + 300
            self.sfx.play("voice_happy")
            self.say(random.choice([
                "送你一颗星光糖~", "今天也想给你甜甜~", "喏,这颗是你的~",
                "嘿嘿,藏着当零食吧~", "别客气呀~"]), 2.6)
            self.play_emotion("thanks", 3.2)
            self.gain_star(5)
            self.add_part("sparkle", 0, -0.2 * self.H, life=0.7,
                          size=random.uniform(5, 9), color=GOLD_L,
                          phase=random.uniform(0, 6.28),
                          vx=random.uniform(-40, 40), vy=-random.uniform(20, 50))
            return
        if random.random() < 0.05:
            self._look_away_cd = time.time() + 0.6   # 摸头 5% 概率看别处
        now = time.time()
        gap = now - self.last_interact
        self.last_interact = now
        if self.state in ("sleep", "yawn"):
            # 久别重逢/普通小睡醒/30s+ 离开后的粘人小醒 — 三档
            if gap > 600:
                line = random.choice(REUNION_LINES)
            elif 30 < gap < 600:
                line = random.choice(["嗯…你回来啦~", "嗯嗯,被叫醒了呀~",
                                       "呀…还想再睡会儿嘛~"])
            else:
                line = random.choice(WAKE_LINES)
            self.wake_if_sleep(line)
            return
        # 连摸彩蛋:6 秒内摸满 6 次,她会害羞地"融化"一次(冷却 60 秒)
        self._pet_combo = [t for t in getattr(self, "_pet_combo", [])
                           if now - t < 6]
        self._pet_combo.append(now)
        if len(self._pet_combo) >= 6 and now > self._pet_combo_cd:
            self._pet_combo = []
            self._pet_combo_cd = now + 60
            self.sfx.play("voice_giggle")
            self.play_emotion("shy", 3.0)
            self.hit_ring(*self._click_rel(-0.27), palette="pink", double=True)
            self.hearts(*self._click_rel(-0.14), 8)
            self.say(random.choice(MELT_LINES), 3.0)
            self.add_affection(3)
            return
        if random.random() < 0.02:
            # R112 2% 抓住你的手:主动抓手(与怕痒区分:怕痒是触觉逃避,这是撒娇迎击)
            self.lean_kick = 1.0
            self.hearts(0, -0.22 * self.H, 4)
            self.sfx.play("voice_giggle")
            self.say(random.choice(
                ["别摸啦~我会抓住你的哦!", "嘻嘻,你的手被我捕到啦~",
                 "不许摸了!要摸了就拉勾~", "抓到了!这下跑不掉了~"]), 2.4)
            self.play_emotion("shy", 2.6)
            self.add_affection(0.8)
            return
        if random.random() < 0.04:
            # 4% 反手摸回:她突然反过来"摸"主人(戳脸彩蛋镜像)
            self.lean_kick = 0.7
            self.hearts(0, 0.18 * self.H, 4)             # 心冒出在主人(画面)身上
            self.sfx.play("voice_giggle")
            self.say(random.choice(
                ["主人也要被摸摸!", "回礼!摸回去!", "嘻嘻,被我抓住啦~"]), 2.4)
            self.play_emotion("shy", 2.4)
            self.add_affection(0.8)             # 少一点,毕竟她占主导
            return
        if random.random() < 0.08:
            # 8% 怕痒变体:碰到痒处突然躲开(演出不同,好感照加)
            self.sfx.play("voice_giggle")
            self.lean_kick = 1.2
            self.squash = 0.9
            self.play_emotion("shy", 2.2)
            self.say(random.choice(["呀,那里好痒!", "别摸那里啦,好痒的!", "嘻嘻,好痒~"]), 2.2)
            self.add_affection(1.5)
            return
        self.sfx.play("voice_happy")
        self.hit_ring(*self._click_rel(-0.27), palette="pink")
        if not self._start_micro_motion("nuzzle"):
            self.hop()
        # R102/R103:离开 30s+ 回来时多 1~2 颗爱心 + 口吻更黏
        # gap 已在 pet_head 开头计算(self.last_interact 在本句之前)
        long_away = gap > 30
        # 爱心从摸到的地方冒出来。按原意的 -0.28H 起点在帽尖上方,往上飘时
        # 离她很远、像飘在天上;没有点击位置(聊天/指令)时落在发顶(-0.14H)
        self.hearts(*self._click_rel(-0.14), random.randint(5, 7) if long_away
                    else random.randint(2, 4))
        self.star_burst(0.22 * self.W, -0.2 * self.H, 3, sp=(50, 110), grav=60)
        self.play_emotion("happy", 2.4)
        # 台词随好感变化:点头之交时还有点客气,很依赖之后才会说贴心话
        if self.affection < 30:
            lines = ["啊…谢谢…", "嘿嘿~", "主人的手好暖和…"]
        elif long_away:
            lines = ["终于回来了!还这么惦记我~", "想你了!这手一摸好暖~",
                     "走开一会儿心里就空空的~"]
        else:
            lines = ["嘿嘿~", "好开心!", "最喜欢你了!", "再摸摸嘛~",
                     "主人的手最温暖了~", "我们心有灵犀吧?"]
        self.say(random.choice(lines), 2.2)
        self.add_affection(1.5 if long_away else 1.0)

    def tickle_body(self):
        self._count_today("tickle")
        self.last_interact = time.time()
        if self.state in ("sleep", "yawn"):
            self.wake_if_sleep()
            return
        self.sfx.play("voice_giggle")
        self.hit_ring(*self._click_rel(-0.08))
        if not self._start_micro_motion("giggle"):
            self.lean_kick = 0.9
        # 笑到抖星星:身上簌簌掉几粒时之沙
        for _ in range(4):
            self.add_part("sparkle",
                          random.uniform(-0.18, 0.18) * self.W,
                          random.uniform(-0.22, 0.02) * self.H,
                          vx=random.uniform(-40, 40),
                          vy=random.uniform(-70, -30),
                          grav=180, life=random.uniform(0.45, 0.75),
                          size=random.uniform(2.5, 4.5),
                          color=random.choice([GOLD_L, GOLD]),
                          phase=random.uniform(0, 6.28))
        self.play_emotion(random.choice(["speechless", "tired", "lazy"]), 2.2)
        self.say(random.choice(TICKLE_SAY), 2.0)
        self.add_affection(0.8)

    def _idle_event(self, now):
        """原有的随机 idle 行为(走路/贴纸/说话/星星/蹦跳/睡觉)。"""
        if self.core_profile():
            return False
        r = random.random()
        if r < 0.42 and False:   # 新立绘坐姿:行走暂缓(素材边界,问题池在案)
            self.state = "walk"
            self.walk_home = self.x
            self.walk_target = self.x + random.choice((-1, 1)) * random.uniform(
                90, 240) * self.scale
            self.walk_target = max(self.x_min, min(self.walk_target, self.x_max))
            self.face = 1 if self.walk_target > self.x else -1
            self.state_until = now + 30
        elif r < 0.62:
            self.play_emotion("mild", 2.2)
            self.state = "sticker"
            self.state_until = now + 2.4
        elif r < 0.72:
            # 星光不足时优先说饥饿台词(这是玩家唯一的"该喂糖了"信号)
            if self.star < 30 and random.random() < 0.6:
                self.say(random.choice(HUNGRY_SAY), 2.5)
                self.play_emotion("tired", 2.2)
            elif (time.localtime().tm_hour >= 23 or time.localtime().tm_hour < 5)                     and random.random() < 0.5:
                # 深夜口吻:轻、软、关心睡觉
                self.say(random.choice(NIGHT_SAY), 3.0)
                self.play_emotion("lazy", 2.5)
            elif random.random() < 0.3:
                # 季节口吻:秋天聊落叶,冬天聊雪,让角色感知四季
                mon = time.localtime().tm_mon
                self.say(random.choice(
                    self.SEASON_SAY[self._season(mon)]), 2.6)
            elif self._ai_ready() and now > self._ai_cur_cd:
                self._ai_cur_cd = now + 180
                self._ai_quick("随便和主人说点什么,一句就好")
            else:
                self.say(random.choice(IDLE_SAY), 2.5)
        elif r < 0.82:
            if random.random() < 0.5:
                # 哼歌:♪♫ 音符从她身边悠悠飘出(无声,纯氛围)
                for i in range(3):
                    self.add_part("note", random.uniform(-0.12, 0.12) * self.W,
                                  -0.30 * self.H - i * 6,
                                  vy=-random.uniform(24, 40),
                                  life=random.uniform(1.6, 2.4),
                                  phase=random.uniform(0, 6.28),
                                  txt=random.choice(("♪", "♫", "♪")))
            else:
                self.circles.append(dict(born=now, life=0.8, rx=0.5, kind="flash"))
                self.star_burst(random.choice((-0.25, 0.25)) * self.W, 0.12 * self.H, 5,
                                sp=(40, 90), grav=120, size=(4, 7))
        elif r < 0.92:
            self.hop(0.5)
            self.play_emotion("excited", 1.6)
        elif r < 0.94:
            # 稀有事件:打喷嚏(2% + 5 分钟冷却),完整小演出
            if now > self._sneeze_cd:
                self._sneeze_cd = now + 300
                self.start_sneeze()
        elif r < 0.96:
            # 稀有事件:吹泡泡(2%),泡泡摇曳上飘,末端"啵"地消散
            for i in range(random.randint(3, 4)):
                self.add_part("bub", (0.06 + 0.04 * i) * self.W * self.face,
                              -0.28 * self.H - i * 8,
                              vx=random.uniform(-14, 26) * self.face,
                              vy=random.uniform(-55, -35),
                              life=random.uniform(3.2, 4.6),
                              size=random.uniform(5, 9),
                              phase=random.uniform(0, 6.28))
        elif r < 0.97:
            # 稀有事件:脚滑摔跤(1% + 5 分钟冷却)
            if now > self._fall_cd:
                self._fall_cd = now + 300
                self.start_fall()
        else:
            self.go_sleep()

    def _seat_guard(self, on_swing_only=False, silent=False):
        """新立绘为坐姿(含坐垫):横移/翻转/跳跃/站立类动作整体不可用。
        on_swing_only=True 时仅在秋千上拦截(如需要离地/空手的动作);
        silent=True 时静默拦截(自动触发不冒「做不了」气泡)。
        返回 True = 已拦截。"""
        if on_swing_only and not (self.state == "swing" and self._swing):
            return False
        if not silent:
            self.say(random.choice([
                "坐在坐垫上做不了这个啦,先让我站起来…啊,站不起来。",
                "现在整个人是坐着的,这个动作做不了哦~",
                "嗯…这个动作要能站起来才行,坐下之后就做不了了~",
            ]), 2.4)
        return True

    def start_twirl(self):
        """转圈圈:真·陀螺式旋转(时间轴驱动)—— 蹲身蓄力(星尘汇聚) ->
        if self._seat_guard():
            return
        原地跳起,整只绕画面平面真转两整圈(720°,先慢后快再收),星星
        螺旋尾迹 -> 落地急停收势(星星炸开+冲击波),余韵摇摆,35% 转晕。"""
        if self.core_profile():
            return False
        if self._seat_guard():
            return
        if self._land_first(self.start_twirl):
            return
        self.state = "twirl"
        self.twirl_start = time.time()
        self.state_until = self.twirl_start + 3.6
        d = self.twirl_dir = random.choice((-1, 1))
        self._twirl_face0 = self.face
        self._begin_tl(
            tracks={
                "_spin_rot":  [(0, 0.0), (0.55, 0.0), (2.45, 720.0 * d),
                               (3.6, 720.0 * d)],
                "_spin_lift": [(0, 0.0), (0.55, 0.0), (1.5, 34.0), (2.45, 0.0)],
                "squash":     [(0, 1.0), (0.55, 0.80), (1.5, 1.05), (2.45, 1.0),
                               (2.55, 0.74), (3.1, 1.0)],
                "lean":       [(0, 0.0), (0.55, -0.12 * d), (1.5, 0.16 * d),
                               (2.45, 0.0), (2.8, 0.18 * d), (3.5, 0.0)],
                "look_x":     [(0, 0.0), (0.55, 0.8 * d), (2.45, 0.0), (3.6, 0.0)],
            },
            events=[
                (0.0, lambda p: (p.sfx.play("sparkle"),
                                 p.say(random.choice(
                                     ["看我的旋转跳跃~✧", "转圈圈~✧",
                                      "裙子转起来的样子最好看了!",
                                      "旋转——开始!"]), 1.6))),
                (1.4, lambda p: p.circles.append(
                    dict(born=time.time(), life=0.45, rx=1.0, kind="cast"))),
                (2.45, lambda p: p._twirl_stop()),
            ])

    def _twirl_stop(self):
        """急停收势:大跳缓冲 + 星星炸开 + 冲击波(压扁由时间轴负责)。"""
        self.hop(0.95)
        self.face = self._twirl_face0
        self.look_x = 0.0
        self.star_burst(0, -0.12 * self.H, 14, sp=(80, 170), grav=170, size=(5, 9))
        self.land_fx(0.9)
        self.sfx.play("pop")

    def start_fall(self):
        """脚滑摔一跤:小哭脸 + 尘星 + 摔出来的小齿轮 + 1.2 秒站起演出。"""
        self.state = "fall_stand"
        self.fall_stand_start = time.time()
        self.state_until = self.fall_stand_start + 1.2
        self.hop_t = self.lean_kick = 0.0
        self.sfx.play("boing")              # 倒地"咚"复用 boing
        self.squash = 0.78                  # 倒地压缩
        self._shocks.append(dict(born=self.fall_stand_start, strength=.4))
        # 坐地扬起一小圈尘星;一两颗"身上戴的"小齿轮被摔出来,弹跳着滚走
        for _ in range(5):
            self.add_part("sparkle",
                          random.uniform(-0.20, 0.20) * self.W,
                          self.FOOT_Y - self.H / 2 - random.uniform(0, 14),
                          vx=random.uniform(-75, 75),
                          vy=random.uniform(-100, -30),
                          grav=240, life=random.uniform(0.4, 0.7),
                          size=random.uniform(2.5, 4.5),
                          color=random.choice([(214, 205, 190), GOLD_L, GOLD]),
                          phase=random.uniform(0, 6.28))
        for side in (-1, 1):
            self.add_part("gear",
                          side * 0.10 * self.W,
                          self.FOOT_Y - self.H / 2 - 22,
                          vx=side * random.uniform(90, 150), vy=-150,
                          grav=430, life=random.uniform(0.9, 1.2),
                          size=random.uniform(8, 10),
                          spin=random.uniform(6, 9) * side,
                          phase=random.uniform(0, 6.28))
        self.say(random.choice(
            ["呜呜~脚滑了~", "哎哟!好疼~", "呜…屁股好痛…"]), 1.4)
        self.play_emotion("tired", 1.0)

    def start_sneeze(self):
        """打喷嚏:后仰吸气 -> 「啊…啊…」 -> 嚏!(猛压缩+星星迸溅) -> 缓过来。"""
        if self.core_profile():
            return False
        self.state = "sneeze"
        self.sneeze_start = time.time()
        self.state_until = self.sneeze_start + 2.4
        self._sneeze_done = False
        self._sneeze_initial = (self.squash, self.lean)
        self.hop_t = self.lean_kick = 0.0
        self.say("啊……啊……", 1.2)

    def _advance_sneeze(self, now):
        """两次吸气、短促前倾与回弹;过时的喷嚏不补发,打断即取消。"""
        if self.state != "sneeze":
            return
        age = now - self.sneeze_start
        squash0, lean0 = self._sneeze_initial
        self.squash = self._track(age, [(0, squash0), (.34, 1.035),
            (.48, 1.015), (.82, 1.07), (.9, 1.07), (1.02, .84),
            (1.2, 1.035), (1.48, .985), (1.85, 1), (2.4, 1)])
        self.lean = self._track(age, [(0, lean0), (.34, -.045),
            (.48, -.025), (.84, -.10), (.9, -.10), (1.02, .14),
            (1.2, -.04), (1.55, .025), (2.15, 0)])
        self._bend = self._track(age, [(0, 0), (.85, -.035), (.9, -.035),
            (1.02, .17), (1.25, -.025), (1.7, 0)])
        if age >= .9 and not self._sneeze_done:
            self._sneeze_done = True
            if age < 1.2:
                self.star_burst(.23*self.W, .15*self.H, 5,
                    sp=(55*self.scale, 105*self.scale), grav=140*self.scale,
                    life=(.4, .65), size=(3*self.scale, 5*self.scale))
                # "嚏"的那一下从嘴前喷出一团气,顺着前倾方向冲出去。原来只有
                # 5 颗 3~5px 的小星,连拍里认不出是在打喷嚏
                mx, my = getattr(self, "_mouth_xy", (self.W * .49, self.H * .42))
                self.puff(mx - self.W / 2 + 18 * self.scale, my - self.H / 2 + 6 * self.scale,
                          vx=150 * self.scale, vy=40 * self.scale)
                self.say("嚏!", .9)
        if age >= 2.4:
            self.state = "idle"
            self.next_event = now + random.uniform(10, 18)
            self.say(random.choice(
                ["失礼了…", "呀,打个喷嚏~", "唔,是不是有人在想我?"]), 2.2)

    @classmethod
    def _dizzy_pose(cls, age):
        # 动作自己的时钟决定相位,前段渐入、后段平稳回正。
        amp = cls._track(age, [(0, 0), (.22, 1), (.65, .95),
                              (1.6, .5), (2.35, .12), (2.8, 0)])
        sway = math.sin(max(0, age) * 8.5) * amp
        return .13*sway, .055*math.sin(max(0, age)*8.5-.5)*amp, \
            1-.025*amp*(.5+.5*math.cos(max(0, age)*17)), .65*sway, amp

    def _advance_dizzy(self, now):
        if self.state != "dizzy":
            return
        age = now - (self.state_until - 2.8)
        self.lean, self._bend, self.squash, self.look_x, self.dizzy_amp = self._dizzy_pose(age)
        settle = 1-self._track(age, [(0, 0), (.3, 1)])
        lean0, squash0, look0 = self._dizzy_initial
        self.lean += lean0*settle
        self.squash += (squash0-1)*settle
        self.look_x += look0*settle
        if age >= 2.8:
            self.state = "idle"
            self.next_event = now + random.uniform(3, 7)
            self.say("呼…终于不转了", 2.0)

    @classmethod
    def _stand_pose(cls, age):
        return (cls._track(age, [(0, .78), (.18, .80), (.58, 1.035),
                                (.78, .985), (1.2, 1)]),
                cls._track(age, [(0, .045), (.2, .065), (.6, -.025), (1.2, 0)]),
                cls._track(age, [(0, .08), (.23, .12), (.62, -.03), (1.2, 0)]))

    # ---------------- 扩展交互 ----------------
    def on_wheel(self, e):
        """滚轮当顺毛用:连续滚够了会害羞。坐在秋千上时滚轮缩放整个场景
        (<MouseWheel> 先绑了缩放、后又被这里覆盖,原来缩放从没生效)。"""
        if self.state == "swing" and getattr(self, "_swing", None):
            return self.on_wheel_scene(e)
        now = time.time()
        self.last_interact = now
        if self.state in ("sleep", "yawn"):
            self.wake_if_sleep(random.choice(WAKE_LINES))
            return
        self.wheel_acc += 1
        self.squash = 0.95
        self.lean_kick = max(getattr(self, "lean_kick", 0.0), 0.35)
        if now > self._spark_cd:
            self._spark_cd = now + 0.05
            self.add_part("sparkle", random.uniform(-0.16, 0.16) * self.W,
                          -0.30 * self.H, life=0.5, size=random.uniform(3, 6),
                          color=random.choice(STAR_COLORS),
                          phase=random.uniform(0, 6.28))
        if self.wheel_acc >= 10 and now > self.wheel_cd:
            self.wheel_acc = 0.0
            self.wheel_cd = now + 7
            self.sfx.play("voice_happy")
            self.hearts(0, -0.30 * self.H, 5)
            self.play_emotion("shy", 2.4)
            self.say(random.choice(WHEEL_LINES), 2.2)
            self.add_affection(2)

    def on_middle(self, e):
        """中键打开 AI 工作信息。"""
        if self.core_profile():
            self.open_ai_panel()
            return
        self.last_interact = time.time()
        if self.state == "sleep":
            self.wake_if_sleep(random.choice(WAKE_LINES))
            return
        pick = random.choice(("burst", "dance", "peek", "proud", "twirl",
                              "flip", "roll", "meditate"))
        if pick == "burst":
            self.sfx.play("sparkle")
            self.star_burst(0, -0.1 * self.H, 14, sp=(120, 240), grav=180, size=(5, 11))
            self.circles.append(dict(born=time.time(), life=0.7, rx=0.9, kind="cast"))
            self.hop(0.8)
            self.say(random.choice(MIDDLE_LINES), 2.0)
        elif pick == "dance":
            self.start_dance()
        elif pick == "peek":
            self.start_peek()
        elif pick == "meditate":
            self.start_meditate()
        elif pick == "twirl":
            self.start_twirl()
        elif pick == "flip":
            self.start_flip()
        elif pick == "roll":
            self.start_roll()
        else:
            self.play_emotion("proud", 2.4)
            self.hop(0.6)
            self.say("嘿嘿,我很厉害吧?", 2.2)

    def on_enter(self, e):
        """鼠标移到她身上。"""
        now = time.time()
        self._inside = True
        if now < self._enter_cd or self.state == "sleep":
            return
        self._enter_cd = now + 20
        self.last_interact = now
        self.sfx.play("greet")
        self.play_emotion("greet", 2.0)
        if not self._start_micro_motion("notice"):
            self.lean_kick = 0.7
        # 被靠近时身边冒出两三粒时之沙,像被惊起的小萤火
        for _ in range(random.randint(2, 3)):
            self.add_part("sparkle",
                          random.uniform(-0.24, 0.24) * self.W,
                          random.uniform(-0.30, -0.05) * self.H,
                          vy=random.uniform(-40, -15),
                          life=random.uniform(0.5, 0.8),
                          size=random.uniform(2.5, 4.5),
                          color=random.choice([GOLD_L, MAGIC_B]),
                          phase=random.uniform(0, 6.28))
        if random.random() < 0.7:
            self.say(random.choice(ENTER_LINES), 2.0)

    def _set_house_hover(self, kind):
        if kind == getattr(self, '_house_hover', None):
            return
        self._house_hover = kind
        try:
            self.root.configure(cursor='hand2' if kind else '')
        except Exception:
            pass

    def on_leave(self, e):
        """鼠标离开她。"""
        now = time.time()
        self._set_house_hover(None)
        self._inside = False
        self._hover_last = None
        self._crystal_hover = False            # 悬停提示随之收起
        self._crystal_hover_since = 0.0
        if now < self._leave_cd or self.state == "sleep":
            return
        self._leave_cd = now + 45
        if random.random() < 0.35:
            self.sfx.play("bye")
            self.play_emotion("bye", 2.0)
            self.say(random.choice(LEAVE_LINES), 2.0)

    # ---------------- 好感度 ----------------
    AFFECTION_LEVELS = [
        (0,   "点头之交"), (30,  "熟起来了"), (80,  "好朋友"),
        (160, "很依赖你"), (280, "最喜欢你"),
    ]

    def add_affection(self, n=1.0, quiet=False):
        old = self.affection_level()
        self.affection = min(400.0, self.affection + n)
        lv = self.affection_level()
        if lv != old and not quiet:
            self.sfx.play("levelup")
            self.say(f"我们的关系升级啦 —— {lv}!", 3.4)
            self.play_emotion("proud", 2.6)
            self.hearts(0, -0.30 * self.H, 8)
            self.star_burst(0, -0.05 * self.H, 12, sp=(110, 210), grav=170, size=(5, 10))
            self.confetti_burst(0, -0.1 * self.H, 18)
            self.circles.append(dict(born=time.time(), life=0.9, rx=1.0, kind="cast"))
            self.save_settings()

    @staticmethod
    def _season(mon):
        return ("spring" if 3 <= mon <= 5 else "summer" if 6 <= mon <= 8
                else "autumn" if 9 <= mon <= 11 else "winter")

    def companion_days(self):
        try:
            first = time.mktime(time.strptime(self.first_day, "%Y-%m-%d"))
            return max(1, int((time.time() - first) // 86400) + 1)
        except Exception:
            return 1

    def affection_level(self):
        name = self.AFFECTION_LEVELS[0][1]
        for need, n in self.AFFECTION_LEVELS:
            if self.affection >= need:
                name = n
        return name

    # ---------------- 石头剪刀布 ----------------
    RPS = {"rock": ("石头", "✊"), "scissors": ("剪刀", "✌"), "paper": ("布", "✋")}
    RPS_BEATS = {"rock": "scissors", "scissors": "paper", "paper": "rock"}

    def play_rps(self, mine):
        """mine 是主人出的拳。她倒数三下再亮拳,免得像作弊。"""
        if self.core_profile():
            return False
        if self._rps_busy:
            return
        if mine not in self.RPS:   # 外部指令可能传非法值,兜回石头
            mine = "rock"
        self._rps_busy = True
        self.last_interact = time.time()
        if self.state == "sleep":
            self.wake_if_sleep()
        hers = random.choice(list(self.RPS))
        self.say("石头…", 0.8)
        self.root.after(700, lambda: self.say("剪刀…", 0.8))
        self.root.after(1400, lambda: self.say("布!", 0.8))
        self.root.after(1500, lambda: self.hop(0.7))
        self.root.after(2000, lambda: self._rps_result(mine, hers))

    def _rps_result(self, mine, hers):
        self._rps_busy = False
        mn, me = self.RPS[mine]
        hn, he = self.RPS[hers]
        if mine == hers:
            self.rps[1] += 1
            self._reply(f"{he} {hn} —— 平手!再来一局?", "curious")
            # 平手也要有点动静:一颗时之沙当"叮~"
            self.add_part("sparkle", 0.0, -0.30 * self.H, vy=-30,
                          life=0.7, size=4.5, color=GOLD_L,
                          phase=random.uniform(0, 6.28))
        elif self.RPS_BEATS[hers] == mine:
            self.rps[0] += 1          # 她赢
            self.sfx.play("levelup")
            self._reply(f"{he} {hn} 克 {me} {mn},我赢啦!", "proud")
            self.star_burst(0, -0.05 * self.H, 10, sp=(100, 190), grav=160, size=(5, 9))
            self.hop(0.9)
        else:
            self.rps[2] += 1          # 她输
            self._reply(f"{he} {hn} 输给 {me} {mn} 了…不服!", "pouty")
            self.lean_kick = 0.9
            self.add_affection(2, quiet=True)   # 输了给点安慰分
            # 输了跺脚,气鼓鼓地冒两滴小泪珠
            for _ in range(2):
                self.add_part("sweat", random.uniform(-0.10, 0.10) * self.W,
                              -0.32 * self.H, vx=random.uniform(-10, 10),
                              vy=random.uniform(24, 36),
                              life=0.9, size=random.uniform(3, 4.2))
        self.add_affection(1)
        self.save_settings()

    # ---------------- 抛掷 ----------------
    def hit_wall(self, side=None):
        """撞墙/弹地的反馈:挤压 + 星星迸溅 + 撞到的那一侧喷一团尘雾。

        side 是撞击点的方向 (dx, dy),各取 -1/0/1。原来不分哪面墙,迸溅永远
        在身体中间,看不出是"撞上了左边"还是"弹在地上"。"""
        self.sfx.play("boing")
        self.squash = 0.86
        self.star_burst(random.uniform(-0.15, 0.15) * self.W, 0, 6,
                        sp=(90, 170), grav=180, size=(4, 8))
        if side:
            dx, dy = side
            # 放在撞击那一侧的轮廓外:0.30W 以内会落在她的宽帽檐上,白雾压在
            # 紫帽子上几乎看不见
            rx = dx * 0.40 * self.W
            ry = ((self.FOOT_Y - self.H / 2) if dy > 0
                  else -0.40 * self.H if dy < 0 else -0.12 * self.H)
            # 不像抛飞拖尾那样钉在屏幕上:撞墙那一刻她已经以几百 px/s 弹开,
            # 钉在墙上的尘雾 0.04 秒就出了窗口(实测),一眼都看不到。让它
            # 跟着她走、往撞击方向外侧鼓出去,读起来是"砰"地蹭起一团灰
            self.puff(rx, ry, vx=dx * 70 * self.scale, vy=dy * 70 * self.scale)

    def throw_ball(self):
        """一颗可点击的星光球,五秒内弹跳,运动与命中共用当前位置。"""
        if self.core_profile():
            return False
        if self.state in ("sleep", "yawn"):
            self.say("再等我睡会儿…", 1.8); return
        self.last_interact = time.time()
        self._cancel_ball()
        # 初始位置在角色侧面,给光晕与边界反弹留出空间。
        from_side = random.choice((-1, 1))
        self.add_part("ball", from_side * 0.3 * self.W, -0.05 * self.H,
                      vx=from_side * random.uniform(80, 130)*self.scale,
                      vy=random.uniform(-300, -240)*self.scale,
                      life=5.0, size=7*self.scale, color=(255, 255, 255),
                      phase=0)
        self._ball_active = True
        self._ball_start = time.time()
        self.sfx.play("magic")
        self.say(random.choice(
            ["点一下光球,一起接住它~", "星光球来啦,点它试试!", "接住这颗小星光~"]), 1.6)
        self.play_emotion("excited", 1.6)
        self._start_micro_motion('notice')

    def _ball_landed(self):
        """结束本轮玩球。"""
        self._cancel_ball()

    def _cancel_ball(self):
        self._ball_active = False
        self.parts = [q for q in self.parts if q['kind'] not in ('ball', 'ball_ring')]

    def _advance_ball(self, now):
        ball = next((q for q in self.parts if q['kind'] == 'ball'), None)
        if ball is None:
            self._ball_active = False
            return
        if self.state in ('sleep', 'yawn') or (self.drag and self.drag[4]):
            self._cancel_ball()
            return
        if now - ball['born'] >= 5:
            self._cancel_ball()
            self.say('哎呀,球滚走了~', 1.8)
            return
        # 固定 120Hz 小步长;用绝对已执行步数避免不同帧率的积分漂移。
        end = max(0, int((now-ball['born'])*120 + 1e-7))
        radius = 7*self.scale
        floor = self.FOOT_Y-radius
        left, right = radius+12*self.scale, self.W-radius-12*self.scale
        impact = None
        for step in range(ball['sim_steps'], end):
            h = 1/120
            if not ball['grounded']:
                ball['vy'] += 1200*self.scale*h
            ball['x'] += ball['vx']*h
            ball['y'] += ball['vy']*h
            if ball['x'] < left or ball['x'] > right:
                ball['x'] = max(left, min(right, ball['x']))
                ball['vx'] *= -.75
            if ball['y'] >= floor and ball['vy'] > 0:
                ball['y'] = floor
                impact = (ball['x'], ball['born']+(step+1)/120)
                ball['vy'] *= -.55
                ball['vx'] *= .85
                if abs(ball['vy']) < 45*self.scale:
                    ball['vy'] = 0
                    ball['grounded'] = True
            if ball['grounded']:
                ball['y'] = floor
                ball['vx'] *= math.exp(-3*h)
            if step % 4 == 0:
                ball['trail'].append((ball['x'], ball['y']))
                ball['trail'] = ball['trail'][-6:]
        ball['sim_steps'] = end
        # 长帧只展示最近一次落地,不回放已经过去的一串冲击。
        if impact and now-impact[1] < .15:
            self.add_part('ball_ring', impact[0]-self.W/2, self.FOOT_Y-self.H/2,
                          life=.35, size=18*self.scale, color=GOLD_L)

    def _catch_ball(self, x, y):
        """命中即消费光球,接住反馈没有会串入下一动作的延迟回调。"""
        self._advance_ball(time.time())
        for q in self.parts:
            if q["kind"] != "ball":
                continue
            # 用 q 当前已推进的位置(_tick_body 持续更新 q["x"]/q["y"],直接读)
            cx, cy = q["x"], q["y"]
            if math.hypot(cx - x, cy - y) < 28*self.scale:
                self.parts.remove(q)
                self._ball_landed()
                self.last_interact = time.time()
                if self.state in ('idle', 'walk', 'chase', 'sticker'):
                    self.state = 'idle'
                    self._start_micro_motion('catch')
                self.sfx.play("voice_happy")
                self.say(random.choice(
                    ["捡到啦!", "接到啦!", "抓到啦~"]), 2.0)
                self.play_emotion("proud", 2.0)
                self.hearts(0, -0.20 * self.H, 4)
                self.add_part("sparkle", q["x"] - self.W / 2,
                              q["y"] - self.H / 2,
                              life=0.6, size=random.uniform(5, 9),
                              color=(255, 255, 200), phase=0)
                return True
        return False

    def throw(self, vx, vy):
        if self.core_profile():
            return False
        self.state = "fly"
        self.sfx.play("voice_surprise")
        self.vx, self.vy = vx, vy
        self.bounces = 0
        self.play_emotion("surprised", 1.6)
        self.say(random.choice(["哇啊——!", "飞起来了!", "太快啦!"]), 1.8)

    def go_dizzy(self):
        """被摇晕。"""
        if self.core_profile():
            return False
        if self.state == "swing" and self._swing and not self.drag:
            self._wake_from_nap()   # 打盹中互动:统一唤醒
            self.star_burst(0, -0.30 * self.H, 8)
            self.say("晕……", 1.8)
            return
        if self._land_first(self.go_dizzy):
            return
        now = time.time()
        self.state = "dizzy"
        self.state_until = now + 2.8
        self._dizzy_initial = (self.lean, self.squash, self.look_x)
        self.hop_t = self.lean_kick = 0.0
        self.sfx.play("boing")
        self.dizzy_amp = 1.0
        self.play_emotion(random.choice(("dizzy", "angry")), 2.8)
        self.say(random.choice(DIZZY_LINES), 2.4)
        for i in range(6):
            side = -1 if i % 2 else 1
            self.add_part("star", side * (.26 + .025*(i//2)) * self.W,
                          (-.23 + .05*(i//2)) * self.H,
                          vx=side*18*self.scale, vy=-12*self.scale,
                          life=1.1 + .12*(i//2), size=random.uniform(4, 6)*self.scale,
                          color=random.choice(STAR_COLORS),
                          phase=random.uniform(0, 6.28), spin=4.0)

    # ==================== 声明式动画引擎 ====================
    # 一个动画 = 一张时间轴表:参数轨道(关键帧插值) + 一次性事件(配音效/
    # 台词/粒子)。start_* 负责把表(可能带着本局的随机方向)挂到实例上并
    # 复位进度,状态分支里只留一行 _play_timeline + 收尾判断。
    # 加新动作 = 填一张表,不用再往 tick 里堆 if/elif。
    @staticmethod
    def _track(t, keys, default=0.0):
        """关键帧插值:keys=[(时间, 值), ...](时间升序)。
        段内 smoothstep(两头慢中间快,自带卡通顿挫),两端外取端值。"""
        if not keys:
            return default
        if t <= keys[0][0]:
            return keys[0][1]
        for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
            if t < t1:
                k = (t - t0) / max(1e-6, t1 - t0)
                e = k * k * (3 - 2 * k)
                return v0 + (v1 - v0) * e
        return keys[-1][1]

    def _play_timeline(self, t, tracks, events, done):
        """把一张时间轴落到当帧:参数轨道直接写入 self.<属性名>,
        事件列表 [(时间, 回调), ...] 到点触发一次(done 集合防重放)。
        回调签名 fn(pet),方便闭包里引用随机选好的台词/方向。"""
        for attr, keys in tracks.items():
            setattr(self, attr, self._track(t, keys))
        for i, (et, fn) in enumerate(events):
            if t >= et and i not in done:
                done.add(i)
                fn(self)

    def _begin_tl(self, tracks, events):
        """挂载一张时间轴并复位进度(每个 start_* 开头调一次)。"""
        self._tl_tracks = tracks
        self._tl_events = events
        self._tl_done = set()

    # 轻互动叠加在视线跟随上,不改主状态或累积变形。四列依次是
    # lean / bend / squash 增量 / lift(px,按 scale 缩放)。起落都回到零。
    MICRO_POSES = {
        "catch": [(0, 0, 0, 0, 0), (.16, .045, .12, -.03, -1),
                  (.36, -.025, -.04, .035, 3), (.58, .02, .04, -.02, -1),
                  (.8, 0, 0, 0, 0)],
        "arrive": [(0, 0, 0, 0, 0), (.2, .035, .08, -.025, -1),
                   (.48, -.02, -.025, .025, 2), (.85, 0, 0, 0, 0)],
        "wake": [(0, 0, 0, 0, 0), (.30, -.025, -.04, -.03, -2),
                 (.85, .045, .10, .045, 4), (1.3, .03, .06, .025, 2),
                 (1.75, -.015, -.02, -.015, -1), (2.2, 0, 0, 0, 0)],
        "notice": [(0, 0, 0, 0, 0), (.22, -.025, -.035, -.02, -1),
                   (.65, .09, .16, .025, 3), (1.15, .09, .16, .025, 3),
                   (1.65, -.018, -.025, 0, 0), (2.1, 0, 0, 0, 0)],
        "nuzzle": [(0, 0, 0, 0, 0), (.20, -.025, -.04, -.025, -2),
                   (.62, .10, .19, .04, 5), (1.0, .065, .12, .02, 3),
                   (1.4, .105, .19, .035, 4), (1.85, -.02, -.03, -.01, -1),
                   (2.3, 0, 0, 0, 0)],
        "giggle": [(0, 0, 0, 0, 0), (.18, -.075, -.09, -.04, -2),
                   (.36, .08, .10, .045, 4), (.55, -.07, -.09, -.025, 0),
                   (.76, .06, .075, .035, 3), (.99, -.04, -.05, -.015, 0),
                   (1.25, .025, .03, .015, 1), (1.65, 0, 0, 0, 0)],
    }

    def _micro_allowed(self):
        return (self.state in ("idle", "sticker")
                and (not self.drag or not self.drag[4])
                and not self.singing and not self.thinking_now)

    def _micro_pose(self, now):
        motion = self._micro_motion
        if not motion:
            return (0.0,) * 4
        kind, born, side, initial = motion
        rows = self.MICRO_POSES[kind]
        age = now - born
        if not self._micro_allowed() or age >= rows[-1][0]:
            self._micro_motion = None
            return (0.0,) * 4
        return tuple(self._track(age, [(0, initial[i])] + [
            (row[0], row[i + 1] * (side if i < 2 else 1))
            for row in rows[1:]]) for i in range(4))

    def _start_micro_motion(self, kind):
        if not self._micro_allowed():
            return False
        now = time.time()
        initial = self._micro_pose(now)  # 连点从当前姿势接续,不突然归零
        mx, _ = cursor_pos()
        side = 1 if mx >= self.x + self.W / 2 else -1
        self._micro_motion = (kind, now, side, initial)
        self.lean_kick = 0.0
        self.hop_t = 0.0
        self.next_event = max(self.next_event, now + self.MICRO_POSES[kind][-1][0] + .5)
        return True

    def land_fx(self, strength=1.0):
        """落地冲击:登记一次脚下冲击波(渲染帧里画,fx.shockwave 需要
        画布句柄)+ 尘土星星粒子。strength 0~1 控制大小。
        卡通原则:落地越重,压扁越狠、冲击波越大(压扁由调用方顺手设)。"""
        self._shocks.append(dict(born=time.time(), strength=strength))
        for _ in range(2 + int(4 * strength)):
            sgn = random.choice((-1, 1))
            self.add_part("sparkle", sgn * random.uniform(0.14, 0.3) * self.W,
                          (self.FOOT_Y - 10) - self.H / 2,
                          vx=sgn * random.uniform(60, 150) * (0.5 + strength),
                          vy=-random.uniform(10, 60),
                          life=random.uniform(0.4, 0.7),
                          size=random.uniform(3, 6),
                          color=random.choice((MAGIC_A, GOLD_L, WHITE)),
                          phase=random.uniform(0, 6.28))

    # ---------------- 扩展自主动作 ----------------
    def start_dance(self):
        """跳舞:五幕编舞(时间轴驱动)—— ①点地起手 ②身体波浪(渐强)
        ③半身转身 ④碎步横移+抖肩电摇 ⑤定格谢幕(大跳+彩带+冲击波)。
        每拍小跳+音符由状态分支的节拍器负责,姿势曲线全在这张表里。"""
        if self.core_profile():
            return False
        if self._seat_guard():
            return
        if self._land_first(self.start_dance):
            return
        self.state = "dance"
        self.sfx.play("voice_play")
        self.dance_start = time.time()
        b = self.dance_beat = random.uniform(0.40, 0.46)
        self.dance_face0 = self.face
        self._dance_bi = -1
        self._dance_landed_beat = -1
        self._dance_home = self.x
        self.hop_t = 0.0
        self.state_until = self.dance_start + b * 16
        self.play_emotion("dance", 2.6)
        sd = self.dance_side = random.choice((-1, 1))
        self._begin_tl(
            tracks={
                "squash": [(0, 1.0), (b, 0.88), (2 * b, 1.0),
                           (14 * b, 1.0), (14.2 * b, .83), (14.5 * b, 1.04),
                           (15.15 * b, .78), (15.4 * b, 1.055), (16 * b, 1.0)],
                "lean":   [(0, 0.0), (2 * b, 0.0),
                           (3 * b, 0.25 * sd), (4 * b, -0.25 * sd),
                           (5 * b, 0.28 * sd), (6 * b, -0.28 * sd),
                           (7 * b, 0.25 * sd), (8 * b, -0.15 * sd),
                           (9 * b, 0.20 * sd), (10 * b, -0.20 * sd),
                           (11 * b, 0.20 * sd), (12 * b, -0.20 * sd),
                           (13 * b, 0.18 * sd), (14 * b, 0.0),
                           (15 * b, 0.06 * sd), (16 * b, 0.0)],
                "look_x": [(0, 0.7 * sd), (2 * b, -0.7 * sd), (7 * b, 0.9 * sd),
                           (9 * b, -0.9 * sd), (13 * b, 0.5 * sd), (14 * b, 0.0)],
                "_bend":  [(9 * b, 0.0), (11 * b, 0.18), (13 * b, -0.18),
                           (14 * b, 0.0)],
            },
            events=[
                (0.0, lambda p: p.say(random.choice(DANCE_LINES), 2.4)),
                (15.15 * b, lambda p: p._dance_finale()),
            ])

    def _dance_finale(self):
        """谢幕:大跳落地 + 彩带星星 + 冲击波 + 骄傲脸。"""
        self.hop_t = 0.0
        self.face = self.dance_face0
        self.confetti_burst(0, -0.05 * self.H, 26)
        self.star_burst(0, -0.1 * self.H, 12, sp=(90, 180), grav=160)
        self.play_emotion("proud", 2.4)
        self.sfx.play("levelup")
        self.land_fx(0.8)
        self.say(random.choice(
            ["完成!掌声在哪里~", "呼——跳完啦!", "谢幕~♪",
             "怎么样,跳得不错吧?"]), 2.2)

    @staticmethod
    def _dance_motion(age, beat, scale):
        beats = max(0.0, age / max(.1, beat))
        if beats < 14:
            lift = Pet._track(beats % 1, [(0, 0), (.15, 0), (.48, 9), (.9, 0), (1, 0)])
        else:
            lift = Pet._track(beats, [(14, 0), (14.2, 0), (14.7, 25),
                                      (15.15, 0), (16, 0)])
        offset = 32 * math.sin((beats - 9) * math.pi) if 9 < beats < 14 else 0.0
        return lift * scale, offset * scale

    def _advance_dance(self, now):
        age, beat = now - self.dance_start, self.dance_beat
        bi = int(age / beat)
        self._play_timeline(age, self._tl_tracks, self._tl_events, self._tl_done)
        self._spin_lift, offset = self._dance_motion(age, beat, self.scale)
        self.x = max(self.x_min, min(self.x_max, self._dance_home + offset))
        if 9 * beat < age < 14 * beat:
            self.face = 1 if math.cos((age / beat - 9) * math.pi) >= 0 else -1
        if bi != self._dance_bi and bi < 14:
            self._dance_bi = bi
            self.add_part("note", random.uniform(-.24, .24) * self.W,
                          -.36 * self.H, vy=-random.uniform(34, 56), life=1.7,
                          size=random.uniform(9, 15), phase=random.uniform(0, 6.28),
                          txt=random.choice(("♪", "♫", "♩")))
            if bi % 2:
                self.star_burst(random.uniform(-.3, .3) * self.W, 0, 3,
                                sp=(60, 130), grav=160, size=(4, 8))
        # 卡顿跨过多拍时只补最后一次落地,不连放一串过时的光圈。
        landed_beat = math.floor(age / beat - .9)
        if 0 <= landed_beat < 14 and landed_beat > self._dance_landed_beat:
            self._dance_landed_beat = landed_beat
            self._shocks.append(dict(born=now, strength=.15))
        if now > self.state_until:
            self.state = "idle"
            self.next_event = now + random.uniform(5, 11)

    @staticmethod
    def _roll_offset(age, direction, scale):
        progress = max(0.0, min(1.0, (age - .3) / 1.9))
        return direction * 114 * scale * progress * progress * (3 - 2 * progress)

    @staticmethod
    def _roll_ground_offset(sprite, resting):
        """旋转后按可见轮廓贴地,扣除原图本来就有的脚下透明留白。"""
        bounds, baseline = sprite.getbbox(), resting.getbbox()
        if bounds is None or baseline is None:
            return 0
        return (sprite.height - bounds[3]) - (resting.height - baseline[3])

    def start_stretch(self):
        """伸懒腰:猫式四段(时间轴驱动)—— ①吸气下蹲蓄力 ②缓慢拉高的
        同时上半身向一侧弯成弓形 ③弓形顶点舒展微颤 ④卸力回弹,向另一
        侧甩一下再归位(爱心+满足音)。微颤和上浮星尘是程序性的,留在分支里。"""
        if self.core_profile():
            return False
        if self.state == "swing" and self._swing and not self.drag:
            self._wake_from_nap()   # 打盹中互动:统一唤醒
            # 坐姿伸懒腰:时之沙从头顶洒下(不走落地时间轴)
            self.say(random.choice(STRETCH_LINES), 2.2)
            self._stretch_dust()
            self.add_affection(0.3)
            return
        self.state = "stretch"
        self.stretch_start = time.time()
        self.state_until = time.time() + 3.8
        sd = self.stretch_side = random.choice((-1, 1))
        self._begin_tl(
            tracks={
                "squash": [(0, 1.0), (.7, .93), (2.0, 1.10), (2.7, 1.09),
                           (3.15, .96), (3.5, 1.015), (3.8, 1.0)],
                "_bend":  [(0, 0.0), (.7, 0.0), (2.0, .36 * sd),
                           (2.7, .36 * sd), (3.2, -.09 * sd), (3.8, 0.0)],
                "lean":   [(0, 0.0), (0.7, 0.07 * sd), (2.0, 0.05 * sd),
                           (2.7, 0.06 * sd), (3.0, 0.0), (3.8, 0.0)],
            },
            events=[
                (0.0, lambda p: p.say(random.choice(STRETCH_LINES), 2.2)),
                (2.0, lambda p: (setattr(p, "_mouth", ("laugh", time.time() + 1.2)),
                                 p.add_part("dial", 0.05 * p.W, -0.30 * p.H,
                                            life=1.1, size=13.5, spin=2.6,
                                            phase=random.uniform(0, 6.28)))),
                (2.9, lambda p: (p.hearts(0, -0.28 * p.H, 5), p.sfx.play("voice_happy"),
                                 p._stretch_dust())),
            ])

    def _stretch_dust(self):
        """舒展到顶卸力:头顶的表盘化作一捧时之沙,扇形洒下来。"""
        for i in range(7):
            a = math.pi * (0.12 + 0.76 * i / 6)
            self.add_part("sparkle",
                          math.cos(a) * 0.15 * self.W,
                          -0.27 * self.H + math.sin(a) * 18,
                          vx=math.cos(a) * 60, vy=random.uniform(-35, 5),
                          grav=110, life=random.uniform(0.5, 0.9),
                          size=random.uniform(3, 5.5),
                          color=random.choice([GOLD_L, GOLD]),
                          phase=random.uniform(0, 6.28))

    def start_peek(self):
        """发会呆:走神四幕(时间轴驱动)—— ①缓缓转头望向一边 ②思绪飘飘
        (萤火虫上浮+走神台词) ③打瞌睡点头(zzz+晚安贴纸) ④猛然惊醒
        (大弹跳+汗滴+惊讶脸)。点头和萤火虫是程序性的,留在分支里。"""
        if self.core_profile():
            return False
        if self.state == "swing" and self._swing and not self.drag:
            self._wake_from_nap()   # 打盹中互动:统一唤醒
            self.say("嗯……发会呆~", 2.2)
            return
        if self._land_first(self.start_peek):
            return
        if self.fy < self.ground_feet - 6:
            return
        self.state = "peek"
        self.hop_t = self.lean_kick = 0.0
        self.peek_start = time.time()
        self.state_until = self.peek_start + 7.6
        d = self.peek_dir = random.choice((-1, 1))
        self._begin_tl(
            tracks={
                "look_x": [(0, 0.0), (1.4, 1.0 * d), (4.6, 1.0 * d),
                           (4.9, 0.25 * d), (6.15, 0.25 * d), (6.3, -1.0 * d),
                           (7.0, 0.0)],
                "lean":   [(0, 0.0), (1.4, 0.13 * d), (4.6, 0.13 * d),
                           (6.4, 0.0), (7.6, 0.0)],
                "_spin_lift": [(0, 0), (6.25, 0), (6.48, 24*self.scale),
                               (6.82, 0), (7.6, 0)],
                "squash": [(0, 1), (6.18, 1), (6.25, .94), (6.42, 1.045),
                           (6.70, 1), (6.82, .91), (7.0, 1.04),
                           (7.22, .985), (7.6, 1)],
            },
            events=[
                (0.0, lambda p: p.say(random.choice(PEEK_LINES), 2.2)
                 if random.random() < 0.6 else None),
                (1.6, lambda p: p.say(random.choice(
                    ["云在动呢…", "晚上吃什么呢…", "(走神中)…",
                     "魔女也是要放空的~"]), 2.6)),
                (4.7, lambda p: p.play_emotion("sleep", 2.0)),
                (6.25, lambda p: p._peek_startle()),
                (6.82, lambda p: p.land_fx(.45)),
            ])

    def _peek_startle(self):
        """惊醒:大弹跳 + 汗滴 + 惊讶脸 + 冲击波。"""
        self.hop_t = 0.0
        self.parts = [p for p in self.parts if p["kind"] != "zzz"]
        self.star_burst(0, -0.3 * self.H, 9, sp=(70, 150), grav=170, size=(4, 7))
        for _ in range(3):
            self.add_part("sweat", random.uniform(-0.12, 0.12) * self.W,
                          -0.4 * self.H, vy=random.uniform(24, 38),
                          life=1.0, size=random.uniform(3, 4.5))
        self.play_emotion("surprised", 1.6)
        self.sfx.play("voice_surprise")
        self.say(random.choice(
            ["哇!差点睡着!", "唔哇!我刚才在想什么来着?",
             "呀!走神走太远了!"]), 2.0)

    def start_flip(self):
        """后空翻:蓄力 -> 抛物线转体 -> 接触地面后压缩回弹与星光冲击。
        轨迹按真实时间求值,收势从实际落地时刻开始。"""
        if self.core_profile():
            return False
        if self._seat_guard():
            return
        if self._land_first(self.start_flip):
            return
        if self.fy < self.ground_feet - 6:
            self.say("先落稳,再翻给你看~", 1.8)
            return
        self.state = "flip"
        self.flip_start = time.time()
        self.state_until = self.flip_start + 2.4
        self.flip_dir = random.choice((-1, 1))
        self.flip_launched = False
        self._flip_landed = False
        self._begin_tl(
            tracks={
                "squash": [(0, 1.0), (0.28, 0.74), (0.40, 1.06), (1.0, 1.02)],
                "lean":   [(0, 0.0), (0.28, -0.12), (0.45, 0.08), (1.4, 0.0)],
            },
            events=[
                (0.0, lambda p: p.say(random.choice(
                    ["看好啦——后空翻!", "我要飞咯!", "超——级——跳跃!"]), 1.2)),
                (0.3, lambda p: (setattr(p, "fvy", -680.0),
                                 setattr(p, "flip_launched", True),
                                 p.sfx.play("boing"))),
            ])

    @staticmethod
    def _flip_flight(age):
        """按实际经过时间求轨迹,低帧率也不会在空中先播放落地演出。"""
        duration = 2 * 680.0 / 1500.0
        air = max(0.0, age - .3)
        progress = min(1.0, air / duration)
        lift = max(0.0, 680 * air - .5 * 1500 * air * air)
        turn = progress * progress * (3 - 2 * progress)
        return lift, turn, age - (.3 + duration)

    def _advance_flip(self, now):
        age = now - self.flip_start
        self._play_timeline(age, self._tl_tracks, self._tl_events, self._tl_done)
        lift, turn, landed_for = self._flip_flight(age)
        self.fy = float(self.ground_feet) - lift
        self._spin_rot = -360 * self.flip_dir * turn if landed_for < 0 else 0.0
        self._afterimage_on = lift > 1
        if landed_for >= 0:
            if not self._flip_landed:
                self._flip_landed = True
                self.fvy = 0.0
                self.land_fx(1.0)
                self.star_burst(0, -0.08 * self.H, 10, sp=(80, 170), grav=170, size=(4, 9))
                self.sfx.play("levelup")
                self.say(random.choice(["稳稳落地!", "怎么样,帅吧!",
                                        "呼,转得我头都晕了~"]), 2.0)
            self.squash = self._track(landed_for, [(0, .74), (.16, 1.055),
                                                  (.33, .965), (.58, 1.0)])
            self.lean = self._track(landed_for, [(0, .06 * self.flip_dir),
                                                (.24, -.025 * self.flip_dir), (.58, 0)])
        if now > self.state_until:
            self.state = "idle"
            self.next_event = now + random.uniform(6, 12)

    def _wave_sands(self):
        """挥手表演的时之沙:每个挥拍从手边洒出 2~3 粒金色小星。
        (手的位置 ≈ +0.32W, -0.18H;粒子 y 是相对窗口中心的坐标)"""
        for _ in range(random.randint(2, 3)):
            self.add_part("sparkle",
                          random.uniform(0.24, 0.34) * self.W,
                          random.uniform(-0.26, -0.14) * self.H,
                          vx=random.uniform(-45, 5), vy=random.uniform(-50, -10),
                          life=random.uniform(0.5, 0.8),
                          size=random.uniform(2.5, 4.5), color=GOLD_L,
                          phase=random.uniform(0, 6.28))

    def start_wave(self):
        """挥手打招呼:身体随挥拍轻摆,抬起的手旁留一小段星光轨迹。
        每拍洒时之沙,收手时小齿轮飘起消散。"""
        if self.core_profile():
            return False
        if self._seat_guard(True):
            return
        if self._land_first(self.start_wave):
            return
        self.state = "wave"
        self.wave_start = time.time()
        self.state_until = self.wave_start + 2.6
        self._wave_until = self.state_until
        s = self.scale
        self._begin_tl(
            tracks={
                # 四拍挥手:身体朝抬手那侧压过去再回弹,每拍再踮一下脚。
                # 原来 lean 只有 ±0.065(约 4°),隔几帧连拍根本分不出她在动,
                # 看着就是站着说句话 —— 幅度提到接近打招呼该有的样子。
                "lean":   [(0, 0.0), (.3, -.115), (.65, .075), (.95, -.105),
                           (1.25, .07), (1.55, -.09), (1.85, .05),
                           (2.2, -.035), (2.6, 0)],
                "_bend":  [(0, 0), (.3, -.10), (.65, .075), (.95, -.09),
                           (1.25, .065), (1.55, -.07), (1.85, .04), (2.6, 0)],
                "_spin_lift": [(0, 0.0), (.3, 5.0 * s), (.54, 0.0), (.95, 5.0 * s),
                               (1.18, 0.0), (1.55, 4.0 * s), (1.78, 0.0),
                               (2.15, 3.0 * s), (2.42, 0.0)],
                "look_x": [(0, 0.0), (0.3, 0.5), (2.2, 0.5), (2.6, 0.0)],
                "squash": [(0, 1.0), (0.25, 0.94), (0.5, 1.0), (0.9, 0.965),
                           (1.12, 1.0), (1.5, 0.975), (1.72, 1.0)],
            },
            events=[
                # "hello" 不是 emotions.json 里的类别(是 greet),贴纸一直没出来 ——
                # 和 E3 同一类静默失效,现在由 test_pet 的"素材名防线"兜住
                (0.0, lambda p: (p.sfx.play("greet"),
                                 p.play_emotion("greet", 2.2),
                                 p.say(random.choice(
                                     ["你好呀~主人!", "嗨嗨~!",
                                      "欢迎回来~今天也请多指教!"]), 2.2))),
                (0.35, lambda p: p._wave_sands()),
                (0.95, lambda p: p._wave_sands()),
                (1.55, lambda p: p._wave_sands()),
                (2.15, lambda p: (p._wave_sands(),
                                  p.add_part("gear", 0.30 * p.W, -0.20 * p.H,
                                             vx=random.uniform(-20, 15), vy=-58,
                                             life=1.15, size=9.0, spin=5.5,
                                             phase=random.uniform(0, 6.28)))),
            ])

    def start_roll(self):
        """撒娇打滚:贴地慢滚一整圈(压扁 0.82 + 横向滚出一段距离),
        一路咯咯笑撒爱心,滚完晃两下站直。"""
        if self.core_profile():
            return False
        if self._seat_guard():
            return
        if self._land_first(self.start_roll):
            return
        self.state = "roll"
        self.roll_start = time.time()
        self.state_until = self.roll_start + 3.0
        self.roll_dir = random.choice((-1, 1))
        self.roll_home = self.x
        self.hop_t = 0.0
        self._begin_tl(
            tracks={
                "squash": [(0, 1.0), (.3, .88), (2.2, .88), (2.45, 1.045),
                           (2.7, .97), (3.0, 1.0)],
                "_spin_rot": [(0.3, 0.0), (2.2, -360.0 * self.roll_dir),
                              (3.0, -360.0 * self.roll_dir)],
                "lean": [(0, 0), (.3, .075 * self.roll_dir), (2.2, 0),
                         (2.45, -.05 * self.roll_dir), (2.7, .02 * self.roll_dir), (3, 0)],
            },
            events=[
                (0.0, lambda p: (p.sfx.play("voice_giggle"),
                                 p.say(random.choice(
                                     ["滚来滚去~", "地板好舒服呀~",
                                      "咯咯咯~别拦我!"]), 2.0))),
                (1.2, lambda p: p.hearts(0, -0.2 * p.H, 4)),
                (2.5, lambda p: p.add_part("dial", 0.0, -0.34 * p.H,
                                           life=1.0, size=14.0, spin=2.4,
                                           phase=random.uniform(0, 6.28))),
            ])

    def start_transform(self):
        """魔法变身:快转 720° + 魔法闪光,变身后进入 30 秒「星光形态」
        (身后柔光变大 + 脚阵常亮 + 被动星尘),一个有奖励感的招牌动作。"""
        if self.core_profile():
            return False
        if self._seat_guard():
            return
        if self._land_first(self.start_transform):
            return
        self.state = "transform"
        self.transform_start = time.time()
        self.state_until = self.transform_start + 2.8
        d = self.transform_dir = random.choice((-1, 1))
        self._begin_tl(
            tracks={
                "_spin_rot":  [(0, 0.0), (0.35, 0.0), (1.5, 720.0 * d), (2.8, 720.0 * d)],
                "squash":     [(0, 1.0), (0.35, 0.84), (1.5, 1.1), (1.7, 0.9),
                               (2.1, 1.0)],
                "_spin_lift": [(0, 0.0), (0.35, 0.0), (0.9, 26.0), (1.5, 0.0)],
            },
            events=[
                (0.0, lambda p: (p.sfx.play("voice_magic"),
                                 p.say("变身!星光形态!!", 1.6))),
                (0.35, lambda p: p.circles.append(
                    dict(born=time.time(), life=0.6, rx=1.0, kind="flash"))),
                (0.75, lambda p: p.circles.append(
                    dict(born=time.time(), life=0.6, rx=1.2, kind="cast"))),
                (1.5, lambda p: (setattr(p, "_starform_until", time.time() + 30.0),
                                 p.sfx.play("levelup"),
                                 p.star_burst(0, -0.12 * p.H, 12, sp=(90, 190),
                                              grav=140, size=(5, 10)),
                                 p.play_emotion("excited", 2.6),
                                 p.say(random.choice(
                                     ["星光满满~!", "变身完成!",
                                      "现在的小乔会发光哦✨"]), 2.2))),
            ])

    def start_chase(self):
        if self.core_profile():
            return False
        if self._seat_guard():
            return
        if self._land_first(self.start_chase):
            return
        if self.fy < self.ground_feet-6 or self.drag:
            return
        if self.state in ('sleep', 'yawn'):
            self.wake_if_sleep()
        mx, _ = cursor_pos()
        self.chase_cd = time.time() + 90
        self.state = "chase"
        self.state_until = time.time() + 6.0
        self.chase_started = time.time()
        self.walk_target = max(self.x_min, min(mx - self.W / 2, self.x_max))
        self.face = 1 if self.walk_target > self.x else -1
        self._chase_home = self.x
        distance = abs(self.walk_target-self.x)
        speed = SPEED*1.5*self.scale
        self._chase_duration = min(6.0, max(.8, distance/speed+.35))
        self._chase_travel = self.face*min(distance, speed*(self._chase_duration-.35))
        self.hop_t = self.lean_kick = 0.0
        self.say(random.choice(CHASE_LINES), 2.0)

    @staticmethod
    def _travel_progress(age, duration):
        """平滑速度的解析积分,起步 .3s、减速 .4s。"""
        t = max(0, min(age, duration))
        if t < .3:
            u = t/.3
            area, velocity = .3*(u**3-.5*u**4), u*u*(3-2*u)
        elif t <= duration-.4:
            area, velocity = t-.15, 1.0
        else:
            u = (t-(duration-.4))/.4
            area = duration-.55 + .4*(u-u**3+.5*u**4)
            velocity = 1-u*u*(3-2*u)
        return area/(duration-.35), velocity

    def _advance_chase(self, now):
        if self.state != 'chase':
            return
        age = now-self.chase_started
        progress, speed = self._travel_progress(age, self._chase_duration)
        self.x = max(self.x_min, min(self.x_max, self._chase_home+self._chase_travel*progress))
        self.lean = self.face*(.055*speed + .025*math.sin(age*10)*speed)
        self._bend = .04*self.face*math.sin(age*10)*speed
        self._spin_lift = 3*self.scale*math.sin(age*10)**2*speed
        if speed > .15 and now > self.next_trail:
            self.next_trail = now+.24
            self.add_part('sparkle', -self.face*.20*self.W,
                          self.FOOT_Y-self.H/2, life=.45, size=3*self.scale,
                          color=GOLD_L, vy=-12*self.scale)
        if age >= self._chase_duration:
            self.state = 'idle'
            self.lean = self._bend = self._spin_lift = 0
            self.next_event = now+random.uniform(5, 10)
            if abs(self.walk_target-self.x) <= 2*self.scale:
                self._start_micro_motion('arrive')
                self.play_emotion('proud', 1.4)
                self.hearts(0, -.20 * self.H, 2)
            else:
                self.play_emotion('tired', 1.6)
                self.say('呼呼…先在这里歇一会儿~', 2.0)

    @staticmethod
    def _drag_velocity(trail, now):
        recent = [s for s in trail if now-s[0] <= .12]
        if len(recent) < 2 or now-recent[-1][0] > .07:
            return 0.0, 0.0
        span = recent[-1][0]-recent[0][0]
        if span <= .01:
            return 0.0, 0.0
        return ((recent[-1][1]-recent[0][1])/span,
                (recent[-1][2]-recent[0][2])/span)

    def _advance_drag_pose(self, now, dt):
        vx, vy = self._drag_velocity(self._drag_trail, now) if self.drag and self.drag[4] else (0, 0)
        target = max(-.10, min(.10, -vx/(9000*self.scale)))
        self._drag_lean = approach(self._drag_lean, target, .25, dt)
        if math.hypot(vx, vy) > 350*self.scale and now > getattr(self, '_drag_fx_cd', 0):
            self._drag_fx_cd = now+.18
            self.add_part('sparkle', random.uniform(-.16, .16)*self.W,
                          .12*self.H, vx=-vx*.025, vy=12*self.scale,
                          life=.45, size=3*self.scale, color=GOLD_L)

    # 农历节日(2025~2030 已知公历日期;宁缺毋滥,过期年份自动失效)
    LUNAR_FESTIVALS = {
        "2025-01-29": ("春节快乐!恭喜恭喜,红包拿来~", "excited"),
        "2025-02-12": ("元宵节!要吃汤圆吗?", "happy"),
        "2025-05-31": ("端午安康!记得吃粽子哦~", "happy"),
        "2025-08-29": ("七夕呢…人家也有喜欢的人的~", "shy"),
        "2025-10-06": ("中秋快乐!今晚的月亮好圆~", "excited"),
        "2026-02-16": ("除夕啦!今晚要守岁吗?", "excited"),
        "2026-02-17": ("春节快乐!恭喜恭喜,红包拿来~", "excited"),
        "2026-03-03": ("元宵节!汤圆甜甜的~", "happy"),
        "2026-06-19": ("端午安康!粽子香香的~", "happy"),
        "2026-08-19": ("七夕呢…和主人一起过,好开心~", "shy"),
        "2026-09-25": ("今晚的月亮又大又圆~和小乔一起赏月吧!", "excited"),
        "2027-02-05": ("除夕啦!一年里的最后一天~", "excited"),
        "2027-02-06": ("春节快乐!新年新气象~", "excited"),
        "2027-08-08": ("七夕快乐!今晚的星星好多~", "shy"),
        "2027-09-15": ("中秋快乐!月亮好圆哦~", "excited"),
        "2028-01-25": ("除夕啦!", "excited"),
        "2028-01-26": ("春节快乐!新的一年也请多指教~", "excited"),
        "2028-08-26": ("七夕快乐!", "shy"),
        "2028-10-03": ("中秋快乐!", "excited"),
        "2029-02-12": ("除夕啦!要吃年夜饭哦~", "happy"),
        "2029-02-13": ("春节快乐!恭喜恭喜~", "excited"),
        "2029-08-16": ("七夕快乐!", "shy"),
        "2029-09-22": ("中秋快乐!", "excited"),
        "2030-02-02": ("除夕啦!", "excited"),
        "2030-02-03": ("春节快乐!", "excited"),
        "2030-08-05": ("七夕快乐!", "shy"),
        "2030-09-12": ("中秋快乐!", "excited"),
        "2025-10-29": ("重阳节~要记得陪陪家人哦", "happy"),
        "2026-10-18": ("重阳节~登高望远的日子", "happy"),
        "2027-10-08": ("重阳节!陪陪家里长辈吧", "happy"),
        "2028-10-26": ("重阳节~秋高气爽,适合出门走走", "happy"),
    }
    FESTIVALS = {
        "01-01": ("新年快乐!今年也请多指教哦~", "excited"),
        "02-14": ("情人节…嘿嘿,有人会想到我吗?", "shy"),
        "05-01": ("劳动节!主人辛苦了,休息一下嘛~", "lazy"),
        "06-01": ("儿童节!人家永远都是小朋友哦~", "excited"),
        "10-01": ("国庆快乐!长假要好好休息哦~", "excited"),
        "10-24": ("1024!程序员节快乐,主人的节日~", "proud"),
        "10-31": ("万圣节!不给糖就捣蛋~", "excited"),
        "12-24": ("平安夜,要吃苹果吗?", "happy"),
        "12-25": ("圣诞快乐!今天想收到什么礼物呢~", "excited"),
    }

    WEEKEND_EVE = ("周五晚上~明天就是周末啦,开心!", "excited")

    def greet_period(self):
        """按时段问候,每个时段只说一次。节日优先于时段。"""
        if self.core_profile():
            return False
        today = time.strftime("%Y-%m-%d")
        md = time.strftime("%m-%d")
        if getattr(self, "_fest_done", None) != today:
            anniv_d = self.settings.get("anniv_date")
            if anniv_d and md == anniv_d:          # 主人自己设的纪念日
                self._fest_done = today
                name = self.settings.get("anniv_name", "纪念日")
                self.say(f"今天是{name}!小乔也一起庆祝哦~", 3.8)
                self.play_emotion("excited", 3.2)
                self.hop(0.7)
                self._festive_burst(big=True)
                return True
            if today in self.LUNAR_FESTIVALS:      # 农历节日(春节/中秋等)
                self._fest_done = today
                line, emo = self.LUNAR_FESTIVALS[today]
                self.say(line, 4.0)
                self.play_emotion(emo, 3.2)
                self.hop(0.7)
                self.confetti_burst(0, -0.1 * self.H, 30)
                # 盛大节日额外:从她四周升起金色烟花
                if md in ("01-01", "10-01") or today in ("2026-02-17", "2026-09-25"):
                    self._firework_burst()
                return True
            if md in self.FESTIVALS:               # 公历节日
                self._fest_done = today
                line, emo = self.FESTIVALS[md]
                self.say(line, 3.6)
                self.play_emotion(emo, 3.0)
                self.hop(0.6)
                self._festive_burst(big=(md in ("12-25",)))
                return True
        h = time.localtime().tm_hour
        period = ("night" if h < 5 else "morning" if h < 11
                  else "noon" if h < 14 else "evening" if h < 22 else "night")
        if period == self._period_greeted:
            return False
        self._period_greeted = period
        # 周五晚上:周末前夜特别版
        if period == "evening" and time.strftime("%a") == "Fri":
            self.sfx.play("greet")
            self.say("周五晚上~明天就是周末啦,开心!", 3.2)
            self.play_emotion("excited", 2.6)
            self.hop(0.6)
            return True
        lines, emo = PERIOD_GREET[period]
        self.sfx.play("greet")
        self.say(random.choice(lines), 3.0)
        self.play_emotion(emo, 2.4)
        self.hop(0.5)
        # 早晨问候带上天气(晨报);没设城市就只问早
        if period == "morning" and self.city:
            self.root.after(3500, self.ask_weather)
        return True

    def wake_up(self):
        if getattr(self, "_nap_on_swing", False) and self._swing:
            # 秋千打盹:复用同一唤醒出口,保持场景与 swing(未来入口不拆场景)
            self._wake_from_nap()
            self.sfx.play("wake")
            self.state_until = time.time() + 3
            self.play_emotion("excited", 2.2)
            self.say("呼啊…睡醒了", 2.2)
            return
        self.state = "idle"
        self._nap_on_swing = False
        self.parts = [p for p in self.parts if p["kind"] != "zzz"]
        self._start_micro_motion("wake")
        self.sfx.play("wake")
        self.state_until = time.time() + 3
        self.play_emotion("excited", 2.2)
        self.say("呼啊…睡醒了", 2.2)
        # 刚醒:头顶的时间还没对上——表盘虚影转半拍化开,带一小撮时之沙
        # (和入睡的 zzz 呼应:睡有 zzz,醒有齿轮)
        self.add_part("dial", 0.0, -0.32 * self.H,
                      life=0.9, size=12.5, spin=2.2, phase=random.uniform(0, 6.28))
        for _ in range(4):
            self.add_part("sparkle",
                          random.uniform(-0.14, 0.14) * self.W,
                          random.uniform(-0.26, -0.16) * self.H,
                          vy=random.uniform(-45, -15),
                          life=random.uniform(0.5, 0.8),
                          size=random.uniform(2.5, 4.5), color=GOLD_L,
                          phase=random.uniform(0, 6.28))
        # 抬头回神后再伸懒腰;新一轮互动或睡眠会使这次预约失效。
        token, interaction = self.state_until, self.last_interact
        self.root.after(2400, lambda: self._finish_wake(token, interaction))

    def _finish_wake(self, token, interaction):
        motion = self._micro_motion
        if (self.state == "idle" and self.state_until == token
                and self.last_interact == interaction and self._micro_allowed()
                and (not motion or motion[0] == "wake")):
            self.start_stretch()

    def _wake_from_nap(self):
        """秋千打盹唤醒:恢复摆幅与阻尼,清残留 zzz,眼睛睁开,平滑回到摆动。"""
        if not getattr(self, "_nap_on_swing", False):
            return False
        self._nap_on_swing = False
        pend = (self._swing or {}).get("pend") if self._swing else None
        if pend:
            pend.idle_amp = 0.085
            pend.damping = 0.30
        self.parts = [q for q in getattr(self, "parts", [])
                      if q.get("kind") != "zzz"]   # 统一清残留 zzz
        self.last_interact = time.time()
        return True

    def go_sleep(self):
        if self.singing:
            return
        if self.state in ("sleep", "yawn"):
            return
        if getattr(self, "_nap_on_swing", False):
            return              # 已经在秋千上打盹了,不重复入睡
        if self.state == "swing" and self._swing and not self.drag:
            # 新坐姿:入睡留在秋千上 —— 闭眼、摆幅逐渐减缓,
            # 场景/绳手/臀垫接触全部不变(状态保持 swing,art_on 不失效)
            self._nap_on_swing = True
            self._cancel_ball()
            self.say("哈——啊……", 1.4)
            pend = self._swing.get("pend")
            if pend:
                pend.idle_amp = 0.012       # 摆幅逐渐减缓(入睡)
                pend.damping = 0.85
            for i in range(2):
                self.add_part("zzz", (0.16 + 0.09 * i) * self.W,
                              -0.36 * self.H + i * 12,
                              vy=-10, life=1.7, size=8 + 2 * i,
                              phase=random.uniform(0, 6.28))
            return
        if self._land_first(self.go_sleep):
            return          # 地面入睡路径(与旧素材一致)
        self._cancel_ball()
        # 先打哈欠,1.6 秒后再滑入睡眠(音效/贴纸在转换点出)
        self.state = "yawn"
        self.hop_t = self.lean_kick = 0.0
        self.state_until = time.time() + 1.6
        self.say("哈——啊……", 1.4)
        # 困意先飘出来:一两个小 zzz 前奏(比睡着时的更小更慢)
        for i in range(2):
            self.add_part("zzz", (0.16 + 0.09 * i) * self.W,
                          -0.36 * self.H + i * 12,
                          vy=-10, life=1.7, size=8 + 2 * i,
                          phase=random.uniform(0, 6.28))

    def cast_magic(self, style=None):
        if self.core_profile():
            return False
        self.last_interact = time.time()
        if self.state in ("sleep", "yawn"):
            self.wake_if_sleep()
        if self.state in ("magic", "eat"):
            return
        if self.state in ("fly", "fall"):
            self.say("落地再变啦!", 1.6)
            return
        if self.state == "swing" and self._swing and not self.drag:
            self._wake_from_nap()   # 打盹中互动:统一唤醒(清 zzz/恢复摆幅)
            # 坐姿施法:不拆场景 —— 法阵与星爆画在原画路径上
            now_ = time.time()
            for k_ in range(2):
                self.circles.append(dict(born=now_ + k_ * 0.12, life=0.6,
                                         rx=1.0, kind="cast"))
            self.star_burst(0, -0.25 * self.H, 10)
            self.sfx.play("magic")
            self.say("变——!", 1.6)
            return
        if style is None:
            style = getattr(self, "magic_style", 0)
        self.state = "magic"
        self.magic_start = time.time()
        self._magic_style_cur = style
        # 原来这里 style==1 分支设好的 state_until 和台词,被下面几行
        # 无条件覆盖了一遍,连 magic_start 都重设了第二次 ——
        # 全屏那几发粒子是按第一次的 magic_start 排的错峰,于是全乱。
        # 现在合并成一次赋值。
        dur = 2.4 if style == 1 else 2.6
        self.state_until = self.magic_start + dur
        self.next_fountain = self.magic_start + 0.05
        self.circles.append(dict(born=self.magic_start, life=dur,
                                 rx=1.0, kind="cast"))
        if style == 1:
            self._magic_fullscreen_burst()
        # 人声获准播放(没撞上 5 秒限频)时,魔法闪烁才跟着同拍出
        if self.sfx.play("voice_magic"):
            self.sfx.play("magic", fx=True)
        self.play_emotion(random.choice(["excited", "happy"]), 2.2)
        self.say("✨ 时间魔法 · 全屏降临!" if style == 1
                 else random.choice(CAST_LINES), 2.2)

    def _magic_fullscreen_burst(self):
        """R114 全屏炫酷版:3 圈错峰爆裂 + 4 角回旋大光球。"""
        if self.core_profile():
            return False
        cx = self.W / 2
        for i, (delay, color, n) in enumerate([
            (0.00, (255, 220, 150), 12),
            (0.08, (255, 200, 220), 10),
            (0.16, (180, 220, 255), 8),
        ]):
            # 每圈的出生时间原来算好了却没传进去,三圈其实同一瞬间炸开,
            # 文档说的"错峰"从没生效过
            t = self.magic_start + delay
            for j in range(n):
                a = j * (2 * math.pi / n) + i * 0.4
                self.add_part("magic_burst", cx + math.cos(a) * 60,
                              -0.2 * self.H + math.sin(a) * 30,
                              vx=0, vy=0, life=1.0 + i * 0.2,
                              size=20 + i * 8, color=color, phase=a, born=t)
        for k in range(4):
            x_off = 0.42 * self.W * (1 if k % 2 == 0 else -1)
            y_off = 0.4 * self.H * (1 if k < 2 else -1)
            self.add_part("magic_corner", x_off, y_off,
                          vx=-x_off * 0.6 + random.uniform(-30, 30),
                          vy=-y_off * 0.6 + random.uniform(-30, 30),
                          life=1.2, size=18 + random.uniform(0, 6),
                          color=random.choice([(255, 240, 200), (255, 220, 240),
                                               (200, 240, 255), (200, 255, 200)]),
                          phase=random.uniform(0, 6.28))

    def tell_time(self):
        self.last_interact = time.time()
        if self.state == "sleep":
            self.wake_if_sleep()
        hm = time.strftime("%H:%M")
        self.sfx.play("tick")
        self.say(f"现在是 {hm} 哦~", 2.8)
        self.play_emotion("curious", 2.0)

    def eat_candy(self):
        self.last_interact = time.time()
        if self.state in ("sleep", "yawn"):
            self.wake_if_sleep()
        if self.state in ("magic", "eat"):
            return
        if self.state in ("fly", "fall"):
            self.say("等等,我还在半空呢!", 1.6)
            return
        if self.state == "swing" and self._swing and not self.drag:
            self._wake_from_nap()   # 打盹中互动:统一唤醒(清 zzz/恢复摆幅)
            # 坐姿吃糖:计数/音效只触发一次,爱心反馈画在原画路径上
            self.sfx.play("voice_yum")
            self._count_today("candy")
            self.hearts(0, -0.35 * self.H, 3)
            self.say("谢谢招待~", 1.8)
            return
        self.sfx.play("voice_yum")
        self._count_today("candy")
        self.state = "eat"
        self.hop_t = self.lean_kick = 0.0
        self.eat_start = time.time()
        self.state_until = self.eat_start + 2.2
        self._eat_beats = set()

    @staticmethod
    def _candy_path(age, mouth=(.487, .55)):
        """精灵内归一化坐标与可见比例;入口后彻底消失。终点 = 嘴(随立绘配置)。"""
        u = max(0.0, min(1.0, age / 1.1))
        u = u * u * (3 - 2 * u)
        x = (1-u)**2 * .90 + 2*(1-u)*u * .64 + u*u * mouth[0]
        y = (1-u)**2 * .70 + 2*(1-u)*u * .43 + u*u * mouth[1]
        size = max(0.0, min(1.0, age / .18, (1.1-age) / .24))
        return x, y, size

    def _eat_pose(self, age):
        # 迎接糖果→三次轻咀嚼→满足地点头;终点回到中性姿势。
        squash = self._track(age, [(0, 1), (.35, .97), (.85, 1.035),
            (1.1, 1), (1.24, .96), (1.38, 1.04), (1.52, .962),
            (1.66, 1.035), (1.8, .965), (1.96, 1.04), (2.2, 1)])
        bend = self._track(age, [(0, 0), (.6, .10), (1.1, .06),
                                (1.65, -.035), (1.95, .04), (2.2, 0)])
        return squash, bend

    def _yawn_pose(self, age):
        return (self._track(age, [(0, 1), (.35, .975), (.85, 1.075),
                                 (1.1, 1.055), (1.6, 1)]),
                self._track(age, [(0, 0), (.4, .025), (.95, .055),
                                 (1.6, -.06)]))

    @staticmethod
    def _sleep_shade(sprite, amount):
        shade = max(0, min(255, int(amount)))
        layer = Image.new("RGBA", sprite.size, (40, 50, 110, 0))
        layer.putalpha(sprite.getchannel("A").point(lambda a: a * shade // 255))
        return layer

    def star_rain(self):
        if self.core_profile():
            return False
        self.last_interact = time.time()
        if self.state == "sleep":
            self.wake_if_sleep()
        self.sfx.play("sparkle")
        self.star_burst(0, -0.1 * self.H, 16)
        self.hop(0.5)
        self.say("接住星星!", 2.0)
        # 小玩法:5 颗金星星可以点击接住(+2 星光/颗),落走就没了
        self._catch_total = 5
        self._catch_got = 0
        self._catch_t0 = time.time()
        for i in range(5):
            a = -math.pi / 2 + random.uniform(-0.8, 0.8)
            v = random.uniform(90, 190)
            self.add_part("cstar", random.uniform(-0.2, 0.2) * self.W,
                          -0.12 * self.H,
                          vx=math.cos(a) * v, vy=math.sin(a) * v,
                          life=random.uniform(5.5, 7.0), size=random.uniform(9, 12),
                          color=GOLD, phase=random.uniform(0, 6.28),
                          grav=30, spin=random.uniform(-2, 2))

    def sing(self):
        if self.core_profile():
            return False
        self.last_interact = time.time()
        if self.singing:
            self.stop_sing()
            self.say("唱完啦~", 2.0)
            return
        if self.state == "sleep":
            self.wake_if_sleep()
        song = os.path.join(ASSETS, "song.mp3")
        if not os.path.exists(song):
            self.say("我还没学会唱歌呢…", 2.2)
            return
        # 交给音频线程去开设备和播放;声音总开关关着时只做动作不出声
        self._sing_audio = self.sfx.play_song(song)
        self.singing = True
        self._sing_poll = 0
        self._sing_started = time.time()
        self.next_note = 0
        if self.state in ("walk", "fall", "yawn"):
            # yawn 也要一并取消:state_until 下面会被覆写成 +40 秒,不然
            # 哈欠分支到点会无条件转入睡眠 —— 歌还在放,人已经睡着
            self.state = "idle"
        self.state_until = time.time() + 40
        self.play_emotion("excited", 2.2)
        self.say(random.choice(
            ["♪~我来唱歌啦,认真听哦~", "♫ 今天想听什么歌呢~",
             "♪ 唱歌要开始了,鼓掌鼓掌!"]), 3.0)

    def stop_sing(self):
        self.singing = False
        self._sing_audio = False
        self.sfx.stop_song()

    # ==================== 聊天(AI) ====================
    def open_chat(self):
        self.close_action_card()
        if self.core_profile():
            self.wake_if_sleep()
        self.last_interact = time.time()
        self.sfx.play("pop")
        if self.chatbox is not None:
            try:
                if self.chatbox.win.winfo_exists():
                    self.chatbox.win.lift()
                    self.chatbox.focus_entry()
                    return
            except Exception:
                pass
        self.chatbox = ChatBox(self)

    def random_emotion(self):
        cats = [c for c in self.emotions if c not in ("sleep",)]
        self.play_emotion(random.choice(cats), 2.6)

    def _log_chat(self, role, text, emotion=""):
        """把一条对话写进可见记录并落盘。role: user / qiao"""
        if not text:
            return
        if role == "user":
            self._count_today("chat")
        self.chat_log.append({"role": role, "text": text, "t": time.time(),
                              "emotion": emotion})
        self.chat_log = self.chat_log[-200:]
        try:
            # 先写 .tmp 再原子替换:进程死在写入中不会留下半截 JSON,
            # 那批历史就全丢了(和 save_settings 同一个坑)
            tmp = self.chat_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.chat_log, f, ensure_ascii=False)
            os.replace(tmp, self.chat_path)
        except Exception:
            # 不能静默:写失败意味着这段对话重启就没了(去重记日志,不刷屏)
            self._log_exc("chat_save")

    def clear_chat(self):
        self.chat_log = []
        self.history = []
        try:
            if os.path.exists(self.chat_path):
                os.remove(self.chat_path)
        except Exception:
            pass
        cb = self.chatbox
        if cb is not None:
            try:
                if cb.win.winfo_exists():
                    cb.log.configure(state="normal")
                    cb.log.delete("1.0", "end")
                    cb.log.configure(state="disabled")
                    cb.log_hint("● 记录已清空")
            except Exception:
                pass

    def _dialog_shell(self, title):
        """所有主题对话框的骨架:置顶、暗紫底、居中。返回 (win, u, pad)。"""
        self.close_action_card()
        win = tk.Toplevel(self.root)
        win.title(title)
        win.attributes("-topmost", True)
        win.resizable(False, False)
        win.configure(bg=UI_PANEL)
        u = max(1.0, self.sh / 1080.0)
        return win, u, int(18 * u)

    def _center_and_wait(self, win, focus=None):
        """居中、抓焦点、阻塞到窗口关闭。

        阻塞语义刻意和 simpledialog 保持一致(grab_set + wait_window):
        5 个调用点都是"问完一个再问下一个"的直线写法,改成回调式就得全部
        重写。阻塞期间桌宠不动 —— 但原来的系统对话框也是这样,没有退步。
        """
        win.update_idletasks()
        win.geometry(f"+{int(self.sw / 2 - win.winfo_width() / 2)}"
                     f"+{int(self.sh / 2 - win.winfo_height() / 2)}")
        if focus is not None:
            focus.focus_set()
        try:
            win.grab_set()
        except tk.TclError:
            pass                    # 已经有别的窗口抓着焦点,不值得为此炸掉
        self.root.wait_window(win)

    def themed_input(self, title, prompt, *, initial="", ok="好", cancel="算了",
                     validate=None):
        """暗紫主题的单行输入框,替掉 simpledialog.askstring 那五个白框。

        返回输入的字符串;取消返回 None(注意空串和取消是两回事,设置城市
        要靠这个区分"清空"和"没改")。

        validate(text) 通过返回 None,不通过返回一句话 —— 提示直接标在框
        里,窗口不关。原来是先关窗、她再吐槽一句"日期没看懂",用户根本看
        不到自己填错在哪。
        """
        win, u, pad = self._dialog_shell(title)
        F, FB = ui_font(TYPE_BODY, u), ui_font(TYPE_BODY, u, bold=True)
        tk.Label(win, text=prompt, bg=UI_PANEL, fg=UI_TEXT, font=FB,
                 wraplength=int(430 * u), justify="left").pack(
                     padx=pad, pady=(int(16 * u), int(6 * u)), anchor="w")
        ent = tk.Entry(win, width=34, font=F, bg=UI_FIELD, fg=UI_TEXT,
                       relief="flat", insertbackground=UI_TEXT)
        ent.pack(padx=pad, pady=int(10 * u), fill="x")
        if initial:
            ent.insert(0, initial)
        msg = tk.Label(win, text="", bg=UI_PANEL, fg=UI_WARN, font=F,
                       wraplength=int(430 * u), justify="left")
        msg.pack(padx=pad, anchor="w")
        got = {}

        def done():
            txt = ent.get().strip()
            if validate is not None:
                err = validate(txt)
                if err:
                    msg.configure(text=err)
                    return
            got["v"] = txt
            win.destroy()

        bar = tk.Frame(win, bg=UI_PANEL)
        bar.pack(padx=pad, pady=int(14 * u), fill="x")
        tk.Button(bar, text=cancel, command=win.destroy, relief="flat",
                  bg=UI_BTN, fg=UI_TEXT_DIM, font=F, cursor="hand2").pack(
                      side="right", padx=(int(8 * u), 0))
        tk.Button(bar, text=ok, command=done, relief="flat",
                  bg=UI_ACCENT, fg=UI_GOLD, font=FB, cursor="hand2").pack(
                      side="right")
        ent.bind("<Return>", lambda e: done())
        win.bind("<Escape>", lambda e: win.destroy())
        self._center_and_wait(win, ent)
        return got.get("v")

    def themed_confirm(self, title, text, *, yes="好", no="算了"):
        """替掉 messagebox.askyesno,风格与 themed_input 一致。返回 bool。"""
        win, u, pad = self._dialog_shell(title)
        F, FB = ui_font(TYPE_BODY, u), ui_font(TYPE_BODY, u, bold=True)
        tk.Label(win, text=text, bg=UI_PANEL, fg=UI_TEXT, font=F,
                 wraplength=int(430 * u), justify="left").pack(
                     padx=pad, pady=(int(16 * u), int(6 * u)), anchor="w")
        got = {}

        def pick(v):
            got["v"] = v
            win.destroy()

        bar = tk.Frame(win, bg=UI_PANEL)
        bar.pack(padx=pad, pady=int(14 * u), fill="x")
        tk.Button(bar, text=no, command=lambda: pick(False), relief="flat",
                  bg=UI_BTN, fg=UI_TEXT_DIM, font=F, cursor="hand2").pack(
                      side="right", padx=(int(8 * u), 0))
        tk.Button(bar, text=yes, command=lambda: pick(True), relief="flat",
                  bg=UI_ACCENT, fg=UI_GOLD, font=FB, cursor="hand2").pack(
                      side="right")
        win.bind("<Escape>", lambda e: win.destroy())
        self._center_and_wait(win)
        return bool(got.get("v"))

    def setup_api_key(self, first_run=False):
        """填写 Gemini API 密钥。首次启动没有密钥时自动弹出。

        发布版不预置任何密钥 —— 每个人填自己的,免费额度也是各算各的。
        """
        win = tk.Toplevel(self.root)
        win.title("小乔 · 设置 AI 密钥")
        win.attributes("-topmost", True)
        win.resizable(False, False)
        win.configure(bg=UI_PANEL)
        u = max(1.0, self.sh / 1080.0)
        F = ("Microsoft YaHei UI", -int(14 * u))
        FB = ("Microsoft YaHei UI", -int(14 * u), "bold")

        tip = ("初次见面~ 想让我能聊天,需要一个免费的 Gemini API 密钥。"
               if first_run else "在这里更换 AI 密钥。")
        tk.Label(win, text=tip, bg=UI_PANEL, fg=UI_TEXT, font=FB,
                 wraplength=int(430 * u), justify="left").pack(
                     padx=int(18 * u), pady=(int(16 * u), int(6 * u)), anchor="w")
        tk.Label(win,
                 text="获取步骤:打开 aistudio.google.com/apikey → 登录 Google 账号\n"
                      "→ 点 Create API key → 复制那串以 AIza 开头的字符,粘到下面。\n"
                      "不填也能用,只是我不会聊天,其他动作和互动都正常。",
                 bg=UI_PANEL, fg=UI_TEXT_DIM, font=F, justify="left",
                 wraplength=int(430 * u)).pack(padx=int(18 * u), anchor="w")

        ent = tk.Entry(win, width=44, font=F, bg=UI_FIELD, fg=UI_TEXT,
                       relief="flat", insertbackground=UI_TEXT)
        ent.pack(padx=int(18 * u), pady=int(12 * u), fill="x")
        cur = self.brain.cfg.get("api_key") if self.brain else ""
        if cur:
            ent.insert(0, cur)

        msg = tk.Label(win, text="", bg=UI_PANEL, fg=UI_WARN, font=F)
        msg.pack(padx=int(18 * u), anchor="w")

        def open_page():
            webbrowser.open("https://aistudio.google.com/apikey")

        def save():
            key = ent.get().strip()
            if key and not key.startswith("AIza"):
                msg.configure(text="这串不太像 Gemini 密钥(通常以 AIza 开头),确认一下?")
                return
            if self.brain and self.brain.save_key(key):
                win.destroy()
                if key:
                    self.say("好耶,连上啦!现在可以找我聊天咯~", 3.0)
                    self.play_emotion("excited", 2.4)
                else:
                    self.say("好,那先这样~", 2.4)
            else:
                msg.configure(text="保存失败,检查一下 assets 目录能不能写?")

        bar = tk.Frame(win, bg=UI_PANEL)
        bar.pack(padx=int(18 * u), pady=int(14 * u), fill="x")
        tk.Button(bar, text="去申请密钥", command=open_page, relief="flat",
                  bg=UI_BTN, fg=UI_TEXT, font=F, cursor="hand2").pack(side="left")
        tk.Button(bar, text="以后再说", command=win.destroy, relief="flat",
                  bg=UI_BTN, fg=UI_TEXT_DIM, font=F, cursor="hand2").pack(
                      side="right", padx=(int(8 * u), 0))
        tk.Button(bar, text="保存", command=save, relief="flat",
                  bg=UI_ACCENT, fg=UI_GOLD, font=FB, cursor="hand2").pack(side="right")
        ent.bind("<Return>", lambda e: save())
        win.update_idletasks()
        win.geometry(f"+{int(self.sw / 2 - win.winfo_width() / 2)}"
                     f"+{int(self.sh / 2 - win.winfo_height() / 2)}")
        ent.focus_set()

    def run_agent(self, intent):
        """执行指令(打开/关闭/卸载/搜索)。本地规则和 AI 都走这里。"""
        if self.core_profile():
            return False
        # AI 触发时,主人原话已经在 ask_ai 里记过了,别重复记一条
        if not intent.get("_from_ai"):
            self._log_chat("user", intent["raw"])
        self.last_interact = time.time()
        if self.state == "sleep":
            self.wake_up()
        # 提醒/剪贴板/找文件/看屏幕/番茄钟/翻译需要定时器、线程、Tk 或截屏,
        # pet.py 自己处理,不走 agent.execute(那边只做纯系统操作)
        kind = intent.get("kind")
        if kind == "remind":
            self._schedule_reminder(intent.get("minutes"), intent.get("target"))
            return
        if kind == "clipboard":
            self.summarize_clipboard()
            return
        if kind == "translate":
            self.translate_clipboard()
            return
        if kind == "find_file":
            self._start_file_search(intent.get("target") or "")
            return
        if kind == "screen":
            self.look_screen(intent.get("target") or "")
            return
        if kind == "pomo":
            self.start_pomodoro(intent.get("minutes") or 25)
            return
        if kind == "weather":
            self.ask_weather()
            return
        # open/close/搜索要起 PowerShell 子进程(秒级),放后台线程跑,
        # 不然动画会僵住;结果回主线程再处理(弹窗/碰 Tk 控件都得在主线程)
        def work():
            try:
                res = agent.execute(intent)
            except Exception as e:
                res = (False, f"出错了:{str(e)[:60]}")
            self.mainq.put(lambda: self._finish_agent(res))

        self._run_bg(work)

    def _finish_agent(self, res):
        # 卸载是不可逆的,必须人点头才继续
        if self.core_profile():
            return False
        if isinstance(res, tuple) and res[0] == "confirm":
            name, cmd = res[1]
            self._reply(f"要卸载「{name}」吗?我把确认框调出来咯", "curious")
            # 原来用 messagebox.askyesno,测试时被不明事件答了「是」,把哔哩哔哩
            # 真卸掉了;换成项目自己的主题确认框,和其他对话框一致
            if self.themed_confirm("小乔 · 确认卸载",
                                   f"真的要卸载「{name}」吗?\n\n"
                                   "我会在资源管理器里把它的卸载程序指出来,\n"
                                   "你双击它才会真的开始卸载。",
                                   yes="指给我看", no="算了"):
                ok = agent.run_uninstaller(cmd)
                self._reply("我把卸载程序给你指出来啦,双击它就行~" if ok
                            else "找不到卸载程序…", "roger" if ok else "pouty")
            else:
                self._reply("好,那就不动它~", "mild")
            return

        ok, msg = res
        self._reply(msg, "proud" if ok else "pouty")

    def _reply(self, msg, emotion=None):
        """统一出口:气泡 + 聊天框 + 记录 + (可选)开口念出来。"""
        # 时长随文本长度自适应:长回复按阅读速度给足时间,别让 200 字 5 秒蒸发
        self.say(msg, max(4.0, min(14.0, 2.5 + len(msg) * 0.14)), keep=True)
        self._log_chat("qiao", msg, emotion or "")
        self._speak(msg)
        if emotion:
            self.play_emotion(emotion, 2.4)
        cb = self.chatbox
        if cb is not None:
            try:
                if cb.win.winfo_exists():
                    cb.log_reply(msg)
            except Exception:
                pass

    # 聊天直通互动:关键词 -> 动作(顺序即优先级,先命中先执行)
    PET_ACTIONS = (
        (("摸摸", "摸头", "摸摸头"), "pet_head"),
        (("挠", "痒"), "tickle_body"),
        (("转圈", "转个圈"), "start_twirl"),
        (("跳个舞", "跳舞"), "start_dance"),
        (("后空翻", "空翻"), "start_flip"),
        (("挥手", "打招呼", "你好呀"), "start_wave"),
        (("打滚", "滚一滚"), "start_roll"),
        (("变身", "星光形态"), "start_transform"),
        (("冥想", "飘起来", "浮空"), "start_meditate"),
        # 秋千只认明确的上/下指令:她默认就住在秋千上,原来裸"秋千"映射到
        # toggle,随口一句"你的秋千真好看"就被吞掉、还把她叫了下来
        (("下秋千", "从秋千上下来"), "dismount_swing"),
        (("上秋千", "荡秋千", "坐秋千"), "mount_swing"),
        (("唱首歌", "唱歌", "唱一首"), "sing"),
        (("撒星星", "星星雨", "接星星"), "star_rain"),
        (("施魔法", "变魔法", "时间魔法"), "cast_magic"),
        (("睡一觉", "睡个觉", "去睡觉", "睡吧"), "go_sleep"),
        (("猜数字", "玩猜数字"), "start_guess"),
        (("不玩了", "不猜了"), "stop_guess"),
        (("运势", "占卜"), "tell_fortune"),
    )

    SEASON_SAY = {
        "spring": ["春天来了,万物都醒了呢~", "花花开的时候最好看了~",
                   "闻到花香了吗?好舒服~", "小草在探头,世界在醒来",
                   "春天最适合在窗边睡午觉了~"],
        "summer": ["夏天要吃冰的才爽快~", "知了在叫,好热闹呀",
                   "萤火虫点灯啦,好浪漫~", "热得想泡在水里…",
                   "夏天的风带着阳光的味道"],
        "autumn": ["秋天的风好舒服~", "树叶都在跳舞呢", "秋高气爽,适合施魔法~",
                   "桂花开了,好香呀~", "落叶接住了,你看!"] if False else
                  ["秋天的风好舒服~", "树叶都在跳舞呢", "秋高气爽,适合施魔法~",
                   "落叶接住了,你看!", "天凉啦,主人注意保暖哦~"],
        "winter": ["下雪的话,想堆个雪人~", "呼,冬天记得保暖哦",
                   "雪花飘下来了,接住它!", "窗上结冰花了诶~",
                   "热茶时间到了~"],
    }

    FORTUNES = [
        ("大吉", "今天做什么都顺,适合开新坑!", "proud"),
        ("中吉", "平稳安好的一天,偷偷摸鱼也没关系哦~", "happy"),
        ("小吉", "会有小小的惊喜,注意查收!", "excited"),
        ("吉", "普通但温暖的一天,像晒过太阳的被子~", "happy"),
        ("末吉", "有点小波折,不过有我陪着呀", "curious"),
    ]

    def tell_fortune(self):
        """今日运势:按日期播种,同一天所有人问都是同一个结果。"""
        if self.core_profile():
            return False
        seed = int(time.strftime("%Y%m%d"))
        luck, line, emo = random.Random(seed ^ 0x5A0).choice(self.FORTUNES)
        # 节日特典:节日/纪念日当天占卜必定大吉(系统联动)
        md = time.strftime("%m-%d")
        today = time.strftime("%Y-%m-%d")
        fest = (md in self.FESTIVALS or today in self.LUNAR_FESTIVALS
                or self.settings.get("anniv_date") == md)
        if fest and luck != "大吉":
            luck, line, emo = "大吉", "节日特典:节日当天注定大吉!", "excited"
        star_line = ""
        if self.star >= 80:
            star_line = " (星光这么足,一定是大吉!)"
        self._reply(f"今日运势【{luck}】:{line}{star_line}", emo)

    def trigger_birthday(self):
        """生日彩蛋:聊天说生日快乐时,根据系统日期判断真假。"""
        if self.core_profile():
            return False
        import datetime as _dt
        real_md = _dt.datetime.now().strftime("%m-%d")
        if real_md == self.settings.get("birthday", ""):
            self.say("谢谢你~今天是我的大日子!该好好庆祝一下!", 3.5)
            self.play_emotion("excited", 3.0)
            self._festive_burst(big=True)
            self.add_affection(3)
        else:
            self.say("嘿嘿,谢谢~我的生日要等明年啦,期待一下哦!", 2.8)
            self.play_emotion("happy", 2.4)
            self.hop(0.4)
            self.add_affection(0.5)

    # ---------------- 时之魔女演出(时停/回溯) ----------------
    def _tfx(self):
        """时停/回溯共用的时间演出层。首次使用时构建(约 13MB 精灵,
        和 _warp_cache 同量级;实测构建 70~100ms,藏在该动作的开场闪光里)。

        不放进 _warm_fx 预热:那样没用过时停的人也要常驻这 13MB。

        这里原来写的是 self.ss —— Pet 上没有这个属性(超采样倍数是模块常量
        SS),于是右键菜单的「时停」「时间回溯」一点就抛 AttributeError。栈会被
        Tk 打进 pet_error.log,但界面上什么都不发生,两个菜单项一直是坏的
        (现在回调出错会由 _on_tk_error 让她说一句)。"""
        if getattr(self, "tfx", None) is None:
            self.tfx = fx.TimeFX(self.scale, SS)
        return self.tfx

    def _prewarm_tfx(self):
        """完整菜单一打开就在后台把时停/回溯精灵建好。

        这两项只能从完整菜单里点到,人从打开菜单到点下去至少要半秒,而构建
        只要 70~180ms(卡顿审计里首次点时停同步卡了 184ms)。没打开过菜单的
        人照旧不占这 13MB。后台建完只在缩放没变时才挂上,和 _tfx() 同时建
        也无妨:谁先挂上用谁的。"""
        if self.core_profile():
            return False
        if getattr(self, "tfx", None) is not None or getattr(self, "_tfx_warming", False):
            return
        self._tfx_warming = True
        scale = self.scale

        def work():
            try:
                built = fx.TimeFX(scale, SS)
                if getattr(self, "tfx", None) is None and self.scale == scale:
                    self.tfx = built
            except Exception:
                self._log_exc("预建时停精灵")
            finally:
                self._tfx_warming = False

        threading.Thread(target=work, daemon=True).start()

    def start_time_stop(self):
        """时停:看家本领 —— 抬手凝滞世界。表盘涟漪扩散、三齿轮螺旋
        环绕,悬浮的星光定格 3 秒,随后时间恢复流动。姿势 = 后仰举手
        (lean/squash 时间轴),定格感由 fx 的齿轮与零重力星光负责。"""
        if self.core_profile():
            return False
        if self.state == "swing" and self._swing and not self.drag:
            self._wake_from_nap()   # 打盹中互动:统一唤醒
            # 坐姿时停:表盘粒子反馈,不落地
            self.say("时间,停止!", 1.8)
            for i in range(3):
                self.add_part("dial", (i - 1) * 0.1 * self.W,
                              -0.30 * self.H, life=0.9,
                              size=12.5, spin=2.2 + i,
                              phase=random.uniform(0, 6.28))
            return
        if self._land_first(self.start_time_stop):
            return
        self.state = "tstop"
        self.tstop_start = time.time()
        self.state_until = self.tstop_start + 3.4
        self._tfx().play("stop", 3.2)
        self._begin_tl(
            tracks={
                "squash":     [(0, 1.0), (0.30, 0.86), (0.55, 1.05),
                               (2.95, 1.0), (3.15, 0.80), (3.4, 1.0)],
                "lean":       [(0, 0.0), (0.30, -0.10), (0.60, -0.14),
                               (2.90, -0.14), (3.15, 0.12), (3.4, 0.0)],
                "look_x":     [(0, 0.0), (0.30, 0.65), (2.95, 0.65), (3.4, 0.0)],
                "_spin_lift": [(0, 0.0), (0.40, 10.0), (3.00, 10.0), (3.2, 0.0)],
            },
            events=[
                (0.0, lambda p: (p.sfx.play("magic"),
                                 p.play_emotion("amazed", 1.6),
                                 p.say(random.choice(
                                     ["时间、停止!", "刹那——静止吧✧",
                                      "这一刻,由我保管~"]), 2.4))),
                (0.35, lambda p: p.land_fx(0.8)),
                # 悬浮星光:零重力慢速,把"世界凝滞"钉在空气里
                (0.50, lambda p: p.star_burst(0, -0.04 * p.H, 10, sp=(4, 14),
                                              grav=0, life=(3.0, 3.3),
                                              size=(4, 7))),
                (0.95, lambda p: p.star_burst(0, -0.20 * p.H, 8, sp=(4, 12),
                                              grav=0, life=(2.6, 2.9),
                                              size=(3, 6))),
                (1.45, lambda p: p.star_burst(0, -0.34 * p.H, 7, sp=(3, 10),
                                              grav=0, life=(2.1, 2.4),
                                              size=(3, 5))),
                (3.05, lambda p: (p.sfx.play("pop"), p.hop(0.85),
                                  p.land_fx(1.0),
                                  p.say(random.choice(
                                      ["时间,继续流动~", "好啦,动起来吧✧"]),
                                      1.8))),
            ])

    def start_rewind(self):
        """时间回溯:倒转的时之扫掠 —— 她反向旋回上一帧,紫色扫掠弧与
        时间碎屑向内收拢,结束时晃晃脑袋(倒带转晕了)。"""
        if self.core_profile():
            return False
        if self.state == "swing" and self._swing and not self.drag:
            self._wake_from_nap()   # 打盹中互动:统一唤醒
            self.say("时间,回溯~", 1.8)
            for i in range(3):
                self.add_part("dial", (i - 1) * 0.12 * self.W,
                              -0.28 * self.H, life=0.9,
                              size=12.5, spin=-2.2 - i,
                              phase=random.uniform(0, 6.28))
            return
        if self._land_first(self.start_rewind):
            return
        self.state = "rewind"
        self.rewind_start = time.time()
        self.state_until = self.rewind_start + 2.8
        self._tfx().play("rewind", 2.6)
        self._begin_tl(
            tracks={
                "_spin_rot": [(0, 0.0), (0.30, 0.0), (2.30, -360.0),
                              (2.8, -360.0)],
                "squash":    [(0, 1.0), (0.30, 0.90), (1.20, 1.03),
                              (2.30, 1.0), (2.45, 0.80), (2.8, 1.0)],
                "lean":      [(0, 0.0), (0.30, 0.10), (1.20, -0.10),
                              (2.30, 0.0), (2.55, 0.13), (2.8, 0.0)],
                "look_x":    [(0, 0.0), (0.30, -0.5), (2.30, -0.5), (2.8, 0.0)],
            },
            events=[
                (0.0, lambda p: (p.sfx.play("tick"),
                                 p.say(random.choice(
                                     ["时间,倒流~⏪", "回到刚刚那一帧✧",
                                      "把这一秒,倒回来~"]), 2.2))),
                (0.30, lambda p: p.land_fx(0.6)),
                (1.05, lambda p: p.sfx.play("tick")),
                (1.80, lambda p: p.sfx.play("tick")),
                (2.30, lambda p: (p.sfx.play("magic"),
                                  p.star_burst(0, -0.10 * p.H, 12, sp=(60, 140),
                                               grav=160, size=(4, 8)))),
                (2.50, lambda p: p.say(random.choice(
                    ["呜…倒带有点晕…", "回来了回来~"]), 1.6)),
            ])

    def start_guess(self):
        """猜数字小游戏:她想一个 1~50 的数,猜中撒彩带 +5 星光。"""
        if self.core_profile():
            return False
        self._guess = {"n": random.randint(1, 50), "tries": 0}
        self._reply("想好啦!一个 1~50 的数字,聊天框里直接猜吧~"
                    "(说「不玩了」随时结束)", "excited")

    def stop_guess(self):
        if self._guess:
            n = self._guess["n"]
            self._guess = None
            self._reply(f"好叭,那个数字其实是 {n}~想玩再叫我!", "mild")
        else:
            self._reply("本来就没在玩呀~", "mild")

    def _guess_turn(self, text):
        """处理一次猜测。大了/小了给方向,猜中庆祝并结束。"""
        if self.core_profile():
            return False
        g = self._guess
        n = int(text)
        if not (1 <= n <= 50):
            self._reply("要在 1~50 之间啦~", "curious")
            return
        g["tries"] += 1
        if n == g["n"]:
            self._guess = None
            self.gain_star(5)                        # 猜中奖励:星光 +5
            self.confetti_burst(0, -0.1 * self.H, 24)
            self.sfx.play("levelup")
            self._reply(f"猜对了!就是 {n}!用了 {g['tries']} 次,厉害呀~", "excited")
            self.add_affection(1)
        elif n > g["n"]:
            self._reply(f"{n}?太大啦,往小的猜~", "curious")
        else:
            self._reply(f"{n}?太小啦,往大的猜~", "curious")

    def report_agent_progress(self):
        from agent_companion import report
        report(self, time.time())

    PET_ACTIONS_CORE = (
        (("进度", "在忙吗", "忙完了吗"), "report_agent_progress"),
        (("摸摸", "摸头", "摸摸头"), "pet_head"),
        (("喂糖", "吃颗糖", "吃糖"), "eat_candy"),
        (("叫醒", "醒醒"), "wake_up"),
        (("上秋千", "荡秋千", "坐秋千"), "mount_swing"),
        (("睡一觉", "睡个觉", "去睡觉", "睡吧"), "go_sleep"),
        (("去小屋", "打开小屋", "看看房间"), "open_room_preview"),
        (("打开聊天", "对话记录"), "open_chat"),
    )

    @classmethod
    def _match_pet_action(cls, text, *, legacy=False):
        for kws, name in (cls.PET_ACTIONS if legacy else cls.PET_ACTIONS_CORE):
            if any(k in text for k in kws):
                return name
        return None

    def ask_ai(self, text):
        text = (text or "").strip()
        if not text:
            return
        # 本地规则优先:「打开微信」这类直接执行,不花 API 额度,
        # 也不给模型误解软件名的机会。没命中才交给 AI。
        # 注意本地路径必须排在 ai_thinking 拦截之前:AI 思考期间(最长
        # 约 90 秒)「打开微信」「猜 25」这些零成本本地指令照样秒执行,
        # 不能跟着一起被吞掉。
        # Core scene/chat commands must win over the retired system parser's
        # broad "open ..." intent. Keep the same negation rule on both paths.
        if self.core_profile() and not any(neg in text for neg in ("别", "不要", "不准")):
            core_action = self._match_pet_action(text)
            if core_action:
                self._log_chat("user", text[:120])
                getattr(self, core_action)()
                return
        intent = agent.parse(text)
        if intent and self.core_profile():
            self._log_chat("user", text[:500])
            self._reply("这一版专注陪伴和 AI 信息，已移除工具操作。可以摸摸、喂糖、休息，或继续聊天。", "mild")
            return
        if intent:
            self.run_agent(intent)
            return
        # 聊天里直接使唤她做动作:本地关键词直通,不花额度。
        # 含"别/不要"的句子放行给 AI(不然"别睡觉"会让她睡觉)。
        if not self.core_profile() and self._guess and text.isdigit() and text.isascii():
            self._guess_turn(text)          # 猜数字进行中:数字就是猜测
            return
        if not self.core_profile() and ("生日快乐" in text or text.strip() == "生快"):
            self.trigger_birthday()
            return
        if not any(neg in text for neg in ("别", "不要", "不准")):
            act_name = self._match_pet_action(text, legacy=not self.core_profile())
            if act_name:
                self._log_chat("user", text[:120])
                getattr(self, act_name)()
                return

        # 本地意图没接住才需要 AI;没密钥时给出和其他功能一致的指引,
        # 而不是等 work() 里 AttributeError 兜底成一句没头没尾的"失灵了"
        if self.brain is None or not self.brain.available:
            self._reply("AI 还没连上,先在右键菜单里设置密钥哦~", "sad")
            return
        if self.state == "sleep":
            self.wake_up()
        if self.ai_thinking:
            # 上一句还在等 AI(45s 超时×重试,最长约 90 秒)。能本地做的
            # 上面已经做完了,走到这里是要等模型的 —— 给句反馈,别让
            # 面板里已经显示出来的消息无声无息地消失。
            self.say("等等嘛,让我先把上一句想完~", 2.2)
            return
        if time.time() - getattr(self, "_last_ai_call", 0) < 1:
            self.say("等等嘛,一句话一句话来~", 2.2)
            return
        self._last_ai_call = time.time()
        self.last_interact = time.time()
        self.history.append({"role": "user", "content": text[:500]})
        self.history = self.history[-16:]
        self._log_chat("user", text[:500])

        self.ai_thinking = True

        def work():
            res = self.brain.chat(text, self.history[:-1])
            self.mainq.put(lambda: self._apply_ai(res))

        self._run_bg(work)

    def _run_bg(self, fn, quiet=False):
        """后台跑 fn,并保证异常不会把线程静默弄死。

        原来 work() 里模型调用在 try 之外:一抛异常线程当场结束,
        后面的 mainq.put 根本执行不到,UI 就永远停在“思考中”。
        """
        def runner():
            try:
                fn()
            except Exception:
                import traceback
                traceback.print_exc()
                try:
                    self.mainq.put(lambda: self._bg_failed(quiet))
                except Exception:
                    pass
        threading.Thread(target=runner, daemon=True).start()

    def _bg_failed(self, quiet=False):
        self.ai_thinking = False
        if not quiet:
            self.say("呜…魔法失灵了,再试一次?", 2.6)

    def _apply_ai(self, res, from_chat=True):
        self.ai_thinking = False
        say = (res or {}).get("say", "")
        if not say:
            self.say("呜…信号不好,魔法失灵了…", 2.4)
            return
        self.history.append({"role": "assistant", "content": say,
                             "emotion": (res or {}).get("emotion", "")})
        self.history = self.history[-16:]
        # 只记聊天框里的正经问答;她主动搭话的碎碎念不进记录
        if from_chat:
            self._log_chat("qiao", say, (res or {}).get("emotion", ""))
        if self.chatbox is not None:
            try:
                if self.chatbox.win.winfo_exists():
                    self.chatbox.log_reply(say)
            except Exception:
                pass
        self.say(say, 6.0)  # 长回答给更长时间显示
        self._speak(say)
        em = res.get("emotion")
        if em:
            self.play_emotion(em, 2.6)
        # AI 判定要操作电脑 —— 走和本地规则完全相同的执行/确认路径,
        # 卸载一样要弹确认框,不因为是模型发起的就放宽
        it = res.get("intent")
        if not self.core_profile() and from_chat and isinstance(it, dict) and it.get("target"):
            self.root.after(700, lambda: self.run_agent(
                {"kind": it["kind"], "target": it["target"],
                 "minutes": it.get("minutes"),
                 "raw": f'({it["kind"]} {it["target"]})', "_from_ai": True}))
        act = res.get("action")
        # 秋千是舞台(宪法 7):AI 主动搭话不打断演出 —— 只冒气泡,不执行
        # 动作(变身/睡觉这类会把她顶下秋千);主人主动聊天的动作照常执行
        if not self.core_profile() and act and not (not from_chat and self.state == "swing"):
            self.root.after(1200, lambda: self._do_action(act))

    def _do_action(self, act):
        if self.core_profile():
            return False
        if act == "magic":
            self.cast_magic()
        elif act == "stars":
            self.star_rain()
        elif act == "hop":
            if self._seat_guard():
                return
            self.hop(0.6)
            self.play_emotion("excited", 1.6)
        elif act == "walk":
            if self._seat_guard():
                return
            if self._land_first(lambda: self._do_action("walk")):
                return
            self.state = "walk"
            self.walk_home = self.x
            self.walk_target = max(self.x_min,
                                   min(self.x + random.choice((-1, 1))
                                       * random.uniform(120, 240) * self.scale,
                                       self.x_max))
            self.face = 1 if self.walk_target > self.x else -1
            self.state_until = time.time() + 30

    # ==================== 本事:提醒/剪贴板/找文件 ====================
    def _load_reminders(self):
        if self.core_profile():
            return False
        data = self._load_json(REMINDERS_FILE, [])
        now = time.time()
        self.reminders = [r for r in data
                          if isinstance(r, dict) and isinstance(r.get("due"), (int, float))
                          and r.get("due", 0) > now]
        self._save_reminders()

    def _save_reminders(self):
        if self.core_profile():
            return False
        try:
            tmp = REMINDERS_FILE + ".tmp"   # 原子替换,防半截 JSON
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.reminders, f, ensure_ascii=False)
            os.replace(tmp, REMINDERS_FILE)
        except Exception:
            # 提醒没落盘,重启后到点就不会响 —— 至少留下痕迹
            self._log_exc("reminders_save")

    def _schedule_reminder(self, minutes, text, quiet=False):
        """定一个一次性提醒,到点由 _tick_body 触发(不用 after,重启也能活)。"""
        if self.core_profile():
            return False
        try:
            minutes = float(minutes)
        except (TypeError, ValueError):
            minutes = 25.0
        minutes = min(max(minutes, 0.1), 1440.0)
        text = (str(text or "").strip() or "时间到啦~")[:200]
        self.reminders.append({"due": time.time() + minutes * 60, "text": text})
        self._save_reminders()
        if not quiet:
            when = f"{minutes:g} 分钟" if minutes < 60 else f"{minutes / 60:g} 小时"
            self._reply(f"记住啦,{when}后叫你:{text}", "roger")
            self.hop(0.4)

    def _fire_reminder(self, text):
        if self.core_profile():
            return False
        self.sfx.play("notify")
        self.wake_if_sleep()
        self._reply(text, "excited")
        self.star_burst(0, -0.2 * self.H, 6)
        if not self._seat_guard(True, silent=True):
            self.hop(0.5)

    def reminder_dialog(self):
        if self.core_profile():
            return False
        def _ck(s):
            # 原来分钟数完全不校验,填个"半小时"进去就悄悄什么也不会发生
            return None if s.isdigit() and 1 <= int(s) <= 1440 else \
                "填个 1~1440 之间的分钟数就行~"

        mins = self.themed_input("小乔 · 提醒", "多少分钟后提醒你?(如 30)",
                                 initial="30", validate=_ck)
        if not mins:
            return
        text = self.themed_input("小乔 · 提醒", "到点时说什么?",
                                 initial="该喝水啦~")
        if text is None:
            return
        self._schedule_reminder(mins, text)

    def set_water_reminder(self, minutes):
        if self.core_profile():
            return False
        self.water_min = int(minutes)
        if self.water_min > 0:
            self.water_next = time.time() + self.water_min * 60
            self._reply(f"好~每 {self.water_min} 分钟催你喝一次水!", "roger")
        else:
            self._reply("好叭,不催你了,你自己记得喝哦~", "mild")
        self.save_settings()

    def _clipboard_ai(self, mode):
        """剪贴板 -> AI,mode: sum=总结 / trans=翻译。"""
        if self.core_profile():
            return False
        self.last_interact = time.time()
        try:
            clip = self.root.clipboard_get()
        except Exception:
            clip = ""
        clip = (clip or "").strip()
        if not clip:
            self._reply("剪贴板里没有文字诶,复制点东西再来找我~", "curious")
            return
        if self.brain is None or not self.brain.available:
            self._reply("AI 还没连上,先在右键菜单里设置密钥哦~", "sad")
            return
        if mode == "sum":
            tag, ask = "[剪贴板]", "帮我总结剪贴板里的内容:"
            waiting = "让我看看你抄了什么…"
        else:
            tag, ask = "[翻译]", "帮我翻译剪贴板里的内容:"
            waiting = "翻译ing,稍等~"
        self._log_chat("user", tag + " " + clip[:120] + ("…" if len(clip) > 120 else ""))
        self.history.append({"role": "user", "content": (ask + clip)[:500]})
        self.history = self.history[-16:]
        self.say(waiting, 2.0)

        self.ai_thinking = True

        def work():
            if mode == "sum":
                res = self.brain.summarize(clip)
            else:
                res = self.brain.translate(clip)
            self.mainq.put(lambda: self._apply_ai(res))

        self._run_bg(work)

    def summarize_clipboard(self):
        if self.core_profile():
            return False
        self._clipboard_ai("sum")

    def translate_clipboard(self):
        if self.core_profile():
            return False
        self._clipboard_ai("trans")

    def look_screen(self, question=""):
        """截一块主屏幕发给 Gemini,让她'看见'并回答。"""
        if self.core_profile():
            return False
        self.last_interact = time.time()
        if self.brain is None or not self.brain.available:
            self._reply("AI 还没连上,先在右键菜单里设置密钥哦~", "sad")
            return
        self.say("别动哦,我看看…", 1.8)
        try:
            shot = ImageGrab.grab()
        except Exception as e:
            self._reply(f"截不了屏…{str(e)[:40]}", "pouty")
            return
        # 缩到 1280 宽 + JPEG:视觉模型按像素算 token,原图又大又没必要
        if shot.width > 1280:
            shot = shot.resize((1280, max(1, int(shot.height * 1280 / shot.width))),
                               Image.LANCZOS)
        buf = io.BytesIO()
        shot.convert("RGB").save(buf, "JPEG", quality=85)
        data = buf.getvalue()
        q = (question or "").strip()
        if q in ("看看", "screen"):
            q = ""
        self._log_chat("user", "[屏幕] " + (q[:120] if q else "看看屏幕"))
        self.history.append({"role": "user",
                             "content": ((("看了你的屏幕,我的问题是:" + q)
                                          if q else "让小乔看了一眼屏幕") )[:500]})
        self.history = self.history[-16:]

        self.ai_thinking = True

        def work():
            res = self.brain.look(data, q)
            self.mainq.put(lambda: self._apply_ai(res))

        self._run_bg(work)

    def focus_mode(self):
        """专注陪伴中吗?——只有番茄钟的"专注"段算,休息段不算。

        休息段她恢复原样(该闹就闹),这正是"一起休息"想要的对比。
        用 getattr 读 pomo:几个 unittest 文件用 Pet.__new__ 造壳桌宠、
        不跑 __init__,而 say() 会调到这里。
        """
        if self.core_profile():
            return False
        p = getattr(self, "pomo", None)
        return bool(p and p.get("phase") == "focus"
                    and time.time() < p.get("due", 0))

    def _focus_tick(self, now):
        """专注陪伴:不说话、不出贴纸,只让几点星光从她身边慢慢升上去。

        刻意只用 sparkle(见 FOCUS_ENCOURAGE 的注释)。有气泡时也跳过 ——
        主人刚摸过她,别让星光跟台词抢戏。坐在秋千上(默认的家)也照常陪。
        """
        if self.core_profile():
            return False
        if (not self.focus_mode() or self.state not in ("idle", "swing")
                or self.bubble):
            return
        if now < self._focus_next:
            return
        if not self._focus_next:          # 刚开始专注,先隔一会儿再冒
            self._focus_next = now + random.uniform(*FOCUS_ENCOURAGE)
            return
        self._focus_next = now + random.uniform(*FOCUS_ENCOURAGE)
        for i in range(3):
            self.add_part("sparkle", random.uniform(-0.14, 0.14) * self.W,
                          -0.30 * self.H - i * 6,
                          vy=-random.uniform(16, 28),
                          life=random.uniform(1.4, 2.2),
                          size=random.uniform(3.5, 6.0), color=GOLD_L,
                          phase=random.uniform(0, 6.28))
        # 过半那一次额外给一个约 1 秒的小动作。全程只此一次:_micro_motion
        # 会占 60fps 档,1s / 25min ≈ 0.07%,这个买得起。
        if (not self._focus_half
                and now >= self.pomo["due"] - self.pomo["mins"] * 30):
            self._focus_half = True
            self._start_micro_motion("nuzzle")

    def start_pomodoro(self, minutes=25):
        if self.core_profile():
            return False
        try:
            minutes = float(minutes)
        except (TypeError, ValueError):
            minutes = 25.0
        if minutes <= 0:
            self.stop_pomodoro()
            return
        minutes = min(max(minutes, 5.0), 120.0)
        self.pomo = {"phase": "focus", "due": time.time() + minutes * 60,
                     "mins": minutes}
        self._focus_next = 0.0
        self._focus_half = False
        self.save_settings()    # 立刻落盘:重启不丢计时
        self.last_interact = time.time()
        self.wake_if_sleep()
        self._reply(f"番茄钟启动!专注 {minutes:g} 分钟,到点我叫你休息~", "roger")
        self.play_emotion("excited", 2.0)

    def stop_pomodoro(self):
        if self.core_profile():
            return False
        if self.pomo:
            self.pomo = None
            self._focus_next = 0.0
            self._focus_half = False
            self.save_settings()    # 停掉也要落盘,别把旧计时留给下次开机
            self._reply("番茄钟停啦,想专注随时叫我~", "mild")
        else:
            self._reply("现在没有在番茄钟哦~", "curious")

    # ---- 前台窗口感知(偷看开关在右键菜单) ----
    def _fg_title(self):
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return ""
            buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
            return buf.value or ""
        except Exception:
            return ""

    @staticmethod
    def _fg_bucket(title):
        t = (title or "").lower()
        if any(k in t for k in ("visual studio code", "vs code", "vscode",
                                "pycharm", "intellij", "zcode", "terminal",
                                "powershell", "cmd.exe", "git bash")):
            return "code"
        if any(k in t for k in ("哔哩哔哩", "bilibili", "youtube", "爱奇艺",
                                "优酷", "腾讯视频", "芒果tv", "netflix", "抖音")):
            return "video"
        return "other"

    def _fg_watch_tick(self, now):
        """每 30 秒瞄一眼前台窗口;同一类连续太久就念叨一次。"""
        if self.core_profile():
            return False
        if not self.fg_watch or now < self.next_fg_check:
            return
        self.next_fg_check = now + 30
        b = self._fg_bucket(self._fg_title())
        if b != self.fg_bucket:
            self.fg_bucket = b
            self.fg_since = now
            return
        if not self.fg_since:
            return
        span = now - self.fg_since
        title = self._fg_title()
        if b == "video" and span > 20 * 60 and now > self._fg_said_video:
            self._fg_said_video = now + 45 * 60
            self._fg_say_on(f"视频都看 {int(span // 60)} 分钟了哦,让眼睛歇歇嘛~", title)
        elif b == "code" and span > 90 * 60 and now > self._fg_said_code:
            self._fg_said_code = now + 90 * 60
            self._fg_say_on(f"代码写了 {int(span // 60)} 分钟啦,起来走走,我看着你", title)

    def _fg_say_on(self, fallback, title):
        # 有 AI 就结合窗口标题说得有鼻子有眼,没 AI 就说固定台词
        if self.core_profile():
            return False
        if self.brain and self.brain.available and random.random() < 0.6:
            self._ai_quick(f"主人的前台窗口标题是「{title[:80]}」。"
                           f"根据这个说一句关心或吐槽(20字内),别复述标题。")
        else:
            self._reply(fallback, "curious")

    # ---- 电量感知(笔记本):插拔电源、低电量、充满 ----
    def toggle_hat_orbit(self):
        self.hat_orbit = not self.hat_orbit
        self.save_settings()
        self.say("帽子上的小星星们又转起来啦~" if self.hat_orbit
                 else "好,让小星星们先休息~", 2.2)

    def toggle_battery_watch(self):
        self.battery_watch = not self.battery_watch
        self._batt_prev = None
        self.save_settings()
        self.say("好,电量有变化我会告诉你~" if self.battery_watch
                 else "好,不念叨电量啦~", 2.4)

    @staticmethod
    def _power_status():
        """(接着电源, 电量%)。台式机没有电池或读不到时返回 None。"""
        s = _PowerStatus()
        try:
            if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)):
                return None
        except Exception:
            return None
        if s.BatteryFlag & 128 or s.BatteryLifePercent > 100 or s.ACLineStatus > 1:
            return None
        return bool(s.ACLineStatus), int(s.BatteryLifePercent)

    @staticmethod
    def _battery_event(prev, cur):
        """比较前后两次采样,返回要演的事件名;阈值只在跨过的那一次触发。"""
        if not prev or not cur:
            return None
        (pac, ppct), (ac, pct) = prev, cur
        if ac and not pac:
            return "plug"
        if pac and not ac:
            return "unplug"
        if not ac and pct <= 10 < ppct:
            return "critical"
        if not ac and pct <= 20 < ppct:
            return "low"
        if ac and pct >= 100 > ppct:
            return "full"
        return None

    def _battery_tick(self, now):
        if self.core_profile():
            return False
        if not self.battery_watch or now < self._batt_next:
            return
        self._batt_next = now + 60.0
        cur = self._power_status()
        ev = self._battery_event(self._batt_prev, cur)
        self._batt_prev = cur
        # 专注时和睡着时不打扰;事件本身已记下,不会攒着事后补报
        if ev and not self.focus_mode() and self.state not in ("sleep", "yawn"):
            self._battery_react(ev, cur[1])

    def _battery_react(self, ev, pct):
        if self.core_profile():
            return False
        now = time.time()
        if ev == "plug":
            # 充能:金色星星往上飘(负重力),脚下一圈闪光
            self.star_burst(0, 0.05 * self.H, 10, sp=(80, 160), grav=-60, size=(4, 8))
            self.circles.append(dict(born=now, life=0.6, rx=0.9, kind="flash"))
            self.play_emotion("excited", 2.2)
            if now > self._batt_star_cd:
                self._batt_star_cd = now + 600
                self.gain_star(5)
                self.say(random.choice(["充能中~星光也 +5!", "电来啦,满血复活!"]), 2.4)
            else:
                self.say("充能中~", 1.8)
        elif ev == "unplug":
            self.play_emotion("curious", 2.0)
            self.say(random.choice(["拔掉电源啦,省着点用哦~",
                                    "要出门吗?电量省着花~"]), 2.4)
        elif ev == "low":
            self.play_emotion("tired", 2.6)
            self.say(f"电量只剩 {pct}% 了…我也有点困", 2.8)
        elif ev == "critical":
            self.hop(0.6)
            self.play_emotion("surprised", 2.4)
            self.say(f"电量 {pct}%!快找充电器!", 3.0)
        elif ev == "full":
            self.play_emotion("proud", 2.2)
            self.say("电充满啦!可以拔掉了~", 2.4)

    # ---- 今日小结:当天的陪伴计数,跨天自动清零 ----
    TODAY_LABELS = (("pet", "摸头 {} 次"), ("candy", "喂糖 {} 颗"),
                    ("catch", "接星 {} 颗"), ("focus_min", "专注 {} 分钟"),
                    ("chat", "聊天 {} 句"), ("tickle", "挠痒 {} 次"))

    def _today_stats(self):
        today = time.strftime("%Y-%m-%d")
        settings = getattr(self, "settings", None)
        if not isinstance(settings, dict):
            # 测试里的壳桌宠没有存档字典:给个不落盘的空统计,别让卡片打不开
            return {"date": today}
        st = settings.get("today_stats")
        if not isinstance(st, dict) or st.get("date") != today:
            st = {"date": today}
            settings["today_stats"] = st
        return st

    def _count_today(self, key, n=1):
        st = self._today_stats()
        st[key] = int(st.get(key, 0)) + int(n)
        self._stats_dirty = True

    def _today_summary(self, limit=None):
        st = self._today_stats()
        labels = self.TODAY_LABELS
        if self.core_profile():
            labels = tuple(item for item in labels if item[0] in ("pet", "candy", "chat", "tickle"))
        items = [fmt.format(st[k]) for k, fmt in labels if st.get(k)]
        return " · ".join(items[:limit] if limit else items)

    def _stats_tick(self, now):
        # 计数不逐次写盘(连摸很频繁):有改动时最多每分钟落一次,退出时 quit 也会存
        if self._stats_dirty and now > self._stats_next_save:
            self._stats_next_save = now + 60.0
            self._stats_dirty = False
            self.save_settings()
        if self.core_profile():
            return
        # 晚上 9 点后第一次安静空闲时,轻声总结一下今天(每天一次)
        # 秋千上静静荡着也算空闲 —— 默认就住在秋千上
        today = time.strftime("%Y-%m-%d")
        if (time.localtime().tm_hour >= 21 and self.settings.get("summary_day") != today
                and self.state in ("idle", "swing") and not self.bubble and not self.drag
                and not self.focus_mode() and now - self.last_interact > 20):
            self.settings["summary_day"] = today
            s = self._today_summary()
            if s:
                self.say(f"今天{s},辛苦啦~", 4.0)
                self.play_emotion("thanks", 2.4)

    # ---- 浮空冥想 ----
    def start_meditate(self):
        """浮空冥想:缓缓升空,腰间三股星尘绕行,悬停时轻轻起伏,最后柔柔落地。"""
        if self.core_profile():
            return False
        if self.state in ("sleep", "yawn"):
            self.wake_if_sleep()
        if self.state == "swing" and self._swing and not self.drag:
            self.say("荡着的时候浮不起来啦~", 2.0)
            return
        if self._land_first(self.start_meditate):
            return
        if self.state not in ("idle", "sticker", "walk"):
            return
        self.last_interact = time.time()
        self.state = "meditate"
        self.meditate_start = time.time()
        self.state_until = self.meditate_start + 5.6
        s = self.scale
        self._begin_tl(
            tracks={
                "_spin_lift": [(0, 0.0), (0.25, 0.0), (1.2, 36.0 * s),
                               (4.3, 36.0 * s), (5.2, 0.0)],
                "squash":     [(0, 1.0), (0.25, 0.93), (0.6, 1.04), (1.0, 1.0),
                               (5.15, 1.0), (5.3, 0.9), (5.6, 1.0)],
                "_bend":      [(0, 0.0), (1.2, 0.0), (2.4, 0.025), (3.4, -0.025),
                               (4.3, 0.0)],
            },
            events=[
                (0.0, lambda p: (p.play_emotion("mild", 2.4),
                                 p.say(random.choice(["静下心来…", "深呼吸~",
                                                      "感受星光的流动…"]), 2.2))),
                (1.2, lambda p: p.circles.append(
                    dict(born=time.time(), life=0.7, rx=0.8, kind="flash"))),
                (2.8, lambda p: p.star_burst(0, -0.18 * p.H, 6, sp=(40, 90), grav=30,
                                             size=(4, 7))),
                (5.2, lambda p: (p._shocks.append(dict(born=time.time(), strength=.3)),
                                 p.star_burst(0, 0.1 * p.H, 8, sp=(70, 140), grav=200),
                                 p.play_emotion("proud", 2.2),
                                 p.say(random.choice(["神清气爽~", "灵感满满!",
                                                      "呼…好舒服"]), 2.2))),
            ])

    def toggle_fg_watch(self):
        self.fg_watch = not self.fg_watch
        self.fg_bucket = ""
        self.fg_since = 0.0
        self.save_settings()
        self.say("那我偶尔看看你在干嘛哦~" if self.fg_watch
                 else "好,我不偷看了,给你留点小秘密~", 2.4)

    # ---- AI 会话灯:两台电脑的 AI 会话,一盏灯一个任务 ----
    def toggle_ai_announce(self):
        self.ai_announce = not self.ai_announce
        self.save_settings()
        self.say("好,任务提醒静音,有急事我再悄悄说~" if not self.ai_announce
                 else "任务提醒打开啦,重要的事我会喊你!", 2.2)

    def toggle_ai_lights(self):
        self.ai_lights = not self.ai_lights
        self.save_settings()
        self.say("AI 会话灯亮起来啦~" if self.ai_lights
                 else "好,会话灯先收起来~", 2.2)

    def _scan_ai_sessions(self):
        # 演示/截图:模拟数据注入期间跳过真实扫描(页脚标注「模拟」)
        if time.time() < getattr(self, "_demo_until", 0.0):
            self._ai_sessions = list(getattr(self, "_demo_sessions", []) or [])
            self._ai_work_sessions = self._ai_sessions
            self._next_ai_scan = time.time() + 2.0
            return
        """扫 ai_sessions/,刷新会话灯;Mac 会话状态变化时播一句。

        限频:_pump 每 2 秒才放行一次。播报只挑 Mac 的会话(本机 ZCode 的
        完成确认已经有 zcode_notify 在说),同类变化 120 秒内不重复,全局
        40 秒内最多一句;她睡着时灯照常更新但不吵醒她。启动后第一轮只记下
        磁盘上的现状,不把几小时前的 Mac 状态当新变化播。

        自主情绪(担心/好奇/松口气/久等催促)每轮都评估 —— 原来排在"状态表
        没变就 return"后面,一直停在 waiting 的会话永远等不到好奇和催促。"""
        prev = getattr(self, "_ai_states", None)
        now = time.time()
        # 全量读,灯板只取前 5:出错的会话被更新的会话挤出灯板,不能当成解决了
        every = scan_ai_sessions(AI_SESSION_DIR, cap=None, now=now)
        sessions = every[:AI_SESSION_CAP]
        self._ai_sessions = sessions
        self._ai_work_sessions = every
        self._next_ai_scan = now + 2.0
        # 额度采样:Claude 桌面版 plan-usage(本机文件,60s 节流)
        self._quota_scan = getattr(self, "_quota_scan", 0) + 1
        if self._quota_scan % 30 == 1:
            self._quota = read_claude_quota()
            from ai_quota import read_codex_quota
            sampled = read_codex_quota(CODEX_QUOTA_FILE)
            self._codex_quota_error = sampled is None and os.path.exists(CODEX_QUOTA_FILE)
            if sampled is not None or not self._codex_quota_error:
                self._codex_quota = sampled
        if getattr(self, "_flat_panel_style", False):
            from agent_companion import tick
            self._ai_states = {s["id"]: s["state"] for s in every}
            tick(self, now, every)
            return
        # 灯已当熄掉的(Mac 同步断了、卡太久)不担心、不催、不算解决
        live = [s for s in every if not ai_session_stale(s, now)]
        # 关灯/睡着时照样记账(已反应集合、上一轮状态),只是不表现 ——
        # 重新开灯、醒过来都不补发旧事件
        awake = self.ai_lights and self.state not in ("sleep", "yawn")
        # 任务提醒静音:灯/水晶/面板照常,只是不冒播报气泡
        speaking = awake and getattr(self, "ai_announce", True)
        # 自主情绪:AI 出错 → 担心(眼睑 sad + 视线垂向灯板);久等的
        # waiting → 好奇微眯。与播报共享独立节流,不与播报抢话。
        lid, mode, reacted = ai_reactions(live, getattr(self, "_ai_err_seen", set()), now)
        self._ai_err_seen = reacted
        # 恢复弧:上一轮还亮着红灯的会话,这轮真的转成 done/running/idle 才松口气。
        # 文件没了、Mac 断线被改成空闲(stale)都不算 —— 错误其实没解决
        muted = getattr(self, "ai_mute_sources", set()) or set()
        prev_err = {sid for sid, st in getattr(self, "_ai_prev_states", {}).items()
                    if st == "error"}
        fixed = [s for s in live
                 if s["id"] in prev_err and s["state"] in ("done", "running", "idle")]
        if fixed and awake and now - getattr(self, "_last_relief", 0.0) > 60:
            self._last_relief = now
            self._lid = 0.05
            self._lid_mode = "relieved"
            self._lid_until = now + 2.4
            if (speaking and fixed[0].get("agent") not in muted
                    and not self.focus_mode()):  # 专注/静音:只松眼神,不蹦不说
                self.hop(0.5)
                self.hearts(0, -self._spr_disp_h() * 0.42, 3)
                if now - self.last_interact > 8:
                    self.say(random.choice(["呼——解决了就好~", "太好了,警报解除!",
                                            "哼,人家刚才可是很担心的!"]), 2.4)
        # 久等催促:同一 waiting 会话等了 5 分钟以上,每 5 分钟催一次。等了多久
        # 从开始等算(ai_wait_since):Mac 文件的 updated 每轮同步都改成现在
        for s in live:
            if s.get("state") != "waiting":
                continue
            if (speaking and s.get("agent") not in muted
                    and now - ai_wait_since(s, now) > 300
                    and now - getattr(self, "_last_urgent", 0.0) > 300):
                self._last_urgent = now
                self._lid = max(self._lid, 0.30)
                self._lid_mode = "urgent"
                self._lid_until = now + 2.6
                if now - self._ai_last_say > 20:
                    self._ai_last_say = now
                    self.say(random.choice(["都等五分钟了,快去看看嘛!",
                                            "再不去处理,人家要生气了哦!"]), 2.6)
        self._ai_prev_states = {s["id"]: s.get("state") for s in live}
        if lid is not None and awake:
            # 眼睑被别的情绪占着时排队补播,不再直接丢(id 已记进 _ai_err_seen)
            self._offer_lid(lid, mode, now)
        cur = {s["id"]: s["state"] for s in every}
        self._ai_states = cur
        if prev is None or prev == cur:
            return                      # 第一轮只记下现状;状态表没变也不用播
        msess = getattr(self, "ai_mute_sess", set()) or set()
        live = [s for s in live if s.get("agent") not in muted
                and s.get("id") not in msess]
        if not speaking or now - self._ai_last_say < 40:
            return
        for s in live:
            if not s["agent"].startswith("mac-"):
                continue
            if prev.get(s["id"]) == s["state"]:
                continue
            # 绿灯已熄的 done 不是新消息:同步停摆后留下的旧文件、
            # 隔了很久才拉到的早已完成的会话
            if s["state"] == "done" and ai_light_style("done", s["updated"], now)[1] != "solid":
                continue
            key = (s["id"], s["state"])
            if now - self._ai_key_last.get(key, 0.0) < 120:
                continue
            lines = AI_SESSION_LINES.get(s["state"])
            if lines:
                self.say(random.choice(lines), 2.6)
                self._ai_last_say = now
                self._ai_key_last[key] = now
                break

    def _draw_ai_lights(self, frame, now, paste_x, spr_w, feet_y, k, bottom_y=None):
        """她身侧一块竖向小面板:DeepBar 式的会话灯,一眼可见。

        橙=等你 红=出错 紫=在跑 绿=刚完成(90 秒后转空心) 空心=空闲;
        每盏灯左侧带 agent 首字母(Z/M/C/W)。靠左屏时面板换到她右侧;
        没有会话或开关关着就完全不画。"""
        if self.house_enabled() or self.studio_enabled() or not self.ai_lights:
            return
        sessions = self._ai_sessions
        if not sessions:
            return
        try:
            d = ImageDraw.Draw(frame, "RGBA")
        except Exception:
            return
        r = max(7, int(8 * k))
        gap = r * 2 + max(6, int(10 * k))
        tag_w = int(r * 2.2)
        pad = int(r * 0.9)
        panel_w = pad + tag_w + r * 2 + pad
        panel_h = len(sessions) * gap + pad * 2 - (gap - r * 2)
        on_left = paste_x > 64 + panel_w
        py = int(feet_y - panel_h - r - 6)
        if bottom_y is not None:
            # 原画秋千:左下是魔法书,灯板挪到书的上方(她举着的手左边、帽檐下)
            on_left, py = True, int(bottom_y - panel_h - 4 * k)
        px = int((paste_x - panel_w - 4) if on_left else (paste_x + spr_w + 4))
        # 面板画在独立小图上再一次性合成:直接往帧上画半透明填充,
        # 实测透明度会失效(帽尖透过来压住内容)
        base, bpad = ui3d.calm_panel(panel_w, panel_h, int(r * 1.6), k=k, studs=False)
        panel = base.copy()
        d = ImageDraw.Draw(panel)
        font = getattr(self, "f_chain", None)
        for i, s in enumerate(sessions):
            rgb, kind = ai_light_style(s["state"], s["updated"], now)
            cy = int(bpad + pad + r + i * gap)
            cx = int(bpad + pad + tag_w + r)
            # agent 首字母:Z=zcode M=mac-claude C=mac-codex W=wslcodex
            ch = AI_AGENT_CHAR.get(s["agent"], (s["agent"][:1] or "?").upper())
            tc = rgb + (255,) if kind != "hollow" else (168, 150, 210, 210)
            if font:
                try:
                    d.text((bpad + pad, cy), ch, font=font, fill=tc, anchor="lm")
                except Exception:
                    pass
            if kind == "hollow":
                g = ui3d.gem(r, rgb, hollow=True, glow=False)
                panel.alpha_composite(g, (int(cx - g.width / 2), int(cy - g.height / 2)))
                continue
            if kind == "pulse":
                a = 160 + int(95 * (0.5 + 0.5 * math.sin(now * 2.6 + i * 0.9)))
            elif kind == "blink_fast":
                a = 255 if math.sin(now * 7.0 + i) > 0 else 120
            elif kind == "blink":
                a = 255 if math.sin(now * 4.0 + i) > 0 else 130
            else:
                a = 255
            # 水晶球灯珠(径向明暗 + 高光 + 同色外辉);闪烁只调整体透明度
            g = ui3d.gem(r, rgb)
            if a < 255:
                g = g.copy()
                g.putalpha(g.getchannel("A").point(lambda v, a=a: v * a // 255))
            panel.alpha_composite(g, (int(cx - g.width / 2), int(cy - g.height / 2)))
        self._ac(frame, panel, px - bpad, py - bpad)

    def _draw_ai_chain(self, frame, now, paste_x, paste_y, spr_w):
        """头顶思维链:最近一个在跑/等人的会话,它的最新动作直接顶在她头上。

        气泡优先(她在说话时链子让位);全空闲时不画,还她清静。"""
        # 这一帧没画卷轴就不能留着上一帧的点击区(原来链子消失后那块
        # 看不见的区域还能点开魔法书)
        self._chain_rect_local = None
        if self.house_enabled() or self.studio_enabled():
            self._chain_rect = None
            return
        if not self.ai_lights:
            return
        b = self.bubble
        if b and now < b[1]:
            return
        got = ai_chain_lines(self._ai_sessions, now)
        if not got:
            return
        title, acts, chain_sid = got
        self._chain_sid = chain_sid
        font = getattr(self, "f_chain", None)
        if not font:
            return
        line_h = int(font.size * 1.5)
        pad_x, pad_y = 10, 6
        max_w = 330 - pad_x * 2
        lines = [title] + acts
        # 按面板宽度截断,长命令加省略号,不让字溢出底板
        fitted = []
        for t in lines:
            try:
                while t and font.getlength(t) > max_w:
                    t = t[:-2] + "…"
            except Exception:
                t = t[:36] + ("…" if len(t) > 36 else "")
            fitted.append(t)
        lines = fitted
        widths = []
        for t in lines:
            try:
                widths.append(font.getlength(t))
            except Exception:
                widths.append(len(t) * 7)
        w = int(max(widths)) + pad_x * 2
        h = pad_y * 2 + line_h * len(lines)
        cx = paste_x + spr_w // 2
        x0 = max(2, min(cx - w // 2, int(430 * 1.6) - w - 2))
        y0 = max(2, paste_y - h - 8)
        # 魔法卷轴(世界化,宪法 8):深紫墨纸面 + 左右卷轴杆 + 金轴帽,
        # 一根细金线挂在帽尖下 —— 替代普通软件窗口样式的悬浮框。
        # 独立小图上画好再合成:直接往帧上画半透明填充会失效
        # 纸面 = 立体面板(投影/受光/金边),左右卷轴杆 = 带高光的圆柱 + 金轴帽
        kk = max(1.0, self.scale)
        paper, ppad = ui3d.calm_panel(w, h + 4, 8 * kk, k=kk, studs=False,
                                 tone=((58, 40, 96), (28, 18, 50)))
        panel = Image.new("RGBA", (w + 16 + 2 * ppad, h + 10 + 2 * ppad), (0, 0, 0, 0))
        panel.alpha_composite(paper, (8, 3))
        for rx in (2, w + 8):
            rod = ui3d.cylinder(6, h + 10, (78, 52, 128))
            panel.alpha_composite(rod, (ppad + rx, ppad))
            for cyy in (ppad - 2, ppad + h + 8):
                cap = ui3d.gem(3, (255, 210, 110), glow=False)
                panel.alpha_composite(cap, (int(ppad + rx + 3 - cap.width / 2), int(cyy - cap.height / 2 + 2)))
        pd = ImageDraw.Draw(panel)
        ty = pad_y
        for i, t in enumerate(lines):
            if i == 0:
                col = (232, 221, 255, 255)              # 标题行:项目名,暖白
            elif i == 1:
                col = (255, 215, 106, 255)              # 最新动作:金,最亮
            else:
                col = (232, 221, 255, 150)              # 更早的动作:淡
            prefix = "" if i == 0 else "› "
            pd.text((ppad + pad_x + 8, ppad + ty), prefix + t, font=font, fill=col)
            ty += line_h
        self._chain_rect_local = (x0 - 8, y0 - 3, w + 16, h + 10)
        # 细金线:卷轴挂在帽尖下(frame 是 Image,自建 Draw)
        ImageDraw.Draw(frame).line((cx, max(2, y0 - 2), cx, paste_y + 6),
                                   fill=(242, 193, 78, 150), width=1)
        self._ac(frame, panel, x0 - 8 - ppad, y0 - 3 - ppad)

    def _save_swing_scene(self):
        """场景位置/大小持久化(重启后恢复)。"""
        sw = self._swing
        if not sw:
            return
        self.settings["swing_scene"] = {
            "l": int(sw["scene_l"]), "t": int(sw["scene_t"]),
            # 按中心记:原画场景和程序秋千的画布大小不同,换了也不跑位
            "cx": int(sw["scene_l"] + sw["scene_w"] / 2),
            "cy": int(sw["scene_t"] + sw["scene_h"] / 2),
            "scale": round(sw.get("scene_scale", 1.0), 3)}
        self.save_settings()

    def on_wheel_scene(self, e):
        """荡秋千时滚轮 = 整个场景等比缩放(持久化)。"""
        if self.state != "swing" or not self._swing:
            return
        if self._swing.get('geo', {}).get('flat'):
            from flat_workspace import scroll, LIST
            u = self._swing['geo']['u']
            ey = e.y - self._swing['geo'].get('hat_fx_pad', 0)
            if LIST[0]*u <= e.x <= (LIST[0]+LIST[2])*u and LIST[1]*u <= ey <= (LIST[1]+LIST[3])*u:
                scroll(self, e.delta)
            self.last_interact = time.time()
            return 'break'
        step = 0.06 if e.delta > 0 else -0.06
        sw = self._swing
        if sw.get("art"):
            lo, hi = SWING_ART_SCALE
            lo = .48 if self.house_enabled() else lo
            self._art_regeo(sw, min(hi, max(lo, sw.get("scene_scale", 1.0) + step)))
        else:
            sw["scene_scale"] = min(SWING_SCALE_MAX, max(
                SWING_SCALE_MIN, sw.get("scene_scale", 1.0) + step))
        self.last_interact = time.time()
        self._save_swing_scene()

    def _swing_impulse(self, dv):
        sw = self._swing
        if sw and "pend" in sw:
            sw["pend"].impulse(dv)
            self.add_part("sparkle", -self.W * 0.2, -self._spr_disp_h() * 0.62,
                          life=0.7, size=random.uniform(5, 9),
                          color=GOLD_L, phase=random.uniform(0, 6.28))
            self.sfx.play("sparkle")

    def wobble_hat(self):
        """点帽子:帽子抖一下 + 星星迸溅 + 偶尔抗议一句。"""
        self.life.hat_rot.impulse(random.choice((-0.05, 0.05)))
        self.life.hat_dx.impulse(random.choice((-2.5, 2.5)))
        self.life.impulse_hair(0.6)
        self.add_part("sparkle", -self.W * 0.04, -self.H * 0.30,
                      life=0.7, size=random.uniform(5, 10),
                      color=random.choice(STAR_COLORS),
                      phase=random.uniform(0, 6.28))
        self.add_part("sparkle", self.W * 0.06, -self.H * 0.26,
                      life=0.6, size=random.uniform(4, 8),
                      color=GOLD_L, phase=random.uniform(0, 6.28))
        self.sfx.play("sparkle")
        if random.random() < 0.45:
            self.say(random.choice(["别弄乱我的帽子~", "帽子是本体!",
                                    "哇,帽子要掉了啦"]), 2.0)

    def _on_escape(self, e):
        """Esc 收起魔法书(悬停提示随 _crystal_hover 自动消失)。"""
        if getattr(self, "_book_open", False):
            self._book_open = False
            return "break"
        return None

    def _ui_hit(self, kind, payload):
        """道具/面板命中分发(设计基准:各命中互不串扰)。"""
        self.last_interact = time.time()
        if kind.startswith('flat_'):
            from flat_workspace import action
            if action(self, kind, payload):
                return
        if kind == 'moon_quota':
            self.open_ai_panel()
            self._book_tab = 'overview'
            self._quota_provider = payload
            return
        if kind == 'moon_next':
            sessions = (getattr(self, '_swing', None) or {}).get('ui', {}).get('sessions') or []
            current = (getattr(self, '_swing', None) or {}).get('ui', {}).get('sel_session') or {}
            if sessions:
                index = next((i for i, row in enumerate(sessions) if row.get('id') == current.get('id')), -1)
                self._book_sel = ('sid', sessions[(index+1) % len(sessions)]['id'])
            return
        if kind == 'house_chat':
            self.open_chat()
            return
        if kind == 'house_trace':
            self.open_ai_panel()
            return
        if kind == 'house_quota':
            self.open_ai_panel()
            self._book_tab = 'overview'
            # Never change the selected workflow while inspecting an account.
            if getattr(self, '_quota_provider', None) is None:
                self._quota_provider = ('codex' if getattr(self, '_codex_quota', None)
                                        else 'claude' if getattr(self, '_quota', None)
                                        else 'zcode')
            return
        if kind == "swallow":
            return                      # 面板本体:不关闭、不拖动场景
        if kind in ("crystal", "book"):
            # 同一入口:点水晶或小书都开同一本书;再点收起
            self._book_open = not self._book_open
            if self._book_open and not self.ui_reduced_anim:
                self._book_anim = 0.0
        elif kind == "close":
            self._book_open = False
        elif kind == "tab":
            self._book_tab = payload or "overview"
            if payload == "trace":
                self.open_ai_panel()
        elif kind == "quota_provider":
            if payload in ("codex", "claude", "zcode"):
                self._quota_provider = payload
        elif kind == "chip":
            self._book_sel = ("agent", payload)     # 用户固定选中来源
            self._session_page = 0
        elif kind == "session":
            self._book_sel = ("sid", payload)       # 固定到具体会话
            self._session_page = 0
        elif kind == "ack" and payload:
            for s in getattr(self, "_ai_work_sessions", self._ai_sessions):
                if s["id"] == payload:
                    self._book_new_seen[payload] = len(s.get("actions") or [])
                    if self._trace_sid == payload:
                        self._trace_snap = list(s.get("actions") or [])
        elif kind == "sessions_page":
            self._session_page = payload
        elif kind == "detail":
            panel = getattr(self, "_ai_work_panel", None)
            if self.house_enabled() and (panel is None or panel.closed):
                self.open_ai_panel()
                if payload:
                    self._book_sel = ('sid', payload[0])
                sw = getattr(self, '_swing', None)
                if sw and sw.get('ui'):
                    self._sync_ai_panel(sw, sw['ui'])
                panel = getattr(self, '_ai_work_panel', None)
            if panel is not None and not panel.closed:
                panel.show_detail(payload)
        elif kind == "exp":
            if payload in self._trace_expand:
                self._trace_expand.discard(payload)
            else:
                self._trace_expand.add(payload)
        elif kind == "mute_sess" and payload:
            ms = getattr(self, "ai_mute_sess", set())
            if payload in ms:
                ms.discard(payload)
            else:
                ms.add(payload)
            self.ai_mute_sess = set(ms)
            self.save_settings()
        elif kind == "mute_src" and payload:
            muted = getattr(self, "ai_mute_sources", set())
            if payload in muted:
                muted.discard(payload)
                self.say(payload + " 的提醒打开啦~", 1.8)
            else:
                muted.add(payload)
                self.say(payload + " 的提醒静音了,灯还亮着~", 1.8)
            self.ai_mute_sources = set(muted)
            self.save_settings()
        elif kind == "pageup":
            self._trace_page += 1
            self._trace_expand = set()
        elif kind == "pagedown":
            self._trace_page = max(0, self._trace_page - 1)
            self._trace_expand = set()
        elif kind == "copy":
            act, res = payload or ("", "")
            text = (act + (" → " + res if res else "")).strip()
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(text)
                self._copied_until = time.time() + 1.4
            except Exception:
                pass

    def _draw_props_v2(self, d, sw, ui, hits):
        """收起态:右下一组道具 —— 24px 水晶挂件(状态内芯 + 选中来源的
        主要额度细金弧)+ 26px 合起小书。固定场景坐标,不随摆动缩放。"""
        now = ui.get("now") or time.time()
        gx, gy = ui["prop_rect"]
        scene_w = sw["scene_w"]
        scene_h = sw["scene_h"]
        cs = ui.get("crystal_state", "idle")
        tint = CRYSTAL_COLORS.get(cs, CRYSTAL_COLORS["idle"])
        hov = ui.get("crystal_hover")
        cx, cy = gx + 16, gy + 18
        # 水晶:状态只影响内芯与少量轮廓;运行中低幅慢呼吸
        pulse = (0.8 + 0.2 * math.sin(now * 1.5)) if cs == "running" else 1.0
        d.regular_polygon((cx, cy, 12), 6, rotation=30,
                          fill=(tint[0] // 3, tint[1] // 3, tint[2] // 3, 225),
                          outline=tint + ((255,) if hov else (210,)), width=1)
        d.regular_polygon((cx, cy, 7), 6, rotation=30,
                          fill=tint + (int(150 + 85 * pulse),))
        mk = CRYSTAL_MARK.get(cs, "")
        if mk:
            d.text((cx - 3, cy - 6), mk, font=load_font(9, sym=True),
                   fill=(16, 10, 28, 255))
        # 额度弧:只代表当前选中来源的主要窗口剩余;未知=中性虚线,
        # 过期=保留最后值+弧尾空心点。不显示假 0 / 假满额。
        q, qa = ui.get("quota"), ui.get("quota_age")
        if (ui.get("sel_key") == "claude" and q
                and isinstance(q.get("fh"), (int, float))):
            rem = max(0.0, min(100.0, 100.0 - float(q["fh"])))
            stale = qa is not None and qa > QUOTA_STALE_AFTER
            col = BOOK_GOLD + ((110,) if stale else (195,))
            end = -90 + 3.6 * rem
            d.arc((cx - 17, cy - 17, cx + 17, cy + 17), -90, end, fill=col, width=2)
            if stale:
                a = math.radians(end)
                ex, ey = cx + 17 * math.cos(a), cy + 17 * math.sin(a)
                d.ellipse((ex - 2.4, ey - 2.4, ex + 2.4, ey + 2.4),
                          outline=col, width=1)
        else:
            for a0 in range(-90, 250, 34):
                d.arc((cx - 17, cy - 17, cx + 17, cy + 17), a0, a0 + 20,
                      fill=(172, 162, 192, 130), width=1)
        # 其他来源的待处理事件角标
        badge = ui.get("badge") or {}
        if badge:
            worst = ("error" if any(v == "error" for v in badge.values())
                     else "waiting")
            bc = CRYSTAL_COLORS[worst]
            d.ellipse((cx + 8, cy - 16, cx + 15, cy - 9), fill=bc + (255,),
                      outline=(16, 10, 28, 230), width=1)
        # 合起的小书(26px):深紫封面 + 细金书脊 + 金扣
        bx, by = gx + 54, gy + 18
        d.rounded_rectangle((bx - 13, by - 10, bx + 13, by + 10), radius=2,
                            fill=(46, 30, 76, 242),
                            outline=BOOK_GOLD + (205,), width=1)
        d.line((bx - 4, by - 10, bx - 4, by + 10), fill=BOOK_GOLD + (175,), width=1)
        d.ellipse((bx + 5, by - 2, bx + 10, by + 3), fill=BOOK_GOLD + (235,))
        # 边角装饰:细金搁线
        d.line((gx - 4, gy + 38, gx + 78, gy + 38), fill=BOOK_GOLD + (85,), width=1)
        d.ellipse((gx - 6, gy + 37, gx - 2, gy + 41), fill=BOOK_GOLD + (130,))
        # 命中区 ≥32px
        hits.append((cx - 16, cy - 16, 32, 32, "crystal", None))
        hits.append((bx - 16, by - 16, 32, 32, "book", None))
        # 悬停 350ms 后的小提示:面板随内容自适应宽高,文字永不溢出
        tip = ui.get("tooltip")
        if tip:
            f11, f10 = load_font(11), load_font(10)
            lines = tip.get("lines") or []
            widths = []
            for i, t in enumerate(lines):
                fnt = f11 if i == 0 else f10
                try:
                    widths.append(fnt.getlength(t))
                except Exception:
                    widths.append(len(t) * 10)
            tw = int(max(150, min(300, max(widths) + 22)))
            th = 14 + 17 * len(lines) + 8
            tx, ty = gx + 92, gy - 8
            if tx + tw > scene_w - 8:           # 靠右边缘 → 换到道具左侧
                tx = gx - tw - 10
            ty = max(6, min(ty, scene_h - th - 8))
            d.rounded_rectangle((tx, ty, tx + tw, ty + th), radius=6,
                                fill=(20, 13, 34, 244),
                                outline=BOOK_GOLD + (140,), width=1)
            ty2 = ty + 7
            for i, t in enumerate(lines):
                col = (BOOK_INK + (255,)) if i == 0 else                     ((BOOK_GOLD + (235,)) if i == len(lines) - 1
                     and "额度" in t else (BOOK_DIM + (255,)))
                d.text((tx + 9, ty2), t, font=(f11 if i == 0 else f10),
                       fill=col)
                ty2 += 17


    def _book_base(self, w, h, r=20):
        """Quiet dark magical-book surface, cached by size."""
        key = ("apple_book", w, h, r)
        hit = self.glow_cache.get(key)
        if hit is None:
            import apple_ui
            hit = apple_ui.panel(w, h, r)
            self.glow_cache[key] = hit
        return hit

    def _draw_book_v2(self, canvas, d, sw, ui, hits):
        """One layout for content and hit targets.  ``ui_scale`` (the detached
        reader on a high-DPI screen) draws it larger; hits come back in pixels."""
        from ai_work_ui import render_content
        s = ui.get("ui_scale") or 1.0
        x, y, w, h = ui["book_rect"]
        page, local_hits = render_content(self, ui, w, h, s)
        x, y = round(x * s), round(y * s)
        base, pad = self._book_base(page.width, page.height, round(20 * s))
        ea = ui.get("book_anim", 1.0)
        e = ea * ea * (3 - 2 * ea)
        if e < 1:
            page.putalpha(page.getchannel("A").point(lambda a: int(a*e)))
            base = base.copy()
            base.putalpha(base.getchannel("A").point(lambda a: int(a*e)))
        self._ac(canvas, base, x-pad, y-pad)
        self._ac(canvas, page, x, y)
        hits.extend((x+hx*s, y+hy*s, hw*s, hh*s, kind, payload)
                    for hx, hy, hw, hh, kind, payload in local_hits)

    def _sync_ai_panel(self, sw, ui):
        """Keep the opened book beside the scene, without covering the character."""
        panel = getattr(self, "_ai_work_panel", None)
        if not self._book_open:
            if panel is not None and not panel.closed:
                panel.close(change_state=False)
            return
        from ai_work_ui import AIWorkPanel
        scene = (sw["scene_l"], sw["scene_t"], sw["scene_w"], sw["scene_h"])
        area = work_area_at(scene[0]+scene[2]/2, scene[1]+scene[3]/2) or (0, 0, self.sw, self.sh)
        if panel is not None and not panel.closed and panel.dragged:
            area = work_area_at(panel.win.winfo_x()+panel.size[0]/2,
                                panel.win.winfo_y()+panel.size[1]/2) or area
        # 和聊天窗同一个界面倍率:高分屏上字和聊天记录一样大(BOOK_W/H 是 100% 逻辑像素)
        u = ChatBox._layout(self.sw, self.sh)[0]
        body = (min(BOOK_W, int((area[2]-area[0]-16)/u) - 24),
                min(BOOK_H, int((area[3]-area[1]-16)/u) - 24))
        if panel is None or panel.closed:
            panel = self._ai_work_panel = AIWorkPanel(self, size=body, scale=u)
        else:
            panel.resize(body, u)
        ui["detached"] = True
        avoid = ()
        cb = getattr(self, "chatbox", None)
        try:
            if cb is not None and cb.win.winfo_exists() and cb.win.winfo_ismapped():
                avoid = ((cb.win.winfo_x(), cb.win.winfo_y(), cb.win.winfo_width(),
                          cb.win.winfo_height()),)       # 聊天窗开着就别盖住它
        except Exception:
            avoid = ()
        panel.update(ui, scene, area, avoid)

    # ==================== 秋千原画场景(assets/scene/) ====================
    # 画布 = 一个分层窗口(主窗口本体,可点可拖):横杆 → 前后荡的「绳+坐垫+她」
    # → 魔法书/水晶灯 → 这一帧的特效/气泡/灯板 → 书面板。坐标都按"原画缩放
    # 坐标"(原画 px × k)算,画布左上角 O 也在这套坐标里。
    def _art_geo(self, scene_scale):
        """k = 屏幕 px / 原画 px:她坐在秋千上和落地时一样大,再乘场景缩放。
        画布取「原画内容 ∪ 渲染帧 small 映射过来的范围」:气泡、灯板、卷轴
        都画在 small 里,画布小了会被裁掉。"""
        sa = self._scene_art
        gx0, gy0, gx1, gy1 = sa.girl_bbox
        spr_h = self._spr_disp_h()
        k = spr_h / (gy1 - gy0) * scene_scale
        spr_w = spr_h * self.main_src.width / self.main_src.height
        # small 帧里"那只没画出来的立绘"左上角(1x 窗口坐标,不含呼吸起伏)
        sl = (self.W / 2 - self._sprite_center_rel * spr_w, self.FOOT_Y - spr_h)
        gtl = (gx0 * k, gy0 * k)

        def s2a(px, py):
            return ((px - sl[0]) * scene_scale + gtl[0],
                    (py - sl[1]) * scene_scale + gtl[1])
        studio = self.studio_enabled()
        if studio:
            stand = self._studio()
            bx0, by0, bx1, by1 = stand.bounds()
            u = ChatBox._layout(self.sw, self.sh)[0]
            cap_h = round(24 * u)
            cap_top = stand.floor + 58
            cb = (min(gx0, bx0), min(0, by0), max(gx1, bx1), cap_top + (cap_h + 18) / k)
        else:
            cb = sa.content_box()
        mx = (cb[2] - cb[0]) * k * 0.05 + 4        # 透视变宽的余量
        fx0, fy0 = s2a(0, 0)
        fx1, fy1 = s2a(self.W, self.H)
        x0, y0 = min(cb[0] * k - mx, fx0), min(cb[1] * k, fy0)
        x1, y1 = max(cb[2] * k + mx, fx1), max(cb[3] * k + 4, fy1)
        # 胸口:渲染帧整块跟着它的透视位移/缩放走
        anchor = ((gx0 + gx1) / 2 * k, (gy0 + (gy1 - gy0) * 0.45) * k)
        geo = {"k": k, "ss": scene_scale, "O": (x0, y0),
               "size": (int(math.ceil(x1 - x0)), int(math.ceil(y1 - y0))),
               "sl": sl, "gtl": gtl, "anchor": anchor}
        if studio:
            geo["studio"] = {"floor": stand.floor * k - y0, "cx": stand.center_x * k - x0,
                             "cap_y": cap_top * k - y0, "cap_h": cap_h,
                             "cap_w": int(min((stand.x_rf - stand.x_lf + 160) * k, 380 * u))}
        if self.house_enabled():
            # 小屋:同一套 k/锚点,只是画布换成「房间 ∪ 原秋千画布」。横杆藏在
            # 檐下帘幔后(从天花挂下来),帘/柱/台是前景层,真的挡在她前面
            from house_scene import layout
            house = layout(k, (x0, y0, x1, y1), self._house_room())
            geo.update(art_size=geo['size'], house_layout=house,
                       O=house.O, size=house.size)
            if getattr(self, '_moon_house_style', False):
                geo['moon_house'] = True
        if getattr(self, '_flat_panel_style', False):
            from flat_workspace import geometry
            return geometry(self, geo)
        return geo

    def _art_regeo(self, sw, scene_scale):
        """换场景缩放 / 换桌宠大小:按同一个场景中心重排画布。"""
        cx = sw["scene_l"] + sw["scene_w"] / 2
        cy = sw["scene_t"] + sw["scene_h"] / 2
        scene_scale = self._limit_house_scale(scene_scale, sw)
        geo = self._art_geo(scene_scale)
        cw, ch = geo["size"]
        sw.update(geo=geo, scene_scale=scene_scale, scene_w=cw, scene_h=ch,
                  scene_l=int(cx - cw / 2), scene_t=int(cy - ch / 2))
        sw["scene_cx"] = sw["scene_l"] + cw // 2
        sw["rect"] = (sw["scene_l"], sw["scene_t"],
                      sw["scene_l"] + cw, sw["scene_t"] + ch)
        sw.pop("scene_canvas", None)
        self._ks_cache.clear()
        self._art_face_cache.clear()

    def _art_small_map(self, sw):
        """渲染帧 small(1x 窗口坐标)→ 场景画布:返回 (ox, oy, 缩放)。
        画布点 = small 点 × 缩放 + (ox, oy)。"""
        geo, sa = sw["geo"], self._scene_art
        g = sa.swing_geometry(geo["k"])
        th = sw.get("theta", 0.0)
        ax, ay = geo["anchor"]
        ax2, ay2 = sa.fwd(g, ax, ay, th, SWING_PERSP)
        R = max(1.0, g["seat"] - sa._pivot_y(g, g["cx"]))
        s_loc = 1.0 + SWING_PERSP * (max(0.0, ay - sa._pivot_y(g, ax)) / R) * math.sin(th)
        ss0 = geo["ss"]
        ox = ax2 + (geo["gtl"][0] - geo["sl"][0] * ss0 - ax) * s_loc - geo["O"][0]
        oy = ay2 + (geo["gtl"][1] - geo["sl"][1] * ss0 - ay) * s_loc - geo["O"][1]
        return ox, oy, ss0 * s_loc

    @staticmethod
    def _ac(canvas, img, x, y):
        """alpha_composite 不接受负坐标:超出画布左/上的部分先裁掉。"""
        x, y = int(round(x)), int(round(y))
        sx, sy = max(0, -x), max(0, -y)
        if sx >= img.width or sy >= img.height or x >= canvas.width or y >= canvas.height:
            return
        if sx or sy:
            img = img.crop((sx, sy, img.width, img.height))
        canvas.alpha_composite(img, (max(0, x), max(0, y)))

    def _art_face_overlay(self, key, k):
        """原画里的眨眼/情绪眼睑/情绪嘴/唱歌嘴:在立绘 spr2(脸部像素和原画是
        同一批)上照常画,只取"画了以后变了的像素"贴回原画。按 (键, k) 缓存。"""
        if not key:
            return None
        style, phase, blink, lid, em = key
        if not style and not blink and lid <= 0.02 and not em:
            return None
        ck = (key, round(k, 4))
        hit = self._art_face_cache.get(ck)
        if hit is not None:
            self._art_face_cache.move_to_end(ck)
            return hit or None
        base = self.spr2
        painted = self._face_texture(None, key, base=base)
        m = ImageChops.difference(painted, base).convert("L").point(
            lambda v: 255 if v > 3 else 0).filter(ImageFilter.MaxFilter(3))
        bb = m.getbbox()
        res = False
        if bb:
            bb = (max(0, bb[0] - 3), max(0, bb[1] - 3),
                  min(base.width, bb[2] + 3), min(base.height, bb[3] + 3))
            crop = painted.crop(bb)
            crop.putalpha(ImageChops.multiply(
                crop.getchannel("A"),
                m.crop(bb).filter(ImageFilter.GaussianBlur(1.0))))
            sa = self._scene_art
            k2 = base.height / (sa.girl_bbox[3] - sa.girl_bbox[1])
            f = k / k2
            img = crop.resize((max(1, round(crop.width * f)),
                               max(1, round(crop.height * f))), Image.LANCZOS)
            res = (img, ((sa.girl_bbox[0] + bb[0] / k2) * k,
                         (sa.girl_bbox[1] + bb[1] / k2) * k))
        self._art_face_cache[ck] = res
        while len(self._art_face_cache) > 24:
            self._art_face_cache.popitem(last=False)
        return res or None

    def _art_props_boxes(self, sw):
        """书 / 水晶在场景画布里的包围盒 (x, y, w, h)。固定,不随摆动。"""
        geo = sw["geo"]
        L = self._scene_art.scaled(geo["k"])
        out = {}
        for n in ("book", "crystal"):
            im, pos = L[n]
            out[n] = (pos[0] - geo["O"][0], pos[1] - geo["O"][1], im.width, im.height)
        return out

    def _art_glow(self, rgb, radius):
        """状态色的柔光(水晶身后),按 (颜色, 半径) 缓存。"""
        key = ("art_glow", rgb, int(radius))
        g = self.glow_cache.get(key)
        if g is None:
            r = max(4, int(radius))
            g = Image.new("RGBA", (r * 2, r * 2), (0, 0, 0, 0))
            ImageDraw.Draw(g).ellipse((r * 0.35, r * 0.35, r * 1.65, r * 1.65),
                                      fill=rgb + (255,))
            g = g.filter(ImageFilter.GaussianBlur(r * 0.32))
            self.glow_cache[key] = g
            while len(self.glow_cache) > 48:
                self.glow_cache.popitem(last=False)
        return g

    def _draw_props_art(self, canvas, sw, ui, hits):
        """原画里的魔法书和水晶灯:水晶按 AI 状态着色(运行中慢呼吸)、贴着
        金环画额度弧、其他来源有待处理时亮角标;悬停 350ms 出小提示。
        命中 kind 仍是 "crystal"/"book"(_ui_hit / on_hover 按这个分发)。"""
        geo, sa = sw["geo"], self._scene_art
        k, O = geo["k"], geo["O"]
        L = sa.scaled(k)
        now = ui.get("now") or time.time()
        d = ImageDraw.Draw(canvas, "RGBA")
        boxes = self._art_props_boxes(sw)
        # 书
        bx, by, bw, bh = boxes["book"]
        if ui.get("book_panel"):
            self._ac(canvas, self._art_glow((242, 193, 78), bw * 0.42),
                     bx + bw / 2 - bw * 0.42, by + bh / 2 - bw * 0.42)
        self._ac(canvas, L["book"][0], bx, by)
        # 水晶:身后一团状态色柔光 + 宝石上一层淡淡的同色
        cs = ui.get("crystal_state", "idle")
        tint = CRYSTAL_COLORS.get(cs, CRYSTAL_COLORS["idle"])
        cx, cy = sa.crystal_c[0] * k - O[0], sa.crystal_c[1] * k - O[1]
        rr = sa.crystal_r * k
        pulse = (0.7 + 0.3 * math.sin(now * 1.5)) if cs == "running" else 1.0
        if cs != "idle" or ui.get("crystal_hover"):
            gl = self._art_glow(tint, rr * 0.95)
            if pulse < 0.999:
                gl = gl.copy()
                gl.putalpha(gl.getchannel("A").point(lambda v: int(v * pulse)))
            self._ac(canvas, gl, cx - gl.width / 2, cy - gl.height / 2)
        cbx, cby, cbw, cbh = boxes["crystal"]
        self._ac(canvas, L["crystal"][0], cbx, cby)
        if cs != "idle":
            core = self._art_glow(tint, rr * 0.42)
            core = core.copy()
            core.putalpha(core.getchannel("A").point(lambda v: int(v * 0.55 * pulse)))
            self._ac(canvas, core, cx - core.width / 2, cy - core.height / 2)
        mk = CRYSTAL_MARK.get(cs, "")
        if mk:
            f = load_font(max(9, int(rr * 0.30)), sym=True)
            d.text((cx, cy - rr * 0.72), mk, font=f, anchor="mm",
                   fill=(255, 255, 255, 240), stroke_width=2, stroke_fill=(30, 18, 50, 230))
        # 额度弧:选中来源是 Claude 且有额度数据时,沿金环外缘画剩余比例
        q, qa = ui.get("quota"), ui.get("quota_age")
        ar = rr * 1.06
        if (ui.get("sel_key") == "claude" and q
                and isinstance(q.get("fh"), (int, float))):
            rem = max(0.0, min(100.0, 100.0 - float(q["fh"])))
            stale = qa is not None and qa > QUOTA_STALE_AFTER
            col = BOOK_GOLD + ((110,) if stale else (215,))
            end = -90 + 3.6 * rem
            d.arc((cx - ar, cy - ar, cx + ar, cy + ar), -90, end, fill=col,
                  width=max(2, int(rr * 0.05)))
            if stale:
                a = math.radians(end)
                ex, ey = cx + ar * math.cos(a), cy + ar * math.sin(a)
                d.ellipse((ex - 3, ey - 3, ex + 3, ey + 3), outline=col, width=1)
        # 其他来源的待处理事件:右上角标
        badge = ui.get("badge") or {}
        if badge:
            worst = "error" if any(v == "error" for v in badge.values()) else "waiting"
            r = max(4, rr * 0.10)
            bxx, byy = cbx + cbw * 0.86, cby + cbh * 0.12
            d.ellipse((bxx - r, byy - r, bxx + r, byy + r),
                      fill=CRYSTAL_COLORS[worst] + (255,),
                      outline=(16, 10, 28, 230), width=1)
        # 命中区:各自位图的包围盒往里收一点(透明角落不挡桌面)
        for (x, y, w, h), kind in ((boxes["crystal"], "crystal"),
                                   (boxes["book"], "book")):
            hits.append((x + w * 0.10, y + h * 0.08, w * 0.80, h * 0.84, kind, None))
        tip = ui.get("tooltip")
        if tip:
            f11, f10 = load_font(11), load_font(10)
            lines = tip.get("lines") or []
            widths = []
            for i, t in enumerate(lines):
                fnt = f11 if i == 0 else f10
                try:
                    widths.append(fnt.getlength(t))
                except Exception:
                    widths.append(len(t) * 10)
            tw = int(max(150, min(300, max(widths) + 22)))
            th = 14 + 17 * len(lines) + 8
            tx = cbx - tw - 6                   # 水晶在右下:提示放它左边
            ty = cby + cbh * 0.1
            tx = max(6, min(tx, canvas.width - tw - 6))
            ty = max(6, min(ty, canvas.height - th - 6))
            tp, tpad = ui3d.calm_panel(tw, th, 12, k=1.0, studs=False,
                                  glow=None if cs == "idle" else tint)
            self._ac(canvas, tp, tx - tpad, ty - tpad)
            ty2 = ty + 7
            for i, t in enumerate(lines):
                col = ((BOOK_INK + (255,)) if i == 0 else
                       (BOOK_GOLD + (235,)) if i == len(lines) - 1 and "额度" in t
                       else (BOOK_DIM + (255,)))
                d.text((tx + 9, ty2), t, font=(f11 if i == 0 else f10), fill=col)
                ty2 += 17

    def _art_pose(self, phase):
        """这一帧的 2.5D 姿态(给 SceneArt.pose_keystone):视线取渲染里那份有
        滞后的头部跟随,帽子/发梢取次级物理弹簧,呼吸按时钟。全部量化,
        静止时缓存几乎总是命中;没配 rig 就返回 None(退回 portrait_view)。"""
        sa = self._scene_art
        if sa is None or not getattr(sa, "_rig", None):
            return None
        dp = getattr(self, "_last_depth_pose", None) or (0.0,) * 6
        lx = round(max(-1.0, min(1.0, dp[0])) * 8) / 8
        ly = round(max(-1.0, min(1.0, dp[1])) * 8) / 8
        if (getattr(self, '_moon_house_style', False)
                and not getattr(self, '_nap_on_swing', False)
                and not getattr(self, 'ui_reduced_anim', False)):
            now = time.time()
            current = (getattr(self, '_swing', None) or {}).get('ui', {}).get('sel_session') or {}
            if now < getattr(self, '_moon_look_until', 0):
                lx = min(1.0, lx+.375)
            elif current.get('state') == 'running' and not current.get('stale') and not ai_session_stale(current, now):
                lx = min(1.0, lx+.125)
        seat = self.__dict__.get("_seat_motion")
        if seat is not None:
            # 坐姿动作(I-40):视线按时间轴缓入缓出地盖过头部跟随,同样量化进缓存键
            gx, gy = seat.gaze(time.time(), (lx, ly))
            lx = round(max(-1.0, min(1.0, gx)) * 8) / 8
            ly = round(max(-1.0, min(1.0, gy)) * 8) / 8
        lf = getattr(self, "life", None)

        def dz(v, dead, step):
            # 死区 + 量化:微风里的细抖不进缓存键,真被推/被点的摆动照样出来
            return 0.0 if abs(v) < dead else round(v / step) * step
        rot = dz(life.clamp(lf.hat_rot.x * 1.8, -0.07, 0.07), 0.008, 0.01) if lf else 0.0
        hdx = dz(life.clamp(lf.hat_dx.x * 1.6, -9.0, 9.0), 1.0, 1.0) if lf else 0.0
        hair = dz(life.clamp(lf.hair.x * 1.4, -9.0, 9.0), 1.0, 1.0) if lf else 0.0
        # 呼吸跟着秋千的相位走(一个来回一口气,3.4 秒正好是平静呼吸的节奏):
        # 它只由摆角和摆动方向决定,摆起来一圈一圈的缓存就能复用
        sw = getattr(self, "_swing", None) or {}
        om = sw.get("omega", 0.0)
        w0 = 2 * math.pi / SWING_PERIOD
        br = round(math.sin(math.atan2(-om / w0, sw.get("theta", phase))) * 4) / 4
        if self.state == "sleep" or getattr(self, "_nap_on_swing", False):
            br *= 1.4                       # 睡着时呼吸更深
        if seat is not None:
            br = round(max(-1.4, min(1.4, seat.breath(time.time(), br))) * 4) / 4
        q = (lx, ly, rot, hdx, hair, br)
        return {"look": (lx, ly), "hat": (rot, hdx), "hair": hair, "breath": br,
                "theta": phase, "q": q}

    def _art_orbit_follow(self, items, k):
        """帽檐星轨的点按帽子的 2.5D 位移平移(帧坐标,SS 倍)。用帽檐中心那
        一点的位移整体平移 —— 星轨是绕着帽子的一圈,跟着帽子走就对了。"""
        sa = self._scene_art
        pose = self._art_pose(0.0)
        if not items or sa is None or pose is None:
            return items
        gx0, gy0, gx1, gy1 = sa.girl_bbox
        cx = gx0 + HAT_ORBIT[0] / HAT_ORBIT_ART[0] * (gx1 - gx0)
        cy = gy0 + HAT_ORBIT[1] / HAT_ORBIT_ART[1] * (gy1 - gy0)
        dx, dy = sa.pose_displacement(cx, cy, pose)
        f = self._spr_disp_h() / (gy1 - gy0) * k          # 原画 px → SS 帧 px
        return [(n, X + dx * f, Y + dy * f, dep, near, lv)
                for n, X, Y, dep, near, lv in items]

    def _art_hat_hit(self, ex, ey):
        """场景画布上的点是不是落在帽子上(按 rig 帽子区;摆动的位移忽略)。"""
        sw, sa = getattr(self, "_swing", None), self._scene_art
        if not sw or not sw.get("art") or sa is None or not getattr(sa, "_rig", None):
            return False
        geo = sw["geo"]
        ax = (ex + geo["O"][0]) / geo["k"]
        ay = (ey + geo["O"][1]) / geo["k"]
        return sa._rig_w("hat", ax, ay) > 0.5 and sa._rig_w("face", ax, ay) < 0.3

    def _art_seat_hit(self, ex, ey):
        """场景画布上的点是不是落在坐垫/腿脚上(原画 y≥SEAT_ZONE_Y,人物包围盒内)。"""
        sw, sa = getattr(self, "_swing", None), self._scene_art
        if not sw or not sw.get("art") or sa is None:
            return False
        geo = sw["geo"]
        ax = (ex + geo["O"][0]) / geo["k"]
        ay = (ey + geo["O"][1]) / geo["k"]
        gx0, gy0, gx1, gy1 = sa.girl_bbox
        return gx0 <= ax <= gx1 and seat_motion.SEAT_ZONE_Y <= ay <= gy1

    # ---- 秋千坐姿动作(I-40):套一陪你干活 + 套二摸摸她,时间轴在 seat_motion ----
    def _seat(self):
        seat = self.__dict__.get("_seat_motion")
        if seat is None:
            seat = self._seat_motion = seat_motion.SeatMotion()
        return seat

    def _seat_allowed(self):
        """只在秋千上、且没有减少动画/打盹/唱歌/拖动时播。"""
        return (self.state == "swing" and bool(self._swing)
                and not getattr(self, "ui_reduced_anim", False)
                and not getattr(self, "_nap_on_swing", False)
                and not getattr(self, "singing", False)
                and not (self.drag and self.drag[4])
                and not (getattr(self, "_scene_drag", None) or {}).get("moved"))

    def start_seat_action(self, name, side=1):
        """播一个坐姿动作。不允许时返回 False(调用方走原来的反馈);
        正在播更高优先级的动作时也返回 False。眼睑/情绪嘴走 _offer_lid,被占着就排队。"""
        if not self._seat_allowed():
            return False
        now = time.time()
        if not self._seat().start(name, now, side):
            return False
        spec = seat_motion.ACTIONS[name]
        if spec.get("lid"):
            lid, mode, hold = spec["lid"]
            self._offer_lid(lid, mode, now, hold)
        if spec.get("mouth"):
            self._mouth = (spec["mouth"][0], now + spec["mouth"][1])
        return True

    def _seat_swing_step(self, sw, dt, now):
        """秋千钟摆走一步:坐姿动作要她停住时临时加大阻尼、不泵;再把到点的帽尖/秋千冲量打出去。
        打盹也会改阻尼,所以只在这一步里改,算完原样还回去。"""
        seat = self.__dict__.get("_seat_motion")
        hold = bool(seat and seat.holding(now))
        pend = sw["pend"]
        damping = pend.damping
        if hold:
            pend.damping = seat_motion.HOLD_DAMPING
        try:
            theta, omega = pend.step(dt, pump=(now - self.last_interact) < 45 and not hold)
        finally:
            pend.damping = damping
        for channel, dv in (seat.due(now) if seat else ()):
            if channel == "hat":
                self.life.hat_rot.impulse(dv)
            elif channel == "swing":
                pend.impulse(dv)
                theta, omega = pend.theta, pend.omega
        return theta, omega

    def _seat_hat_click(self):
        """B2 弹帽尖:原来的帽子星星/台词照旧,帽尖用看得见的冲量,她抬头看。"""
        self.wobble_hat()
        if not self.start_seat_action("flick", random.choice((-1, 1))):
            self._swing_impulse(0.05)

    def _seat_head_click(self):
        """B1 摸头蹭手心:秋千放慢、低头蹭两下(不能播时退回原来的摸头+推一下)。"""
        self.pet_head()
        if not self.start_seat_action("pat"):
            self._swing_impulse(0.10)

    def _seat_push(self):
        """B3 推一把:秋千荡起来,她开心地看前面。不能播时和原来一样当摸头。"""
        if self.start_seat_action("push"):
            self._swing_impulse(seat_motion.PUSH_IMPULSE)
        else:
            self.pet_head()
            self._swing_impulse(0.10)

    def _seat_long_press(self, d, x):
        """B4 长按害羞:按住没挪动才算;扭头躲开按下的那一侧。"""
        if getattr(self, "_scene_drag", None) is not d or d.get("moved"):
            return False
        sw = self._swing or {}
        geo, sa = sw.get("geo") or {}, self._scene_art
        side = 1
        if sa is not None and geo.get("k"):
            face = sa.meta.get("face") or {}
            eyes = (face.get("eye_l", (610, 520)), face.get("eye_r", (737, 554)))
            fx = (eyes[0][0] + eyes[1][0]) / 2 * geo["k"] - geo["O"][0]
            side = 1 if x >= fx else -1   # 点在脸右边 → 往左躲(shy 的视线是负向)
        if not self.start_seat_action("shy", side):
            return False
        d["seat"] = "shy"
        self.last_interact = time.time()
        return True

    def _art_ground_shadow(self, canvas, sw, phase):
        geo, sa = sw["geo"], self._scene_art
        k, O = geo["k"], geo["O"]
        gx0, gy0, gx1, gy1 = sa.girl_bbox
        s = math.sin(phase)
        w = (gx1 - gx0) * k * (0.62 + 0.10 * s)
        h = max(6.0, w * 0.11)
        cx = (gx0 + gx1) / 2 * k - O[0]
        cy = min(canvas.height - h / 2 - 1, gy1 * k - O[1] + h * 0.9)
        if geo.get('studio'):
            # 工作室:落在支架脚下那条地面线上,更扁更淡,像产品照里的影子
            w *= 0.78
            h = max(5.0, w * 0.09)
            cy = geo['studio']['floor'] - h * (0.2 - 0.25 * s)
        if geo.get('house_layout'):
            # 小屋地板上、秋千所在深度的那条线。窗光从她身后高处来,影子往前
            # (屏幕下方)落一点;荡近略往前,荡远略往后。比裸桌面上更实
            w *= 0.82
            h = max(6.0, w * 0.13)
            cy = geo['house_layout'].floor_y + h * (0.6 + 0.35 * s)
        a = int((112 if geo.get('house_layout') else 60 if geo.get('studio') else 78)
                * (1.0 - 0.35 * abs(s)) * (0.85 if s > 0 else 1.0))
        key = ("art_shadow", int(w), int(h), a)
        img = self.glow_cache.get(key)
        if img is None:
            pad = int(h)
            img = Image.new("RGBA", (int(w) + 2 * pad, int(h) + 2 * pad), (14, 8, 30, 0))
            m = Image.new("L", img.size, 0)
            ImageDraw.Draw(m).ellipse((pad, pad, pad + w, pad + h), fill=a)
            img.putalpha(m.filter(ImageFilter.GaussianBlur(h * 0.45)))
            self.glow_cache[key] = img
            while len(self.glow_cache) > 64:
                self.glow_cache.popitem(last=False)
        self._ac(canvas, img, cx - img.width / 2, cy - img.height / 2)

    def _house_ground_shadow(self, canvas, sw, swing_hit, phase):
        """Project the existing alpha onto the room floor, without changing
        the swing's face, grip or seat geometry. One cast shadow, no ellipse."""
        from house_shadow import HouseShadow
        renderer = getattr(self, '_house_shadow_renderer', None)
        if renderer is None:
            room = self._house_room()
            if room is None:
                return
            renderer = self._house_shadow_renderer = HouseShadow(room)
        # The room compositor may reuse a quantized camera frame while gliding.
        # Its visible view, rather than the next target, anchors the shadow.
        room_renderer = getattr(self, '_house_renderer', None)
        room_hit = getattr(room_renderer, '_last_hit', None)
        view = room_hit[0][3] if room_hit else getattr(self, '_house_view', (0.0, 0.0))
        geo = sw['geo']
        offset = (swing_hit[1][0]-geo['O'][0], swing_hit[1][1]-geo['O'][1])
        shadow, at = renderer.render(swing_hit[0], offset, geo['house_layout'], phase, view)
        self._ac(canvas, shadow, *at)

    def _house_layers(self, sw):
        if sw['geo'].get('moon_house'):
            from moon_house import MoonRenderer as HouseRenderer
        else:
            from house_scene import HouseRenderer
        renderer = getattr(self, '_house_renderer', None)
        if renderer is None:
            renderer = self._house_renderer = HouseRenderer(os.path.join(ASSETS, 'house'))
            renderer.min_interval = .1
        now = time.time()
        dt = min(.12, max(0, now-getattr(self, '_house_view_at', now)))
        target = getattr(self, '_house_pointer', (0.0, 0.0))
        if now-getattr(self, '_house_pointer_at', 0) > 2.0:
            target = (0.0, 0.0)
        old = getattr(self, '_house_view', (0.0, 0.0))
        amount = 1-math.exp(-dt*5)
        view = tuple(a+(b-a)*amount for a,b in zip(old,target))
        self._house_view, self._house_view_at = view, now
        return renderer.render(sw['geo']['house_layout'], view)

    def _room_life(self):
        """房间的环境生命(窗里星/月光、浮尘、架上水晶球、垂饰闪光);素材几何来自
        room-v2.json,读不到就不画。"""
        if getattr(self, '_moon_house_style', False):
            return None
        life = getattr(self, '_room_life_obj', None)
        if life is None:
            try:
                from room_life import RoomLife
                life = RoomLife(self._house_room())
            except (KeyError, TypeError, ValueError, ImportError):
                life = False
            self._room_life_obj = life
        return life or None

    def _room_sleep_level(self, now):
        """她在秋千上打盹/睡着时屋里慢慢暗下来(约 1.5 s),醒来再亮回去。"""
        target = 1.0 if (getattr(self, '_nap_on_swing', False) or getattr(self, 'state', '') == 'sleep') else 0.0
        level, at = getattr(self, '_room_dim', (0.0, now))
        if now - at > 1.0:
            level = target                 # the room was not on screen: no stale fade
        dt = min(.5, max(0.0, now - at))
        level += (target - level) * (1 - math.exp(-dt / .55))
        if abs(level - target) < .01:
            level = target
        self._room_dim = (level, now)
        return level

    def _house_rim(self, img):
        """小屋里她背后是亮窗:帽/发/肩的外轮廓加一道很淡的淡紫轮廓光,把她从
        深紫的屋里托出来(帽尖贴深墙时最需要)。只是受光,不是外发光:只提亮轮廓
        内侧约 2px,越往下越弱,座面以下没有。按缩放后的那张层缓存。"""
        hit = getattr(self, '_house_rim_cache', None)
        if hit is not None and hit[0] is img:
            return hit[1]
        a = img.getchannel('A')
        edge = ImageChops.subtract(a, a.filter(ImageFilter.MinFilter(5)))
        edge = ImageChops.multiply(edge.filter(ImageFilter.GaussianBlur(1.2)), a)
        fade = Image.linear_gradient('L').resize(img.size).point(
            lambda v: int(max(0.0, min(1.0, (.74 - v / 255) / .5)) * 150))   # 座面(.72)以下为 0
        edge = ImageChops.multiply(edge, fade)
        rgb = img.convert('RGB')
        lit = ImageChops.screen(rgb, Image.new('RGB', img.size, (226, 214, 255)))
        out = Image.composite(lit, rgb, edge).convert('RGBA')
        out.putalpha(a)
        self._house_rim_cache = (img, out)
        return out

    def _draw_studio_capsule(self, canvas, sw, ui, hits):
        """支架下方的状态胶囊:左边是 AI 工作流(点开轨迹),右边的环是 5 小时额度。"""
        from status_capsule import render_capsule
        g = sw['geo']['studio']
        img, local, _ = render_capsule(ui, g['cap_h'], g['cap_w'], time.time(),
                                       getattr(self, '_house_hover', None))
        x, y = g['cx'] - img.width / 2, g['cap_y']
        key = ('capsule_shadow', img.width, img.height)
        shade = self.glow_cache.get(key)
        if shade is None:
            pad = img.height
            shade = Image.new('RGBA', (img.width + 2 * pad, img.height + 2 * pad), (0, 0, 0, 0))
            ImageDraw.Draw(shade).rounded_rectangle(
                (pad, pad + img.height * .18, pad + img.width, pad + img.height * 1.18),
                radius=img.height // 2, fill=(0, 0, 0, 60))
            shade = self.glow_cache[key] = shade.filter(ImageFilter.GaussianBlur(img.height * .28))
        self._ac(canvas, shade, x - img.height, y - img.height)
        self._ac(canvas, img, x, y)
        hits.extend((x + hx, y + hy, hw, hh, kind, payload)
                    for hx, hy, hw, hh, kind, payload in local)

    def _draw_house_plaque(self, canvas, sw, ui, hits, shift):
        """台座正面的铭牌:一行大字(状态宝石 · 来源 · 状态 · 最新一步 · 5h 额度),
        点它打开完整的 AI 工作书页。铭牌嵌在前景台座上,随前景整像素平移。"""
        from house_ai_ui import render_plaque
        x, y, w, h = sw['geo']['house_layout'].plaque
        x, y = x + shift[0], y + shift[1]
        u = ChatBox._layout(self.sw, self.sh)[0]
        # 场景缩小时铭牌不跟着缩到看不清:至少一行正文高,超出台面的部分上下均分
        min_h = round(23 * u)
        if h < min_h:
            y -= (min_h - h) // 2
            h = min_h
        font_px = min(int(15 * u), round(h * .56))
        # 小场景里台面窄:铭牌向两侧长到两块标签读得全(最多房间宽的 88%),而不是缩成「工作流…」
        from house_ai_ui import preferred_width
        hl = sw['geo']['house_layout']
        band = (self._house_room() or {}).get('plaque_max')
        limit = int((band[1] - band[0]) * hl.scale) if band else w
        want = min(preferred_width(ui, h, font_px), limit)
        if want > w:
            x -= (want - w) // 2
            w = want
        key = repr((w, h, font_px, ui.get('sources'), ui.get('sel_key'), ui.get('sel_session'),
                    ui.get('quota'), ui.get('codex_quota'), ui.get('codex_quota_error'),
                    int((ui.get('quota_age') or 0)/60),
                    int((ui.get('now') or time.time())/30), ui.get('mock')))
        cached = getattr(self, '_house_plaque_cache', None)
        if not cached or cached[0] != key:
            image, local_hits = render_plaque(self, ui, (w, h), font_px)
            cached = self._house_plaque_cache = (key, image, local_hits)
        self._ac(canvas, cached[1], x, y)
        hover = getattr(self, '_house_hover', None)
        for hx, hy, hw, hh, kind, _pl in cached[2]:
            if kind == hover:
                # 悬停:这一块轻轻亮起、金边加深 —— 告诉你它能点
                lit = Image.new('RGBA', (max(1, int(hw)-2), max(1, int(h)-2)), (0, 0, 0, 0))
                ImageDraw.Draw(lit).rounded_rectangle(
                    (0, 0, lit.width-1, lit.height-1), radius=max(3, h//3-1),
                    fill=(255, 245, 225, 18), outline=(232, 204, 150, 170), width=1)
                self._ac(canvas, lit, x+hx+1, y+1)
        if not getattr(self, 'ui_reduced_anim', False):
            from house_ai_ui import gem_center, gem_motion
            rgb, glow = gem_motion(ui, time.time())
            if rgb and glow > .02:
                gx, gy, gr = gem_center(h)
                halo = _faded(self._gem_halo(gr, rgb), glow)
                hx0, hy0 = int(round(x+gx-halo.width/2)), int(round(y+gy-halo.height/2))
                inside = halo.crop((int(x)-hx0, int(y)-hy0, int(x)-hx0+int(w), int(y)-hy0+int(h)))
                mask = Image.new('L', inside.size, 0)
                ImageDraw.Draw(mask).rounded_rectangle((0, 0, inside.width-1, inside.height-1),
                                                       radius=max(4, int(h)//3), fill=255)
                inside.putalpha(ImageChops.multiply(inside.getchannel('A'), mask))
                self._ac(canvas, inside, int(x), int(y))
        hits.extend((x+hx, y+hy, hw, hh, kind, payload)
                    for hx, hy, hw, hh, kind, payload in cached[2])

    def _gem_halo(self, r, rgb):
        """铭牌宝石外圈的柔光(只在宝石外侧,不盖住首字母)。"""
        key = ('gem_halo', r, rgb)
        img = self.glow_cache.get(key)
        if img is None:
            from room_life import RoomLife
            img = RoomLife._glow(r * 2.0, tuple(rgb), hole=r * 1.04)
            self.glow_cache[key] = img
        return img

    def _push_swing_art(self, small):
        sw, sa = self._swing, self._scene_art
        if sw['geo'].get('flat'):
            from flat_workspace import push
            return push(self, small)
        geo = sw["geo"]
        k, O = geo["k"], geo["O"]
        cw, ch = geo["size"]
        canvas = sw.get("scene_canvas")
        if canvas is None or canvas.size != (cw, ch):
            canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
            sw["scene_canvas"] = canvas
        canvas.paste((0, 0, 0, 0), (0, 0, cw, ch))
        house_front = None
        life = dims = None
        if geo.get('house_layout'):
            house_back, house_front, front_at = self._house_layers(sw)
            if geo.get('moon_house'):
                bar, bar_at = sa.scaled(k)['static']
                self._ac(canvas, bar, bar_at[0]-O[0], bar_at[1]-O[1])
            canvas.alpha_composite(house_back)
            life, tnow = self._room_life(), time.time()
            sleepy = self._room_sleep_level(tnow)
            if life is not None:
                hl = geo['house_layout']
                dims = life.dim_layers(hl, house_back, house_front, sleepy)
                if dims[0] is not None:
                    canvas.alpha_composite(dims[0])
                if not getattr(self, 'ui_reduced_anim', False):
                    life.draw_behind(canvas, hl, getattr(getattr(self, '_house_renderer', None),
                                                         'last_view', (0.0, 0.0)), tnow, sleepy)
        L = sa.scaled(k)
        studio = geo.get("studio")
        if studio:
            stand_img, stand_at = self._studio().render(k)
            self._ac(canvas, stand_img, stand_at[0] - O[0], stand_at[1] - O[1])
        elif not geo.get("moon_house"):
            st, sp = L["static"]
            self._ac(canvas, st, sp[0] - O[0], sp[1] - O[1])
        # 绳+坐垫+她:先贴这一帧的五官补丁,再按摆角做透视变形(按量化摆角缓存)
        tq = round(sw.get("theta", 0.0) / 0.008)
        face_key = self._last_face_key
        # Depth follows the same quantized pendulum phase, so the seat, grip
        # and cached face patch cannot drift against an independently timed loop.
        phase = tq * .008
        pose = self._art_pose(phase)
        # 地面软影:荡近时影子大而淡,荡远时小而实 —— 场景不再像飘在桌面上的贴纸
        if not geo.get('house_layout'):
            self._art_ground_shadow(canvas, sw, phase)
        back = getattr(self, "_art_small_back", None)
        if back is not None:
            bx_, by_, bs_ = self._art_small_map(sw)
            if abs(bs_ - 1.0) > 1e-3:
                back = back.resize((max(1, int(back.width * bs_)),
                                    max(1, int(back.height * bs_))), Image.BILINEAR)
            self._ac(canvas, back.convert("RGBA"), bx_, by_)
        if pose is not None:
            ck = (tq, face_key, round(k, 4), pose["q"])
        else:
            portrait_view = (max(-1.0, min(1.0, phase / .12)),
                             max(-1.0, min(1.0, math.sin(phase) * 2.0)))
            ck = (tq, face_key, round(k, 4), portrait_view)
        hit = self._ks_cache.get(ck)
        if hit is None and pose is not None:
            # 只有呼吸/帽子/发梢这些"软"量在微动(摆角、视线、五官都没变)时,
            # 0.15 秒内沿用上一张:呼吸一口约 3.7 秒,每秒 7 档足够顺
            prev = getattr(self, "_ks_prev", None)
            hard = (tq, face_key, round(k, 4), pose["q"][:2])
            tnow = time.time()
            if prev and prev[0] == hard and tnow - prev[2] < 0.15:
                hit = prev[1]
        if hit is None:
            img, off = L["swing_studio"] if (studio or geo.get("moon_house")) and "swing_studio" in L else L["swing"]
            if geo.get('house_layout'):
                img = self._house_rim(img)                    # 身后窗光的轮廓光
            if pose is not None:
                img = sa.light_field(img, off, k, pose)       # 受光跟着转头/荡近荡远
            ov = self._art_face_overlay(face_key, k)
            if ov:
                img = img.copy()
                self._ac(img, ov[0], ov[1][0] - off[0], ov[1][1] - off[1])
            if pose is not None:
                hit = sa.pose_keystone(img, off, k, phase, SWING_PERSP, pose)
                self._ks_prev = ((tq, face_key, round(k, 4), pose["q"][:2]), hit, time.time())
            else:
                hit = sa.keystone(img, off, k, phase, SWING_PERSP,
                                  portrait_view=portrait_view)
            self._ks_cache.put(ck, hit)
        if geo.get('house_layout'):
            self._house_ground_shadow(canvas, sw, hit, phase)
        self._ac(canvas, hit[0], hit[1][0] - O[0], hit[1][1] - O[1])
        ui = sw.get("ui") or {}
        hits = []
        if not geo.get('house_layout') and not studio:
            self._draw_props_art(canvas, sw, ui, hits)
        # 这一帧的特效/气泡/灯板/卷轴(她本人在原画里,渲染时没画)
        if small.mode != "RGBA":
            small = small.convert("RGBA")
        ox, oy, ss = self._art_small_map(sw)
        if abs(ss - 1.0) > 1e-3:
            small = small.resize((max(1, int(small.width * ss)),
                                  max(1, int(small.height * ss))), Image.BILINEAR)
        if house_front is not None:
            # 前景框(檐/帘/柱/台)挡在秋千前面;气泡、特效、zzz 仍在最上层
            canvas.alpha_composite(house_front, front_at)
            if dims and dims[1] is not None:
                canvas.alpha_composite(dims[1], front_at)
            if life is not None and not getattr(self, 'ui_reduced_anim', False):
                life.draw_front(canvas, geo['house_layout'], front_at, tnow, house_front)
        self._ac(canvas, small, ox, oy)
        lcr = getattr(self, "_chain_rect_local", None)      # SS 帧坐标
        self._chain_rect = ((ox + lcr[0] / SS * ss, oy + lcr[1] / SS * ss,
                             lcr[2] / SS * ss, lcr[3] / SS * ss) if lcr else None)
        if studio:
            self._draw_studio_capsule(canvas, sw, ui, hits)
        if geo.get('moon_house'):
            from moon_house import draw_board
            draw_board(self, canvas, sw, ui, hits)
        elif house_front is not None:
            hl = geo['house_layout']
            self._draw_house_plaque(canvas, sw, ui, hits,
                                    (front_at[0] - hl.room_origin[0],
                                     front_at[1] - hl.room_origin[1]))
        d2 = ImageDraw.Draw(canvas, "RGBA")
        if (ui.get("book_panel") and not ui.get("detached")
                and ui.get("book_anim", 0) > 0 and ui.get("book_rect")):
            self._draw_book_v2(canvas, d2, sw, ui, hits)
        for hx, hy, hw2, hh, _kind, _pl in hits:
            patch = Image.new("RGBA", (max(1, int(hw2)), max(1, int(hh))), (0, 0, 0, 1))
            self._ac(canvas, patch, hx, hy)
        sw["ui_hits"] = hits
        # 场景出现/切换小屋时 0.6 s 淡入,不是一下子「啪」地贴到桌面上
        f = min(1.0, max(0.0, (time.time() - sw.get("fade_at", sw.get("t0", 0.0))) / .6))
        push_layered(self.hwnd, canvas, sw["scene_l"], sw["scene_t"],
                     round(255 * f * f * (3 - 2 * f)))

    def _push_swing(self, small):
        """前后荡推送:渲染帧按 (scene_scale×透视) 缩放,臀点锚到场景
        座椅线,合成进场景画布后按场景坐标推送。"""
        sw = self._swing
        if sw.get("art"):
            return self._push_swing_art(small)
        theta = sw.get("theta", 0.0)
        persp = sw.get("persp", 1.0)
        S = sw.get("scene_scale", 1.0) * persp
        scene_w, scene_h = sw["scene_w"], sw["scene_h"]
        canvas = sw.get("scene_canvas")
        if canvas is None or canvas.size != (scene_w, scene_h):
            canvas = Image.new("RGBA", (scene_w, scene_h), (0, 0, 0, 0))
            sw["scene_canvas"] = canvas
        canvas.paste((0, 0, 0, 0), (0, 0, scene_w, scene_h))
        if small.mode != "RGBA":
            small = small.convert("RGBA")
        ow, oh = max(8, int(small.width * S)), max(8, int(small.height * S))
        scaled = (small.resize((ow, oh), Image.BILINEAR)
                  if abs(S - 1.0) > 1e-3 else small)
        # 臀点粘贴坐标必须是场景局部坐标(画布 (0,0) = 场景左上角)
        butt_x = (sw["scene_cx"] - sw["scene_l"]) - BUTT_X_REL * small.width * S
        # 臀点(髋折线)落在座面线上(+6S):座椅上表面真正承托臀部,
        # 前缘再压住裙摆 —— 接触点全程稳定,不漂移
        butt_y = (sw.get("bar_y", 8) - 2 + sw["R"] * math.cos(theta)
                  - 18 * S) - BUTT_Y_REL * small.height * S
        bx = int(min(scene_w - min(ow, scene_w - 4), max(4 - ow, butt_x)))
        by = int(min(scene_h - min(oh, scene_h - 4), max(4 - oh, butt_y)))
        canvas.alpha_composite(scaled, (bx, by))
        # 卷轴区域换算到画布坐标(思维链点击直达轨迹页)
        if getattr(self, "_chain_rect_local", None):
            l = self._chain_rect_local
            self._chain_rect = (bx + l[0], by + l[1], l[2], l[3])
        # 座椅前缘画在她之上(后座面在场景层、她身后):遮挡关系 =
        # 后椅面被她遮住,前缘合理压住臀部/裙摆下缘
        sf = sw.get("seat_front")
        if sf:
            canvas.alpha_composite(sf[0], sf[1])
            # 接触阴影画在可见座缘上:臀位正下方的柔和暗斑 + 裙摆下缘 AO,
            # 表达重量(层上的阴影被裙摆挡住看不见,重量要画在可见面上)
            d_c = ImageDraw.Draw(canvas, "RGBA")
            S_c = sw.get("scene_scale", 1.0) * sw.get("persp", 1.0)
            sx_c = sw["scene_cx"] - sw["scene_l"]
            sy_c = sw.get("bar_y", 8) + sw["R"] * math.cos(sw.get("theta", 0.0))
            hw0 = sw["hw"]
            for rx, vh, a in ((0.40, 5.5, 34), (0.27, 3.5, 50)):
                d_c.ellipse((sx_c - hw0 * S_c * rx, sy_c + (10 - vh) * S_c,
                             sx_c + hw0 * S_c * rx, sy_c + (10 + vh) * S_c),
                            fill=(36, 20, 58, a))
        # ---- UI 层(设计基准:小乔AI界面设计方案.md):水晶挂件 + 魔法书
        # 画在主画布(她之上),固定场景坐标,不随摆动/透视缩放 ----
        ui = sw.get("ui") or {}
        hits = []
        d2 = ImageDraw.Draw(canvas, "RGBA")
        if ui.get("prop_rect"):
            self._draw_props_v2(d2, sw, ui, hits)
        if (ui.get("book_panel") and not ui.get("detached")
                and ui.get("book_anim", 0) > 0 and ui.get("book_rect")):
            self._draw_book_v2(canvas, d2, sw, ui, hits)
        # 命中区域垫 alpha=1 隐形块:命中区比字形大(≥32px),空白处
        # alpha=0 照常穿透桌面,不吞点击
        for hx, hy, hw2, hh, _kind, _pl in hits:
            patch = Image.new("RGBA", (max(1, int(hw2)), max(1, int(hh))), (0, 0, 0, 1))
            canvas.alpha_composite(patch, (int(hx), int(hy)))
        sw["ui_hits"] = hits
        push_layered(self.hwnd, canvas, sw["scene_l"], sw["scene_t"])

    def toggle_swing(self):
        """荡秋千 / 从秋千上跳下来(菜单)。在秋千上点别的地面动作(跳舞、
        睡觉、喂糖…)由 _land_first 先下来、落地后再做。"""
        if self.state == "swing":
            self._swing_dismount("荡完啦,看我轻功下地~")
        else:
            self.start_swing()

    def mount_swing(self):
        """「上秋千/荡秋千」(聊天、{"op":"swing"}):幂等。已经坐着就
        用力荡一下 —— 她本来就住在秋千上,不能反把她叫下来。"""
        if self.state == "swing" and self._swing:
            self._swing_impulse(0.3)
            self.say(random.choice(["抓稳了,要荡咯~", "再荡高一点~"]), 2.0)
        else:
            self.start_swing()

    def dismount_swing(self):
        """「下秋千」(聊天、{"op":"swing","on":false}):幂等。"""
        if self.state == "swing":
            self._swing_dismount("荡完啦,看我轻功下地~")
        else:
            self.say("我现在没在秋千上呀~", 2.0)

    def toggle_swing_home(self):
        """「默认住在秋千上」:开机自动入座 + 空闲后自动回座。"""
        self.swing_home = not self.swing_home
        self.save_settings()
        if not self.swing_home:
            self._swing_remount = time.time() + 1e12
            self.say("好,想叫我荡的时候喊我哦~", 2.2)
        else:
            self._swing_remount = 0.0
            self.say("那我以后就住在秋千上啦~", 2.2)

    def start_swing(self, quiet=False):
        """入座:整个场景(锚点+绳+月牙+她)按上次的位置/大小恢复。"""
        if self.state in ("sleep", "yawn") or self.drag:
            return
        if self.state == "swing" and self._swing:
            return      # 已经坐着:开机的 after(2000) 和 idle 回座会各来一次
        if getattr(self, "_scene_art", None) is not None:
            self._start_swing_art(quiet)
            return
        # 场景矩形:锚点在场景顶部,绳长到座椅,下留腿部余量
        scene_w = int(self.W * 1.35)
        scene_h = int(self.H * SWING_SCENE_H)
        lift_out = int(SEAT_LIFT_ART *
                       (self.spr2.height if hasattr(self, "spr2") else 650) / 750.0)
        saved = self.settings.get("swing_scene") or {}
        scene_scale = min(SWING_SCALE_MAX,
                          max(SWING_SCALE_MIN, float(saved.get("scale", 1.0))))
        if saved.get("l") is not None:
            scene_l, scene_t = int(saved["l"]), int(saved["t"])
        else:
            scene_l = int(self.x + self.W / 2 - scene_w / 2)
            scene_t = int(self.fy - lift_out - scene_h * 0.70)
        self._swing = {"scene_l": scene_l, "scene_t": scene_t,
                       "scene_w": scene_w, "scene_h": scene_h,
                       "scene_cx": scene_l + scene_w // 2,
                       "R": int(self.H * SWING_ROPE_LEN),
                       "bar_y": int(self.H * SWING_BAR_Y), "lift_out": lift_out,
                       "hw": int(58 * self.scale), "scene_scale": scene_scale,
                       "theta": 0.0, "omega": 0.0, "t0": time.time(),
                       "x0": self.x, "fy0": self.fy,
                       "pend": life.Pendulum(period=SWING_PERIOD,
                                             idle_amp=0.085,
                                             max_amp=SWING_MAX_AMP),
                       "rect": (scene_l, scene_t,
                                scene_l + scene_w, scene_t + scene_h)}
        self._swing_fit_scene()     # 存档里的位置可能在已经拔掉的屏上
        self.state = "swing"
        if hasattr(self, "squash") and hasattr(self, "add_part"):
            self.squash = min(self.squash, 0.94)  # 入座:轻轻一坐的弹性
            self.add_part("sparkle", -self.W * 0.06, -self.H * 0.30,
                          life=0.7, size=random.uniform(5, 10),
                          color=GOLD_L, phase=random.uniform(0, 6.28))
            self.add_part("sparkle", self.W * 0.05, -self.H * 0.26,
                          life=0.6, size=random.uniform(4, 8),
                          color=(185, 140, 255), phase=random.uniform(0, 6.28))
        if not quiet:
            self.say(random.choice(["荡秋千咯~", "月亮秋千,起飞!",
                                    "抓稳了,要荡咯~"]), 2.4)

    def _start_swing_art(self, quiet=False):
        """入座(原画场景):整张原画场景按上次的中心/大小恢复。第一次入座
        让原画里的她和她现在的位置重合(看起来是原地坐上去的)。"""
        saved = self.settings.get("swing_scene") or {}
        lo, hi = SWING_ART_SCALE
        lo = .48 if self.house_enabled() else lo
        ss = min(hi, max(lo, float(saved.get("scale", 1.0))))
        ss = self._limit_house_scale(ss)
        geo = self._art_geo(ss)
        cw, ch = geo["size"]
        if saved.get("cx") is not None:
            cx, cy = float(saved["cx"]), float(saved["cy"])
            scene_l, scene_t = int(cx - cw / 2), int(cy - ch / 2)
        elif saved.get("l") is not None:
            # 旧版程序秋千只存了左上角(画布 1.35W×1.26H):换算成中心再放
            cx = int(saved["l"]) + int(self.W * 1.35) / 2
            cy = int(saved["t"]) + int(self.H * SWING_SCENE_H) / 2
            scene_l, scene_t = int(cx - cw / 2), int(cy - ch / 2)
        else:
            stl_x = self.x + geo["sl"][0]
            stl_y = self.fy - self.FOOT_Y + geo["sl"][1]
            scene_l = int(stl_x - (geo["gtl"][0] - geo["O"][0]))
            scene_t = int(stl_y - (geo["gtl"][1] - geo["O"][1]))
        self._swing = {"art": True, "geo": geo,
                       "scene_l": scene_l, "scene_t": scene_t,
                       "scene_w": cw, "scene_h": ch,
                       "scene_cx": scene_l + cw // 2, "scene_scale": ss,
                       # 程序秋千的字段:留着默认值,零散读取不至于 KeyError
                       "R": 1, "bar_y": 0, "hw": int(58 * self.scale),
                       "theta": 0.0, "omega": 0.0, "t0": time.time(),
                       "x0": self.x, "fy0": self.fy,
                       "pend": life.Pendulum(period=SWING_PERIOD, idle_amp=0.085,
                                             max_amp=SWING_MAX_AMP),
                       "rect": (scene_l, scene_t, scene_l + cw, scene_t + ch)}
        self.swing_layer.close()            # 程序秋千的后景层用不上
        self._ks_cache.clear()
        if self._swing_fit_scene():
            self._save_swing_scene()        # 挪回屏内的位置存下来,重启不再出屏
        self.state = "swing"
        if hasattr(self, "squash") and hasattr(self, "add_part"):
            self.squash = min(self.squash, 0.94)
            self.add_part("sparkle", -self.W * 0.06, -self.H * 0.30,
                          life=0.7, size=random.uniform(5, 10),
                          color=GOLD_L, phase=random.uniform(0, 6.28))
        if not quiet:
            self.say(random.choice(["荡秋千咯~", "月亮秋千,起飞!",
                                    "抓稳了,要荡咯~"]), 2.4)

    def _swing_stop(self, restore=False):
        self._set_house_hover(None)
        sw = getattr(self, "_swing", None)
        self._swing = None
        self._swing_pull = None
        # 离开/重建场景:清理打盹标记与残留 zzz,恢复摆动参数
        if getattr(self, "_nap_on_swing", False):
            self._nap_on_swing = False
            pend = sw.get("pend") if sw else None
            if pend:
                pend.idle_amp = 0.085
                pend.damping = 0.30
        self.parts = [q for q in getattr(self, "parts", [])
                      if q.get("kind") not in ("zzz", "ball", "ball_ring")]
        self.swing_layer.close()
        if sw and getattr(self, "swing_home", False):
            # 不管怎么下来的(菜单/犯困/别的动作/被抛飞),都落地空闲一阵再
            # 自己回座。原来只有菜单「下来」设了 40~70 秒,其余路径要么是
            # 开机的 0(立刻又回座),要么是回座时占位的 1 小时
            self._swing_remount = time.time() + random.uniform(40, 70)
        if sw and restore and self.state == "swing":
            self.x, self.fy = sw["x0"], sw["fy0"]
            self.state = "idle"

    def _swing_dismount(self, line=None):
        """下秋千:收绳椅,从座椅高度自然落地(不瞬移)。菜单「下来」、
        秋千上犯困、在秋千上点了地面动作都走这一条。"""
        self._swing_stop(restore=False)
        self.state = "fall"
        self.vy = 0.0
        if line:
            self.say(line, 2.2)

    def _land_first(self, act):
        """坐在秋千上时点了地面动作(喂糖/施法/跳舞/睡觉/伸懒腰…):先走
        下秋千的自然落地,落地站稳后再补做 act。返回 True = 已排队,调用方
        直接 return。

        原来动作直接改 state,下一帧顶部收掉秋千、她留在座椅高度,重力
        兜底随即把 eat/magic/dance/yawn 统统改成 fall —— 动作整个丢掉,
        喂糖还白记了一颗。"""
        if getattr(self, "state", None) != "swing" or not getattr(self, "_swing", None):
            return False
        self._swing_dismount()
        self._land_then = act
        return True

    def _run_land_then(self):
        """落地那一帧(fall 分支)调用:补做下秋千前点的动作,只做一次。"""
        act, self._land_then = self._land_then, None
        if act:
            act()

    def _swing_fit_scene(self):
        """场景中心不在任何一块显示器上(外接屏拔了、排列改了、存档来自
        别的布局)时,整块挪回最近那块屏的工作区。只救"看不见、够不着",
        主人故意摆到屏幕边上的位置不动。挪了返回 True(不落盘:屏插回来、
        重启后还是主人摆的位置)。"""
        sw = self._swing
        if not sw:
            return False
        if sw.get("art") and self._scene_art is not None:
            return self._art_fit_scene(sw)
        cx = sw["scene_l"] + sw["scene_w"] / 2
        cy = sw["scene_t"] + sw["scene_h"] / 2
        mon = monitor_rect_at(cx, cy)      # 点不在任何屏上时给最近的一块
        if not mon or (mon[0] <= cx < mon[2] and mon[1] <= cy < mon[3]):
            return False
        wa = monitor_rect_at(cx, cy, work=True) or mon
        sw["scene_l"] = int(max(wa[0], min(sw["scene_l"], wa[2] - sw["scene_w"])))
        sw["scene_t"] = int(max(wa[1], min(sw["scene_t"], wa[3] - sw["scene_h"])))
        sw["scene_cx"] = sw["scene_l"] + sw["scene_w"] // 2
        sw["rect"] = (sw["scene_l"], sw["scene_t"],
                      sw["scene_l"] + sw["scene_w"], sw["scene_t"] + sw["scene_h"])
        return True

    def _art_fit_scene(self, sw):
        """原画场景:看得见的内容(横杆/她/书/水晶,不含画布四周给气泡留的
        透明边)只要有一块伸出屏幕,就整体挪回所在屏的工作区。程序秋千只救
        "中心出屏";原画场景的书和水晶在两侧边上,半截出屏就点不到了。
        拖着场景时不抢(松手后下一次复查再挪)。挪了返回 True。"""
        if getattr(self, "_scene_drag", None):
            return False
        geo = sw["geo"]
        if geo.get('flat') or geo.get('house_layout'):
            x0, y0 = sw['scene_l'], sw['scene_t']
            x1, y1 = x0+sw['scene_w'], y0+sw['scene_h']
            wa = work_area_at((x0+x1)/2, (y0+y1)/2)
            if not wa:
                return False
            if (sw['scene_w'] > wa[2]-wa[0]-16 or
                    sw['scene_h'] > wa[3]-wa[1]-16):
                self._art_regeo(sw, sw.get('scene_scale', 1.0))
                self._art_fit_scene(sw)
                return True
            nx = int(max(wa[0]+8, min(x0, wa[2]-sw['scene_w']-8)))
            ny = int(max(wa[1]+8, min(y0, wa[3]-sw['scene_h']-8)))
            if (nx, ny) == (x0, y0):
                return False
            sw.update(scene_l=nx, scene_t=ny, scene_cx=nx+sw['scene_w']//2,
                      rect=(nx, ny, nx+sw['scene_w'], ny+sw['scene_h']))
            return True
        k, O = geo["k"], geo["O"]
        cb = self._scene_art.content_box()
        x0 = sw["scene_l"] + cb[0] * k - O[0]
        y0 = sw["scene_t"] + cb[1] * k - O[1]
        x1 = sw["scene_l"] + cb[2] * k - O[0]
        y1 = sw["scene_t"] + cb[3] * k - O[1]
        wa = (monitor_rect_at((x0 + x1) / 2, (y0 + y1) / 2, work=True)
              or monitor_rect_at((x0 + x1) / 2, (y0 + y1) / 2))
        if not wa:
            return False
        dx = (wa[0] - x0 if x0 < wa[0] else wa[2] - x1 if x1 > wa[2] else 0)
        dy = (wa[1] - y0 if y0 < wa[1] else wa[3] - y1 if y1 > wa[3] else 0)
        if not dx and not dy:
            return False
        sw["scene_l"] = int(round(sw["scene_l"] + dx))
        sw["scene_t"] = int(round(sw["scene_t"] + dy))
        sw["scene_cx"] = sw["scene_l"] + sw["scene_w"] // 2
        sw["rect"] = (sw["scene_l"], sw["scene_t"],
                      sw["scene_l"] + sw["scene_w"], sw["scene_t"] + sw["scene_h"])
        return True

    # ---- 开口说话(TTS,Windows 自带 SAPI,零依赖) ----
    def _speak(self, text):
        """念一段话。不排队:上一句没念完就跳过这句,免得炸麦。

        先用 edge-tts 现合成 —— 和 assets/audio 里那 42 个反馈音同一把嗓子,
        这样"她说话"和"她的反应音"才像同一个人。合成不了(没装 venv / 断网 /
        超时)才退回系统 SAPI,那条路是机器音,只当兜底。
        """
        if not self.tts_on or not self.sound_on or not text:
            return
        text = " ".join(str(text).split())[:120]
        if not text:
            return

        def work():
            if not self._speak_lock.acquire(blocking=False):
                return
            try:
                mp3 = self._tts_render(text)
                if mp3 and self._tts_play(mp3):
                    return
                self._speak_sapi(text)
            except Exception:
                pass
            finally:
                self._speak_lock.release()

        threading.Thread(target=work, daemon=True).start()

    def _tts_render(self, text):
        """合成成 mp3 并返回路径,失败返回 None。命中缓存就不联网。"""
        py = tts_python()
        if not py:
            return None
        key = hashlib.md5(
            f"{TTS_VOICE}|{TTS_PITCH}|{TTS_RATE}|{text}".encode("utf-8")).hexdigest()
        dst = os.path.join(TTS_CACHE, key + ".mp3")
        if os.path.exists(dst) and os.path.getsize(dst) > 1000:
            try:
                os.utime(dst, None)      # 刷新 mtime,当作 LRU 的"最近使用时间"
            except OSError:
                pass
            return dst
        tmp = dst + ".part"
        try:
            os.makedirs(TTS_CACHE, exist_ok=True)
            r = subprocess.run(
                [py, "-m", "edge_tts", f"--voice={TTS_VOICE}",
                 f"--pitch={TTS_PITCH}", f"--rate={TTS_RATE}",
                 f"--text={text}", f"--write-media={tmp}"],
                stdin=subprocess.DEVNULL, capture_output=True, timeout=12,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            ok = (r.returncode == 0 and os.path.exists(tmp)
                  and os.path.getsize(tmp) > 1000)
            if not ok:
                if os.path.exists(tmp):
                    os.remove(tmp)
                return None
            os.replace(tmp, dst)         # 先写 .part 再改名,别让半截文件进缓存
            self._tts_trim_cache()
            return dst
        except Exception:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            return None

    def _tts_trim_cache(self):
        try:
            fs = [os.path.join(TTS_CACHE, f) for f in os.listdir(TTS_CACHE)
                  if f.endswith(".mp3")]
            if len(fs) <= TTS_CACHE_MAX:
                return
            fs.sort(key=os.path.getmtime)
            for old in fs[:len(fs) - TTS_CACHE_MAX]:
                os.remove(old)
        except Exception:
            pass

    def _tts_play(self, path):
        """MCI 播放并等它念完(work() 本来就在后台线程,阻塞的是它自己)。"""
        alias = f"pettts{self._tts_n % 4}"
        self._tts_n += 1
        try:
            mci(f"close {alias}")
            err, _ = mci(f'open "{path}" type mpegvideo alias {alias}')
            if err != 0:
                return False
            mci(f"setaudio {alias} volume to {self.tts_volume}")
            err, _ = mci(f"play {alias} wait")
            return err == 0
        except Exception:
            return False
        finally:
            try:
                mci(f"close {alias}")
            except Exception:
                pass

    def _speak_sapi(self, text):
        """兜底:系统自带 TTS。文本走 base64 塞进 PowerShell 绕开转义地狱;
        挑最甜的中文女声,SSML 抬调 +30%,不然听起来像客服阿姨。"""
        try:
            b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
            ps = (
                "Add-Type -AssemblyName System.Speech;"
                "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                "$zh=$s.GetInstalledVoices()|"
                "Where-Object{$_.VoiceInfo.Culture.Name -like 'zh*'};"
                "$pick=$null;"
                "foreach($p in @('Xiaoyi','Yaoyao','Xiaoxiao','Huihui')){"
                "$m=$zh|Where-Object{$_.VoiceInfo.Name -like ('*'+$p+'*')}|"
                "Select-Object -First 1;if($m){$pick=$m;break}};"
                "if(-not $pick){$pick=$zh|Select-Object -First 1};"
                "if($pick){$s.SelectVoice($pick.VoiceInfo.Name)};"
                "$t=[Text.Encoding]::UTF8.GetString("
                f"[Convert]::FromBase64String('{b64}'));"
                "$t=[Security.SecurityElement]::Escape($t);"
                "$ssml='<?xml version=\"1.0\" encoding=\"utf-8\"?>'"
                "+'<speak version=\"1.0\" "
                "xmlns=\"http://www.w3.org/2001/10/synthesis\" "
                "xml:lang=\"zh-CN\">'"
                "+'<prosody pitch=\"+30%\" rate=\"+8%\">'+$t+'</prosody>'"
                "+'</speak>';"
                "$s.SpeakSsml($ssml);"
                "$s.Dispose()"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                stdin=subprocess.DEVNULL, capture_output=True,
                timeout=25,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            pass

    def toggle_tts(self):
        self.tts_on = not self.tts_on
        self.save_settings()
        self.say("好~以后用说的!" if self.tts_on else "好叭,安静做个美人…", 2.4)
        if self.tts_on:
            self._speak("以后我用这个声音陪你哦")

    def toggle_autostart(self):
        """开机自启:写/删 HKCU 注册表 Run 键,不需要管理员权限。"""
        on = not autostart_enabled()
        ok = autostart_set(on)
        if ok and on:
            self.sfx.play("greet")
            self.say("下次开机我也会自己来陪你哦~", 2.6)
        elif ok:
            self.say("好,开机就不自动启动了~", 2.4)
        else:
            self.say("呜…注册表写不进去…", 2.4)

    def toggle_sound(self):
        """「语音」总开关:反应音效 + 聊天朗读一起静音/恢复。

        「开口说话」是细粒度开关,只管朗读;这个关掉后她全程闭嘴,
        只用气泡和表情表达。"""
        self.sound_on = not self.sound_on
        self.sfx.enabled = self.sound_on
        self.save_settings()
        if self.sound_on:
            self.sfx.play("greet")
            self.say("锵锵~声音魔法恢复!", 2.4)
        else:
            self.say("好~进入安静模式,只用气泡说话", 2.4)

    # ---- 天气(Open-Meteo,免费无 key) ----
    WMO = {0: "晴", 1: "基本晴", 2: "多云", 3: "阴", 45: "雾", 48: "雾凇",
           51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨", 56: "冻毛毛雨", 57: "冻毛毛雨",
           61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "冻雨",
           71: "小雪", 73: "中雪", 75: "大雪", 77: "米雪",
           80: "阵雨", 81: "阵雨", 82: "强阵雨", 85: "阵雪", 86: "阵雪",
           95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "雷阵雨伴冰雹"}

    def anniv_dialog(self):
        """设置/取消自定义纪念日。每年当天的第一次问候会自动庆祝。"""
        cur_d = self.settings.get("anniv_date")
        if cur_d:
            # 原来这里是反的:提示写着「是」来更换,而 True 分支里却把纪念日
            # 删掉直接 return —— 想换日期的人按了「是」,结果纪念日没了。
            if not self.themed_confirm(
                    "小乔 · 纪念日",
                    f"已经有一个纪念日了({cur_d} "
                    f"{self.settings.get('anniv_name', '')})。\n"
                    "要换成新的,还是干脆取消掉?",
                    yes="换一个", no="取消它"):
                self.settings.pop("anniv_date", None)
                self.settings.pop("anniv_name", None)
                self.save_settings()
                self._fest_done = None
                self._reply("好,纪念日取消啦~", "mild")
                return
        d = self.themed_input(
            "小乔 · 纪念日", "纪念日是几月几号?(比如 09-15 或 3月5日)",
            validate=lambda s: None if parse_mmdd(s) else
            "日期没看懂…像 09-15 这样告诉人家好不好?")
        if not d:
            return
        mm, dd = parse_mmdd(d)
        name = self.themed_input("小乔 · 纪念日",
                                 "这一天叫什么名字?(比如 主人的生日)",
                                 initial="纪念日")
        name = (name or "").strip()[:12] or "纪念日"
        self.settings["anniv_date"] = f"{mm:02d}-{dd:02d}"
        self.settings["anniv_name"] = name
        self.save_settings()
        self._fest_done = None
        self._reply(f"记住啦!每年 {mm:02d}-{dd:02d} 的 {name},小乔都会一起庆祝的~", "excited")

    def birthday_dialog(self):
        """设置聊天『生日快乐』彩蛋触发的真实日期(MM-DD)。"""
        cur = self.settings.get("birthday", "")
        prompt = ("今天是几月几号?(填了以后,聊天说生日快乐会触发彩蛋) " +
                  ("当前已设: " + cur if cur else "当前未设"))
        d = self.themed_input(
            "小乔 · 我的生日", prompt, initial=cur,
            validate=lambda s: None if parse_mmdd(s) else
            "日期没看懂…像 09-15 这样告诉人家好不好?")
        if not d:
            return
        mm, dd = parse_mmdd(d)
        self.settings["birthday"] = f"{mm:02d}-{dd:02d}"
        self.save_settings()
        self._reply(f"记住啦!以后 {mm:02d}-{dd:02d} 就是我的生日啦~", "excited")

    def set_city_dialog(self):
        c = self.themed_input("小乔 · 城市", "你在哪个城市?(用来查天气,比如 北京)",
                              initial=self.city)
        if c is None:            # 取消;留空则是"清掉城市",两者不一样
            return
        self.city = (c or "").strip()
        self.city_lat = None
        self.city_lon = None
        self.save_settings()
        if self.city:
            self._reply(f"记住啦,你在{self.city}~要查天气随时叫我", "roger")
            self._speak("记住啦")
        else:
            self._reply("好,天气功能先歇着~", "mild")

    def ask_weather(self):
        if self.core_profile():
            return False
        if not self.city:
            self._reply("还不知道你在哪个城市呢,右键菜单里设置一下呗~", "curious")
            return
        self.say("我看看窗外…", 1.6)

        def work():
            w = self._fetch_weather()

            def apply():
                if w == "nocity":
                    self._reply(f"查不到「{self.city}」这个地方…是不是名字写错了?"
                                "右键菜单里可以重新设置城市~", "curious")
                    return
                if w is None:
                    self._reply("天气服务没连上,等会儿再试?", "pouty")
                    return
                desc, tmin, tmax = w
                self._reply(f"今天{self.city} {desc},{tmin:.0f}~{tmax:.0f}°C"
                            + self._weather_tip(desc), "happy")

            self.mainq.put(apply)

        self._run_bg(work)

    def _fetch_weather(self):
        """返回 (天气描述, 最低温, 最高温);"nocity"=城市名查不到;
        None=网络原因。城市先经地理编码缓存坐标。"""
        try:
            if not (self.city_lat and self.city_lon):
                r = self._resolve_city()
                if r != "ok":
                    return r
                if not (self.city_lat and self.city_lon):
                    return None
            url = ("https://api.open-meteo.com/v1/forecast"
                   f"?latitude={self.city_lat}&longitude={self.city_lon}"
                   "&daily=temperature_2m_max,temperature_2m_min,weathercode"
                   "&timezone=auto&forecast_days=1")
            with urllib.request.urlopen(url, timeout=8) as r:
                d = json.loads(r.read().decode("utf-8"))
            daily = d.get("daily") or {}
            code = (daily.get("weathercode") or [None])[0]
            tmin = (daily.get("temperature_2m_min") or [None])[0]
            tmax = (daily.get("temperature_2m_max") or [None])[0]
            if code is None or tmin is None or tmax is None:
                return None
            return self.WMO.get(int(code), "变化莫测"), float(tmin), float(tmax)
        except Exception:
            return None

    def _resolve_city(self):
        """后台线程里跑。返回 "ok"=坐标就绪;"nocity"=城市名查不到;
        "net"=网络原因。坐标缓存绝不在这里直接落盘 —— save_settings 与
        主线程共用同一个 .tmp 临时文件,并发写会把存档写坏(丢全部养成
        数据),改经 mainq 回主线程保存。"""
        url = ("https://geocoding-api.open-meteo.com/v1/search?name="
               + urllib.parse.quote(self.city) + "&count=1&language=zh&format=json")
        try:
            with urllib.request.urlopen(url, timeout=8) as r:
                d = json.loads(r.read().decode("utf-8"))
        except Exception:
            return "net"
        hits = d.get("results") or []
        if not hits:
            return "nocity"
        self.city_lat = hits[0]["latitude"]
        self.city_lon = hits[0]["longitude"]
        self.mainq.put(self.save_settings)
        return "ok"

    @staticmethod
    def _weather_tip(desc):
        if "雷" in desc:
            return ",雷雨天别在外面晃!"
        if "雨" in desc:
            return ",出门带把伞哦~"
        if "雪" in desc:
            return ",记得穿厚点!"
        if desc in ("晴", "基本晴"):
            return ",太阳很好,适合出门转转~"
        return ",注意添减衣服~"

    def find_file_dialog(self):
        name = self.themed_input(
            "小乔 · 找文件", "找什么文件?(名字的一部分就行,比如 报告、.png)")
        if name and name.strip():
            self._start_file_search(name.strip())

    def _start_file_search(self, name):
        if self.core_profile():
            return False
        self.last_interact = time.time()
        self._reply(f"我去桌面、文档、下载这些地方翻翻「{name}」…", "roger")

        def work():
            try:
                hits = agent.find_files(name)
            except Exception:
                hits = []
            self.mainq.put(lambda: self._file_search_done(name, hits))

        threading.Thread(target=work, daemon=True).start()

    def _file_search_done(self, name, hits):
        if not hits:
            self._reply(f"常见目录里没找到「{name}」…换个关键词试试?", "pouty")
            return
        # 顺手在资源管理器里定位第一个结果,省得手抄路径
        try:
            subprocess.Popen(["explorer", "/select,",
                              os.path.normpath(hits[0].rstrip(os.sep))])
        except Exception:
            pass
        if len(hits) == 1:
            self._reply(f"找到啦,帮你定位好了:\n{hits[0]}", "excited")
            return
        lines = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(hits[:5]))
        more = f"\n…还有 {len(hits) - 5} 个" if len(hits) > 5 else ""
        self._reply(f"找到 {len(hits)} 个,第一个已经帮你定位:\n{lines}{more}",
                    "excited")

    def _prewarm_ai(self):
        """开机 25 秒后在后台把 SDK 预热好。没配 AI 时 brain 是 None ——
        原来这里直接取 self.brain.prewarm,于是凡是没填密钥的用户,开机
        25 秒必定往 pet_error.log 抛一次 AttributeError。"""
        if self.core_profile():
            return False
        if self.brain:
            threading.Thread(target=self.brain.prewarm, daemon=True).start()

    def _ai_ready(self):
        """被动检查用的 AI 就绪判断,绝不在主线程里同步 import google.genai。

        brain.available 首次访问会当场导入 SDK(约 0.8 秒)。原来第一帧 tick
        的主动搭话检查就访问了它,把开机 25 秒后台预热抵消了,冷启动多卡
        0.8 秒。发消息、开聊天框这类互动路径仍直接用 available。
        """
        b = self.brain
        if not b:
            return False
        ready = getattr(b, "ready", None)      # 测试里的假 brain 可能只有 available
        return bool(b.available if ready is None else ready)

    def _ai_quick(self, hint=""):
        if self.core_profile():
            return False
        if not (self.brain and self.brain.available):
            return

        def work():
            res = self.brain.quick_line(hint)
            if res:
                self.mainq.put(lambda: self._apply_ai(res, from_chat=False))

        # 她主动搭话失败就安静地算了,不用弹“魔法失灵”打扰主人
        self._run_bg(work, quiet=True)

    def toggle_greet(self):
        if not self.brain:
            return
        cur = self.brain.cfg.get("greet_interval_min", 0)
        self.brain.cfg["greet_interval_min"] = 0 if cur > 0 else 30
        self.brain.save()
        self.next_greet = time.time() + 30
        self.say("好呀,我会主动找你玩的~" if cur == 0 else "好叭,我不吵你了…", 2.2)

    # ==================== 交互 ====================
    def on_press(self, e):
        if getattr(self, '_flat_panel_style', False):
            from flat_workspace import bar_input
            if bar_input(self, e, 'press'):
                return
        self.last_interact = time.time()
        woke = self._wake_from_nap()        # 点她一下就醒,平滑回到摆动
        if self._catch_collect(e.x, e.y):
            return          # 点到星星 = 接住,这一下不进入拖拽
        if self._pop_bubble(e.x, e.y):
            return          # 点到泡泡 = 戳破,同样不进入拖拽
        if self._catch_ball(e.x, e.y):
            return          # 点到光球 = 玩球互动
        if self._catch_leaf(e.x, e.y) or self._catch_flower(e.x, e.y)                 or self._catch_snow(e.x, e.y):
            return          # 点到飘落物 = 季节互动
        if self.state in ("walk", "fall"):
            self.state = "idle"
            self.vy = 0.0
        # 思维链卷轴:点击 → 打开该会话轨迹页;她在落地态则先回秋千
        # (宪法 7:秋千是舞台,也是 AI UI 的展示位)
        cr = getattr(self, "_chain_rect", None)
        if cr and cr[0] <= e.x <= cr[0] + cr[2] and cr[1] <= e.y <= cr[1] + cr[3]:
            sid = getattr(self, "_chain_sid", None)
            if sid:
                self._book_open = True
                self._book_tab = "trace"
                self._book_sel = ("sid", sid)
                if not self.ui_reduced_anim:
                    self._book_anim = 0.0
                self._book_new_seen[sid] = len(
                    next((s for s in self._ai_sessions
                          if s["id"] == sid), {"actions": []})
                    .get("actions") or [])
                if self.state != "swing":
                    self.start_swing()      # 回舞台看详情
            return
        if self.state == "swing" and self._swing:
            sw = self._swing
            # 道具/面板命中(各命中互不串扰;面板本体吞掉点击不拖场景)
            for hx, hy, hw2, hh, kind, payload in (sw.get("ui_hits") or []):
                if hx <= e.x <= hx + hw2 and hy <= e.y <= hy + hh:
                    self._ui_hit(kind, payload)
                    return
            if self._book_open or self._crystal_open:
                self._book_open = self._crystal_open = False
                if not self.house_enabled():
                    return                   # standalone scene closes its panel first
            # 其余 = 拖动整个场景(场景连同她一起移动)
            self._scene_drag = d = {"mx": e.x_root, "my": e.y_root, "moved": False}
            root = getattr(self, "root", None)
            if not woke and root is not None:
                # 按住不动约 0.9 秒 = 长按(B4 害羞躲开);一挪动就仍是拖场景
                root.after(seat_motion.LONG_PRESS_MS,
                           lambda: self._seat_long_press(d, e.x))
            return
        self.drag = (e.x_root, e.y_root, self.x, self.fy, False, time.time())

    def _catch_collect(self, x, y):
        """接星星:点在可捕捉金星的当前位置附近就算接住。返回是否接到。"""
        hit = None
        # 星光充盈(≥80)时星星像被磁铁吸着一样,点击范围更大
        radius = 88 if self.star >= 80 else 52
        for p in self.parts:
            if p["kind"] != "cstar":
                continue
            age = time.time() - p["born"]
            cx = p["x"] + p["vx"] * age
            cy = p["y"] + p["vy"] * age + 0.5 * p["grav"] * age * age
            if math.hypot(cx - x, cy - y) < radius:
                hit = p
                break
        if hit is None:
            return False
        self.parts.remove(hit)
        self._catch_got += 1
        self._count_today("catch")
        # 飘字从接住的那颗星的位置升起
        self.gain_star(2, hit["x"] - self.W / 2, hit["y"] - self.H / 2 - 18 * self.scale)
        self.add_part("sparkle", hit["x"] - self.W / 2, hit["y"] - self.H / 2,
                      life=0.6, size=random.uniform(6, 10), color=GOLD_L,
                      phase=random.uniform(0, 6.28))
        self.sfx.play("sparkle")
        # 连击:2 秒内连续接住累计,4 连击起在星星位置喷小彩带
        now2 = time.time()
        if now2 - getattr(self, "_catch_last", 0.0) <= 2.0:
            self._catch_combo = getattr(self, "_catch_combo", 0) + 1
        else:
            self._catch_combo = 1
        self._catch_last = now2
        self.hit_ring(hit["x"] - self.W / 2, hit["y"] - self.H / 2,
                      double=self._catch_combo >= 2)
        combo_txt = f" 连击x{self._catch_combo}!" if self._catch_combo >= 2 else ""
        if self._catch_combo >= 4:
            self.confetti_burst(hit["x"] - self.W / 2, hit["y"] - self.H / 2, 6)
        left = self._catch_total - self._catch_got
        if left <= 0 and self._catch_got > 0:
            # 满接结算(只在这里说):新纪录 > 神速(≤4.5s,+3 星光) > 普通
            speed = time.time() - getattr(self, "_catch_t0", time.time())
            fast = speed <= 4.5
            if self._catch_got > self.catch_best:
                self.catch_best = self._catch_got
                self.save_settings()
                self.say(f"新纪录!一口气接住 {self._catch_got} 颗星星!"
                         + (" 而且神速!" if fast else "")
                         + combo_txt, 2.6)
                self.confetti_burst(0, -0.1 * self.H, 14)
                self.play_emotion("proud", 2.4)
            else:
                if fast:
                    self.gain_star(3)
                self.say(random.choice(
                    ["神速!手气爆棚!" if fast else "全接住了!",
                     f"{self._catch_got} 颗全接住,谢谢你~" if not fast else "太强了吧!",
                     "接满啦!" if not fast else "闪电小乔!"]) + combo_txt, 2.4)
                self.play_emotion("proud" if fast else "happy", 2.4)
        else:
            self.say(f"接住 {self._catch_got}/{self._catch_total}!{combo_txt}", 1.2)
        return True

    def _catch_floating(self, x, y, kind, radius, sway, sparkle_color):
        """通用:接任一种飘落物(叶/瓣/雪)。点中即碎+季节台词+闪光。"""
        for p in self.parts:
            if p["kind"] != kind:
                continue
            age = time.time() - p["born"]
            cx = p["x"] + math.sin(age * sway + p["phase"]) * 14
            cy = p["y"] + p["vy"] * age
            if math.hypot(cx - x, cy - y) < radius:
                self.parts.remove(p)
                mon = time.localtime().tm_mon
                self.say(random.choice(self.SEASON_SAY[self._season(mon)]), 2.2)
                self.add_part("sparkle", p["x"] - self.W / 2, p["y"] - self.H / 2,
                              life=0.5, size=random.uniform(5, 9),
                              color=sparkle_color, phase=random.uniform(0, 6.28))
                self.sfx.play("sparkle")
                return True
        return False

    def _catch_leaf(self, x, y):
        return self._catch_floating(x, y, "leaf", 44, 1.8, GOLD_L)

    def _catch_flower(self, x, y):
        return self._catch_floating(x, y, "petal", 40, 2.1,
                                    (255, 210, 220))

    def _catch_snow(self, x, y):
        # 雪花也是季节飘落物:接住 + 季节台词 + 雪花色闪光
        for p in self.parts:
            if p["kind"] != "snow":
                continue
            age = time.time() - p["born"]
            cx = p["x"] + math.sin(age * 1.5 + p["phase"]) * 10
            cy = p["y"] + p["vy"] * age
            if math.hypot(cx - x, cy - y) < 32:
                self.parts.remove(p)
                self.say(random.choice(self.SEASON_SAY["winter"]), 2.2)
                self.add_part("sparkle", p["x"] - self.W / 2, p["y"] - self.H / 2,
                              life=0.4, size=random.uniform(4, 7),
                              color=(245, 248, 255), phase=random.uniform(0, 6.28))
                self.sfx.play("pop")
                return True
        return False

    def _firework_burst(self):
        """节日烟花:四发金色火点慢升+二次爆开彩带。"""
        for side in (-1, 1):
            for _ in range(2):
                self.add_part("fw", side * 0.3 * self.W, -0.05 * self.H,
                              vx=side * random.uniform(20, 35),
                              vy=random.uniform(-110, -80),
                              life=random.uniform(0.7, 1.0),
                              size=random.uniform(5, 8),
                              color=GOLD_L, phase=random.uniform(0, 6.28),
                              spin=random.uniform(-1, 1))

    def _festive_burst(self, big=False):
        """庆典通用:彩带 + (盛大)烟花。自定义纪念日也是 big。"""
        self.confetti_burst(0, -0.1 * self.H, 30 if big else 22)
        if big:
            self._firework_burst()

    def _pop_bubble(self, x, y):
        """戳泡泡:点在漂动的泡泡附近就直接戳破(啵~ + 小闪光)。"""
        for p in self.parts:
            if p["kind"] != "bub":
                continue
            age = time.time() - p["born"]
            cx = p["x"] + math.sin(age * 2.6 + p["phase"]) * 9
            cy = p["y"] + p["vy"] * age
            if math.hypot(cx - x, cy - y) < 40:
                self.parts.remove(p)
                self.sfx.play("pop")
                self.add_part("sparkle", p["x"] - self.W / 2, p["y"] - self.H / 2,
                              life=0.5, size=random.uniform(5, 9),
                              color=(196, 228, 255), phase=random.uniform(0, 6.28))
                return True
        return False

    def on_drag(self, e):
        if getattr(self, '_flat_panel_style', False):
            from flat_workspace import bar_input
            if bar_input(self, e, 'move'):
                return
        if getattr(self, "_scene_drag", None):
            d = self._scene_drag
            sw = self._swing
            dx, dy = e.x_root - d["mx"], e.y_root - d["my"]
            if abs(dx) + abs(dy) > 5:
                d["moved"] = True
            if sw and (dx or dy):
                sw["scene_l"] += dx
                sw["scene_t"] += dy
                sw["scene_cx"] = sw["scene_l"] + sw["scene_w"] // 2
                sw["rect"] = (sw["scene_l"], sw["scene_t"],
                              sw["scene_l"] + sw["scene_w"],
                              sw["scene_t"] + sw["scene_h"])
            d["mx"], d["my"] = e.x_root, e.y_root
            self.last_interact = time.time()
            return
        if not self.drag:
            return
        dx = e.x_root - self.drag[0]
        dy = e.y_root - self.drag[1]
        if abs(dx) + abs(dy) > 5:
            if not self.drag[4]:
                # 刚从"按住"变成"拖动"的那一下:在手抓住的位置亮一圈。窗口跟着
                # 手走,光环钉在窗口坐标上,也就一直在手底下
                self.hit_ring(self.drag[0] - self.drag[2] - self.W / 2,
                              self.drag[1] - (self.drag[3] - self.FOOT_Y) - self.H / 2)
            self.drag = self.drag[:4] + (True, self.drag[5])
            if self.state in ("walk", "dance", "roll", "stretch", "peek", "chase",
                              "sneeze", "fall_stand"):
                self.state = "idle"
            self._micro_motion = None
            self._cancel_ball()
            prev_x = self.x
            self.x = int(self.drag[2] + dx)
            self.fy = self.drag[3] + dy
            self._clamp_pos()

            # 记录轨迹,松手时用最近 120ms 的位移算抛掷初速
            now = time.time()
            self._drag_trail.append((now, self.x, self.fy))
            self._drag_trail = [s for s in self._drag_trail if now - s[0] < 0.12]

            # 摇晃检测:记录水平方向的翻转次数,短时间内翻转够多次就摇晕
            step = self.x - prev_x
            if abs(step) > 6:
                d = 1 if step > 0 else -1
                if not self._shake_dirs or self._shake_dirs[-1][1] != d:
                    self._shake_dirs.append((now, d))
                self._shake_dirs = [s for s in self._shake_dirs if now - s[0] < 1.4]
                if (len(self._shake_dirs) >= 5 and now > self._shake_cd
                        and self.state != "dizzy"):
                    self._shake_cd = now + 12
                    self._shake_dirs.clear()
                    self.go_dizzy()

    def on_release(self, e):
        if getattr(self, '_flat_panel_style', False):
            from flat_workspace import bar_input
            if bar_input(self, e, 'release'):
                return
        if getattr(self, "_scene_drag", None):
            d = self._scene_drag
            self._scene_drag = None
            if not d["moved"] and self._swing:
                if d.get("seat"):
                    return                   # 长按已经回应过(害羞躲开),松手不再算一次摸头
                self.click_token += 1
                token = self.click_token
                if self._art_hat_hit(e.x, e.y):
                    # 点到帽子:帽子抖一下(弹簧 + 星星),她抬头去看
                    self.root.after(60, lambda: token == self.click_token
                                    and self._seat_hat_click())
                elif self._art_seat_hit(e.x, e.y):
                    # 点坐垫/腿脚:推一把秋千
                    self.root.after(60, lambda: token == self.click_token
                                    and self._seat_push())
                else:
                    self.root.after(60, lambda: token == self.click_token
                                    and self._seat_head_click())
            else:
                self._save_swing_scene()
            return
        drag = self.drag
        if not drag:
            return
        self.drag = None
        if drag[4]:
            self.save_settings()
            # 甩得够快就抛出去,否则还是原来的自由落体
            tr, self._drag_trail = self._drag_trail, []
            vx, vy = self._drag_velocity(tr, time.time())
            if not self.core_profile() and math.hypot(vx, vy) > 900*self.scale:
                self.throw(max(-1800, min(1800, vx)), max(-1800, min(1800, vy)))
                return
            if self.fy < self.ground_feet - 6:
                self.state = "fall"
                self.vy = 0.0
            return
        self.click_token += 1
        token = self.click_token
        self._last_click = (e.x, e.y, time.time())
        zone = self._click_zone(e.x, e.y)
        if zone == "hat":
            self.root.after(60, lambda: token == self.click_token and self.wobble_hat())
        elif zone == "head":
            self.root.after(60, lambda: token == self.click_token and self.pet_head())
        else:
            self.root.after(60, lambda: token == self.click_token and self.tickle_body())

    def _click_zone(self, ex, ey):
        """单击落在哪:"hat" 帽子 / "head" 摸头 / "body" 挠痒。

        有 rig 部位多边形时按多边形判(新立绘的帽檐斜着伸到脸的高度,只按
        y 切会把帽檐当成挠痒);没有就退回旧立绘的 y 分带。"""
        spr_h = self._spr_disp_h()
        regions = (self.cfg.get("rig") or {}).get("regions")
        if regions:
            spr_w = spr_h * self.main_src.width / self.main_src.height
            left = self.W / 2 - self._sprite_center_rel * spr_w
            rx, ry = (ex - left) / spr_w, (ey - (self.FOOT_Y - spr_h)) / spr_h
            for zone, names in (("head", ("face",)), ("hat", ("hat",)),
                                ("head", ("hair",))):
                if any(point_in_poly(rx, ry, regions.get(n) or ()) for n in names):
                    return zone
            return "body"
        if ey < self.FOOT_Y - spr_h * 0.60:    # 帽区:上 40%(点击=帽子抖+星星)
            return "hat"
        if ey < self.FOOT_Y - spr_h * 0.58:    # 脸区:摸头
            return "head"
        return "body"

    def on_double(self, e):
        self.click_token += 1
        if self.core_profile():
            self.open_chat()
            return
        if self.singing:
            self.stop_sing()
            self.say("唱一半被叫停啦~", 2.2)
            return
        self.cast_magic()

    def on_hover(self, e):
        self.last_interact = time.time()
        if self.house_enabled() and getattr(self, '_swing', None):
            bounds = self._swing['geo']['house_layout'].left_bounds
            hx, hy, hw, hh = bounds
            self._house_pointer = (max(-1.0, min(1.0, (e.x-hx)/max(1,hw)*2-1)),
                                   max(-1.0, min(1.0, (e.y-hy)/max(1,hh)*2-1)))
            self._house_pointer_at = time.time()
        if self.state == "swing" and self._swing:
            sw = self._swing
            over_crystal = over_ui = False
            hover = None
            for hx, hy, hw2, hh, kind, _pl in (sw.get("ui_hits") or []):
                if hx <= e.x <= hx + hw2 and hy <= e.y <= hy + hh:
                    over_ui = True
                    over_crystal = kind == "crystal"
                    hover = kind
                    break
            self._set_house_hover(hover if hover in ('house_trace', 'house_quota') else None)
            self._crystal_hover = over_crystal   # 350ms 后出小提示
            if over_ui:
                if over_crystal and not self._crystal_hover_since:
                    self._crystal_hover_since = time.time()
                return        # 道具/面板上不顺毛、不撒花(命中不串扰)
            self._crystal_hover_since = 0.0
            if self.house_enabled():
                hx, hy, hw, hh = sw['geo']['house_layout'].left_bounds
                if not (hx <= e.x < hx+hw and hy <= e.y < hy+hh):
                    return
                ox, oy, scale = self._art_small_map(sw)
                from types import SimpleNamespace
                e = SimpleNamespace(x=(e.x-ox)/scale, y=(e.y-oy)/scale)
        if self.drag:
            return
        if self._hover_last:
            self.stroke_acc += math.hypot(e.x - self._hover_last[0], e.y - self._hover_last[1])
        self._hover_last = (e.x, e.y)
        now = time.time()
        if now > self._spark_cd and not self.studio_enabled():
            self._spark_cd = now + 0.07
            self.add_part("sparkle", e.x - self.W / 2, e.y - self.H / 2 - 4,
                          life=0.5, size=random.uniform(3, 6),
                          color=random.choice(STAR_COLORS), phase=random.uniform(0, 6.28))
        if self.stroke_acc > 430 and now > self.stroke_cd and self.state != "sleep":
            self.stroke_acc = 0.0
            self.stroke_cd = now + 6
            self.sfx.play("voice_giggle")
            self.hearts(e.x - self.W / 2, e.y - self.H / 2 - 10, 3)
            self.play_emotion("happy", 1.8)
            if random.random() < 0.5:
                self.say(random.choice(STROKE_LINES), 1.8)

    def on_menu(self, e):
        self.open_action_card(e.x_root, e.y_root)

    def close_action_card(self):
        card = getattr(self, 'action_card', None)
        if card is not None:
            card.close()

    def open_action_card(self, x, y):
        self.last_interact = time.time()
        self.close_action_card()
        try:
            self.action_card = InteractionCard(self, x, y)
        except Exception:
            import traceback
            traceback.print_exc()
            self._show_full_menu(x, y)

    def open_room_preview(self):
        """Enter the integrated house while keeping the same swing and AI pipeline."""
        self._set_house_mode(True)

    def open_house_3d(self):
        """3D 小屋试验窗口(I-25):Godot 独立进程渲染,数据只读复用
        ai_sessions/与额度快照,不碰本进程渲染管线。重复调用唤起已有窗口。"""
        exe = os.environ.get("HOUSE3D_GODOT", "")
        if not exe or not os.path.isfile(exe):
            exe = None
            for cand in (os.path.expanduser(r"~\godot4\Godot_v4.7.2-stable_win64.exe"),
                         os.path.join(HERE, "house3d", "Godot.exe")):
                if os.path.isfile(cand):
                    exe = cand
                    break
        if exe is None:
            self.say("3D 小屋需要 Godot 4,还没有安装")
            return
        home = os.path.join(HERE, "house3d")
        lock = os.path.join(home, "instance.lock")
        if os.path.isfile(lock):
            try:
                with open(lock, encoding="utf-8") as f:
                    pid = int(f.read().strip() or 0)
            except Exception:
                pid = 0
            if pid > 0 and self._pid_alive(pid):
                self.say("3D 小屋开着呢,就在屏幕角落")
                return
        try:
            subprocess.Popen([exe, "--path", home], cwd=home,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            import traceback
            traceback.print_exc()
            self.say("3D 小屋启动失败了")

    @staticmethod
    def _pid_alive(pid):
        k32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
        h = k32.OpenProcess(0x1000, False, int(pid))   # QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return True    # 查不到状态宁可当活着,避免重复拉起
            return code.value == 259   # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)

    def _show_full_menu(self, x, y):
        self.close_action_card()
        self.last_interact = time.time()
        if not self.core_profile():
            self._prewarm_tfx()
        old = getattr(self, '_popup_menu', None)
        if old is not None:
            try:
                old.destroy()
            except tk.TclError:
                pass
        try:
            m = self._build_menu()
        except Exception:
            # 菜单构建里但凡抛一次异常,整份菜单就出不来 —— 表现是
            # "右键没反应",而且所有只能从菜单进的功能一起消失,看着
            # 就像"功能少了一大半"。这个坑已经踩过两次(_magic_style_var、
            # magic_style),所以兜个底:至少让退出还点得到,并且把原因写进日志。
            import traceback
            traceback.print_exc()
            from popup_material import SurfaceMenu
            m = SurfaceMenu(self.root, tearoff=0)
            m.add_command(label="⚠ 菜单出错了,原因见 pet_error.log",
                          state="disabled")
            m.add_separator()
            m.add_command(label="退出", command=self.quit)
        try:
            self._popup_menu = m
            m.update_idletasks()
            area = work_area_at(x, y) or (0, 0, self.sw, self.sh)
            x, y = InteractionCard.position(x, y, m.winfo_reqwidth(), m.winfo_reqheight(), area)
            m.tk_popup(x, y)
        finally:
            m.grab_release()

    def _menu(self, parent=None):
        """和桌宠同款主题的弹出菜单:UI_* 深色面板底 + 主文字 + 按钮色
        高亮。右键菜单和全部子菜单都走这一套,不再用系统默认的白底。"""
        from popup_material import SurfaceMenu
        return SurfaceMenu(parent or self.root, tearoff=0,
                       font=ui_font(13), relief="flat", bd=1,
                       bg=UI_PANEL, fg=UI_TEXT,
                       activebackground=UI_BTN, activeforeground=UI_TITLE,
                       disabledforeground=UI_TEXT_DIM,
                       selectcolor=UI_FIELD)

    def _build_menu(self):
        if not self.core_profile():
            return self._build_legacy_menu()
        m = self._menu()
        m.add_command(label="小乔 · 时之魔女", state="disabled")
        m.add_separator()
        m.add_command(label="聊天与对话记录", command=self.open_chat)
        m.add_command(label="摸摸头", command=self.pet_head)
        m.add_command(label="喂颗糖", command=self.eat_candy)
        napping = self.state in ("sleep", "yawn") or getattr(self, "_nap_on_swing", False)
        m.add_command(label="叫醒" if napping else "休息", command=self.wake_up if napping else self.go_sleep)
        m.add_separator()
        scenes = self._menu(m)
        scenes.add_command(label="秋千", command=self.open_swing_scene)
        scenes.add_command(label="小屋 · Live2.5D", command=self.open_room_preview)
        scenes.add_command(label="3D 小屋（试验）", command=self.open_house_3d)
        m.add_cascade(label="场景", menu=scenes)
        m.add_command(label="AI 工作轨迹与额度", command=self.open_ai_panel)
        cfg = self._menu(m)
        cfg.add_command(label="声音:" + ("开" if self.sound_on else "关"), command=self.toggle_sound)
        cfg.add_command(label="朗读回复:" + ("开" if self.tts_on else "关"), command=self.toggle_tts)
        cfg.add_command(label="AI 状态灯:" + ("开" if self.ai_lights else "关"), command=self.toggle_ai_lights)
        cfg.add_command(label="AI 任务提醒:" + ("开" if self.ai_announce else "关"), command=self.toggle_ai_announce)
        cfg.add_separator()
        sizes = self._menu(cfg)
        for label, scale in (("小", .8), ("标准", 1.0), ("大", 1.25)):
            sizes.add_command(label=label, command=lambda value=scale: self.set_scale(value))
        cfg.add_cascade(label="大小 · 也可滚轮缩放", menu=sizes)
        cfg.add_command(label="取消置顶" if self.topmost else "置顶", command=self.toggle_topmost)
        cfg.add_command(label="关闭鼠标穿透" if self.click_through else "鼠标穿透", command=self.toggle_click_through)
        cfg.add_command(label="开机启动:" + ("开" if autostart_enabled() else "关"), command=self.toggle_autostart)
        cfg.add_separator()
        cfg.add_command(label="连接 AI 聊天…", command=self.setup_api_key)
        m.add_cascade(label="设置", menu=cfg)
        m.add_separator()
        m.add_command(label="退出", command=self.quit)
        return m

    def _build_legacy_menu(self):
        """把整份右键菜单建出来并返回。抽成单独一个方法,
        是为了让 on_menu 能在它出错时退回一份最小可用菜单。"""
        m = self._menu()
        m.add_command(label="✦ 小乔 · 时之魔女", state="disabled")
        m.add_command(label=f"陪伴第 {self.companion_days()} 天  ·  "
                            f"星光 {int(self.star)}%  ·  {self.affection_level()}",
                      state="disabled")
        m.add_separator()
        # 最高频的四个动作放一级,剩下的按场景收进子菜单
        m.add_command(label="摸摸头", command=self.pet_head)
        m.add_command(label="吃星光糖果", command=self.eat_candy)
        napping = self.state in ("sleep", "yawn") or getattr(self, "_nap_on_swing", False)
        m.add_command(label="叫醒小乔" if napping else "睡一觉",
                      command=lambda: (self.wake_up() if self.state in ("sleep", "yawn")
                                       else self._wake_from_nap())
                      if (self.state in ("sleep", "yawn")
                          or getattr(self, "_nap_on_swing", False))
                      else self.go_sleep())
        # R114 时间魔法双版本(子菜单,可在两种风格间选择,或设为默认)
        magic_m = self._menu(m)
        magic_m.add_command(label="原版(默认)",
                            command=lambda: self.cast_magic(style=0))
        magic_m.add_command(label="✨ 全屏炫酷版",
                            command=lambda: self.cast_magic(style=1))
        magic_m.add_separator()
        magic_m.add_checkbutton(label="默认使用炫酷版",
                                command=self.toggle_magic_style,
                                variable=self._magic_style_var)
        m.add_cascade(label="⏳ 时间魔法 ▸", menu=magic_m)
        m.add_command(label="✦ 和小乔聊天", command=self.open_chat)
        m.add_command(label=("停止唱歌" if self.singing else "唱首歌 ♪"),
                      command=self.sing)

        # ---- 一起玩 ----
        play = self._menu(m)
        play.add_command(label="🌟 撒一把星星(点星接住!)", command=self.star_rain)
        play.add_command(label="💫 转个圈", command=self.start_twirl)
        play.add_command(label="💃 跳个舞", command=self.start_dance)
        play.add_command(label="🤸 后空翻", command=self.start_flip)
        play.add_command(label="✨ 魔法变身(30s 星光形态)", command=self.start_transform)
        play.add_command(label="🤪 打个滚", command=self.start_roll)
        play.add_command(label="👋 挥挥手", command=self.start_wave)
        play.add_command(label="⚽ 玩球(扔给她接!)", command=self.throw_ball)
        play.add_command(label=("🪢 从秋千上下来" if self.state == "swing"
                                else "🌙 荡秋千(月牙星链)"),
                        command=self.toggle_swing)
        play.add_command(label="☾ 小屋布局样稿…", command=self.open_room_preview)
        play.add_command(label="🧘 伸懒腰", command=self.start_stretch)
        play.add_command(label="🔭 发会儿呆", command=self.start_peek)
        play.add_command(label="🏃 过来我这边", command=self.start_chase)
        play.add_command(label="⏰ 现在几点?", command=self.tell_time)
        play.add_command(label="⏳ 时停:时间,停止!",
                         command=self.start_time_stop)
        play.add_command(label="⏪ 时间回溯", command=self.start_rewind)
        play.add_separator()
        rps = self._menu(play)
        for k, (cn, emo) in self.RPS.items():
            rps.add_command(label=f"{emo} {cn}", command=lambda k=k: self.play_rps(k))
        rps.add_separator()
        rps.add_command(label=f"战绩 她{self.rps[0]}胜 {self.rps[1]}平 {self.rps[2]}负",
                        state="disabled")
        play.add_cascade(label="石头剪刀布 ✊", menu=rps)
        m.add_cascade(label="一起玩 ▸", menu=play)

        # ---- 小本事 ----
        tools = self._menu(m)
        tools.add_command(label="定个提醒…", command=self.reminder_dialog)
        tools.add_command(label="帮我找文件…", command=self.find_file_dialog)
        tools.add_command(label="看看我的剪贴板 ✦", command=self.summarize_clipboard)
        tools.add_command(label="翻译剪贴板 ✦", command=self.translate_clipboard)
        tools.add_command(label="看看我的屏幕 ✦", command=lambda: self.look_screen(""))
        tools.add_command(label="现在天气如何?", command=self.ask_weather)
        tools.add_separator()
        pm = self._menu(tools)
        for label, v in (("专注 25 分钟", 25), ("专注 50 分钟", 50),
                         ("停止番茄钟", 0)):
            pm.add_command(label=label,
                           command=lambda v=v: self.start_pomodoro(v))
        tools.add_cascade(label="番茄钟", menu=pm)
        wm = self._menu(tools)
        for label, v in (("关", 0), ("每 30 分钟", 30), ("每 45 分钟", 45),
                         ("每 60 分钟", 60), ("每 90 分钟", 90)):
            mark = "●" if self.water_min == v else "○"
            wm.add_command(label=f"{mark} {label}",
                           command=lambda v=v: self.set_water_reminder(v))
        tools.add_cascade(label="喝水提醒", menu=wm)
        if self.brain:
            tools.add_command(label="AI 主动搭话:" +
                              ("开" if self.brain.cfg.get("greet_interval_min", 0) > 0 else "关"),
                              command=self.toggle_greet)
        m.add_cascade(label="小本事 ▸", menu=tools)

        # ---- 设置 ----
        cfg = self._menu(m)
        cfg.add_command(label="语音(全部声音):" + ("开" if self.sound_on else "关"),
                        command=self.toggle_sound)
        cfg.add_command(label="开机自启:" + ("开" if autostart_enabled() else "关"),
                        command=self.toggle_autostart)
        cfg.add_command(label="开口说话:" + ("开" if self.tts_on else "关"),
                        command=self.toggle_tts)
        cfg.add_command(label="偷看窗口:" + ("开" if self.fg_watch else "关"),
                        command=self.toggle_fg_watch)
        cfg.add_command(label="电量提醒:" + ("开" if self.battery_watch else "关"),
                        command=self.toggle_battery_watch)
        cfg.add_command(label="帽檐星轨:" + ("开" if self.hat_orbit else "关"),
                        command=self.toggle_hat_orbit)
        cfg.add_command(label="AI 会话灯:" + ("开" if self.ai_lights else "关"),
                        command=self.toggle_ai_lights)
        cfg.add_command(label="任务提醒播报:" + ("开" if self.ai_announce else "关"),
                        command=self.toggle_ai_announce)
        cfg.add_command(label="默认住在秋千上:" + ("开" if self.swing_home else "关"),
                        command=self.toggle_swing_home)
        cfg.add_separator()
        szm = self._menu(cfg)
        for label, s in (("小 80%", 0.8), ("中 100%", 1.0), ("大 125%", 1.25),
                         ("加大 150%", 1.5), ("超大 175%", 1.75)):
            szm.add_command(label=label, command=lambda s=s: self.set_scale(s))
        cfg.add_cascade(label="大小", menu=szm)
        cfg.add_command(label=("取消置顶" if self.topmost else "窗口置顶"),
                        command=self.toggle_topmost)
        cfg.add_command(label=("关闭鼠标穿透" if self.click_through else "鼠标穿透(点不到我)"),
                        command=self.toggle_click_through)
        cfg.add_separator()
        cfg.add_command(label="设置 AI 密钥…", command=self.setup_api_key)
        cfg.add_command(label=f"清空聊天记录({len(self.chat_log)} 条)",
                        command=self.clear_chat,
                        state=("normal" if self.chat_log else "disabled"))
        cfg.add_command(label="设置城市…", command=self.set_city_dialog)
        anniv = self.settings.get("anniv_date")
        cfg.add_command(label=("取消纪念日(当前: " + anniv + " " +
                               self.settings.get("anniv_name", "") + ")")
                        if anniv else "设置纪念日…",
                        command=self.anniv_dialog)
        cfg.add_command(label="设置我的生日(用于「生日快乐」彩蛋)",
                        command=self.birthday_dialog)
        m.add_cascade(label="设置 ▸", menu=cfg)

        m.add_separator()
        m.add_command(label="退出", command=self.quit)
        return m

    def set_scale(self, s):
        s = max(0.6, min(1.75, s))   # 上限对齐菜单里的"超大 175%",不然选了也落回 1.7
        if abs(s - self.scale) < 0.01:
            return
        self.scale = s
        self.W = int(BASE_W * s)
        self.H = int(BASE_H * s)
        self.ground_feet = self.sh - int(FEET_GAP * s)
        self._refresh_screen()          # 尺寸变了,边界要跟着重算
        self._clamp_pos()
        self.rebuild_scale_cache()
        self.root.geometry(f"{self.W}x{self.H}+{int(self.x)}+{int(self.fy - self.FOOT_Y)}")
        self.save_settings()

    def _refresh_screen(self):
        """刷新屏幕边界。每隔几秒复查一次 —— 插拔外接屏、改分辨率之后
        才不会出现"地面还是旧值"(悬空或陷进任务栏)和"存的 x 落在屏幕外"。

        横向范围取虚拟桌面:只用主屏宽度的话她永远走不到第二块屏。
        地面高度取她当前所在那块显示器的工作区下沿,自动避开任务栏。
        """
        vs = virtual_screen()
        vx, vy, vw, vh = vs if vs else (0, 0, self.sw, self.sh)
        changed = (vx, vy, vw, vh) != self._vscreen
        self._vscreen = (vx, vy, vw, vh)
        self.x_min = vx + 4
        self.x_max = vx + vw - self.W - 4
        wa = work_area_at(getattr(self, "x", vx) + self.W / 2,
                          getattr(self, "fy", vy + vh * 0.8))
        bottom = wa[3] if wa else vy + vh
        ground = bottom - int(FEET_GAP * self.scale)
        if ground != self.ground_feet:
            self.ground_feet = ground
            changed = True
        if changed and hasattr(self, "fy"):
            self._clamp_pos()
        return changed

    def _clamp_pos(self):
        self.x = max(self.x_min, min(self.x, self.x_max))
        top_min = 40
        self.fy = max(top_min + self.H * 0.6, min(self.fy, float(self.ground_feet)))

    def toggle_topmost(self):
        self.topmost = not self.topmost
        self.root.attributes("-topmost", self.topmost)
        # 秋千层按新的置顶设定重建(下一帧 frame 自动建好、插回她身后)
        self.swing_layer.close()
        self.save_settings()

    def toggle_click_through(self):
        self._set_house_hover(None)
        """左键穿透、右键保留。

        Win32 的 WS_EX_TRANSPARENT 是整窗口全透,连右键都透过去,
        关掉就完全点不到。改用 Tk 层面拦截:左键按下时自己把事件
        投递给 z 序上下一个窗口,桌宠当透明;右键 / 滚轮 / 中键照常
        响应,菜单照开。
        """
        self.click_through = not self.click_through
        self._apply_click_through_bindings()
        self.save_settings()

    def _apply_click_through_bindings(self):
        """根据 click_through 状态挂/解绑鼠标事件。

        穿透时:左键/双击/移动/移入移出都关 —— 桌宠把自己当透明玻璃,
        只留右键菜单、滚轮顺毛、中键彩蛋。
        """
        root = self.root
        if self.click_through:
            root.bind("<ButtonPress-1>", self._on_press_passthrough)
            root.bind("<Double-Button-1>", self._on_double_passthrough)
            root.unbind("<B1-Motion>")
            root.unbind("<ButtonRelease-1>")
            root.unbind("<Motion>")
            root.unbind("<Enter>")
            root.unbind("<Leave>")
        else:
            root.bind("<ButtonPress-1>", self.on_press)
            root.bind("<B1-Motion>", self.on_drag)
            root.bind("<ButtonRelease-1>", self.on_release)
            root.bind("<Double-Button-1>", self.on_double)
            root.bind("<Motion>", self.on_hover)
            root.bind("<Enter>", self.on_enter)
            root.bind("<Leave>", self.on_leave)

    def _post_click_below(self, e):
        """把左键 down/up 投递到鼠标位置 z 序下的下一个窗口。

        桌宠常驻 WS_EX_TOPMOST 列表,跟普通窗口不在同一个 z 序链里,
        GW_HWNDNEXT 不会跨列表 —— 沿自己列表走完就 NULL,再也找不到
        下层窗口。要同时考虑 topmost 和非 topmost 两条链,得自己拼。

        流程:鼠标位置 → 候选 1=WindowFromPoint(最顶层,跨列表);
              如果候选 1 就是自己,沿"自己所在链"向后走,跳过自己,再
              跳到另一条链的最顶。两个候选都不行就放弃。
        """
        try:
            pt = wintypes.POINT(e.x_root, e.y_root)
            self_hwnd = self.hwnd or 0
            top = user32.WindowFromPoint(ctypes.byref(pt)) or 0
            # 找 z 序上"自己下面"那一个窗口。
            # 先看 WindowFromPoint 是不是自己(最常见情形:鼠标在桌宠上)
            if top and top != self_hwnd:
                target = top
            else:
                # 自己是顶层。沿自己所在列表 GW_HWNDNEXT 向后找。
                target = self._next_visible_window(self_hwnd)
            if not target or target == self_hwnd:
                return False
            # 二次确认目标矩形真包含鼠标(WindowFromPoint 已经保证)
            user32.ScreenToClient(target, ctypes.byref(pt))
            lparam = (pt.y & 0xFFFF) << 16 | (pt.x & 0xFFFF)
            wparam = 0
            user32.PostMessageW(target, 0x0201, wparam, lparam)  # WM_LBUTTONDOWN
            user32.PostMessageW(target, 0x0202, wparam, lparam)  # WM_LBUTTONUP
            return True
        except Exception:
            return False

    def _next_visible_window(self, hwnd):
        """从 hwnd 出发,沿 z 序向后找第一个非自己、可见的顶层窗口。

        桌宠常驻 topmost,先沿 topmost 链走(本进程内 GW_HWNDNEXT 已经
        能跨同 z 序的兄弟),走完跳到非 topmost 链的最顶 GetTopWindow。
        """
        cur = user32.GetWindow(hwnd, 4)  # GW_HWNDNEXT
        steps = 0
        while cur and steps < 256:
            if cur != hwnd and user32.IsWindowVisible(cur):
                return cur
            cur = user32.GetWindow(cur, 4)
            steps += 1
        # 走到链尾(NULL),从另一条链最顶开始
        alt = user32.GetTopWindow(None)  # 非 topmost 列表最顶
        steps = 0
        while alt and steps < 256:
            if alt != hwnd and user32.IsWindowVisible(alt):
                return alt
            alt = user32.GetWindow(alt, 4)
            steps += 1
        return 0

    def _on_press_passthrough(self, e):
        """穿透模式下的左键按下:投递给下方窗口,桌宠不响应。"""
        # 如果当时正在拖动桌宠(罕见,但拖动期间切到穿透也要继续),不动
        if self.drag:
            return
        self._post_click_below(e)
        return "break"

    def _on_double_passthrough(self, e):
        """穿透模式下的双击:也是下方窗口的事,桌宠不响应。"""
        self._post_click_below(e)
        return "break"

    def quit(self):
        panel = getattr(self, "_ai_work_panel", None)
        if panel is not None and not panel.closed:
            panel.close()
        self.close_action_card()
        room = getattr(self, "_room_preview", None)
        if room is not None and not room.closed:
            room.close()
        self.fsmagic.close()
        self.swing_layer.close()
        self._swing = None
        self._swing_pull = None
        self.save_settings()
        self.stop_sing()
        self.sfx.close_all()
        if self._tray:
            try:
                self._tray.stop()
            except Exception:
                pass
        # Destroying a Tk window does not remove its Tcl timer scripts. Cancel
        # this interpreter's callbacks first, including delayed warmups/tick.
        for timer in self.root.tk.call("after", "info"):
            try:
                self.root.after_cancel(timer)
            except tk.TclError:
                pass
        self.root.destroy()

    def post(self, fn):
        self.mainq.put(fn)

    # ==================== 托盘 ====================
    def start_tray(self):
        self._tray = None
        if not HAS_TRAY:
            return
        try:
            ms = self.main_src
            # 图标裁脸:icon_box = (中心 x, 中心 y, 边长),都按立绘比例(边长按高)
            icx, icy, iside = self.cfg.get("icon_box", (0.47, 0.28, 0.44))
            side = int(ms.height * iside)
            cx0 = max(0, int(ms.width * icx - side / 2))
            cy0 = max(0, int(ms.height * icy - side / 2))
            icon_img = ms.crop((cx0, cy0, cx0 + side, cy0 + side)).resize((64, 64))
            menu = pystray.Menu(
                pystray.MenuItem("显示/隐藏", lambda: self.post(self.toggle_visible),
                                 default=True),
                pystray.MenuItem("和小乔聊天 ✦", lambda: self.post(self.open_chat)),
                pystray.MenuItem("小屋 · Live2.5D", lambda: self.post(self.open_room_preview)),
                pystray.MenuItem("3D 小屋（试验）", lambda: self.post(self.open_house_3d)),
                pystray.MenuItem("AI 工作轨迹与额度", lambda: self.post(self.open_ai_panel)),
                pystray.MenuItem(lambda item: "语音:开" if self.sound_on else "语音:关",
                                 lambda: self.post(self.toggle_sound)),
                pystray.MenuItem("退出", lambda: self.post(self.quit)))
            self._tray = pystray.Icon("xiaoqiao", icon_img, "小乔·时之魔女", menu)
            threading.Thread(target=self._tray.run, daemon=True).start()
        except Exception as e:
            print("托盘不可用:", e)
            self._tray = None

    # ==================== 调试/自动化 ====================
    def _exec_cmd(self, cmd):
        op = cmd.get("op")
        allowed = {"open_chat", "send", "sleep", "wake", "feed", "pet", "room",
                   "swing", "panel", "book", "sel", "demo", "announce", "state",
                   "toggle_click_through", "toggle_sound", "toggle_visible"}
        if self.core_profile() and (op not in allowed or
                                   (op == "swing" and not cmd.get("on", True))):
            return False
        if op == "room":
            self.open_room_preview()
        elif op == "wake":
            self.wake_up()
        elif op == "feed":
            self.eat_candy()
        elif op == "open_chat":
            self.open_chat()
        elif op == "send":
            self.open_chat()
            cb = self.chatbox
            if cb:
                cb.entry.delete(0, "end")
                cb.entry.insert(0, str(cmd.get("text", ""))[:500])
                cb.send()
        elif op == "think":
            self._think_demo_until = time.time() + float(cmd.get("secs", 6))
        elif op == "sing":
            self.sing()
        elif op == "sleep":
            self.go_sleep()
        elif op == "state":
            canvas = (getattr(self, "_swing", None) or {}).get("scene_canvas")
            if cmd.get("capture") and canvas is not None:
                canvas.save(str(cmd["capture"]))
            self._write_state()
        elif op == "play_emotion":
            self.play_emotion(cmd.get("category", "happy"), 2.6)
        elif op == "dance":
            self.start_dance()
        elif op == "stretch":
            self.start_stretch()
        elif op == "peek":
            self.start_peek()
        elif op == "flip":
            self.start_flip()
        elif op == "wave":
            self.start_wave()
        elif op == "roll":
            self.start_roll()
        elif op == "transform":
            self.start_transform()
        elif op == "chase":
            self.start_chase()
        elif op == "dizzy":
            self.go_dizzy()
        elif op == "pet":
            self.pet_head()
        elif op == "throw":
            self.throw(float(cmd.get("vx", 900)), float(cmd.get("vy", -700)))
        elif op == "rps":
            self.play_rps(cmd.get("mine", "rock"))
        elif op == "toggle_click_through":
            self.toggle_click_through()
        elif op == "toggle_sound":
            self.toggle_sound()
        elif op == "toggle_visible":
            self.toggle_visible()
        elif op == "play_sfx":
            # 外部测试用:{"op":"play_sfx","name":"magic"}
            self.sfx.play(str(cmd.get("name", "greet")))
        elif op == "remind":
            # 外部(ZCode/脚本)也能塞提醒进来:{"op":"remind","minutes":5,"text":"..."}
            self._schedule_reminder(cmd.get("minutes", 25), cmd.get("text", ""))
        elif op == "meditate":
            self.start_meditate()
        elif op == "swing":
            # 外部(ZCode/脚本):{"op":"swing"} 让她上秋千(已经坐着就荡高点),
            # {"op":"swing","on":false} 让她下来。原来是 toggle —— 她默认就住
            # 在秋千上,"让她荡秋千"反而把她叫了下来
            if cmd.get("on", True):
                self.mount_swing()
            else:
                self.dismount_swing()
        elif op == "panel":
            self._book_open = (bool(cmd["show"]) if "show" in cmd else not self._book_open)
            self._book_tab = "overview"
            if cmd.get("provider") in ("codex", "claude", "zcode"):
                self._quota_provider = cmd["provider"]
        elif op == "book":
            self._book_open = not self._book_open         # 演示/截图用:轨迹
            self._book_tab = "trace"
        elif op == "sel":
            # 自动化/截图用:固定选中来源(等同点击芯片)
            self._book_sel = ("agent", str(cmd.get("source") or ""))
            if getattr(self, "_flat_panel_style", False):
                from flat_workspace import agent_name
                self._flat_agent = agent_name(cmd.get("source"))
                self._flat_mode = "tasks"
                self._flat_scroll = 0
                self._flat_cache = None
        elif op == "demo":
            # 演示/截图用:注入模拟会话与额度(页脚明确标注模拟,不碰真实文件)
            self._demo_until = time.time() + float(cmd.get("secs", 60))
            self._demo_sessions = cmd.get("sessions") or []
            self._demo_quota = cmd.get("quota")
            if DEBUG_STATE and isinstance(cmd.get("hat_fx"), dict):
                self._configure_hat_fx_demo(cmd["hat_fx"], float(cmd.get("secs", 60)))
        elif op == "announce":
            if not getattr(self, "ai_announce", True)                     or "zcode" in (getattr(self, "ai_mute_sources", set())
                                   or set()):
                return                  # 总静音/该来源静音:灯照常,气泡免了
            # Permission hooks keep their immediate delivery; mark the same waiting
            # episode so the companion does not repeat it twenty seconds later.
            if getattr(self, "_flat_panel_style", False):
                from agent_companion import acknowledge_hook
                acknowledge_hook(self, time.time())
            # ZCode hook 用:任务完成/需要确认时播报,不走 AI 直接说
            self._reply(str(cmd.get("text", ""))[:200],
                        cmd.get("emotion") if cmd.get("emotion") in
                        ("happy", "curious", "excited", "surprised", "tired") else "happy")

    def _write_state(self):
        try:
            cb = self.chatbox
            data = {
                "time": time.time(),
                "state": self.state,
                "bubble": self.bubble[0] if self.bubble else None,
                "history_n": len(self.history),
                "ai_thinking": self.ai_thinking,
                "hat_fx": (self.fx.hat.stats() if getattr(self.fx, "hat", None) is not None else None),
                "hat_fx_demo": time.time() < getattr(self, "_hat_fx_demo_until", 0),
                "brain_ok": self._ai_ready(),
                "panel_visible": bool(cb and cb.win.winfo_exists()
                                      and cb.win.winfo_ismapped()),
                "crystal_panel": self._crystal_open,
                "nap": getattr(self, "_nap_on_swing", False),
                "scene_scale": (self._swing or {}).get("scene_scale"),
                "theta": round((self._swing or {}).get("theta", 0.0), 3),
                "pend_amp": round(((self._swing or {}).get("pend").amplitude
                                   if (self._swing or {}).get("pend") else 0.0), 4),
                "book_panel": self._book_open,
                "house_mode": self.house_enabled(),
                "ai_state": crystal_state(self._ai_sessions),
                "workspace": (__import__("flat_workspace").runtime_state(self)
                              if getattr(self, "_flat_panel_style", False) else None),
                "ai_panel": {"open": bool(getattr(self, "_book_open", False)),
                             "tab": getattr(self, "_book_tab", None),
                             "quota_provider": getattr(self, "_quota_provider", None),
                             "workflow_sessions": len(getattr(self, "_ai_work_sessions", self._ai_sessions)),
                             "codex_quota_connected": bool(getattr(self, "_codex_quota", None))},
                "chat_log": (cb.log.get("1.0", "end") if cb and cb.win.winfo_exists()
                             and cb.log.winfo_exists() else None),
                # 性能观测量:帧耗滑动平均/当前档位/粒子与缓存规模,
                # 给以后的调优决策留数据(配合 --debug-state 用)
                "frame_ms": round(getattr(self, "_frame_ms", 0.0), 2),
                "frame_delay": self._frame_delay(),
                "quiet_idle": self._quiet_idle_ok(),
                "quiet_block": getattr(self, "_quiet_block", ""),
                "focus": self.focus_mode(),
                "particles": len(self.parts),
                "warp_cache": len(self._warp_cache),
            }
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:
            self._log_exc("state export")

    def toggle_visible(self):
        if self.root.state() == "withdrawn":
            self.root.deiconify()
        else:
            self.root.withdraw()
            panel = getattr(self, "_ai_work_panel", None)
            if panel is not None and not panel.closed:
                panel.close()
            # 秋千层是独立的置顶窗口,不跟 root 一起隐藏;隐藏期间 tick 只泵
            # 消息、没人收它,绳椅会定格在屏幕最上层。关掉即可:重新显示后
            # 下一帧 frame() 自己重建、插回她身后
            self.swing_layer.close()

    # ==================== 主循环 ====================
    def tick(self):
        self._beat = time.time()   # 看门狗心跳:这一行能跑到,主循环就是活的
        delay = 33
        try:
            if self.root.state() == "withdrawn":
                self._pump()      # 托盘隐藏:整条渲染管线跳过,只泵消息
                delay = 100       # 隐藏时只需要泵消息,不用 30Hz
            else:
                t0 = time.perf_counter()
                self._tick_body()
                spent = (time.perf_counter() - t0) * 1000.0
                # 单帧耗时滑动平均 + 迟滞。60fps 只在真的画得动的机器上开:
                # 画不动却硬排 16ms,结果是排期积压后的抖动,比稳定 30fps
                # 还难看。带迟滞是免得在阈值上来回横跳。
                self._frame_ms += (spent - self._frame_ms) * 0.1
                if self._frame_ms > FAST_BUDGET_MS:
                    self._fast_ok = False
                elif self._frame_ms < FAST_BUDGET_MS * 0.7:
                    self._fast_ok = True
                delay = self._paced_delay(spent)
        except Exception:
            self._log_exc("tick")
        self.root.after(delay, self.tick)

    def _start_watchdog(self):
        """主循环卡死自愈:心跳停滞超过阈值就落盘线程栈并重启自己。

        Tk 是单线程的,mainloop 一旦悄悄卡死,窗口还在、进程还在,但渲染
        冻结、所有鼠标事件(包括右键菜单)全部没反应;更糟的是单实例保护
        会把任何"再开一只"的自救挡回去,只能任务管理器杀进程。
        2026-09-08 就冻了将近 30 小时。正常情况下 tick 每 33~100ms 摸一次
        心跳(隐藏到托盘也照跑),只有 mainloop 真卡住才会连续超时。
        系统睡眠/休眠不误杀:醒来后心跳滞后是负数或大得离谱,视为时钟
        跳变,重新观察。
        """
        self._beat = time.time()
        self._wd_armed = False

        def guard():
            stale_since = None
            while True:
                time.sleep(5)
                lag = time.time() - self._beat
                if lag < WATCHDOG_STALE or lag > 300:
                    # 300s 以上说明中途发生过睡眠/时钟跳变,不是卡死
                    stale_since = None
                    self._wd_armed = False
                    continue
                if stale_since is None:
                    stale_since = time.time()     # 第一轮发现停滞,先观察一轮
                    continue
                if not self._wd_armed:
                    self._wd_armed = True         # 连续两轮都停滞,武装
                    continue
                # 确认卡死(连续 ~15s 无心跳):留下案发现场再走
                try:
                    with open(os.path.join(HERE, "pet_error.log"),
                              "a", encoding="utf-8") as f:
                        print(f"\n[watchdog] 主循环 {int(lag)}s 无心跳,判定卡死,"
                              "dump 全部线程栈后自重启:", file=f, flush=True)
                        faulthandler.dump_traceback(file=f)
                except Exception:
                    pass
                try:
                    self.save_settings()
                except Exception:
                    pass
                # 卡死的 mainloop 里普通退出走不出来,直接换镜像;
                # --wait-lock 让新进程等旧进程放手再抢单实例锁
                try:
                    extra = sys.argv if not getattr(sys, "frozen", False) \
                        else sys.argv[1:]
                    os.execv(sys.executable,
                             [sys.executable] + list(extra) + ["--wait-lock"])
                except Exception:
                    pass
                os._exit(1)   # execv 失败(杀软拦截等)也要把僵尸放掉

        threading.Thread(target=guard, daemon=True, name="watchdog").start()

    def _paced_delay(self, spent_ms):
        """下一帧还要等多久 = 目标帧间隔 - 这一帧已经花掉的时间。

        原来是干完活再固定 after(_frame_delay()),渲染耗时被叠加进间隔:
        标称 30fps 的档位,一帧画 36ms 时实际只有 13fps(跳舞实测)。而且
        _tick_body 的 dt 上限是 50ms,帧间隔超过它时,按时间推进的动作会被
        放慢成慢动作。最少留 4ms,给 Tk 处理鼠标键盘事件的空隙。
        """
        return max(4, int(self._frame_delay() - spent_ms))

    def _frame_delay(self):
        """按"画面上还有没有东西在动"决定下一帧间隔。

        四档:互动/演出 60fps,常规 30fps,安静待机 20fps,睡着且完全
        静止 10fps。每秒全量重绘 200 万像素是笔记本上最大的一笔电,所以
        60fps 只给真正看得出差别的时刻(拖拽、大招、翻滚、演出粒子在飞)
        —— 点击走的是 Tk 事件不是这个循环,响应速度在哪一档都不受影响。
        注意待机时她周围常驻环境星光(AMBIENT_PARTS),那是慢速飘浮的
        氛围元素,不该把待机拽进 60fps 档。

        _fast_ok 由 tick 里的单帧耗时实测控制:画不动 60fps 的机器会自动
        停在 30fps,不会因为排了 16ms 却跑不满而抖。
        """
        if self.state == "sleep" and not self.drag:
            if self.bubble or self.sticker or self.circles or self.thinking_now:
                return 33
            # zzz 是睡眠专属的慢飘粒子,它自己不需要 30fps
            if any(p["kind"] != "zzz" for p in self.parts):
                return 33
            return 100
        if self._fast_ok and (
                self.drag or self._micro_motion or self.state in FAST_STATES
                or self.singing          # 主人点的唱歌:摆动+音符,按演出对待
                or any(p["kind"] not in _NOT_FAST_PARTS for p in self.parts)):
            return 16
        if self.state == "swing" and self._scene_drag:
            # 按住拖整个秋千场景:跟手,走互动档(画不动 60fps 的机器停在
            # 30fps)。拖场景不设 self.drag,原来那条 swing+drag 永远走不到
            return 16 if self._fast_ok else 33
        if getattr(self, "_nap_on_swing", False) and not self.drag:
            # 秋千打盹安静档:go_sleep 的秋千分支刻意保持 state=="swing"
            # (场景/绳手/接触不动),所以打盹永远落不进上面的睡眠档,而是
            # 落进下面的常驻荡 50ms 档,闭眼打盹也按 20fps 全管线重绘
            # (实测 ~30% 单核)。镜像睡眠档的判据:有互动信号(气泡/贴纸/
            # 法阵/思考/任何非 zzz 粒子)当帧回互动档,不会"叫不醒";
            # zzz 是慢飘粒子,10fps 足够。拖拽/场景拖拽/演出在上面的分支
            # 已先返回,优先级更高。
            if self.bubble or self.sticker or self.circles or self.thinking_now:
                return 33
            if any(p["kind"] != "zzz" for p in self.parts):
                return 33
            return 100
        if self.state == "swing":
            return 50                    # 常驻荡:20fps 足够,层推帧是大头
        # 安静待机 20fps:idle 态、没有任何演出元素(气泡/贴纸/法阵/思考/
        # 嘴型/蹦跳/眨眼窗口)、只剩她本人的呼吸浮动(±3.5px/2s)和氛围
        # 粒子、4 秒内没互动、光标也离得远 —— 20fps 与 30fps 肉眼无差别,
        # 待机 CPU 却省下三分之一。任何信号变化下一帧立即回到 30fps。
        if self._quiet_idle_ok():
            return 50
        return 33

    def _quiet_idle_ok(self):
        """安静待机判定(state 文件也报一份,方便核对哪个条件没过)。"""
        block = None
        if self.state != "idle":
            block = "state"
        elif self.drag or self.bubble or self.sticker or self.circles or self._micro_motion:
            block = "show"
        elif self.thinking_now or self.singing or self.hop_t > 0 \
                or self.lean_kick > 0 or time.time() <= self.blink_until \
                or getattr(self, "_mouth", None):
            block = "anim"
        elif time.time() - self.last_interact <= 4:
            block = "interact"
        elif not all(p["kind"] in AMBIENT_PARTS for p in self.parts):
            block = "parts"
        else:
            mx, my = cursor_pos()
            if math.hypot(mx - (self.x + self.W / 2),
                          my - (self.fy - self.H * 0.35)) > 260 * self.scale:
                return True
            block = "cursor"
        self._quiet_block = block
        return False

    def _chat_open(self):
        """聊天面板是否开着(开着期间不自动入睡)。"""
        cb = self.chatbox
        try:
            return bool(cb and cb.win.winfo_exists() and cb.win.winfo_ismapped())
        except Exception:
            return False

    def toggle_magic_style(self):
        self.magic_style = 1 - self.magic_style
        self._magic_style_var.set(self.magic_style == 1)
        self.save_settings()          # 原来不落盘,改完重启就忘了
        # 原来 save_settings 和 say 各写了两遍,第二个 say 用随机台词把下面
        # 这句正确的覆盖掉 —— 切到全屏版有 1/3 概率说"风格切到原版啦"。
        self.say("以后默认放全屏版!" if self.magic_style
                 else "好,换回原来那个~", 2.0)

    def _pump(self):
        """跨线程回调 + 外部指令轮询。隐藏到托盘时这是唯一还活着的东西,
        保证托盘菜单和 pet_cmd.json 在隐藏状态下照常可用。"""
        # 跨线程回调。逐条隔离:某一条回调炸了不能中断本帧泵送 ——
        # 队列里排在后面的回调、以及下面的外部指令轮询,都会被吞掉一轮
        while True:
            try:
                fn = self.mainq.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:
                self._log_exc("pump")
        # AI 会话灯:限频扫描 ai_sessions/(每 2 秒一次,不逐帧 listdir)
        if time.time() >= self._next_ai_scan:
            try:
                self._scan_ai_sessions()
            except Exception:
                self._next_ai_scan = time.time() + 5.0
        # 调试/自动化:读 pet_cmd.json(状态文件隐藏期间冻结,无妨)。
        # 先解析成功再推进 _cmd_seen:赶上写入方写到一半时,下一帧 mtime
        # 变化后会自然重试,指令不会丢;同一个 mtime 只报一次错,不刷日志。
        # 空文件(截断式写入的中间态)静默跳过,连日志都不用。
        mt = None       # 必须先占位:getmtime 抛异常时(文件刚被删/权限问题)
                        # 下面的 except 会读它,未定义就再抛一次 UnboundLocalError,
                        # 而那一次没人接得住
        try:
            if os.path.exists(self.cmd_path):
                mt = os.path.getmtime(self.cmd_path)
                if mt > self._cmd_seen:
                    with open(self.cmd_path, "r", encoding="utf-8") as f:
                        raw = f.read()
                    if not raw.strip():
                        return
                    cmd = json.loads(raw)
                    self._cmd_seen = mt
                    self._exec_cmd(cmd)
        except Exception:
            if mt != getattr(self, "_cmd_err_mt", None):
                self._cmd_err_mt = mt
                import traceback
                traceback.print_exc()

    def _tick_body(self):
        now = time.time()
        self.thinking_now = self.ai_thinking or now < self._think_demo_until
        t = now - self.t0
        dt = min(0.05, now - self.last)      # 积分用:必须夹紧,防止卡顿后穿地
        # 平滑用。approach 对任意 dt 都稳定(残差因子恒在 0..1),所以这里
        # 可以放宽 —— 夹在 0.05 上的话,睡眠时 10fps 的帧(真实 0.1s)仍然
        # 只按半步算,睡醒那一下照样会顿。
        dts = min(0.25, now - self.last)
        self.last = now
        # 秋千只属于 "swing" 状态:被拖拽/别的动作顶掉时,统一在这里收绳椅
        if getattr(self, "_swing", None) and (
                self.state != "swing" or self.state == "swing" and self.drag):
            self._swing_stop(restore=False)   # 从弧线位置自然落下,不瞬移
        # 下秋千后待补做的动作只在这一段自然落地里有效:半空被抓住、抛飞、
        # 转去别的状态就作废,免得很久以后某次落地突然补做
        if self._land_then and self.state != "fall":
            self._land_then = None
        self._advance_drag_pose(now, dts)
        # spin/bend 是动画专用的变形维度,每帧先复位,只有真的在做
        # 转身/弓身的动作才覆写 —— 动画中途被打断也不会残留变形
        self._spin_rot = 0.0    # 整只的平面旋转角(度,陀螺式转圈)
        self._spin_lift = 0.0   # 旋转时的腾空抬升(px)
        self._bend = 0.0        # 上半身侧向弓弯量
        self._afterimage_on = False   # 残影开关(转圈/空翻/打滚时开)

        mx, my = cursor_pos()
        wcx = self.x + self.W / 2
        wcy = self.fy - self.H * 0.18
        near = math.hypot(mx - wcx, my - (self.fy - self.H * .35)) < 150 * self.scale
        just_approached = near and not self._cursor_near
        # 法阵感应光标:按距离平滑升温/降温。只在她醒着、站着不演出时算,
        # 其余时候归零 —— 演出有自己的法阵能量
        if self.state in ("idle", "sticker") and not self.drag:
            target = self._prox_target(
                math.hypot(mx - wcx, my - (self.fy - self.H * .35)) / self.scale)
        else:
            target = 0.0
        self._prox = approach(getattr(self, "_prox", 0.0), target, 0.12, dts)
        if just_approached and self.state == "idle":
            self._ripple_kick = now
        # 帽檐星轨的时钟:按"速度"积分而不是直接乘墙钟,变速时不会跳位置。
        # 睡着慢慢停下(停住后不占睡眠 10fps 档的动画);施法加速;时停时
        # 星星也跟着停;时间回溯时倒着转
        spin = self._orbit_spin_target(self.state)
        self._orbit_speed = approach(getattr(self, "_orbit_speed", 1.0), spin, 0.06, dts)
        self._orbit_t = getattr(self, "_orbit_t", 0.0) + dts * self._orbit_speed
        self._cursor_near = near
        if now > getattr(self, "_sac_next", 0.0):
            # micro-saccade:真人眼球的小幅跳动,10% 概率连跳两下
            self._sac_dx = random.uniform(-0.28, 0.28)
            self._sac_dy = random.uniform(-0.14, 0.14)
            self._sac_until = now + random.uniform(0.10, 0.26)
            self._sac_next = now + (random.uniform(0.35, 0.7)
                                    if random.random() < 0.10
                                    else random.uniform(2.0, 4.5))
        sac_on = now < getattr(self, "_sac_until", 0.0)
        if getattr(self, "_worry_gaze", 0.0) > now:
            tx = math.sin(t * 1.8) * 0.55 - 0.2
            ty = math.cos(t * 2.1) * 0.2 + 0.3
        elif getattr(self, "_look_away_cd", 0) > now:
            tx = math.sin(t * 1.8) * 0.9
            ty = math.cos(t * 2.1) * 0.25
        else:
            tx = max(-1.0, min(1.0, (mx - wcx) / (520 * self.scale)))
            # 这行原来少缩进一级,跑在 if/else 外面,把上面"害羞移开视线"
            # 的 ty 又覆盖回追光标 —— 她移开视线时只有左右在躲,上下还盯着你
            ty = max(-1.0, min(1.0, (my - wcy) / (420 * self.scale)))
        if sac_on:
            tx = max(-1.0, min(1.0, tx + self._sac_dx * 0.4))
            ty = max(-1.0, min(1.0, ty + self._sac_dy * 0.4))
        k = 0.08 if self.drag else 0.06
        self.look_x = approach(self.look_x, tx, k, dts)
        self.look_y = approach(self.look_y, ty, k, dts)
        self.lean = approach(
            self.lean, self.look_x * 0.09 + math.sin(t * 0.9) * 0.012, 0.06, dts)
        if self.drag:
            self._lid = max(self._lid, 0.24)   # 被拎着:眯眼(不安)
        if getattr(self, "lean_kick", 0) > 0:
            self.lean_kick = max(0.0, self.lean_kick - 2.2 * dt)
            self.lean += math.sin(t * 22) * 0.05 * self.lean_kick
        if self.thinking_now and self.state != "sleep":
            self.lean = approach(self.lean, -0.06 + math.sin(t * 1.4) * 0.03,
                                 0.10, dts)
        self.squash = approach(self.squash, 1.0, 7 / 30.0, dts)

        prev_star = self.star
        self.star = max(0.0, self.star - dt * 100.0 / 7200.0)
        # 饥饿主动提醒:星光跌破 25% 时说一次,充回 50% 以上复位,
        # 不然玩家根本不会知道要去右键喂糖
        if self.star < 25 and prev_star >= 25 and not self._star_warned:
            self._star_warned = True
            if self.state != "sleep":
                self.say(random.choice(HUNGRY_SAY), 3.0)
                self.play_emotion("tired", 2.6)
        if self.star >= 50:
            self._star_warned = False
        # 星光满格:达到 100 时小庆祝一次(吃糖/接星的奖励反馈)。
        # 边沿由 _star_full_cele 标志检测——糖果/接星是在帧间直接改值,
        # prev 对比永远看不到"穿越",只能靠标志位。
        if self.star >= 99.5 and not self._star_full_cele:
            self._star_full_cele = True
            if self.state != "sleep":
                self.say(random.choice(
                    ["星光满满!状态绝佳~", "满格!今天也是闪闪发光的一天!",
                     "哇,星光全满了,感觉自己能发光✨"]), 3.0)
                self.play_emotion("excited", 2.8)
                self.star_burst(0, -0.05 * self.H, 14, sp=(70, 150), grav=90)
        if self.star < 90:
            self._star_full_cele = False

        self._pump()   # 跨线程回调 + 外部指令轮询

        # 思考动效
        if self.thinking_now and now > self.next_thinkfx:
            self.next_thinkfx = now + 0.35
            self.add_part("sparkle", random.uniform(-0.09, 0.09) * self.W,
                          -0.37 * self.H, vy=-30, life=0.7,
                          size=random.uniform(3, 6), color=GOLD_L,
                          phase=random.uniform(0, 6.28))

        # 唱歌摆动+音符+收尾
        if self.singing:
            beat = abs(math.sin(t * 4.2))
            self.lean = approach(self.lean, math.sin(t * 4.5) * 0.06 * beat,
                                 0.20, dts)
            if now > self.next_note:
                self.next_note = now + random.uniform(0.35, 0.6)
                self.add_part("note", random.uniform(-0.14, 0.14) * self.W,
                              -0.36 * self.H, vy=-random.uniform(26, 44),
                              life=2.0, phase=random.uniform(0, 6.28),
                              txt=random.choice(("♪", "♫", "♪")))
            # R109 唱到兴头偷偷看主人一眼(唱歌 5s 后每 4~7s 30% 概率)
            sing_t = now - self._sing_started
            if (sing_t > 5 and now > getattr(self, "_sing_peek_cd", 0)):
                self._sing_peek_cd = now + random.uniform(4, 7)
                if random.random() < 0.3:
                    self._look_away_cd = now + 0.4
            if now > self._sing_poll and now - self._sing_started > 1.2:
                self._sing_poll = now + 0.5
                # 放完没有:标志由音频线程维护(UI 线程不再自己调 MCI)。
                # 静音唱(声音开关关着)时没有播放状态可查,按固定时长收尾
                done = (not self.sfx.song_playing if getattr(self, "_sing_audio", False)
                        else now - self._sing_started > 32)
                if done:
                    self.stop_sing()
                    self.hearts(0, -0.18 * self.H, 4)
                    self.say('唱完啦~掌声在哪里!', 2.6)

        if not self.core_profile():
            # AI 主动搭话
            if self.focus_mode():
                # 专注期间不主动搭话;把下次时间推到这段结束之后,免得一收工
                # 就立刻蹦一句出来(那比中途说话更突兀)
                self.next_greet = max(self.next_greet, self.pomo["due"] + 60)
            elif (self._ai_ready()
                    and self.state in ("idle", "sticker", "swing")   # 秋千 = 默认待机
                    and now > self.next_greet):
                g = self.brain.cfg.get("greet_interval_min", 0)
                if g > 0:
                    self.next_greet = now + max(15, g) * 60
                    self._ai_quick()

            # 到点的一次性提醒 & 周期性喝水提醒
            if self.reminders:
                due = [r for r in self.reminders if now >= r.get("due", 0)]
                if due:
                    self.reminders = [r for r in self.reminders if now < r.get("due", 0)]
                    self._save_reminders()
                    for r in due:
                        self._fire_reminder(r.get("text", "时间到啦~"))
            if self.water_min > 0 and now >= self.water_next:
                self.water_next = now + self.water_min * 60
                self._fire_reminder("该喝水啦!顺便起来动一动~")

            # 专注陪伴:安静地冒几点星光,不说话
            self._focus_tick(now)

            # 番茄钟:专注到点 -> 提示休息并自动排 5 分钟休息;休息到点 -> 收工
            if self.pomo and now >= self.pomo["due"]:
                p = self.pomo
                self.pomo = None
                if p["phase"] == "focus":
                    self.pomo = {"phase": "break", "due": now + 5 * 60, "mins": 5}
                    self._focus_next = 0.0
                    self._focus_half = False
                    self.hearts(0, -0.2 * self.H, 5)
                    self.confetti_burst(0, -0.15 * self.H, 20)
                    self.add_affection(2)   # 陪你完成一段专注,感情自然升温
                    self.pomo_done += 1
                    self._count_today("focus_min", int(round(p["mins"])))
                    milestone = {1: "初次专注", 5: "专注学徒", 10: "专注达人",
                                 25: "专注大师"}.get(self.pomo_done)
                    extra = (f"获得称号【{milestone}】!" if milestone
                             else f"(累计专注 {self.pomo_done} 次)")
                    self._fire_reminder(
                        f"陪你专注了 {p['mins']:g} 分钟!{extra}一起伸个懒腰,"
                        f"休息 5 分钟~")
                    # 休息的开场就是一起伸懒腰:专注期间她一直安静待着,这一下
                    # 同时是"结束了"和"你也该起来动动"。已经在别的状态或被
                    # 拖着就算了,不抢演出。坐在秋千上算待机:先跳下来再伸。
                    self.root.after(1600, lambda: (
                        self.start_stretch()
                        if self.state in ("idle", "swing") and not self.drag else None))
                else:
                    self._fire_reminder("休息结束,回来继续加油!")

            # 偷看窗口:同一类应用用太久就念叨一次
            self._fg_watch_tick(now)
            self._battery_tick(now)
        self._stats_tick(now)

        if now >= self.next_blink and self.state not in ("sleep", "yawn"):
            self.blink_until = now + 0.12
            if random.random() < 0.15:
                self.next_blink = now + 0.32      # 双眨眼:偶尔很快再眨一次
            else:
                self.next_blink = now + random.uniform(2.2, 6.0)

        # ---- 状态机 ----
        # 长按戳脸:按住不放 0.9 秒(没拖动),她会有反应。低频彩蛋。
        if (self.drag and not self.drag[4] and self.state == "idle"
                and now - self.drag[5] > 0.9 and now > self._poke_cd):
            self._poke_cd = now + 30
            self.squash = 0.88
            self.hearts(0, -0.2 * self.H, 2)
            # 戳中的位置弹开两粒小星,像按下了一个隐形按钮
            for _ in range(2):
                self.add_part("sparkle",
                              random.uniform(0.14, 0.24) * self.W,
                              random.uniform(-0.26, -0.18) * self.H,
                              vx=random.uniform(-55, -25),
                              vy=random.uniform(-45, -15),
                              life=0.6, size=random.uniform(3, 4.5),
                              color=GOLD_L, phase=random.uniform(0, 6.28))
            self.play_emotion(random.choice(("shy", "surprised")), 2.0)
            self.say(random.choice(
                ["唔嗯?要捏扁我了吗~", "呜哇,被抓住了!", "捏…捏脸吗?"]), 2.0)

        st = 'drag' if self.drag and self.drag[4] else self.state
        # 闲置彩蛋:空闲 8 秒后,5% 看别处,30% 主动跟眼,65% 默认
        if (self.state == "idle" and not self.singing
                and now - self.last_interact > 8
                and now > getattr(self, "_idle_eye_cd", 0)):
            self._idle_eye_cd = now + random.uniform(2.5, 5.0)
            r = random.random()
            if r < 0.05:
                self._look_away_cd = now + 0.7   # 偷看别处
        # R108 闲置自语:30 秒后每 1~2 分钟 3% 概率冒一句随机小气泡
        # (秋千是她的家,坐在上面静静荡着也算空闲)
        if (self.state in ("idle", "swing") and not self.singing
                and now - self.last_interact > 30
                and not self.bubble
                and now > getattr(self, "_idle_mumble_cd", 0)):
            self._idle_mumble_cd = now + random.uniform(60, 120)
            if random.random() < 0.03:
                self.say(random.choice([
                    "嗯?", "咦~", "发呆中…", "今天要做点什么呢",
                    "不知道主人在忙什么", "有点想吃东西了",
                    "窗外的云好慢呀~", "嗯嗯,继续加油!"]), 2.0)

        # 重力兜底:任何常规状态只要离地(比如吃糖/施法/发呆时被抛到半空),
        # 就转入 fall,杜绝"卡在空中"——飞行/下落/被举着不在此列
        if (self.fy < self.ground_feet - 6
                and st in ("idle", "walk", "sticker", "dance", "stretch",
                           "peek", "chase", "dizzy", "eat", "magic", "sneeze",
                           "yawn", "fall_stand")):
            self.state = "fall"
            st = "fall"

        # 魔女秋千 v2:前后荡(纵深)。可积钟摆的 θ 表示"朝屏幕里/外"的
        # 摆角:座椅沿垂线上下、随透视缩放(靠近变大/远离变小);人物渲染
        # 帧整体按同一透视系数缩放,臀点锚在座椅上 —— 三层永不脱节。
        # 20fps 档由状态保证;swing 不在重力兜底名单里,不会被拽进 fall。
        if st == "swing" and self._swing and not self.drag:
            sw = self._swing
            theta, omega = self._seat_swing_step(sw, dt, now)
            sw["theta"], sw["omega"] = theta, omega
            persp = 1.0 + SWING_PERSP * math.sin(theta)
            sw["persp"] = persp
            # 摆到最近点(θ≈0 且速度最快):轻微压缩一下(克制)
            if (abs(theta) < 0.06 and abs(omega) > 0.55
                    and getattr(self, "_swing_bottom_armed", True)):
                self.squash = min(self.squash, 0.958)
                self._swing_bottom_armed = False
            elif abs(theta) > 0.30:
                self._swing_bottom_armed = True
            # 帽/发/腿吃到前后荡的惯性(深度变化的"甩")
            d_S = life.clamp((persp - sw.get("prev_persp", 1.0)) * 40.0,
                             -0.10, 0.10)
            self.life.hat_rot.impulse(d_S * 0.30)
            self.life.impulse_hair(d_S * 0.55)
            self.life.leg_l.impulse(d_S * 0.20)
            self.life.leg_r.impulse(d_S * 0.16)
            self.life.knee_l.impulse(d_S * 0.9)
            self.life.knee_r.impulse(d_S * 0.8)
            self.life.hem.impulse(d_S * 0.9)     # 裙摆下缘的荡动拖尾
            sw["prev_persp"] = persp
            S0 = sw.get("scene_scale", 1.0) * persp   # 臀点锚定的缩放(=S)
            # 外部状态同步:灯板/粒子/点击分区用的窗口坐标
            if sw.get("art"):
                # 原画场景:渲染帧整块映射进画布,x/fy = 那一帧的窗口左缘/脚线,
                # 下秋千时她从这里接着落(不跳位)
                aox, aoy, ass = self._art_small_map(sw)
                self.x = int(sw["scene_l"] + aox + self.W / 2 * ass - self.W / 2)
                self.fy = sw["scene_t"] + aoy + self.FOOT_Y * ass
            else:
                self.x = sw["scene_l"] + (sw["scene_cx"] - sw["scene_l"]) - self.W // 2
                self.fy = (sw["scene_t"] + sw.get("bar_y", 8) - 2 + sw["R"] * math.cos(theta)
                           - 18 * S0) + int(SEAT_LIFT_ART * (self.spr2.height if hasattr(self, "spr2") else 650)
                          / 750.0 * sw.get("persp", 1.0) * sw.get("scene_scale", 1.0))
            # 长时间没人理:自己轻轻荡大一点(悠闲感)
            if (now - self.last_interact > 30 and now > self._swing_kick_cd
                    and random.random() < 0.006):
                sw["pend"].impulse(random.choice((-0.28, 0.28)))
                kick = random.choice((-0.06, 0.06))
                self.life.leg_l.impulse(kick)
                self.life.leg_r.impulse(-kick * 0.8)
                self.life.knee_l.impulse(-kick * 30)
                self.life.knee_r.impulse(kick * 26)
                # 防连发用独立冷却。原来把 last_interact 改成 now-20,等于每次
                # 自己荡都伪造一次"刚有人互动",入睡永远等不到、钟摆一直被泵
                self._swing_kick_cd = now + 10.0
            # ---- 魔法书 v2 的 UI 状态(设计基准:小乔AI界面设计方案.md)----
            # 水晶/书/面板固定在场景坐标不随摆动;面板矩形做屏幕级钳制
            scene_w, scene_h = sw["scene_w"], sw["scene_h"]
            demo = now < getattr(self, "_demo_until", 0.0)
            sessions_d = (self._demo_sessions if demo else
                          getattr(self, "_ai_work_sessions", self._ai_sessions))
            quota_d = (getattr(self, "_demo_quota", None) if demo else self._quota)
            # Simulation must not leak an actual account sample into a demo.
            codex_quota_d = None if demo else getattr(self, "_codex_quota", None)
            sources = book_sources(sessions_d, quota_d)
            sel = self._book_sel
            if sel and sel[0] == "agent" and sel[1] not in [k for k, _, _ in sources]:
                sel = None                     # 固定的来源消失了 → 回自动
            if sel and sel[0] == "agent":
                sel_key = sel[1]
            elif sel and sel[0] == "sid":
                srow = next((x for x in sessions_d if x["id"] == sel[1]), None)
                sel_key = srow["agent"] if srow else pick_auto_source(sessions_d, sources, now)
            else:
                sel_key = pick_auto_source(sessions_d, sources, now)
            sel_session = None
            if sel and sel[0] == "sid":
                sel_session = next((x for x in sessions_d if x["id"] == sel[1]), None)
            if sel_session is None and sel_key:
                sel_session = select_work_session(sessions_d, sel_key, now)
            # 其他来源的待处理事件(查看时,水晶右上亮角标)
            badge = {}
            for s in sessions_d:
                if (s.get("state") in ("waiting", "error") and not s.get("stale")
                        and not ai_session_stale(s, now) and s.get("agent") != sel_key):
                    badge[s.get("agent")] = s.get("state")
            # 书没开时持续记录基线:打开后新增的动作才算「有新记录」
            if not self._book_open:
                self._book_new_seen = {s["id"]: len(s.get("actions") or [])
                                       for s in sessions_d}
                self._trace_snap = None
            elif sel_session is not None:
                # 打开/切换会话时冻结动作快照:阅读期间新动作只进「有新记录」
                # 提示,不把正在看的行顶走(阅读历史不自动跳走)
                if self._trace_snap is None or self._trace_sid != sel_session["id"]:
                    self._trace_snap = list(sel_session.get("actions") or [])
                    self._trace_sid = sel_session["id"]
                    self._trace_expand = set()
                    self._trace_page = 0
            new_n = 0
            if self._book_open and sel_session:
                seen = self._book_new_seen.get(sel_session["id"])
                if seen is not None:
                    new_n = max(0, len(sel_session.get("actions") or []) - seen)
            # 展开缓动 150-220ms(减少动画选项直接到位)
            if self.ui_reduced_anim:
                self._book_anim = 1.0 if self._book_open else 0.0
            else:
                step = dt / 0.18
                self._book_anim = (min(1.0, self._book_anim + step)
                                   if self._book_open
                                   else max(0.0, self._book_anim - step))
            # 道具组(收起态)在场景右下、人物摆动包围盒之外
            gx, gy = scene_w - 128, scene_h - 132   # 右下角:躲开她身上的 AI 灯板
            book_rect = None
            if self._book_open:
                bx1, by0 = gx - 14, gy + 46
                if sw.get("art"):
                    # 原画场景:面板贴场景左下(书在左边),压住坐垫和腿,不盖脸
                    bx1, by0 = 8 + BOOK_W, scene_h - 8 - BOOK_H
                bx0, by1 = bx1 - BOOK_W, by0 + BOOK_H
                if by1 > scene_h - 14:         # 贴近场景底边 → 上移
                    by1, by0 = scene_h - 14, scene_h - 14 - BOOK_H
                if by0 < 14:
                    by0, by1 = 14, 14 + BOOK_H
                mon = monitor_rect_at(sw["scene_l"], sw["scene_t"]) or (0, 0, 2880, 1800)
                dx = dy = 0
                if sw["scene_l"] + bx0 < mon[0] + 8:
                    dx = (mon[0] + 8) - (sw["scene_l"] + bx0)
                elif sw["scene_l"] + bx1 > mon[2] - 8:
                    dx = (mon[2] - 8) - (sw["scene_l"] + bx1)
                if sw["scene_t"] + by0 < mon[1] + 8:
                    dy = (mon[1] + 8) - (sw["scene_t"] + by0)
                elif sw["scene_t"] + by1 > mon[3] - 8:
                    dy = (mon[3] - 8) - (sw["scene_t"] + by1)
                book_rect = (bx0 + dx, by0 + dy, BOOK_W, BOOK_H)
            cs = crystal_state(sessions_d, now)
            # 悬停水晶 350ms 后的小提示:来源 / 任务 / 状态 / 主要额度
            tip = None
            if (self._crystal_hover and not self._book_open
                    and now - self._crystal_hover_since >= TOOLTIP_DELAY
                    and cs != "unknown"):
                src_lab = next((lab for k, lab, _ in sources if k == sel_key), "AI")
                task = ((sel_session or {}).get("title") or "—")[:20]
                tip_lines = [f"{src_lab} · {CRYSTAL_LABEL.get(cs, cs)}",
                             f"任务 {task}"]
                # 额度速览 = Claude 账户口径(不随选中来源隐藏;
                # 选中来源自身的额度仍在书面板/弧中按来源表达)
                if quota_d and isinstance(quota_d.get("fh"), (int, float)):
                    tip_lines.append(
                        f"Claude 5h 已用 {quota_d['fh']:.0f}%"
                        f" · 剩余 {max(0, 100 - quota_d['fh']):.0f}%")
                    if isinstance(quota_d.get("sd"), (int, float)):
                        tip_lines.append(
                            f"7d 已用 {quota_d['sd']:.0f}%"
                            f" · 剩余 {max(0, 100 - quota_d['sd']):.0f}%")
                    rest = quota_d.get("reset_est")
                    stale = quota_age(quota_d, now)
                    if rest and rest > now:
                        tip_lines.append("恢复 预计 "
                            + time.strftime("%H:%M", time.localtime(rest))
                            + "(估算)")
                    elif stale is not None and stale > QUOTA_STALE_AFTER:
                        tip_lines.append("额度样本已过期(显示最后已知值)")
                else:
                    tip_lines.append("额度数据 未接入")
                tip = {"lines": tip_lines}
            ui = {"crystal_state": cs,
                  "crystal_hover": self._crystal_hover,
                  "tooltip": tip,
                  "badge": badge,
                  "book_panel": self._book_open,
                  "book_anim": self._book_anim,
                  "book_tab": self._book_tab,
                  "book_rect": book_rect,
                  "sel_key": sel_key,
                  "sel_session": sel_session,
                  "sources": sources,
                  "sessions": sessions_d,
                  "quota": quota_d,
                  "quota_age": quota_age(quota_d, now),
                  "codex_quota": codex_quota_d,
                  "codex_quota_error": False if demo else getattr(self, "_codex_quota_error", False),
                  "quota_provider": getattr(self, "_quota_provider", None),
                  "now": now,
                  "new_n": new_n,
                  "prop_rect": None if sw.get("art") else (gx, gy),
                  "muted": sorted(getattr(self, "ai_mute_sources", set())
                                  or set()),
                  "mock": demo}
            sw["ui"] = ui
            if sw.get("geo", {}).get("moon_house") and not sw.get("geo", {}).get("flat"):
                from moon_house import react
                react(self, ui)
            self._sync_ai_panel(sw, ui)
            if not sw.get("art"):
                self.swing_layer.frame(sw["rect"], sw,
                                       below_hwnd=getattr(self, "hwnd", 0), now=now,
                                       topmost=self.topmost)
            # 秋千上也会犯困,和地面同一口径(75 秒没人理、没在聊天、不在专注)。
            # 原来入睡判定只写在 idle 分支,默认住秋千就永远不睡,一直 20fps
            # 推两层窗口。现行设计(I-5):犯困直接睡在秋千上(go_sleep 秋千
            # 分支,state 保持 swing 不落地),_frame_delay 的秋千打盹分支给
            # 10fps 安静档;唤醒走 _wake_from_nap,场景/绳手/接触全程不动
            if (now - self.last_interact > 75 and not self._chat_open()
                    and not self.focus_mode()):
                self.go_sleep()      # 新坐姿:犯困就睡在秋千上,不再落地
        # 秋千打盹:偶发 zzz(睡眠氛围)
        if getattr(self, "_nap_on_swing", False) and random.random() < 0.006:
            self.add_part("zzz", (0.18 + random.random() * 0.1) * self.W,
                          -0.38 * self.H, vy=-9, life=1.8, size=9,
                          phase=random.uniform(0, 6.28))
        # 场景是她的家:落地空闲一阵后自己回到场景入座(swing_home 可关)
        if self.swing_home and st in ("sleep", "yawn"):
            # 睡着不算"空闲一阵":醒了再等一会儿才回座。不然自己醒一下就
            # 回秋千、没人理又马上下来睡,来回折腾
            self._swing_remount = max(self._swing_remount, now + 45.0)
        if (self.swing_home and self._swing is None and st == "idle"
                and not self.drag and now > getattr(self, "_swing_remount", 0.0)):
            self._swing_remount = now + 3600.0   # 先占位防同帧连发;下来时 _swing_stop 改回 40~70 秒
            self.start_swing(quiet=True)
        if st == "idle":
            # 专注陪伴:她安静待着。这一条同时关掉了时段问候、追光标、
            # 跳舞、探头和整个 _idle_event(走动/贴纸/闲聊/哼歌/吹泡泡/
            # 打喷嚏/脚滑),是抑制面最大的一处。
            if (not self.core_profile() and now > self.next_event and not self.singing
                    and not self.focus_mode()):
                self.next_event = now + random.uniform(7, 16)
                # 整点前后先做时段问候(每个时段仅一次)
                if self.greet_period():
                    pass
                elif (now > self.chase_cd and random.random() < 0.10):
                    self.start_chase()
                elif random.random() < 0.14:
                    self.start_dance()
                elif random.random() < 0.16:
                    self.start_peek()
                else:
                    self._idle_event(now)
            if just_approached and now > self._curious_cd and not self.bubble:
                self._curious_cd = now + 14
                self._start_micro_motion("notice")
                self.play_emotion("curious", 2.0)
                self.say(random.choice(["在叫我吗?", "唔?", "要摸摸我吗?"]), 2.0)
            # 聊天窗开着时不睡死:对话还在进行,中途睡着很出戏
            # 专注期间不自动入睡:用户在敲键盘、75 秒不碰她是常态,
            # 睡过去等于这个功能不存在。代价是这 25 分钟走 20fps 安静档
            # 而不是 10fps 睡眠档,有意为之。
            if (now - self.last_interact > 75 and not self._chat_open()
                    and not self.focus_mode()):
                self.go_sleep()
            # R101 主动迎回:离开 30s~3min 后主动说句欢迎
            elif (just_approached and 30 < now - self.last_interact < 180
                    and not getattr(self, "_return_greeted", False)
                    and self.state == "idle" and not self.bubble):
                self._return_greeted = True
                self.say(random.choice([
                    "主人回来啦~", "终于回来了!好想你~", "欢迎回来~",
                    "呀,主人!刚才在干嘛呀?"]), 2.6)
                self.play_emotion("happy", 2.2)
            if now - self.last_interact < 5:
                self._return_greeted = False
        elif st == "dance":
            self._advance_dance(now)
        elif st == "stretch":
            # 时间轴管四段主曲线;顶点微颤和上浮星尘是程序性叠加
            t = now - self.stretch_start
            sd = getattr(self, "stretch_side", 1)
            self._play_timeline(t, self._tl_tracks, self._tl_events, self._tl_done)
            if 2.0 < t < 2.7:
                # 舒展停留时只保留缓慢呼吸,两端归零,不再高频抖动。
                breath = math.sin((t - 2.0) / .7 * math.pi) ** 2
                self.squash += .008 * breath
                self._bend += .015 * sd * breath
            if 0.7 < t < 2.0 and now > self.next_trail:
                # ② 拉展时星尘缓缓上浮
                self.next_trail = now + 0.12
                self.add_part("sparkle", random.uniform(-0.14, 0.14) * self.W,
                              -0.38 * self.H, vy=-random.uniform(16, 30),
                              life=1.1, size=random.uniform(3, 6.5),
                              color=random.choice(STAR_COLORS),
                              phase=random.uniform(0, 6.28))
            if now > self.state_until:
                self.state = "idle"
                self.next_event = now + random.uniform(5, 10)
        elif st == "peek":
            # 走神四幕走时间轴;这里只管萤火虫、点头和 zzz
            t = now - self.peek_start
            d = self.peek_dir
            self._play_timeline(t, self._tl_tracks, self._tl_events, self._tl_done)
            if 1.4 < t < 4.6:
                # ② 思绪飘飘:视线放空 + 萤火虫缓缓上浮
                if now > self.next_trail:
                    self.next_trail = now + 0.4
                    self.add_part("firefly",
                                  random.uniform(0.02, 0.34) * self.W * d,
                                  random.uniform(-0.44, -0.2) * self.H,
                                  vx=random.uniform(-8, 8),
                                  vy=random.uniform(-14, -6),
                                  life=2.6, size=random.uniform(3.5, 6),
                                  color=(210, 235, 130),
                                  phase=random.uniform(0, 6.28))
            elif 4.6 < t < 6.2:
                # ③ 打瞌睡:头一点一点(压扁跟点头),冒 zzz
                ph = (t - 4.6) / 1.6
                nod = math.sin(ph * math.pi)**2 * math.sin(ph * 3 * math.pi)**2
                self.squash = 1.0 - 0.045 * nod
                self._bend = .075 * d * nod
                if nod > 0.9 and now > self.next_trail:
                    self.next_trail = now + 0.35
                    self.add_part("zzz", 0.16 * self.W * d, -0.42 * self.H,
                                  life=1.8, size=random.uniform(5, 8))
            if now > self.state_until:
                self.state = "idle"
                self.next_event = now + random.uniform(6, 12)
        elif st == "flip":
            self._advance_flip(now)
        elif st == "meditate":
            t2 = now - self.meditate_start
            self._play_timeline(t2, self._tl_tracks, self._tl_events, self._tl_done)
            if 1.2 < t2 < 4.3:
                # 悬停时的呼吸起伏叠加在升空高度上
                self._spin_lift += math.sin((t2 - 1.2) * 2.4) * 3.0 * self.scale
            if 0.8 < t2 < 4.9 and now > self.next_trail:
                # 腰间三股星尘绕行,跟着升空高度走
                self.next_trail = now + 0.05
                for x, y, side, a in self._meditate_arms(t2, self.W, self.H,
                                                         self._spin_lift):
                    # 尾迹在远侧缩小一圈:粒子没法画到她身后,只能靠近大远小
                    near = side == "near"
                    self.add_part("sparkle", x, y, life=0.7,
                                  size=random.uniform(5.5, 9) * (1.0 if near else 0.6),
                                  color=random.choice(STAR_COLORS), phase=a)
            if now > self.state_until:
                self._spin_lift = 0.0
                self.state = "idle"
                self.next_event = now + random.uniform(6, 12)
        elif st == "wave":
            t = now - self.wave_start
            self._play_timeline(t, self._tl_tracks, self._tl_events, self._tl_done)
            if now > self.state_until:
                self.state = "idle"
                self.next_event = now + random.uniform(6, 12)
        elif st == "roll":
            # 打滚:时间轴管转体和压扁;横向位移在这里(滚真的会滚出去)
            t = now - self.roll_start
            d = self.roll_dir
            self._play_timeline(t, self._tl_tracks, self._tl_events, self._tl_done)
            self._afterimage_on = 0.3 < t < 2.2
            self.x = max(self.x_min, min(self.x_max,
                         self.roll_home + self._roll_offset(t, d, self.scale)))
            if 0.3 < t < 2.2:
                # 滚动拖出时之沙尾迹:贴地、节流到 ~7 粒/秒
                if now > self.next_trail:
                    self.next_trail = now + 0.14
                    self.add_part("sparkle",
                                  random.uniform(-0.28, 0.28) * self.W,
                                  self.FOOT_Y - self.H / 2 - random.uniform(0, 10),
                                  vx=random.uniform(-25, 25),
                                  vy=random.uniform(-70, -25),
                                  life=random.uniform(0.4, 0.7),
                                  size=random.uniform(2.5, 5),
                                  color=random.choice([GOLD_L, GOLD, MAGIC_B]),
                                  phase=random.uniform(0, 6.28))
            if now > self.state_until:
                self.state = "idle"
                self.next_event = now + random.uniform(6, 12)
        elif st == "transform":
            t = now - self.transform_start
            self._play_timeline(t, self._tl_tracks, self._tl_events, self._tl_done)
            self._afterimage_on = 0.35 < t < 1.5
            if now > self.state_until:
                self.state = "idle"
                self.next_event = now + random.uniform(6, 12)
        elif st == "chase":
            self._advance_chase(now)
        elif st == "fly":
            # 抛物线 + 撞边反弹,每次反弹损耗能量,慢下来就落地
            # 空气阻力:水平速度每帧衰减 1.5%(0.03/秒),飞得更自然
            self.vx *= max(0.0, 1.0 - 1.5 * dt)
            self.vy += 1500 * dt
            self.x += self.vx * dt
            self.fy += self.vy * dt
            self.lean = approach(self.lean, math.sin(t * 18) * 0.20, 0.4, dts)
            left, right = self.x_min, self.x_max
            if self.x <= left or self.x >= right:
                wall = -1 if self.x <= left else 1
                self.x = max(left, min(self.x, right))
                self.vx *= -0.62
                self.bounces += 1
                self.hit_wall((wall, 0))
            top = self.H * 0.55
            if self.fy <= top:
                self.fy = top
                self.vy = abs(self.vy) * 0.5
                self.bounces += 1
                self.hit_wall((0, -1))
            if now > self.next_trail:
                # 窗口本身在跟着她飞,而粒子坐标是相对窗口的:原来的星星一直
                # 挂在她头顶跟着走,根本不是"拖尾"。给星星和窗口相反的速度、
                # 相反的重力,它们在屏幕上就停在原地,被真正甩在身后。
                # 飞得快时一颗星 0.2 秒就出了窗口,所以发得更密、从身体发出
                # (同屏粒子数反而比原来少:寿命 0.7 -> 0.45)。
                self.next_trail = now + 0.015
                # 一帧里窗口可能走了几十像素(30fps、1300px/s 时约 43px),只在
                # 当前位置撒一颗,拖尾就成了稀疏的点线。按这一帧走过的路程
                # 沿路补几颗:u 越大越靠后(窗口坐标里往反方向挪)。
                n = max(1, min(4, int(math.hypot(self.vx, self.vy) * dt
                                      / (18 * self.scale))))
                for j in range(n):
                    u = j / n
                    self.add_part("star",
                                  random.uniform(-0.08, 0.08) * self.W - self.vx * dt * u,
                                  random.uniform(-0.22, 0.02) * self.H - self.vy * dt * u,
                                  life=0.45,
                                  vx=-self.vx + random.uniform(-25, 25),
                                  vy=-self.vy + random.uniform(-25, 25), grav=-1500,
                                  size=random.uniform(4, 8),
                                  color=random.choice(STAR_COLORS),
                                  phase=random.uniform(0, 6.28), spin=6.0)
            if self.fy >= self.ground_feet:
                self.fy = float(self.ground_feet)
                # 触地冲击按竖直速度给强度:原来抛飞/下落的落地不走 land_fx,
                # 只闪一圈法阵,而翻跟头、转圈这些小落地反倒都有冲击波
                impact = self._landing_strength(abs(self.vy))
                if abs(self.vy) > 260 and self.bounces < 4:
                    self.vy = -abs(self.vy) * 0.5   # 地面也弹一下
                    self.vx *= 0.7
                    self.bounces += 1
                    self.hit_wall((0, 1))
                    self.land_fx(impact)
                else:
                    self.state = "idle"
                    self.vx = self.vy = 0.0
                    self.squash = 0.82
                    self.land_fx(impact)
                    self.circles.append(dict(born=now, life=0.7, rx=0.9, kind="cast"))
                    self.star_burst(0, 0.1 * self.H, 8, sp=(80, 150), grav=200)
                    self.next_event = now + random.uniform(3, 7)
                    self.say(random.choice(["落地成功!", "呼…头晕", "再来一次?"]), 2.2)
                    if self.bounces >= 3:
                        self.go_dizzy()
        elif st == "dizzy":
            self._advance_dizzy(now)
            # 头顶转圈的小星星:开场那 6 颗是向外飞散的,1 秒后就没了,后半段
            # 她只是站着晃。这里补一圈绕着头转的,跟着晕眩程度一起淡出。
            if self.dizzy_amp > 0.18 and now > self.next_trail:
                self.next_trail = now + 0.07
                a = t * 4.2
                # 绕的是头顶,所以锚点跟开场那 6 颗星一个高度(-0.25H);挂在
                # -0.42H 会飘到气泡那儿去,看着不像绕着她转。x 再跟一点她的
                # 倾斜,头歪过去这圈星星也跟着歪。
                self.add_part("star",
                              math.cos(a) * 0.24 * self.W + self.lean * self.H * 0.35,
                              -0.28 * self.H + math.sin(a) * 0.055 * self.H,
                              life=0.5, size=(7.0 + 3.0 * self.dizzy_amp) * self.scale,
                              color=GOLD_L, phase=a, spin=5.0)
        elif st == "walk":
            step = SPEED * self.scale * dt
            if abs(self.walk_target - self.x) <= step:
                self.x = int(self.walk_target)
                self.state = "idle"
                self.next_event = now + random.uniform(6, 14)
            else:
                self.x += step if self.walk_target > self.x else -step
            # 步态:按真实走过的距离推进步相(整数处落脚)。起伏、前倾和脚下
            # 星尘都踩在同一个步点上 —— 原来起伏按全局时钟算、星尘固定 0.35 秒
            # 一颗,和实际移动脱节,看起来像被拖着平移。
            prev_phase = self._walk_phase
            self._walk_phase += step / (26.0 * self.scale)
            self.lean += (self.face * 0.04 - self.lean) * 0.15
            if int(self._walk_phase) != int(prev_phase):
                # 落脚这一下:轻轻踩实(squash 每帧自己回弹)、落点压出一圈
                # 扁光环、尘星往身后扬。光环走粒子而不是 self.circles —— 后者
                # 恒定画在身体正中,和常驻的地面法阵重叠,等于没画;粒子能落在
                # 真正的落脚点上,左右脚交替就看得出来了。尘星也甩到法阵外圈,
                # 不再混进法阵自带的星点里。
                foot = 0.11 if int(self._walk_phase) % 2 else -0.06
                ground = (self.FOOT_Y + 8 * self.scale) - self.H / 2
                self.squash = min(self.squash, 0.955)
                self._step_flash = now
                for _ in range(random.randint(2, 3)):
                    self.add_part("sparkle", (foot - self.face * 0.03) * self.W
                                  + random.uniform(-5, 5),
                                  ground - 6 + random.uniform(-4, 2),
                                  vx=-self.face * random.uniform(34, 78),
                                  vy=-random.uniform(26, 48), grav=130,
                                  life=0.55, size=random.uniform(5, 8.5),
                                  color=random.choice([GOLD_L, WHITE]),
                                  phase=random.uniform(0, 6.28))
            if now > self.state_until:
                self.state = "idle"
                self.next_event = now + random.uniform(6, 14)
        elif st == "sticker":
            if now > self.state_until:
                self.state = "idle"
                self.next_event = now + random.uniform(8, 18)
        elif st == "sleep":
            if now > self.next_z:
                self.next_z = now + 1.3
                self.add_part("zzz", 0.16 * self.W, -0.34 * self.H,
                              vy=-14, life=2.2, size=13, phase=0)
            self.parts = [p for p in self.parts if p["kind"] == "zzz"]
            if now > self.state_until:
                self.wake_up()
        elif st == "fall":
            self.vy = min(120.0 * self.scale, self.vy + 420 * dt)
            self.fy += self.vy * dt
            if now > self.next_trail:
                self.next_trail = now + 0.09
                self.add_part("sparkle", random.uniform(-0.1, 0.1) * self.W,
                              0.1 * self.H, life=0.55, size=random.uniform(3, 6),
                              color=random.choice([MAGIC_A, MAGIC_B, GOLD]),
                              phase=random.uniform(0, 6.28))
            if self.fy >= self.ground_feet:
                self.fy = self.ground_feet
                if self.vy > 100:
                    self.vy = -self.vy * 0.3
                    self.squash = 0.88
                else:
                    self.vy = 0.0
                    self.state = "idle"
                    self.next_event = now + random.uniform(2.5, 5)
                    self.circles.append(dict(born=now, life=0.6, rx=0.9, kind="flash"))
                    # 松手下落是轻落地(速度上限 120px/s):最弱一档冲击波
                    self.land_fx(self._landing_strength(0.0))
                    self.star_burst(0, 0.22 * self.H, 6, sp=(60, 120), grav=150, size=(4, 8))
                    # 被抛出去弹跳过的落地:30% 概率来一句"安全着陆"
                    if self.bounces >= 2 and random.random() < 0.3:
                        self.say(random.choice(
                            ["安全着陆!", "哇…还活着~", "落地成功!"]), 2.0)
                    self.save_settings()
                    # 在秋千上点的动作(喂糖/施法/跳舞/睡觉…):站稳了再做
                    self._run_land_then()
        elif st == "magic":
            if self.next_fountain and now > self.next_fountain:
                self.next_fountain = now + 0.12
                self.add_part("star", 0.2 * self.W, -0.36 * self.H,
                              vx=random.uniform(-30, 30), vy=-random.uniform(50, 110),
                              life=random.uniform(0.8, 1.3), size=random.uniform(4, 8),
                              color=random.choice([GOLD, WHITE, GOLD_L]),
                              phase=random.uniform(0, 6.28), spin=random.uniform(-5, 5),
                              grav=170)
            if now > self.state_until:
                self.state = "idle"
                self.next_event = now + random.uniform(8, 16)
        elif st == "eat":
            age = now - self.eat_start
            self.squash, self._bend = self._eat_pose(age)
            # 糖果 1.1 秒进嘴后到结算之间原来什么都不发生,连拍看就是站着。
            # 进嘴那下迸一小撮金屑,之后每口嚼(对上 _eat_pose 的压扁拍)
            # 从嘴角崩两粒往下掉 —— 节拍用集合记,掉帧也不会重放或漏掉。
            mx, my = getattr(self, "_mouth_xy", (self.W * .49, self.H * .42))
            beats = getattr(self, "_eat_beats", set())
            for i, bt in enumerate((1.1, 1.24, 1.52, 1.8)):
                if age >= bt and i not in beats:
                    beats.add(i)
                    first = i == 0
                    for _ in range(5 if first else 2):
                        side = random.choice((-1, 1))
                        self.add_part("sparkle",
                                      mx - self.W / 2 + side * random.uniform(4, 10) * self.scale,
                                      my - self.H / 2 + random.uniform(-2, 3),
                                      # 往两侧甩出脸的轮廓:落在白领口/脸上
                                      # 的浅色碎屑完全没有对比,看不见。
                                      vx=side * random.uniform(*((75, 135) if first
                                                                 else (55, 95))),
                                      vy=-random.uniform(*((55, 105) if first
                                                           else (35, 60))),
                                      grav=240, life=.55 if first else .48,
                                      size=random.uniform(6.5, 9.5) if first
                                      else random.uniform(5.0, 7.0),
                                      color=random.choice((GOLD, GOLD_L)),
                                      phase=random.uniform(0, 6.28))
            self._eat_beats = beats
            if now > self.state_until:
                gained = self.gain_star(40)
                mx, my = getattr(self, "_mouth_xy", (self.W * .49, self.H * .42))
                self.hit_ring(mx - self.W / 2, my - self.H / 2)
                self.star_burst(0, -0.1 * self.H, 8, sp=(60, 130), grav=100)
                self.hearts(0, -0.15 * self.H, 3)
                self.play_emotion("thanks", 2.4)
                # 已经饱的时候别说"能量充满",得说吃饱了的话
                self.say(random.choice(
                    ["已经饱啦,星光满满的~"] if gained < 5 else
                    ["星光糖果,甜甜的!", "能量充满!", "谢谢招待~",
                     "唔姆,甜到心里了~", "星光要满满的才行!"]), 2.4)
                self.state = "idle"
                self.next_event = now + random.uniform(8, 16)
                self.save_settings()
        elif st == "fall_stand":
            self.squash, self.lean, self._bend = self._stand_pose(now-self.fall_stand_start)
            if now > self.state_until:
                self.state = "idle"
                self.next_event = now + random.uniform(3, 6)
        elif st == "yawn":
            age = now - (self.state_until - 1.6)
            self.squash, self.lean = self._yawn_pose(age)
            if now > self.state_until:
                self.sfx.play("sleep")
                self.play_emotion("sleep", 3.2)
                self.state = "sleep"
                self.state_until = now + random.uniform(60, 120)
                self.next_z = now + .7
                self.bubble = None
        elif st == "twirl":
            # 陀螺式真旋转走时间轴;这里只管星尘(蓄力汇聚 + 螺旋尾迹)
            t2 = now - self.twirl_start
            d = getattr(self, "twirl_dir", 1)
            self._play_timeline(t2, self._tl_tracks, self._tl_events, self._tl_done)
            if t2 < 0.55 and now > self.next_trail:
                # ① 蓄力:星尘向身体汇聚
                self.next_trail = now + 0.04
                a = random.uniform(0, 6.28)
                rr = (0.42 - 0.5 * t2) * self.W
                self.add_part("sparkle", math.cos(a) * rr,
                              math.sin(a) * rr * 0.5 - 0.1 * self.H,
                              life=0.45, size=random.uniform(4, 8),
                              color=random.choice(STAR_COLORS), phase=a)
            elif 0.55 < t2 < 2.45 and now > self.next_trail:
                # ② 旋转:螺旋星尘尾迹,越转越高
                k = (t2 - 0.55) / 1.9
                self.next_trail = now + 0.05
                a2 = t2 * (9 + 9 * k) * d
                rr = (0.16 + 0.20 * min(1.0, t2 / 1.4)) * self.W
                self.add_part("sparkle", math.cos(a2) * rr,
                              math.sin(a2) * rr * 0.55 - 0.08 * self.H,
                              life=0.6, size=random.uniform(5, 10),
                              color=random.choice(STAR_COLORS), phase=a2)
            if now > self.state_until:
                self.state = "idle"
                self.next_event = now + random.uniform(8, 14)
                if random.random() < 0.35:
                    self.go_dizzy()
                    self.say("呜…转得有点晕…", 2.2)
                else:
                    self.say(random.choice(
                        ["转圈圈好开心~", "看到我的裙摆了吗~✧", "转完啦!稳稳落地~"]), 2.0)
        elif st == "tstop":
            # 时停:姿势与特效全在时间轴和 fx 演出层里,分支只管到点收工
            self._play_timeline(now - self.tstop_start, self._tl_tracks,
                                self._tl_events, self._tl_done)
            if now > self.state_until:
                self.state = "idle"
                self.next_event = now + random.uniform(8, 14)
        elif st == "rewind":
            # 回演:同上,倒带结束顺手哼一声
            self._play_timeline(now - self.rewind_start, self._tl_tracks,
                                self._tl_events, self._tl_done)
            if now > self.state_until:
                self.state = "idle"
                self.next_event = now + random.uniform(8, 14)
        elif st == "sneeze":
            self._advance_sneeze(now)

        # 星光形态(魔法变身 Buff):被动星尘尾迹,走到哪洒到哪
        if not self.core_profile() and now < getattr(self, "_starform_until", 0) and now > self.next_trail:
            self.next_trail = now + 0.3
            self.add_part("sparkle", random.uniform(-0.35, 0.35) * self.W,
                          random.uniform(-0.3, 0.05) * self.H,
                          life=0.9, size=random.uniform(3, 6),
                          color=random.choice(STAR_COLORS),
                          phase=random.uniform(0, 6.28))

        # 星光磁铁(可见版):星光≥80 时,可捕捉金星缓慢向她漂移
        if self.star >= 80:
            hx, hy = self.W / 2, self.H * 0.42
            for q in self.parts:
                if q["kind"] == "cstar":
                    age = now - q["born"]
                    cx = q["x"] + q["vx"] * age
                    cy = q["y"] + q["vy"] * age + 0.5 * q["grav"] * age * age
                    d = math.hypot(hx - cx, hy - cy)
                    if d > 30:
                        q["x"] += (hx - cx) / d * 1.6
                        q["y"] += (hy - cy) / d * 1.6

        self._advance_ball(now)

        for q in self.parts:
            if q["kind"] == "bub" and not q.get("popped"):
                if now - q["born"] > q["life"] * 0.86:
                    q["popped"] = True
                    self.sfx.play("pop")

        # 雪花落到地面高度 -> 积雪变厚;平时缓慢融化
        landed_snow = 0
        for q in self.parts:
            if q["kind"] == "snow" and not q.get("landed"):
                age = now - q["born"]
                if q["y"] + q["vy"] * age + 0.5 * q["grav"] * age * age > self.H * 0.92:
                    q["landed"] = True
                    landed_snow += 1
        if landed_snow:
            self.snow_ground = min(1.0, self.snow_ground + landed_snow * 0.18)
        self.snow_ground = max(0.0, self.snow_ground - dt * 0.02)

        # 全屏魔法:画在另一块盖住整个显示器的分层窗口上
        if self.state == "magic" and self._magic_style_cur == 1:
            span = max(0.1, self.state_until - self.magic_start)
            self.fsmagic.frame(self.x + self.W / 2,
                               self.fy - self.H * 0.38,
                               min(1.0, (now - self.magic_start) / span))
        elif self.fsmagic.win is not None:
            self.fsmagic.close()

        # 屏幕边界复查:插拔外接屏、切分辨率之后跟着变
        if now > getattr(self, "_next_screen_check", 0):
            self._next_screen_check = now + 2.0
            self._refresh_screen()
            # 秋千态每帧按场景覆盖 x/fy,上面的 clamp 对她不起作用:场景
            # 所在的屏拔掉/挪走了,就得把整个场景拉回看得见的工作区
            if self._swing:
                self._swing_fit_scene()

        # 粒子 / 特效清理
        self.parts = [p for p in self.parts if now - p["born"] < p["life"]]
        # 硬上限兜底:纪念日会同时放彩带 + 烟花 + 环境星光,靠 life 自然过期
        # 峰值能上几百。留最新的 MAX_PARTS 个,旧的直接丢 —— 看不出来。
        if len(self.parts) > MAX_PARTS:
            del self.parts[:len(self.parts) - MAX_PARTS]
        self.circles = [c for c in self.circles if now - c["born"] < c["life"]]
        self._shocks = [s for s in self._shocks if now - s["born"] < 0.6]
        # 接星星收尾:场上没有可捕捉星了就结账
        if getattr(self, "_catch_total", 0) > 0:
            if not any(p["kind"] == "cstar" for p in self.parts):
                got = self._catch_got
                if got > 0 and got < self._catch_total:
                    self.say(f"接住了 {got} 颗~", 2.2)
                self._catch_total = 0
        if self.hop_t > 0:
            total = getattr(self, "_hop_total", self.hop_t)
            prev_age = total - self.hop_t
            self.hop_t = max(0.0, self.hop_t - dt)
            if self._hop_touchdown(prev_age, total - self.hop_t, total):
                # 每次触地压扁一下(squash 每帧自己回弹到 1)。压到 0.93 只
                # 跨一个变形缓存档,整段蹦跳最多多出两张网格,不会连续未命中。
                self.squash = min(self.squash, 0.93)
        if self.sticker and now - self.sticker["born"] > self.sticker["life"]:
            self.sticker = None
        if self._sticker_previous and (not self.sticker or now-self._sticker_previous[1] >= .18):
            self._sticker_previous = None
        if self.bubble and now >= self.bubble[1]:
            # 过期的气泡要清掉:渲染虽然不画它,但安静待机/睡眠的降帧判定
            # 都拿 self.bubble 当"有话在说"的信号,残留会让降帧永远进不去
            self.bubble = None

        # 季节氛围:春樱/秋叶/冬雪 + 夏夜萤火虫(20~40 秒一个,不打扰)
        lt = self._now_local()
        mon, hour = lt.tm_mon, lt.tm_hour
        if (self.state not in ("sleep", "yawn")
                and now > getattr(self, "next_seasonal", 0)):
            self.next_seasonal = now + random.uniform(20, 40)
            # add_part 的 rx 是相对窗口中心的偏移,先减掉半宽
            lx = random.uniform(0.06, 0.94) * self.W - self.W / 2
            if mon in (9, 10, 11):                       # 秋:落叶
                leaf_colors = [(214, 138, 63), (193, 90, 57), (222, 184, 84)]
                self.add_part("leaf", lx, -0.05 * self.H,
                              vx=random.uniform(-15, 15),
                              vy=random.uniform(28, 46),
                              life=random.uniform(4.5, 6.5),
                              size=random.uniform(5, 8),
                              color=random.choice(leaf_colors),
                              phase=random.uniform(0, 6.28),
                              spin=random.uniform(-4, 4))
            elif mon in (3, 4, 5):                       # 春:樱花瓣
                petal_colors = [(255, 183, 197), (255, 210, 220), (250, 160, 180)]
                self.add_part("petal", lx, -0.05 * self.H,
                              vx=random.uniform(-20, 20),
                              vy=random.uniform(24, 40),
                              life=random.uniform(4.5, 6.5),
                              size=random.uniform(4, 7),
                              color=random.choice(petal_colors),
                              phase=random.uniform(0, 6.28),
                              spin=random.uniform(-5, 5))
            elif mon in (12, 1, 2):                      # 冬:雪
                self.add_part("snow", lx, -0.05 * self.H,
                              vx=random.uniform(-10, 10),
                              vy=random.uniform(22, 38),
                              life=random.uniform(5.0, 7.0),
                              size=random.uniform(2, 4),
                              color=(245, 248, 255), phase=random.uniform(0, 6.28))
            elif mon in (6, 7, 8) and (hour >= 19 or hour < 5):  # 夏夜:萤火虫
                self.add_part("firefly",
                              random.uniform(0.1, 0.9) * self.W - self.W / 2,
                              random.uniform(0.15, 0.75) * self.H - self.H / 2,
                              vx=random.uniform(-8, 8), vy=random.uniform(-6, 6),
                              life=random.uniform(5.0, 8.0),
                              size=random.uniform(2, 3.5),
                              color=(210, 235, 130), phase=random.uniform(0, 6.28))

        # 夜间流星:22 点~5 点,低频划过她头顶的窗外(氛围,不打扰)
        hour = lt.tm_hour
        if ((hour >= 22 or hour < 5) and self.state not in ("sleep", "yawn")
                and now > self.next_meteor):
            self.next_meteor = now + random.uniform(50, 100)
            side = random.choice((-1, 1))
            self.add_part("meteor", -0.5 * self.W * side, -0.42 * self.H,
                          vx=(680 + random.uniform(-120, 160)) * side,
                          vy=random.uniform(140, 230),
                          life=random.uniform(0.7, 1.0), size=6,
                          color=GOLD_L, phase=random.uniform(0, 6.28))
            # 流星本身留着 —— 无声划过是"窗外的夜在继续",不是打扰;
            # 台词是,所以专注时只闭嘴不撤景
            if random.random() < 0.2 and not self.focus_mode():
                self.say("流星!快许愿~", 2.0)

        # 环境星光(她会随星光值变暗淡:能量低时周围的星星也稀疏些,
        # 和饥饿台词一起构成"该喂糖了"的视觉信号)
        if self.state not in ("sleep",) and now > self.next_ambient:
            scarcity = 1.0 + (1.0 - self.star / 100.0) * 1.5
            self.next_ambient = now + random.uniform(0.45, 1.1) * scarcity
            a = random.uniform(0, 2 * math.pi)
            r = random.uniform(0.16, 0.3) * self.W
            self.add_part("sparkle", math.cos(a) * r, math.sin(a) * r * 0.9 - 0.05 * self.H,
                          life=random.uniform(0.8, 1.3), size=random.uniform(4, 8),
                          color=random.choice(STAR_COLORS), phase=random.uniform(0, 6.28))

        # 数字彩蛋:每天 12:34 那一分钟,她会发现"数字在排队"
        if (self._now_hm == "12:34"
                and getattr(self, "_num_egg_day", None) != self._now_ymd
                and self.state in ("idle", "walk") and not self.bubble):
            self._num_egg_day = self._now_ymd
            self.say("咦,12:34!数字们在排队整队呢~", 3.0)
            self.play_emotion("curious", 2.5)
            # "数字们"出场:三颗小齿轮排成一列,从她面前正步走过
            for i in range(3):
                self.add_part("gear",
                              (-0.42 + 0.13 * i) * self.W,
                              (0.20 - 0.05 * i) * self.H,
                              vx=95.0, life=1.7,
                              size=7.0 - 1.3 * i,
                              spin=7.0, phase=random.uniform(0, 6.28))

        # 托盘 tooltip 每分钟刷新:陪伴天数 + 星光(悬停托盘图标可见)
        if (self._tray and int(now) != getattr(self, "_tray_title_min", -1)):
            self._tray_title_min = int(now)
            try:
                self._tray.title = (f"小乔 · 陪伴第 {self.companion_days()} 天 · "
                                    f"星光 {int(self.star)}%")
            except Exception:
                pass

        # 被冷落撒娇:整整 15 分钟没人互动才轻轻来一次(粘人属性)。
        # 放在状态机之后:不被同帧的随机 idle 台词覆盖;有气泡在说就不抢。
        # 睡着时只说梦话,不真的醒来;平时委屈脸 + 小蹦跶。
        # 专注期间必然满足"15 分钟没互动",但那是主人在干正事,不是冷落。
        # 不 guard 的话她会在专注到一半时说"哼,都不理我" —— 语义正好说反。
        if (now > self.next_whine and now - self.last_interact > 900
                and not self.bubble and not self.focus_mode()):
            self.next_whine = now + 900
            if self.state == "sleep":
                self.say(random.choice(SLEEP_WHINE_LINES), 3.2)
            elif self.state == "idle":
                self.say(random.choice(WHINE_LINES), 3.0)
                self.play_emotion("sad", 2.6)
                self.hop(0.35)
                # 委屈得冒泪珠:两三滴小泪飘下来
                for _ in range(random.randint(2, 3)):
                    self.add_part("sweat",
                                  random.uniform(-0.10, 0.10) * self.W,
                                  -0.28 * self.H + random.uniform(-8, 8),
                                  vx=random.uniform(-12, 12),
                                  vy=random.uniform(22, 34),
                                  life=1.0, size=random.uniform(2.8, 4.2))

        self.render(now, t)

        # 状态文件默认不写:它每秒把聊天框全文 dump 一次到硬盘,
        # 开着一天就是几万次写入,而这本来只是调试/自动化接口。
        # 需要的话加 --debug-state 启动。
        if DEBUG_STATE and int(now) != getattr(self, "_last_state_write", -1):
            self._last_state_write = int(now)
            self._write_state()

    def cast_fx(self):
        """大招用的精灵比常驻的大不少(约 650ms),不放在启动路径上。

        但也不能真等到第一次施法才建 —— 那 650ms 会直接砸在主线程上,
        双击之后人僵住半秒才出效果。所以启动几秒后由 _warm_fx 在后台先建好,
        这里只是兜底:万一预热还没跑完就施法了,该等还是得等。
        """
        with self._castfx_lock:
            if self._castfx is None:
                self._castfx = fx.CastFX(self.fx)
            return self._castfx

    def _warm_tk_text(self, tries=0):
        """聊天窗第一次打开时,Tk 第一次实现那几种字体/文字要 130~200ms(标题里
        的 ✦ 雅黑没有字形,还要找替代字体),点开那一下就卡在这里。在隐藏画布上
        先画一遍。这 130~200ms 挪不掉,只是挪到没人互动的时候:她空闲、3 秒没
        人碰才做,不然 5 秒后再看,最多等 6 次。实测首次开聊天窗 233~299ms ->
        92~111ms。Tk 不是线程安全的,只能在主线程做。秋千上荡着也算空闲(默认
        就住在秋千上,不认它的话 6 次全落空,这一步等于没做)。"""
        if (self.state not in ("idle", "sleep", "swing")
                or time.time() - self.last_interact < 3):
            if tries < 6:
                self.root.after(5000, lambda: self._warm_tk_text(tries + 1))
            return
        try:
            u = ChatBox._layout(self.sw, self.sh)[0]
            cv = tk.Canvas(self.root, width=1, height=1)
            for txt, font in (("✦ 和小乔聊一会儿", ("Microsoft YaHei UI", -int(18 * u), "bold")),
                              ("陪伴第 1 天 · 互动陪伴中", ("Microsoft YaHei UI", -int(10 * u))),
                              ("你好", ("Microsoft YaHei UI", -int(14 * u))),
                              ("摸摸头", ("Microsoft YaHei UI", -int(13 * u), "bold"))):
                cv.create_text(0, 0, text=txt, font=font)
            cv.update_idletasks()
            cv.destroy()
            self._text_warmed = True
        except Exception:
            self._log_exc("预热聊天窗字体")

    def _warm_fx_deferred(self):
        """开机 0.7 秒后在后台补建冲击波/命中光环/喷气团/冥想星核。PIL 的模糊
        在 C 里放开 GIL,不怎么抢帧循环。"""
        if self.core_profile():
            return False
        layer = self.fx

        def work():
            try:
                layer.build_deferred()
            except Exception:
                self._log_exc("warm_fx 补建精灵")

        threading.Thread(target=work, daemon=True).start()

    def _warm_fx(self):
        """后台预热大招精灵和飘字字形。全程只碰 PIL 不碰 Tk,放线程里安全。

        字形放这里而不是跟着 FX 同步建:11 个带柔光的字形约 40ms,同步建会
        再拖慢一次启动首帧。没建好之前 gain_text 什么都不画,开机头几秒
        喂糖只是少一行飘字。"""
        layer = self.fx

        def work():
            if self.core_profile():
                layer.build_core_feedback()
            else:
                layer.build_deferred()
            try:
                ChatBox.prewarm_bg(self.sw, self.sh)   # 聊天窗背景先画好,第一次打开不卡
            except Exception:
                self._log_exc("warm_fx 聊天窗背景")
            if not self.core_profile():
                self.cast_fx()
            try:
                if getattr(layer, "gain", None) is None:
                    layer.build_gain_glyphs(load_font(int(17 * layer.scale * SS)))
            except Exception:
                self._log_exc("warm_fx 飘字字形")

        threading.Thread(target=work, daemon=True).start()

    def _spr_top(self):
        return self.fy - self._spr_disp_h() + 6

    def _spr_disp_h(self):
        return getattr(self, "_sprite_h", SPRITE_H) * self.scale

    # ==================== 渲染 ====================
    def render(self, now, t):
        W, H = self.W, self.H
        asleep = self.state == "sleep" or getattr(self, "_nap_on_swing", False)
        casting = self.state == "magic"
        eating = self.state == "eat"
        happy = self.hop_t > 0

        drop = max(0.0, self.ground_feet - self.fy)
        dy = -drop
        # 连续的双节奏浮动,避免 abs(sin) 每半周期突然折返。
        breath_rate = .95 if asleep else 1.7
        bob = (-1.75 + 1.75 * math.sin(t * breath_rate)
               + .6 * math.sin(t * .73)) * self.scale
        if self.state == "walk":
            bob = -abs(math.sin(self._walk_phase * math.pi)) * 5.5 * self.scale
        if happy:
            # 呼吸浮动不停,小跳叠在它上面:起跳和落地都接得上,不会跳变
            total = getattr(self, "_hop_total", self.hop_t)
            bob -= self._hop_curve(total - self.hop_t, total,
                                   getattr(self, "_hop_amp", self.hop_t)) * self.scale

        # 复用同一块画布:每帧新建再丢掉一个 8MB 的 RGBA,一秒 30 次,
        # 分配器的压力远大于直接清空(实测 1.32ms vs 0.38ms)。
        frame = self._frame_buf
        if frame is None or frame.size != (W * SS, H * SS):
            frame = self._frame_buf = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
        else:
            frame.paste((0, 0, 0, 0), (0, 0, frame.width, frame.height))
        light = self._light
        if light is None or light.im.size != frame.size:
            light = self._light = LightLayer(frame.size)
        d = ImageDraw.Draw(frame, "RGBA")
        k = SS
        cx2 = W / 2 * k
        foot_base = H - int(30 * self.scale)
        feet2 = foot_base * k
        circ_y = foot_base + 8 * self.scale
        # 阴影留在地面,腾空时扩散变淡;使用少量预模糊档位。
        altitude = drop + max(0., bob + getattr(self, '_spin_lift', 0.))
        # 坐在原画秋千上:她和坐垫都在场景原画里,这一帧只画特效/气泡/灯板,
        # 脚下的影子、光垫、法阵也不画(脚悬在半空)
        art_on = bool(self.state == "swing" and getattr(self, "_swing", None)
                      and self._swing.get("art"))
        if not art_on:
            shadow = self.warper.shadow(altitude, self.scale)
            frame.alpha_composite(shadow, (int(cx2-shadow.width/2),
                int((circ_y+drop)*k-shadow.height/2)))
        if not asleep and not art_on:
            self.paste_glow(frame, W / 2 * k, circ_y * k, int(96 * self.scale),
                            (120, 150, 255), 60)
            # 脚下魔法阵:施法全开;跳舞时每拍踩点亮一下;星光形态常亮微光
            energy = 0.0
            if casting:
                energy = 1.0
            elif self.state == "dance":
                energy = max(0.0, 1.0 - ((now - self.dance_start)
                                         % getattr(self, "dance_beat", 0.42)) / 0.2) * 0.7
            elif self.state == "walk":
                # 每次落脚法阵亮一下、转速顶一下 —— 比在法阵里再画一圈小光环
                # 管用得多:那圈细线正好和常驻法阵重叠,等于没画。
                energy = max(0.0, 1.0 - (now - self._step_flash) / 0.18) * 0.38
            elif now < getattr(self, "_starform_until", 0):
                energy = 0.35
            # 光标靠近时法阵"醒过来":五芒星变亮、符文转快。只抬不压,
            # 演出本身的能量更高时以演出为准
            energy = max(energy, 0.5 * getattr(self, "_prox", 0.0))
            # 呼吸光跟她的浮动同相:浮到高处时脚下最亮,像是法阵在托着她。
            # 原来光垫亮度是死的,待机时法阵只有符文在匀速转。
            self.fx.ground_circle(frame, d, cx2, circ_y * k, now - self.t0, energy=energy,
                                  breath=0.5 - 0.5 * math.sin(t * breath_rate))
            if not casting:
                # 每 5.2 秒从金色内圈荡出一道光纹,1.8 秒走到外圈。按全局时钟
                # 算而不存状态:没有要复位的东西,掉帧也不会叠出好几道。
                self.fx.ground_ripple(frame, cx2, circ_y * k,
                                      (t % RIPPLE_PERIOD) / RIPPLE_TRAVEL)
                # 光标刚靠近:额外荡一道"欢迎"光纹,和周期光纹各走各的
                self.fx.ground_ripple(frame, cx2, circ_y * k,
                                      (now - getattr(self, "_ripple_kick", -99.0))
                                      / RIPPLE_TRAVEL)
        # 冬季积雪:雪花落地后脚下慢慢积出一圈软白雪,停止下雪会融化
        mon = self._now_local().tm_mon
        if self._season(mon) == "winter" and self.snow_ground > 0.02 and not art_on:
            g = self.snow_ground
            sw = W * (0.55 + 0.35 * g) * k
            sh = 10 * self.scale * (0.5 + 0.5 * g) * k
            a1 = int(30 + 55 * g)
            d.ellipse([cx2 - sw / 2, circ_y * k - sh / 2,
                       cx2 + sw / 2, circ_y * k + sh / 2],
                      fill=(235, 242, 252, a1))
            d.ellipse([cx2 - sw / 2.6, circ_y * k - sh / 2.6,
                       cx2 + sw / 2.6, circ_y * k + sh / 2.6],
                      fill=(246, 250, 255, min(255, a1 + 30)))
        self._draw_decors(frame, d, t, "back", dy, k)

        amp = PARALLAX_AMP * self.scale * SS
        micro_lean, micro_bend, micro_squash, micro_lift = self._micro_pose(now)
        render_lean = self.lean + micro_lean + self._drag_lean
        if self.state == "swing" and self._swing:
            # 荡动的轻微俯仰:身体随绳微倾(0.05rad 内,不破坏脸型结构)
            render_lean += 0.05 * math.sin(self._swing.get("theta", 0.0))
        render_bend = getattr(self, "_bend", 0.0) + micro_bend
        render_squash = self.squash + micro_squash
        # bob 只是整体上下平移,没必要参与网格变形。把它从缓存键里拿掉后,
        # 鼠标静止时 look/lean/squash 都不变,同时在用的条目从 22 个塌缩到 1 个,
        # 所以缓存上限从 40 张(40 x 4.3MB = 172MB)降到 12 张也不掉命中率。
        # 顺带修掉两个老毛病:bob 原来在画布内部位移,她的脚会被切掉最多 10px,
        # 而气泡/眨眼贴片又不跟着动 —— 现在整体一起平移,两个问题都没了。
        depth_pose = self._depth_motion.sample(now, self.look_x, self.look_y,
            self.state, bool(self.drag and self.drag[4]))
        depth_pose = tuple(round(v*20)/20 for v in depth_pose)
        # 次级物理:呼吸/走路/拖拽/落地激励帽尖、发梢、裙摆的弹簧。
        # sway 量化进缓存键(1/50 步):静止时弹簧只在微风幅度内缓慢移动,
        # 缓存照样命中;一阵风或一次落地才重变形几帧,和跳舞同量级。
        _lpbt = max(0.001, now - self._life_prev_t) if self._life_prev_t else 0.033
        bob_vel = (bob - self._life_prev_bob) / _lpbt
        self._life_prev_bob, self._life_prev_t = bob, now
        if PET_SWAY:
            sway = self.life.update(now, self.state, bool(self.drag and self.drag[4]),
                                    self.x, self.fy, bob_vel=bob_vel,
                                    walking=(self.state == "walk"), t=t)
            # 分通道量化:旋转步长小(帽尖 0.8px 级)、位移步长 0.25px —— 都是
            # 肉眼不可见的台阶,但让微风期的缓存命中率回到"几乎总是命中",
            # 只有真正的一阵风/一次落地才重变形几帧(和跳舞同量级)
            sway_q = (round(sway[0] * 100) / 100,) + tuple(round(v * 2) / 2 for v in sway[1:])
        else:
            sway = sway_q = None
        face_key = self._face_texture_key(now, t, asleep)
        self._last_face_key = face_key      # 秋千原画模式按同一帧的五官状态贴补丁
        self._last_depth_pose = depth_pose  # …和同一帧的视线(头部跟随有滞后)
        wkey = (depth_pose, face_key,
                round(render_lean * 80), round(render_squash * 12),
                round(render_bend * 60), sway_q)
        warped = self._warp_cache.get(wkey)
        if warped is None:
            source = self._face_texture(depth_pose, face_key)
            warped = self.warper.warp(self.look_x, self.look_y, render_lean, 0.0,
                render_squash, amp, bend=render_bend, pose=depth_pose, source=source,
                source_alpha_fixed=True, sway=sway_q)
            if len(self._warp_cache) >= WARP_CACHE_MAX:
                self._warp_cache.popitem(last=False)      # 淘汰最久没用的那张
            self._warp_cache[wkey] = warped
        else:
            self._warp_cache.move_to_end(wkey)
        sprite = warped
        # 有图层要叠时先复制:warped 是 _warp_cache 里的缓存图,直接在它上面
        # alpha_composite 会把这一帧的帽/腿/发层永久烙进缓存,下一帧命中再叠
        # 一次 —— 摆动中的图层就一层层累积成残影和碎片。
        if (getattr(self, "hat_spr2", None) is not None
                or getattr(self, "hair_bands", None)
                or getattr(self, "legsl_spr2", None) is not None
                or getattr(self, "legsr_spr2", None) is not None):
            sprite = warped.copy()
        # ---- 帽层:同一张深度网格(lean/squash/视线全一致)+ 自身弹簧。
        # 帽子已经从底图挖掉,这里的 sway 帽通道对底图是空操作,帽层的
        # 大幅摆动由 hat_ang/hat_lift 承担(是深度帽通道的 2.2 倍)。
        if getattr(self, "hat_spr2", None) is not None:
            hat_ang = life.clamp(self.life.hat_rot.x * 2.2
                                 + self.look_x * 0.035, -0.14, 0.14)
            hat_lift = self.life.hat_dx.x * 1.5
            hat_ang_q = round(hat_ang * 80) / 80
            hat_lift_q = round(hat_lift * 2) / 2
            hkey = (wkey, hat_ang_q, hat_lift_q)
            hat_warped = self._hat_warp_cache.get(hkey)
            if hat_warped is None:
                hat_img = self.hat_spr2
                if abs(hat_ang_q) > 1e-4 or abs(hat_lift_q) > 1e-4:
                    hat_img = hat_img.rotate(
                        -math.degrees(hat_ang_q), resample=Image.BILINEAR,
                        center=(hat_img.width * 0.475, hat_img.height * 0.55))
                    if abs(hat_lift_q) > 1e-4:
                        lifted = Image.new("RGBA", hat_img.size, (0, 0, 0, 0))
                        lifted.alpha_composite(
                            hat_img, (0, int(round(hat_lift_q))))
                        hat_img = lifted
                hat_src_lit = self.warper.lit_for(hat_img, depth_pose)
                hat_warped = self.warper.warp(
                    self.look_x, self.look_y, render_lean, 0.0,
                    render_squash, amp, bend=render_bend, pose=depth_pose,
                    source=hat_src_lit, source_alpha_fixed=True,
                    lighting=False, sway=(0.0, 0.0, sway_q[2], sway_q[3]))
                if len(self._hat_warp_cache) >= 10:
                    self._hat_warp_cache.popitem(last=False)
                self._hat_warp_cache[hkey] = hat_warped
            else:
                self._hat_warp_cache.move_to_end(hkey)
            sprite.alpha_composite(hat_warped)
        # ---- 腿层:悬垂/踢腿物理(荡秋千的角加速度、落地屈膝、随机轻晃),
        # 绕髋部旋转,同一张深度网格跟随 lean/squash。
        for side, ang_key in (("l", "leg_l"), ("r", "leg_r")):
            if getattr(self, f"legs{side}_spr2", None) is None:
                continue
            leg_ang = life.clamp(getattr(self.life, ang_key).x, -0.10, 0.10)
            leg_q = round(leg_ang * 100) / 100
            # 膝弯也要进缓存键(0.5px 一档):之前漏了,命中缓存时膝弯
            # 就冻在第一次画的那个角度上
            knee_dx = round(life.clamp(getattr(
                self.life, f"knee_{side}").x, -7.0, 7.0) * 2) / 2
            # 键里只放腿层变形真正用到的输入(网格 pose/lean/squash/bend + 摆角
            # + 膝弯)。原来整个 wkey 都塞进来:腿层不吃五官贴图也不吃 sway,
            # 眨一下眼、帽尖发梢裙摆走一个弹簧台阶,两条腿就白白重变形一遍
            lkey = (depth_pose, round(render_lean * 80), round(render_squash * 12),
                    round(render_bend * 60), side, leg_q, knee_dx)
            legs_warped = self._legs_warp_cache.get(lkey)
            if legs_warped is None:
                legs_img = getattr(self, f"legs{side}_spr2")
                if abs(leg_q) > 1e-4:
                    legs_img = legs_img.rotate(
                        math.degrees(leg_q), resample=Image.BILINEAR,
                        center=(legs_img.width * 0.45, legs_img.height * 0.05))
                legs_warped = self.warper.warp(
                    self.look_x, self.look_y, render_lean, 0.0,
                    render_squash, amp, bend=render_bend, pose=depth_pose,
                    source=legs_img, source_alpha_fixed=True, lighting=False,
                    source_offset=getattr(self, f"legs{side}_off_s"),
                    leg_bend=(0.827 * self.spr2.height, knee_dx))
                if len(self._legs_warp_cache) >= 12:
                    self._legs_warp_cache.popitem(last=False)
                self._legs_warp_cache[lkey] = legs_warped
            else:
                self._legs_warp_cache.move_to_end(lkey)
            sprite.alpha_composite(legs_warped, getattr(self, f"legs{side}_off_s"))
        # ---- 发层:三分带(左/中/右缕)+ 每缕独立弹簧 —— 相位差让头发
        # 呈波浪般起伏;剪切锚定肩线处为 0,与底图拼接无接缝。
        if getattr(self, "hair_bands", None):
            for bi, (band_img, band_off) in enumerate(self.hair_bands):
                amp_i = life.clamp(self.life.hair_strands[bi].x * 2.4,
                                   -15.0, 15.0) + self.look_x * 3.0
                amp_q = round(amp_i * 2) / 2
                bkey = (wkey, bi, amp_q)
                band_warped = self._hair_warp_cache.get(bkey)
                if band_warped is None:
                    band_src_lit = self.warper.lit_for(band_img, depth_pose)
                    band_warped = self.warper.warp(
                        self.look_x, self.look_y, render_lean, 0.0,
                        render_squash, amp, bend=render_bend, pose=depth_pose,
                        source=band_src_lit, source_alpha_fixed=True,
                        lighting=False,
                        sway=(0.0, 0.0, amp_q, 0.0, 0.64 * self.spr2.height),
                        source_offset=(self.hair_off_s[0] + band_off[0],
                                       self.hair_off_s[1] + band_off[1]))
                    if len(self._hair_warp_cache) >= 24:
                        self._hair_warp_cache.popitem(last=False)
                    self._hair_warp_cache[bkey] = band_warped
                else:
                    self._hair_warp_cache.move_to_end(bkey)
                sprite.alpha_composite(band_warped,
                                       (self.hair_off_s[0] + band_off[0],
                                        self.hair_off_s[1] + band_off[1]))
        # 整圈结束视为零角度,收势时不再反复旋转整张图片或隐藏表情。
        _rot = (getattr(self, "_spin_rot", 0.0) + 180) % 360 - 180
        upright = sprite        # 叠好各图层、还没转的合成图:打滚贴地的参照
        if _rot:
            # 真旋转:整只绕画面中心转过去(陀螺式)。expand 画布会超出
            # 窗口,按窗口约束缩回来 —— 转到侧面时她略小一圈,像收手
            # 收裙摆,转完立刻恢复原大。
            sprite = sprite.rotate(_rot, Image.BILINEAR, expand=True)
            _s = min(frame.width / sprite.width, frame.height / sprite.height, 1.0)
            if _s < 1.0:
                sprite = sprite.resize((int(sprite.width * _s),
                                        int(sprite.height * _s)), Image.BILINEAR)
        # 横向按人物躯干对齐画布中心(新立绘帽檐向右伸很远,按图片中心
        # 居中身体会偏左);旋转中的图按扩出来的新宽度补同样的偏移
        paste_x = int(cx2 - sprite.width / 2
                      - (self._sprite_center_rel - 0.5) * upright.width)
        paste_y = int(feet2 - sprite.height
                      - (bob + micro_lift * self.scale
                         + getattr(self, "_spin_lift", 0.0)) * k)
        if self.state == "roll":
            # 参照必须是合成图:腿层切出底图后,只有底图的 warped 可见下沿比脚
            # 高 56 原画 px,拿它当参照一进 roll 整只就悬空,滚完再掉回地面
            paste_y += self._roll_ground_offset(sprite, upright)

        # 残影拖尾:动作期间每隔一帧留一张半透明快照,画在主体身后。
        # 快照在采集时就降好透明度,绘制阶段只做 paste,零逐帧点运算。
        if getattr(self, "_afterimage_on", False) and not art_on:
            if now - getattr(self, "_after_last", 0.0) > 0.066:
                self._after_last = now
                ghost = sprite.copy()
                ghost.putalpha(ghost.getchannel("A").point(
                    lambda v: v * 100 // 255))
                self._afters.append((ghost, paste_x, paste_y, now))
        if self._afters:
            self._afters = [a for a in self._afters if now - a[3] < 0.25]
        for ghost, ax, ay, born in self._afters:
            frame.paste(ghost, (ax, ay), ghost)

        if casting:
            # 光柱/逆光必须画在她身后 —— 画前面会在她脸上糊一层奶白
            self.cast_fx().draw_back(frame, d, cx2, circ_y * k,
                                     min(1.0, (now - self.magic_start) / 2.6))
        if self.state == "transform":
            transform_ribbons(d, cx2, feet2, self.spr2.width, self.spr2.height,
                                 now - self.transform_start, k, front=False)
        meditating = self.state == "meditate"
        orbit_items = (self._hat_orbit_screen(warped, sprite, paste_x, paste_y, _rot,
                                              render_lean, render_squash, render_bend, now)
                       if getattr(self, "hat_orbit", True) else ())
        back = None
        if art_on:
            # 原画秋千:星轨跟着帽子一起动(2.5D 帽子位移),远侧画在一张单独的
            # 底层里,合成时垫在她身后 —— 先被帽子挡住、再绕到前面来
            orbit_items = self._art_orbit_follow(orbit_items, k)
            back = self._art_back
            if back is None or back.size != frame.size:
                back = self._art_back = Image.new("RGBA", frame.size, (0, 0, 0, 0))
            else:
                back.paste((0, 0, 0, 0), (0, 0, back.width, back.height))
            if self._hat_fx_enabled_now():
                tip_x, tip_y = self._hat_fx_tip_screen(warped, sprite, paste_x, paste_y, _rot)
                self.gain_star(0, tip_x, tip_y, hat_fx=True, orbit_items=orbit_items,
                               now=now, thinking=self._hat_fx_thinking(now),
                               girl_box=(paste_x, paste_y,
                                         paste_x + sprite.width, paste_y + sprite.height))
            self._draw_hat_orbit(back, orbit_items, False)
        else:
            if self._hat_fx_enabled_now():
                tip_x, tip_y = self._hat_fx_tip_screen(warped, sprite, paste_x, paste_y, _rot)
                self.gain_star(0, tip_x, tip_y, hat_fx=True, orbit_items=orbit_items,
                               now=now, thinking=self._hat_fx_thinking(now),
                               girl_box=(paste_x, paste_y,
                                         paste_x + sprite.width, paste_y + sprite.height))
            self._draw_hat_orbit(frame, orbit_items, False)
        if meditating:
            self._draw_meditate_orbs(frame, now, k, "far")
        if self.state == "fly":
            # 画在立绘之前:速度线从她身后拖出来,不压在身上
            self._draw_speed_lines(d, cx2, paste_y + sprite.height * 0.55, k, now)
        if not art_on:
            frame.alpha_composite(sprite, (paste_x, paste_y))
        self._draw_hat_orbit(frame, orbit_items, True)
        if meditating:
            self._draw_meditate_orbs(frame, now, k, "near")
        lights_bottom = None
        if art_on:
            # 书上沿换算到这一帧(SS 帧坐标):原画 y → 立绘裁图 → 帧
            sa_ = self._scene_art
            gy0_, gy1_ = sa_.girl_bbox[1], sa_.girl_bbox[3]
            spr_h1 = self._spr_disp_h()
            lights_bottom = (self.FOOT_Y - spr_h1
                             + (sa_.bbox["book"][1] - gy0_) * spr_h1 / (gy1_ - gy0_)) * k
        self._draw_ai_lights(frame, now, paste_x, sprite.width, feet2, k, lights_bottom)
        self._draw_ai_chain(frame, now, paste_x, paste_y, sprite.width)
        # 落地态:卷轴区域换成窗口坐标(_chain_rect_local 是 SS 超采样帧坐标,
        # 原来直接当窗口坐标用,点击区比画面大一倍还偏到右下);没画卷轴就清掉
        lcr = getattr(self, "_chain_rect_local", None)
        self._chain_rect = tuple(v / SS for v in lcr) if lcr else None
        if self.state == "transform":
            transform_ribbons(d, cx2, feet2, self.spr2.width, self.spr2.height,
                                 now - self.transform_start, k, front=True)
        spr_left = paste_x / k
        spr_top1 = paste_y / k
        spr_w1 = sprite.width / k
        # 嘴的位置(画布像素):吃糖崩糖屑、喷嚏喷气都从这里出。每帧记,
        # 两次乘法,不用等到某个状态才有
        mrx, mry = self._mouth_rel
        self._mouth_xy = (spr_left + spr_w1 * mrx, spr_top1 + sprite.height / k * mry)

        if self.singing and not asleep:
            self._draw_singing_pose(frame, d, k, t, spr_left, spr_top1, spr_w1, sprite)
            if t * 1.0 + getattr(self, "_sing_started", 0) * 0 > self.next_sing_pulse:
                self.next_sing_pulse = now + 0.4
                self.circles.append(dict(born=now, life=0.45, rx=0.6, kind="cast"))
        elif not asleep and not _rot:
            if self.state == "wave" and now < getattr(self, "_wave_until", 0):
                self._draw_wave_arm(frame, d, k, now - self.wave_start, spr_left, spr_top1,
                                    spr_w1, sprite.height / k)

        if self.thinking_now and not asleep:
            sk = self.scale * k
            hx = cx2
            hy = paste_y - int(6 * self.scale) * k
            self.paste_glow(frame, hx, hy, int(24 * self.scale), MAGIC_B, 55)
            d.ellipse([hx - 22 * sk, hy - 22 * sk * 0.34, hx + 22 * sk, hy + 22 * sk * 0.34],
                      outline=MAGIC_B + (215,), width=int(1.5 * k))
            d.line(flat_star(hx, hy, 22 * sk, 0.34, 11 * sk, 4.5 * sk, rot=t * 2.2),
                   fill=MAGIC_A + (200,), width=int(1.3 * k), joint="curve")
            ph = int(t * 2.5) % 3
            for i in range(3):
                a = 235 if i == ph else 85
                r = (3.2 if i == ph else 2.1) * k
                dx = hx - 9 * k + i * 8 * k
                dy = hy - 26 * k
                d.ellipse([dx - r, dy - r, dx + r, dy + r], fill=GOLD_L + (a,))

        if asleep and not art_on:
            # 原画秋千/小屋里她不是这张精灵画的:按精灵轮廓叠的夜色会变成一层雾罩在她
            # 身上,角上的小月亮也会飘到屋檐上 —— 那里改由房间整体暗下来表达入睡
            sleep_alpha = 0.7 + 0.3 * math.sin(t * 1.3)
            # 叠加夜色,不能用精灵 alpha 把整只替换成低透明度的纯色。
            dim = self._sleep_shade(sprite, 40 * sleep_alpha)
            frame.alpha_composite(dim, (paste_x, paste_y))
            self.paste_glow(frame, 56 * k, 60 * k, 30, GOLD, 60)
            d.text((44 * k, 44 * k), "☾", fill=GOLD + (255,), font=self.f_moon)
            d.polygon(star_pts(88 * k, 46 * k, 6 * k, 2.6 * k), fill=GOLD_L + (230,))
            d.polygon(star_pts(38 * k, 96 * k, 5 * k, 2.2 * k, rot=0.6), fill=GOLD_L + (210,))

        self._draw_decors(frame, d, t, "front", dy, k)

        if casting:
            self.cast_fx().draw_front(frame, d, cx2, circ_y * k,
                                      min(1.0, (now - self.magic_start) / 2.6),
                                      self.fx.sig)

        if casting:
            age = now - self.magic_start
            self.paste_glow(frame, cx2, circ_y * k if not asleep else foot_base * k,
                            int(110 * self.scale), MAGIC_B, 46)
            kx, ky = int(52 * self.scale) * k, int(120 * self.scale) * k
            r = 26 * min(1.0, age / 0.3) * self.scale * k
            if r > 2:
                self.paste_glow(frame, kx, ky, 34, GOLD, 80)
                d.ellipse([kx - r, ky - r, kx + r, ky + r],
                          fill=(255, 248, 232, 235), outline=GOLD + (255,), width=int(2.4 * k))
                for i in range(12):
                    a = i * math.pi / 6
                    tx = kx + math.cos(a) * (r - 6 * k)
                    ty2 = ky + math.sin(a) * (r - 6 * k)
                    d.ellipse([tx - 1.4 * k, ty2 - 1.4 * k, tx + 1.4 * k, ty2 + 1.4 * k],
                              fill=INK + (255,))
                ha = -math.pi / 2 + t * 6
                ma = -math.pi / 2 + t * 11
                d.line([kx, ky, kx + math.cos(ha) * r * 0.45, ky + math.sin(ha) * r * 0.45],
                       fill=INK + (255,), width=int(2.6 * k))
                d.line([kx, ky, kx + math.cos(ma) * r * 0.68, ky + math.sin(ma) * r * 0.68],
                       fill=INK + (255,), width=int(2 * k))
                d.ellipse([kx - 3 * k, ky - 3 * k, kx + 3 * k, ky + 3 * k], fill=GOLD + (255,))
            self._tv_cat(d, t, k)

        if eating:
            age = now - self.eat_start
            # 轨迹与糖果共用一条曲线,不依赖帧率积累粒子。
            for i in range(5, -1, -1):
                sample_age = age - i * .045
                if sample_age <= 0:
                    continue
                px, py, visibility = self._candy_path(sample_age, self._mouth_rel)
                if visibility <= 0:
                    continue
                cx = (spr_left + spr_w1 * px) * k
                cy = (spr_top1 + sprite.height / k * py) * k
                radius = (13 if i == 0 else 2.2) * visibility * self.scale * k
                alpha = int((255 if i == 0 else 150 - i * 20) * visibility)
                if i == 0:
                    self.paste_glow(frame, cx, cy, int(14*self.scale*k), GOLD, int(90*visibility))
                d.polygon(star_pts(cx, cy, radius, radius * .45, rot=sample_age*2),
                          fill=GOLD + (alpha,))
            # 吞下糖果后,两侧的小星星随满足的点头淡出。
            glint = max(0.0, 1 - abs(age - 1.45) / .35)
            if glint > 0:
                for side in (-1, 1):
                    cx = (spr_left + spr_w1*(self._mouth_rel[0]+side*.14)) * k
                    cy = (spr_top1 + sprite.height/k*.56) * k
                    r = (4.5 + 3*glint)*self.scale*k
                    d.polygon(star_pts(cx, cy, r, r*.3, rot=.2), fill=GOLD_L+(int(210*glint),))

        # 时之魔法演出(时停/回溯):fx 预渲染叠加层,pet.py 侧只留这一个钩子
        tfx = getattr(self, "tfx", None)
        if tfx:
            tfx.draw(frame, d, cx2, (foot_base + 8 * self.scale) * k, k, now)

        # 一次性魔法阵
        for cfx in self.circles:
            age = now - cfx["born"]
            p = age / cfx["life"]
            scale = min(1.0, age / 0.25)
            if p > 0.7:
                scale *= max(0.0, (1 - p) / 0.3)
            rx = cfx["rx"] * 88 * self.scale * scale
            if rx < 2:
                continue
            ry = rx * 0.26
            spin = t * 3.0 if cfx["kind"] == "cast" else t * 1.6
            col = MAGIC_A if cfx["kind"] == "cast" else MAGIC_B
            a2 = int(220 * (1 - p) + 35)
            cy3 = (foot_base + 8 * self.scale) * k
            d.ellipse([cx2 - rx * k, cy3 - ry * k, cx2 + rx * k, cy3 + ry * k],
                      outline=col + (a2,), width=int(2.2 * k))
            d.line(flat_star(cx2, cy3, rx * k, 0.26, rx * 0.55 * k, rx * 0.24 * k, rot=spin),
                   fill=MAGIC_B + (a2,), width=int(1.6 * k), joint="curve")

        # 落地冲击波(land_fx 登记,这里画):fx 预渲染的阶梯半径,零缩放开销
        for sk in self._shocks:
            p = (now - sk["born"]) / 0.45
            if 0 <= p <= 1:
                self.fx.shockwave(frame, cx2, (foot_base + 8 * self.scale) * k,
                                  p, strength=sk["strength"])

        # 粒子
        for p in self.parts:
            age = now - p["born"]
            if age < 0:
                continue
            kk = age / p["life"]
            px = (p["x"]) * k
            py = (p["y"]) * k + p["vy"] * age * k + 0.5 * p["grav"] * age * age * k
            px += p["vx"] * age * k
            col = p["color"]
            if p["kind"] == "puff":
                self.fx.puff_at(frame, px, py, kk)
            elif p["kind"] == "gain":
                # 前 0.12 秒淡入,末 40% 淡出;字形全是预渲染贴图,只排版不画字
                vis = min(1.0, age / 0.12, (1.0 - kk) / 0.4)
                self.fx.gain_text(frame, px, py, p.get("txt") or "", vis)
            elif p["kind"] == "hit_ring":
                # 不跟随 vx/vy:光环钉在点中的那个位置上
                self.fx.hit_ring(frame, p["x"] * k, p["y"] * k, kk, p.get("txt") or "gold")
            elif p["kind"] == "heart":
                s = p["size"] * (1 - kk * 0.45) * k
                sway = math.sin(p["phase"] + age * 5) * 8
                a2 = int(255 * (1 - kk * 0.7))
                d.polygon(heart_pts(px + sway * k, py, s), fill=HEART_C + (a2,))
            elif p["kind"] == "magic_burst":
                r = (p["size"] + (now - p["born"]) * 380) * k
                if r > 0:
                    a2 = max(0, int(255 * (1 - (now - p["born"]) / max(0.1, p["life"]))))
                    d.ellipse([W / 2 * k - r, H * 0.45 * k - r * 0.55,
                               W / 2 * k + r, H * 0.45 * k + r * 0.55],
                              outline=p["color"] + (a2,),
                              width=max(1, int(3 * k)))
                    if a2 > 80:
                        d.ellipse([W / 2 * k - r * 0.85, H * 0.45 * k - r * 0.48,
                                   W / 2 * k + r * 0.85, H * 0.45 * k + r * 0.48],
                                  outline=(255, 255, 255, int(a2 * 0.4)),
                                  width=max(1, int(1.2 * k)))
            elif p["kind"] == "magic_corner":
                r = p["size"] * (1.2 - (now - p["born"]) * 0.3) * k
                if r > 0:
                    a2 = max(0, int(255 * (1 - (now - p["born"]) / max(0.1, p["life"]))))
                    d.ellipse([px - r, py - r, px + r, py + r],
                              fill=p["color"] + (a2,),
                              outline=(255, 255, 255, a2), width=max(1, int(2 * k)))
                    self.glow_lit(px, py, int(r * 3), p["color"], int(a2 * 0.7))
            elif p["kind"] == "ball":
                # 动态球已由固定步长推进,不能再套一次通用粒子的速度×年龄。
                px, py = p['x']*k, p['y']*k
                bf = tail_fade(kk)
                trail = p.get('trail', [])
                for i, (tx, ty) in enumerate(trail):
                    r = (1+i*.4)*self.scale*k
                    d.ellipse([tx*k-r, ty*k-r, tx*k+r, ty*k+r],
                              fill=GOLD_L+(int((25+i*14)*bf),))
                r = 7*self.scale*k
                self.glow_lit(px, py, int(18*self.scale*k), GOLD_L, int(85*bf))
                d.ellipse([px-r, py-r, px+r, py+r], fill=(245, 237, 255, int(245*bf)),
                          outline=GOLD_L+(int(255*bf),), width=max(1, int(k)))
                d.polygon(star_pts(px, py, r*.58, r*.2, n=4, rot=age),
                          fill=(157, 130, 222, int(240*bf)))
            elif p['kind'] == 'ball_ring':
                r = p['size']*(.3+.7*kk)*k
                d.ellipse([px-r, py-r*.22, px+r, py+r*.22],
                          outline=GOLD_L+(max(0, int(160*(1-kk))),), width=max(1, int(k)))
            elif p["kind"] == "sparkle":
                s = p["size"] * math.sin(math.pi * min(1.0, kk)) * k
                if s < 1:
                    continue
                rot = p["phase"] + age * 3
                a2 = int(235 * (1 - kk * 0.5))
                d.polygon(star_pts(px, py, s, s * 0.3, n=4, rot=rot), fill=col + (a2,))
            elif p["kind"] == "star":
                s = p["size"] * (1 - 0.6 * kk) * k
                rot = p["phase"] + p["spin"] * age
                a2 = int(240 * (1 - kk * 0.6))
                if s > 6 * k:
                    self.glow_lit(px, py, int(s) + 8, col, 40)
                d.polygon(star_pts(px, py, s, s * 0.45, rot=rot), fill=col + (a2,))
            elif p["kind"] == "cstar":
                # 可捕捉的金星星:脉冲发光提示"点我"
                s = p["size"] * (1.0 + 0.18 * math.sin(age * 6)) * k
                rot = p["phase"] + p["spin"] * age
                self.glow_lit(px, py, int(s) + 12, GOLD_L, 70)
                d.polygon(star_pts(px, py, s, s * 0.5, n=5, rot=rot),
                          fill=(255, 233, 160, 245), outline=(242, 193, 78, 255))
            elif p["kind"] == "gear":
                # 时之魔女的小齿轮:转着飘/弹走,末段缩小消散
                s = p["size"] * (1 - 0.45 * kk) * k
                if s < 2:
                    continue
                rot = p["phase"] + p["spin"] * age
                a2 = int(235 * (1 - kk * 0.55))
                self.glow_lit(px, py, int(s * 1.7) + 6, GOLD_L, 45)
                d.polygon(gear_pts(px, py, s, 8, rot),
                          outline=GOLD_L + (a2,), width=max(1, int(1.3 * k)))
                d.ellipse([px - s * 0.55, py - s * 0.55,
                           px + s * 0.55, py + s * 0.55],
                          outline=GOLD_L + (a2,), width=max(1, int(1.0 * k)))
                d.ellipse([px - s * 0.11, py - s * 0.11,
                           px + s * 0.11, py + s * 0.11], fill=GOLD + (a2,))
            elif p["kind"] == "dial":
                # 悬在头顶的表盘虚影:淡入淡出,指针倒着走(时间倒流的意象)
                s = p["size"] * min(1.0, age / 0.25) * (1 - 0.25 * kk) * k
                if s < 2:
                    continue
                a2 = max(0, int(205 * math.sin(math.pi * min(1.0, kk))))
                if a2 < 8:
                    continue
                d.ellipse([px - s, py - s, px + s, py + s],
                          outline=MAGIC_A + (a2,), width=max(1, int(1.5 * k)))
                d.ellipse([px - s * 0.70, py - s * 0.70,
                           px + s * 0.70, py + s * 0.70],
                          outline=MAGIC_B + (int(a2 * 0.55),),
                          width=max(1, int(0.8 * k)))
                for i in range(12):
                    ta = p["phase"] + math.pi * i / 6
                    d.line([px + math.cos(ta) * s * 0.86,
                            py + math.sin(ta) * s * 0.86,
                            px + math.cos(ta) * s * 0.70,
                            py + math.sin(ta) * s * 0.70],
                           fill=MAGIC_A + (a2,), width=max(1, int(1.0 * k)))
                spin = p.get("spin", 2.0)
                ha = p["phase"] - age * spin          # 倒转的时针/分针
                ma = p["phase"] - age * spin * 2.6
                d.line([px, py, px + math.cos(ha) * s * 0.40,
                        py + math.sin(ha) * s * 0.40],
                       fill=INK + (a2,), width=max(1, int(2.0 * k)))
                d.line([px, py, px + math.cos(ma) * s * 0.62,
                        py + math.sin(ma) * s * 0.62],
                       fill=INK + (a2,), width=max(1, int(1.4 * k)))
                d.ellipse([px - 1.6 * k, py - 1.6 * k,
                           px + 1.6 * k, py + 1.6 * k], fill=GOLD + (a2,))
            elif p["kind"] == "bub":
                r = p["size"] * (1 + 0.1 * math.sin(age * 4 + p["phase"])) * k
                sway = math.sin(age * 2.6 + p["phase"]) * 9 * k
                a2 = int(200 * (1 - kk * 0.35))
                d.ellipse([px + sway - r, py - r, px + sway + r, py + r],
                          outline=(196, 228, 255, a2), width=max(1, int(1.6 * k)))
                d.ellipse([px + sway - r * 0.45, py - r * 0.55,
                           px + sway - r * 0.05, py - r * 0.15],
                          fill=(235, 248, 255, int(a2 * 0.8)))
                if kk > 0.86:   # 末端"啵":撑大的一圈消散光环
                    pr = r * (1 + (kk - 0.86) * 6)
                    pa = int(160 * (1 - (kk - 0.86) / 0.14))
                    d.ellipse([px + sway - pr, py - pr, px + sway + pr, py + pr],
                              outline=(210, 238, 255, pa), width=max(1, int(1.4 * k)))
            elif p["kind"] == "meteor":
                tx, ty = px - p["vx"] * 0.16 * k, py - p["vy"] * 0.16 * k
                d.line([tx, ty, px, py], fill=(255, 240, 200, 90),
                       width=max(1, int(3.5 * k)))
                d.line([px - p["vx"] * 0.05 * k, py - p["vy"] * 0.05 * k, px, py],
                       fill=(255, 252, 235, 235), width=max(1, int(1.8 * k)))
                self.glow_lit(px, py, int(10 * k), GOLD_L, 120)
            elif p["kind"] == "petal":
                s = p["size"] * k
                rot = p["phase"] + p["spin"] * age * 1.4
                sway = math.sin(age * 2.1 + p["phase"]) * 16 * k
                ca, sa = math.cos(rot), math.sin(rot)
                pts = [(px + sway + dx * ca - dy * sa, py + dx * sa + dy * ca)
                       for dx, dy in ((-s, 0), (0, -s * 0.6),
                                      (s, 0), (0, s * 0.6))]
                a2 = int(240 * (1 - kk * 0.45))
                d.polygon(pts, fill=p["color"] + (a2,))
            elif p["kind"] == "fw":
                kk2 = max(0.0, min(1.0, (now - p["born"]) / max(0.01, p["life"])))
                # 升空阶段:细长亮线
                if kk2 < 0.6:
                    ty = p["y"] + p["vy"] * (now - p["born"]) * k
                    a2 = int(255 * (1 - kk2 * 0.4))
                    d.ellipse([p["x"] - 1.5 * k, ty - 2 * k,
                               p["x"] + 1.5 * k, ty + 2 * k],
                              fill=p["color"] + (a2,))
                # 爆开阶段:8 颗彩点向外飞
                else:
                    p2 = (kk2 - 0.6) / 0.4
                    for j in range(8):
                        a = j * (math.pi * 2 / 8) + p["phase"]
                        r = p2 * 60 * k
                        fx = p["x"] + math.cos(a) * r
                        fy = p["y"] + math.sin(a) * r
                        sz = max(0.6, 3.5 * (1 - p2)) * k
                        a2 = int(255 * (1 - p2))
                        d.ellipse([fx - sz, fy - sz, fx + sz, fy + sz],
                                  fill=p["color"] + (a2,))
            elif p["kind"] == "sweat":
                r = p["size"] * k
                d.ellipse([px - r, py - r, px + r, py + r],
                          fill=(180, 220, 255, int(200 * tail_fade(kk))))
            elif p["kind"] == "firefly":
                r = p["size"] * k
                pulse = 0.45 + 0.55 * abs(math.sin(age * 2.2 + p["phase"]))
                self.glow_lit(px, py, int(r * 5), (220, 240, 140),
                              int(150 * pulse))
                d.ellipse([px - r, py - r, px + r, py + r],
                          fill=(240, 255, 180, int(230 * pulse)))
            elif p["kind"] == "leaf":
                s = p["size"] * k
                rot = p["phase"] + p["spin"] * age
                sway = math.sin(age * 1.8 + p["phase"]) * 14 * k
                ca, sa = math.cos(rot), math.sin(rot)
                pts = [(px + sway + dx * ca - dy * sa, py + dx * sa + dy * ca)
                       for dx, dy in ((-s, -s * 0.45), (s, -s * 0.3),
                                      (s * 0.4, s * 0.5), (-s * 0.5, s * 0.4))]
                a2 = int(235 * (1 - kk * 0.4))
                d.polygon(pts, fill=p["color"] + (a2,),
                          outline=(120, 70, 40, int(a2 * 0.7)))
            elif p["kind"] == "snow":
                r = p["size"] * k
                sway = math.sin(age * 1.5 + p["phase"]) * 10 * k
                tw = 0.7 + 0.3 * math.sin(age * 5 + p["phase"])
                d.ellipse([px + sway - r, py - r, px + sway + r, py + r],
                          fill=(245, 248, 255, int(210 * tw * tail_fade(kk))))
            elif p["kind"] == "confetti":
                w2, h2 = p["size"] * k, p["size"] * 0.55 * k
                rot = p["phase"] + p["spin"] * age
                ca, sa = math.cos(rot), math.sin(rot)
                pts = [(px + dx * ca - dy * sa, py + dx * sa + dy * ca)
                       for dx, dy in ((-w2, -h2), (w2, -h2), (w2, h2), (-w2, h2))]
                a2 = int(255 * (1 - kk * 0.7))
                d.polygon(pts, fill=p["color"] + (a2,))
            elif p["kind"] == "zzz":
                s = int((p["size"] + 10 * kk) * self.scale)
                a2 = int(235 * (1 - kk * 0.6))
                d.text((px + 12 * kk * k, py), "Z", fill=(143, 167, 201, a2),
                       font=self._font(s))
            elif p["kind"] == "note":
                sway = math.sin(p["phase"] + age * 4) * 10
                a2 = int(240 * (1 - kk * 0.5))
                sz = int((11 + 4 * math.sin(age * 6)) * self.scale)
                d.text((px + sway * k, py), p.get("txt") or "♪",
                       fill=(255, 214, 120, a2), font=self._font(sz, sym=True))

        # 攒了一整轮的粒子光晕在这里一次性加色合成回主帧。放在贴纸和气泡
        # 之前:光可以盖在她身上,但不能糊住要读的字。
        light.flush(frame)

        # 表情贴纸
        if self.sticker:
            self._draw_sticker(frame, d, now, k, spr_left, spr_top1, spr_w1, warped)

        # 气泡底图与排版缓存,只有小图的透明度随时间变化。
        if self.bubble and now < self.bubble[1]:
            art = self._bubble_sprite(k)
            alpha = self._bubble_alpha(now)
            if alpha < 1:
                art = art.copy()
                art.putalpha(art.getchannel('A').point(lambda v: int(v*alpha)))
            # 气泡本体仍落在原来的位置(画布外圈是投影)
            self._ac(frame, art, cx2-art.width/2, 8*k - getattr(self, "_bubble_pad", 0))

        # 整数倍降采样用 reduce():精确 2x2 均值,正是超采样该有的解析方式。
        # 实测 1290x1560 -> 645x780,BILINEAR 约 23ms,reduce(2) 约 7.5ms。
        # 在预乘模式(RGBa)下降采样:reduce 对 RGBA 内部本来就要先预乘、缩完
        # 再还原,推帧时又得再预乘一次。直接在 RGBa 里缩,缩完的字节就是
        # UpdateLayeredWindow 要的预乘数据,省掉"还原 + 再预乘"两趟整帧转换
        # (实测 1290x1560 源帧:10.0ms -> 6.7ms,误差 <=1 级舍入)。在预乘域
        # 求均值也正是半透明边缘该有的合成方式。
        if frame.width == W * SS and frame.height == H * SS:
            small = frame.convert("RGBa").reduce(SS)
        else:
            small = frame.resize((W, H), Image.BILINEAR)
        if art_on and back is not None:
            self._art_small_back = (back.convert("RGBa").reduce(SS)
                                    if back.size == (W * SS, H * SS)
                                    else back.resize((W, H), Image.BILINEAR))
        else:
            self._art_small_back = None
        if self.selftest and now - self.t0 > 1.6 and not self.snap_done:
            self.snap_done = True
            small.convert("RGBA").save(os.path.join(HERE, "_preview_idle.png"))
        # 只推与窗口物理尺寸一致的这一帧;
        # 再推一次 SS 倍的超采样帧会把分层窗口撑成 2 倍大。
        if self.state == "swing" and self._swing:
            self._push_swing(small)   # 前后荡:场景画布推送
            # 原画秋千模式下渲染帧里没有她(她在场景原画里):自检预览存整张场景
            if (self.selftest and self._swing.get("art") and self.snap_done
                    and not getattr(self, "_scene_snap_done", False)
                    and self._swing.get("scene_canvas") is not None):
                self._scene_snap_done = True
                self._swing["scene_canvas"].save(os.path.join(HERE, "_preview_idle.png"))
            return
        self._push(small)

    def _bubble_alpha(self, now):
        if not self.bubble:
            return 0.0
        return max(0.0, min(1.0, (now-self._bubble_born)/.12,
                            (self.bubble[1]-now)/.18))

    def _bubble_sprite(self, k):
        txt = self.bubble[0]
        key = (txt, id(self.f_bubble), self.W, self.H, k)
        if self._bubble_art and self._bubble_art[0] == key:
            return self._bubble_art[1]
        import apple_ui as A
        fnt = A.font(getattr(self.f_bubble, 'size', round(15 * k)), 430)
        lines, lh, tw = self._bubble_layout(txt, fnt, k)
        bw, bh = int(math.ceil(tw+30*k)), int(math.ceil(lh*len(lines)+16*k))
        # 质感版:石墨色圆角气泡 + 白色细边 + 柔和投影(和状态胶囊同一材质),不再是紫底金边
        pad = int(8*k)
        art = Image.new('RGBA', (bw + 2*pad, bh + 2*pad + int(7*k)), (0, 0, 0, 0))
        center = art.width/2
        shade = Image.new('L', art.size, 0)
        ImageDraw.Draw(shade).rounded_rectangle((pad, pad + 2*k, pad + bw, pad + bh + 2*k),
                                                radius=int(min(bh / 2, 16*k)), fill=70)
        shadow = Image.new('RGBA', art.size, (0, 0, 0, 0))
        shadow.putalpha(shade.filter(ImageFilter.GaussianBlur(4*k)))
        art.alpha_composite(shadow)
        d = ImageDraw.Draw(art)
        fill, edge = A.BG + (244,), A.HAIR
        d.rounded_rectangle((pad, pad, pad + bw - 1, pad + bh - 1), radius=int(min(bh / 2, 16*k)),
                            fill=fill, outline=edge, width=max(1, int(k)))
        tail = [(center - 7*k, pad + bh - 2*k), (center + 7*k, pad + bh - 2*k), (center, pad + bh + 6*k)]
        d.polygon(tail, fill=fill)
        for i, line in enumerate(lines):
            d.text((center-tw/2, pad+8*k+i*lh), line, fill=A.TEXT + (255,), font=fnt)
        self._bubble_pad = pad
        self._bubble_art = (key, art)
        return art

    def _bubble_layout(self, txt, fnt, k):
        """气泡排版:断行 + 按窗口高度夹取行数。返回 (行列表, 行高, 文本宽)。

        原来 bh 没有任何上限,而 frame 只有 H*SS 高 —— 长回复会从窗口底部
        被静默裁掉。气泡最多吃掉窗口上方 42%,再往下就糊到她脸上了。
        超出的部分截断加省略号:AI 长回复的完整文本本来就同时写进了聊天
        面板,气泡只是"她说了句话"的提示,不是阅读界面。

        结果按 (文本, 字体, 窗宽) 缓存:气泡活着的时候这些都不变,原来
        每帧都把整段文本的 getlength 重跑一遍。
        """
        key = (txt, id(fnt), self.W)
        hit = self._bubble_lay.get(key)
        if hit is not None:
            return hit
        lines = self._wrap_text(txt, fnt, self.W * 0.78 * k)
        lh = fnt.size + 4 * k
        max_lines = max(1, int((self.H * 0.42 * k - 14 * k) / lh))
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1][:-1] + "…"
        res = (lines, lh, max(fnt.getlength(ln) for ln in lines))
        if len(self._bubble_lay) > 12:
            self._bubble_lay.clear()
        self._bubble_lay[key] = res
        return res

    def _wrap_text(self, text, fnt, max_w):
        """简易按字符断行,中文按字符宽度估算"""
        lines = []
        cur = ""
        for ch in text:
            trial = cur + ch
            if fnt.getlength(trial) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = ch
        if cur:
            lines.append(cur)
        return lines or [""]

    def _draw_singing_mouth(self, d, x, y, t, k):
        kk = abs(math.sin(t * 5.0))
        w = (4 + 6 * kk) * k
        h = (2.5 + 7 * kk) * k
        d.ellipse([x - w, y - h, x + w, y + h],
                  fill=(180, 60, 90, 250), outline=INK + (200,),
                  width=max(1, int(0.8 * k)))

    def _draw_wave_arm(self, frame, d, k, t, spr_left, spr_top1, spr_w1, spr_h1):
        """星光从立绘抬起的手旁划过,随挥拍摆动并淡出,不再额外画一条手臂。"""
        envelope = self._track(t, [(0, 0), (.3, 1), (2.15, 1), (2.6, 0)])
        if envelope <= 0:
            return
        def point(at):
            hx_, hy_ = self.cfg.get("wave_hand", (.71, .40))
            return ((spr_left + spr_w1 * (hx_ + .055 * math.sin(at * 10.47))) * k,
                    (spr_top1 + spr_h1 * (hy_ - .035 * math.cos(at * 10.47))) * k)
        points = [point(max(0, t - .24 + i * .024)) for i in range(11)]
        for i in range(10):
            alpha = int(150 * envelope * (i + 1) / 10)
            d.line([points[i], points[i + 1]], fill=GOLD_L + (alpha,),
                   width=max(1, int(1.6 * self.scale * k)))
        hx, hy = points[-1]
        r = (3 + 2 * envelope) * self.scale * k
        self.paste_glow(frame, hx, hy, int(12 * self.scale), GOLD_L, int(80 * envelope))
        d.polygon(star_pts(hx, hy, r, r * .42, rot=t * 3),
                  fill=GOLD_L + (int(240 * envelope),))

    def _draw_mouth(self, style, d, x, y, t, k):
        """表情嘴(复用唱歌嘴的画法):laugh=哈哈大笑(张嘴+弹跳),
        wow=O 形惊讶,chew=咀嚼。由 self._mouth=(style, until) 驱动,
        渲染帧里检查到期自动熄灭;唱歌/旋转期间让位,不画。"""
        if style == "laugh":
            w = 8 * k
            h = (5 + 6 * abs(math.sin(t * 13))) * k
            d.ellipse([x - w, y - h * 0.7, x + w, y + h],
                      fill=(180, 60, 90, 250), outline=INK + (210,),
                      width=max(1, int(0.9 * k)))
            d.pieslice([x - w * 0.72, y - h * 0.55, x + w * 0.72, y + h * 0.75],
                       0, 180, fill=(255, 170, 180, 200))     # 小舌头
        elif style == "wow":
            r = 5.5 * k
            d.ellipse([x - r, y - r * 1.25, x + r, y + r * 1.25],
                      fill=(120, 50, 75, 250), outline=INK + (210,),
                      width=max(1, int(0.9 * k)))
        elif style == "chew":
            kk = abs(math.sin(t * 9.0))
            w = (6 - 3 * kk) * k
            h = (3.5 - 2 * kk) * k
            d.ellipse([x - w, y - h, x + w, y + h],
                      fill=(180, 60, 90, 240), outline=INK + (200,),
                      width=max(1, int(0.8 * k)))

    def _draw_singing_pose(self, frame, d, k, t, spr_left, spr_top1, spr_w1, warped):
        mic_y = spr_top1 + warped.height / k * 0.34
        sway = math.sin(t * 3.2) * 3 * self.scale
        arms = self.cfg.get("sing_arms", True)
        for sgn in (-1, 1):
            mx = spr_left + spr_w1 * (0.43 + sgn * 0.06) + sway * sgn
            my = mic_y + abs(math.sin(t * 4.5)) * 2 * self.scale
            if arms:
                # 两条"手臂"按旧立绘的肩位画;新立绘(握绳/搭膝)不画,只留星光
                d.line([(spr_left + spr_w1 * (0.39 + sgn * 0.05)) * k,
                        (spr_top1 + warped.height / k * 0.50) * k,
                        mx * k, my * k],
                       fill=(255, 240, 225, 240), width=int(6 * self.scale * k))
            self.paste_glow(frame, mx * k, my * k,
                            int(18 * self.scale), GOLD_L, 110)
            r = 7 * self.scale * k
            rot = t * 1.6
            d.polygon(star_pts(mx * k, my * k, r, r * 0.42, rot=rot),
                      fill=GOLD + (255,), outline=(200, 149, 48, 255))

    @staticmethod
    def _orbit_spin_target(state):
        return {"sleep": 0.0, "tstop": 0.0, "magic": 2.4, "rewind": -2.2}.get(state, 1.0)

    @staticmethod
    def _hat_orbit_layout(orbit_t):
        """帽檐星轨此刻的布局(原画归一化坐标 0..1)。

        返回 [(名字或 None, nx, ny, 远近 depth 0..1, 近侧?, 轨迹点透明度)],
        名字为 None 的是轨迹点。近侧 = 椭圆靠观众的下半圈(局部 sin>0)。"""
        cx, cy, a, b, tilt = HAT_ORBIT
        aw, ah = HAT_ORBIT_ART
        ct, st = math.cos(math.radians(tilt)), math.sin(math.radians(tilt))
        # 轨道本身:中圈画一圈固定不动的淡虚点,天体不在那儿时也看得出是
        # "绕着帽子的一条轨道"。名字 "path" 和轨迹点区分开。静态几何只算一次
        # —— 第一版每帧重算 40 个点的三角函数,剖析里待机多出来的一截主要在这
        if not _HAT_PATH_CACHE:
            for i in range(HAT_ORBIT_PATH):
                ang = 2 * math.pi * i / HAT_ORBIT_PATH
                lx, ly = a * math.cos(ang), b * math.sin(ang)
                sn = math.sin(ang)
                _HAT_PATH_CACHE.append(("path", (cx + lx * ct - ly * st) / aw,
                                        (cy + lx * st + ly * ct) / ah, (sn + 1) / 2, sn > 0, 0.0))
        out = list(_HAT_PATH_CACHE)
        for name, k, period, phase in HAT_ORBIT_BODIES:
            ang0 = phase + orbit_t * 2 * math.pi / period
            for j in range(HAT_ORBIT_TRAIL + 1):
                ang = ang0 - j * HAT_ORBIT_TRAIL_GAP
                lx, ly = a * k * math.cos(ang), b * k * math.sin(ang)
                x, y = cx + lx * ct - ly * st, cy + lx * st + ly * ct
                sn = math.sin(ang)
                out.append((name if j == 0 else None, x / aw, y / ah, (sn + 1) / 2, sn > 0,
                            1.0 - j / (HAT_ORBIT_TRAIL + 1)))
        return out

    @staticmethod
    def _orbit_follow(x, y, w, pivot_y, lean, squash, bend):
        """变形网格把原画上 (x, y) 这一点挪了多少(像素)。

        照 DepthWarp.displacement 的全局项(倾斜/弓身/挤压)算,权重和取 1。
        实测(scratchpad orbit_follow_probe):倾斜、弓身逐像素吻合;挤压被网格
        的防翻折增益压到约七成,所以挤压项乘 0.72。不跟的话挥手倾斜 0.115 时
        帽子挪了 30px,星轨还留在原地。"""
        h = pivot_y if pivot_y else 1.0
        ar = (pivot_y - y) / max(1.0, h)
        dx = -math.tan(max(-.5, min(.5, lean))) * .5 * (y - pivot_y) + bend * .22 * w * ar * ar
        sq = max(.6, min(1.4, squash))
        dx += (x - w / 2) * (sq - 1) * 0.72
        dy = (pivot_y - y) * (1 / sq - 1) * 0.72
        return dx, dy

    @staticmethod
    def _rotate_about(dx, dy, rot_deg):
        """和 Image.rotate(rot_deg) 同向(逆时针为正,y 轴朝下)转一个相对中心的点。"""
        a = math.radians(rot_deg)
        ca, sa = math.cos(a), math.sin(a)
        return dx * ca + dy * sa, -dx * sa + dy * ca

    def _hat_orbit_screen(self, warped, sprite, paste_x, paste_y, rot, lean, squash, bend, now):
        """布局换到画布坐标(2x):跟随变形、整只旋转、bob/腾空(paste 已含)。"""
        w, h = warped.size
        cxw = HAT_ORBIT[0] / HAT_ORBIT_ART[0] * w
        cyw = HAT_ORBIT[1] / HAT_ORBIT_ART[1] * h
        fdx, fdy = self._orbit_follow(cxw, cyw, w, getattr(self.warper, "pivot_y", h),
                                      lean, squash, bend)
        if rot:
            a = math.radians(rot)
            ew = abs(w * math.cos(a)) + abs(h * math.sin(a))
            sc = sprite.width / ew if ew else 1.0
            ocx, ocy = paste_x + sprite.width / 2, paste_y + sprite.height / 2
        out = []
        for name, nx, ny, depth, near, level in self._hat_orbit_layout(
                getattr(self, "_orbit_t", 0.0)):
            px, py = nx * w + fdx, ny * h + fdy
            if rot:
                rx, ry = self._rotate_about(px - w / 2, py - h / 2, rot)
                X, Y = ocx + rx * sc, ocy + ry * sc
            else:
                X, Y = paste_x + px, paste_y + py
            out.append((name, X, Y, depth, near, level))
        return out

    def _hat_fx_enabled_now(self):
        return (getattr(self, '_hat_fx_enabled', True)
                and not getattr(self, 'ui_reduced_anim', False)
                and getattr(getattr(self, 'fx', None), 'hat', None) is not None)

    def _hat_fx_thinking(self, now):
        # Outside the explicitly marked debug demo, ONLY ai_thinking drives A2.
        return bool(getattr(self, 'ai_thinking', False) or
                    (DEBUG_STATE and now < getattr(self, '_hat_fx_demo_until', 0)
                     and getattr(self, '_hat_fx_demo_thinking', False)))

    def _hat_fx_tip_screen(self, warped, sprite, paste_x, paste_y, rot):
        nx, ny = getattr(self, '_hat_fx_tip_uv', (.64, .003))
        sw, sa = getattr(self, '_swing', None), getattr(self, '_scene_art', None)
        if sw and sw.get('art') and sa is not None:
            geo=sw['geo'];gx0,gy0,gx1,gy1=sa.girl_bbox;k=geo['k']
            x,y=gx0+nx*(gx1-gx0),gy0+ny*(gy1-gy0)
            phase=round(sw.get('theta',0)/.008)*.008
            pose=self._art_pose(phase)
            if pose:
                dx,dy=sa.pose_displacement(x,y,pose);x+=dx;y+=dy
            x,y=sa.fwd(sa.swing_geometry(k),x*k,y*k,phase,SWING_PERSP)
            ox,oy,ss=self._art_small_map(sw)
            return (x-geo['O'][0]-ox)/ss*SS,(y-geo['O'][1]-oy)/ss*SS
        x,y=nx*warped.width,ny*warped.height
        if rot:
            rx,ry=self._rotate_about(x-warped.width/2,y-warped.height/2,rot)
            return paste_x+sprite.width/2+rx,paste_y+sprite.height/2+ry
        return paste_x+x,paste_y+y

    def _configure_hat_fx_demo(self, spec, seconds):
        # Visual-only fixture: no AI request, conversation, quota or saved state changes.
        if not hasattr(self, '_hat_fx_demo_saved'):
            sw=getattr(self, '_swing', None) or {}
            self._hat_fx_demo_saved=(sw.get('scene_scale',1),getattr(self,'_hat_fx_enabled',True))
        token=getattr(self,'_hat_fx_demo_token',0)+1;self._hat_fx_demo_token=token
        self._hat_fx_demo_until=time.time()+max(0,seconds)
        self._hat_fx_demo_thinking=bool(spec.get('thinking'))
        self._hat_fx_enabled=bool(spec.get('enabled',True))
        if getattr(self.fx,'hat',None) is not None:self.fx.hat.clear()
        self._flat_cache=None
        if self._swing:self._art_regeo(self._swing,max(.5,min(1.1,float(spec.get('scale',1)))))
        def restore():
            if token!=self._hat_fx_demo_token:return
            scale,enabled=self._hat_fx_demo_saved;del self._hat_fx_demo_saved
            self._hat_fx_demo_until=0;self._hat_fx_demo_thinking=False;self._hat_fx_enabled=enabled
            self._demo_until=0;self._flat_cache=None
            if self._swing:self._art_regeo(self._swing,scale)
        self.root.after(max(1,round(seconds*1000)),restore)

    def _draw_hat_orbit(self, frame, items, near_side):
        """远侧在立绘之前画(被帽子和头发挡住),近侧在立绘之后画。

        一帧要贴五十多个小点,这里直接从 fx 的精灵表里取图贴,不再每个点
        经过 orbit_dot -> _paste_c 两层调用(待机常驻,省的是 Python 调用开销)。"""
        layer = self.fx
        dots = layer.orbit_dots
        nd = layer.ORBIT_DOT_STEPS
        hat = getattr(layer, "hat", None) if self._hat_fx_enabled_now() else None
        if hat is not None and not near_side:
            hat.draw(frame)  # all new dust is behind the character silhouette
        paste = frame.paste
        for name, X, Y, depth, near, level in items:
            if near != near_side:
                continue
            if name is None and hat is not None:
                continue  # replace the old six dots, do not stack another trail
            if name is None or name == "path":
                lv = (0.28 + 0.22 * depth) if name else level * (0.45 + 0.55 * depth)
                i = int(lv * nd) - 1
                if i < 0:
                    continue
                sp = dots[min(i, nd - 1)]
                paste(sp, (int(X - sp.width / 2), int(Y - sp.height / 2)), sp)
            else:
                layer.orbit_body(frame, X, Y, name, depth)

    def _speed_line_specs(self, now):
        """速度线的几何:[(起点偏移, 终点偏移, 透明度)],偏移是相对身体中心的
        画布像素(1x)。E27 的星星拖尾在高速时 0.2 秒就飞出窗口,只剩一小截
        点线;速度线直接画在身后、长度随速度伸缩,高速时反而最明显。

        每 50ms 换一组随机位置(按时间片播种,不存状态),线条会闪,读起来
        是"风"而不是几根死线。速度不够时返回空。"""
        sp = math.hypot(self.vx, self.vy)
        if sp < SPEED_LINE_MIN:
            return []
        ux, uy = -self.vx / sp, -self.vy / sp          # 指向身后
        px, py = -uy, ux                               # 垂直于运动方向
        f = min(1.0, (sp - SPEED_LINE_MIN) / (SPEED_LINE_FULL - SPEED_LINE_MIN))
        rnd = random.Random(int(now * 20))
        out = []
        for _ in range(7):
            off = rnd.uniform(-0.26, 0.26) * self.W
            start = rnd.uniform(0.16, 0.28) * self.W   # 从身体轮廓外起笔
            length = (36 + 120 * f) * self.scale * rnd.uniform(0.55, 1.0)
            x0, y0 = ux * start + px * off, uy * start + py * off
            out.append(((x0, y0), (x0 + ux * length, y0 + uy * length),
                        int((70 + 130 * f) * rnd.uniform(0.55, 1.0))))
        return out

    def _draw_speed_lines(self, d, cx, cy, k, now):
        for (x0, y0), (x1, y1), a in self._speed_line_specs(now):
            d.line([cx + x0 * k, cy + y0 * k, cx + x1 * k, cy + y1 * k],
                   fill=(236, 240, 255, a), width=max(1, int(1.7 * k)))

    @staticmethod
    def _meditate_arms(t2, W, H, lift):
        """冥想三股星尘此刻的头部位置(相对窗口中心)与远近。tick 里撒尾迹
        和 render 里画星核共用这一份,两边永远对得上。"""
        arms = []
        for arm in range(3):
            a = t2 * 2.6 + arm * 2.0944
            # sin(a) > 0 是椭圆靠观众的下半圈(近侧)
            arms.append((math.cos(a) * 0.30 * W,
                         math.sin(a) * 0.30 * W * 0.26 - 0.02 * H - lift,
                         "near" if math.sin(a) > 0 else "far", a))
        return arms

    @staticmethod
    def _meditate_orb_vis(t2):
        """星核淡入淡出:跟着尾迹的起止(0.8~4.9 秒)各留一小段过渡。"""
        return max(0.0, min(1.0, (t2 - 0.8) / 0.4, (4.9 - t2) / 0.5))

    def _draw_meditate_orbs(self, frame, now, k, side):
        """原来三股星尘全是平贴的 sparkle,永远画在她身前,看不出是"绕着"
        她转。每股的头部加一颗星核:远侧的小而暗、画在立绘之前(被她挡住),
        近侧的大而亮、画在立绘之后。"""
        t2 = now - self.meditate_start
        vis = self._meditate_orb_vis(t2)
        if vis <= 0:
            return
        for x, y, arm_side, _ in self._meditate_arms(t2, self.W, self.H, self._spin_lift):
            if arm_side == side:
                self.fx.orb(frame, (self.W / 2 + x) * k, (self.H / 2 + y) * k, side, vis)

    def _draw_decors(self, frame, d, t, layer, dy, k):
        W = self.W
        spr_w1 = self.spr2.width / SS
        spr_h1 = self._spr_disp_h()
        center_rel = float(self.cfg.get("char_center_rel", 0.44))
        for name, (img, rel, lyr) in self.decor_imgs.items():
            if lyr != layer:
                continue
            amp = (13.0 if layer == "front" else 18.0) * self.scale
            ox = (self.look_x * amp + math.sin(t * 0.8 + hash(name) % 7) * 4) * k
            oy = (self.look_y * amp * 0.5 + math.sin(t * 1.1 + hash(name) % 5) * 5) * k
            bx = (W / 2 + (rel[0] - center_rel) * spr_w1) * k
            by = (self.FOOT_Y - spr_h1 + rel[1] * spr_h1) * k
            frame.paste(img, (int(bx - img.width / 2 + ox),
                              int(by - img.height / 2 + oy)), img)

    # 有替代嘴形的情绪(_face_texture 的 em 分支):只有这些才盖掉原画的嘴。
    # happy/shy/curious 等只靠眼睑表现 —— 原来也盖嘴却不画新嘴,她就没了嘴
    # 立绘几何的类级默认(= 旧立绘):测试里不走 __init__ 的壳桌宠也有值
    _mouth_rel = (.469, .463)     # 新立绘嘴位(坐姿抱坐垫)
    _sprite_center_rel = 0.5
    _scene_art = None
    _last_face_key = None

    EMO_MOUTHS = frozenset(("angry", "surprised", "amazed", "shocked",
                            "sad", "sleepy", "tired"))

    def _offer_lid(self, lid, mode, now, hold=2.2):
        """自主情绪眼睑(AI 担心/好奇):眼睑空着就播,被别的情绪占着就排队。

        原来占着就直接丢 —— 出错会话的 id 却已记进 _ai_err_seen,同一会话
        再也不会担心第二次。排队的那份由 _face_texture_key 在眼睑空出来时
        补播,15 秒还轮不上就算过时作罢;排着的担心不被好奇顶掉。"""
        if now >= getattr(self, "_lid_until", 0.0):
            self._lid, self._lid_mode, self._lid_until = lid, mode, now + hold
            return
        old = getattr(self, "_lid_pending", None)
        if not (old and now < old[2] and old[1] == "sad" and mode != "sad"):
            self._lid_pending = (lid, mode, now + 15.0)

    def _face_texture_key(self, now, t, asleep):
        blink = self.cfg.get('blink_overlay', True) and now < self.blink_until
        style = 'sleep' if asleep else 'sing' if self.singing else ''
        mouth = getattr(self, '_mouth', None)
        if not style and mouth:
            if now < mouth[1]:
                style = mouth[0]
            else:
                self._mouth = None
        rate = {'sing':5, 'laugh':13, 'chew':9}.get(style, 0)
        phase = round(abs(math.sin(t*rate))*8) if rate else 0
        # 排队的自主情绪(AI 担心撞上别的情绪时延后):眼睑一空出来就补播
        pend = getattr(self, "_lid_pending", None)
        if pend and now >= getattr(self, "_lid_until", 0.0):
            self._lid_pending = None
            if now < pend[2]:
                self._offer_lid(pend[0], pend[1], now)
        lid_target = getattr(self, "_lid", 0.0) if now < getattr(self, "_lid_until", 0.0) else 0.0
        # 眼睑缓动:约 0.25 秒滑到目标,情绪切换不再瞬跳。
        # approach 的 rate 是"30fps 下每帧吃掉的比例",必须 < 1(原来传 12.0
        # 直接 return target,缓动从没生效);0.33 ≈ 1-exp(-12/30),0.25 秒走完约 95%
        prev_t = getattr(self, "_lid_prev_t", None)
        dt = max(0.0, now - prev_t) if prev_t else 0.033
        self._lid_prev_t = now
        self._lid_disp = approach(getattr(self, "_lid_disp", 0.0), lid_target, 0.33, dt)
        lid = round(self._lid_disp * 8) / 8
        # 情绪嘴跟眼睑同生同灭:_lid_until 过了、眼睑也缓回全开才撤。原来 em
        # 只看 style,_lid_mode 又从不复位,一次情绪的嘴形会永久留在脸上。
        # 只保留真会改画面的模式(有替代嘴形的),其余归 "" —— 键跟着画面走,
        # 不同情绪同一档眼睑共用一张缓存
        em = getattr(self, "_lid_mode", "") if (
            not style and (now < getattr(self, "_lid_until", 0.0) or lid > 0)) else ""
        if em not in self.EMO_MOUTHS:
            em = ""
        if blink or style == 'sleep':
            lid = 1.0
        return style, phase, bool(blink and not asleep), lid, em

    def _face_texture(self, pose, key, base=None):
        """所有五官先落在原画坐标,再与原画共用同一次网格变形。
        base:画在给定底图上(秋千原画模式拿不打光的 spr2 取五官补丁)。"""
        source = base if base is not None else self.warper.lit_source(pose)
        style, phase, blink, lid, em = key
        if not style and not blink and lid <= 0.02 and not em:
            return source
        source = source.copy()
        w, h = source.size
        # sk 必须在所有分支之前定:情绪嘴的 angry/sad 也要用,原来只在
        # lid 分支里赋值,眨眼帧/眼睑归零时一读就 UnboundLocalError,整帧冻住
        sk = self.scale * SS
        if blink or style == 'sleep':
            self._draw_blink(source, 0, 0, source.getchannel('A'))
        elif lid > 0.06:
            # 半开眼睑:情绪神情(生气半眯/困倦耷拉)。复用眨眼肤色贴片,
            # 只贴上部 lid 比例,下缘一条睑缘线让"眯眼"有轮廓。
            self._ensure_blink_patches()
            side_i = 0
            for side_i, (cxp, cyp, patch) in enumerate(self._blink_patches):
                pw, ph = patch.size
                cover = max(2, int(ph * 0.52 * lid))
                part = patch.crop((0, 0, pw, cover))
                source.alpha_composite(part, (int(cxp - pw / 2),
                                              int(cyp - ph * 0.46)))
                ly = cyp - ph * 0.46 + cover
                dd = ImageDraw.Draw(source, "RGBA")
                # 睑缘线:生气时斜切(内低外高 —— 两眼内端下压),程度随 lid
                # (看键里的 em 而不是 _lid_mode:画面只能取决于缓存键)
                slant = (3.2 * sk * lid) if em == "angry" else 0.0
                if side_i == 0:      # 左眼:内端在 +x
                    y_a, y_b = ly, ly + slant
                else:                # 右眼:内端在 -x
                    y_a, y_b = ly + slant, ly
                dd.line((cxp - pw * 0.30, y_a, cxp + pw * 0.30, y_b),
                        fill=(72, 58, 92, 200), width=max(1, round(1.4 * sk)))
        if em in self.EMO_MOUTHS:
            # 情绪嘴:先盖住原画的微笑,再画对应形状(生气嘟嘴/惊讶张圆/
            # 难过下弯/困倦小张)。盖嘴用眨眼贴片采到的肤色,写死的米色有色差
            self._ensure_blink_patches()
            mx, my = w * self._mouth_rel[0], h * (self._mouth_rel[1] + 0.002)
            dd = ImageDraw.Draw(source, "RGBA")
            dd.ellipse((mx - w*0.024, my - h*0.014, mx + w*0.024, my + h*0.018),
                       fill=self._blink_skin + (255,))
            if em == "angry":
                dd.arc((mx - w*0.016, my - h*0.008, mx + w*0.016, my + h*0.014),
                       205, 335, fill=(172, 84, 96, 255), width=max(2, round(2.2*sk)))
            elif em in ("surprised", "amazed", "shocked"):
                dd.ellipse((mx - w*0.011, my - h*0.006, mx + w*0.011, my + h*0.020),
                           fill=(150, 74, 84, 255))
                dd.ellipse((mx - w*0.006, my + h*0.004, mx + w*0.006, my + h*0.016),
                           fill=(120, 52, 62, 255))
            elif em == "sad":
                dd.arc((mx - w*0.015, my + h*0.002, mx + w*0.015, my + h*0.022),
                       180, 360, fill=(172, 84, 96, 255), width=max(2, round(2.0*sk)))
            elif em in ("sleepy", "tired"):
                dd.ellipse((mx - w*0.008, my - h*0.004, mx + w*0.008, my + h*0.014),
                           fill=(150, 74, 84, 230))
        d = ImageDraw.Draw(source, 'RGBA')
        w, h = source.size
        # Sleep already uses _draw_blink above. Drawing another arc here
        # creates two eyelids per eye (a glasses-like outline).
        if style and style != 'sleep':
            rate = {'sing':5, 'laugh':13, 'chew':9}.get(style, 1)
            phase_time = math.asin(phase/8)/rate
            if style == 'sing':
                self._draw_singing_mouth(d, w*self._mouth_rel[0], h*self._mouth_rel[1],
                                         phase_time, sk)
            else:
                self._draw_mouth(style, d, w*self._mouth_rel[0], h*self._mouth_rel[1],
                                 phase_time, sk)
        source.putalpha(self.spr2.getchannel('A'))
        return source

    def _ensure_blink_patches(self):
        if self._blink_patches is not None:
            return
        eyes = self.cfg.get("eyes", {})
        w2, h2 = self.spr2.size
        size = self.cfg.get("eyes", {}).get("size", 0.052)
        patches, cols = [], []
        skin_at = eyes.get("skin_at")      # 新立绘:眼下直落是刘海/腮红,单独指定取色点
        for i, key in enumerate(("left", "right")):
            ex, ey = eyes.get(key, [0.4, 0.46])
            cxp, cyp = ex * w2, ey * h2
            rw = size * w2 * 0.62
            rh = size * h2 * 0.30
            sx, sy = int(cxp), int(cyp + rh * 3.2)
            if skin_at and len(skin_at) > i:
                sx, sy = int(skin_at[i][0] * w2), int(skin_at[i][1] * h2)
            region = self.spr2.crop((max(0, sx - 8), max(0, sy - 4),
                                     min(w2, sx + 8), min(h2, sy + 4)))
            # 平均肤色:取亮于阈值的像素均值(tobytes 替代已弃用的 getdata)
            raw = region.convert("RGB").tobytes()
            px = [(raw[i], raw[i + 1], raw[i + 2])
                  for i in range(0, len(raw), 3)
                  if raw[i] + raw[i + 1] + raw[i + 2] > 330] or [(255, 240, 228)]
            col = tuple(sum(c[i] for c in px) // len(px) for i in range(3))
            pw, ph = int(rw * 2.6), int(rh * 3.4)
            patch = Image.new("RGBA", (pw, ph), col + (0,))
            # 底色整块铺肤色:只模糊 alpha 时,椭圆外的黑色 RGB 会被拖成一圈暗边
            pd = ImageDraw.Draw(patch)
            pd.ellipse([2, 2, pw - 2, ph - 2], fill=col + (255,))
            patch.putalpha(patch.getchannel("A").filter(
                # 羽化比例可配:新立绘的大眼睛睫毛粗,羽化太宽睫毛会从边上透出来,
                # 闭眼看着像戴了一副圆眼镜
                ImageFilter.GaussianBlur(min(pw, ph) * eyes.get("blur", 0.18))))
            patches.append((cxp, cyp, patch))
            cols.append(col)
        self._blink_patches = patches
        # 两眼下方采到的肤色均值:情绪嘴盖原画微笑时用同一份颜色
        self._blink_skin = tuple(sum(c[i] for c in cols) // len(cols) for i in range(3))

    def _draw_blink(self, frame, paste_x, paste_y, spr_alpha):
        self._ensure_blink_patches()
        eyes = self.cfg.get("eyes", {})
        w2, h2 = self.spr2.size
        size = eyes.get("size", 0.052)
        lid_line = eyes.get("lid_line", False)
        dd = ImageDraw.Draw(frame, "RGBA") if lid_line else None
        sk = self.scale * SS
        left, right = eyes.get("left", (.4, .46)), eyes.get("right", (.4, .46))
        eye_dx = (right[0] - left[0]) * w2
        slope = max(-.45, min(.45, (right[1] - left[1]) * h2 / eye_dx)) if abs(eye_dx) > 1 else 0.0
        for (cxp, cyp, patch) in self._blink_patches:
            pw, ph = patch.size
            frame.paste(patch, (int(paste_x + cxp - pw / 2),
                                int(paste_y + cyp - ph * 0.42)), patch)
            if dd is not None:
                # 闭眼的睫毛线("︶"):只盖肤色读起来是一块空白,有这条线才像闭眼
                x, y = paste_x + cxp, paste_y + cyp
                # Follow the painted head's tilt; a horizontal arc on each
                # slanted eye looks pasted on. One continuous, shallow curve.
                points = []
                for n in range(25):
                    u = n / 24
                    dx = (u - .5) * pw * .60
                    points.append((x + dx, y + slope * dx + ph * (.06 + .10 * (1 - (2*u-1)**2))))
                dd.line(points, fill=(66, 46, 82, 235), width=max(2, round(1.5 * sk)), joint="curve")

    def _draw_sticker(self, frame, d, now, k, spr_left, spr_top1, spr_w1, warped):
        previous = self._sticker_previous
        if previous:
            st, born, (sc, alpha) = previous
            alpha *= max(0.0, 1-(now-born)/.18)
            self._draw_sticker_layer(frame, now, k, spr_left, spr_top1, spr_w1, warped,
                                     st, (sc, alpha))
        self._draw_sticker_layer(frame, now, k, spr_left, spr_top1, spr_w1, warped, self.sticker)

    def _draw_sticker_layer(self, frame, now, k, spr_left, spr_top1, spr_w1, warped, st, pose=None):
        sc, opacity = pose if pose is not None else self._sticker_pose(st, now)
        alpha = max(0, min(255, int(255*opacity)))
        if alpha == 0:
            return
        img = self.load_expr(st["name"])
        if img is None:
            return
        th = int(self._spr_disp_h() * 0.55 * k * sc)
        tw = int(img.width * th / img.height)
        if tw > spr_w1 * 0.6 * k:
            tw = int(spr_w1 * 0.6 * k)
            th = int(tw * img.height / img.width)
        # 尺寸可能被上面的夹取算成 0(小 scale + 生命末期),
        # PIL 会直接抛 ValueError 把整帧 render 打断。
        if tw < 1 or th < 1:
            return
        # 尺寸量化到 2px 再缓存:呼吸动画(sc 那条 sin)每帧把目标尺寸挪动
        # 零点几个像素,原来每帧都要对一张 ~300px 的图做一次 LANCZOS ——
        # 一次贴纸表演要做 45~100 次。量化后整场表演只剩个位数次。
        tw = max(1, (tw + 1) // 2 * 2)
        th = max(1, (th + 1) // 2 * 2)
        ck = (st["name"], tw, th)
        im2 = self._expr_rs.get(ck)
        if im2 is None:
            im2 = img.resize((tw, th), Image.LANCZOS)
            self._expr_rs[ck] = im2
            while len(self._expr_rs) > 24:
                self._expr_rs.popitem(last=False)
        else:
            self._expr_rs.move_to_end(ck)
        if alpha < 255:
            # 淡出是逐帧变的,必须先复制 —— 直接 putalpha 会把缓存里那张改掉
            im2 = im2.copy()
            im2.putalpha(im2.getchannel("A").point(lambda v: v * alpha // 255))
        tw1 = tw / k
        if spr_left + spr_w1 + tw1 * 0.8 < self.W - 8:
            sx = int((spr_left + spr_w1 - tw1 * 0.25) * k)
        else:
            sx = int((self.W - tw1 - 6) * k)
        sy = int((spr_top1 + warped.height / k * 0.06) * k)
        self.paste_glow(frame, sx + tw / 2, sy + th / 2, 40, (200, 190, 255), max(1,int(42*opacity)))
        frame.alpha_composite(im2, (sx, sy))

    def _tv_cat(self, d, t, k):
        bob = math.sin(t * 4) * 3
        x0, y0 = int(34 * self.scale) * k, int((150 + bob) * self.scale) * k
        u = k
        d.line([x0 + 22 * u, y0, x0 + 15 * u, y0 - 13 * u], fill=INK + (255,), width=int(1.6 * u))
        d.line([x0 + 22 * u, y0, x0 + 29 * u, y0 - 13 * u], fill=INK + (255,), width=int(1.6 * u))
        d.ellipse([x0 + 13 * u, y0 - 16 * u, x0 + 17 * u, y0 - 12 * u], fill=GOLD + (255,))
        d.ellipse([x0 + 27 * u, y0 - 16 * u, x0 + 31 * u, y0 - 12 * u], fill=GOLD + (255,))
        d.polygon([(x0 + 2 * u, y0 + 1 * u), (x0 + 8 * u, y0 - 11 * u), (x0 + 14 * u, y0 + 1 * u)],
                  fill=(90, 74, 138, 255), outline=(58, 38, 112, 255))
        d.polygon([(x0 + 30 * u, y0 + 1 * u), (x0 + 36 * u, y0 - 11 * u), (x0 + 42 * u, y0 + 1 * u)],
                  fill=(90, 74, 138, 255), outline=(58, 38, 112, 255))
        d.rounded_rectangle([x0, y0, x0 + 44 * u, y0 + 34 * u], radius=4 * u,
                            fill=(90, 74, 138, 255), outline=(58, 38, 112, 255),
                            width=int(1.6 * u))
        d.rounded_rectangle([x0 + 4 * u, y0 + 4 * u, x0 + 40 * u, y0 + 30 * u],
                            radius=3 * u, fill=(189, 227, 255, 255))
        for ex in (x0 + 15 * u, x0 + 29 * u):
            d.ellipse([ex - 2 * u, y0 + 13 * u, ex + 2 * u, y0 + 17 * u], fill=(58, 38, 112, 255))
        d.line([x0 + 17 * u, y0 + 22 * u, x0 + 20 * u, y0 + 25 * u, x0 + 22 * u, y0 + 22 * u],
               fill=(58, 38, 112, 255), width=int(1.4 * u), joint="curve")
        d.line([x0 + 22 * u, y0 + 22 * u, x0 + 25 * u, y0 + 25 * u, x0 + 27 * u, y0 + 22 * u],
               fill=(58, 38, 112, 255), width=int(1.4 * u), joint="curve")


    def _acquire_hwnd(self):
        """(重新)获取顶层窗口句柄, 并确保 WS_EX_LAYERED 已置位。

        鼠标穿透不再走 WS_EX_TRANSPARENT(那样会连右键都透过去),
        改成在 Tk 层面拦截左键再投递到下方窗口,右键/滚轮/中键照常。
        """
        try:
            wid = self.root.winfo_id()
        except Exception:
            return 0
        hwnd = user32.GetAncestor(wid, 2) or wid
        if not hwnd:
            return 0
        self.hwnd = hwnd
        ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) or 0
        # 只保证分层(透明色键) 标志在,绝不主动加 WS_EX_TRANSPARENT
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, int(ex) | WS_EX_LAYERED)
        return hwnd


    def _push(self, img):
        w, h = img.size
        # 必须按 BGRA 取字节:PIL 的 RGBA 是 R,G,B,A 顺序,而 Windows 32 位
        # DIB(BI_RGB)按 B,G,R,A 存放。直接 tobytes() 会让 R 和 B 对调 ——
        # alpha 在第 4 字节所以透明度看不出问题,只有颜色会反(蓝发变橙发)。
        buf = premult_bgra(img)
        hdc, mdc, ptr = _gdi_surface(w, h)
        if not mdc:
            return
        ctypes.memmove(ptr, buf, len(buf))
        blend = _Blend(0, 0, 255, 1)
        pt_dst = wintypes.POINT(int(self.x), int(self.fy - self.FOOT_Y))
        sz = wintypes.SIZE(w, h)
        pt_src = wintypes.POINT(0, 0)
        ok = user32.UpdateLayeredWindow(self.hwnd, hdc, ctypes.byref(pt_dst),
                                   ctypes.byref(sz), mdc, ctypes.byref(pt_src),
                                   0, ctypes.byref(blend), ULW_ALPHA)
        if not ok:
            gle = ctypes.get_last_error()
            if gle == 1400 and self._acquire_hwnd():
                ok = user32.UpdateLayeredWindow(
                    self.hwnd, hdc, ctypes.byref(pt_dst),
                    ctypes.byref(sz), mdc, ctypes.byref(pt_src),
                    0, ctypes.byref(blend), ULW_ALPHA)
            if not ok and getattr(self, '_push_fail', 0) < 20:
                self._push_fail = getattr(self, '_push_fail', 0) + 1
                try:
                    with open(os.path.join(HERE, '_push_debug.log'), 'a',
                              encoding='utf-8') as f:
                        f.write(f'_push fail gle={gle} '
                                f'({ctypes.FormatError(gle)}) hwnd={self.hwnd} '
                                f'pt=({pt_dst.x},{pt_dst.y}) '
                                f'sz=({sz.cx},{sz.cy}) img={w}x{h}\n')
                except Exception:
                    pass


# ==================== 聊天面板(大幅扩大的魔法风)====================
class InteractionCard:
    """用户右键唤出的不透明卡片;不会常驻,动作仍由 Pet 统一处理。"""

    HINTS = {'聊天':'聊天并查看之前的对话', '喂糖':'吃颗糖，最多补充 40 点星光',
             '小屋':'打开小屋空间预览', '睡觉':'安心休息一会儿'}

    @staticmethod
    def disabled_reasons(pet):
        if pet.state in ('magic', 'eat'):
            return {'喂糖':'先让我吃完这颗糖~' if pet.state == 'eat' else '等这次动作结束~'}
        if pet.state in ('fly', 'fall'):
            return {'喂糖':'等我落稳，再喂糖~'}
        return {}

    @staticmethod
    def position(x, y, w, h, area):
        left, top, right, bottom = area
        return (int(max(left+8, min(x, right-w-8))),
                int(max(top+8, min(y, bottom-h-8))))

    def __init__(self, pet, x, y):
        self.pet = pet
        self.closed = False
        self._refresh_id = self._focus_id = None
        self.win = tk.Toplevel(pet.root)
        self.win.withdraw()
        try:
            self._build(x, y)
        except Exception:
            self.win.destroy()
            raise

    def _build(self, x, y):
        pet, win = self.pet, self.win
        area = work_area_at(x, y) or (0, 0, pet.sw, pet.sh)
        u = max(1.0, min(1.5, (area[3]-area[1])/1080))
        w, h = int(320*u), int(324*u)
        self.u = u
        x, y = self.position(x+8, y+8, w, h, area)
        win.title('小乔 · 互动卡片')
        from popup_material import apply_surface
        apply_surface(win)
        win.overrideredirect(True)
        win.attributes('-topmost', True)
        win.configure(bg=UI_BG)
        win.geometry(f'{w}x{h}+{x}+{y}')
        self.cv = cv = tk.Canvas(win, bg=UI_BG, highlightthickness=0, bd=0)
        cv.pack(fill='both', expand=True)
        # 深紫卡片、细金边与少量柔和层次，让真实状态与四个动作成为主角。
        self._w, self._h = w, h
        self._imgs = []
        self._btn_rects = []
        self._bg_img = self._card_background(w, h, u)
        for x0, y0, bw, bh, accent in (
                [(16*u + c * 147*u, 152*u + r_ * 56*u, 141*u, 50*u, (r_, c) == (0, 0))
                 for r_ in range(2) for c in range(2)]
                + [(18*u, 274*u, 150*u, 32*u, False), (212*u, 274*u, 90*u, 32*u, False)]):
            self._btn_rects.append((x0, y0, bw, bh, accent))
            bi, bp = ui3d.calm_button(bw, bh, 12*u if bh > 40*u else 9*u, k=u, accent=accent)
            sh = bi.copy()
            sh.paste((0, 0, 0, 0), (bp, bp, bp + int(bw), bp + int(bh)))   # 只留投影
            self._bg_img.alpha_composite(sh, (int(x0 - bp), int(y0 - bp)))
        self._bg_tk = ImageTk.PhotoImage(self._bg_img)
        cv.create_image(0, 0, anchor='nw', image=self._bg_tk)
        cv.create_text(18*u, 28*u, anchor='w', text='小乔',
                       font=ui_font(20,u,True), fill=UI_TITLE)
        cv.create_text(18*u, 53*u, anchor='w', text=f'陪伴第 {pet.companion_days()} 天 · 一起度过这会儿',
                       font=ui_font(11,u), fill=UI_TEXT_DIM)
        cv.create_line(18*u, 66*u, 302*u, 66*u, fill=UI_BORDER, width=1)
        self.status = cv.create_text(18*u, 82*u, anchor='w', font=ui_font(14,u), fill=UI_TEXT)
        self.energy = cv.create_rectangle(18*u,99*u,18*u,104*u,fill=UI_ACCENT,outline='')
        self._hint_key = None
        self.hint = cv.create_text(18*u,128*u,anchor='w',text=self._default_hint(),font=ui_font(11,u),fill=UI_TEXT_DIM,width=284*u,justify='left')
        self.buttons = {}
        choices = [('聊天', pet.open_chat), ('喂糖', pet.eat_candy),
                   ('小屋', pet.open_room_preview), ('睡觉', self._sleep)]
        for i, (label, action) in enumerate(choices):
            button = self._button(win, label, lambda fn=action,key=label: self._run(fn,key),
                                  rect=self._btn_rects[i])
            button.bind('<Enter>',lambda e,key=label:self._show_hint(key),add='+')
            button.bind('<FocusIn>',lambda e,key=label:self._focus_hint(key),add='+')
            button.bind('<Leave>',lambda e:self._show_hint(None),add='+')
            self.buttons[label] = button
        self._button(win, '场景与设置  ›', self._more, rect=self._btn_rects[4], size=11)
        self._button(win, '关闭  Esc', self.close, rect=self._btn_rects[5], size=11)
        win.bind('<Escape>', lambda e: self.close())
        win.bind('<FocusOut>', self._on_focus_out)
        win.protocol('WM_DELETE_WINDOW', self.close)
        self._refresh()
        win.deiconify()
        win.lift()
        # 打开时程序自动把焦点给「聊天」,这一下别用按钮说明盖掉今日小结
        self._auto_focus = True
        self._auto_focus_id = win.after(250, self._end_auto_focus)
        self.buttons['聊天'].focus_force()

    def _card_background(self, w, h, u):
        """Quiet purple material and a simple star-energy track; no studs or clock."""
        bg = Image.new('RGBA', (int(w), int(h)), UI_BG)
        m = int(3*u)
        body, pad = ui3d.calm_panel(int(w - 2*m), int(h - 2*m), 18*u,
                                   k=u, studs=False)
        Pet._ac(bg, body, m - pad, m - pad)
        d = ImageDraw.Draw(bg)
        d.rounded_rectangle((18*u, 98*u, 302*u, 105*u), radius=3*u,
                            fill=UI_FIELD)
        return bg

    def _button(self, parent, text, action, rect=None, size=14):
        """Calm material; retain Tk focus, activation and disabled behavior."""
        u = self.u
        x0, y0, bw, bh, accent = rect
        imgs = {}
        for st in ('normal', 'hover', 'pressed', 'disabled'):
            bi, bp = ui3d.calm_button(bw, bh, 12*u if bh > 40*u else 9*u, k=u,
                                 state=st, accent=accent)
            base = self._bg_img.crop((int(x0), int(y0), int(x0 + bw), int(y0 + bh)))
            base.alpha_composite(bi.crop((bp, bp, bp + int(bw), bp + int(bh))))
            imgs[st] = ImageTk.PhotoImage(base)
        self._imgs.append(imgs)
        b = tk.Button(parent, text=text, command=action, image=imgs['normal'], compound='center',
                      font=ui_font(size,u,True), bg=UI_PANEL, activebackground=UI_PANEL,
                      fg=UI_GOLD if accent else UI_TEXT, activeforeground=UI_GOLD,
                      disabledforeground=UI_TEXT_DIM,
                      relief='flat', bd=0, cursor='hand2', takefocus=True, padx=0, pady=0,
                      highlightthickness=0)
        b._imgs = imgs
        def show(st):
            if str(b['state']) == 'disabled':
                st = 'disabled'
            b.configure(image=imgs[st])
        b.bind('<Enter>', lambda e: show('hover'))
        b.bind('<Leave>', lambda e: show('normal'))
        b.bind('<ButtonPress-1>', lambda e: show('pressed'))
        b.bind('<ButtonRelease-1>', lambda e: show('hover'))
        # 键盘焦点用"悬停"那张图表示(Tk 的焦点框会在图外描一圈平色边)
        b.bind('<FocusIn>', lambda e: show('hover'), add='+')
        b.bind('<FocusOut>', lambda e: show('normal'), add='+')
        b.bind('<Return>', lambda e: (b.invoke(), 'break')[1])
        self.cv.create_window(int(x0), int(y0), anchor='nw', window=b,
                              width=int(bw), height=int(bh))
        return b

    def _refresh(self):
        if self.closed:
            return
        star = max(0, min(100, self.pet.star))
        self.cv.itemconfigure(self.status, text=f'星光 {int(star)}%  ·  {self.pet.affection_level()}')
        self.cv.coords(self.energy,18*self.u,99*self.u,(18+284*star/100)*self.u,104*self.u)
        napping = (self.pet.state in ('sleep', 'yawn')
                   or getattr(self.pet, '_nap_on_swing', False))
        self.buttons['睡觉'].configure(text='叫醒' if napping else '睡觉')
        reasons = self.disabled_reasons(self.pet)
        for key, button in self.buttons.items():
            off = key in reasons
            button.configure(state='disabled' if off else 'normal')
            imgs = getattr(button, '_imgs', None)
            if isinstance(imgs, dict) and (off or button.cget('image') == str(imgs['disabled'])):
                button.configure(image=imgs['disabled' if off else 'normal'])
        self._show_hint(self._hint_key)
        self._refresh_id = self.win.after(400, self._refresh)

    def _focus_hint(self, key):
        """Tab 切焦点时显示按钮说明;打开卡片瞬间的程序自动聚焦除外。"""
        if getattr(self, '_auto_focus', False):
            return
        self._show_hint(key)

    def _end_auto_focus(self):
        self._auto_focus = False

    def _default_hint(self):
        """没悬停按钮时显示今天的陪伴小结(最多三项,卡片放不下更多)。"""
        s = self.pet._today_summary(limit=3)
        return f'今天 · {s}' if s else '一起度过这会儿'

    def _show_hint(self, key):
        if self.closed:
            return
        self._hint_key = key
        reason = self.disabled_reasons(self.pet).get(key)
        hint = self.HINTS.get(key, self._default_hint())
        if key == '睡觉' and (self.pet.state in ('sleep', 'yawn')
                              or getattr(self.pet, '_nap_on_swing', False)):
            hint = '轻轻叫醒，等她慢慢回过神'
        self.cv.itemconfigure(self.hint,text=reason or hint,fill=UI_GOLD if reason else UI_TEXT_DIM)

    def _sleep(self):
        if (self.pet.state in ('sleep', 'yawn')
                or getattr(self.pet, '_nap_on_swing', False)):
            self.pet.wake_up()      # 打盹唤醒:复用同一出口,保持场景
        else:
            self.pet.go_sleep()

    def _run(self, action, key=None):
        if self.closed:
            return
        if key in self.disabled_reasons(self.pet):
            self._show_hint(key)
            return
        self.close()
        action()

    def _more(self):
        x, y = self.win.winfo_x()+int(18*self.u), self.win.winfo_y()+int(274*self.u)
        self.close()
        self.pet._show_full_menu(x, y)

    def _on_focus_out(self, event):
        if not self.closed and self._focus_id is None:
            self._focus_id = self.win.after_idle(self._check_focus)

    def _check_focus(self):
        self._focus_id = None
        if self.closed:
            return
        focused = self.win.focus_displayof()
        if focused is None or focused.winfo_toplevel() != self.win:
            self.close()

    def close(self):
        if self.closed:
            return
        self.closed = True
        # 自动聚焦的 250ms 定时器也要撤:卡片 250ms 内被关掉时(测试里很常见)
        # 它会对已销毁的窗口触发,Tcl 报 invalid command name
        for timer in (self._refresh_id, self._focus_id,
                      getattr(self, '_auto_focus_id', None)):
            if timer:
                self.win.after_cancel(timer)
        if getattr(self.pet, 'action_card', None) is self:
            self.pet.action_card = None
        self.win.destroy()


class ChatBox:
    """聊天窗(苹果「信息」式):她的话是左边的石墨色气泡,你的话是右边的蓝色气泡,
    时间只在隔了一会儿时居中写一次;她连着说同一句只留一个气泡并计数 ×N;
    等回复时有三个点的「正在输入」气泡。每个气泡后面跟着同样内容的隐藏文字,
    所以复制、查找和状态导出都还是纯文本。"""

    @staticmethod
    def _layout(screen_w, screen_h):
        u = max(1.0, min(1.5, screen_h / 1080.0))
        return u, int(min(560*u, screen_w-32)), int(min(680*u, screen_h-100)), int(16*u)

    def __init__(self, pet: "Pet"):
        import apple_ui as A
        self.A = A
        self.pet = pet
        self.win = tk.Toplevel(pet.root)
        self.win.title("和小乔聊天")
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=KEY)
        self.win.attributes("-transparentcolor", KEY)
        from popup_material import apply_surface
        apply_surface(self.win)

        # 尺寸按「她所在那块屏」算:副屏小也不溢出,输入栏始终在屏幕内
        scene = getattr(pet, "_swing", None)
        if getattr(pet, "state", "") == "swing" and scene and scene.get("rect"):
            l, t, r, b = scene["rect"]
            area = work_area_at((l + r) / 2, (t + b) / 2) or (0, 0, pet.sw, pet.sh)
        else:
            area = (work_area_at(getattr(pet, "x", 0) + getattr(pet, "W", 0) / 2,
                                 getattr(pet, "fy", 0)) or (0, 0, pet.sw, pet.sh))
        u, w_, h_, tail = self._layout(pet.sw, pet.sh)
        self.w_ = int(min(w_, area[2] - area[0] - 32))
        self.h_ = int(min(h_, area[3] - area[1] - tail - 40))
        self.u = u
        self._bg = A.BG
        f_title = A.tk_font(17 * u, medium=True)
        f_text = A.tk_font(14 * u)
        f_btn = A.tk_font(13 * u, medium=True)
        f_hint = A.tk_font(11 * u)
        self._pf = A.font(round(14 * u), 420)          # bubble text
        self._pf_small = A.font(round(11 * u), 420)

        if scene and getattr(pet, "state", "") == "swing" and scene.get("rect"):
            # 在场景空的一侧打开,顶边和场景对齐
            l, t, r, b = scene["rect"]
            px = l - self.w_ - 16 if l - area[0] >= area[2] - r else r + 16
            py = t
        else:
            px = pet.x - self.w_ - 20
            py = pet.fy - pet.H - self.h_ - tail - 8
        px = int(max(area[0] + 8, min(px, area[2] - self.w_ - 8)))
        py = int(max(area[1] + 8, min(py, area[3] - self.h_ - tail - 8)))
        self.win.geometry(f"{self.w_}x{self.h_ + tail}+{px}+{py}")

        bg = self.cached_bg(self.w_, self.h_, tail)
        self._bg_photo = ImageTk.PhotoImage(bg, master=self.win)
        self.cv = tk.Canvas(self.win, width=self.w_, height=self.h_ + tail, bg=KEY,
                            highlightthickness=0, bd=0)
        self.cv.pack()
        self.cv.create_image(0, 0, image=self._bg_photo, anchor="nw")
        self.cv.create_text(self.w_ // 2, int(27*u), anchor="center",
                            text="小乔", fill=A.hexc(A.TEXT), font=f_title)
        online = bool(pet.brain and pet.brain.available)
        self.cv.create_text(self.w_ // 2, int(50*u), anchor="center",
                            text=f"陪伴第 {pet.companion_days()} 天  ·  " +
                                 ("已连接" if online else "互动陪伴中"),
                            fill=A.hexc(A.TEXT2), font=f_hint)
        self._imgs = []

        def icon_button(glyph, action, d, accent=None):
            imgs = {st: ImageTk.PhotoImage(A.circle_button(d, glyph, st, accent), master=self.win)
                    for st in ("normal", "hover", "pressed", "disabled")}
            self._imgs.append(imgs)
            b = tk.Button(self.win, image=imgs["normal"], command=action, relief="flat", bd=0,
                          bg=A.hexc(A.BG), activebackground=A.hexc(A.BG), cursor="hand2",
                          highlightthickness=0, padx=0, pady=0, takefocus=True)
            b._imgs = imgs
            self._wire(b)
            return b

        close = icon_button("×", self.close, int(26 * u))
        self.cv.create_window(self.w_ - int(30*u), int(30*u), window=close,
                              width=int(26*u), height=int(26*u))
        self.cv.bind("<Button-1>", self._bar_press)
        self.cv.bind("<B1-Motion>", self._bar_move)

        def pill_button(parent, text, action, bw, bh, *, accent=None, state="normal"):
            bw, bh = int(bw), int(bh)
            imgs = {st: ImageTk.PhotoImage(A.pill(bw, bh, st, accent), master=self.win)
                    for st in ("normal", "hover", "pressed", "disabled")}
            self._imgs.append(imgs)
            b = tk.Button(parent, text=text, command=action, image=imgs[state], compound="center",
                          font=f_btn, state=state, bg=A.hexc(A.BG), activebackground=A.hexc(A.BG),
                          fg=A.hexc(A.TEXT), activeforeground=A.hexc(A.TEXT),
                          disabledforeground=A.hexc(A.TEXT3), relief="flat", bd=0, cursor="hand2",
                          takefocus=True, highlightthickness=0, padx=0, pady=0)
            b._imgs = imgs
            self._wire(b)
            return b

        quick = tk.Frame(self.win, bg=A.hexc(A.BG))
        self.cv.create_window(int(20*u), int(70*u), anchor="nw", window=quick,
                              width=self.w_ - int(40*u), height=int(30*u))
        for label, action in (("摸摸头", pet.pet_head), ("喂颗糖", pet.eat_candy),
                              ("AI 工作信息", pet.open_ai_panel)):
            pill_button(quick, label, action, (self.w_ - 40*u) / 3 - 8*u, 30*u).pack(
                side="left", fill="both", expand=True, padx=int(4*u))
        inset_top = int(114 * u)
        self.log_h = self.h_ - inset_top - int(84 * u)
        self.log_w = self.w_ - int(48 * u)
        self.log = tk.Text(self.win, bg=A.hexc(A.BG), fg=A.hexc(A.TEXT),
                           font=f_text, relief="flat", insertbackground=A.hexc(A.TEXT),
                           state="disabled", wrap="word", padx=int(6 * u), pady=int(6 * u),
                           highlightthickness=0, spacing1=0, spacing3=0, cursor="arrow")
        self.cv.create_window(int(20 * u), inset_top, anchor="nw", window=self.log,
                              width=self.log_w, height=self.log_h)
        self.scrollbar = tk.Scrollbar(self.win, command=self.log.yview, relief="flat", bd=0,
                                      highlightthickness=0, bg=A.hexc(A.BG),
                                      troughcolor=A.hexc(A.BG), activebackground=A.hexc(A.ELEV2))
        # 像 macOS 一样不常驻滚动条(Windows 原生滚动条是一道灰条);滚轮照常滚动
        self.log.configure(yscrollcommand=self.scrollbar.set)
        gap = int(4 * u)
        self.log.tag_configure("user", justify="right", spacing1=gap, spacing3=gap)
        self.log.tag_configure("qiao", justify="left", spacing1=gap, spacing3=gap)
        self.log.tag_configure("plain", elide=True)          # the text behind each bubble
        self.log.tag_configure("count", elide=True)
        self.log.tag_configure("hint", foreground=A.hexc(A.TEXT2), justify="center",
                               font=f_hint, spacing1=int(10*u), spacing3=int(6*u))
        self.log.tag_configure("stamp", foreground=A.hexc(A.TEXT3), justify="center",
                               font=f_hint, spacing1=int(12*u), spacing3=int(4*u))
        self.log.tag_configure("typing", justify="left", spacing1=gap, spacing3=gap)
        self.log.tag_configure("user_head", justify="right")   # kept for old callers
        self._last_msg = None      # (role, text, time, count, image name, photo)
        self._typing = None        # after-id of the typing dots
        self._typing_img = None

        # 输入栏:圆角输入框 + 蓝色圆形发送键
        row_y = inset_top + self.log_h + int(18 * u)
        row = tk.Frame(self.win, bg=A.hexc(A.BG))
        self.cv.create_window(int(20 * u), row_y, anchor="nw", window=row,
                              width=self.w_ - int(40 * u), height=int(36 * u))
        self.draft = tk.StringVar(master=self.win)
        field = tk.Frame(row, bg=A.hexc(A.BG))
        field.pack(side="left", fill="both", expand=True, padx=(0, int(10 * u)))
        fw = self.w_ - int(40 * u) - int(46 * u)
        self._field_img = ImageTk.PhotoImage(A.pill(fw, int(36 * u), "normal"), master=self.win)
        tk.Label(field, image=self._field_img, bg=A.hexc(A.BG), bd=0).place(x=0, y=0)
        self.entry = tk.Entry(field, textvariable=self.draft, bg=A.hexc(A.ELEV), fg=A.hexc(A.TEXT),
                              relief="flat", font=f_text, insertbackground=A.hexc(A.TEXT),
                              highlightthickness=0, bd=0)
        self.entry.place(x=int(16 * u), y=int(6 * u), width=fw - int(32 * u), height=int(24 * u))
        self.hist = []          # 发送过的消息(最新在后)
        self.hist_i = 0
        self.hist_draft = ""
        self.entry.bind("<Up>", self._hist_up)
        self.entry.bind("<Down>", self._hist_down)
        d = int(36 * u)
        imgs = {st: ImageTk.PhotoImage(A.circle_button(d, "↑", st, A.BLUE), master=self.win)
                for st in ("normal", "hover", "pressed", "disabled")}
        self._imgs.append(imgs)
        self.send_btn = tk.Button(row, image=imgs["disabled"], command=self.send, state="disabled",
                                  relief="flat", bd=0, bg=A.hexc(A.BG), activebackground=A.hexc(A.BG),
                                  cursor="hand2", highlightthickness=0, padx=0, pady=0, takefocus=True)
        self.send_btn._imgs = imgs
        self._wire(self.send_btn)
        self.send_btn.pack(side="left")
        self.draft.trace_add("write", lambda *_: self.send_btn.configure(
            state="normal" if self.draft.get().strip() else "disabled",
            image=self.send_btn._imgs["normal" if self.draft.get().strip() else "disabled"]))
        tk.Label(self.win, text="Enter 发送  ·  ↑↓ 已发消息  ·  Esc 关闭", bg=A.hexc(A.BG),
                 fg=A.hexc(A.TEXT3), font=f_hint).place(x=self.w_ // 2, y=self.h_ - int(18 * u),
                                                       anchor="center")

        self.entry.bind("<Return>", lambda e: self.send())
        self.log.bind("<Button-3>", self._log_menu)
        self.win.bind("<Escape>", lambda e: self.close())
        self._bx = self._by = 0
        self.replay_history()
        if self.pet.brain and self.pet.brain.available:
            self.log_hint("想聊什么，随时告诉我。")
        else:
            self.log_hint("尚未连接 AI。可在右键菜单「设置 → 连接 AI 聊天」中连接。")
        if getattr(self.pet, "ai_thinking", False) is True:
            self.show_typing(True)
        self.entry.focus_set()

    @staticmethod
    def _wire(button):
        imgs = button._imgs

        def show(look):
            if str(button["state"]) == "disabled":
                look = "disabled"
            button.configure(image=imgs[look])
        button.bind("<Enter>", lambda e: show("hover"))
        button.bind("<Leave>", lambda e: show("normal"))
        button.bind("<ButtonPress-1>", lambda e: show("pressed"))
        button.bind("<ButtonRelease-1>", lambda e: show("hover"))
        button.bind("<FocusIn>", lambda e: show("hover"), add="+")
        button.bind("<FocusOut>", lambda e: show("normal"), add="+")

    def replay_history(self):
        """回放之前的对话 —— 关掉聊天框会销毁文本控件,记录存在 pet.chat_log 里。"""
        log = getattr(self.pet, "chat_log", [])
        if not log:
            self.log_hint("对话开始 · 问技术问题她也能给你真答案")
            return
        for m in log[-60:]:
            ts = m.get("t")
            if m.get("role") == "user":
                self.log_user(m.get("text", ""), ts)
            else:
                self.log_reply(m.get("text", ""), ts)
        self.log_hint(f"以上是之前的 {len(log)} 条记录")

    def _bar_press(self, e):
        self._bx, self._by = e.x, e.y

    def _bar_move(self, e):
        self.win.geometry(f"+{self.win.winfo_x() + e.x - self._bx}"
                          f"+{self.win.winfo_y() + e.y - self._by}")

    # ---- 背景 ----
    _BG_CACHE = {}

    @classmethod
    def cached_bg(cls, w, h, tail):
        """背景图只跟窗口尺寸有关,同尺寸每次画出来都一样;最多留 2 张。"""
        key = (w, h, tail)
        img = cls._BG_CACHE.get(key)
        if img is None:
            img = cls._render_bg(None, w, h, tail)
            if len(cls._BG_CACHE) >= 2:
                cls._BG_CACHE.pop(next(iter(cls._BG_CACHE)))
            cls._BG_CACHE[key] = img
        return img

    @classmethod
    def prewarm_bg(cls, screen_w, screen_h):
        _, w, h, tail = cls._layout(screen_w, screen_h)
        cls.cached_bg(w, h, tail)

    def _render_bg(self, w, h, tail):
        """深色圆角窗体 + 一条细边,标题下一道分隔线;没有星空、金边或光效。"""
        import apple_ui as A
        u = tail / 16.0
        frame = Image.new("RGBA", (w, h + tail), KEY)
        frame.alpha_composite(A.window(w - 2, h - 2, int(22 * u), KEY), (1, 1))
        d = ImageDraw.Draw(frame)
        d.line((20*u, 108*u, w - 20*u, 108*u), fill=A.SEP + (255,), width=1)
        return frame.convert("RGB")

    def focus_entry(self):
        self.entry.focus_set()

    # ---- 消息 ----
    def _bubble(self, role, text, count=1):
        img = self.A.bubble(text, int(self.log_w * .74), self._pf, role == "user",
                            count, self._pf_small, self.A.BG)
        photo = ImageTk.PhotoImage(img, master=self.win)
        self._imgs.append(photo)
        return photo

    def _stamp(self, when, last):
        """隔了半小时以上、或换了一天,居中写一次时间(像「信息」)。"""
        if last and when - last[2] <= 1800 and time.localtime(when)[:3] == time.localtime(last[2])[:3]:
            return
        today = time.localtime()[:3] == time.localtime(when)[:3]
        label = time.strftime("%H:%M" if today else "%m-%d %H:%M", time.localtime(when))
        self.log.insert("end", label + "\n", ("stamp",))

    def _message(self, role, text, when=None):
        when = time.time() if when is None else when
        follow = role == "user" or self.log.yview()[1] >= .995
        typing = self._typing is not None
        if typing:
            self.show_typing(False)          # the thinking bubble always stays last
        last = self._last_msg
        self.log.configure(state="normal")
        if (last and role != "user" and last[0] == role and last[1] == text
                and when - last[2] <= 1800):
            # 同一句又来了(旧提醒常这样):不刷屏,同一个气泡计数
            n = last[3] + 1
            photo = self._bubble(role, text, n)
            self.log.image_configure(last[4], image=photo)
            prev = self.log.tag_prevrange("count", "end")
            if n > 2 and prev:
                self.log.delete(*prev)
            self.log.insert("end-2c", f"  ×{n}", ("count",))
            self._last_msg = (role, text, when, n, last[4], photo)
        else:
            self._stamp(when, last)
            tag = "user" if role == "user" else "qiao"
            photo = self._bubble(role, text)
            start = self.log.index("end-1c")
            name = self.log.image_create("end", image=photo)
            self.log.insert("end", text, (tag, "plain"))
            self.log.insert("end", "\n", (tag,))
            self.log.tag_add(tag, start, "end-1c")
            self._last_msg = (role, text, when, 1, name, photo)
        self.log.configure(state="disabled")
        if follow:
            self.log.see("end")
        if getattr(self.pet, "ai_thinking", False) is True:
            self.show_typing(True)           # still waiting for her actual answer

    def log_user(self, t, when=None):
        self._message("user", t, when)

    def log_reply(self, t, when=None):
        # 不截断,完整语气保留
        self._message("qiao", t, when)

    def log_hint(self, t):
        follow = self.log.yview()[1] >= .995
        self.log.configure(state="normal")
        self.log.insert("end", f"{t}\n", "hint")
        self._last_msg = None
        self.log.configure(state="disabled")
        if follow:
            self.log.see("end")

    def show_typing(self, on):
        """等回复时末尾一个三点气泡(点会走),回复到了、失败或超时就自己收起。
        只是显示,不进聊天记录。"""
        if on and self._typing is None:
            follow = self.log.yview()[1] >= .995
            self._typing_img = ImageTk.PhotoImage(self.A.typing_bubble(self._pf, 0, self.A.BG),
                                                  master=self.win)
            self.log.configure(state="normal")
            start = self.log.index("end-1c")
            self._typing_name = self.log.image_create("end", image=self._typing_img)
            self.log.insert("end", "小乔正在想 ·", ("typing", "plain"))
            self.log.insert("end", "\n", ("typing",))
            self.log.tag_add("typing", start, "end-1c")
            self.log.configure(state="disabled")
            if follow:
                self.log.see("end")
            self._typing = self.win.after(420, self._typing_tick, 1)
        elif not on and self._typing is not None:
            try:
                self.win.after_cancel(self._typing)
            except Exception:
                pass
            self._typing = None
            rng = self.log.tag_prevrange("typing", "end")
            if rng:
                self.log.configure(state="normal")
                self.log.delete(*rng)
                self.log.configure(state="disabled")

    def _typing_tick(self, n):
        rng = self.log.tag_prevrange("typing", "end")
        if not rng or not getattr(self.pet, "ai_thinking", False):
            if not rng:
                self._typing = None
            self.show_typing(False)
            return
        try:
            self._typing_img = ImageTk.PhotoImage(self.A.typing_bubble(self._pf, n, self.A.BG),
                                                  master=self.win)
            self.log.image_configure(self._typing_name, image=self._typing_img)
        except Exception:
            pass
        self._typing = self.win.after(420, self._typing_tick, n + 1)

    def _text_without_typing(self):
        text = self.log.get("1.0", "end")
        rng = self.log.tag_prevrange("typing", "end")
        if rng:
            text = self.log.get("1.0", rng[0]) + self.log.get(rng[1], "end")
        return text

    def _log_menu(self, e):
        A = self.A
        from popup_material import SurfaceMenu
        m = SurfaceMenu(self.win, tearoff=0, bg=A.hexc(A.ELEV), fg=A.hexc(A.TEXT),
                    activebackground=A.hexc(A.BLUE), activeforeground="#ffffff",
                    disabledforeground=A.hexc(A.TEXT3), bd=0)
        index = self.log.index(f"@{e.x},{e.y}")
        line = self.log.get(f"{index} linestart", f"{index} lineend").strip()
        m.add_command(label="复制这一条", command=lambda: self._copy(line),
                      state=("normal" if line else "disabled"))
        m.add_command(label="复制全部记录", command=self._copy_all)
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def _copy(self, text):
        if text:
            self.win.clipboard_clear()
            self.win.clipboard_append(text)

    def _copy_sel(self):
        try:
            t = self.log.get("sel.first", "sel.last")
        except Exception:
            return
        self._copy(t)

    def _copy_all(self):
        self._copy(self._text_without_typing().strip())

    def _hist_up(self, e=None):
        if not self.hist:
            return "break"
        if self.hist_i == len(self.hist):
            self.hist_draft = self.entry.get()
        if self.hist_i > 0:
            self.hist_i -= 1
            self.entry.delete(0, "end")
            self.entry.insert(0, self.hist[self.hist_i])
        return "break"

    def _hist_down(self, e=None):
        if self.hist_i < len(self.hist):
            self.hist_i += 1
            self.entry.delete(0, "end")
            if self.hist_i == len(self.hist):
                self.entry.insert(0, self.hist_draft)
            else:
                self.entry.insert(0, self.hist[self.hist_i])
        return "break"

    def send(self):
        try:
            t = self.entry.get().strip()
        except Exception:
            return
        if not t:
            return
        if not self.hist or self.hist[-1] != t:
            self.hist.append(t)
            self.hist = self.hist[-40:]        # 上限 40 条,防膨胀
        self.hist_i = len(self.hist)
        self.entry.delete(0, "end")
        self.log_user(t)
        try:
            self.pet.ask_ai(t)
        except Exception as e:
            self.log_hint(f"发送出错: {str(e)[:60]}")
        if getattr(self.pet, "ai_thinking", False) is True:
            self.show_typing(True)
        self.entry.focus_set()

    def close(self):
        if self._typing is not None:
            try:
                self.win.after_cancel(self._typing)
            except Exception:
                pass
            self._typing = None
        try:
            self.win.destroy()
        except Exception:
            pass


# ---------------- Win32 结构体 ----------------
class _PowerStatus(ctypes.Structure):
    """GetSystemPowerStatus 的 SYSTEM_POWER_STATUS。"""
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]


class _Blend(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class _BMIH(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32)]


class _BMI(ctypes.Structure):
    _fields_ = [("bmiHeader", _BMIH), ("bmiColors", ctypes.c_uint32 * 3)]


WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
ULW_ALPHA = 0x2
GWL_EXSTYLE = -20


# ---------------- 启动 ----------------
def main():
    # DPI awareness 已在 import 阶段设置
    try:
        # 日志限容:超过 1MB 滚动成 .old,避免常年累月无限膨胀
        log_path = os.path.join(HERE, "pet_error.log")
        try:
            if os.path.getsize(log_path) > 1_000_000:
                os.replace(log_path, log_path + ".old")
        except OSError:
            pass
        sys.stderr = open(log_path, "a", encoding="utf-8")
    except Exception:
        pass
    # 开机先把 build 写进日志:排查"改完没生效"的第一凭据
    print(f"[pet] 启动 build={build_stamp()}", file=sys.stderr, flush=True)
    selftest = "--selftest" in sys.argv
    # 单实例保护(selftest 豁免,方便自动化测试):
    # 已有一只小乔在跑时,再次启动只会把旧窗口带到前台,然后自己退出 ——
    # 否则更新/误点都会桌面上出现两只,聊天记录还会被两个进程轮流覆写。
    if not selftest:
        # 单实例:互斥体已存在时,若旧窗口还健康,把旧的带到前台然后自己退出;
        # 若旧窗口已经没了(旧进程正在退出、窗口先销毁),最多等 2 秒重试
        # 拿互斥体 —— 不然"关掉马上再开"会撞上退出竞态,新实例静默消失,
        # 桌面上谁都不剩。
        # 旧窗口"在但没反应"(主循环卡死)则不能退:那样用户点一万次
        # 快捷方式都救不回来 —— 转为等旧进程放手后顶替它。
        k32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
        k32.CreateMutexW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL,
                                     wintypes.LPCWSTR]
        k32.CreateMutexW.restype = wintypes.HANDLE
        u32 = ctypes.WinDLL("user32.dll", use_last_error=True)
        u32.SendMessageTimeoutW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
            wintypes.UINT, wintypes.UINT, ctypes.POINTER(wintypes.DWORD)]
        u32.SendMessageTimeoutW.restype = ctypes.c_size_t   # ULONG_PTR

        def grab_mutex():
            m = k32.CreateMutexW(None, False, "XiaoqiaoPet_SingleInstance")
            globals()["_PET_MUTEX"] = m   # 撑住句柄,进程活着就持有
            return ctypes.get_last_error() != 183   # ERROR_ALREADY_EXISTS

        def wait_and_take(seconds):
            # 等持锁方退出(看门狗 os.execv / 用户手动结束),拿到锁为止
            deadline = time.time() + seconds
            while not grab_mutex():
                if time.time() >= deadline:
                    break            # 超时也硬着头皮继续,避免谁都起不来
                time.sleep(0.2)

        if "--wait-lock" in sys.argv:
            # 看门狗自重启路径:旧进程多半还捏着锁没咽气,等它放手
            wait_and_take(15.0)
        else:
            deadline = time.time() + 2.0
            while not grab_mutex():
                hwnd = ctypes.windll.user32.FindWindowW(None, "小乔 · 时之魔女")
                if hwnd:
                    # 先敲一下旧窗口:两秒内应答的才配当"正在跑的那只"
                    res = wintypes.DWORD()
                    hung = not u32.SendMessageTimeoutW(
                        hwnd, 0x0000, 0, 0,          # WM_NULL
                        0x0002,                      # SMTO_ABORTIFHUNG
                        2000, ctypes.byref(res))
                    if not hung:
                        # 真有另一只健康的在跑:带到前台,自己退出
                        ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                        ctypes.windll.user32.SetForegroundWindow(hwnd)
                        sys.exit(0)
                    # 旧的卡死了:不当第二只,等它退出后顶替
                    wait_and_take(15.0)
                    break
                if time.time() >= deadline:
                    # 等不到也没有旧窗口 —— 超时强行继续,避免谁都起不来
                    break
                time.sleep(0.1)
    root = tk.Tk()
    p = Pet(root, selftest)
    if not selftest:
        # Main entry only: constructing a test Pet never reads native sessions.
        from native_session_sync import start as start_native_sessions
        p._native_session_thread = start_native_sessions(AI_SESSION_DIR)
        p._start_watchdog()   # 主循环卡死看门狗(测试套件直接建 Pet,不经过这里)
    root.mainloop()
    if selftest:
        print("SELFTEST_OK")


if __name__ == "__main__":
    main()
