# -*- coding: utf-8 -*-
"""小乔的执行能力:听懂「打开/关闭/卸载/搜索 XXX」并去做。

设计取舍
--------
1. 本地规则优先。「打开微信」这类说法用正则直接命中,不走 AI —— 快、免费、
   而且不存在模型把软件名理解错的风险。说得绕的时候才由 pet.py 交给 Gemini。
2. 破坏性操作不静默执行。卸载只负责把官方卸载程序调起来,最后那下确认留给人;
   识别错了也就是弹错一个卸载向导,而不是东西已经没了。
3. 匹配不确定就问,不猜。分数接近的候选一并抛回去让用户选。

独立测试:
    py agent.py "打开微信"        # 只解析,不执行
    py agent.py --run "打开微信"  # 真的执行
"""
import os
import re
import subprocess
import sys
import time
import unicodedata

# ---------------- 应用索引 ----------------
_START_MENU = [
    r"%ProgramData%\Microsoft\Windows\Start Menu\Programs",
    r"%APPDATA%\Microsoft\Windows\Start Menu\Programs",
]

# 常见中英别名,避免「打开微信」匹配不到名为 WeChat 的快捷方式
ALIASES = {
    "微信": ["wechat", "weixin"],
    "qq": ["qq", "tencent qq"],
    "浏览器": ["chrome", "edge", "firefox"],
    "谷歌": ["chrome", "google chrome"],
    "记事本": ["notepad"],
    "计算器": ["calc", "calculator"],
    "画图": ["mspaint", "paint"],
    "资源管理器": ["explorer"],
    "任务管理器": ["taskmgr"],
    "控制面板": ["control"],
    "命令行": ["cmd", "terminal", "powershell"],
    "终端": ["terminal", "powershell", "cmd"],
    "b站": ["bilibili", "哔哩哔哩"],
    "网易云": ["cloudmusic", "网易云音乐"],
    "微软商店": ["store", "microsoft store"],
}

# 不需要快捷方式、直接可执行的系统程序
BUILTIN = {
    "notepad": "notepad.exe", "记事本": "notepad.exe",
    "calc": "calc.exe", "计算器": "calc.exe",
    "mspaint": "mspaint.exe", "画图": "mspaint.exe",
    "explorer": "explorer.exe", "资源管理器": "explorer.exe",
    "taskmgr": "taskmgr.exe", "任务管理器": "taskmgr.exe",
    "control": "control.exe", "控制面板": "control.exe",
    "cmd": "cmd.exe", "powershell": "powershell.exe",
    "regedit": "regedit.exe", "注册表": "regedit.exe",
}


# 卸载默认关闭。
# 它是唯一不可逆的能力,而确认框被意外回答过一次(真的卸掉了一个软件),
# 所以分发给别人的版本一律禁用。自己要用就设环境变量 PET_ALLOW_UNINSTALL=1。
ALLOW_UNINSTALL = os.environ.get("PET_ALLOW_UNINSTALL") == "1"


def _ps(script, timeout=40):
    """跑一段 PowerShell 并按 UTF-8 取回输出。

    必须显式指定编码:PowerShell 输出 UTF-8,而 subprocess 默认按系统区域
    (中文机器上是 GBK)解码,注册表里但凡有个 GBK 编不出的字符就会抛
    UnicodeDecodeError,整个调用静默失败。
    """
    full = ("[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; " + script)
    # stdin 必须显式给 DEVNULL:桌宠跑在 pythonw.exe 下没有控制台,标准句柄
    # 是无效的,子进程继承过去会直接起不来(而且失败得很安静)。
    # CREATE_NO_WINDOW 则是别让黑框一闪而过。
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", full],
            stdin=subprocess.DEVNULL, capture_output=True,
            timeout=timeout, creationflags=flags)
        return out.stdout.decode("utf-8", errors="replace")
    except Exception as e:
        # 不要静默吞掉 —— 之前就是这里把 pythonw 下的启动失败藏起来了。
        # 直接打到 stderr(pet.py 的 main 会把它接进 pet_error.log),
        # 以前存的 LAST_ERROR 没有任何读取方,纯死通道
        print(f"[agent] PowerShell 执行失败: {type(e).__name__}: {e}")
        return ""


