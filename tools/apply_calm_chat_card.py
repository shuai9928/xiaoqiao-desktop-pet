"""Apply only the reviewed card/chat presentation methods, atomically.

Default: validate and refresh the diff without touching pet.py.
Use --apply once the owner has finished concurrent edits elsewhere in pet.py.
"""
import argparse
import ast
from datetime import datetime, timedelta, timezone
import difflib
import hashlib
import json
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "calm-ui"


def locate(source, class_name, method_name):
    cls = next(node for node in ast.parse(source).body
               if isinstance(node, ast.ClassDef) and node.name == class_name)
    return next(node for node in cls.body
                if isinstance(node, ast.FunctionDef) and node.name == method_name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    plan = json.loads((OUTPUT / "card-chat-methods.json").read_text(encoding="utf-8"))
    path = ROOT / "pet.py"
    original = path.read_bytes()
    source = original.decode("utf-8").replace("\r\n", "\n")
    lines = source.splitlines(keepends=True)
    replacements = []
    for item in plan:
        node = locate(source, item["class"], item["method"])
        old = "".join(lines[node.lineno - 1:node.end_lineno])
        digest = hashlib.sha256(old.encode("utf-8")).hexdigest()
        if digest != item["sha256"]:
            raise SystemExit(f'Refusing changed method: {item["class"]}.{item["method"]}')
        replacements.append((node.lineno - 1, node.end_lineno, item["replacement"]))
        print(f'{item["class"]}.{item["method"]}: {node.lineno}-{node.end_lineno}; '
              f'{len(old.splitlines())} -> {len(item["replacement"].splitlines())} lines')
    for start, end, new in sorted(replacements, reverse=True):
        lines[start:end] = [new]
    updated = "".join(lines)
    compile(updated, str(path), "exec")
    diff = "".join(difflib.unified_diff(source.splitlines(keepends=True),
                                       updated.splitlines(keepends=True),
                                       fromfile="pet.py", tofile="pet.py"))
    (OUTPUT / "card-chat.patch").write_text(diff, encoding="utf-8")
    if not args.apply:
        print("Validated; pet.py unchanged. Review outputs/calm-ui/card-chat.patch.")
        return
    helpers = ast.parse((ROOT / "ui3d.py").read_text(encoding="utf-8"))
    available = {node.name for node in helpers.body if isinstance(node, ast.FunctionDef)}
    if not {"calm_panel", "calm_button"} <= available:
        raise SystemExit("Install shared ui3d.calm_panel/calm_button before applying.")
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%dT%H%M%S%f")
    backup = OUTPUT / f"pet-before-card-chat-{stamp}.py"
    backup.write_bytes(original)
    encoded = updated.replace("\n", "\r\n").encode("utf-8") if b"\r\n" in original else updated.encode("utf-8")
    fd, pending = tempfile.mkstemp(prefix=".card-chat-", suffix=".py", dir=ROOT)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
        if path.read_bytes() != original:
            raise SystemExit("Concurrent pet.py change detected; nothing was applied.")
        os.replace(pending, path)
    finally:
        if os.path.exists(pending):
            os.remove(pending)
    print(f"Applied five presentation methods; backup: {backup}")


if __name__ == "__main__":
    main()
