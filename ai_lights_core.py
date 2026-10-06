# -*- coding: utf-8 -*-
"""会话灯数据层的公共部分:hook 脚本(本机 ZCode、WSL Codex)和 Mac 同步都用。

- action_label():工具调用 -> 一句人话(「读 pet.py」「跑测试 pytest」「命令 git status」),
  和 Mac 触控栏路线图一个口径。只留工具种类、文件名、命令开头:不留完整路径、
  不留环境变量的值、不留 URL 的查询串、不留命令后面的参数,头顶和缓存里都不会出现密钥。
- locked() + update_json():一个会话文件的「读 → 改 → 写」整个包在跨进程锁里,
  临时文件名带进程号,写完原子替换。两个 hook 同时来也不会丢动作或状态。
- session_id_from():优先 hook 给的完整 session_id;没有就从 rollout 文件名里取完整 UUID。
"""
import contextlib
import json
import os
import re
import time

from task_directions import delegation_label

STATES = ("running", "waiting", "done", "error", "idle")

_TEST = ("pytest", "unittest", "test.sh", "npm test", "pnpm test", "yarn test", "bun test", "go test",
         "cargo test", "swift test", "jest", "vitest", "mvn test", "gradle test", "make test", "make check")
_BUILD = ("build.sh", "swift build", "npm run build", "pnpm build", "pnpm run build", "yarn build",
          "cargo build", "go build", "xcodebuild", "tsc", "make", "msbuild", "dotnet build", "csc", "gradle build")
_READ = ("cat", "head", "tail", "less", "more", "type", "get-content", "gc", "nl", "wc")
_SEARCH = ("grep", "rg", "egrep", "fgrep", "ag", "findstr", "select-string", "find", "fd", "ls", "dir", "tree",
           "get-childitem", "gci")
_QUIET = ("export", "env", "set", "unset", "declare", "setx")
# 第二个词只在「主命令 + 子命令」的程序后面写(git status、npm install),和 Mac 触控栏一个口径;
# 别的程序后面的词可能是密码(sshpass -p …、redis-cli -a …)、连接串、要 echo 的内容,一律不写
_SUBCOMMAND = ("git", "npm", "pnpm", "yarn", "bun", "npx", "pip", "pip3", "uv", "poetry", "docker", "kubectl", "cargo",
               "go", "swift", "dotnet", "brew", "apt", "gh", "make", "python", "python3", "py", "node", "deno", "ruby",
               "bash", "sh", "zsh", "powershell", "pwsh", "winget", "wsl", "conda")


def base(path):
    """完整路径 -> 文件名(Windows 和 POSIX 的分隔符都认)。"""
    p = str(path or "").strip().strip("\"'").rstrip("\\/")
    return re.split(r"[\\/]", p)[-1] if p else ""


def _short(text, n=24):
    t = str(text or "").splitlines()[0].strip() if text else ""
    return t if len(t) <= n else t[:n - 1] + "…"


def _words(segment):
    """一段命令拆成词:去掉引号,丢掉开头的环境变量赋值。"""
    words = [w.strip("\"'") for w in re.findall(r'"[^"]*"|\'[^\']*\'|\S+', segment)]
    # 开头的环境变量赋值(FOO=1、PowerShell 的 $env:KEY='…'、$token=…)都丢掉
    while words and re.match(r"^\$?[A-Za-z_][A-Za-z0-9_:]*=", words[0]):
        words.pop(0)
    return words


def _safe_word(text):
    """像标识符、文件名的短词才写出来;像密钥(全大写长串、长数字)的不写。"""
    t = str(text or "")
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,23}", t)) and not re.search(r"\d{4,}", t) and not (len(t) > 8 and t.isupper())


