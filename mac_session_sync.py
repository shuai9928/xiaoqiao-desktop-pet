# -*- coding: utf-8 -*-
"""把 Mac 上 AIQuota 的会话状态和思维链拉到本地 ai_sessions/,给小乔当双机会话灯。

用法:
    python mac_session_sync.py --loop   常驻:Mac 上有在跑/等你的会话时 30 秒一轮,没有 120 秒,拉不到退避 300 秒
    python mac_session_sync.py          只拉一次(测试/手动)

走 WSL 里的 Tailscale `ssh mac`(见 ~/two-machine-setup.md),在 Mac 上跑
`AIQuota --sessions-json`:一次拿到所有还亮着灯的会话(Claude / Codex / ZCode),
在跑、等你、出错的那几条还带这一轮的路线图(steps)和最近三步(actions,新的在前,
小乔头顶的思维链直接用)。只有工具种类、文件名、命令开头,没有对话内容。

拉到一份完整的快照就对账:快照里有的写成 mac-<agent>-<id>.json,没有的 mac-*.json 删掉
(Mac 上会话结束、灯过期了,这边跟着熄)。空列表也算成功(Mac 上没有亮着的)。
拉不到(Mac 离线是常态,Tailscale 按需开关省电)就安静等下一轮,绝不刷日志;
超过 10 分钟没拉到,mac-*.json 标 stale、状态改成空闲(记下原来的 lastState)——
看不到的东西不能继续当实时的橙灯红灯闪。
"""
import json
import os
import re
import subprocess
import sys
import time

import ai_lights_core as core

HERE = os.path.dirname(os.path.abspath(__file__))
SESSIONS_DIR = os.path.join(HERE, "ai_sessions")
STATE_NAME = ".mac_sync_state"      # 上次拉到的时间;不以 .json 结尾,桌宠不把它当会话
REMOTE = '"$HOME/Applications/AIQuota.app/Contents/MacOS/AIQuota" --sessions-json'
# ssh 走 WSL:Windows 原生没有 Tailscale,100.x 只在 WSL 里可达
SSH_CMD = ["wsl.exe", "-d", "Ubuntu", "--exec", "ssh", "-o", "BatchMode=yes",
           "-o", "ConnectTimeout=8", "mac", REMOTE]
STALE_AFTER = 600
BUSY_EVERY, IDLE_EVERY, FAIL_EVERY = 30, 120, 300


