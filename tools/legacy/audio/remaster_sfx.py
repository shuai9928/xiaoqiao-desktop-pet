# -*- coding: utf-8 -*-
"""把 assets/audio 的音效从「峰值归一化」重制为「响度归一化」。

背景:素材现在几乎全是晓晓 TTS 的短句(只有 magic_1~6 还是 CC0 音效),
生成脚本按峰值 -9 dBFS 对齐。峰值齐不代表听起来一样响 ——
同样峰值下,实测响度差 7.6 dB(wake_2 -14.4 / bye_2 -22.0),
听感上就是有的句子明显冲、有的偏轻。

这里改用带时间积分的响度:取 200ms 滑动窗内的最大能量。
选 200ms 是因为人耳对短促声音的响度感知本来就偏低(时域整合),
用它当指标,tick 这种 40ms 的爆音会被自动多推几个 dB 才算「一样响」。

处理顺序:高频衰减 -> 首尾淡入淡出 -> 响度归一 -> 峰值上限 -> TPDF 抖动。

用法:
    python remaster_sfx.py           # 只生成 assets/audio_v2,不动原文件
    python remaster_sfx.py --apply   # 原目录备份为 audio_peaknorm_backup 后替换
"""
import math
import os
import shutil
import sys
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "assets", "audio")
DST = os.path.join(HERE, "..", "assets", "audio_v2")
BAK = os.path.join(HERE, "..", "assets", "audio_peaknorm_backup")

SR = 44100
WIN = int(0.2 * SR)          # 响度积分窗

# 目标响度(本脚本的 200ms 积分口径,不是 LUFS)。
# 组间关系刻意保留 prep_sfx.py 的意图:她的声音在最前,魔法当背景层,
# UI 音垫在下面 —— 但差距从原来的 14 dB 收到 9 dB,免得提醒音被淹掉。
# 目标响度(本脚本的 200ms 积分口径,不是 LUFS)。
# 说话声全部归一到同一个电平 —— 她们本来就是同一个人的同一把嗓子,
# 按用途分高低反而会像忽远忽近。魔法音是施法语音底下的背景层,
# 压到比说话低 5.5dB,让"魔法发动!"那句能清楚浮在上面。
TARGET = {"speech": -19.5, "magic": -25.0}
# 峰值上限:留余量,施法时"语音 + 魔法闪烁"两层叠放不会顶满。
CEILING = {"speech": -5.0, "magic": -10.0}

# 高频搁架:原来 bye_1/2 是 Kenney 的嘶声,74% 能量在 8kHz 以上,需要压。
# 现在它们已经换成晓晓的"拜拜~",不能再滤,否则会把人声压闷。留空。
SHELF = {}
SHELF_LO, SHELF_HI = 6000.0, 12000.0

FADE_IN_MS = 3.0
FADE_OUT_MS = 8.0
EDGE_THRESH_DB = -60.0       # 首尾采样点高于这个电平就认为会「咔」一下


def db(v):
    return 20 * math.log10(v) if v > 1e-12 else -99.0


def group(name):
    # magic_1~6 是 CC0 魔法闪烁音效;其余 42 个全是晓晓 TTS 的说话声。
    return "magic" if name.startswith("magic_") else "speech"


def read_wav(path):
    with wave.open(path, "rb") as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2, path
        n, sr = w.getnframes(), w.getframerate()
        x = np.frombuffer(w.readframes(n), dtype=np.int16)
    return x.astype(np.float64) / 32768.0, sr


def write_wav(path, x, sr):
    # TPDF 抖动:两个独立均匀分布之和,幅度 1 LSB,压掉 16bit 量化的谐波失真
    d = (np.random.random(len(x)) - np.random.random(len(x))) / 32768.0
    y = np.clip(x + d, -1.0, 32767 / 32768)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(np.round(y * 32768.0).astype("<i2").tobytes())


def loudness(x):
    """200ms 窗内最大能量,dB。文件短于窗长时分母仍用窗长,短音因此被判定为更轻。"""
    e = x * x
    if len(e) <= WIN:
        return 10 * math.log10(max(e.sum() / WIN, 1e-12))
    c = np.concatenate(([0.0], np.cumsum(e)))
    return 10 * math.log10(max(((c[WIN:] - c[:-WIN]) / WIN).max(), 1e-12))