def _norm(s):
    """归一化:全角转半角、去空格标点、转小写。"""
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"[\s\-_.()（）\[\]【】]+", "", s)


class AppIndex:
    def __init__(self):
        self.apps = {}      # 展示名 -> 快捷方式/可执行文件路径
        self._built = False
        self.built_at = 0.0  # 索引扫描完成的时间戳(notfound 时按它节流重扫)

    def build(self, force=False):
        if self._built and not force:
            return self
        import glob
        seen = {}
        for root in _START_MENU:
            root = os.path.expandvars(root)
            if not os.path.isdir(root):
                continue
            for p in glob.glob(os.path.join(root, "**", "*.lnk"), recursive=True):
                name = os.path.splitext(os.path.basename(p))[0]
                seen.setdefault(name, p)
        # 桌面快捷方式(用户自己放的,优先级更高)
        for d in (os.path.join(os.path.expanduser("~"), "Desktop"),
                  os.path.expandvars(r"%PUBLIC%\Desktop")):
            if os.path.isdir(d):
                for f in os.listdir(d):
                    if f.lower().endswith(".lnk"):
                        seen[os.path.splitext(f)[0]] = os.path.join(d, f)
        self.apps = seen
        self._built = True
        self.built_at = time.time()
        return self

    def find(self, query, limit=4):
        """返回 [(分数, 展示名, 路径)],分数越高越像。"""
        self.build()
        q = _norm(query)
        if not q:
            return []
        cands = set(ALIASES.get(query.strip().lower(), []))
        cands.add(q)

        scored = []
        for name, path in self.apps.items():
            n = _norm(name)
            best = 0
            for c in cands:
                c = _norm(c)
                if not c:
                    continue
                if n == c:
                    best = max(best, 100)
                elif n.startswith(c):
                    best = max(best, 85 - min(20, len(n) - len(c)))
                elif c in n:
                    best = max(best, 70 - min(20, len(n) - len(c)))
                elif n in c:
                    best = max(best, 60)
            if best:
                scored.append((best, name, path))
        scored.sort(reverse=True)
        return scored[:limit]


_INDEX = AppIndex()
_INDEX_RESCAN_MIN = 300.0   # notfound 触发重扫的节流间隔(秒)


# ---------------- 意图解析 ----------------
# 中文里宾语经常前置(「把学习通卸载掉」),所以每类动作都要同时覆盖
# 「动词+宾语」和「(把)宾语+动词」两种语序,只写前者会漏掉一大半说法,
# 然后这些话就落给 AI —— 而 AI 没有执行能力,只会嘴上答应「好的」。
_VERBS = {
    "open":      r"打开|开一?下|开启|启动|运行|来一?个|open|start",
    "close":     r"关闭|关掉|关一?下|退出|结束|close|quit",
    "uninstall": r"卸载|卸掉|删除软件|删掉|删了|uninstall",
    "search":    r"搜索|搜|查|百度|google|search",
    "folder":    r"打开文件夹|去",
}
# 前缀:帮我 / 我想 / 能不能 / 可以 ; 后缀语气:一下 / 掉 / 了 / 吧
_PRE = r"(?:帮我|替我|给我|我想|我要|能不能|可以|麻烦你?)?\s*"
_TAIL = r"(?:一?下|掉|了|吧|嘛|呗)*[!!。.~\s]*"

_PATTERNS = []
for _k, _v in _VERBS.items():
    # 动词在前:打开微信 / 搜索一下 XXX(动词后可能跟"一下""一个")
    _PATTERNS.append((_k, rf"^{_PRE}(?:{_v})(?:一?下|一?个)?\s*(.+?){_TAIL}$"))
for _k, _v in _VERBS.items():
    # 宾语在前:把学习通卸载掉 / 学习通卸载一下
    _PATTERNS.append((_k, rf"^{_PRE}(?:把|将)?\s*(.+?)\s*(?:{_v}){_TAIL}$"))

