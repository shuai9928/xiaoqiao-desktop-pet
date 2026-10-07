"""AI 会话灯回归;不创建窗口,不读写用户存档。

数据源是 ai_sessions/*.json:zcode_notify.py(本机 ZCode hook)和
mac_session_sync.py(Mac 拉取)写,pet.py 的 scan_ai_sessions 读。
这套用例钉住:坏文件只跳过自己;状态→灯样式的映射;Mac 会话变化才
播报、本机 ZCode 不播(hook 已播过,避免连播两句);限频与睡着不打扰;
久等好奇/催促不靠状态变化触发;松口气只认真的出错→解决;熄掉的灯不挂链子。
"""
import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import mac_session_sync
import pet
import zcode_notify

NOW = 10_000.0


def write_session(d, name, **kw):
    data = {"id": kw.get("id", name[:-5]), "agent": kw.get("agent", "mac-claude"),
            "state": kw.get("state", "done"), "title": kw.get("title", ""),
            "updated": kw.get("updated", NOW - 30)}
    data.update({k: v for k, v in kw.items() if k not in data})   # since/stale/source 等
    with open(os.path.join(d, name), "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def shell_pet(**kw):
    """壳桌宠:只有会话灯用得到的字段,不跑 __init__。"""
    p = pet.Pet.__new__(pet.Pet)
    p.state = kw.get("state", "idle")
    p.ai_lights = kw.get("ai_lights", True)
    p._ai_sessions = []
    p._ai_states = kw.get("ai_states", {})     # None=刚启动还没扫过
    p._ai_key_last = {}
    p._ai_last_say = 0.0
    p._lid, p._lid_mode, p._lid_until, p._lid_pending = 0.0, "", 0.0, None
    p.last_interact = 0.0
    p.say = Mock()
    p.hop = Mock()
    p.hearts = Mock()
    p._spr_disp_h = Mock(return_value=200)
    return p


def scan_at(p, t):
    with patch.object(pet.time, "time", return_value=t):
        p._scan_ai_sessions()


def mac_snap(*sessions):
    return {"schemaVersion": 1, "sessions": list(sessions)}


RELIEF_LINES = {"呼——解决了就好~", "太好了,警报解除!", "哼,人家刚才可是很担心的!"}
NAG_LINES = {"都等五分钟了,快去看看嘛!", "再不去处理,人家要生气了哦!"}


def said(p):
    return [c.args[0] for c in p.say.call_args_list]


class ScanTests(unittest.TestCase):
    def test_bad_files_skip_their_own(self):
        with tempfile.TemporaryDirectory() as d:
            write_session(d, "a.json", id="a")
            with open(os.path.join(d, "b.json"), "w", encoding="utf-8") as f:
                f.write("{截断的json")
            with open(os.path.join(d, "c.txt"), "w", encoding="utf-8") as f:
                f.write("not json at all")
            with open(os.path.join(d, "d.json"), "w", encoding="utf-8") as f:
                f.write("[1,2,3]")          # 不是 dict
            got = pet.scan_ai_sessions(d)
            self.assertEqual([s["id"] for s in got], ["a"])

    def test_mac_file_with_dead_sync_goes_idle(self):
        # 同步进程没在跑(重启电脑后没人拉起它)就没人标 stale:syncedAt 太久没动这边自己算熄
        with tempfile.TemporaryDirectory() as d:
            write_session(d, "mac-a.json", id="mac-a", state="waiting", updated=NOW - 800,
                          source="mac", syncedAt=NOW - 800)
            write_session(d, "mac-b.json", id="mac-b", state="error", updated=NOW - 30,
                          source="mac", syncedAt=NOW - 30)
            got = {s["id"]: s for s in pet.scan_ai_sessions(d, now=NOW)}
            self.assertEqual((got["mac-a"]["state"], got["mac-a"]["stale"]), ("idle", True))
            self.assertEqual((got["mac-b"]["state"], got["mac-b"]["stale"]), ("error", False))

    def test_unknown_state_becomes_idle(self):
        with tempfile.TemporaryDirectory() as d:
            write_session(d, "x.json", state="interrupted")
            self.assertEqual(pet.scan_ai_sessions(d)[0]["state"], "idle")

    def test_sorted_and_capped(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(8):
                write_session(d, f"s{i}.json", id=f"s{i}", updated=NOW - i * 10)
            got = pet.scan_ai_sessions(d, cap=5, now=NOW)
            self.assertEqual([s["id"] for s in got],
                             ["s0", "s1", "s2", "s3", "s4"])

    def test_missing_dir_is_empty_not_crash(self):
        self.assertEqual(pet.scan_ai_sessions(os.path.join(drive(), "no", "such", "dir")), [])


def drive():
    return os.environ.get("SystemDrive", "C:")


class LightStyleTests(unittest.TestCase):
    def test_mapping(self):
        style = lambda s: pet.ai_light_style(s, NOW - 10, NOW)[1]
        self.assertEqual(style("waiting"), "blink")
        self.assertEqual(style("error"), "blink_fast")
        self.assertEqual(style("running"), "pulse")
        self.assertEqual(style("done"), "solid")
        self.assertEqual(style("idle"), "hollow")

    def test_done_fades_to_hollow(self):
        rgb, kind = pet.ai_light_style("done", NOW - 91, NOW)
        self.assertEqual(kind, "hollow")

    def test_running_goes_stale_to_hollow(self):
        # 进程硬崩溃时没人写 done,40 分钟没更新的紫灯按熄掉算
        self.assertEqual(pet.ai_light_style("running", NOW - 2401, NOW)[1], "hollow")
        self.assertEqual(pet.ai_light_style("running", NOW - 60, NOW)[1], "pulse")

    def test_waiting_and_error_expire_like_running(self):
        # 在确认框时关掉 ZCode 不会有 Stop:橙灯 2 小时、红灯 1 小时没更新也按熄掉算
        self.assertEqual(pet.ai_light_style("waiting", NOW - 7100, NOW)[1], "blink")
        self.assertEqual(pet.ai_light_style("waiting", NOW - 7201, NOW)[1], "hollow")
        self.assertEqual(pet.ai_light_style("error", NOW - 3500, NOW)[1], "blink_fast")
        self.assertEqual(pet.ai_light_style("error", NOW - 3601, NOW)[1], "hollow")

    def test_crystal_ignores_dead_sessions(self):
        dead = {"id": "z", "state": "waiting", "updated": NOW - 3 * 3600}
        live = {"id": "r", "state": "running", "updated": NOW - 5}
        self.assertEqual(pet.crystal_state([dead, live], now=NOW), "running")
        self.assertEqual(pet.crystal_state([dead], now=NOW), "idle")
        self.assertEqual(pet.crystal_state([dict(dead, updated=NOW - 5)], now=NOW), "waiting")
        # 详情面板和魔法书的圆点也一样:死掉的记空闲,活着的照实
        rows = pet.crystal_rows([dead, live], None, now=NOW)
        self.assertEqual([r[1] for r in rows[:2]],
                         [pet.CRYSTAL_COLORS["idle"], pet.CRYSTAL_COLORS["running"]])
        self.assertEqual([r[1] for r in pet.book_rows([dead, live], now=NOW)],
                         ["idle", "running"])

    def test_waiting_is_orange_error_is_red(self):
        self.assertEqual(pet.ai_light_style("waiting", NOW, NOW)[0], (255, 170, 60))
        self.assertEqual(pet.ai_light_style("error", NOW, NOW)[0], (255, 92, 92))


class ZcodeUpsertTests(unittest.TestCase):
    def test_upsert_then_scan_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            zcode_notify.upsert_session("zcode", "abc123", "waiting",
                                        "xiaoqiao-2.5d", sessions_dir=d)
            got = pet.scan_ai_sessions(d)
            self.assertEqual(len(got), 1)
            self.assertEqual(got[0]["id"], "zcode-abc123")
            self.assertEqual(got[0]["state"], "waiting")
            self.assertEqual(got[0]["agent"], "zcode")

    def test_sid_with_path_junk_sanitized(self):
        with tempfile.TemporaryDirectory() as d:
            zcode_notify.upsert_session("zcode", "a/b\\c:d", "done", "",
                                        sessions_dir=d)
            self.assertEqual(len(os.listdir(d)), 1)
            self.assertTrue(os.listdir(d)[0].endswith(".json"))
            self.assertFalse(any(f.endswith(".tmp") for f in os.listdir(d)))


class ScanPetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(pet, "AI_SESSION_DIR", self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_mac_transition_speaks_once(self):
        p = shell_pet()
        write_session(self.tmp.name, "m1.json", id="mac-m1", agent="mac-claude",
                      state="running", updated=NOW - 60)
        with patch.object(pet.time, "time", return_value=NOW):
            p._scan_ai_sessions()
            self.assertEqual(p.say.call_count, 0)      # running 没有台词
            write_session(self.tmp.name, "m1.json", id="mac-m1", agent="mac-claude",
                          state="done", updated=NOW - 1)
            p._scan_ai_sessions()
            self.assertEqual(p.say.call_count, 1)
            p._scan_ai_sessions()                      # 状态没变,不再说
            self.assertEqual(p.say.call_count, 1)

    def test_local_zcode_never_speaks(self):
        p = shell_pet()
        zcode_notify.upsert_session("zcode", "local", "waiting", "",
                                    sessions_dir=self.tmp.name)
        with patch.object(pet.time, "time", return_value=NOW):
            p._scan_ai_sessions()
        self.assertEqual(p.say.call_count, 0)

    def test_same_state_again_within_120s_stays_quiet(self):
        p = shell_pet()
        write_session(self.tmp.name, "m1.json", id="mac-m1", agent="mac-claude",
                      state="waiting", updated=NOW - 1)
        with patch.object(pet.time, "time", return_value=NOW):
            p._scan_ai_sessions()
            self.assertEqual(p.say.call_count, 1)
        # 灯灭了又亮起同一种状态,120 秒内不再吵
        p._ai_states = {}
        with patch.object(pet.time, "time", return_value=NOW + 30):
            p._scan_ai_sessions()
        self.assertEqual(p.say.call_count, 1)

    def test_asleep_lights_update_without_talking(self):
        p = shell_pet(state="sleep")
        write_session(self.tmp.name, "m1.json", id="mac-m1", agent="mac-claude",
                      state="waiting", updated=NOW - 1)
        with patch.object(pet.time, "time", return_value=NOW):
            p._scan_ai_sessions()
        self.assertEqual(len(p._ai_sessions), 1)
        self.assertEqual(p.say.call_count, 0)

    def test_toggle_off_stays_silent_but_still_scans(self):
        p = shell_pet(ai_lights=False)
        write_session(self.tmp.name, "m1.json", id="mac-m1", agent="mac-claude",
                      state="waiting", updated=NOW - 1)
        with patch.object(pet.time, "time", return_value=NOW):
            p._scan_ai_sessions()
        self.assertEqual(len(p._ai_sessions), 1)
        self.assertEqual(p.say.call_count, 0)

    def test_long_wait_reacts_without_any_state_change(self):
        # 状态表一直没变也要评估:原来"prev == cur 就 return"排在情绪前面,
        # 停在确认框的会话永远等不到好奇和催促
        p = shell_pet()
        write_session(self.tmp.name, "z1.json", id="zcode-z1", agent="zcode",
                      state="waiting", updated=NOW)
        for dt in (0, 30, 60):
            scan_at(p, NOW + dt)
        self.assertEqual(p._lid_mode, "")
        scan_at(p, NOW + 100)
        self.assertEqual(p._lid_mode, "curious")
        p._lid_mode = ""
        scan_at(p, NOW + 110)                          # 同一段等待只好奇一次
        self.assertEqual(p._lid_mode, "")
        self.assertEqual(p.say.call_count, 0)
        scan_at(p, NOW + 310)
        self.assertEqual(p._lid_mode, "urgent")
        self.assertTrue(said(p) and set(said(p)) <= NAG_LINES)
        scan_at(p, NOW + 400)                          # 5 分钟内不再催
        self.assertEqual(p.say.call_count, 1)

    def test_mac_wait_age_counts_from_since_not_sync_time(self):
        # Mac 同步每轮都把 updated 改成现在,等了多久要看 since
        p = shell_pet(ai_states=None)
        w = {"agent": "claude", "id": "w", "state": "waiting", "since": NOW - 200,
             "updated": NOW - 200}
        for dt in (0, 30, 60, 90, 120):
            mac_session_sync.apply_snapshot(mac_snap(w), now=NOW + dt,
                                            sessions_dir=self.tmp.name)
            scan_at(p, NOW + dt)
        self.assertEqual(p._lid_mode, "urgent")
        self.assertTrue(said(p) and set(said(p)) <= NAG_LINES)

    def test_asleep_or_lights_off_no_nag(self):
        for kw in ({"state": "sleep"}, {"ai_lights": False}):
            p = shell_pet(**kw)
            write_session(self.tmp.name, "z1.json", id="zcode-z1", agent="zcode",
                          state="waiting", updated=NOW - 600)
            scan_at(p, NOW)
            self.assertEqual((p._lid_mode, p.say.call_count), ("", 0), kw)

    def worried_pet(self, **kw):
        p = shell_pet(**kw)
        write_session(self.tmp.name, "m1.json", id="mac-m1", agent="mac-claude",
                      state="error", updated=NOW - 1)
        scan_at(p, NOW)
        return p

    def test_relief_when_error_really_resolves(self):
        p = self.worried_pet()
        write_session(self.tmp.name, "m1.json", id="mac-m1", agent="mac-claude",
                      state="running", updated=NOW + 5)
        scan_at(p, NOW + 10)
        p.hop.assert_called_once()
        self.assertEqual(p._lid_mode, "relieved")
        self.assertTrue(RELIEF_LINES & set(said(p)))

    def test_relief_respects_lights_sleep_and_focus(self):
        for kw in ({"ai_lights": False}, {"state": "sleep"}, {"focus": True}):
            p = self.worried_pet(**{k: v for k, v in kw.items() if k != "focus"})
            if kw.get("focus"):
                p._core_edition = False  # Retired focus behavior, explicit compatibility check.
                p.pomo = {"phase": "focus", "due": NOW + 900}
            write_session(self.tmp.name, "m1.json", id="mac-m1", agent="mac-claude",
                          state="done", updated=NOW + 5)
            scan_at(p, NOW + 10)
            p.hop.assert_not_called()
            p.hearts.assert_not_called()
            self.assertFalse(RELIEF_LINES & set(said(p)), kw)

    def test_error_pushed_off_the_board_is_not_relief(self):
        p = self.worried_pet()
        for i in range(5):
            write_session(self.tmp.name, f"z{i}.json", id=f"zcode-z{i}", agent="zcode",
                          state="running", updated=NOW + 1 + i)
        scan_at(p, NOW + 10)
        self.assertNotIn("mac-m1", [s["id"] for s in p._ai_sessions])
        p.hop.assert_not_called()
        self.assertFalse(RELIEF_LINES & set(said(p)))

    def test_mac_going_offline_is_not_relief(self):
        # Mac 掉线:同步标 stale 改成空闲,或者同步进程本身停了(syncedAt 不再动)
        for marked in (True, False):
            p = shell_pet()
            err = {"agent": "claude", "id": "e", "state": "error", "since": NOW, "updated": NOW}
            mac_session_sync.apply_snapshot(mac_snap(err), now=NOW, sessions_dir=self.tmp.name)
            scan_at(p, NOW)
            self.assertIn("mac-claude-e", p._ai_err_seen)
            if marked:
                mac_session_sync.mark_stale(now=NOW + 700, sessions_dir=self.tmp.name)
            scan_at(p, NOW + 800)
            self.assertEqual(p._ai_sessions[0]["state"], "idle")
            p.hop.assert_not_called()
            self.assertFalse(RELIEF_LINES & set(said(p)), marked)

    def test_first_scan_only_records_what_is_on_disk(self):
        # 重启小乔:磁盘上的 Mac 状态是旧闻,第一轮只记下来,之后真变了才播
        p = shell_pet(ai_states=None)
        write_session(self.tmp.name, "m1.json", id="mac-m1", agent="mac-claude",
                      state="done", updated=NOW - 5)
        write_session(self.tmp.name, "m2.json", id="mac-m2", agent="mac-claude",
                      state="waiting", updated=NOW - 5)
        scan_at(p, NOW)
        scan_at(p, NOW + 2)
        self.assertEqual(p.say.call_count, 0)
        write_session(self.tmp.name, "m2.json", id="mac-m2", agent="mac-claude",
                      state="error", updated=NOW + 3)
        scan_at(p, NOW + 4)
        self.assertEqual(p.say.call_count, 1)
        self.assertIn(said(p)[0], pet.AI_SESSION_LINES["error"])

    def test_long_finished_done_is_not_news(self):
        p = shell_pet()
        write_session(self.tmp.name, "m1.json", id="mac-m1", agent="mac-claude",
                      state="done", updated=NOW - 3 * 3600)
        scan_at(p, NOW)
        self.assertEqual(p.say.call_count, 0)

    def test_mac_reconnect_does_not_reannounce_done(self):
        p = shell_pet()
        done = {"agent": "claude", "id": "d", "state": "done", "since": NOW, "updated": NOW}
        mac_session_sync.apply_snapshot(mac_snap(done), now=NOW, sessions_dir=self.tmp.name)
        scan_at(p, NOW + 1)
        self.assertEqual(p.say.call_count, 1)          # 第一次完成:报一次
        mac_session_sync.mark_stale(now=NOW + 700, sessions_dir=self.tmp.name)
        scan_at(p, NOW + 700)
        for dt in (800, 830, 950, 1100):               # 重连后一轮轮同步
            mac_session_sync.apply_snapshot(mac_snap(done), now=NOW + dt,
                                            sessions_dir=self.tmp.name)
            scan_at(p, NOW + dt)
        self.assertEqual(p.say.call_count, 1)

    def lid_pet(self, mode, until):
        p = shell_pet()
        p.cfg, p.blink_until, p.singing, p._mouth = {}, 0, False, None
        p._lid, p._lid_mode, p._lid_until = 0.30, mode, until
        write_session(self.tmp.name, "m1.json", id="mac-m1", agent="mac-claude",
                      state="error", updated=NOW - 1)
        with patch.object(pet.time, "time", return_value=NOW):
            p._scan_ai_sessions()
        self.assertIn("mac-m1", p._ai_err_seen)
        self.assertEqual(p._lid_mode, mode)            # 不抢正在播的情绪
        return p

    def test_worry_waits_for_busy_lid_instead_of_vanishing(self):
        # 出错时她正被摸头(别的情绪占着眼睑):原来担心直接丢,id 却已记进
        # _ai_err_seen,同一会话再也不担心。现在排队,眼睑一空就补播
        p = self.lid_pet("shy", NOW + 3.0)
        p._face_texture_key(NOW + 1.0, 0, False)
        self.assertEqual(p._lid_mode, "shy")
        p._face_texture_key(NOW + 3.1, 0, False)       # 眼睑空出来
        self.assertEqual((p._lid, p._lid_mode), (0.34, "sad"))
        self.assertAlmostEqual(p._lid_until, NOW + 3.1 + 2.2)
        self.assertEqual(p._face_texture_key(NOW + 3.2, 0, False)[4], "sad")

    def test_queued_worry_goes_stale(self):
        p = self.lid_pet("happy", NOW + 30.0)
        p._face_texture_key(NOW + 31.0, 0, False)      # 排了 30 秒,过时作罢
        self.assertEqual(p._lid_mode, "happy")
        self.assertIsNone(p._lid_pending)


class ReactionTests(unittest.TestCase):
    def test_error_worry_beats_curious_regardless_of_order(self):
        # 久等的 waiting 排在前面时,原来 lid 先被 curious 占住,error 的 id
        # 照记进已反应集合,担心却永远没出现
        sessions = [{"id": "w", "state": "waiting", "updated": NOW - 200},
                    {"id": "e", "state": "error", "updated": NOW - 300}]
        lid, mode, seen = pet.ai_reactions(sessions, set(), NOW)
        self.assertEqual((lid, mode), (0.34, "sad"))
        self.assertIn("e", seen)


class ChainTests(unittest.TestCase):
    def test_active_session_chain_lines(self):
        sessions = [{"id": "a", "agent": "zcode", "state": "done",
                     "title": "旧", "updated": NOW - 60, "actions": []},
                    {"id": "b", "agent": "wslcodex", "state": "running",
                     "title": "proj", "updated": NOW - 5,
                     "actions": ["Bash: py -m unittest", "Read: pet.py"]}]
        got = pet.ai_chain_lines(sessions, now=NOW)
        self.assertEqual(got[0], "proj")
        self.assertEqual(got[1], ["Bash: py -m unittest", "Read: pet.py"])

    def test_no_action_data_falls_back_to_state_word(self):
        got = pet.ai_chain_lines([{"id": "m", "agent": "mac-claude",
                                   "state": "waiting", "title": "",
                                   "updated": NOW, "actions": []}], now=NOW)
        self.assertEqual(got[0], "M")
        self.assertEqual(got[1], ["等你批准"])

    def test_dead_sessions_do_not_hang_over_her_head(self):
        # 40 分钟没动静的 running(硬崩溃没人写 done):灯已空心,链子也不挂
        stuck = {"id": "s", "agent": "zcode", "state": "running", "title": "卡死",
                 "updated": NOW - 6 * 3600, "actions": []}
        self.assertIsNone(pet.ai_chain_lines([stuck], now=NOW))
        # 熄掉的跳过,不是整条放弃:后面真在跑的照样顶上来
        gone = {"id": "m", "agent": "mac-claude", "state": "waiting", "title": "断线",
                "updated": NOW, "stale": True, "actions": []}
        live = {"id": "b", "agent": "zcode", "state": "running", "title": "proj",
                "updated": NOW - 10, "actions": ["读 pet.py"]}
        self.assertEqual(pet.ai_chain_lines([gone, stuck, live], now=NOW),
                         ("proj", ["读 pet.py"], "b"))

    def test_all_idle_no_chain(self):
        self.assertIsNone(pet.ai_chain_lines(
            [{"id": "a", "agent": "zcode", "state": "done", "title": "x",
              "updated": NOW, "actions": []}], now=NOW))


class ToolBriefTests(unittest.TestCase):
    def test_bash_command_brief(self):
        j = {"tool_name": "Bash", "tool_input": {"command": "py -m unittest\nmore"}}
        self.assertEqual(zcode_notify.tool_brief(j), "跑测试 unittest")

    def test_file_tools_show_basename_path(self):
        # 只写文件名,不写完整路径(和 Mac 触控栏路线图一个口径)
        j = {"tool_name": "Read", "tool_input": {"file_path": r"C:\x\pet.py"}}
        self.assertEqual(zcode_notify.tool_brief(j), "读 pet.py")

    def test_garbage_input_is_empty_not_crash(self):
        self.assertEqual(zcode_notify.tool_brief(None), "")
        self.assertEqual(zcode_notify.tool_brief("junk"), "")

    def test_update_action_prepends_and_caps(self):
        with tempfile.TemporaryDirectory() as d:
            zcode_notify.upsert_session("zcode", "s1", "running", "p",
                                        sessions_dir=d)
            for t in ("a1", "a2", "a3", "a4"):
                zcode_notify.update_action("zcode", "s1", t, sessions_dir=d)
            got = pet.scan_ai_sessions(d)
            self.assertEqual(got[0]["state"], "running")   # 干活时保持/落到 running
            # F1 起动作为 dict(带时间戳),历史深度 3 → 24
            self.assertEqual([a["a"] for a in got[0]["actions"] if "a" in a],
                             ["a4", "a3", "a2", "a1"])
            self.assertTrue(all("t" in a for a in got[0]["actions"]
                                if "a" in a))   # 轮次标记没有 a


class TrimTests(unittest.TestCase):
    # Mac 会话不再按「最多 8 个」修剪,而是拿到完整快照后对账(见 test_ai_lights_data.MacSyncTests)

    def test_zcode_trim_keeps_newest_eight(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(10):
                path = os.path.join(d, f"zcode-s{i}.json")
                with open(path, "w", encoding="utf-8") as f:
                    f.write("{}")
                os.utime(path, (NOW + i, NOW + i))
            zcode_notify.trim_zcode(d)
            left = sorted(os.listdir(d))
            self.assertEqual(len(left), 8)
            self.assertNotIn("zcode-s0.json", left)
            self.assertIn("zcode-s9.json", left)

    def test_zcode_start_roundtrip_running(self):
        with tempfile.TemporaryDirectory() as d:
            zcode_notify.upsert_session("zcode", "sess1", "running", "proj",
                                        sessions_dir=d)
            got = pet.scan_ai_sessions(d)
            self.assertEqual(got[0]["state"], "running")
            self.assertEqual(got[0]["agent"], "zcode")


if __name__ == "__main__":
    unittest.main()