def hf_shelf(x, sr, cut_db):
    """零相位高频搁架:6kHz 以下不动,12kHz 以上衰减 cut_db,中间余弦过渡。"""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1.0 / sr)
    g = np.ones_like(f)
    mid = (f > SHELF_LO) & (f < SHELF_HI)
    t = (f[mid] - SHELF_LO) / (SHELF_HI - SHELF_LO)
    lin = 10 ** (cut_db / 20.0)
    g[mid] = 1.0 + (lin - 1.0) * (1 - np.cos(np.pi * t)) / 2
    g[f >= SHELF_HI] = lin
    return np.fft.irfft(X * g, n=len(x))


def apply_fades(x, sr):
    """首尾不是从静音开始/结束的,加短淡入淡出消掉爆音。返回 (x, 做了什么)。"""
    done = []
    if len(x) < 64:
        return x, done
    if db(abs(x[0])) > EDGE_THRESH_DB:
        n = min(int(FADE_IN_MS * sr / 1000), len(x) // 4)
        if n > 1:
            x[:n] *= (1 - np.cos(np.linspace(0, np.pi, n))) / 2
            done.append("fade-in")
    if db(abs(x[-1])) > EDGE_THRESH_DB:
        n = min(int(FADE_OUT_MS * sr / 1000), len(x) // 4)
        if n > 1:
            x[-n:] *= (1 + np.cos(np.linspace(0, np.pi, n))) / 2
            done.append("fade-out")
    return x, done


def main():
    apply = "--apply" in sys.argv
    src = os.path.normpath(SRC)
    dst = os.path.normpath(DST)
    os.makedirs(dst, exist_ok=True)
    np.random.seed(20260906)          # 抖动噪声也可复现

    names = sorted(f for f in os.listdir(src) if f.lower().endswith(".wav"))
    before, after = {}, {}
    print(f"{'file':22}{'grp':>6}{'loud→':>16}{'gain':>8}{'peak':>8}  notes")
    for fn in names:
        name = os.path.splitext(fn)[0]
        g = group(name)
        x, sr = read_wav(os.path.join(src, fn))
        l0 = loudness(x)
        notes = []

        if name in SHELF:
            x = hf_shelf(x, sr, SHELF[name])
            notes.append(f"shelf{SHELF[name]:+.0f}dB")

        x, fades = apply_fades(x, sr)
        notes += fades

        gain = TARGET[g] - loudness(x)
        x = x * (10 ** (gain / 20.0))

        pk = np.abs(x).max()
        ceil = 10 ** (CEILING[g] / 20.0)
        if pk > ceil:
            x *= ceil / pk
            short = TARGET[g] - loudness(x)
            notes.append(f"峰值封顶(还差{short:.1f}dB)")
            gain += db(ceil / pk)

        write_wav(os.path.join(dst, fn), x, sr)
        l1 = loudness(x)
        before.setdefault(g, []).append(l0)
        after.setdefault(g, []).append(l1)
        print(f"{name:22}{g:>6}{l0:8.1f}→{l1:6.1f}{gain:>8.1f}"
              f"{db(np.abs(x).max()):>8.1f}  {', '.join(notes)}")

    print()
    for g in ("speech", "magic"):
        b, a = before[g], after[g]
        print(f"{g:>6}  组内响度差  {max(b)-min(b):5.1f} dB  ->  {max(a)-min(a):5.1f} dB")

    for extra in ("CREDITS.md",):
        p = os.path.join(src, extra)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(dst, extra))

    print(f"\n输出目录: {dst}")
    if apply:
        if os.path.exists(BAK):
            print("备份目录已存在,先自行处理:", os.path.normpath(BAK))
            return
        shutil.move(src, os.path.normpath(BAK))
        shutil.move(dst, src)
        print("已替换。原文件备份在:", os.path.normpath(BAK))
    else:
        print("原文件未改动。听过没问题后跑 --apply 替换。")


if __name__ == "__main__":
    main()
