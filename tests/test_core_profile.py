"""Core edition boundaries; synthetic pets/data only, with no model or user I/O.

Run with Windows Python: python -m unittest discover -s tests -p test_core_profile.py -v.
The scheduler test executes the actual scheduling statements from _tick_body,
leaving window positioning and rendering outside this focused regression.
"""
import ast
import copy
import inspect
import json
import tempfile
import textwrap
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pet
import ai_chat

NOW = 10_000.0
CORE_ACTIONS = {
    "pet_head", "eat_candy", "wake_up", "mount_swing", "go_sleep",
    "open_room_preview", "open_chat", "report_agent_progress",
}
REMOVED_LABELS = (
    "猜", "运势", "占卜", "变身", "时停", "回溯", "魔法", "跳舞", "转圈",
    "空翻", "打滚", "冥想", "玩球", "天气", "喝水", "电量", "番茄", "提醒…",
    "剪贴板", "翻译", "找文件", "我的屏幕", "偷看窗口", "纪念日", "生日",
)


def core_pet():
    p = pet.Pet.__new__(pet.Pet)
    p._core_edition = True
    p.state, p.drag, p.bubble = "swing", None, None
    p.settings = {}
    p.star, p.affection, p.scale = 76.0, 12.0, 1.0
    p.W, p.H, p.sw, p.sh = 430, 520, 1366, 768
    p._nap_on_swing = False
    p.singing = False
    p.sound_on, p.tts_on = False, False
    p.ai_lights, p.ai_announce = True, True
    p.topmost, p.click_through = True, False
    p.parts, p.circles = [], []
    p.sfx = Mock()
    p.companion_days = Mock(return_value=12)
    p.affection_level = Mock(return_value="熟悉")
    p._today_summary = Mock(return_value="摸头 1 次")
    return p


def scheduling_statements():
    """Keep the production guards and bodies, rather than copying their logic."""
    fn = ast.parse(textwrap.dedent(inspect.getsource(pet.Pet._tick_body))).body[0]
    schedule_fields = {
        "reminders", "water_min", "water_next", "pomo", "next_greet",
        "_focus_tick", "_fg_watch_tick", "_battery_tick", "_stats_tick",
    }
    fn.body = [stmt for stmt in fn.body if any(
        isinstance(node, ast.Attribute) and node.attr in schedule_fields
        for node in ast.walk(stmt)
    )]
    if not fn.body:
        raise AssertionError("No production scheduling statements were found")
    tree = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
    namespace = dict(vars(pet), now=NOW)
    exec(compile(tree, inspect.getsourcefile(pet.Pet), "exec"), namespace)
    return namespace[fn.name]


