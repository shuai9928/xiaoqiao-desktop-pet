"""Clickable room layout study. Does not read or change live AI/user data."""
from __future__ import annotations

import argparse
import math
import time
import threading
from pathlib import Path
import tkinter as tk
from tkinter import font as tkfont

from PIL import ImageTk

from room_preview import ENTRANCE_LABELS, RoomSceneRenderer
from depth_model import DepthMotion
import ui3d

INK = "#191522"
PAPER = "#251e36"
GOLD = "#%02x%02x%02x" % ui3d.CALM_GOLD
TEXT = "#%02x%02x%02x" % ui3d.CALM_TEXT
MUTED = "#%02x%02x%02x" % ui3d.CALM_MUTED
ACCENT = "#%02x%02x%02x" % ui3d.CALM_ACCENT
PAGES = {
    "trace": ("魔法书 · 工作轨迹", "看看 AI 正在做什么",
              "当前任务、最近动作、结果和等待确认，都放在这本书里。",
              "尚未接入真实工作记录；此处仅演示入口。"),
    "chat": ("信笺 · 对话记录", "回看你们说过的话",
             "按 AI 和会话找聊天，区分用户消息与 AI 回复，再查看、搜索或复制。",
             "这里暂时没有读取聊天内容。"),
    "quota": ("水晶 · 额度与状态", "一眼看清还能用多少",
              "水晶负责状态速览，展开后查看所属服务、各周期剩余额度和恢复时间。",
              "这里暂时没有接入额度数据。"),
}


class _FrameWorker:
    """Render off the Tk thread. Keep only the newest request and completed frame."""

    def __init__(self, renderer):
        self.renderer = renderer
        self.condition = threading.Condition()
        self.request = None
        self.result = None
        self.stopped = False
        self.revision = 0
        self.thread = threading.Thread(target=self._run, name="room-preview", daemon=True)
        self.thread.start()

    def submit(self, view, lag, breath):
        with self.condition:
            self.request = (view, lag, breath)
            self.condition.notify()

    def take(self):
        with self.condition:
            result, self.result = self.result, None
            return result

    def stop(self):
        with self.condition:
            self.stopped = True
            self.request = None
            self.condition.notify()

    def _run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.stopped or self.request is not None)
                if self.stopped:
                    return
                request, self.request = self.request, None
            try:
                image, rects = self.renderer.render(1.0, *request)
                result = (image, rects, None)
            except Exception as error:
                result = (None, None, error)
            with self.condition:
                if self.stopped:
                    return
                self.result = result


