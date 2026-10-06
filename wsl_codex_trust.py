#!/usr/bin/env python3
"""把 ~/.codex/hooks.json 里小乔会话灯的 hook 标成「已信任」(WSL 适配版)。

方法和 Mac 的 codex-trust-hooks.py 相同:走 codex app-server 的
hooks/list + config/batchWrite,哈希由 Codex 自己算,不是手写;
只碰命令含 xiaoqiao-lights-hook 的条目,写前自动备份 config.toml。"""
import json, os, re, shutil, subprocess, sys, time

DRY = "--dry-run" in sys.argv
PATTERN = re.compile(r"xiaoqiao-lights-hook")

proc = subprocess.Popen(["codex", "app-server"], stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, bufsize=1)
counter = [10]

def send(m):
    proc.stdin.write(json.dumps(m) + "\n")
    proc.stdin.flush()

def receive(wanted, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        line = proc.stdout.readline()
        if not line:
            break
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if m.get("id") == wanted:
            return m
    return None

def call(method, params):
    counter[0] += 1
    send({"jsonrpc": "2.0", "id": counter[0], "method": method, "params": params})
    return receive(counter[0])

send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
      "params": {"clientInfo": {"name": "xiaoqiao-lights-trust", "title": None, "version": "1"}}})
receive(1)
send({"jsonrpc": "2.0", "method": "initialized"})
listed = call("hooks/list", {"cwds": []})
hooks = (listed or {}).get("result", {}).get("data", [{}])[0].get("hooks", [])
mine = [h for h in hooks
        if h.get("source") == "user" and PATTERN.search(h.get("command") or "")]
for h in mine:
    print('%-18s %-10s %s' % (h.get("eventName"), h.get("trustStatus"), (h.get("command") or "")[:80]))
todo = {h["key"]: {"trusted_hash": h["currentHash"]}
        for h in mine if h.get("trustStatus") != "trusted"}
print("小乔会话灯的 hook %d 条,要信任 %d 条" % (len(mine), len(todo)))
if todo and not DRY:
    cfg = os.path.expanduser("~/.codex/config.toml")
    shutil.copy(cfg, "%s.bak-lights-%s" % (cfg, time.strftime("%Y%m%d-%H%M%S")))
    done = call("config/batchWrite", {
        "edits": [{"keyPath": "hooks.state", "mergeStrategy": "upsert", "value": todo}],
        "reloadUserConfig": True})
    print("写入:", (done or {}).get("result", {}).get("status", "没有回应"))
    after = call("hooks/list", {"cwds": []})
    hs = after["result"]["data"][0]["hooks"] if after else []
    print("现在:", [(h.get("eventName"), h.get("trustStatus")) for h in hs
                 if PATTERN.search(h.get("command") or "")])
proc.terminate()
