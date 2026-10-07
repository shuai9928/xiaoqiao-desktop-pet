"""Exercise replacement methods in temporary classes, without writing pet.py.

Uses the existing UI/core fixtures: no Pet construction, private records or AI.
"""
import json
from pathlib import Path
import sys
import textwrap
from types import FunctionType
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pet


def main():
    plan = json.loads((ROOT / "outputs" / "calm-ui" / "card-chat-methods.json")
                      .read_text(encoding="utf-8"))
    methods = {"InteractionCard": {}, "ChatBox": {}}
    for item in plan:
        namespace = dict(vars(pet))
        exec(compile(textwrap.dedent(item["replacement"]),
                     f'<calm-preview:{item["class"]}.{item["method"]}>', "exec"),
             namespace)
        prepared = namespace[item["method"]]
        # Keep production module globals live so existing fixture patches (such
        # as work_area_at for a negative-coordinate monitor) affect the preview.
        method = FunctionType(prepared.__code__, vars(pet), prepared.__name__,
                              prepared.__defaults__, prepared.__closure__)
        method.__kwdefaults__ = prepared.__kwdefaults__
        method.__annotations__ = prepared.__annotations__
        methods[item["class"]][item["method"]] = method
    for name, presentation in methods.items():
        original = getattr(pet, name)
        preview = type(name, (original,), presentation)
        setattr(pet, name, preview)
    suite = unittest.defaultTestLoader.loadTestsFromNames(
        ["test_chat_ui", "test_core_profile"])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
