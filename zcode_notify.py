# -*- coding: utf-8 -*-
"""ZCode hook -> 小乔播报。

ZCode 在 ~/.zcode/cli/config.json 的 hooks 里配置(process 类型):
    SessionStart     -> python zcode_notify.py start    (会话灯:空闲,只是开了会话)
    UserPromptSubmit -> python zcode_notify.py start    (会话灯:running,新的一轮清空动作)
    Stop             -> python zcode_notify.py stop     (会话灯:done + 播报)
    PermissionRequest-> python zcode_notify.py permission (会话灯:waiting + 播报)
    PreToolUse       -> python zcode_notify.py tool     (思维链加一个动作;在等你时又开始干活=已批准,回 running)
    PostToolUse / PostToolUseFailure -> python zcode_notify.py after(可选,注册了才有:批准的工具一跑起来
                        橙灯就灭;被你打断 is_interrupt 记成空闲。不注册也行,下一个工具调用时同样会回 running)

不管发生什么都以退出码 0 结束:ZCode 把退出码 2 当成「拦下这次操作」,hook 出错不能挡住你干活。

stdin 会收到 hook 的 JSON 输入:播报不看它,但会取 session_id/cwd 写进
ai_sessions/ 的会话状态文件 —— 那是小乔身上"AI 会话灯"的数据源
(pet.py 的 _scan_ai_sessions 每 2 秒扫一遍)。ZCode 没有 SessionEnd
事件,所以 upsert 时顺手把 zcode-*.json 修剪到最新 8 个,旧灯自动熄。
播报本身仍通过写 pet_cmd.json 的 {"op":"announce"} 实现,桌宠渲染循环
每帧检测 mtime,她在桌面右下角冒个气泡就把话带到了。

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

try:
    import ai_lights_core as core
except Exception:          # 公共模块坏了、没拷过来:灯不更新,但 hook 照样安静退出
    core = None

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

SESSIONS_DIR = os.path.join(HERE, "ai_sessions")


def lock_path(sessions_dir, safe=""):
    # 只有本机的 ZCode hook 写 zcode-*.json,锁放在本机临时目录(不放进 ai_sessions/),
    # 一个会话一把:两个 ZCode 会话同时干活互不等;不和 WSL、Mac 同步争同一把锁
    import tempfile
    return os.path.join(tempfile.gettempdir(), "xiaoqiao-zcode-lights-%s.lock" % (safe or "all"))


def read_hook_input():
    """stdin 里的 hook JSON -> (session_id, title, raw, json_obj)。

    解析不了就给个稳定的 "local",灯少一盏总好过 hook 报错。"""
    try:
        raw = "" if sys.stdin.isatty() else sys.stdin.read()
    except Exception:
        raw = ""
    j = None
    try:
        j = json.loads(raw)
    except Exception:
        j = None
    if not isinstance(j, dict):
        return "local", "", raw, None
    sid = str(j.get("session_id") or j.get("sessionId") or "local")[:64]
    cwd = str(j.get("cwd") or "")
    title = os.path.basename(cwd.rstrip("\\/")) if cwd else ""
    return sid, title, raw, j


def tool_brief(j):
    """PreToolUse 输入 -> 一句人话(「跑测试 unittest」「读 pet.py」「命令 git status」)。

    和 Mac 触控栏路线图一个口径(ai_lights_core.action_label):只留工具种类、文件名、
    命令开头,不留完整路径、参数、URL 和环境变量的值 —— 头顶和 ai_sessions/ 里都不会出现密钥。"""
    if not isinstance(j, dict) or core is None:
        return ""
    tool = j.get("tool_name") or j.get("toolName") or j.get("tool") or j.get("name") or ""
    inp = j.get("tool_input") or j.get("toolInput") or j.get("input") or {}
    return core.action_label(tool, inp)


REDACT_RE = None


def result_brief(j, failed=False):
    """PostToolUse 输入 -> 一句安全的 结果摘要(给轨迹页)。

    按工具细化:Read/Write/Edit 只记字符数(内容绝不落盘);Bash 保留
    成败 + 输出里第一条 error/failed/passed 类模式行,截 60 字,并抹掉
    疑似密钥/令牌的赋值段。完整输出、路径、参数一律不落盘 —— 和
    action_label 同一条隐私红线。"""
    if not isinstance(j, dict):
        return ""
    import re
    tool = str(j.get("tool_name") or j.get("toolName") or "")
    resp = j.get("tool_response") or j.get("toolResponse") or {}
    # 读写类工具:只报规模,不碰内容
    if tool in ("Read", "read"):
        n = len(resp) if isinstance(resp, str) else             len(str(resp.get("content") or resp.get("text") or ""))
        return f"读取 {n} 字符" if n else ""
    if tool in ("Write", "write"):
        n = len(resp) if isinstance(resp, str) else             len(str(resp.get("content") or resp.get("text") or ""))
        return f"写入 {n} 字符" if n else "写入完成"
    if tool in ("Edit", "edit"):
        return "编辑完成"
    ok = None
    text = ""
    if isinstance(resp, dict):
        # 常见形态:Bash {stdout, stderr, ...} / 通用 {success, ...}
        if "exitCode" in resp or "exit_code" in resp or "code" in resp:
            code = resp.get("exitCode", resp.get("exit_code", resp.get("code")))
            try:
                ok = (int(code) == 0)
            except Exception:
                ok = None
        text = str(resp.get("stdout") or resp.get("stderr") or
                   resp.get("content") or resp.get("text") or "")
        if not text and any(k in resp for k in ("success", "ok")):
            ok = bool(resp.get("success", resp.get("ok")))
    elif isinstance(resp, str):
        text = resp
    # 模式行:错误/失败/通过 优先,取首行
    line = ""
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            continue
        if re.search(r"error|failed|失败|exception|traceback|passed|通过|✓|✗",
                     s, re.I):
            line = s
            break
    if line:
        # 抹掉疑似密钥赋值:key=xxx / sk-xxx / token: xxx
        line = re.sub(r"((?:sk-|key|token|secret|password|passwd)\s*[=:]\s*)\S+",
                      r"***", line, flags=re.I)[:60]
    if failed:
        ok = False
    if ok is False:
        base = "失败"
    elif ok is True:
        base = "完成"
    else:
        base = "完成" if line else ""
    out = base + ((": " + line) if line else "")
    return out[:72] if out else ""


def update_action(agent, sid, text, title="", sessions_dir=None):
    """把最新动作插到会话文件的 actions 头部(留 3 条),思维链的数据源。

    又开始用工具了就是在干活:原来在等你批准的回到 running(批准后不再一直亮橙灯)。
    整个读改写在锁里,两个 hook 同时来也不丢动作。text 为空(TodoWrite 这类)只恢复状态。"""
    try:
        d = sessions_dir or SESSIONS_DIR
        os.makedirs(d, exist_ok=True)
        safe = core.safe_name(sid)
        path = os.path.join(d, f"{agent}-{safe}.json")

        def change(data):
            data.update({"id": f"{agent}-{safe}", "agent": agent,
                         "title": title or data.get("title", "")})
            if text:
                return core.push_action(data, {"t": time.time(), "a": text})
            if data.get("state") != "running":
                data["state"] = "running"
                data["updated"] = time.time()
            return data
        core.update_json(path, change, lock_path(d, safe))
    except Exception:
        pass


def record_result(agent, sid, brief, failed=False, title="", sessions_dir=None):
    """PostToolUse(-Failure):把 结果摘要 挂到最近一条还没有结果的动作上;
    失败时动作行标红(err=1)。找不到可挂的动作就单记一条。"""
    if not brief:
        return
    try:
        d = sessions_dir or SESSIONS_DIR
        safe = core.safe_name(sid)
        path = os.path.join(d, f"{agent}-{safe}.json")

        def change(data):
            data.update({"id": f"{agent}-{safe}", "agent": agent,
                         "title": title or data.get("title", "")})
            acts = data.get("actions")
            if not isinstance(acts, list):
                acts = []
            for a in acts:
                if isinstance(a, dict) and a.get("a") and not a.get("r") \
                        and not a.get("turn"):
                    a["r"] = brief
                    if failed or brief.startswith("失败"):
                        a["err"] = 1
                    data["updated"] = time.time()
                    return data
            core.push_action(data, {"t": time.time(), "a": "工具调用",
                                    "r": brief,
                                    "err": 1 if (failed or brief.startswith("失败")) else 0})
            return data
        core.update_json(path, change, lock_path(d, safe))
    except Exception:
        pass


def tool_finished(agent, sid, interrupted=False, sessions_dir=None):
    """PostToolUse / PostToolUseFailure:在等你批准的,工具跑起来了说明你点了同意,回 running;
    被你打断的(is_interrupt)记成空闲,动作留着。别的情况不写文件(这个事件每个工具都来,要便宜)。"""
    try:
        d = sessions_dir or SESSIONS_DIR
        safe = core.safe_name(sid)
        path = os.path.join(d, f"{agent}-{safe}.json")
        if not os.path.exists(path):
            return

        def change(data):
            if interrupted and data.get("state") in ("running", "waiting"):
                data.update({"state": "idle", "updated": time.time()})
                return data
            if data.get("state") == "waiting":
                data.update({"state": "running", "updated": time.time()})
                return data
            return None
        core.update_json(path, change, lock_path(d, safe))
    except Exception:
        pass


def upsert_session(agent, sid, state, title="", sessions_dir=None, new_turn=None):
    """写 ai_sessions/<agent>-<sid>.json,给小乔的会话灯供数据。

    桌宠没开也照写:灯是状态记录,下次她醒来直接看到最近的会话。
    new_turn(默认:state 是 running 时)**不清空**上一轮动作 —— 插一条
    轮次标记(轨迹页的分隔线),思维链只读最后一个标记之后的动作。"""
    if new_turn is None:
        new_turn = state == "running"
    try:
        d = sessions_dir or SESSIONS_DIR
        os.makedirs(d, exist_ok=True)
        safe = core.safe_name(sid)
        path = os.path.join(d, f"{agent}-{safe}.json")

        def change(data):
            data.update({"id": f"{agent}-{safe}", "agent": agent, "state": state,
                         "title": title or data.get("title", ""), "updated": time.time()})
            if not isinstance(data.get("actions"), list):
                data["actions"] = []
            if new_turn and not (data["actions"]
                                 and isinstance(data["actions"][0], dict)
                                 and data["actions"][0].get("turn")):
                core.push_action(data, {"t": time.time(), "turn": 1})
            return data
        with core.locked(lock_path(d, safe)):
            core.write_json(path, change(core.load_json(path)))
            if agent == "zcode":
                trim_zcode(d)
    except Exception:
        pass  # 会话灯是锦上添花,盘不可写也不能让 hook 报错


def trim_zcode(sessions_dir=None, keep=8):
    """ZCode 没有 SessionEnd 事件,旧会话文件不会有人删 —— 只留最新
    keep 个 zcode-*.json,老灯自然熄掉,别把最近 5 盏的位置占满。"""
    try:
        d = sessions_dir or SESSIONS_DIR
        files = [(os.path.getmtime(os.path.join(d, f)), f)
                 for f in os.listdir(d) if f.startswith("zcode-") and f.endswith(".json")]
    except OSError:
        return
    for _, f in sorted(files)[:-keep]:
        try:
            os.remove(os.path.join(d, f))
        except OSError:
            pass


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
    try:
        return _main()
    except BaseException:
        return 0               # 退出码 2 会被 ZCode 当成拦截:出什么错都按 0 退出


def _main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--deliver":
        return deliver(random.choice(PERM_LINES), "surprised")

    event = (sys.argv[1] if len(sys.argv) > 1 else "stop").lower()
    sid, title, raw, j = read_hook_input()
    # 原始输入不落盘(里面有你说的话、命令参数);要核对字段名时临时打印字段名就够
    if event == "start":
        # UserPromptSubmit:灯变紫,不播报(每轮都响谁受得了);SessionStart 只是开了会话,还没干活
        opened = isinstance(j, dict) and (j.get("hook_event_name") or j.get("hookEventName")) == "SessionStart"
        upsert_session("zcode", sid, "idle" if opened else "running", title, new_turn=not opened)
        return 0
    if event == "tool":
        # PreToolUse:思维链 —— 她头顶滚动的"正在干什么"
        update_action("zcode", sid, tool_brief(j), title)
        return 0
    if event == "after":
        interrupted = isinstance(j, dict) and bool(j.get("is_interrupt") or j.get("isInterrupt"))
        tool_finished("zcode", sid, interrupted)
        # 轨迹增厚:PostToolUse 带结果摘要;PostToolUseFailure 带错误行
        if isinstance(j, dict) and not interrupted:
            failed = (j.get("hook_event_name") == "PostToolUseFailure"
                      or j.get("hookEventName") == "PostToolUseFailure")
            brief = result_brief(j, failed=bool(failed))
            if failed and not brief:
                err = j.get("error") or j.get("message") or ""
                brief = ("失败: " + str(err).strip()[:52]) if err else "失败"
            if brief:
                record_result("zcode", sid, brief, failed=bool(failed), title=title)
        return 0
    if event == "permission":
        # 要人点头的事不限频,漏一次就可能干等
        upsert_session("zcode", sid, "waiting", title)
        if pet_running():
            announce(random.choice(PERM_LINES), "surprised")
        else:
            try:
                spawn_detached([find_pythonw(), os.path.abspath(__file__),
                                "--deliver"])
            except Exception:
                pass
        return 0

    upsert_session("zcode", sid, "done", title)
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