def fetch_snapshot():
    """一次 ssh -> 快照 dict;拉不到、不是完整的 JSON、版本不认识都返回 None。"""
    try:
        p = subprocess.run(SSH_CMD, capture_output=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        return None
    if p.returncode != 0:
        return None
    return parse_snapshot(p.stdout.decode("utf-8", "replace"))


def parse_snapshot(text):
    try:
        snap = json.loads(text)
    except Exception:
        return None
    if not isinstance(snap, dict) or snap.get("schemaVersion") != 1 or not isinstance(snap.get("sessions"), list):
        return None
    return snap


def clean(text, n):
    """防一手:像 URL、带 @ 的连接串、很长的一串字母数字(密钥)的词换成 …(Mac 那边已经过滤过)。"""
    words = [("…" if re.search(r"://|@|[A-Za-z0-9_\-]{24,}", w) else w) for w in str(text or "").split(" ")]
    return " ".join(words)[:n]


def file_name(s):
    return "mac-%s-%s.json" % (core.safe_name(s.get("agent") or "claude"), core.safe_name(s.get("id") or ""))


def apply_snapshot(snap, now=None, sessions_dir=None):
    """写快照里的每个会话,删掉快照里没有的 mac-*.json。返回 (写了几个, 有没有在跑/等你的)。

    updated 换成桌宠认的意思:Mac 已经按自己的规则判断过还亮着,在跑、等你、出错的就是「现在」还在
    (Mac 的 updated 只在变状态时动,长任务 40 分钟后桌宠会当成卡死);刚完成的用「这边第一次看到它完成」的时间,
    这样隔了两分钟才拉到也能亮 90 秒绿灯。离线前已经完成、标过 stale 的,回来后记成空闲,之后每一轮也是
    (doneSeen 记着),不再报一次「干完啦」。"""
    d = sessions_dir or SESSIONS_DIR
    now = time.time() if now is None else now
    os.makedirs(d, exist_ok=True)
    keep, busy, written = set(), False, 0
    for s in snap["sessions"]:
        if not isinstance(s, dict) or not s.get("id"):
            continue
        name = file_name(s)
        keep.add(name)                     # 写失败也留着旧文件,不当成 Mac 上没了
        path = os.path.join(d, name)
        old = core.load_json(path)
        agent = str(s.get("agent") or "claude")
        state = s.get("state") if s.get("state") in core.STATES else "idle"
        since = float(s.get("since") or s.get("updated") or now)
        busy = busy or state in ("running", "waiting")
        if state in ("running", "waiting", "error"):
            updated = now
        elif state == "done" and old.get("since") == since and old.get("state") == "done":
            updated = float(old.get("updated") or now)
        else:
            updated = now if state == "done" else float(s.get("updated") or now)
        seen = None
        if state == "done" and old.get("since") == since and (
                (old.get("stale") and old.get("lastState") == "done") or old.get("doneSeen") == since):
            # 断线前就知道它完成了,已经报过。doneSeen 记下这次完成:新文件不带 stale,
            # 原来下一轮就又翻回 done、绿灯重亮、再报一次「干完啦」。updated 也沿用旧的,
            # 写成现在会让这盏空闲灯每轮都排到灯板最前面
            state, seen = "idle", since
            updated = float(old.get("updated") or updated)
        acts = s.get("actions") if isinstance(s.get("actions"), list) else []
        steps = s.get("steps") if isinstance(s.get("steps"), list) else []
        data = {"id": "mac-%s-%s" % (agent, s["id"]), "agent": "mac-" + agent, "state": state,
                "title": clean(s.get("title"), 40), "updated": updated, "since": since,
                "actions": [clean(a, 60) for a in acts if isinstance(a, str) and a][:3],
                "steps": [{"title": clean(x.get("title", ""), 40), "sub": clean(x.get("sub", ""), 60),
                           "state": str(x.get("state", ""))} for x in steps if isinstance(x, dict)][:8],
                "project": clean(s.get("project"), 40), "waitReason": str(s.get("waitReason") or ""),
                "errorType": str(s.get("errorType") or ""), "source": "mac", "syncedAt": now}
        if seen is not None:
            data["doneSeen"] = seen
        try:
            core.write_json(path, data)
            written += 1
        except Exception:
            continue
    for f in os.listdir(d):
        if f.startswith("mac-") and f.endswith(".json") and f not in keep:
            try:
                os.remove(os.path.join(d, f))
            except OSError:
                pass
    save_state(d, {"lastOk": now})
    return written, busy


def mark_stale(now=None, sessions_dir=None):
    """好久没拉到了:mac-*.json 改成空闲、标 stale(原来的状态记在 lastState)。"""
    d = sessions_dir or SESSIONS_DIR
    now = time.time() if now is None else now
    if now - float(load_state(d).get("lastOk", 0) or 0) < STALE_AFTER:
        return
    try:
        names = [f for f in os.listdir(d) if f.startswith("mac-") and f.endswith(".json")]
    except OSError:
        return
    for f in names:
        path = os.path.join(d, f)
        data = core.load_json(path)
        if not data or data.get("stale"):
            continue
        data.update({"stale": True, "lastState": data.get("state"), "state": "idle", "actions": []})
        try:
            core.write_json(path, data)
        except Exception:
            pass


def load_state(d):
    return core.load_json(os.path.join(d, STATE_NAME))


def save_state(d, data):
    try:
        core.write_json(os.path.join(d, STATE_NAME), data)
    except Exception:
        pass


def fetch_once():
    """一轮拉取 -> (同步条数, 是否成功, Mac 上有没有在跑/等你的)。"""
    snap = fetch_snapshot()
    if snap is None:
        mark_stale()
        return 0, False, False
    n, busy = apply_snapshot(snap)
    return n, True, busy


def main():
    if "--loop" not in sys.argv:
        n, ok, busy = fetch_once()
        print(f"synced {n} session(s), ok={ok}, busy={busy}")
        return 0
    while True:
        try:
            n, ok, busy = fetch_once()
        except Exception:            # 一次奇怪的快照、磁盘满了:这一轮算失败,循环不能死
            ok, busy = False, False
        time.sleep(FAIL_EVERY if not ok else BUSY_EVERY if busy else IDLE_EVERY)
    return 0


if __name__ == "__main__":
    sys.exit(main())
