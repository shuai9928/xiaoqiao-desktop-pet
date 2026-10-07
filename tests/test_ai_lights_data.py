# -*- coding: utf-8 -*-
"""会话灯数据层回归(ai_lights_core / zcode_notify / wsl_lights_hook / mac_session_sync):
动作写成人话且不带密钥、批准后回到 running、新的一轮清空动作、并发不丢、会话身份不串、
Mac 快照对账删除、离线标过期。全部用临时目录和假数据,不碰真实的 ai_sessions/、不联网。"""
import json
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import ai_lights_core as core
import mac_session_sync
import pet
import wsl_lights_hook
import zcode_notify

NOW = 1_800_000_000.0


class LabelTests(unittest.TestCase):
    def test_same_wording_as_touch_bar(self):
        L = core.action_label
        self.assertEqual(L("Read", {"file_path": "/a/b/Pet.swift"}), "读 Pet.swift")
        self.assertEqual(L("Edit", {"file_path": r"C:\\x\\pet.py"}), "改 pet.py")
        self.assertEqual(L("Write", {"file_path": "new.py"}), "写 new.py")
        self.assertEqual(L("Bash", {"command": "cd C:\\\\x && py -m pytest -q"}), "跑测试 pytest")
        self.assertEqual(L("Bash", {"command": "./build.sh 2>&1 | tail"}), "构建 build.sh")
        self.assertEqual(L("Bash", {"command": "git status -s"}), "命令 git status")
        self.assertEqual(L("Bash", {"command": "cat /home/js/a/b.py | head"}), "读 b.py")
        self.assertEqual(L("Bash", {"command": "ssh win 'ls'"}), "远程 win")
        self.assertEqual(L("Bash", {"command": "cat > /p/notes.md <<'EOF'\nhi\nEOF"}), "写 notes.md")
        self.assertEqual(L("Bash", {"command": "echo hi >> log.txt"}), "写 log.txt")
        self.assertEqual(L("Bash", {"command": "cat a.py 2>&1 | head"}), "读 a.py")
        self.assertEqual(L("Bash", {"command": "cat a.py > /dev/null"}), "读 a.py")
        self.assertEqual(L("apply_patch", {"input": "*** Begin Patch\n*** Update File: src/x.py\n"}), "改 x.py")
        self.assertEqual(L("mcp__github__create_issue", {}), "调用工具 create_issue")
        self.assertEqual(L("TodoWrite", {"todos": []}), "")

    def test_no_secrets_paths_or_urls(self):
        L = core.action_label
        for cmd in ("OPENAI_API_KEY=sk-abc123 python3 run.py --token=xyz", "export TOKEN=abc123",
                    "curl -s https://api.example.com/v1?key=SECRET", "python3 /home/js/secret/run.py",
                    "echo \"my password\" > f", "\"C:\\Program Files\\x\\tool.exe\" --key=abc"):
            got = L("Bash", {"command": cmd})
            for bad in ("sk-abc", "abc123", "xyz", "SECRET", "example.com", "/home/js", "password", "Program Files", "key="):
                self.assertNotIn(bad, got, cmd)
        self.assertEqual(L("WebFetch", {"url": "https://x.com/?token=1"}), "读网页")
        # 评审给的几条:参数里的密码、要搜的密钥、PowerShell 的赋值、连接串
        leaks = {"sshpass -p hunter2 ssh win": "hunter2", "redis-cli -a S3cretPass ping": "S3cretPass",
                 "echo hunter2pass | sudo -S apt update": "hunter2pass", "rg sk-proj-ABCDEF123456 ~/.config": "sk-proj",
                 'grep -rn "Bearer eyJhbGci.abc" .': "eyJ", "find /home/js/private/clientX -name x.pem": "clientX",
                 "grep -r 帮我把老板的邮件改一下 .": "老板", "$env:OPENAI_API_KEY='sk-live-abc123'; foo": "sk-live",
                 "psql postgres://admin:hunter2@db/prod": "hunter2"}
        for cmd, secret in leaks.items():
            self.assertNotIn(secret, L("Bash", {"command": cmd}), cmd)
        self.assertEqual(L("Grep", {"pattern": "AKIA" + "X" * 16}), "搜索")
        self.assertEqual(L("Grep", {"pattern": "petLine"}), "搜索 petLine")
        delegated = L("Task", {"description": "审查用户的私密邮件"})
        self.assertEqual(delegated, "委派子智能体 · 审核与检查")
        self.assertNotIn("私密", delegated)
        self.assertNotIn("邮件", delegated)
        self.assertEqual(L("Bash", {"command": 'echo "=> done"'}), "命令 echo")       # 引号里的 > 不是写文件

    def test_garbage(self):
        self.assertEqual(core.action_label(None, None), "")
        self.assertEqual(core.command_label(""), "命令")

    def test_shared_hook_delegation_uses_finite_directions(self):
        label = core.action_label('collaboration.spawn_agent', {
            'task_name': 'ui_layout_review', 'message': 'PRIVATE_PROMPT'})
        self.assertEqual(label, '委派子智能体 · 界面与布局')
        self.assertEqual(core.action_label('Task', {'subagent_type': 'Explore',
            'description': '检查颜色与对比度', 'prompt': 'PRIVATE_PROMPT'}),
            '委派子智能体 · 颜色与对比度')
        self.assertEqual(core.action_label('collaboration.followup_task', {
            'target': 'PRIVATE_ID', 'message': '测试回归 PRIVATE_MESSAGE'}),
            '跟进子智能体 · 测试与验证')
        self.assertEqual(core.action_label('send_message', {
            'target': 'PRIVATE_ID', 'message': '审核代码 PRIVATE_MESSAGE'}),
            '跟进子智能体 · 审核与检查')
        self.assertEqual(core.action_label('Task', {'prompt': 'PRIVATE_PROMPT'}),
            '委派子智能体')
        self.assertEqual(core.action_label('wait', {'message': '测试 PRIVATE_MESSAGE'}), '等结果')


class ZcodeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = self.tmp.name

    def read(self, sid="s1"):
        return core.load_json(os.path.join(self.d, "zcode-%s.json" % sid))

    def test_approval_then_tool_goes_back_to_running(self):
        zcode_notify.upsert_session("zcode", "s1", "running", "p", sessions_dir=self.d)
        zcode_notify.update_action("zcode", "s1", "读 a.py", sessions_dir=self.d)
        zcode_notify.upsert_session("zcode", "s1", "waiting", "p", sessions_dir=self.d)
        self.assertEqual(self.read()["state"], "waiting")
        self.assertEqual([a["a"] for a in self.read()["actions"] if "a" in a],
                         ["读 a.py"])        # 等你时动作留着(F1:dict+轮次标记)
        zcode_notify.update_action("zcode", "s1", "命令 git status", sessions_dir=self.d)
        self.assertEqual(self.read()["state"], "running")             # 批准后开始下一个工具:不再亮橙灯
        self.assertEqual([a["a"] for a in self.read()["actions"] if "a" in a],
                         ["命令 git status", "读 a.py"])

    def test_empty_label_still_resumes(self):
        zcode_notify.upsert_session("zcode", "s1", "waiting", "p", sessions_dir=self.d)
        zcode_notify.update_action("zcode", "s1", "", sessions_dir=self.d)
        self.assertEqual(self.read()["state"], "running")

    def test_new_turn_marks_history_stop_keeps_them(self):
        # F1:新轮不再清空动作 —— 插轮次标记,历史留给轨迹页;思维链
        # 只读最后一个标记之后的动作(pet.ai_chain_lines 负责截取)。
        zcode_notify.upsert_session("zcode", "s1", "running", "p", sessions_dir=self.d)
        zcode_notify.update_action("zcode", "s1", "读 a.py", sessions_dir=self.d)
        zcode_notify.upsert_session("zcode", "s1", "done", "p", sessions_dir=self.d)
        self.assertEqual([a["a"] for a in self.read()["actions"] if "a" in a],
                         ["读 a.py"])
        zcode_notify.upsert_session("zcode", "s1", "running", "p", sessions_dir=self.d)
        acts = self.read()["actions"]
        self.assertTrue(acts[0].get("turn"))                 # 新轮 = 顶部轮次标记
        self.assertEqual([a["a"] for a in acts if "a" in a],
                         ["读 a.py"])                        # 历史保留

    def test_after_tool_approval_and_interrupt(self):
        zcode_notify.upsert_session("zcode", "s1", "waiting", "p", sessions_dir=self.d)
        zcode_notify.tool_finished("zcode", "s1", sessions_dir=self.d)
        self.assertEqual(self.read()["state"], "running")             # 批准的工具跑起来了:橙灯灭
        before = os.path.getmtime(os.path.join(self.d, "zcode-s1.json"))
        time.sleep(0.05)
        zcode_notify.tool_finished("zcode", "s1", sessions_dir=self.d)
        self.assertEqual(os.path.getmtime(os.path.join(self.d, "zcode-s1.json")), before)   # 平常的工具完成:不写文件
        zcode_notify.tool_finished("zcode", "s1", interrupted=True, sessions_dir=self.d)
        self.assertEqual(self.read()["state"], "idle")                # 你打断了:空闲,不再紫灯

    def test_hook_never_exits_nonzero(self):
        with patch.object(zcode_notify, "_main", side_effect=RuntimeError("boom")):
            self.assertEqual(zcode_notify.main(), 0)                  # 退出码 2 会让 ZCode 拦下操作

    def test_concurrent_hooks_lose_nothing(self):
        zcode_notify.upsert_session("zcode", "s1", "running", "p", sessions_dir=self.d)
        threads = [threading.Thread(target=zcode_notify.update_action,
                                    args=("zcode", "s1", "动作%d" % i), kwargs={"sessions_dir": self.d}) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        data = self.read()
        self.assertEqual(len([a for a in data["actions"] if "a" in a]), 6)
        self.assertEqual(data["state"], "running")
        self.assertFalse([f for f in os.listdir(self.d) if f.endswith(".tmp")])

    def test_session_start_is_idle(self):
        hook = json.dumps({"session_id": "s9", "hook_event_name": "SessionStart", "cwd": "C:\\\\p\\\\proj"})
        with patch.object(zcode_notify, "SESSIONS_DIR", self.d), patch("sys.argv", ["zcode_notify.py", "start"]), \
                patch("sys.stdin") as stdin:
            stdin.isatty.return_value = False
            stdin.read.return_value = hook
            zcode_notify.main()
        self.assertEqual(self.read("s9")["state"], "idle")

    def test_hook_input_is_not_written_to_disk(self):
        hook = json.dumps({"session_id": "s8", "hook_event_name": "PreToolUse", "tool_name": "Bash",
                           "tool_input": {"command": "TOKEN=abc123 deploy"}})
        with patch.object(zcode_notify, "SESSIONS_DIR", self.d), patch.object(zcode_notify, "HERE", self.d), \
                patch("sys.argv", ["zcode_notify.py", "tool"]), patch("sys.stdin") as stdin:
            stdin.isatty.return_value = False
            stdin.read.return_value = hook
            zcode_notify.main()
        self.assertFalse(os.path.exists(os.path.join(self.d, "_hook_input_last.txt")))
        for name in os.listdir(self.d):
            with open(os.path.join(self.d, name), encoding="utf-8", errors="replace") as f:
                self.assertNotIn("abc123", f.read())

    def test_delegation_hook_records_responsibility_without_prompt(self):
        hook = json.dumps({'session_id': 's-delegate', 'hook_event_name': 'PreToolUse',
            'tool_name': 'Task', 'tool_input': {'description': '检查比例与尺寸',
                'subagent_type': 'Explore', 'prompt': 'PRIVATE_PROMPT TOKEN=PRIVATE_TOKEN'}})
        with patch.object(zcode_notify, 'SESSIONS_DIR', self.d), patch.object(zcode_notify, 'HERE', self.d), \
                patch('sys.argv', ['zcode_notify.py', 'tool']), patch('sys.stdin') as stdin:
            stdin.isatty.return_value = False
            stdin.read.return_value = hook
            zcode_notify.main()
        data = self.read('s-delegate')
        self.assertEqual(data['actions'][0]['a'], '委派子智能体 · 比例与尺寸')
        self.assertNotIn('PRIVATE_', json.dumps(data))


class WslHookTests(unittest.TestCase):
    def test_shared_delegation_label_flows_through_wsl(self):
        label = core.action_label('spawn_agent', {'task_name': 'hat_fx_render',
            'message': 'PRIVATE_PROMPT'})
        data = wsl_lights_hook.on_action({}, 's', 'project', label)
        self.assertEqual(data['actions'][0], '委派子智能体 · 动态特效')
        self.assertNotIn('PRIVATE_', json.dumps(data))

    def test_full_session_id_kept(self):
        a = core.session_id_from({"transcript_path": "/h/.codex/sessions/rollout-2026-10-01T09-00-00-01a0f4f7-ae4c-7b10-b576-aa7100437385.jsonl"})
        b = core.session_id_from({"transcript_path": "/h/.codex/sessions/rollout-2026-10-01T09-00-00-01a0f4f8-ae4c-7b10-b576-aa7100437385.jsonl"})
        self.assertEqual(a, "01a0f4f7-ae4c-7b10-b576-aa7100437385")
        self.assertNotEqual(a, b)                                        # 末 12 位一样也不串灯
        self.assertEqual(core.session_id_from({"session_id": "abc/def"}), "abc_def")
        self.assertIsNone(core.session_id_from({}))

    def test_after(self):
        self.assertEqual(wsl_lights_hook.on_after({"state": "waiting"}, False)["state"], "running")
        self.assertEqual(wsl_lights_hook.on_after({"state": "running"}, True)["state"], "idle")
        self.assertIsNone(wsl_lights_hook.on_after({"state": "running"}, False))

    def test_action_resumes_and_new_turn_clears(self):
        d = {"state": "waiting", "actions": ["读 a.py"]}
        d = wsl_lights_hook.on_action(d, "x", "proj", "命令 git status")
        self.assertEqual(d["state"], "running")
        self.assertEqual(d["actions"], ["命令 git status", "读 a.py"])
        d = wsl_lights_hook.on_state(d, "x", "proj", "running", new_turn=True)
        self.assertEqual(d["actions"], [])
        d = wsl_lights_hook.on_state({"actions": ["读 a"]}, "x", "proj", "done", new_turn=False)
        self.assertEqual(d["actions"], ["读 a"])


def snapshot(*sessions):
    return {"schemaVersion": 1, "source": "mac", "generated": NOW, "sessions": list(sessions)}


class MacSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = self.tmp.name

    def names(self):
        return sorted(f for f in os.listdir(self.d) if f.startswith("mac-") and f.endswith(".json"))

    def test_snapshot_written_and_chain_uses_mac_actions(self):
        n, busy = mac_session_sync.apply_snapshot(snapshot(
            {"agent": "claude", "id": "a1", "state": "running", "title": "修登录", "updated": NOW - 5,
             "actions": ["改 B.swift（进行中）", "跑测试 test.sh · 过了"],
             "steps": [{"title": "读", "sub": "A.swift", "state": "done"}]},
            {"agent": "codex", "id": "a1", "state": "done", "title": "审查", "updated": NOW - 60}), now=NOW, sessions_dir=self.d)
        self.assertEqual((n, busy), (2, True))
        self.assertEqual(self.names(), ["mac-claude-a1.json", "mac-codex-a1.json"])   # 同一个 id 不同 AI 不串
        got = pet.scan_ai_sessions(self.d)
        chain = pet.ai_chain_lines(got)
        self.assertEqual(chain[:2], ("修登录", ["改 B.swift（进行中）", "跑测试 test.sh · 过了"]))
        self.assertEqual(chain[2], "mac-claude-a1")   # id = agent + "-" + 原始 id            # F1:返回会话 id 供卷轴直达

    def test_reconcile_deletes_gone_sessions_and_empty_list_clears(self):
        mac_session_sync.apply_snapshot(snapshot({"agent": "claude", "id": "a", "state": "waiting", "updated": NOW}),
                                        now=NOW, sessions_dir=self.d)
        with open(os.path.join(self.d, "zcode-x.json"), "w", encoding="utf-8") as f:
            f.write("{}")
        mac_session_sync.apply_snapshot(snapshot({"agent": "claude", "id": "b", "state": "running", "updated": NOW}),
                                        now=NOW, sessions_dir=self.d)
        self.assertEqual(self.names(), ["mac-claude-b.json"])          # Mac 上结束了的,这边跟着熄
        mac_session_sync.apply_snapshot(snapshot(), now=NOW, sessions_dir=self.d)
        self.assertEqual(self.names(), [])                             # 空列表也算成功
        self.assertTrue(os.path.exists(os.path.join(self.d, "zcode-x.json")))   # 只动 Mac 来源的

    def test_freshness_in_pet_terms(self):
        # 在跑的:Mac 的 updated 是一小时前提交那一刻,但 Mac 说还亮着 -> 桌宠这边记成现在,不会 40 分钟后变空心
        mac_session_sync.apply_snapshot(snapshot({"agent": "claude", "id": "r", "state": "running", "updated": NOW - 3600,
                                                  "since": NOW - 3600}), now=NOW, sessions_dir=self.d)
        data = core.load_json(os.path.join(self.d, "mac-claude-r.json"))
        self.assertEqual(pet.ai_light_style(data["state"], data["updated"], NOW + 10)[1], "pulse")
        # 刚完成的:隔了两分钟才拉到,也从「这边看到」起亮绿灯;下一轮还是同一次完成,不重新计时
        done = {"agent": "claude", "id": "d", "state": "done", "updated": NOW - 120, "since": NOW - 120}
        mac_session_sync.apply_snapshot(snapshot(done), now=NOW, sessions_dir=self.d)
        first = core.load_json(os.path.join(self.d, "mac-claude-d.json"))
        self.assertEqual(pet.ai_light_style("done", first["updated"], NOW + 10)[1], "solid")
        mac_session_sync.apply_snapshot(snapshot(done), now=NOW + 120, sessions_dir=self.d)
        again = core.load_json(os.path.join(self.d, "mac-claude-d.json"))
        self.assertEqual(again["updated"], first["updated"])

    def test_reconnect_does_not_announce_old_completion_again(self):
        done = {"agent": "claude", "id": "d", "state": "done", "updated": NOW, "since": NOW}
        mac_session_sync.apply_snapshot(snapshot(done), now=NOW, sessions_dir=self.d)
        mac_session_sync.mark_stale(now=NOW + 700, sessions_dir=self.d)
        mac_session_sync.apply_snapshot(snapshot(done), now=NOW + 800, sessions_dir=self.d)
        self.assertEqual(core.load_json(os.path.join(self.d, "mac-claude-d.json"))["state"], "idle")
        # 之后每一轮也不能翻回 done(原来第二轮就翻回、updated=现在、绿灯重亮再报一次);
        # updated 沿用旧的,空闲灯不占灯板最前面。再掉线一次也一样
        for t in (830, 950, 1800, 2000):
            if t == 1800:
                mac_session_sync.mark_stale(now=NOW + t, sessions_dir=self.d)
                continue
            mac_session_sync.apply_snapshot(snapshot(done), now=NOW + t, sessions_dir=self.d)
            data = core.load_json(os.path.join(self.d, "mac-claude-d.json"))
            self.assertEqual((data["state"], data["updated"]), ("idle", NOW), t)
        # 同一个会话真的又完成了一次(新的 since):照常亮绿灯
        mac_session_sync.apply_snapshot(snapshot(dict(done, since=NOW + 2100)), now=NOW + 2100, sessions_dir=self.d)
        data = core.load_json(os.path.join(self.d, "mac-claude-d.json"))
        self.assertEqual((data["state"], data["updated"]), ("done", NOW + 2100))

    def test_failed_write_keeps_the_old_file(self):
        mac_session_sync.apply_snapshot(snapshot({"agent": "claude", "id": "a", "state": "waiting", "updated": NOW}),
                                        now=NOW, sessions_dir=self.d)
        with patch.object(core, "write_json", side_effect=PermissionError("open by pet")):
            mac_session_sync.apply_snapshot(snapshot({"agent": "claude", "id": "a", "state": "running", "updated": NOW}),
                                            now=NOW + 30, sessions_dir=self.d)
        self.assertEqual(self.names(), ["mac-claude-a.json"])

    def test_snapshot_text_is_cleaned(self):
        stripe_fixture = "sk_live_" + "X" * 24
        mac_session_sync.apply_snapshot(snapshot({"agent": "claude", "id": "u", "state": "running", "updated": NOW,
                                                  "actions": ["命令 psql postgres://a:b@db/x", "读 " + stripe_fixture]}),
                                        now=NOW, sessions_dir=self.d)
        text = json.dumps(core.load_json(os.path.join(self.d, "mac-claude-u.json")), ensure_ascii=False)
        self.assertNotIn("postgres://", text)
        self.assertNotIn(stripe_fixture, text)

    def test_bad_or_partial_output_is_not_a_snapshot(self):
        for text in ("", "{截断", "[]", json.dumps({"schemaVersion": 2, "sessions": []}),
                     json.dumps({"schemaVersion": 1}), "@@F@@claude-a.json\\n{}"):
            self.assertIsNone(mac_session_sync.parse_snapshot(text), text)
        self.assertIsNotNone(mac_session_sync.parse_snapshot(json.dumps(snapshot())))

    def test_offline_marks_stale_after_ten_minutes(self):
        mac_session_sync.apply_snapshot(snapshot({"agent": "claude", "id": "w", "state": "waiting", "updated": NOW,
                                                  "actions": ["等你批准"]}), now=NOW, sessions_dir=self.d)
        mac_session_sync.mark_stale(now=NOW + 300, sessions_dir=self.d)
        data = core.load_json(os.path.join(self.d, "mac-claude-w.json"))
        self.assertEqual(data["state"], "waiting")                     # 5 分钟没拉到:还当真
        mac_session_sync.mark_stale(now=NOW + 601, sessions_dir=self.d)
        data = core.load_json(os.path.join(self.d, "mac-claude-w.json"))
        self.assertEqual((data["state"], data["stale"], data["lastState"], data["actions"]), ("idle", True, "waiting", []))
        self.assertEqual(pet.ai_light_style(data["state"], data["updated"], NOW + 601)[1], "hollow")


class CoreTests(unittest.TestCase):
    def test_contended_lock_gives_up_quickly(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.lock")
            held = threading.Event()
            release = threading.Event()

            def holder():
                with core.locked(path):
                    held.set()
                    release.wait(5)
            t = threading.Thread(target=holder)
            t.start()
            held.wait(5)
            start = time.time()
            with core.locked(path, wait=0.3):
                pass
            took = time.time() - start
            release.set()
            t.join()
            self.assertLess(took, 1.0)                 # 不像 LK_LOCK 那样一等就是 1 秒起

    def test_write_retries_when_file_is_busy(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.json")
            real = os.replace
            calls = []

            def flaky(src, dst):
                calls.append(1)
                if len(calls) < 3:
                    raise PermissionError("in use")
                return real(src, dst)
            with patch.object(core.os, "replace", side_effect=flaky):
                core.write_json(path, {"a": 1})
            self.assertEqual(core.load_json(path), {"a": 1})
            self.assertFalse([f for f in os.listdir(d) if f.endswith(".tmp")])
            with patch.object(core.os, "replace", side_effect=PermissionError("in use")):
                with self.assertRaises(PermissionError):
                    core.write_json(path, {"a": 2}, tries=2)
            self.assertFalse([f for f in os.listdir(d) if f.endswith(".tmp")])   # 失败也不留临时文件


if __name__ == "__main__":
    unittest.main()