class RoomPreviewWindow:
    """A separate, single-instance preview; closing it never changes the pet."""

    def __init__(self, parent, assets_dir, scale=1.0):
        self.assets_dir = Path(assets_dir)
        self.scale = scale
        self.selected = None
        self.focused = None
        self.closed = False
        self.dynamic = True
        self._animation_id = None
        self._motion = DepthMotion()
        self._target = (0.0, 0.0)
        self._view = self._lag = (0.0, 0.0)
        self._breath = 0.0
        self._started = time.monotonic()
        self._renderer = RoomSceneRenderer(self.assets_dir)
        self._worker = None
        self._base_image = self._base_rects = None
        self.win = tk.Toplevel(parent)
        self.win.withdraw()
        self.win.title("小乔的小屋 · 2.5D 空间预览")
        self.win.configure(bg=INK, highlightbackground="#54445f", highlightthickness=1)
        self.win.overrideredirect(True)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.win.bind("<Escape>", lambda _e: self.close())
        self.win.bind("<Tab>", self._next_entrance)
        self.win.bind("<Shift-Tab>", lambda e: self._next_entrance(e, -1))
        self.win.bind("<Return>", self._activate_focused)
        self.win.bind("<Destroy>", self._destroyed)

        header = tk.Frame(self.win, bg=INK, padx=18, pady=14)
        header.pack(fill="x")
        title = tk.Label(header, text="☾  小乔的小屋", bg=INK, fg=TEXT,
                         font=("Microsoft YaHei UI", 14, "bold"))
        title.pack(side="left")
        tk.Label(header, text="空间预览", bg=INK, fg=MUTED,
                 font=("Microsoft YaHei UI", 9), padx=12).pack(side="left")
        self._drag_origin = None
        for widget in (header, title):
            widget.bind("<ButtonPress-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)
        self._button(header, "×", self.close).pack(side="right")
        self.dynamic_button = self._button(header, "动态开启", self.toggle_dynamic)
        self.dynamic_button.pack(side="right", padx=4)
        self._style_button(self.dynamic_button, True)
        self.scale_buttons = {}
        for value, label in ((0.76, "76%"), (1.0, "100%")):
            button = self._button(header, label, lambda s=value: self.set_scale(s))
            button.pack(side="right", padx=4)
            self.scale_buttons[value] = button

        body = tk.Frame(self.win, bg=INK, padx=18)
        body.pack(fill="both", expand=True)
        scene_area = tk.Frame(body, bg=INK)
        scene_area.pack(side="left", anchor="n")
        self.canvas = tk.Canvas(scene_area, bg=INK, highlightthickness=0,
                                takefocus=True)
        self.canvas.pack()
        self.canvas.bind("<Motion>", self._hover)
        self.canvas.bind("<Leave>", self._leave)
        self.canvas.bind("<Button-1>", self._click)
        self.hint = tk.StringVar(value="点魔法书、信笺或水晶，看看入口")
        tk.Label(scene_area, textvariable=self.hint, bg=INK, fg=ACCENT,
                 font=("Microsoft YaHei UI", 9), pady=8).pack()

        # Stable book page: text stays readable when only the scene is resized.
        self.page_shell = tk.Canvas(body, bg=INK, highlightthickness=0)
        self.page_shell.pack(side="left", anchor="n", padx=(14, 0), pady=(24, 0))
        self.page_tabs_frame = tk.Frame(self.page_shell, bg=PAPER)
        self._tabs_window = self.page_shell.create_window(0, 0, anchor="nw",
                                                         window=self.page_tabs_frame)
        self.page_tabs = {}
        for key, label in (("trace", "工作轨迹"), ("chat", "对话"), ("quota", "额度")):
            button = self._button(self.page_tabs_frame, label, lambda k=key: self.select(k))
            button.pack(side="left", padx=2)
            self.page_tabs[key] = button
        page = tk.Frame(self.page_shell, bg=PAPER, padx=18, pady=18, width=286, height=310)
        self._page_window = self.page_shell.create_window(0, 0, anchor="nw", window=page)
        page.pack_propagate(False)
        self.page = page
        tk.Label(page, text="小屋手记 · 布局预览", fg=MUTED, bg=PAPER,
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(0, 14))
        self.page_title = tk.StringVar()
        self.page_subtitle = tk.StringVar()
        self.page_body = tk.StringVar()
        self.page_note = tk.StringVar()
        for variable, color, size, bold, pady in (
            (self.page_title, TEXT, 13, True, (0, 10)),
            (self.page_subtitle, ACCENT, 10, False, (0, 16)),
            (self.page_body, TEXT, 10, False, (0, 18)),
            (self.page_note, MUTED, 9, False, (0, 0)),
        ):
            tk.Label(page, textvariable=variable, fg=color, bg=PAPER,
                     font=("Microsoft YaHei UI", size, "bold" if bold else "normal"),
                     wraplength=246, justify="left", anchor="w", pady=3).pack(
                         fill="x", pady=pady)
        self.page_title.set("欢迎到小屋坐坐")
        self.page_subtitle.set("先看布局，再完善功能")
        self.page_body.set("魔法书看工作轨迹，信笺看对话，水晶看额度。右上角的月牙返回秋千。")
        self.page_note.set("本次是可点击的布局样稿。室内手势和家具还需换成同画风素材。")
        self._fit_page()
        footer = tk.Frame(self.win, bg=INK, padx=18, pady=12)
        footer.pack(fill="x")
        tk.Label(footer, text="移鼠标看空间视差  ·  拖动上沿移动  ·  Tab / Enter 选入口  ·  Esc 返回",
                 bg=INK, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor="w")

        self.set_scale(scale)
        self.win.update_idletasks()
        width, height = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        x = max(0, (self.win.winfo_screenwidth() - width) // 2)
        y = max(0, (self.win.winfo_screenheight() - height) // 2)
        self.win.geometry(f"+{x}+{y}")
        self.win.deiconify()
        self.canvas.focus_set()
        self._worker = _FrameWorker(self._renderer)
        self._animation_id = self.win.after(50, self._animate)

    def _button(self, parent, text, command):
        font = tkfont.Font(parent, family="Microsoft YaHei UI", size=10)
        width, height = max(34, font.measure(text) + 24), max(32, font.metrics("linespace") + 12)
        photos = {}
        for selected in (False, True):
            for state in ("normal", "hover", "pressed"):
                image, _pad = ui3d.calm_button(width, height, 9, state=state, accent=selected)
                photos[selected, state] = ImageTk.PhotoImage(image, master=self.win)
        background = parent.cget("bg")
        button = tk.Button(parent, text=text, command=command, bg=background, fg=MUTED,
                           activebackground=background, activeforeground=TEXT,
                           relief="flat", bd=0, padx=0, pady=0, compound="center",
                           image=photos[False, "normal"], font=font, cursor="hand2",
                           highlightthickness=0, takefocus=False)
        button._calm_photos, button._calm_font = photos, font
        button._calm_selected = False
        for event, state in (("<Enter>", "hover"), ("<Leave>", "normal"),
                             ("<ButtonPress-1>", "pressed"), ("<ButtonRelease-1>", "hover")):
            button.bind(event, lambda _e, s=state: button.configure(
                image=photos[button._calm_selected, s]))
        return button

    @staticmethod
    def _style_button(button, selected):
        button._calm_selected = selected
        button.configure(fg=TEXT if selected else MUTED,
                         image=button._calm_photos[selected, "normal"])

    def set_scale(self, scale):
        if scale not in (1.0, 0.76):
            raise ValueError("Preview supports 100% and 76% scene size")
        self.scale = scale
        self._draw_frame()
        for value, button in self.scale_buttons.items():
            self._style_button(button, value == scale)

    def _draw_frame(self):
        if self._base_image is None:
            self._base_image, self._base_rects = self._renderer.render(1.0, self._view, self._lag, self._breath)
        self._apply_frame(self._base_image, self._base_rects)

    def _apply_frame(self, image, rects):
        from PIL import Image
        im = image.convert("RGBa").resize((round(400*self.scale), round(500*self.scale)),
                                            Image.Resampling.LANCZOS).convert("RGBA")
        self.rects = {}
        for key, (x, y, w, h) in rects.items():
            cx, cy = (x+w/2)*self.scale, (y+h/2)*self.scale
            sw, sh = max(32, w*self.scale), max(32, h*self.scale)
            left, top = round(cx-sw/2), round(cy-sh/2)
            self.rects[key] = (left, top, round(cx+sw/2)-left, round(cy+sh/2)-top)
        self.photo = ImageTk.PhotoImage(im, master=self.win)
        self.canvas.configure(width=self.photo.width(), height=self.photo.height())
        if hasattr(self, "_image_item"):
            self.canvas.itemconfigure(self._image_item, image=self.photo)
        else:
            self._image_item = self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self._highlight(self.selected or self.focused)

    def toggle_dynamic(self):
        self.dynamic = not self.dynamic
        self.dynamic_button.configure(text="动态开启" if self.dynamic else "动态关闭")
        self._style_button(self.dynamic_button, self.dynamic)
        if not self.dynamic:
            self._view = self._lag = (0.0, 0.0)
            self._breath = 0.0
            self._motion = DepthMotion()
            if self._worker:
                self._worker.submit(self._view, self._lag, self._breath)
        elif self._animation_id is None:
            self._animation_id = self.win.after(50, self._animate)

    def _animate(self):
        self._animation_id = None
        if self.closed:
            return
        start = time.monotonic()
        if not self.win.winfo_viewable():
            self._animation_id = self.win.after(250, self._animate)
            return
        t = start - self._started
        if self.dynamic:
            pose = self._motion.sample(start, *self._target)
            self._view = (pose[2], pose[3])
            self._lag = (pose[4], pose[5])
            self._breath = .85 * math.sin(t * math.tau / 4.8)
            self._worker.submit(self._view, self._lag, self._breath)
        completed = self._worker.take()
        if completed is not None:
            image, rects, error = completed
            if error is not None:
                self.dynamic = False
                self.dynamic_button.configure(text="动态暂停")
                self._style_button(self.dynamic_button, False)
                self.hint.set("动态暂不可用，可继续看布局")
            else:
                self._base_image, self._base_rects = image, rects
                self._apply_frame(image, rects)
        # Render time is deducted; no queued frames accumulate when busy.
        elapsed = round((time.monotonic() - start) * 1000)
        self._animation_id = self.win.after(max(8, (50 if self.dynamic else 150) - elapsed), self._animate)

    def hit_test(self, x, y):
        for key, (left, top, width, height) in self.rects.items():
            if left <= x < left + width and top <= y < top + height:
                return key
        return None

    def _fit_page(self):
        """Grow the book to fit wrapped text, including larger Windows fonts."""
        self.win.update_idletasks()
        height = 2 * int(self.page.cget("pady"))
        for widget in self.page.winfo_children():
            raw = widget.pack_info().get("pady", 0)
            if isinstance(raw, (tuple, list)):
                padding = raw
            elif isinstance(raw, (int, float)):
                padding = (raw,)
            else:
                padding = self.win.tk.splitlist(raw)
            amounts = [self.win.winfo_pixels(v) for v in padding]
            height += widget.winfo_reqheight() + (sum(amounts) if len(amounts) == 2 else 2 * amounts[0])
        height = max(310, height)
        self.page.configure(height=height)
        top = 12 + self.page_tabs_frame.winfo_reqheight() + 4
        material, pad = ui3d.calm_panel(310, top + height + 12, 18)
        self._page_surface = ImageTk.PhotoImage(material, master=self.win)
        self.page_shell.configure(width=material.width, height=material.height)
        self.page_shell.delete("page-surface")
        self.page_shell.create_image(0, 0, anchor="nw", image=self._page_surface, tags="page-surface")
        self.page_shell.tag_lower("page-surface")
        self.page_shell.coords(self._tabs_window, pad + 18, pad + 12)
        self.page_shell.coords(self._page_window, pad + 12, pad + top)
        self.page_shell.itemconfigure(self._page_window, width=286, height=height)

    def _highlight(self, key):
        self.canvas.delete("entrance-focus")
        if key in self.rects:
            x, y, w, h = self.rects[key]
            self.canvas.create_rectangle(x, y, x + w - 1, y + h - 1,
                                         outline=ACCENT, width=1,
                                         tags="entrance-focus")

    def _hover(self, event):
        self._target = (max(-1, min(1, event.x / self.photo.width() * 2 - 1)),
                        max(-1, min(1, event.y / self.photo.height() * 2 - 1)))
        key = self.hit_test(event.x, event.y)
        self.canvas.configure(cursor="hand2" if key else "")
        self.hint.set(ENTRANCE_LABELS[key] if key else "点魔法书、信笺或水晶，看看入口")
        self._highlight(key or self.selected or self.focused)

    def _leave(self, _event):
        self._target = (0.0, 0.0)
        self._highlight(self.selected or self.focused)

    def _click(self, event):
        self.canvas.focus_set()
        self.select(self.hit_test(event.x, event.y))

    def select(self, key):
        if key == "back":
            self.close()
        elif key in PAGES:
            self.selected = self.focused = key
            for page_key, button in self.page_tabs.items():
                self._style_button(button, page_key == key)
            for variable, value in zip((self.page_title, self.page_subtitle,
                                        self.page_body, self.page_note), PAGES[key]):
                variable.set(value)
            self._fit_page()
            self.hint.set(ENTRANCE_LABELS[key])
            self._highlight(key)

    def _next_entrance(self, _event=None, direction=1):
        keys = ("trace", "chat", "quota", "back")
        index = keys.index(self.focused) if self.focused in keys else (-1 if direction == 1 else 0)
        self.focused = keys[(index + direction) % len(keys)]
        self.hint.set(ENTRANCE_LABELS[self.focused])
        self._highlight(self.focused)
        return "break"

    def _activate_focused(self, _event=None):
        self.select(self.focused)
        return "break"

    def _drag_start(self, event):
        self._drag_origin = (event.x_root, event.y_root, self.win.winfo_x(), self.win.winfo_y())

    def _drag_move(self, event):
        if self._drag_origin:
            x0, y0, wx, wy = self._drag_origin
            x = min(max(0, wx + event.x_root - x0),
                    max(0, self.win.winfo_screenwidth() - self.win.winfo_width()))
            y = min(max(0, wy + event.y_root - y0),
                    max(0, self.win.winfo_screenheight() - self.win.winfo_height()))
            self.win.geometry(f"+{x}+{y}")

    def _destroyed(self, event):
        if event.widget == self.win:
            self.closed = True
            if self._worker:
                self._worker.stop()
            if self._animation_id is not None:
                try:
                    self.win.after_cancel(self._animation_id)
                except tk.TclError:
                    pass
                self._animation_id = None

    def show(self):
        if not self.closed:
            self.win.deiconify()
            self.win.lift()
            self.canvas.focus_set()

    def close(self):
        if not self.closed:
            self.closed = True
            if self._worker:
                self._worker.stop()
            if self._animation_id is not None:
                self.win.after_cancel(self._animation_id)
                self._animation_id = None
            self.win.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, default=Path(__file__).parent / "assets")
    parser.add_argument("--scale", type=float, choices=(1.0, 0.76), default=1.0)
    args = parser.parse_args()
    root = tk.Tk()
    root.withdraw()
    view = RoomPreviewWindow(root, args.assets, args.scale)
    view.win.bind("<Destroy>", lambda e: root.quit() if e.widget == view.win else None, add="+")
    print("小乔的小屋布局预览已打开。", flush=True)
    root.mainloop()
    root.destroy()


if __name__ == "__main__":
    main()
