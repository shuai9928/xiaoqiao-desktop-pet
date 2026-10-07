"""Prepare a guarded, standalone patch for the card/chat presentation methods.

This preparation script never writes pet.py. It produces the reviewable diff,
replacement-method manifest, and a separate application script for the owner.
"""
import ast
import difflib
import hashlib
import json
from pathlib import Path
import textwrap


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "calm-ui"


def method_source(source, class_name, method_name):
    tree = ast.parse(source)
    cls = next(node for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name == class_name)
    fn = next(node for node in cls.body
              if isinstance(node, ast.FunctionDef) and node.name == method_name)
    return "".join(source.splitlines(keepends=True)[fn.lineno - 1:fn.end_lineno])


def once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f"Expected exactly one presentation anchor: {old[:85]!r}")
    return source.replace(old, new)


def patch_card_build(source):
    source = once(source,
                  "        # 立体底板(ui3d):受光渐变 + 金边 + 四角金钉;按钮按自己的位置从底板上\n"
                  "        # 裁一块垫底再叠凸起按钮,投影直接画进底板 —— Tk 窗口不透明也一样有厚度\n",
                  "        # 深紫卡片、细金边与少量柔和层次，让真实状态与四个动作成为主角。\n")
    source = source.replace("ui3d.button(", "ui3d.calm_button(")
    source = once(source, "text='小乔 · 时之魔女',\n                       font=ui_font(18,u,True)",
                  "text='小乔',\n                       font=ui_font(20,u,True)")
    source = once(source, "text=f'陪伴第 {pet.companion_days()} 天',",
                  "text=f'陪伴第 {pet.companion_days()} 天 · 一起度过这会儿',")
    source = once(source,
                  '        # 小时钟标记,静态装饰避免无意义常驻动画。\n'
                  '        cx, cy = 282*u, 38*u\n'
                  '        cv.create_oval(cx-16*u,cy-16*u,cx+16*u,cy+16*u,outline=UI_GOLD,width=1)\n'
                  '        cv.create_line(cx,cy-10*u,cx,cy,cx+7*u,cy+4*u,fill=UI_GOLD,width=2)\n',
                  '        cv.create_line(18*u, 66*u, 302*u, 66*u, fill=UI_BORDER, width=1)\n')
    source = once(source, "font=ui_font(11,u), fill=UI_GOLD)",
                  "font=ui_font(14,u), fill=UI_TEXT)")
    source = once(source, "fill=UI_GOLD,outline='')", "fill=UI_ACCENT,outline='')")
    source = once(source, "font=ui_font(11,u),fill=UI_TEXT_DIM)",
                  "font=ui_font(11,u),fill=UI_TEXT_DIM,width=284*u,justify='left')")
    return source


CARD_BACKGROUND = '''    def _card_background(self, w, h, u):
        """Quiet purple material and a simple star-energy track; no studs or clock."""
        bg = Image.new('RGBA', (int(w), int(h)), UI_BG)
        m = int(3*u)
        body, pad = ui3d.calm_panel(int(w - 2*m), int(h - 2*m), 18*u,
                                   k=u, studs=False)
        Pet._ac(bg, body, m - pad, m - pad)
        d = ImageDraw.Draw(bg)
        d.rounded_rectangle((18*u, 98*u, 302*u, 105*u), radius=3*u,
                            fill=UI_FIELD)
        return bg
'''


def patch_card_button(source):
    source = once(source, "def _button(self, parent, text, action, rect=None, size=13):",
                  "def _button(self, parent, text, action, rect=None, size=14):")
    source = once(source,
                  '        """立体按钮:仍是 tk.Button(焦点、Tab、回车、禁用都照旧),外观换成\n'
                  '        从底板上裁一块垫底再叠的凸起按钮图,四种状态四张图。"""',
                  '        """Calm material; retain Tk focus, activation and disabled behavior."""')
    return source.replace("ui3d.button(", "ui3d.calm_button(")


CHAT_BUTTON_HELPER = '''        # Presentation-only helper: the same Tk buttons keep their callbacks.
        self._button_imgs = []
        def material_button(parent, text, action, bw, bh, *, accent=False, state='normal'):
            bw, bh = int(bw), int(bh)
            imgs = {}
            for look in ('normal', 'hover', 'pressed', 'disabled'):
                image, pad = ui3d.calm_button(bw, bh, 12*u, k=u,
                                              state=look, accent=accent)
                core = image.crop((pad, pad, pad + bw, pad + bh))
                imgs[look] = ImageTk.PhotoImage(core, master=self.win)
            self._button_imgs.append(imgs)
            button = tk.Button(parent, text=text, command=action, image=imgs[state],
                               compound='center', font=f_btn, state=state,
                               bg=UI_PANEL, activebackground=UI_PANEL,
                               fg=UI_TEXT, activeforeground=UI_TEXT,
                               disabledforeground=UI_TEXT_DIM, relief='flat', bd=0,
                               cursor='hand2', takefocus=True, highlightthickness=0,
                               padx=0, pady=0)
            button._imgs = imgs
            def show(look):
                if str(button['state']) == 'disabled':
                    look = 'disabled'
                button.configure(image=imgs[look])
            button.bind('<Enter>', lambda event: show('hover'))
            button.bind('<Leave>', lambda event: show('normal'))
            button.bind('<ButtonPress-1>', lambda event: show('pressed'))
            button.bind('<ButtonRelease-1>', lambda event: show('hover'))
            button.bind('<FocusIn>', lambda event: show('hover'), add='+')
            button.bind('<FocusOut>', lambda event: show('normal'), add='+')
            return button

'''