# 目标里常混进位置/指代词,注册表和快捷方式名里都没有它们
_NOISE = re.compile(
    r"^(?:那个|这个|一个|我的|电脑(?:里|上)?的?|桌面(?:上|里)?的?|"
    r"开始菜单(?:里|上)?的?|系统(?:里|上)?的?)+")

# 「打开下载文件夹」会被 open 规则先匹配到,靠这个后处理纠正
_FOLDER_SUFFIX = re.compile(r"(.+?)(?:文件夹|目录)$")

# 说话里可能带前缀称呼
_CALL = re.compile(r"^\s*(?:小乔|喂|嘿|hey)?[,,、\s]*")

# 「帮我找一下叫ai-workspace的文件」→ find_file 意图
_FIND_FILE = re.compile(
    r"^(?:帮我|替我|给我|麻烦你?)?\s*"
    r"(?:找(?:一?下|找找|到)?|查找|find)\s*"
    r"(?:叫|叫做|名为|名字是|名字叫)?\s*"
    r"(?P<name>.+?)"
    r"(?:这个?文件|文件夹)?"
    r"(?:一?下|掉|了|吧|嘛|呗)*[!!。.~\s]*$", re.I)
# 目标得看着像个文件名:带扩展名,或者话里出现了「文件/文件夹」这类词
_FILEISH = re.compile(
    r"\.(txt|docx?|xlsx?|pptx?|pdf|md|csv|tsv|json|ya?ml|xml|html?|css|js|py|"
    r"zip|rar|7z|exe|lnk|mp3|mp4|wav|jpg|jpeg|png|gif|webp|sql|ipynb|iso)\b", re.I)
_FILE_WORDS = re.compile(r"文件|文件夹|图片|视频|音乐|安装包", re.I)


def parse(text):
    """把一句话解析成意图。命中返回 dict,否则 None(交给 AI 兜底)。"""
    t = _CALL.sub("", (text or "").strip())
    # 找文件先于通用规则:必须出现「文件」字样或常见扩展名才算,
    # 免得「帮我找个方法」也被当成搜文件
    m = _FIND_FILE.match(t)
    if m:
        name = _NOISE.sub("", m.group("name").strip()).strip(" \"'“”")
        name = re.sub(r"^(?:一?个|这个|那个|我的)\s*", "", name)
        name = re.sub(r"(?:这?个?)?文件$", "", name)
        name = re.sub(r"的?(?:图片|视频|音乐|安装包)$", "", name).strip()
        if name and (_FILEISH.search(name) or _FILE_WORDS.search(t)):
            return {"kind": "find_file", "target": name, "raw": text}
    # 专属短语,必须先于通用规则:「来个番茄钟」会被 open 的「来一个」
    # 抢先误判成"打开番茄钟";提醒要单独抠出分钟数,AI 兜底要多花一次
    # 调用和一秒延迟,而这几句恰恰是使用说明里写明的招牌用法。
    m = re.match(
        r"^(?:帮我|给我|请)?(?:来一?个|开一?个|启动|想|要)?\s*"
        r"番茄钟(?:模式|专注)?$", t)
    if m:
        return {"kind": "pomo", "target": "番茄钟", "raw": text}
    m = re.match(r"^(?:帮我)?翻译(?:一下)?剪贴板$", t)
    if m:
        return {"kind": "translate", "target": "剪贴板", "raw": text}
    m = re.match(r"^(?:帮我)?(?:总结|看看)一下?剪贴板$", t)
    if m:
        return {"kind": "clipboard", "target": "剪贴板", "raw": text}
    r = _remind_parse(t)
    if r:
        return {"kind": "remind", "target": r[1], "minutes": r[0], "raw": text}
    for kind, pat in _PATTERNS:
        m = re.match(pat, t, re.I)
        if m:
            target = _NOISE.sub("", m.group(1).strip()).strip()
            if not target:
                continue
            # 「打开XX文件夹」按文件夹处理,而不是去应用索引里找一个叫
            # 「XX文件夹」的程序
            if kind == "open":
                fm = _FOLDER_SUFFIX.match(target)
                if fm:
                    return {"kind": "folder", "target": fm.group(1).strip(),
                            "raw": text}
            return {"kind": kind, "target": target, "raw": text}
    return None


