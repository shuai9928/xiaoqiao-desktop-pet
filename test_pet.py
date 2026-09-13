# -*- coding: utf-8 -*-
"""桌宠回归测试套件。改完代码跑一下,十几秒覆盖核心行为。

用法:
    py test_pet.py            # 跑全部断言,输出 PASS/FAIL 汇总
注意:
    会短暂在屏幕上创建一只测试小乔(约 20 秒),跑完自动关闭;
    会强制静音测试实例;会使用真实的 pet_settings.json 读取设置,
    但测试中产生的写盘行为集中在临时目录(除 rps 战绩等少量字段)。
覆盖:
    JSON 类型防线 / 指令通道竞态 / SFX 限频与开关 / 星光养成闭环 /
    被冷落撒娇 / 连摸彩蛋 / 久别重逢 / 猜拳加固 / 空中吃糖拒绝 /
    重力兜底 / say 文本归一化 / PS 转义
"""
import json
import os
import random
import sys
import tempfile
import time
from unittest.mock import patch

sys.argv = ["pet"]
import tkinter as tk

import pet
import agent


class FakeWin:
    def winfo_exists(self): return True
    def winfo_ismapped(self): return True


class FakeChat:
    win = FakeWin()
    def log_reply(self, t): pass
    def log_user(self, t): pass
    def log_hint(self, t): pass
    def focus_entry(self): pass
    def close(self): pass


RESULTS = []


def check(name, cond):
    """只记录,不中断。

    原来这里一失败就 raise,于是第一个 FAIL 之后所有用例都不跑了,
    拿不到文档承诺的那份汇总 —— 而回归测试最有价值的恰恰是
    "一次改动到底打破了几处"。
    """
    RESULTS.append(("PASS " if cond else "FAIL ") + name)


def main():
    root = tk.Tk()
    # 不 withdraw:重力/下落测试需要完整的 tick 渲染管线在跑
    p = pet.Pet(root)
    try:
        return _run(p, root)
    except Exception:                 # 用例自身抛异常(不是断言失败)
        import traceback
        RESULTS.append("ERROR " + traceback.format_exc().strip().splitlines()[-1])
        return _finish(p)


def _finish(p):
    bad = [r for r in RESULTS if not r.startswith("PASS")]
    print("\n".join(RESULTS))
    print(f"{len(RESULTS) - len(bad)}/{len(RESULTS)} 通过")
    try:
        p.sfx.close_all()
    except Exception:
        pass
    try:
        p.quit()          # 内部会销毁 root
    except Exception:
        pass
    return 1 if bad else 0