class CoreProfileTests(unittest.TestCase):
    def test_default_profile_and_explicit_legacy_override(self):
        p = pet.Pet.__new__(pet.Pet)
        self.assertTrue(pet.Pet.CORE_EDITION)
        self.assertTrue(p.core_profile())
        p._core_edition = False
        self.assertFalse(p.core_profile())

    def test_chat_local_actions_are_only_core_actions(self):
        p = core_pet()
        self.assertEqual({name for _, name in pet.Pet.PET_ACTIONS_CORE}, CORE_ACTIONS)
        for keywords, name in pet.Pet.PET_ACTIONS_CORE:
            for keyword in keywords:
                with self.subTest(keyword=keyword):
                    self.assertEqual(p._match_pet_action(keyword), name)
        for text in ("猜数字", "今日运势", "变身", "跳舞", "转个圈", "后空翻",
                     "打滚", "冥想", "施魔法", "撒星星", "现在天气如何"):
            with self.subTest(text=text):
                self.assertIsNone(p._match_pet_action(text))

    def test_command_channel_cannot_start_removed_behaviors_or_set_state(self):
        p = core_pet()
        methods = ("sing", "start_dance", "start_stretch", "start_peek", "start_flip",
                   "start_wave", "start_roll", "start_transform", "start_chase",
                   "go_dizzy", "throw", "play_rps", "start_meditate", "cast_magic",
                   "_schedule_reminder", "play_emotion", "_write_state")
        for name in methods:
            setattr(p, name, Mock())
        for op in ("sing", "dance", "stretch", "peek", "flip", "wave", "roll",
                   "transform", "chase", "dizzy", "throw", "rps", "meditate",
                   "magic", "remind", "play_sfx", "play_emotion", "set_state"):
            with self.subTest(op=op):
                p._exec_cmd({"op": op, "state": "transform", "name": "magic"})
                self.assertEqual(p.state, "swing")
                for name in methods:
                    if name != "_write_state":
                        getattr(p, name).assert_not_called()
                p.sfx.play.assert_not_called()
        # The read-only state observation operation must not become a setter.
        p._exec_cmd({"op": "state", "state": "transform"})
        self.assertEqual(p.state, "swing")

    def test_system_intents_do_not_run_local_tools(self):
        p = core_pet()
        for name in ("_run_bg", "_log_chat", "_schedule_reminder", "ask_weather",
                     "start_pomodoro", "summarize_clipboard", "translate_clipboard",
                     "_start_file_search", "look_screen"):
            setattr(p, name, Mock())
        with patch.object(pet.agent, "execute") as execute:
            for kind in ("open", "close", "uninstall", "search", "remind", "weather",
                         "pomo", "clipboard", "translate", "find_file", "screen"):
                with self.subTest(kind=kind):
                    p.run_agent({"kind": kind, "target": "synthetic", "raw": "synthetic"})
            execute.assert_not_called()
        for name in ("_run_bg", "_schedule_reminder", "ask_weather", "start_pomodoro",
                     "summarize_clipboard", "translate_clipboard", "_start_file_search",
                     "look_screen"):
            getattr(p, name).assert_not_called()

    def test_core_chat_commands_take_priority_over_system_verb_parser(self):
        for text, action in (("打开小屋", "open_room_preview"),
                             ("去小屋", "open_room_preview"),
                             ("打开聊天", "open_chat")):
            with self.subTest(text=text):
                p = core_pet()
                p.brain = SimpleNamespace(available=False)
                p._log_chat, p._reply, p._run_bg = Mock(), Mock(), Mock()
                for name in CORE_ACTIONS:
                    setattr(p, name, Mock())
                p.ask_ai(text)
                getattr(p, action).assert_called_once()
                p._run_bg.assert_not_called()
                p._reply.assert_not_called()

    def test_direct_legacy_entrances_stop_before_any_work(self):
        p = pet.Pet.__new__(pet.Pet)
        p._core_edition = True
        for name, args in (
            ("cast_magic", ()), ("start_transform", ()), ("start_time_stop", ()),
            ("start_rewind", ()), ("play_rps", ("rock",)), ("start_guess", ()),
            ("tell_fortune", ()), ("ask_weather", ()), ("start_pomodoro", (25,)),
            ("set_water_reminder", (30,)),
        ):
            with self.subTest(method=name):
                self.assertIs(getattr(p, name)(*args), False)

    def test_idle_random_branches_do_not_call_models_or_big_actions(self):
        p = core_pet()
        p.state = "idle"
        p._ai_ready = Mock(return_value=True)
        p._ai_cur_cd = p._sneeze_cd = p._fall_cd = 0
        for name in ("_ai_quick", "say", "play_emotion", "add_part", "hop", "star_burst",
                     "start_sneeze", "start_fall", "go_sleep", "_start_micro_motion"):
            setattr(p, name, Mock())
        for draw in (.01, .65, .70, .75, .86, .93, .95, .965, .99):
            with patch.object(pet.random, "random", return_value=draw):
                p._idle_event(NOW)
        p._ai_quick.assert_not_called()
        p.hop.assert_not_called()
        p.start_sneeze.assert_not_called()
        p.start_fall.assert_not_called()

    def test_old_focus_does_not_change_core_companionship(self):
        p = core_pet()
        p.pomo = {"phase": "focus", "due": NOW + 1500, "mins": 25}
        with patch.object(pet.time, "time", return_value=NOW):
            self.assertFalse(p.focus_mode())

    def test_old_reminder_file_is_neither_loaded_nor_rewritten(self):
        p = core_pet()
        p.reminders = []
        p._load_json = Mock(side_effect=AssertionError("Reminder data must stay dormant"))
        p._save_reminders = Mock()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pet_reminders.json"
            before = b'[{"due":1,"text":"synthetic old reminder"}]'
            path.write_bytes(before)
            with patch.object(pet, "REMINDERS_FILE", str(path)):
                p._load_reminders()
            self.assertEqual(path.read_bytes(), before)
        p._load_json.assert_not_called()
        p._save_reminders.assert_not_called()

    def test_saving_core_progress_preserves_dormant_settings(self):
        p = core_pet()
        archived = {
            "pomo": {"phase": "focus", "due": 1, "mins": 50},
            "water_min": 90, "fg_watch": True, "battery_watch": True,
            "city": "synthetic city", "lat": 1.25, "lon": 2.5,
            "magic_style": 1, "rps": [7, 2, 1], "catch_best": 5,
            "pomo_done": 9, "anniv_date": "10-03", "unknown_legacy_key": "keep",
        }
        p.settings = dict(archived, x=1, fy=2, star=1, affection=3)
        for name, value in {
            "x": 123, "fy": 456, "first_day": "2020-01-01", "catch_best": 0,
            "magic_style": 0, "pomo_done": 0, "pomo": None, "rps": [0, 0, 0],
            "water_min": 0, "fg_watch": False, "battery_watch": False,
            "tts_volume": 700, "city": "", "city_lat": None, "city_lon": None,
        }.items():
            setattr(p, name, value)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pet_settings.json"
            path.write_text(json.dumps(p.settings), encoding="utf-8")
            with patch.object(pet, "CONFIG_FILE", str(path)):
                p.save_settings()
            saved = json.loads(path.read_text(encoding="utf-8"))
        for name, value in archived.items():
            with self.subTest(field=name):
                self.assertEqual(saved[name], value)
        self.assertEqual((saved["x"], saved["fy"], saved["star"], saved["affection"]),
                         (123, 456, 76, 12))

    def test_due_old_timers_and_proactive_ai_do_not_fire(self):
        p = core_pet()
        p.reminders = [{"due": NOW - 1, "text": "synthetic overdue reminder"}]
        p.water_min, p.water_next = 45, NOW - 1
        p.pomo = {"phase": "focus", "due": NOW - 1, "mins": 25}
        before = copy.deepcopy((p.reminders, p.water_next, p.pomo))
        p.last_interact, p.next_greet = NOW, NOW - 1
        p.brain = SimpleNamespace(cfg={"greet_interval_min": 30})
        p._ai_ready = Mock(return_value=True)
        p._stats_tick = Mock()
        for name in ("_ai_quick", "_fire_reminder", "_save_reminders", "hearts",
                     "confetti_burst", "add_affection", "_count_today"):
            setattr(p, name, Mock())
        with patch.object(pet.time, "time", return_value=NOW):
            scheduling_statements()(p)
        self.assertEqual((p.reminders, p.water_next, p.pomo), before)
        for name in ("_ai_quick", "_fire_reminder", "_save_reminders", "add_affection"):
            getattr(p, name).assert_not_called()