def patch_chat_init(source):
    source = once(source, '-int(18 * u), "bold"', '-int(20 * u), "bold"')
    source = once(source, '-int(13 * u), "bold"', '-int(14 * u), "bold"')
    source = once(source, '-int(10 * u)', '-int(11 * u)')
    source = once(source, "        # 星空背景\n", "        # 缓存的深紫面板；内容区留给真实聊天记录。\n")
    source = once(source, 'int(20*u), int(25*u)', 'int(24*u), int(29*u)')
    source = once(source, 'text="✦ 和小乔聊一会儿"', 'text="和小乔聊天"')
    source = once(source, 'int(20*u), int(50*u)', 'int(24*u), int(58*u)')
    source = once(source, 'self.w_-int(34*u), int(28*u)', 'self.w_-int(38*u), int(29*u)')
    source = once(source, 'width=int(30*u), height=int(30*u)',
                  'width=int(32*u), height=int(32*u)')
    source = once(source, '        quick = tk.Frame(self.win, bg=UI_PANEL)\n',
                  CHAT_BUTTON_HELPER + '        quick = tk.Frame(self.win, bg=UI_PANEL)\n')
    source = once(source, 'int(16*u), int(70*u)', 'int(22*u), int(82*u)')
    source = once(source, 'width=self.w_-int(32*u), height=int(32*u)',
                  'width=self.w_-int(44*u), height=int(34*u)')
    source = once(source,
                  '            tk.Button(quick, text=label, command=action, font=f_btn, relief="flat",\n'
                  '                      bg=UI_BTN, fg=UI_TEXT, activebackground=UI_ACCENT,\n'
                  '                      activeforeground=UI_GOLD, cursor="hand2", bd=0).pack(\n'
                  '                          side="left", fill="both", expand=True, padx=3)\n',
                  '            material_button(quick, label, action,\n'
                  '                            (self.w_ - 44*u) / 3 - 6*u, 34*u).pack(\n'
                  '                                side="left", fill="both", expand=True, padx=int(3*u))\n')
    source = once(source, 'inset_top = int(114 * u)', 'inset_top = int(128 * u)')
    source = once(source, 'self.h_ - inset_top - int(94 * u)',
                  'self.h_ - inset_top - int(112 * u)')
    source = once(source, 'tk.Text(self.win, bg=UI_BG, fg=UI_TEXT',
                  'tk.Text(self.win, bg=UI_PANEL, fg=UI_TEXT')
    source = once(source,
                  '                           padx=int(10 * u), pady=int(6 * u),\n'
                  '                           highlightthickness=int(1.4 * u),\n'
                  '                           highlightbackground=UI_BORDER, highlightcolor=UI_GOLD,\n'
                  '                           spacing1=4, spacing3=6)',
                  '                           padx=int(14 * u), pady=int(10 * u),\n'
                  '                           highlightthickness=0,\n'
                  '                           spacing1=8, spacing3=10)')
    source = once(source, 'int(14 * u), inset_top, anchor="nw"',
                  'int(22 * u), inset_top, anchor="nw"')
    source = once(source, 'width=self.w_ - int(46 * u), height=self.log_h',
                  'width=self.w_ - int(60 * u), height=self.log_h')
    source = once(source, 'bg=UI_BTN, troughcolor=UI_BG, activebackground=UI_ACCENT',
                  'bg=UI_PANEL, troughcolor=UI_PANEL, activebackground=UI_ACCENT')
    source = once(source, 'self.w_-int(27*u), inset_top', 'self.w_-int(32*u), inset_top')
    source = once(source, 'width=int(13*u), height=self.log_h',
                  'width=int(10*u), height=self.log_h')
    source = once(source, 'foreground="#9FD8FF", spacing1=6',
                  'foreground=UI_TEXT, spacing1=8')
    source = once(source, 'foreground="#FFC9D6", spacing1=6',
                  'foreground=UI_TEXT, spacing1=8')
    source = once(source, 'foreground="#7BB8E0", font=f_btn',
                  'foreground=UI_TEXT_DIM, font=f_btn')
    source = once(source, 'foreground="#FF8FA6", font=f_btn',
                  'foreground=UI_GOLD, font=f_btn')
    source = once(source, 'inset_top + self.log_h + int(10 * u)',
                  'inset_top + self.log_h + int(14 * u)')
    source = once(source, 'row = tk.Frame(self.win, bg=KEY)',
                  'row = tk.Frame(self.win, bg=UI_PANEL)')
    source = once(source, 'int(14 * u), row_y, anchor="nw"',
                  'int(22 * u), row_y, anchor="nw"')
    source = once(source, 'width=self.w_ - int(28 * u), height=int(38 * u)',
                  'width=self.w_ - int(44 * u), height=int(46 * u)')
    source = once(source, 'padx=(0, int(6 * u))', 'padx=(0, int(12 * u))')
    source = once(source,
                  '        self.send_btn = tk.Button(row, text="发送 ✦", command=self.send, relief="flat", cursor="hand2",\n'
                  '                  bg=UI_ACCENT, fg=UI_GOLD, font=f_btn,\n'
                  '                  disabledforeground=UI_TEXT_DIM, state="disabled",\n'
                  '                  activebackground="#9B7BE0", activeforeground="#FFF6D9")\n'
                  '        self.send_btn.pack(side="left", fill="y", ipadx=int(10*u))\n',
                  '        self.send_btn = material_button(row, "发送", self.send,\n'
                  '                                        82*u, 46*u, accent=True, state="disabled")\n'
                  '        self.send_btn.pack(side="left", fill="y")\n')
    source = once(source,
                  '            state="normal" if self.draft.get().strip() else "disabled"))',
                  '            state="normal" if self.draft.get().strip() else "disabled",\n'
                  '            image=self.send_btn._imgs["normal" if self.draft.get().strip() else "disabled"]))')
    source = once(source, 'text="写下想聊的话  ·  Enter 发送  ·  ↑↓ 历史  ·  Esc 关闭"',
                  'text="Enter 发送   ·   ↑↓ 已发消息   ·   Esc 关闭"')
    source = once(source, '.place(x=int(14 * u),', '.place(x=int(24 * u),')
    source = once(source, 'y=self.h_ - int(26 * u)', 'y=self.h_ - int(30 * u)')
    source = once(source, '"随时告诉我你想聊什么,或者点上方按钮一起玩。"',
                  '"想聊什么，随时告诉我。"')
    source = once(source, '"想开启 AI 聊天,请在小乔的右键菜单「设置 → 设置 AI 密钥」中连接。"',
                  '"尚未连接 AI。可在右键菜单「设置 → 连接 AI 聊天」中连接。"')
    return source