def command_label(command):
    """一条 shell 命令 -> 「跑测试 pytest」「读 pet.py」「命令 git status」。"""
    text = str(command or "").strip()
    if not text:
        return "命令"
    first_line = text.splitlines()[0]
    segments = [s for s in re.split(r"&&|\|\||;|\|", first_line) if s.strip()]
    words = []
    for seg in segments:                               # 跳过 cd / pushd 这种只是换目录的
        seg = re.sub(r"\d*(?:>>?|<<?)\s*&?\d*\s*[^\s;&|]*", " ", seg)   # 去掉重定向(2>&1、> 文件、<<EOF)
        w = _words(seg)
        if w and w[0].lower() not in ("cd", "pushd", "set-location", "sl"):
            words = w
            break
    if not words:
        return "命令"
    head = words[0]
    prog = base(head).lower()
    if prog.endswith(".exe"):
        prog = prog[:-4]
    if not re.fullmatch(r"[a-z0-9._+-]{1,24}", prog):
        return "命令"                                   # 程序名本身就怪(变量、引号里的一段话):什么都不写
    lowered = " ".join([prog] + [w.lower() for w in words[1:4]])
    # Python interpreter flags can push -m unittest past that short prefix.
    # Recognize the executable target only: a file read/echo mentioning tests
    # must not become a test phase, and command arguments never enter the UI.
    if prog in ('python', 'python3', 'py'):
        rest = words[1:]
        while rest:
            arg = rest.pop(0)
            if arg in ('-X', '-W'):
                if rest:rest.pop(0)
                continue
            if arg == '-m':
                module = rest[0].lower() if rest else ''
                if module in ('pytest', 'unittest'):
                    return '跑测试 ' + module
                break
            if arg == '-c':break
            if arg.startswith('-'):continue
            if re.fullmatch(r'test[_-][A-Za-z0-9_.-]+\.py', base(arg)):
                return '跑测试 Python'
            break
    if prog in _QUIET:
        return "命令 " + prog                          # export TOKEN=… 只写命令名
    for name in _TEST:
        if re.search(r"(^|[\s/\\])" + re.escape(name) + r"($|\s)", lowered):
            return "跑测试 " + name
    for name in _BUILD:
        if re.search(r"(^|[\s/\\])" + re.escape(name) + r"($|\s)", lowered):
            return "构建 " + name
    if prog in ("ssh",):
        return "远程 " + _short(words[1], 16) if len(words) > 1 and not words[1].startswith("-") else "远程"
    args = [w for w in words[1:] if not w.startswith("-") and "=" not in w]
    # cat > 文件 <<EOF、echo … >> 文件、tee 文件:是在写文件,不是读(2>&1、> /dev/null 不算)
    unquoted = re.sub(r'"[^"]*"|\'[^\']*\'', "_", first_line)     # 引号里的 > 不是重定向(echo "=> done")
    m = re.search(r"(?<![0-9&>])>>?\s*([^\s;&|<>'\"]+)", unquoted)
    target = m.group(1) if m and not m.group(1).startswith("&") and m.group(1) not in ("/dev/null", "nul", "NUL") else ""
    if prog in ("cat", "echo", "printf", "tee") and (target or prog == "tee"):
        return ("写 " + base(target or (args[0] if args else ""))).strip()
    if prog in _READ and args:
        name = base(args[-1])
        return "读 " + name if _safe_word(name) else "读"
    if prog in _SEARCH:
        # 要搜的内容可能是密钥、你说的话:只在像标识符时写出来
        what = args[0] if args and prog not in ("ls", "dir", "tree", "get-childitem", "gci", "find", "fd") else ""
        return "搜索" + (" " + what if _safe_word(what) else "")
    second = args[0] if prog in _SUBCOMMAND and args and _safe_word(args[0]) else ""
    return ("命令 " + prog + (" " + second if second else "")).strip()