# ---------------- 执行 ----------------
# 两种语序:时间在前(5分钟后提醒我喝水) / 提醒在前(提醒我10分钟后站起来)
_REMIND_NUM = re.compile(
    r"^(?:提醒我?\s*)?(\d+(?:\.\d+)?)\s*(分钟|小时|秒)\s*(?:之|过)?后,?"
    r"(?:提醒我?(?:去|要|记得)?)?\s*(.+)$")
_REMIND_HALF = re.compile(
    r"^(?:提醒我?\s*)?半\s*(小时|分钟)\s*(?:之|过)?后,?"
    r"(?:提醒我?(?:去|要|记得)?)?\s*(.+)$")
_UNIT_MIN = {"分钟": 1.0, "小时": 60.0, "秒": 1.0 / 60}


def _remind_parse(t):
    """「(N分钟|N小时|N秒|半小时)后提醒我…」-> (分钟数, 事项) 或 None。

    AI 兜底虽然也能出提醒,但要多花一次调用和一秒延迟 —— 这是使用说明
    里写明的招牌用法,值得本地直出。"""
    for pat, conv in ((_REMIND_NUM, None), (_REMIND_HALF, "half")):
        m = pat.match(t)
        if not m:
            continue
        if conv:
            return (30.0 if m.group(1) == "小时" else 0.5,
                    m.group(2).strip())
        return (float(m.group(1)) * _UNIT_MIN[m.group(2)],
                m.group(3).strip())
    return None


def resolve_app(target):
    """返回 (状态, 数据)。状态: ok / ambiguous / notfound"""
    key = _norm(target)
    for k, exe in BUILTIN.items():
        if _norm(k) == key:
            return "ok", (target, exe)
    hits = _INDEX.find(target)
    if not hits:
        # 索引是启动后扫的一次快照,之后新装的软件会一直"找不到" ——
        # notfound 且索引超过 5 分钟没更新时,重扫一遍开始菜单再试一次
        # (带节流,目标名乱敲也不会反复全盘扫描)
        if time.time() - _INDEX.built_at > _INDEX_RESCAN_MIN:
            _INDEX.build(force=True)
            hits = _INDEX.find(target)
        if not hits:
            return "notfound", None
    if len(hits) > 1 and hits[0][0] - hits[1][0] < 12:
        return "ambiguous", [(n, p) for _, n, p in hits]
    return "ok", (hits[0][1], hits[0][2])


def open_app(target):
    st, data = resolve_app(target)
    if st == "notfound":
        return False, f"没找到叫「{target}」的程序…"
    if st == "ambiguous":
        names = " / ".join(n for n, _ in data[:3])
        return False, f"有好几个都像:{names},你说的是哪个?"
    name, path = data
    try:
        os.startfile(path)
        return True, f"好的,已经打开「{name}」啦~"
    except Exception as e:
        return False, f"打开「{name}」失败了:{str(e)[:60]}"


def _ps_name(name):
    """把进程名安全地放进 PowerShell 单引号串。

    单引号串里唯一要转义的就是 ' 本身(翻倍成 '')—— AI 文本/快捷方式
    解析出的名字都可能带。不要用 Get-Process -Name + 反引号转义通配符:
    -Name 的通配符引擎不认单引号串里的反引号,「关闭 a*b」会误伤一批进程,
    所以匹配改走 Where-Object -eq(字面比较)。"""
    return name.replace("'", "''")