def _run(p, root=None):
    p.sfx.enabled = False          # 测试全程静音
    p.brain = None                 # 排除 AI 插话的不确定性

    # ---- 1. JSON 类型防线 ----
    d = tempfile.mkdtemp()
    bad = os.path.join(d, "x.json")
    json.dump(["x"], open(bad, "w", encoding="utf-8"))
    check("JSON: 类型不符用默认值", pet.Pet._load_json(p, bad, {}) == {})
    json.dump({"a": 1}, open(bad, "w", encoding="utf-8"))
    check("JSON: 正常内容不受影响", pet.Pet._load_json(p, bad, {}) == {"a": 1})

    # ---- 2. 指令通道竞态 ----
    p.cmd_path = os.path.join(d, "cmd.json")
    p._cmd_seen = 0.0
    seen = []
    p._exec_cmd = lambda c: seen.append(c)
    open(p.cmd_path, "w").close()          # 空文件(截断中间态)
    p._pump()
    check("指令: 空文件静默跳过", seen == [] and not getattr(p, "_cmd_err_mt", None))
    time.sleep(0.02)
    json.dump({"op": "pet"}, open(p.cmd_path, "w", encoding="utf-8"))
    p._pump()
    check("指令: 写完自动重试执行", seen == [{"op": "pet"}])
    time.sleep(0.02)
    open(p.cmd_path, "w").close()
    with open(p.cmd_path, "w", encoding="utf-8") as f:
        f.write("{bad")
    # 这里的 JSONDecodeError 是被测行为本身(同 mtime 只报一次),吞掉输出
    import io
    old_err, sys.stderr = sys.stderr, io.StringIO()
    try:
        p._pump()
    finally:
        sys.stderr = old_err
    check("指令: 损坏内容报一次", getattr(p, "_cmd_err_mt", None) is not None)

    # ---- 3. SFX 限频与开关 ----
    p.sfx.enabled = True
    p.sfx._next_any = 0.0
    p.sfx._next = {}
    p.sfx._chan = {}
    r1 = p.sfx.play("greet"); r2 = p.sfx.play("voice_happy")
    check("SFX: 5 秒全局限频", r1 is True and r2 is False)
    p._next_any = time.time() - 0.1
    p.sfx.enabled = False
    check("SFX: 总开关关闭", p.sfx.play("greet") is False)
    p.sfx.enabled = True

    # ---- 3.5 动画引擎:关键帧插值与时间轴 ----
    tr = pet.Pet._track
    check("引擎: 关键帧中点取值", tr(0.5, [(0, 0.0), (1.0, 1.0)]) == 0.5)
    check("引擎: 两端外延取端值",
          tr(-1.0, [(0, 2.0), (1, 4.0)]) == 2.0 and tr(9.0, [(0, 1.0), (1, 3.0)]) == 3.0)
    fired = []
    p._begin_tl({"squash": [(0, 1.0), (1.0, 2.0)]},
                [(0.1, lambda q: fired.append(1))])
    p._play_timeline(0.2, p._tl_tracks, p._tl_events, p._tl_done)
    p._play_timeline(0.2, p._tl_tracks, p._tl_events, p._tl_done)
    p._play_timeline(0.5, p._tl_tracks, p._tl_events, p._tl_done)
    check("引擎: 事件只触发一次且轨道写入属性",
          fired == [1] and p.squash == 1.5)
    p.squash = 1.0

    # ---- 3.6 帧率无关缓动 ----
    # 关键性质:30fps 下必须与老写法 `x += (target-x)*rate` 逐位相同,
    # 否则这次迁移就悄悄改掉了调了很久的手感。
    _same = True
    for _c in (0.06, 0.08, 0.10, 0.20, 0.3, 0.4, 0.45, 7 / 30.0):
        if abs(pet.approach(0.0, 1.0, _c, 1 / 30.0) - _c) > 1e-12:
            _same = False
    check("缓动: 30fps 下与老写法逐位等价", _same)
    check("缓动: dt 越大走得越远",
          pet.approach(0, 1, 0.06, 0.1) > pet.approach(0, 1, 0.06, 1 / 30.0))
    check("缓动: 长时间后收敛到目标", pet.approach(0, 1, 0.06, 10.0) > 0.999)
    check("缓动: 已在目标上就不动", pet.approach(5.0, 5.0, 0.3, 0.1) == 5.0)
    check("缓动: dt<=0 不动", pet.approach(2.0, 9.0, 0.3, 0.0) == 2.0)
    check("缓动: 任意 dt 都不过冲", 0.0 <= pet.approach(0, 1, 0.9, 5.0) <= 1.0)

    # ---- 3.7 光晕缓存:量化 + 真 LRU ----
    p.glow_cache.clear()
    for _r in range(8, 90):
        p.get_glow(_r, pet.WHITE, 120)
    check("光晕: 量化后条目数远少于半径种类数",
          len(p.glow_cache) <= 24 and len(p.glow_cache) <= pet.GLOW_CACHE_MAX)
    check("光晕: 相邻半径命中同一张",
          p.get_glow(20, pet.WHITE, 120) is p.get_glow(21, pet.WHITE, 120))
    p.glow_cache.clear()
    for _i in range(pet.GLOW_CACHE_MAX + 30):     # 用换色撑爆上限(建图便宜)
        p.get_glow(12, (_i, 60, 90), 120)
    check("光晕: 满了是淘汰最旧而不是整个清空",
          len(p.glow_cache) == pet.GLOW_CACHE_MAX)

    # ---- 3.85 加色光层 ----
    _sz = (64, 64)
    _g = p.get_glow(12, pet.WHITE, 120)
    _lay = pet.LightLayer(_sz)
    check("光层: 没画过东西时不脏", _lay.box is None)
    _lay.add(_g, 32, 32)
    _one = pet.Image.new("RGBA", _sz, (0, 0, 0, 0))
    _lay.flush(_one)
    check("光层: flush 之后脏矩形复位", _lay.box is None)
    # 关键性质 1:只有一团光时,结果必须与改动前的 alpha-over 逐位相同
    _ref = pet.Image.new("RGBA", _sz, (0, 0, 0, 0))
    _ref.paste(_g, (32 - _g.width // 2, 32 - _g.height // 2), _g)
    check("光层: 单独一团与老的 alpha-over 逐位相同",
          _one.tobytes() == _ref.tobytes())
    # 关键性质 2:重叠处必须真的更亮(这条一旦挂了就是退回 alpha-over 了)
    _lay2 = pet.LightLayer(_sz)
    _lay2.add(_g, 32, 32)
    _lay2.add(_g, 32, 32)
    _two = pet.Image.new("RGBA", _sz, (0, 0, 0, 0))
    _lay2.flush(_two)
    check("光层: 两团重叠比一团亮",
          sum(_two.getpixel((32, 32))[:3]) > sum(_one.getpixel((32, 32))[:3]))
    _lay3 = pet.LightLayer(_sz)
    _lay3.add(_g, -99, -99)
    check("光层: 完全越界不炸也不脏", _lay3.box is None)
    _lay3.add(_g, 2, 2)
    _lay3.flush(pet.Image.new("RGBA", _sz, (0, 0, 0, 0)))
    check("光层: 部分越界能正常裁剪", _lay3.box is None)

    # ---- 3.86 四档帧率 ----
    _save = (p.state, list(p.parts), p.bubble, p.sticker, p.drag, p._fast_ok,
             p.hop_t, p.lean_kick, p.blink_until, p._mouth, p.singing,
             p.last_interact, pet.cursor_pos)
    p.parts = []; p.bubble = None; p.sticker = None; p.drag = None
    p.circles = []; p.thinking_now = False
    p.hop_t = 0.0; p.lean_kick = 0.0; p.blink_until = 0.0
    p._mouth = None; p.singing = False
    p.last_interact = time.time()          # 刚互动过:压住安静待机档
    p._fast_ok = True
    p.state = "sleep"
    check("帧率: 睡着且完全静止降到 10fps", p._frame_delay() == 100)
    p.add_part("zzz", 0, 0, life=9.0)
    check("帧率: 只有 zzz 粒子仍然算静止", p._frame_delay() == 100)
    p.add_part("star", 0, 0, life=9.0)
    check("帧率: 睡着但有别的粒子回到 30fps", p._frame_delay() == 33)
    p.parts = []; p.state = "idle"
    check("帧率: 常规待机 30fps", p._frame_delay() == 33)
    # 安静待机:条件全清 + 光标桩到远处 -> 20fps;氛围粒子不算"在动"
    p.last_interact = time.time() - 99
    pet.cursor_pos = lambda: (-99999, -99999)
    check("帧率: 安静待机(光标远)降到 20fps", p._frame_delay() == 50)
    p.parts = [dict(kind="sparkle", x=0, y=0, vx=0, vy=-10, born=time.time(),
                    life=9.0, size=4, color=(255, 233, 160), phase=0.0,
                    spin=0.0, grav=0.0, txt=None)]
    check("帧率: 只有氛围粒子仍算安静", p._frame_delay() == 50)
    pet.cursor_pos = lambda: (p.x + p.W // 2, p.fy - p.H // 3)
    check("帧率: 光标靠近回到 30fps", p._frame_delay() == 33)
    pet.cursor_pos = lambda: (-99999, -99999)
    p.parts = [dict(kind="star", x=0, y=0, vx=60, vy=-90, born=time.time(),
                    life=9.0, size=6, color=(255, 255, 255), phase=0.0,
                    spin=3.0, grav=160.0, txt=None)]
    # 原来这里写的是 p.state = "casting",而真实状态名是 "magic",于是这条
    # 用例把"大招拿不到 60fps"验证成了"正确"。真正防住这一类的是下面
    # 11b 的状态名防线(从源码抽真实状态名做子集断言);这里只保留一条
    # 具体断言。
    # 不在这里调 cast_magic():实测它在整套用例的上下文里会偶发让解释器
    # 堆崩溃(0xC0000374,5 次复现 0 次,但确实崩过两次)。原因未查清,
    # 不能把一个偶发硬崩溃放进回归套件 —— 那会毁掉套件本身的可信度。
    p.state = "magic"
    check("帧率: 时间魔法给 60fps",
          p.state == "magic" and p._frame_delay() == 16)
    p.circles = []          # cast_magic 会压一个法阵进去,别漏给后面的用例
    p.state = "idle"
    check("帧率: 有演出粒子在飞给 60fps", p._frame_delay() == 16)
    p._fast_ok = False
    check("帧率: 机器画不动时退回 30fps", p._frame_delay() == 33)
    # 专注陪伴:她安静待着,而且陪伴演出只用氛围粒子 —— 所以这段时间
    # 反而比平时更容易落到 20fps 省电档。这条一旦挂了,多半是有人把
    # 陪伴特效换成了 heart/confetti(那会把档位顶到 60fps)。
    p._fast_ok = True
    p.parts = []; p.bubble = None; p.sticker = None
    p.last_interact = time.time() - 99
    pet.cursor_pos = lambda: (-99999, -99999)
    p.state = "idle"; p._micro_motion = None
    _t0 = time.time()
    p.pomo = {"phase": "focus", "due": _t0 + 1500, "mins": 25}
    check("帧率: 专注陪伴能落到 20fps 安静档", p._frame_delay() == 50)
    p._focus_next = 0.0; p._focus_half = False
    p._focus_tick(_t0)                    # 第一次只排期,不冒
    p._focus_tick(_t0 + 500)              # 过了间隔、但还没到"过半"那一下
    check("帧率: 陪伴星光不打破安静档",
          p.parts and all(q["kind"] in pet.AMBIENT_PARTS for q in p.parts)
          and not p._micro_motion and p._frame_delay() == 50)
    p.pomo = None; p.parts = []; p._micro_motion = None
    (p.state, p.parts, p.bubble, p.sticker, p.drag, p._fast_ok,
     p.hop_t, p.lean_kick, p.blink_until, p._mouth, p.singing,
     p.last_interact, pet.cursor_pos) = _save

    # ---- 3.8 粒子尾淡 ----
    check("尾淡: 前段不衰减", pet.tail_fade(0.5) == 1.0)
    check("尾淡: 末尾归零", pet.tail_fade(1.0) == 0.0)
    check("尾淡: 末段单调下降",
          pet.tail_fade(0.8) > pet.tail_fade(0.9) > 0.0)

    # ---- 4. 星光养成闭环 ----
    p.star = 10.0
    random.seed(3)                 # 固定种子,保证 idle 分支落在饥饿路径上
    random_fired = False
    for _ in range(12):
        p.state = "idle"; p.bubble = None; p._ai_cur_cd = time.time() + 9999
        p._idle_event(time.time())
        if p.bubble and p.bubble[0] in pet.HUNGRY_SAY:
            random_fired = True; break
    check("星光: 低星光说饥饿台词", random_fired)
    p.star = 25.0004; p.bubble = None; p.state = "idle"
    p.last = time.time() - 0.05
    p._tick_body()
    check("星光: 跌破 25% 主动提醒", p._star_warned and p.bubble
          and p.bubble[0] in pet.HUNGRY_SAY)
    p.star = 60.0; p._tick_body()
    check("星光: 充回复位", not p._star_warned)

    # ---- 5. 被冷落撒娇 ----
    # (75 秒无互动会先入睡,所以"清醒被冷落"要桩掉入睡才能单独测到)
    real_go_sleep = p.go_sleep
    p.go_sleep = lambda: None
    # 清醒撒娇必须在地面安静待机;前面的随机事件可能留下行走/落地位置。
    p.fy = p.ground_feet
    p.next_event = time.time() + 9999
    p.next_whine = 0.0; p.bubble = None; p.state = "idle"
    p.last_interact = time.time() - 2000
    p._tick_body()
    check("撒娇: 清醒时委屈台词", p.bubble and p.bubble[0] in pet.WHINE_LINES)
    p.go_sleep = real_go_sleep
    p.next_whine = 0.0; p.bubble = None; p.state = "sleep"
    p._tick_body()
    check("撒娇: 睡着时说梦话不醒", p.state == "sleep"
          and p.bubble and p.bubble[0] in pet.SLEEP_WHINE_LINES)

    # ---- 5b. 入睡前哈欠演出 ----
    p.wake_up(); p.state = "idle"; p.bubble = None
    # 上一段把 last_interact 拨到了 2000 秒前、next_whine 归零。不复位的话
    # 哈欠这 1.6 秒中途会撞上"被冷落撒娇"分支,状态被改回 idle,循环提前
    # 退出 —— 这条断言就会随机假失败,还连累后面依赖状态的用例。
    p.last_interact = time.time()
    p.next_whine = time.time() + 9999
    p.go_sleep()
    check("入睡: 先进 yawn 态", p.state == "yawn"
          and p.bubble and p.bubble[0] == "哈——啊……")
    # 预算给足:启动 2.5 秒后 _warm_fx 会在后台线程建大招精灵(~650ms 的
    # 纯 Python PIL,基本全程占着 GIL),和这段撞上时 1.6 秒的转场会被拖过
    # 3 秒 —— 这条断言会假失败,还会连累后面依赖状态的用例。
    end = time.time() + 8
    while time.time() < end and p.state == "yawn":
        root.update(); time.sleep(0.02)
    check("入睡: 1.6 秒后滑入睡眠", p.state == "sleep")
    p.wake_up(); p.state = "idle"

    # ---- 6. 连摸彩蛋 + 久别重逢 ----
    # 不让上一次测试保存的好感度跨过升级线,用升级气泡覆盖融化台词。
    p.affection = 0
    p._pet_combo = []
    p._pet_combo_cd = 0
    p.state = "idle"; p.bubble = None; p.last_interact = time.time()
    p.next_whine = time.time() + 9999
    # 禁用所有早返门(R98/怕痒/反手/R111)让 6 次都走默认路径累计 combo
    p._gift_cd = time.time() + 9999
    p._sneeze_cd = time.time() + 9999
    p._poke_cd = time.time() + 9999
    p._return_greeted = True  # 跳过 R101 迎回
    for _ in range(6):
        # 怕痒(8%)/抓手(2%)/反手戳(4%)这些概率门偶尔会打断 6 连摸,
        # 让这条用例随机假失败 —— 把随机数钉在 0.99 越过所有概率门。
        # 只影响直接掷骰:random.choice/randrange 走 getrandbits,不受影响。
        _rr = pet.random.random
        pet.random.random = lambda: 0.99
        try:
            p.pet_head()
        finally:
            pet.random.random = _rr
    check("彩蛋: 连摸 6 次融化", p.bubble and p.bubble[0] in pet.MELT_LINES
          and p._pet_combo == [])
    p.state = "sleep"; p.bubble = None
    p.last_interact = time.time() - 3600
    p.pet_head()
    check("彩蛋: 久别重逢台词", p.bubble and p.bubble[0] in pet.REUNION_LINES)

    # ---- 7. 猜拳加固 ----
    p.play_rps("剪刀")          # 非法值
    end = time.time() + 3
    while time.time() < end and p._rps_busy:
        root.update(); time.sleep(0.02)
    check("猜拳: 非法拳值不炸", not p._rps_busy and p.rps != [0, 0, 0])

    # ---- 7b. 猜数字小游戏 ----
    p.star = 50.0
    p.ask_ai("猜数字")
    check("猜数字: 开局", p._guess is not None and 1 <= p._guess["n"] <= 50)
    p._guess["n"] = 25                    # 固定答案便于断言
    p.ask_ai("30")
    check("猜数字: 大了提示", "太大" in p.bubble[0])
    p.ask_ai("20")
    check("猜数字: 小了提示", "太小" in p.bubble[0])
    star0 = p.star
    p.ask_ai("25")
    check("猜数字: 猜中奖励", p._guess is None and abs(p.star - (star0 + 5)) < 0.2)
    p.ask_ai("不玩了")
    check("猜数字: 空状态提示", "本来就没在玩" in p.bubble[0])

    # ---- 8. 空中吃糖拒绝 + 重力兜底 ----
    p.fy = p.ground_feet - 300; p.state = "fly"; p.vx = 0; p.vy = 0
    p.eat_candy()
    check("状态: 空中吃糖被拒绝", p.state == "fly"
          and p.bubble and "半空" in p.bubble[0])
    p.state = "idle"; p.last_interact = time.time()  # 防 R100 迎回抢气泡
    # 验证物理经过的时间,不把窗口渲染/机器负载算进六秒预算。
    # 只屏蔽绘制;仍推进完整状态机和原来的落地判定。
    born = p.last = time.time()
    with patch.object(p, 'render'):
        for step in range(1, 361):
            with patch.object(pet.time, 'time', return_value=born+step/60):
                p._tick_body()
            if p.fy >= p.ground_feet - 6:
                break
    p.last = time.time()
    check("状态: 重力兜底落回地面", p.fy >= p.ground_feet - 6)

    # ---- 9. say 归一化 + 换行 ----
    p.bubble = None
    p.say("你好\n\n世界\t测试")
    check("气泡: 空白归一化", p.bubble[0] == "你好 世界 测试")

    # ---- 9b. 气泡时长自适应 + 长文本夹取 ----
    p.bubble = None
    _t0 = time.time()
    p.say("短句")
    check("气泡: 短句仍是 2.5 秒左右", 2.2 <= p.bubble[1] - _t0 <= 3.0)
    p.bubble = None
    _t0 = time.time()
    p.say("很长的一句话" * 20)
    check("气泡: 长句时长拉长且封顶 14 秒", 6.0 < p.bubble[1] - _t0 <= 14.1)
    p.bubble = None
    _t0 = time.time()
    p.say("随便", 0.8)
    check("气泡: 显式 dur 优先", abs((p.bubble[1] - _t0) - 0.8) < 0.1)
    _lines, _lh, _tw = p._bubble_layout("很长的话" * 200, p.f_bubble, 2)
    check("气泡: 长文本行数被夹在窗口内",
          _lh * len(_lines) + 14 * 2 <= p.H * 0.42 * 2 + _lh)
    check("气泡: 截断后以省略号收尾", _lines[-1].endswith("…"))
    check("气泡: 短文本不被截断",
          p._bubble_layout("短", p.f_bubble, 2)[0] == ["短"])

    # ---- 9b2. 主题对话框能构建(把阻塞那步打桩掉)----
    # 这几个是从菜单里点出来的,构建时抛异常就是"点了没反应" —— 正是
    # R115 那一类事故。wait_window 打桩成立即销毁,只验证搭建不炸。
    _real_wait = root.wait_window
    root.wait_window = lambda w: w.destroy()
    _dlg = True
    try:
        p.themed_input("t", "问点什么", initial="x")
        p.themed_input("t", "带校验", validate=lambda s: None)
        p.themed_confirm("t", "确认点什么")
    except Exception as _e:
        _dlg = f"{type(_e).__name__}: {_e}"
    finally:
        root.wait_window = _real_wait
    check(f"对话框: themed_input/confirm 能构建 {'' if _dlg is True else _dlg}",
          _dlg is True)

    # ---- 9c. 日期解析(原来 anniv/birthday 各抄了一份)----
    _cases = [("09-15", (9, 15)), ("9/15", (9, 15)), ("3月5日", (3, 5)),
              ("3月5号", (3, 5)), (" 12-31 ", (12, 31)), ("2-29", (2, 29)),
              ("1.1", (1, 1)),
              ("13-01", None), ("2-31", None), ("4-31", None), ("0-5", None),
              ("9-0", None), ("", None), (None, None), ("abc", None),
              ("9-15-2", None), ("915", None)]
    _wrong = [(s, pet.parse_mmdd(s), want) for s, want in _cases
              if pet.parse_mmdd(s) != want]
    check(f"日期: 四种写法与各种非法输入 {_wrong or ''}", not _wrong)

    # ---- 10. PS 转义 ----
    # R19 后匹配走 Where-Object -eq(字面),只需转义单引号
    check("agent: 单引号转义", agent._ps_name("it's") == "it''s")

    # ---- 10b. 渲染冒烟:每个状态都跑一帧完整 tick+render ----
    # _tick_body 的状态分发和 render 的粒子分发加起来近 700 行 if/elif,
    # 原来一条都没被覆盖过 —— 而这次改动正好同时动了这两条链。
    # 先把渲染路径上的可选元素都填上,否则这些分支一条都跑不到 ——
    # fx.shockwave 少传一个 frame 参数(每次落地都炸)就是这么漏出去的。
    p.land_fx(0.8)
    p.say("冒烟测试")
    p.play_emotion("happy", 4.0)
    for _kind in ("heart", "magic_burst", "magic_corner", "ball", "sparkle",
                  "star", "cstar", "bub", "meteor", "petal", "fw", "sweat",
                  "firefly", "leaf", "snow", "confetti", "zzz", "note"):
        p.add_part(_kind, 0, -40, vy=-20, life=4.0, size=8, txt="♪")
    _bad = []
    for _st in ("idle", "walk", "sleep", "yawn", "fly", "fall", "dance",
                "magic", "tstop", "rewind", "chase", "dizzy", "fall_stand",
                "eat", "twirl", "flip", "roll", "wave", "peek",
                "stretch", "transform", "sneeze", "drag"):
        p.state = _st
        p.state_until = time.time() + 5
        p.last = time.time() - 0.033
        try:
            p._tick_body()
        except Exception as _e:
            _bad.append(f"{_st}:{type(_e).__name__}:{_e}")
    check(f"渲染: 各状态跑一帧都不抛异常 {_bad or ''}", not _bad)
    # 睡眠帧(10fps)也要能跑 —— 这是 dts 那条路径
    p.state = "sleep"; p.last = time.time() - 0.1
    try:
        p._tick_body()
        _ok10 = True
    except Exception:
        _ok10 = False
    check("渲染: 10fps 睡眠帧不抛异常", _ok10)
    p.state = "idle"; p.wake_up()

    # ---- 11. 属性初始化防线 ----
    # 这一条是为 R115 那次事故加的:_magic_style_var 没初始化 -> 右键菜单
    # 整个打不开;magic_style 没初始化 -> save_settings 在 open("w") 之后
    # 才抛异常,pet_settings.json 被清成 0 字节。两个都是"读了没赋值"。
    import ast as _ast
    _src = open(os.path.join(os.path.dirname(pet.__file__), "pet.py"),
                encoding="utf-8").read()
    _tree = _ast.parse(_src)
    _cls = [c for c in _tree.body
            if isinstance(c, _ast.ClassDef) and c.name == "Pet"][0]
    missing = {}
    # _build_menu 必须在列表里:R115 那次事故就是菜单构造里读了没初始化的
    # 变量。上个 commit 把构造从 on_menu 拆进了 _build_menu,这条防线正好
    # 落空在变量所在的地方 —— 补回来。互动/后台的入口方法也一并盯住。
    for _fn in ("on_menu", "_build_menu", "save_settings", "_idle_event",
                "render", "_tick_body", "_draw_sticker", "pet_head",
                "tickle_body", "on_drag", "on_enter", "wake_up", "go_sleep",
                "_apply_ai", "_exec_cmd", "_finish_agent",
                "focus_mode", "_focus_tick"):
        _node = [n for n in _cls.body
                 if isinstance(n, _ast.FunctionDef) and n.name == _fn]
        if not _node:
            continue
        for _n in _ast.walk(_node[0]):
            if (isinstance(_n, _ast.Attribute)
                    and getattr(_n.value, "id", None) == "self"
                    and isinstance(_n.ctx, _ast.Load)
                    and not hasattr(p, _n.attr)):
                missing.setdefault(_fn, set()).add(_n.attr)
    check(f"属性: 关键方法读到的 self.* 全部存在 {missing or ''}", not missing)

    # ---- 11b. 状态名 / 粒子名防线 ----
    # FAST_STATES 里曾经写着一个根本不存在的 "casting"(真名 "magic"),
    # 于是旗舰的时间魔法从来没吃到 60fps 档;而旧用例也是手工
    # p.state = "casting" 再断言,刚好把这个错误一起验证成了"正确"。
    # 改成从源码里抽出所有 self.state = "字面量",任何状态集合都必须是
    # 它的子集 —— 打错一个字母立刻 FAIL,单双引号也都覆盖得到。
    _states = set()
    for _n in _ast.walk(_tree):
        if (isinstance(_n, _ast.Assign) and isinstance(_n.value, _ast.Constant)
                and isinstance(_n.value.value, str)):
            for _t in _n.targets:
                if (isinstance(_t, _ast.Attribute) and _t.attr == "state"
                        and getattr(_t.value, "id", None) == "self"):
                    _states.add(_n.value.value)
    check(f"状态名: 抽到的真实状态数合理({len(_states)})", len(_states) >= 20)
    _ghost = pet.FAST_STATES - _states
    check(f"状态名: FAST_STATES 全是真状态 {sorted(_ghost) or ''}", not _ghost)
    check("状态名: 时间魔法(magic)在 60fps 档", "magic" in pet.FAST_STATES)

    # 同一类隐患:AMBIENT_PARTS 写错 kind 名不会报错,只会让那种粒子
    # 悄悄把待机顶到 60fps。从 add_part 的第一个实参抽真实 kind 名。
    _kinds = set()
    for _n in _ast.walk(_tree):
        if (isinstance(_n, _ast.Call)
                and getattr(_n.func, "attr", "") == "add_part"
                and _n.args and isinstance(_n.args[0], _ast.Constant)
                and isinstance(_n.args[0].value, str)):
            _kinds.add(_n.args[0].value)
    _ghost_p = pet.AMBIENT_PARTS - _kinds
    check(f"粒子名: AMBIENT_PARTS 全是真 kind {sorted(_ghost_p) or ''}", not _ghost_p)

    # ---- 12. 存档不会被清空 ----
    _cfg = pet.CONFIG_FILE
    p.save_settings()
    _ok = os.path.exists(_cfg) and os.path.getsize(_cfg) > 2
    check("存档: save_settings 写出了非空文件", _ok)
    if _ok:
        try:
            _data = json.load(open(_cfg, encoding="utf-8"))
        except Exception:
            _data = None
        check("存档: 内容是合法 JSON 且含关键字段",
              isinstance(_data, dict) and "first_day" in _data and "x" in _data)
    check("存档: 没有残留 .tmp", not os.path.exists(_cfg + ".tmp"))
    # 白名单之外、散在 settings 里的键(纪念日/生日/里程碑去重)也必须
    # 跟着回盘 —— 曾经只写白名单,这几个功能重启即丢
    p.settings["anniv_date"] = "12-25"
    p.settings["anniv_name"] = "测试纪念日"
    p.settings["birthday"] = "01-01"
    p.settings["milestone_day"] = "2026-01-01"
    p.save_settings()
    try:
        _data2 = json.load(open(_cfg, encoding="utf-8"))
    except Exception:
        _data2 = None
    check("存档: 零散键(纪念日/生日/里程碑)能落盘",
          isinstance(_data2, dict) and _data2.get("anniv_date") == "12-25"
          and _data2.get("anniv_name") == "测试纪念日"
          and _data2.get("birthday") == "01-01"
          and _data2.get("milestone_day") == "2026-01-01")
    for _k in ("anniv_date", "anniv_name", "birthday", "milestone_day"):
        p.settings.pop(_k, None)
    p.save_settings()

    # ---- 12b. 番茄钟状态落盘 ----
    # 曾经计时器只活在内存里:重启(含看门狗自愈重启)静默丢计时,
    # 到点永不提醒 —— 和"一次性提醒落盘不丢"的待遇不一致。
    p.start_pomodoro(25)
    try:
        _data3 = json.load(open(_cfg, encoding="utf-8"))
    except Exception:
        _data3 = None
    check("存档: 番茄钟状态随 start_pomodoro 落盘",
          isinstance(_data3, dict) and isinstance(_data3.get("pomo"), dict)
          and _data3["pomo"].get("phase") == "focus"
          and isinstance(_data3["pomo"].get("due"), float))
    p.stop_pomodoro()           # 收尾:清掉计时,落盘同步清掉

    # ---- 13. AI 密钥 DPAPI 加密往返(含中文,密文不得是明文) ----
    # 落盘迁移用真配置在无头链路里验过;这里只钉住加解密原语本身。
    import ai_chat as _aic
    if os.name == "nt":
        _enc = _aic._dpapi_protect("AIza-test-密钥-123")
        check("AI: DPAPI 加密往返且落盘非明文",
              _enc is not None and _enc != "AIza-test-密钥-123"
              and _aic._dpapi_unprotect(_enc) == "AIza-test-密钥-123")
        check("AI: 解不开的密文安全返回空",
              _aic._dpapi_unprotect("garbage-not-base64!!") is None)

    # ---- 14. 长期记忆抽取覆盖(用临时记忆文件,不碰真实数据) ----
    # "我叫小明""我是程序员""我住在上海"这些最自然的话曾全部漏记。
    _mem_path = "_tmp_mem_check.json"
    if os.path.exists(_mem_path):
        os.remove(_mem_path)
    _mem = _aic.MemoryStore(_mem_path)
    _keep = ["我叫小明", "叫我阿乔就好", "我是程序员", "我是一名产品经理",
             "我住在上海", "我家在北京", "我今年25岁", "我养了只猫",
             "我周末喜欢爬山", "我在写爬虫", "我不会Python",
             "以后记住我喜欢深色主题", "我的项目是网关服务"]
    _skip = ["我是真的喜欢你", "我们喜欢聚餐", "我是说真的",
             "我的password是123", "今天天气不错", "帮我打开微信"]
    _missed = [t for t in _keep if not _mem.add_from_text(t)]
    _wrong = [t for t in _skip if _mem.add_from_text(t)]
    if _mem.add_from_text("我叫小明"):
        _wrong.append("我叫小明(重复入册)")
    check(f"记忆: 自然语句抽取 {len(_keep) - len(_missed)}/{len(_keep)} {_missed or ''}",
          not _missed)
    check(f"记忆: 起手句/我们/密码/闲聊不误记 {_wrong or ''}", not _wrong)
    check("记忆: 相对路径落盘", os.path.exists(_mem_path))
    # 检索端:自然问法要能召回(曾经整句匹配等于永远匹配不上)
    _rq = [("我那只猫今天喂了吗", "我养了只猫"),
           ("爬虫跑起来了吗", "我在写爬虫"),
           ("我周末爬山回来好累", "我周末喜欢爬山"),
           ("我叫什么名字", "我叫小明")]
    _bad_rq = [q for q, want in _rq if want not in _mem.relevant(q, 2)]
    check(f"记忆: 自然问法检索召回 {len(_rq) - len(_bad_rq)}/{len(_rq)} {_bad_rq or ''}",
          not _bad_rq)
    check("记忆: 无关话题不硬塞记忆",
          "我在写爬虫" not in _mem.relevant("今天天气怎么样", 2))
    if os.path.exists(_mem_path):
        os.remove(_mem_path)

    return _finish(p)


if __name__ == "__main__":
    sys.exit(main())
