# -*- coding: utf-8 -*-
"""tkinter 面板/对话框的配色与字号。pet.py 和独立出来的界面组件共用这一份。

只放常量和纯函数,不 import pet —— 组件模块从这里取主题,才不会和 pet.py
循环导入。
"""

# 原来 29 处 #RRGGBB 散在各处:同一个暗紫底被写成 #221C40 和 #1D1838 两份
# (复制粘贴出来的巧合),#EDE7FF 手打了 5 遍。这里收口成一套,顺便把那两个
# 近似色明确成"面板底 / 抬起面板"两档,原来的巧合变成有意的层次。
UI_BG       = "#1D1838"   # 面板底
UI_PANEL    = "#221C40"   # 抬起的面板、对话框底
UI_FIELD    = "#312A56"   # 输入框
UI_BTN      = "#3C3268"   # 次要按钮
UI_ACCENT   = "#7B5BD6"   # 主按钮 / 强调紫
UI_TEXT     = "#EDE7FF"   # 主文字
UI_TEXT_DIM = "#A99CD0"   # 次要文字
UI_TITLE    = "#E8DCFF"   # 标题
UI_WARN     = "#FFD98A"   # 校验提示
UI_GOLD     = "#FFE9A0"   # 主按钮文字
UI_DANGER   = "#FF9DB0"   # 关闭 / 危险
UI_BORDER   = "#695782"   # 卡片、记录区和输入框的统一描边

UI_FONT = "Microsoft YaHei UI"
TYPE_TITLE, TYPE_BODY, TYPE_BTN, TYPE_HINT = 15, 14, 13, 10


def ui_font(px, u=1.0, bold=False):
    """统一字号阶梯。px 取 TYPE_* 档位,u 是按屏幕高度换算的 DPI 系数。"""
    return (UI_FONT, -int(px * u)) + (("bold",) if bold else ())