CHAT_BACKGROUND = '''    def _render_bg(self, w, h, tail):
        """Cached quiet purple surface; no stars, glass glow or ornamental studs."""
        u = tail / 16.0
        frame = Image.new("RGBA", (w, h + tail), KEY)
        body, pad = ui3d.calm_panel(w - 4, h - 4, 20*u, k=u,
                                   alpha=255, studs=False)
        Pet._ac(frame, body, 2 - pad, 2 - pad)
        inset_top = int(128*u)
        log_h = h - inset_top - int(112*u)
        tone = tuple(int(UI_PANEL[i:i+2], 16) for i in (1, 3, 5))
        well, wp = ui3d.calm_panel(int(w - 36*u), int(log_h + 12*u),
                                  14*u, k=u*0.35, alpha=255,
                                  tone=(tone, tone), studs=False)
        Pet._ac(frame, well, 18*u - wp, inset_top - 6*u - wp)
        d = ImageDraw.Draw(frame)
        d.line((24*u, 74*u, w - 24*u, 74*u), fill=UI_BORDER, width=1)
        d.line((24*u, h - 46*u, w - 24*u, h - 46*u), fill=UI_BORDER, width=1)
        return frame.convert("RGB")
'''


APPLY_SCRIPT = r'''"""Apply only the reviewed card/chat presentation methods, atomically.

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
'''


def main():
    source = (ROOT / "pet.py").read_text(encoding="utf-8")
    transformations = {
        ("InteractionCard", "_build"): patch_card_build,
        ("InteractionCard", "_card_background"): lambda old: CARD_BACKGROUND,
        ("InteractionCard", "_button"): patch_card_button,
        ("ChatBox", "__init__"): patch_chat_init,
        ("ChatBox", "_render_bg"): lambda old: CHAT_BACKGROUND,
    }
    plan = []
    for (class_name, method_name), transform in transformations.items():
        old = method_source(source, class_name, method_name)
        new = transform(old)
        ast.parse(textwrap.dedent(new))
        plan.append({"class": class_name, "method": method_name,
                     "sha256": hashlib.sha256(old.encode("utf-8")).hexdigest(),
                     "replacement": new})
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "card-chat-methods.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    application = ROOT / "tools" / "apply_calm_chat_card.py"
    application.write_text(APPLY_SCRIPT, encoding="utf-8")
    print(f"Prepared {application}; pet.py was not modified.")


if __name__ == "__main__":
    main()
