# -*- coding: utf-8 -*-
"""右键互动卡片。从 pet.py 原样搬出,行为不变。

只依赖 tkinter 和 ui_theme,不 import pet;需要桌宠的地方都走构造时传入
的 pet 实例。所在显示器的工作区 area 由 Pet.open_action_card 算好传进来,
这样多显示器定位仍然只有 pet.work_area_at 一个入口(测试也打桩在那里)。
"""
import tkinter as tk

from ui_theme import (UI_ACCENT, UI_BG, UI_BORDER, UI_BTN, UI_FIELD, UI_GOLD,
                      UI_PANEL, UI_TEXT, UI_TEXT_DIM, UI_TITLE, ui_font)


class InteractionCard:
    """用户右键唤出的不透明卡片;不会常驻,动作仍由 Pet 统一处理。"""

    HINTS = {'聊天':'聊聊天，或让我帮你做点事', '喂糖':'吃颗糖，最多补充 40 点星光',
             '时间魔法':'施放你选好的时间魔法', '跳舞':'跟着星光跳一支舞',
             '玩球':'光球出现后，点它就能接住', '睡觉':'打个哈欠，安心休息一会儿'}

    @staticmethod
    def disabled_reasons(pet):
        reasons = {}
        if pet.state in ('magic','eat'):
            reason = '等这次魔法结束，再点我吧' if pet.state=='magic' else '先让我吃完这颗糖~'
            reasons.update({'喂糖':reason, '时间魔法':reason})
        if pet.state in ('fly','fall'):
            reasons.update({key:'等我落稳，再一起玩~' for key in ('喂糖','时间魔法','跳舞')})
        if pet.state in ('sleep','yawn'):
            reasons['玩球'] = '先叫醒小乔，再一起接光球'
        elif getattr(pet,'singing',False):
            reasons['睡觉'] = '先在「更多」里停止唱歌，再休息'
        return reasons

    @staticmethod
    def position(x, y, w, h, area):
        left, top, right, bottom = area
        return (int(max(left+8, min(x, right-w-8))),
                int(max(top+8, min(y, bottom-h-8))))

    def __init__(self, pet, x, y, area):
        self.pet = pet
        self.closed = False
        self._refresh_id = self._focus_id = None
        self.win = tk.Toplevel(pet.root)
        self.win.withdraw()
        try:
            self._build(x, y, area)
        except Exception:
            self.win.destroy()
            raise

    def _build(self, x, y, area):
        pet, win = self.pet, self.win
        u = max(1.0, min(1.5, (area[3]-area[1])/1080))
        w, h = int(320*u), int(384*u)
        self.u = u
        x, y = self.position(x+8, y+8, w, h, area)
        win.title('小乔 · 互动卡片')
        win.overrideredirect(True)
        win.attributes('-topmost', True)
        win.configure(bg=UI_BG)
        win.geometry(f'{w}x{h}+{x}+{y}')
        self.cv = cv = tk.Canvas(win, bg=UI_BG, highlightthickness=0, bd=0)
        cv.pack(fill='both', expand=True)
        # 不使用透明窗口;内部轮廓以平滑折线构成圆角。
        r, pad = 16*u, 2*u
        cv.create_polygon(pad+r,pad, w-pad-r,pad, w-pad,pad, w-pad,pad+r,
                          w-pad,h-pad-r, w-pad,h-pad, w-pad-r,h-pad,
                          pad+r,h-pad, pad,h-pad, pad,h-pad-r, pad,pad+r,pad,pad,
                          smooth=True, splinesteps=24, fill=UI_PANEL, outline=UI_BORDER, width=1)
        cv.create_text(18*u, 28*u, anchor='w', text='小乔 · 时之魔女',
                       font=ui_font(18,u,True), fill=UI_TITLE)
        cv.create_text(18*u, 53*u, anchor='w', text=f'陪伴第 {pet.companion_days()} 天',
                       font=ui_font(11,u), fill=UI_TEXT_DIM)
        # 小时钟标记,静态装饰避免无意义常驻动画。
        cx, cy = 282*u, 38*u
        cv.create_oval(cx-16*u,cy-16*u,cx+16*u,cy+16*u,outline=UI_GOLD,width=1)
        cv.create_line(cx,cy-10*u,cx,cy,cx+7*u,cy+4*u,fill=UI_GOLD,width=2)
        self.status = cv.create_text(18*u, 82*u, anchor='w', font=ui_font(11,u), fill=UI_GOLD)
        cv.create_rectangle(18*u,99*u,302*u,104*u,fill=UI_FIELD,outline='')
        self.energy = cv.create_rectangle(18*u,99*u,18*u,104*u,fill=UI_GOLD,outline='')
        self._hint_key = None
        self.hint = cv.create_text(18*u,128*u,anchor='w',text=self._default_hint(),font=ui_font(11,u),fill=UI_TEXT_DIM)
        grid = tk.Frame(win, bg=UI_PANEL)
        cv.create_window(16*u,146*u,anchor='nw',window=grid,width=288*u,height=170*u)
        grid.columnconfigure((0,1), weight=1, uniform='actions')
        self.buttons = {}
        choices = [('聊天', pet.open_chat), ('喂糖', pet.eat_candy),
                   ('时间魔法', pet.cast_magic), ('跳舞', pet.start_dance),
                   ('玩球', pet.throw_ball), ('睡觉', self._sleep)]
        for i, (label, action) in enumerate(choices):
            grid.rowconfigure(i//2, weight=1, uniform='actions')
            button = self._button(grid, label, lambda fn=action,key=label: self._run(fn,key))
            button.bind('<Enter>',lambda e,key=label:self._show_hint(key),add='+')
            button.bind('<FocusIn>',lambda e,key=label:self._focus_hint(key))
            button.bind('<Leave>',lambda e:self._show_hint(None),add='+')
            button.grid(row=i//2,column=i%2,sticky='nsew',padx=3*u,pady=4*u)
            self.buttons[label] = button
        footer = tk.Frame(win, bg=UI_PANEL)
        cv.create_window(18*u,334*u,anchor='nw',window=footer,width=284*u,height=32*u)
        self._button(footer, '更多  ›', self._more).pack(side='left',fill='y',ipadx=12*u)
        self._button(footer, '关闭  Esc', self.close).pack(side='right',fill='y',ipadx=8*u)
        win.bind('<Escape>', lambda e: self.close())
        win.bind('<FocusOut>', self._on_focus_out)
        win.protocol('WM_DELETE_WINDOW', self.close)
        self._refresh()
        win.deiconify()
        win.lift()
        # 打开时程序自动把焦点给「聊天」,这一下别用按钮说明盖掉今日小结
        self._auto_focus = True
        self._auto_focus_id = win.after(250, self._end_auto_focus)
        self.buttons['聊天'].focus_force()

    def _button(self, parent, text, action):
        b = tk.Button(parent, text=text, command=action, font=ui_font(13,self.u,True),
                      bg=UI_BTN, fg=UI_TEXT, activebackground=UI_ACCENT, activeforeground=UI_GOLD,
                      disabledforeground=UI_TEXT_DIM,
                      relief='flat', bd=0, cursor='hand2', takefocus=True,
                      highlightthickness=1, highlightbackground=UI_BTN, highlightcolor=UI_GOLD)
        b.bind('<Enter>', lambda e: b.configure(bg=UI_ACCENT if str(b['state'])!='disabled' else UI_BTN))
        b.bind('<Leave>', lambda e: b.configure(bg=UI_BTN))
        b.bind('<Return>', lambda e: (b.invoke(), 'break')[1])
        return b

    def _refresh(self):
        if self.closed:
            return
        star = max(0, min(100, self.pet.star))
        self.cv.itemconfigure(self.status, text=f'星光 {int(star)}%  ·  {self.pet.affection_level()}')
        self.cv.coords(self.energy,18*self.u,99*self.u,(18+284*star/100)*self.u,104*self.u)
        self.buttons['睡觉'].configure(text='叫醒' if self.pet.state in ('sleep','yawn') else '睡觉')
        reasons = self.disabled_reasons(self.pet)
        for key, button in self.buttons.items():
            button.configure(state='disabled' if key in reasons else 'normal')
            if key in reasons:
                button.configure(bg=UI_BTN)
        self._show_hint(self._hint_key)
        self._refresh_id = self.win.after(400, self._refresh)

    def _focus_hint(self, key):
        """Tab 切焦点时显示按钮说明;打开卡片瞬间的程序自动聚焦除外。"""
        if getattr(self, '_auto_focus', False):
            return
        self._show_hint(key)

    def _end_auto_focus(self):
        self._auto_focus = False

    def _default_hint(self):
        """没悬停按钮时显示今天的陪伴小结(最多三项,卡片放不下更多)。"""
        s = self.pet._today_summary(limit=3)
        return f'今天 · {s}' if s else '一起度过这会儿'

    def _show_hint(self, key):
        if self.closed:
            return
        self._hint_key = key
        reason = self.disabled_reasons(self.pet).get(key)
        hint = self.HINTS.get(key, self._default_hint())
        if key=='睡觉' and self.pet.state in ('sleep','yawn'):
            hint = '轻轻叫醒，等她慢慢回过神'
        self.cv.itemconfigure(self.hint,text=reason or hint,fill=UI_GOLD if reason else UI_TEXT_DIM)

    def _sleep(self):
        if self.pet.state in ('sleep', 'yawn'):
            self.pet.wake_up()
        else:
            self.pet.go_sleep()

    def _run(self, action, key=None):
        if self.closed:
            return
        if key in self.disabled_reasons(self.pet):
            self._show_hint(key)
            return
        self.close()
        action()

    def _more(self):
        x, y = self.win.winfo_x()+int(18*self.u), self.win.winfo_y()+int(334*self.u)
        self.close()
        self.pet._show_full_menu(x, y)

    def _on_focus_out(self, event):
        if not self.closed and self._focus_id is None:
            self._focus_id = self.win.after_idle(self._check_focus)

    def _check_focus(self):
        self._focus_id = None
        if self.closed:
            return
        focused = self.win.focus_displayof()
        if focused is None or focused.winfo_toplevel() != self.win:
            self.close()

    def close(self):
        if self.closed:
            return
        self.closed = True
        # 自动聚焦的 250ms 定时器也要撤:卡片 250ms 内被关掉时(测试里很常见)
        # 它会对已销毁的窗口触发,Tcl 报 invalid command name
        for timer in (self._refresh_id, self._focus_id,
                      getattr(self, '_auto_focus_id', None)):
            if timer:
                self.win.after_cancel(timer)
        if getattr(self.pet, 'action_card', None) is self:
            self.pet.action_card = None
        self.win.destroy()
