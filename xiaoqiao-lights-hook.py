#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小乔 AI 会话灯的 Codex hook(WSL 侧)—— F1 对齐版。

由 ~/.codex/hooks.json 调用:
    xiaoqiao-lights-hook.py running|done|waiting|action|after
    SessionStart、UserPromptSubmit -> running(SessionStart 只是开了会话,记成空闲)
    Stop -> done;PermissionRequest -> waiting;PreToolUse -> action
    PostToolUse -> after:结果摘要挂到最近动作(失败标红);Interrupt -> 空闲。

F1 对齐(与 Windows 侧 zcode_notify 同代):
    动作为 dict {t: 时间戳, a: 动作, r: 结果摘要, err: 失败};
    新一轮不清空动作,插轮次标记 {t, turn:1}(轨迹页的分隔线),
    思维链(pet.ai_chain_lines)只读最后一个标记之后的动作。
    动作留 48 条(与 Windows 侧一致)。

会话 id:hook 给的完整 session_id > rollout 文件 UUID > 调用进程号。
状态写到 Windows 侧 ai_sessions/(经 /mnt/c),桌宠每 2 秒扫描。
隐私红线:不落盘完整输出/路径/参数,结果只留 成败+首条模式行。
安装:拷成 ~/.local/bin/xiaoqiao-lights-hook.py,ai_lights_core.py 同目录。
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = "/mnt/c/Users/32447/.zcode/workspace/default/xiaoqiao-2.5d"
DEST = os.path.join(PROJECT, "ai_sessions")
LOCK = os.path.expanduser("~/.cache/xiaoqiao-lights.lock")
KEEP = 48

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
                new = on_after(data, interrupted, j)
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
    data.update({"id": "wslcodex-" + sid, "agent": "wslcodex",
                 "title": cwd or data.get("title", ""), "updated": time.time()})
    if not isinstance(data.get("actions"), list):
        data["actions"] = []
    # F1:新轮不清空,插轮次标记;思维链只读最后一个标记之后的动作
    if new_turn and not (data["actions"]
                         and isinstance(data["actions"][0], dict)
                         and data["actions"][0].get("turn")):
        core.push_action(data, {"t": time.time(), "turn": 1})
    return data


def on_action(data, sid, cwd, label):
    data.update({"id": "wslcodex-" + sid, "agent": "wslcodex",
                 "title": cwd or data.get("title", "")})
    if label:
        return core.push_action(data, {"t": time.time(), "a": label})
    data["state"] = "running"
    data["updated"] = time.time()
    return data


def result_brief(j):
    """PostToolUse 结果 -> 一句安全摘要(成败;exit 码)。不落盘输出内容。"""
    resp = j.get("tool_response") or {}
    if isinstance(resp, dict):
        code = resp.get("exitCode", resp.get("exit_code"))
        if isinstance(code, int):
            return "完成" if code == 0 else "失败: exit %d" % code
        if any(k in resp for k in ("success", "ok")):
            return "完成" if bool(resp.get("success", resp.get("ok"))) else "失败"
    return "完成"


def on_after(data, interrupted, j):
    """批准后工具跑起来了:等你的回到 running;你打断了:空闲。
    F1:结果摘要挂到最近一条没有结果的动作上(失败标红)。"""
    if interrupted and data.get("state") in ("running", "waiting"):
        data.update({"state": "idle", "updated": time.time()})
        return data
    if isinstance(j, dict) and not interrupted:
        brief = result_brief(j)
        attached = False
        for a in reversed(data.get("actions") or []):
            if isinstance(a, dict) and a.get("a") and not a.get("r") \
                    and not a.get("turn"):
                a["r"] = brief
                if brief.startswith("失败"):
                    a["err"] = 1
                attached = True
                break
        if attached:
            return data          # 结果挂上了必须写盘(旧语义会丢结果)
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
