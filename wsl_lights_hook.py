#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小乔 AI 会话灯的 Codex hook(WSL 侧)。

由 ~/.codex/hooks.json 调用:
    xiaoqiao-lights-hook.py running|done|waiting|action|after
    SessionStart、UserPromptSubmit -> running(SessionStart 只是开了会话,记成空闲)
    Stop -> done;PermissionRequest -> waiting;PreToolUse -> action
    (可选)PostToolUse -> after:在等你的回到 running;Interrupt -> after 也行(记成空闲)。
    注册新 hook 要在 Codex 里重新信任,所以默认没注册;不注册时下一次 PreToolUse 同样会回 running
stdin 是 Codex 的 hook JSON。会话 id 用 hook 给的完整 session_id,没有就取 rollout
文件名里的完整 UUID,再没有就按调用它的 Codex 进程号分开(不把不认识的会话都挤进一盏灯)。
状态写到 Windows 侧小乔的 ai_sessions/(经 /mnt/c),桌宠每 2 秒扫描。
action = PreToolUse:把正在用的工具写成一句人话插到 actions 头部(留 3 条,小乔头顶
「思维链」的数据源);在等你批准时又开始用工具,说明已经批准了,灯回到 running。
整个读改写在 flock 里(锁文件在 WSL 本地,只有 WSL 里的 hook 用),临时文件名带进程号。
Codex 侧没有可靠的「清灯」时机(这里没注册 SessionEnd),写完顺手把 wslcodex-*.json
修剪到最新 8 个,老灯自然熄掉。

安装:改完把本文件拷成 ~/.local/bin/xiaoqiao-lights-hook.py,ai_lights_core.py 拷到同一个目录。
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = "/mnt/c/Users/32447/.zcode/workspace/default/xiaoqiao-2.5d"
DEST = os.path.join(PROJECT, "ai_sessions")
LOCK = os.path.expanduser("~/.cache/xiaoqiao-lights.lock")
KEEP = 8

sys.path.insert(0, HERE)
if PROJECT not in sys.path:
    sys.path.append(PROJECT)          # ~/.local/bin 里没拷 ai_lights_core.py 时,从项目目录拿
try:
    import ai_lights_core as core  # noqa: E402
except Exception:
    core = None


def main():
    try:
        return _main()
    except BaseException:
        return 0               # hook 绝不能因为灯报错


def _main():
    if core is None:
        return 0
    mode = sys.argv[1] if len(sys.argv) > 1 else "done"
    raw = ""
    try:
        if not sys.stdin.isatty():
            raw = sys.stdin.read()
    except Exception:
        pass
    try:
        import json
        j = json.loads(raw)
    except Exception:
        j = None
    if not isinstance(j, dict):
        j = {}
    sid = core.session_id_from(j) or "pid%d" % os.getppid()
    cwd = os.path.basename(str(j.get("cwd") or "").rstrip("/"))[:40]
    event = j.get("hook_event_name") or ""
    try:
        os.makedirs(DEST, exist_ok=True)
        path = os.path.join(DEST, "wslcodex-%s.json" % sid)
        if mode == "after":
            if not os.path.exists(path):
                return 0
            interrupted = event == "Interrupt"
            with core.locked(LOCK):
                data = core.load_json(path)
                new = on_after(data, interrupted)
                if new is not None:
                    core.write_json(path, new)
            return 0
        if mode == "action":
            label = core.action_label(j.get("tool_name"), j.get("tool_input"))
            change = lambda d: on_action(d, sid, cwd, label)
        else:
            state = mode if mode in core.STATES else "idle"
            if mode == "running" and event == "SessionStart":
                state = "idle"
            change = lambda d: on_state(d, sid, cwd, state, new_turn=(state == "running"))
        with core.locked(LOCK):
            core.write_json(path, change(core.load_json(path)))
            trim()
    except Exception:
        pass          # 灯是锦上添花,hook 绝不能因此报错
    return 0


def on_state(data, sid, cwd, state, new_turn):
    data.update({"id": "wslcodex-" + sid, "agent": "wslcodex", "state": state,
                 "title": cwd or data.get("title", ""), "updated": time.time()})
    if new_turn or not isinstance(data.get("actions"), list):
        data["actions"] = []                 # 新的一轮:思维链只画这一轮的
    return data


def on_action(data, sid, cwd, label):
    data.update({"id": "wslcodex-" + sid, "agent": "wslcodex",
                 "title": cwd or data.get("title", "")})
    if label:
        return core.push_action(data, label)
    data["state"] = "running"
    data["updated"] = time.time()
    return data


def on_after(data, interrupted):
    """批准后工具跑起来了:等你的回到 running;你打断了:空闲。别的情况不写(None)。"""
    if interrupted and data.get("state") in ("running", "waiting"):
        data.update({"state": "idle", "updated": time.time()})
        return data
    if data.get("state") == "waiting":
        data.update({"state": "running", "updated": time.time()})
        return data
    return None


def trim():
    files = [(os.path.getmtime(os.path.join(DEST, f)), f)
             for f in os.listdir(DEST) if f.startswith("wslcodex-") and f.endswith(".json")]
    for _, f in sorted(files)[:-KEEP]:
        try:
            os.remove(os.path.join(DEST, f))
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