def action_label(tool, tool_input):
    """工具调用 -> 一句人话。TodoWrite 是计划不是动作,返回空串(不记)。"""
    tool = str(tool or "").strip()
    if not tool:
        return ""
    delegated = delegation_label(tool, tool_input)
    if delegated:
        return delegated
    inp = tool_input if isinstance(tool_input, dict) else {}
    path = inp.get("file_path") or inp.get("notebook_path") or inp.get("path") or ""
    if tool in ("TodoWrite", "update_plan"):
        return ""
    if tool in ("Read", "NotebookRead", "view_image", "ReadFile"):
        return ("读 " + base(path)).strip()
    if tool in ("Edit", "MultiEdit", "NotebookEdit", "StrReplace", "apply_patch"):
        if not path and isinstance(inp.get("input"), str):
            m = re.search(r"\*\*\* (?:Update|Add|Delete) File: (\S+)", inp["input"])
            path = m.group(1) if m else ""
        return ("改 " + base(path)).strip()
    if tool in ("Write", "WriteFile", "Create"):
        return ("写 " + base(path)).strip()
    if tool in ("Grep", "Glob", "Search", "LS"):
        what = inp.get("pattern") or inp.get("query") or ""
        return "搜索 " + what if _safe_word(what) else "搜索"
    if tool == "WebFetch":
        return "读网页"
    if tool in ("WebSearch", "web_search"):
        return "搜网页"
    if tool in ("TaskOutput", "BashOutput", "wait"):
        return "等结果"
    if tool in ("AskUserQuestion", "request_user_input"):
        return "问你问题"
    if tool in ("Bash", "shell", "exec_command", "local_shell", "PowerShell", "Shell"):
        cmd = inp.get("command") or inp.get("cmd") or ""
        if isinstance(cmd, list):
            cmd = cmd[-1] if cmd else ""
        return command_label(cmd)
    if tool.startswith("mcp__"):
        name = tool.split("__")[-1]
        return "调用工具 " + name if _safe_word(name) else "调用工具"
    return tool if _safe_word(tool) else "工具"


def safe_name(text):
    return "".join(c if (c.isalnum() or c in "-_") else "_" for c in str(text))[:80]


def session_id_from(hook):
    """hook 输入 -> 会话 id:完整 session_id 优先,再看 rollout 文件名里的完整 UUID;都没有返回 None。"""
    if not isinstance(hook, dict):
        return None
    sid = hook.get("session_id") or hook.get("sessionId")
    if sid:
        return safe_name(sid)
    name = base(hook.get("transcript_path") or hook.get("transcriptPath") or "")
    m = re.search(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\.jsonl$", name)
    return m.group(1) if m else None


@contextlib.contextmanager
def locked(lock_path, wait=1.5):
    """跨进程锁(Windows 用 msvcrt,Linux 用 flock),最多等 wait 秒,每 25 毫秒试一次。
    拿不到锁也照样往下走:灯是锦上添花,hook 不能卡住(ZCode 的 hook 超时是 5 秒)。"""
    f = None
    try:
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
        f = open(lock_path, "a+")
        deadline = time.time() + wait
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.time() >= deadline:
                    break
                time.sleep(0.025)
    except Exception:
        pass
    try:
        yield
    finally:
        if f is not None:
            try:
                if os.name == "nt":
                    import msvcrt
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            except Exception:
                pass
            f.close()


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_json(path, data, tries=8):
    """唯一的临时文件名 + 原子替换。Windows 上桌宠正好开着这个文件读时替换会失败:隔 30 毫秒重试几次;
    最后还是失败就删掉临时文件、把错误抛给调用方。"""
    tmp = "%s.%d.%d.tmp" % (path, os.getpid(), int(time.time() * 1000000) % 1000000000)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        for attempt in range(tries):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == tries - 1:
                    raise
                time.sleep(0.03)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def update_json(path, change, lock_path):
    """在锁里读 → change(data) 改 → 写。change 返回 None 表示不写。"""
    with locked(lock_path):
        data = load_json(path)
        new = change(data)
        if new is not None:
            write_json(path, new)
        return new


def push_action(data, label, keep=48):
    """动作插到最前面(新的在前,留 keep 条);在等你时又开始干活了,说明已经批准:回到 running。

    动作支持两种形态:str(旧格式,兼容)或 dict
    {"t": 时间戳, "a": 动作, "r": 结果摘要(可缺), "err": 失败(可缺),
     "turn": 1(轮次标记,可缺)} —— 轨迹页的时间/结果/轮次分隔靠它。"""
    def same(a):
        if isinstance(label, dict):
            return isinstance(a, dict) and a.get("a") == label.get("a") and not a.get("r") and not a.get("turn")
        return (a == label) if isinstance(a, str) else a.get("a") == label
    acts = [a for a in (data.get("actions") or []) if not same(a)]
    data["actions"] = ([label] + acts)[:keep]
    state = data.get("state")
    data["state"] = "running" if state in (None, "waiting", "done", "idle") or state not in STATES else state
    data["updated"] = time.time()
    return data