class CoreMenuTests(unittest.TestCase):
    def test_menu_contains_core_entries_and_no_removed_game_or_tool(self):
        p = core_pet()
        menus = []

        def new_menu(*args):
            menu = Mock()
            menus.append(menu)
            return menu

        p._menu = new_menu
        with patch.object(pet, "autostart_enabled", return_value=False):
            p._build_menu()
        labels = [call.kwargs.get("label", "") for menu in menus
                  for call in menu.method_calls if call[0].startswith("add_")]
        for fragment in REMOVED_LABELS:
            with self.subTest(fragment=fragment):
                self.assertFalse(any(fragment in label for label in labels), labels)
        for fragment in ("聊天", "糖", "休息", "秋千", "小屋", "退出"):
            with self.subTest(core=fragment):
                self.assertTrue(any(fragment in label for label in labels), labels)

    def test_actual_card_offers_only_core_daily_actions(self):
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        p = core_pet()
        p.root = root
        p.action_card = None
        for name in CORE_ACTIONS:
            setattr(p, name, Mock())
        with patch.object(pet, "work_area_at", return_value=(0, 0, 1366, 728)):
            card = pet.InteractionCard(p, 40, 40)
        self.addCleanup(card.close)
        self.assertEqual(set(card.buttons), {"聊天", "喂糖", "小屋", "睡觉"})
        card.buttons["喂糖"].invoke()
        p.eat_candy.assert_called_once()
        self.assertTrue(card.closed)