def close_app(target):
    """温和关闭:先发 WM_CLOSE 让程序自己保存,不直接强杀。"""
    st, data = resolve_app(target)
    name = data[0] if st == "ok" else target
    exe = None
    if st == "ok":
        path = data[1]
        exe = os.path.splitext(os.path.basename(_lnk_target(path) or path))[0]
    exe = exe or target
    safe = _ps_name(exe)
    ps = ("$p = Get-Process -ErrorAction SilentlyContinue | "
          f"Where-Object {{ $_.ProcessName -eq '{safe}' }}; "
          "if ($p) { $p | ForEach-Object { $_.CloseMainWindow() | Out-Null }; "
          "'closed' } else { 'none' }")
    if "closed" in _ps(ps, timeout=20):
        return True, f"已经帮你关掉「{name}」了~"
    return False, f"「{name}」好像没在运行呀"


def _lnk_target(lnk):
    """读取 .lnk 指向的真实可执行文件。"""
    if not lnk.lower().endswith(".lnk"):
        return lnk
    # 路径同样可能带单引号(比如 It's App.lnk),进单引号串前必须转义
    safe = _ps_name(lnk)
    ps = (f"$s=New-Object -ComObject WScript.Shell; "
          f"$s.CreateShortcut('{safe}').TargetPath")
    return (_ps(ps, timeout=20) or "").strip() or None


def find_uninstaller(target):
    """在注册表里找卸载项。返回 [(显示名, 卸载命令)]。"""
    ps = r"""
$paths = @(
 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*')
Get-ItemProperty $paths -ErrorAction SilentlyContinue |
  Where-Object { $_.DisplayName } |
  Select-Object DisplayName, UninstallString |
  ConvertTo-Json -Compress
"""
    import json
    try:
        data = json.loads(_ps(ps) or "[]")
        if isinstance(data, dict):
            data = [data]
    except Exception:
        return []
    q = _norm(target)
    hits = []
    for it in data:
        name = it.get("DisplayName") or ""
        if q and q in _norm(name):
            hits.append((name, it.get("UninstallString") or ""))
    return hits


def uninstall_app(target):
    """不直接卸载 —— 只把官方卸载程序调起来,最终确认由用户点。

    识别错了顶多是弹错一个卸载向导,而不是软件已经没了。
    """
    hits = find_uninstaller(target)
    if not hits:
        # 退而求其次:打开「应用和功能」让用户自己找
        try:
            os.startfile("ms-settings:appsfeatures")
            return True, f"没在注册表里找到「{target}」,我把「应用和功能」打开了,你看看?"
        except Exception:
            return False, f"没找到「{target}」的卸载程序…"
    if len(hits) > 1:
        names = " / ".join(n for n, _ in hits[:3])
        return False, f"找到好几个:{names},你说的是哪个?"
    name, cmd = hits[0]
    if not cmd:
        return False, f"「{name}」没提供卸载命令…"
    return "confirm", (name, cmd)


def run_uninstaller(cmd):
    """不再直接运行卸载器 —— 只在资源管理器里把它定位出来,由人自己双击。

    之前这里是 Popen(cmd),结果测试时把哔哩哔哩真卸干净了:一是那个确认
    对话框会被杂散事件answered,二是国产卸载器往往静默跑完,并不像我预期
    的那样还要逐步点击。删东西这一下必须落在人手上。
    """
    m = re.match(r'^"([^"]+)"|^(\S+\.exe)', (cmd or "").strip(), re.I)
    path = (m.group(1) or m.group(2)) if m else None
    try:
        if path and os.path.exists(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            os.startfile("ms-settings:appsfeatures")
        return True
    except Exception:
        return False


def web_search(target):
    import urllib.parse
    url = "https://www.bing.com/search?q=" + urllib.parse.quote(target)
    try:
        os.startfile(url)
        return True, f"帮你搜「{target}」啦~"
    except Exception as e:
        return False, f"搜索失败:{str(e)[:60]}"


def open_folder(target):
    cands = {
        "桌面": os.path.join(os.path.expanduser("~"), "Desktop"),
        "下载": os.path.join(os.path.expanduser("~"), "Downloads"),
        "文档": os.path.join(os.path.expanduser("~"), "Documents"),
        "图片": os.path.join(os.path.expanduser("~"), "Pictures"),
    }
    p = cands.get(target.strip()) or (target if os.path.isdir(target) else None)
    if not p:
        return False, f"没找到「{target}」这个文件夹"
    os.startfile(p)
    return True, f"打开「{target}」啦~"


# ---------------- 文件搜索(纯逻辑,可放线程里跑) ----------------
# 常见用户目录的 KNOWNFOLDERID —— 用 shell API 拿真实路径,
# 因为这台机器的下载/文档很可能被重定向到 D 盘,C:\Users 下是空的
_KNOWN_FOLDERS = [
    "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",  # Desktop
    "FDD39AD0-238F-46AF-ADB4-6C85480369C7",  # Documents
    "374DE290-123F-4565-9164-39C4925E467B",  # Downloads
    "33E28130-4E1E-4676-835A-98395C3BC3BB",  # Pictures
]
# 这些目录又深又不可能藏着用户找的东西,剪掉省时间
_PRUNE_DIRS = {"node_modules", "__pycache__", ".git", "appdata", "venv",
               "site-packages", "$recycle.bin", "system volume information"}


def _search_roots():
    roots, seen = [], set()
    try:
        import ctypes
        import uuid
        from ctypes import wintypes
        buf = wintypes.LPWSTR()
        shell32 = ctypes.windll.shell32
        for s in _KNOWN_FOLDERS:
            # SHGetKnownFolderPath 要的是 16 字节 GUID;uuid 的 bytes_le
            # 正好就是 Windows GUID 的内存布局
            g = (ctypes.c_ubyte * 16)(*uuid.UUID(s).bytes_le)
            if shell32.SHGetKnownFolderPath(g, 0, None, ctypes.byref(buf)) == 0 \
                    and buf.value:
                p = buf.value          # 先拷成 str 再释放缓冲区
                ctypes.windll.ole32.CoTaskMemFree(buf)
                if p not in seen and os.path.isdir(p):
                    roots.append(p)
                    seen.add(p)
    except Exception:
        pass
    home = os.path.expanduser("~")
    for sub in ("Desktop", "Documents", "Downloads", "Pictures"):
        p = os.path.join(home, sub)
        if p not in seen and os.path.isdir(p):
            roots.append(p)
            seen.add(p)
    return roots


def find_files(name, limit=12, time_budget=8.0):
    """按文件名子串在常见用户目录里搜。只读不删,返回 [路径]。

    走 os.walk + 时间预算,不依赖 Windows Search 服务(很多机器是关的)。
    调用方应放在线程里跑,别堵 UI。
    """
    q = _norm(name)
    if not q:
        return []
    hits, deadline = [], time.time() + time_budget
    for root in _search_roots():
        if time.time() > deadline:
            break
        for dirpath, dirs, files in os.walk(root):
            if time.time() > deadline:
                break
            dirs[:] = [d for d in dirs
                       if d.lower() not in _PRUNE_DIRS and not d.startswith(("."))]
            for f in files:
                if q in _norm(f):
                    hits.append(os.path.join(dirpath, f))
                    if len(hits) >= limit:
                        return hits
            for d in dirs:
                if q in _norm(d):
                    hits.append(os.path.join(dirpath, d) + os.sep)
                    if len(hits) >= limit:
                        return hits
    return hits


def execute(intent):
    """执行意图。返回 (ok, 说的话) 或 ('confirm', (名字, 命令))。"""
    kind, target = intent["kind"], intent["target"]
    if kind == "uninstall" and not ALLOW_UNINSTALL:
        return False, ("卸载这种事我不敢乱来~ 你自己去「设置 → 应用」里操作会更稳妥。"
                       f"要我帮你把「{target}」的卸载页面打开吗?")
    if kind == "open":
        return open_app(target)
    if kind == "close":
        return close_app(target)
    if kind == "uninstall":
        return uninstall_app(target)
    if kind == "search":
        return web_search(target)
    if kind == "folder":
        return open_folder(target)
    return False, "这个我还不会呢…"


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--run"]
    do_run = "--run" in sys.argv
    text = " ".join(args)
    it = parse(text)
    print("解析:", it)
    if it:
        if it["kind"] == "open":
            print("候选:", _INDEX.find(it["target"]))
        if do_run:
            print("执行:", execute(it))