class CoreAIContractTests(unittest.TestCase):
    def test_default_ai_schema_only_allows_null_actions_and_intents(self):
        brain = ai_chat.AIBrain.__new__(ai_chat.AIBrain)
        schema = brain._schema()
        self.assertEqual(set(schema["required"]), {"say", "emotion", "action", "intent"})
        self.assertEqual(schema["properties"]["action"], {"type": "null"})
        self.assertEqual(schema["properties"]["intent"], {"type": "null"})
        self.assertEqual(schema["properties"]["say"]["type"], "string")

    def test_core_prompt_does_not_offer_legacy_tool_or_action_protocols(self):
        prompt = ai_chat.build_system_instruction({"name": "Synthetic"}, core=True)
        self.assertIn("action和intent始终为null", prompt)
        self.assertIn("不能执行电脑操作", prompt)
        self.assertIn("不能声称完成这些操作", prompt)
        self.assertNotIn('"kind"', prompt)
        self.assertNotIn("magic/stars/hop", prompt)

    def test_few_shot_messages_filter_old_tools_and_preserve_plain_chat(self):
        brain = ai_chat.AIBrain.__new__(ai_chat.AIBrain)
        brain.examples = []
        brain.memory = SimpleNamespace(facts=[])
        examples = [
            {"user": "old action", "assistant": {"say": "old", "action": "magic"}},
            {"user": "old tool", "assistant": {
                "say": "old", "intent": {"kind": "open", "target": "synthetic"}}},
            {"user": "plain chat", "assistant": {"say": "hello", "emotion": "happy"}},
        ]
        before = copy.deepcopy(examples)
        with patch.object(ai_chat, "select_examples", return_value=examples):
            messages = brain._build_messages("synthetic question", [])
        user_text = [message["parts"][0]["text"] for message in messages
                     if message["role"] == "user"]
        self.assertEqual(user_text, ["plain chat", "synthetic question"])
        answers = [json.loads(message["parts"][0]["text"]) for message in messages
                   if message["role"] == "model"]
        self.assertEqual(len(answers), 1)
        self.assertIsNone(answers[0]["action"])
        self.assertIsNone(answers[0]["intent"])
        self.assertEqual(examples, before)

    def test_ai_reply_keeps_chat_but_does_not_enqueue_tools_or_actions(self):
        for from_chat in (True, False):
            with self.subTest(from_chat=from_chat):
                p = core_pet()
                p.state = "idle"
                p.root, p.chatbox, p.history = Mock(), None, []
                p.ai_thinking = True
                for name in ("say", "_speak", "play_emotion", "_log_chat",
                             "run_agent", "_do_action"):
                    setattr(p, name, Mock())
                p._apply_ai({"say": "synthetic reply", "emotion": "happy",
                             "action": "magic", "intent": {
                                 "kind": "open", "target": "synthetic"}},
                            from_chat=from_chat)
                self.assertFalse(p.ai_thinking)
                self.assertEqual(p.history[0]["content"], "synthetic reply")
                p.say.assert_called_once_with("synthetic reply", 6.0)
                if from_chat:
                    p._log_chat.assert_called_once()
                else:
                    p._log_chat.assert_not_called()
                p.root.after.assert_not_called()
                p.run_agent.assert_not_called()
                p._do_action.assert_not_called()


if __name__ == "__main__":
    unittest.main()
